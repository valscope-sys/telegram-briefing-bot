"""NODE Research 실시간 이슈 봇 — Phase 1 MVP

메리츠 Tech 채널 스타일로 DART 공시 + RSS 뉴스를 요약하여
관리자 승인 후 @noderesearch 채널에 발송.

모듈 구조:
- collectors/: 소스 데이터 수집 (DART, RSS)
- pipeline/: 필터/중복감지/생성/린트
- approval/: 승인 카드 발송/폴링/수정/명령
- utils/: 텔레그램 래퍼, 시간 보호 구간, KILL_SWITCH

상세 스펙: ISSUE_BOT_SPEC.md
"""
__version__ = "0.1.0"
