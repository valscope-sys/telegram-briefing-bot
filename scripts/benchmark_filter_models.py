"""필터 모델 비교 벤치마크 — Haiku vs Sonnet vs Hybrid

동일한 이벤트 세트를 3가지 필터 전략으로 돌려 결과 비교.
서버 배포 전 로컬에서 품질·비용 차이 체감용.

사용:
  python scripts/benchmark_filter_models.py
  python scripts/benchmark_filter_models.py --max 30       # 30건만 테스트
  python scripts/benchmark_filter_models.py --save results.json

출력:
- 모델별 priority 분포
- 일치/불일치 건수
- 불일치 샘플 상세 (누가 뭘 다르게 판정했는가)
- 비용 요약
"""
import os
import sys
import json
import time
import argparse
import re
from collections import Counter

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import anthropic
from telegram_bot.config import ANTHROPIC_API_KEY
from telegram_bot.issue_bot.pipeline.filter import FILTER_SYSTEM, _parse_filter_json
from telegram_bot.issue_bot.collectors.dart_collector import (
    fetch_recent_disclosures, classify_by_rules, _normalize_report_nm,
)
from telegram_bot.issue_bot.collectors.rss_adapter import collect_rss_events


HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-5"

PRICING = {
    HAIKU_MODEL: {"input": 1, "output": 5},       # $/MTok
    SONNET_MODEL: {"input": 3, "output": 15},
}


def _client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _make_user_msg(event: dict) -> str:
    source = event.get("source", "?")
    title = event.get("title", "")[:200]
    company = event.get("company_name", "")
    body = event.get("body_excerpt") or event.get("original_content", "") or ""
    body = body[:1000]
    return f"""[소스] {source}
[기업/주체] {company}
[제목] {title}
[본문 요약]
{body}

이 이벤트를 분류해주세요. JSON만."""


def call_model(event: dict, model: str) -> dict:
    """단일 모델 호출. 결과와 토큰 리턴."""
    client = _client()
    user_msg = _make_user_msg(event)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=FILTER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        parsed = _parse_filter_json(text)
        if not parsed:
            return {"error": "json parse fail", "raw": text[:200], "tokens_in": 0, "tokens_out": 0}
        parsed["tokens_in"] = resp.usage.input_tokens
        parsed["tokens_out"] = resp.usage.output_tokens
        return parsed
    except Exception as e:
        return {"error": str(e), "tokens_in": 0, "tokens_out": 0}


def cost_of(tokens_in: int, tokens_out: int, model: str) -> float:
    p = PRICING[model]
    return tokens_in * p["input"] / 1_000_000 + tokens_out * p["output"] / 1_000_000


def collect_test_events(max_events: int = 40, dart_days: int = 1, rss_limit: int = 20):
    """테스트용 이벤트 수집. rule-SKIP 패턴은 제외 (이미 확실한 SKIP은 모델 판정 불필요)."""
    print("[수집] DART ...")
    raw_dart = fetch_recent_disclosures(days_back=dart_days, page_count=100)
    events = []
    for item in raw_dart:
        report_nm_raw = item.get("report_nm", "")
        cls = classify_by_rules(report_nm_raw)
        # rule SKIP은 제외 (명확한 SKIP이라 모델 비교에 의미 없음)
        if cls and cls.get("priority") == "SKIP":
            continue
        # rule 매칭된 URGENT/HIGH/NORMAL도 제외 (이미 확정, 모델 판정 불필요)
        if cls and cls.get("priority") in ("URGENT", "HIGH", "NORMAL"):
            # 일부는 포함해서 모델이 동일 판정하는지 sanity check
            if len(events) >= max_events // 3:
                continue
        rcept_dt = item.get("rcept_dt", "")
        events.append({
            "id": f"dart_{item.get('rcept_no', '')}",
            "source": "DART",
            "company_name": item.get("corp_name", ""),
            "title": report_nm_raw.strip(),
            "body_excerpt": "",
            "rule_hint": cls.get("priority") if cls else None,
            "ticker": item.get("stock_code", ""),
        })
        if len(events) >= max_events // 2:
            break

    print("[수집] RSS ...")
    rss_events = collect_rss_events(limit=rss_limit, fetch_images=False)
    for ev in rss_events:
        events.append({
            "id": ev["id"],
            "source": "RSS",
            "company_name": ev["company_name"],
            "title": ev["title"],
            "body_excerpt": ev.get("body_excerpt", "")[:500],
            "rule_hint": None,
            "ticker": None,
        })
        if len(events) >= max_events:
            break

    return events[:max_events]


