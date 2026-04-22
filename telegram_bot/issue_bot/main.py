"""이슈 봇 메인 루프 — Phase 1 MVP

주기적 실행:
1. 보호 구간/KILL_SWITCH 체크 → 차단 시 스킵
2. DART 공시 수집 → seen_ids로 신규만 필터
3. 필터(Haiku) → 우선순위 분류
4. State 1 원문 카드 발송 (Sonnet 생성 X → 비용 0)
5. 관리자가 버튼 클릭 시 poller가 처리

별도 스레드:
- run_poller() 백그라운드 → 콜백 + 수정 답장 수신

통합:
- telegram_bot/main.py APScheduler에 이 모듈의 `issue_bot_poll_once`를 15분 cron으로 등록
- 별도 프로세스 테스트: `python -m telegram_bot.issue_bot.main`
"""
import os
import sys
import time
import threading
import datetime

from telegram_bot.config import ISSUE_BOT_ENABLED, ISSUE_BOT_POLL_INTERVAL_MIN

# admin 카드 발송 최소 priority (기본 HIGH — NORMAL 은 로그만)
# env: ISSUE_BOT_ADMIN_MIN_PRIORITY = URGENT|HIGH|NORMAL
_PRIORITY_RANK = {"URGENT": 3, "HIGH": 2, "NORMAL": 1, "SKIP": 0}
_ADMIN_MIN = _PRIORITY_RANK.get(
    os.environ.get("ISSUE_BOT_ADMIN_MIN_PRIORITY", "HIGH").upper(),
    2,  # HIGH
)
from telegram_bot.issue_bot.collectors.dart_collector import collect_disclosures
from telegram_bot.issue_bot.pipeline.filter import filter_event
from telegram_bot.issue_bot.pipeline.dedup import (
    generate_dedup_key,
    is_duplicate,
    mark_seen,
)
from telegram_bot.issue_bot.approval.bot import send_raw_approval_card
from telegram_bot.issue_bot.approval.poller import run_poller
from telegram_bot.issue_bot.utils.telegram import is_issue_bot_blocked


def issue_bot_poll_once(fetch_body: bool = True, days_back: int = 1) -> dict:
    """
    1회 폴링 실행: DART → 필터 → State 1 카드 발송.
    외부 스케줄러(APScheduler)가 이 함수를 주기 호출.

    Returns:
        {"collected": N, "new": N, "cards_sent": N, "skipped_blocked": bool}
    """
    if not ISSUE_BOT_ENABLED:
        return {"collected": 0, "new": 0, "cards_sent": 0, "skipped_reason": "ISSUE_BOT_ENABLED=false"}

    blocked, reason = is_issue_bot_blocked()
    if blocked:
        print(f"[ISSUE_BOT] 스킵: {reason}")
        return {"collected": 0, "new": 0, "cards_sent": 0, "skipped_reason": reason}

    print(f"[ISSUE_BOT] 폴링 시작 ({datetime.datetime.now().isoformat(timespec='seconds')})")

    # 1. DART 수집
    try:
        events = collect_disclosures(days_back=days_back, fetch_body=fetch_body)
    except Exception as e:
        print(f"[ISSUE_BOT] DART 수집 실패: {e}")
        return {"collected": 0, "new": 0, "cards_sent": 0, "error": str(e)}

    print(f"[ISSUE_BOT] DART 수집: {len(events)}건 (SKIP 제외)")

    new_count = 0
    sent_count = 0

    for event in events:
        # 2. dedup
        dedup_key = generate_dedup_key(event)
        if is_duplicate(dedup_key):
            continue
        new_count += 1

        # 3. 필터 (DART는 rule-based 매칭 되면 Haiku 스킵)
        try:
            classification = filter_event(event)
        except Exception as e:
            print(f"[ISSUE_BOT] 필터 오류 ({event['id']}): {e}")
            continue

        pri = classification.get("priority", "NORMAL")
        if pri == "SKIP":
            mark_seen(dedup_key, source_url=event.get("source_url", ""), role="skipped")
            continue

        # admin 발송 최소 priority 체크 (기본 HIGH — NORMAL 은 로그만, 카드 발송 안 함)
        if _PRIORITY_RANK.get(pri, 0) < _ADMIN_MIN:
            mark_seen(dedup_key, source_url=event.get("source_url", ""), role="below_min_priority",
                      extra={"priority": pri, "title": event.get("title", "")[:60]})
            print(f"  [below min] {pri} | {event.get('company_name', '')[:15]} | {event.get('title', '')[:40]}")
            continue

        # 4. State 1 카드 발송 준비
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
                          extra={"issue_id": event["id"]})
                print(f"  [card sent] {classification['priority']} | {event['company_name'][:15]} | {event['title'][:40]}")
            else:
                print(f"  [card fail] {event['id']}: {result.get('error')}")
        except Exception as e:
            print(f"[ISSUE_BOT] 카드 발송 오류 ({event['id']}): {e}")

        # rate limit
        time.sleep(1)

    print(f"[ISSUE_BOT] 폴링 완료 — 신규 {new_count}건, 카드 {sent_count}건 발송")
    return {
        "collected": len(events),
        "new": new_count,
        "cards_sent": sent_count,
    }


def run_standalone():
    """독립 프로세스 실행 (테스트/개발용).
    - poller를 백그라운드 스레드로 돌림
    - 메인 스레드에서 interval_min 마다 폴링
    """
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
        # 1회만 폴링 (cron 테스트용)
        result = issue_bot_poll_once()
        print(f"\n결과: {result}")
    else:
        run_standalone()
