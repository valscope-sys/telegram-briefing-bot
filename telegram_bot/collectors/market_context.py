"""시장 컨텍스트 관리 — 초기 학습 + 자동 업데이트"""
import os
import json
import datetime

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history", "market_context.txt")


def get_market_context_for_prompt():
    """저장된 시장 컨텍스트를 프롬프트에 삽입할 텍스트로 반환"""
    if not os.path.exists(CONTEXT_FILE):
        return ""

    try:
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            context = f.read()

        if not context.strip():
            return ""

        # 최대 3000자만 사용 (토큰 절약)
        return f"=== 현재 시장 컨텍스트 ===\n{context[:3000]}"
    except Exception:
        return ""


def update_market_context(new_commentary, market_data=None):
    """시황 생성 후 컨텍스트 업데이트"""
    if not new_commentary:
        return

    from telegram_bot.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        return

    # 기존 컨텍스트 읽기
    existing = ""
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            pass

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = datetime.date.today().strftime("%Y-%m-%d")

    prompt = f"""기존 시장 컨텍스트와 오늘 시황을 기반으로 컨텍스트를 업데이트해주세요.

[기존 컨텍스트]
{existing[:2000]}

[오늘 시황 ({today})]
{new_commentary[:1500]}

업데이트 규칙:
- 기존 컨텍스트의 구조(지정학/매크로/섹터/수급/밸류에이션/시장국면)를 유지
- 오늘 새로 확인된 사실만 반영 (날짜, 수치 업데이트)
- 이미 해결된 이슈는 제거 (예: 전쟁 끝났으면 전쟁 관련 삭제)
- 새로운 이슈가 등장했으면 추가
- 전체 2000자 이내로 간결하게

업데이트된 컨텍스트만 작성하세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        updated = response.content[0].text.strip()

        with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception:
        pass
