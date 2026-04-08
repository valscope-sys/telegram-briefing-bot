"""시장 컨텍스트 관리 — 저장된 컨텍스트 + 한지영 최신 크롤링"""
import os
import datetime
import requests
from bs4 import BeautifulSoup

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history", "market_context.txt")


def _fetch_latest_analyst_comment():
    """한지영 채널에서 가장 최근 코멘트 1개만 가져오기 (크롤링)"""
    try:
        url = "https://t.me/s/hedgecat0301"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return ""

        soup = BeautifulSoup(res.text, "lxml")
        messages = soup.select(".tgme_widget_message_text")

        # 마지막 메시지 (가장 최신)
        if messages:
            latest = messages[-1].get_text(strip=True)
            if len(latest) > 200:  # 의미 있는 코멘트만
                return latest[:2000]
        return ""
    except Exception:
        return ""


def get_market_context_for_prompt():
    """저장된 컨텍스트 + 한지영 최신 코멘트를 프롬프트용으로 반환"""
    parts = []

    # 1. 저장된 시장 컨텍스트
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                context = f.read().strip()
            if context:
                parts.append(f"=== 현재 시장 컨텍스트 ===\n{context[:2000]}")
        except Exception:
            pass

    # 2. 한지영 최신 코멘트 (매일 크롤링)
    analyst = _fetch_latest_analyst_comment()
    if analyst:
        parts.append(f"=== 증권사 애널리스트 최신 코멘트 (참고용, 복사 금지) ===\n{analyst}")

    return "\n\n".join(parts)


def update_market_context(new_commentary, market_data=None):
    """시황 생성 후 컨텍스트 업데이트"""
    if not new_commentary:
        return

    from telegram_bot.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        return

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
- 기존 구조(지정학/매크로/섹터/수급/밸류에이션/시장국면)를 유지
- 오늘 새로 확인된 사실만 반영
- 이미 해결된 이슈는 제거
- 전체 2000자 이내

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
