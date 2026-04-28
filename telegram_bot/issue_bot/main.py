"""이슈 봇 메인 루프 — Phase 1 MVP

주기적 실행:
1. 보호 구간/KILL_SWITCH 체크 → 차단 시 스킵
2. DART 공시 수집 (rcept_no 증분 커서 기반) + RSS 수집
3. 필터 (rule → Haiku → Sonnet 재검증 하이브리드)
4. State 1 원문 카드 발송 (최대 N건 제한)
5. 관리자 버튼 클릭 시 poller가 처리

별도 스레드:
- run_poller() 백그라운드 → 콜백 + 수정 답장 수신
"""
import os
import sys
import gc
import time
import threading
import datetime

from itertools import zip_longest

from telegram_bot.config import (
    ISSUE_BOT_ENABLED,
    ISSUE_BOT_POLL_INTERVAL_MIN,
    ISSUE_BOT_MAX_CARDS_PER_POLL,
)

# admin 카드 발송 최소 priority (기본 HIGH — NORMAL은 로그만, 카드 발송 안 함)
_PRIORITY_RANK = {"URGENT": 3, "HIGH": 2, "NORMAL": 1, "SKIP": 0}
_ADMIN_MIN = _PRIORITY_RANK.get(
    os.environ.get("ISSUE_BOT_ADMIN_MIN_PRIORITY", "HIGH").upper(),
    2,  # HIGH
)

from telegram_bot.issue_bot.collectors.dart_collector import (
    collect_disclosures, get_last_rcept_no, save_last_rcept_no,
)
from telegram_bot.issue_bot.collectors.rss_adapter import collect_rss_events
from telegram_bot.issue_bot.collectors.sec_collector import collect_sec_8k_filings
from telegram_bot.issue_bot.pipeline.filter import filter_event, get_filter_metrics
from telegram_bot.issue_bot.pipeline.dedup import (
    generate_dedup_key, is_duplicate, mark_seen, find_recent_duplicates,
)
from telegram_bot.issue_bot.approval.bot import send_raw_approval_card
from telegram_bot.issue_bot.approval.poller import run_poller
from telegram_bot.issue_bot.utils.telegram import is_issue_bot_blocked