def hybrid_decision(haiku_result, sonnet_result_fn):
    """Hybrid: Haiku가 SKIP/URGENT 판정이면 그대로, 나머지(애매한 HIGH/NORMAL)는 Sonnet 재판정."""
    if haiku_result.get("error"):
        return sonnet_result_fn()  # Haiku 실패면 Sonnet으로
    p = haiku_result.get("priority")
    if p == "SKIP":
        return {"decision": "haiku", "result": haiku_result}
    if p == "URGENT":
        return {"decision": "haiku", "result": haiku_result}
    # HIGH/NORMAL은 Sonnet으로 재판정 (애매함 많은 구간)
    sonnet_result = sonnet_result_fn()
    return {"decision": "sonnet", "result": sonnet_result, "haiku_was": haiku_result}


def run_benchmark(events: list):
    print(f"\n{'='*90}")
    print(f"모델 벤치마크 — 테스트 이벤트 {len(events)}건")
    print('='*90)

    haiku_results = []
    sonnet_results = []
    hybrid_results = []
    tokens_haiku_in = tokens_haiku_out = 0
    tokens_sonnet_in = tokens_sonnet_out = 0
    hybrid_sonnet_calls = 0

    for i, ev in enumerate(events, 1):
        sys.stdout.write(f"\r[{i}/{len(events)}] {ev['company_name'][:12]:<12} | {ev['title'][:40]:<40}")
        sys.stdout.flush()

        # Haiku
        h = call_model(ev, HAIKU_MODEL)
        tokens_haiku_in += h.get("tokens_in", 0)
        tokens_haiku_out += h.get("tokens_out", 0)
        haiku_results.append(h)

        # Sonnet
        s = call_model(ev, SONNET_MODEL)
        tokens_sonnet_in += s.get("tokens_in", 0)
        tokens_sonnet_out += s.get("tokens_out", 0)
        sonnet_results.append(s)

        # Hybrid (Haiku가 SKIP/URGENT면 그대로, 아니면 Sonnet 재판정 — Sonnet 이미 호출했으니 재사용)
        if h.get("priority") in ("SKIP", "URGENT") or h.get("error"):
            hybrid_results.append({"decision": "haiku", "result": h})
        else:
            hybrid_results.append({"decision": "sonnet", "result": s})
            hybrid_sonnet_calls += 1

    print("\n")

    # ===== 분포 =====
    def tally(results):
        c = Counter()
        for r in results:
            data = r.get("result") if "result" in r else r
            p = data.get("priority", "ERROR") if not data.get("error") else "ERROR"
            c[p] += 1
        return c

    h_tally = tally(haiku_results)
    s_tally = tally(sonnet_results)
    hybrid_tally = tally(hybrid_results)

    print(f"{'Priority':<12} {'Haiku':>8} {'Sonnet':>8} {'Hybrid':>8}")
    print("-" * 40)
    for p in ("URGENT", "HIGH", "NORMAL", "SKIP", "ERROR"):
        print(f"{p:<12} {h_tally.get(p, 0):>8} {s_tally.get(p, 0):>8} {hybrid_tally.get(p, 0):>8}")

    # ===== 일치/불일치 =====
    agree = 0
    disagree = []
    for i, (h, s) in enumerate(zip(haiku_results, sonnet_results)):
        if h.get("error") or s.get("error"):
            continue
        hp = h.get("priority")
        sp = s.get("priority")
        if hp == sp:
            agree += 1
        else:
            disagree.append((i, events[i], h, s))

    print(f"\n일치: {agree}/{len(events)}건 ({agree/len(events)*100:.1f}%)")
    print(f"불일치: {len(disagree)}건")

    # ===== 불일치 샘플 (상위 15) =====
    print(f"\n{'='*90}")
    print("[불일치 상세 — Haiku vs Sonnet]")
    print('='*90)
    for i, ev, h, s in disagree[:15]:
        print(f"\n• [{ev['source']}] {ev['company_name'][:15]} | {ev['title'][:60]}")
        print(f"    Haiku : {h.get('priority', '?'):<8} ({h.get('sector', '?')}) — {h.get('significance', h.get('reason', ''))[:70]}")
        print(f"    Sonnet: {s.get('priority', '?'):<8} ({s.get('sector', '?')}) — {s.get('significance', s.get('reason', ''))[:70]}")

    if len(disagree) > 15:
        print(f"\n... 외 {len(disagree) - 15}건 불일치")

    # ===== 통과 건수 (SKIP 제외) =====
    def not_skip(results):
        n = 0
        for r in results:
            data = r.get("result") if "result" in r else r
            if data.get("priority") and data["priority"] != "SKIP" and not data.get("error"):
                n += 1
        return n

    print(f"\n{'='*90}")
    print("[통과 건수 (SKIP 제외 = 승인 카드 발송 후보)]")
    print('='*90)
    print(f"  Haiku  통과: {not_skip(haiku_results)}/{len(events)}건")
    print(f"  Sonnet 통과: {not_skip(sonnet_results)}/{len(events)}건")
    print(f"  Hybrid 통과: {not_skip(hybrid_results)}/{len(events)}건 (Sonnet 재판정 {hybrid_sonnet_calls}건)")

    # ===== 비용 =====
    cost_haiku_only = cost_of(tokens_haiku_in, tokens_haiku_out, HAIKU_MODEL)
    cost_sonnet_only = cost_of(tokens_sonnet_in, tokens_sonnet_out, SONNET_MODEL)

    # Hybrid: Haiku 전부 + Sonnet은 hybrid_sonnet_calls 건만
    # (단순화: Haiku 토큰 / 전체 × full 비용 + Sonnet 토큰 / 전체 × 비율)
    hybrid_sonnet_ratio = hybrid_sonnet_calls / len(events) if events else 0
    cost_hybrid = cost_haiku_only + cost_sonnet_only * hybrid_sonnet_ratio

    print(f"\n{'='*90}")
    print(f"[비용 (테스트 {len(events)}건 기준)]")
    print('='*90)
    print(f"  Haiku only : ${cost_haiku_only:.4f}  (tokens in={tokens_haiku_in:,}, out={tokens_haiku_out:,})")
    print(f"  Sonnet only: ${cost_sonnet_only:.4f}  (tokens in={tokens_sonnet_in:,}, out={tokens_sonnet_out:,})")
    print(f"  Hybrid     : ${cost_hybrid:.4f}  (Haiku 100% + Sonnet {hybrid_sonnet_ratio*100:.0f}%)")

    # 월 환산 (하루 100건 가정)
    scale_daily = 100 / len(events) if events else 0
    scale_monthly = scale_daily * 30
    print(f"\n  월 환산 (하루 100건 가정):")
    print(f"    Haiku only : ${cost_haiku_only * scale_monthly:.2f}/월")
    print(f"    Sonnet only: ${cost_sonnet_only * scale_monthly:.2f}/월")
    print(f"    Hybrid     : ${cost_hybrid * scale_monthly:.2f}/월")

    return {
        "events_count": len(events),
        "haiku_tally": dict(h_tally),
        "sonnet_tally": dict(s_tally),
        "hybrid_tally": dict(hybrid_tally),
        "agreement": agree / len(events) if events else 0,
        "disagreements": len(disagree),
        "hybrid_sonnet_calls": hybrid_sonnet_calls,
        "cost": {
            "haiku_only": cost_haiku_only,
            "sonnet_only": cost_sonnet_only,
            "hybrid": cost_hybrid,
        },
        "monthly_estimate": {
            "haiku_only": cost_haiku_only * scale_monthly,
            "sonnet_only": cost_sonnet_only * scale_monthly,
            "hybrid": cost_hybrid * scale_monthly,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=40, help="테스트 이벤트 수 (기본 40)")
    parser.add_argument("--dart-days", type=int, default=1, help="DART 몇 일치 (기본 1)")
    parser.add_argument("--rss", type=int, default=20, help="RSS 몇 건 (기본 20)")
    parser.add_argument("--save", help="결과 JSON 저장 경로")
    args = parser.parse_args()

    print(f"테스트 이벤트 수집 중...")
    events = collect_test_events(max_events=args.max, dart_days=args.dart_days, rss_limit=args.rss)
    print(f"수집 완료: {len(events)}건 (DART {sum(1 for e in events if e['source']=='DART')}, RSS {sum(1 for e in events if e['source']=='RSS')})")
    print(f"\n예상 호출: Haiku {len(events)}회 + Sonnet {len(events)}회 = 총 {len(events)*2}회")
    print(f"예상 비용: ~$0.05 (Haiku) + ~$0.50 (Sonnet) = ~$0.55 전후")
    print()

    result = run_benchmark(events)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {args.save}")
