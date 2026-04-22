"""Claude.ai 웹 챗 테스트용 팩 생성기

API 비용 없이 Claude.ai 유료 구독(Sonnet 4.5)으로 필터 품질 테스트.

사용:
  python scripts/export_claude_testpack.py              # 기본 30건
  python scripts/export_claude_testpack.py --max 50
  python scripts/export_claude_testpack.py --only-dart  # DART만
  python scripts/export_claude_testpack.py --only-rss   # RSS만

출력:
  scripts/claude_ai_testpack.txt — 이 파일을 열어서 전체 복사 → Claude.ai 붙여넣기 → 결과 받기
"""
import os
import sys
import argparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from telegram_bot.issue_bot.collectors.dart_collector import (
    fetch_recent_disclosures, classify_by_rules,
)
from telegram_bot.issue_bot.pipeline.filter import FILTER_SYSTEM


def collect_events(max_events=30, only_dart=False, only_rss=False):
    events = []
    if not only_rss:
        print("[수집] DART...")
        raw = fetch_recent_disclosures(days_back=1, page_count=100)
        for item in raw:
            cls = classify_by_rules(item.get("report_nm", ""))
            # rule-SKIP은 제외 (이미 확정된 건)
            if cls and cls.get("priority") == "SKIP":
                continue
            events.append({
                "source": "DART",
                "company": item.get("corp_name", ""),
                "title": item.get("report_nm", "").strip(),
                "body": "",
                "rule_hint": cls.get("priority") if cls else "UNMATCHED",
            })
            if len(events) >= max_events // 2:
                break

    if not only_dart:
        print("[수집] RSS...")
        try:
            from telegram_bot.issue_bot.collectors.rss_adapter import collect_rss_events
            rss = collect_rss_events(limit=max_events, fetch_images=False)
        except Exception as e:
            print(f"RSS 수집 실패(일부 스킵): {e}")
            rss = []
        for ev in rss:
            events.append({
                "source": "RSS",
                "company": ev["company_name"],
                "title": ev["title"],
                "body": ev.get("body_excerpt", "")[:400],
                "rule_hint": None,
            })
            if len(events) >= max_events:
                break
    return events[:max_events]


def make_testpack(events, output_path):
    lines = []
    lines.append("=" * 80)
    lines.append("NODE Research 이슈봇 — Claude.ai 웹 챗 필터 품질 테스트 팩")
    lines.append("=" * 80)
    lines.append("")
    lines.append("[사용 방법]")
    lines.append("1. 이 파일 전체 복사")
    lines.append("2. Claude.ai (claude.ai) 새 대화 열기 → 붙여넣기 → 전송")
    lines.append("3. Claude가 각 이벤트를 JSON으로 분류해서 돌려줌")
    lines.append("4. 결과를 다시 봇에게 공유하면 Haiku 결과와 비교 분석 가능")
    lines.append("")
    lines.append("=" * 80)
    lines.append("[시스템 프롬프트 — Claude에 주입할 필터 규칙]")
    lines.append("=" * 80)
    lines.append("")
    lines.append("당신은 아래 규칙대로 필터 판단을 합니다.")
    lines.append("")
    lines.append(FILTER_SYSTEM)
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"[분류할 이벤트 — 총 {len(events)}건]")
    lines.append("=" * 80)
    lines.append("")
    lines.append("아래 각 이벤트를 1번부터 순서대로 위 규칙에 따라 분류해주세요.")
    lines.append("결과는 하나의 JSON 배열로 출력:")
    lines.append('[{"no": 1, "priority": "...", "sector": "...", "category": "...", "significance": "...", "reason": "..."}, ...]')
    lines.append("")

    for i, ev in enumerate(events, 1):
        lines.append(f"--- [{i}] ---")
        lines.append(f"소스: {ev['source']}")
        lines.append(f"기업/주체: {ev['company']}")
        lines.append(f"제목: {ev['title']}")
        if ev.get("body"):
            lines.append(f"본문 발췌:")
            lines.append(ev["body"])
        if ev.get("rule_hint"):
            lines.append(f"(참고: rule 힌트 = {ev['rule_hint']})")
        lines.append("")

    lines.append("=" * 80)
    lines.append("위 전체를 JSON 배열 하나로 분류해서 답해주세요.")
    lines.append("=" * 80)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=30)
    parser.add_argument("--only-dart", action="store_true")
    parser.add_argument("--only-rss", action="store_true")
    parser.add_argument("--out", default=os.path.join(_PROJECT_ROOT, "scripts", "claude_ai_testpack.txt"))
    args = parser.parse_args()

    events = collect_events(max_events=args.max, only_dart=args.only_dart, only_rss=args.only_rss)
    print(f"\n수집된 이벤트: {len(events)}건 (DART {sum(1 for e in events if e['source']=='DART')}, RSS {sum(1 for e in events if e['source']=='RSS')})")

    make_testpack(events, args.out)
    print(f"\n✓ 생성 완료: {args.out}")
    print(f"  파일 크기: {os.path.getsize(args.out):,} bytes")
    print(f"\n[다음 단계]")
    print(f"  1. notepad 또는 VS Code로 파일 열기")
    print(f"  2. Ctrl+A → Ctrl+C (전체 복사)")
    print(f"  3. claude.ai 새 대화 → Ctrl+V → 전송")
    print(f"  4. 결과를 봇에게 공유하면 비교 분석")