def issue_bot_poll_once(fetch_body: bool = True, days_back: int = 1,
                        max_cards_per_poll: int = None, include_rss: bool = True,
                        include_sec: bool = True) -> dict:
    """
    1회 폴링: DART(증분) + RSS + SEC 8-K → 필터 → 카드 발송 (최대 N건).

    Args:
        fetch_body: KIND HTML 본문 추출 여부
        days_back: DART 조회 범위 (증분 커서와 교차 필터링됨)
        max_cards_per_poll: 카드 상한. None이면 config.ISSUE_BOT_MAX_CARDS_PER_POLL
            (기본 10) 사용. 나머지는 다음 폴링으로 이월.
            2026-04-25 기본 3 → 10 상향: 잠정실적 시즌 DART 슬롯 독점으로
            RSS·SEC이 영원히 deferred 되는 버그 대응.
        include_rss: RSS 수집 포함 여부
        include_sec: SEC EDGAR 8-K 수집 포함 여부 (빅테크 Peer)

    Returns:
        {"collected", "new", "cards_sent", "deferred", "last_rcept_no", ...}
    """
    if max_cards_per_poll is None:
        max_cards_per_poll = ISSUE_BOT_MAX_CARDS_PER_POLL

    if not ISSUE_BOT_ENABLED:
        return {"collected": 0, "new": 0, "cards_sent": 0, "skipped_reason": "ISSUE_BOT_ENABLED=false"}

    blocked, reason = is_issue_bot_blocked()
    if blocked:
        print(f"[ISSUE_BOT] 스킵: {reason}")
        return {"collected": 0, "new": 0, "cards_sent": 0, "skipped_reason": reason}

    print(f"[ISSUE_BOT] 폴링 시작 ({datetime.datetime.now().isoformat(timespec='seconds')}, max_cards={max_cards_per_poll})")

    # 1. DART 수집 (증분 커서 기반, 첫 실행 시 최근 10건만)
    try:
        dart_events = collect_disclosures(
            days_back=days_back, fetch_body=fetch_body,
            incremental=True, first_run_limit=10,
        )
    except Exception as e:
        print(f"[ISSUE_BOT] DART 수집 실패: {e}")
        dart_events = []
    print(f"[ISSUE_BOT] DART 수집: {len(dart_events)}건 (rule SKIP 제외)")

    # 2. RSS 수집 (기존 news_collector 재활용)
    rss_events = []
    if include_rss:
        try:
            rss_events = collect_rss_events(limit=50, fetch_images=False)
        except Exception as e:
            print(f"[ISSUE_BOT] RSS 수집 실패: {e}")
        print(f"[ISSUE_BOT] RSS 수집: {len(rss_events)}건")

    # 3. SEC 8-K 수집 (빅테크 + 반도체 Peer — Phase 2)
    sec_events = []
    if include_sec:
        try:
            sec_events = collect_sec_8k_filings(per_cik_limit=5, days_back=2)
        except Exception as e:
            print(f"[ISSUE_BOT] SEC 수집 실패: {e}")
        print(f"[ISSUE_BOT] SEC 8-K 수집: {len(sec_events)}건")

    # 2026-04-25 인터리빙: DART/RSS/SEC를 라운드 로빈으로 섞음.
    # 기존 단순 concat 방식은 DART가 항상 앞에 와서 max_cards 상한 도달 시
    # RSS·SEC이 영원히 deferred 되는 버그. 인터리빙으로 source별 균등 발송 보장.
    # 예: [DART1, RSS1, SEC1, DART2, RSS2, SEC2, DART3, RSS3, ...]
    events = [
        e for triplet in zip_longest(dart_events, rss_events, sec_events)
        for e in triplet if e is not None
    ]

    new_count = 0
    sent_count = 0
    deferred_count = 0
    current_max_rcept_no = get_last_rcept_no()

    for event in events:
        # 카드 상한 도달 → 나머지 이월 (DART는 커서 갱신 X, 다음 폴링에서 다시 조회)
        if sent_count >= max_cards_per_poll:
            deferred_count += 1
            continue

        rcept_no = event.get("source_id", "") if event.get("source") == "DART" else ""

        # 2-1. dedup (정확 일치)
        dedup_key = generate_dedup_key(event)
        if is_duplicate(dedup_key):
            if rcept_no and rcept_no > current_max_rcept_no:
                current_max_rcept_no = rcept_no
            continue

        # 2-2. 클러스터 dedup + 권위 소스 우선 (DART/SEC > RSS)
        # 정책: 같은 이벤트라면 공시(DART/SEC)를 우선. RSS는 공시 이미 있으면 secondary.
        # 공시가 RSS 이후에 들어와도 primary로 발송 (공시가 더 권위 있음).
        recent = find_recent_duplicates(dedup_key, hours=6)
        src = event.get("source", "")
        authoritative_sources = {"DART", "SEC"}
        current_is_authoritative = src in authoritative_sources

        authoritative_primary_exists = any(
            r.get("role") == "primary" and r.get("source") in authoritative_sources
            for r in recent
        )
        non_auth_primary_exists = any(
            r.get("role") == "primary" and r.get("source") not in authoritative_sources
            for r in recent
        )

        should_skip_as_secondary = False
        if authoritative_primary_exists:
            # 공시 primary 이미 발송됨 → 현재 건(뭐든) secondary
            should_skip_as_secondary = True
        elif not current_is_authoritative and non_auth_primary_exists:
            # 현재 RSS, 이전 RSS primary 있음 → secondary (일반 cluster dedup)
            should_skip_as_secondary = True
        # 현재 DART/SEC이고 이전 RSS primary만 있음 → 그대로 진행 (공시가 우선)

        if should_skip_as_secondary:
            mark_seen(dedup_key, source_url=event.get("source_url", ""), role="secondary",
                      extra={"title": event.get("title", "")[:80], "source": src})
            if rcept_no and rcept_no > current_max_rcept_no:
                current_max_rcept_no = rcept_no
            print(f"  [cluster dup] {src} | {event.get('company_name','')[:15]} | {event.get('title','')[:50]}")
            continue

        new_count += 1

        # 3. 필터
        try:
            classification = filter_event(event)
        except Exception as e:
            print(f"[ISSUE_BOT] 필터 오류 ({event['id']}): {e}")
            continue

        pri = classification.get("priority", "NORMAL")

        if pri == "SKIP":
            mark_seen(dedup_key, source_url=event.get("source_url", ""), role="skipped",
                      extra={"source": src})
            if rcept_no and rcept_no > current_max_rcept_no:
                current_max_rcept_no = rcept_no
            continue

        # admin 발송 최소 priority 체크 (기본 HIGH)
        if _PRIORITY_RANK.get(pri, 0) < _ADMIN_MIN:
            mark_seen(dedup_key, source_url=event.get("source_url", ""), role="below_min_priority",
                      extra={"priority": pri, "title": event.get("title", "")[:60], "source": src})
            if rcept_no and rcept_no > current_max_rcept_no:
                current_max_rcept_no = rcept_no
            print(f"  [below min] {pri} | {event.get('company_name', '')[:15]} | {event.get('title', '')[:40]}")
            continue

        # 4. State 1 카드 발송
        original_body = event.get("body_excerpt") or ""
        issue = {
            **event,
            **classification,
            "dedup_key": dedup_key,
            "original_content": original_body,
            "original_excerpt": original_body[:500] if original_body else event.get("title", ""),
            "generated_content": None,
            "has_generated": False,
            "peer_map_used": [],
        }

        try:
            result = send_raw_approval_card(issue)
            if result.get("ok"):
                sent_count += 1
                mark_seen(dedup_key, source_url=event.get("source_url", ""), role="primary",
                          extra={"issue_id": event["id"], "source": src})
                if rcept_no and rcept_no > current_max_rcept_no:
                    current_max_rcept_no = rcept_no
                print(f"  [card sent {sent_count}/{max_cards_per_poll}] {pri} | {event['source']} | {event['company_name'][:15]} | {event['title'][:40]}")
            else:
                print(f"  [card fail] {event['id']}: {result.get('error')}")
        except Exception as e:
            print(f"[ISSUE_BOT] 카드 발송 오류 ({event['id']}): {e}")

        time.sleep(1)  # rate limit

    # 증분 커서 저장 (처리 완료한 DART 이벤트까지)
    if current_max_rcept_no and current_max_rcept_no != get_last_rcept_no():
        save_last_rcept_no(current_max_rcept_no)
        print(f"[ISSUE_BOT] last_rcept_no 갱신 → {current_max_rcept_no}")

    msg = f"[ISSUE_BOT] 폴링 완료 — 신규 {new_count}, 카드 {sent_count}"
    if deferred_count > 0:
        msg += f", 이월 {deferred_count}건 (상한 도달)"
    print(msg)

    # 비용 메트릭 출력 (누적치, 프로세스 시작 이후)
    m = get_filter_metrics()
    haiku_total_input = m["haiku_input_uncached"] + m["haiku_cache_read"] + m["haiku_cache_create"]
    cache_hit_pct = (100 * m["haiku_cache_read"] / haiku_total_input) if haiku_total_input else 0
    print(
        f"[FILTER_METRICS 누적] pre_skip={m['pre_filter_skip']} "
        f"haiku={m['haiku_calls']} sonnet={m['sonnet_calls']} "
        f"haiku_cache_hit={cache_hit_pct:.1f}% "
        f"(read={m['haiku_cache_read']:,} / uncached={m['haiku_input_uncached']:,})"
    )

    result = {
        "collected": len(events),
        "dart": len(dart_events),
        "rss": len(rss_events),
        "sec": len(sec_events),
        "new": new_count,
        "cards_sent": sent_count,
        "deferred": deferred_count,
        "last_rcept_no": current_max_rcept_no,
    }

    # 메모리 정리 — 512MB 서버에서 fwupd 등과 경쟁. 매 폴링 후 순환 참조 수거.
    del events, dart_events, rss_events, sec_events
    gc.collect()

    return result


def run_standalone():
    """독립 프로세스 실행 (테스트/개발용)."""
    if not ISSUE_BOT_ENABLED:
        print("[ISSUE_BOT] ISSUE_BOT_ENABLED=false — 종료")
        return

    print("=" * 60)
    print("NODE Research 이슈 봇 (standalone)")
    print(f"폴링 주기: {ISSUE_BOT_POLL_INTERVAL_MIN}분")
    print("=" * 60)

    stop_event = threading.Event()
    poller_thread = threading.Thread(target=run_poller, args=(stop_event,), daemon=True)
    poller_thread.start()

    try:
        while True:
            issue_bot_poll_once()
            time.sleep(ISSUE_BOT_POLL_INTERVAL_MIN * 60)
    except (KeyboardInterrupt, SystemExit):
        print("\n[ISSUE_BOT] 종료 신호 수신")
        stop_event.set()
        poller_thread.join(timeout=30)
        print("[ISSUE_BOT] 종료 완료")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if len(sys.argv) > 1 and sys.argv[1] == "once":
        result = issue_bot_poll_once()
        print(f"\n결과: {result}")
    else:
        run_standalone()
