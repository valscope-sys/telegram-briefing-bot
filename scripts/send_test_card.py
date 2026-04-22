"""테스트용 승인 카드를 관리자 DM으로 발송.

사용: python scripts/send_test_card.py

실제 파이프라인(send_raw_approval_card)을 거쳐 DM에 카드가 도달.
관리자가 미리보기 → 발송 / 스킵 / 수정 모두 테스트 가능.

주의: 본 스크립트는 로컬·서버 어디서든 실행 가능하나,
     TELEGRAM_BOT_TOKEN + TELEGRAM_ADMIN_CHAT_ID가 .env에 있어야 함.
"""
import os
import sys
import datetime

# scripts/에서 실행 시 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from telegram_bot.issue_bot.approval.bot import send_raw_approval_card


# 어제(2026-04-21) 전후의 실제 업계 맥락을 반영한 테스트 이벤트
# (TSMC는 통상 4월 중순~하순에 1분기 실적 발표 — Peer 시사점 큼)
TEST_EVENT = {
    "id": f"test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_tsmc",
    "priority": "HIGH",
    "sector": "반도체",
    "category": "C",
    "source": "RSS (TEST)",
    "source_url": "https://pr.tsmc.com/english/news/financial-results",
    "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "ticker": "TSM",
    "company_name": "TSMC",
    "corp_code": "",
    "corp_cls": "",
    "title": "[TEST 카드] TSMC 1Q26 실적 — AI·HBM 첨단공정 수요 지속",
    "report_nm_raw": "1Q26 Earnings",
    "body_excerpt": (
        "※ 본 메시지는 이슈봇 파이프라인 점검용 테스트 카드입니다 (실제 확인된 수치는 원문 참조).\n\n"
        "TSMC가 1분기 실적을 발표했습니다. AI 가속기용 첨단공정(5nm/3nm) 수요 지속, "
        "HBM 관련 파운드리 매출 비중 확대. 2026년 연간 매출 가이던스 기존 전망 유지. "
        "선단공정 설비투자(Capex) 계획은 가이던스 하단에 근접한 수준으로 조정.\n\n"
        "한국 메모리(삼성전자·SK하이닉스) 관점: HBM 고성장 지속 시사, "
        "파운드리 영역에서 TSMC의 공급 병목은 국내 HBM 물량 인도 스케줄과 연동."
    ),
    "original_content": "",
    "original_excerpt": "",
    "generated_content": None,
    "has_generated": False,
    "peer_map_used": ["SK하이닉스", "삼성전자"],
    "peer_confidence": 0.85,
    "category_hint": "C",
    "priority_hint": "HIGH",
    "rule_match_reason": "TEST 카드 (수동 투입)",
    "event_type": "TEST",
    "date": datetime.date.today().strftime("%Y-%m-%d"),
}
TEST_EVENT["original_content"] = TEST_EVENT["body_excerpt"]
TEST_EVENT["original_excerpt"] = TEST_EVENT["body_excerpt"][:500]


def main():
    print("=" * 70)
    print("테스트 카드 발송 — 관리자 DM")
    print("=" * 70)
    print(f"issue_id: {TEST_EVENT['id']}")
    print(f"priority: {TEST_EVENT['priority']} / sector: {TEST_EVENT['sector']} / template: {TEST_EVENT['category']}")
    print(f"제목: {TEST_EVENT['title']}")
    print()

    result = send_raw_approval_card(TEST_EVENT)
    if result.get("ok"):
        print(f"✅ 발송 성공!")
        print(f"   admin_msg_id: {result.get('admin_msg_id')}")
        print(f"   expires_at:   {result.get('expires_at')}")
        print(f"   status:       {result.get('status')}")
        print()
        print("👉 텔레그램 @noderesearch_bot DM을 확인하세요.")
        print("   미리보기 → 발송 / 스킵 / 수정 버튼으로 전 기능 테스트 가능.")
    else:
        print(f"❌ 발송 실패: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
