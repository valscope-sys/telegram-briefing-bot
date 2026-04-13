"""시장 컨텍스트 관리 — 저장된 컨텍스트 + 한지영 최신 크롤링"""
import os
import datetime
import requests
from bs4 import BeautifulSoup

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history", "market_context.txt")
ANALYST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history", "analyst_raw.txt")


def _fetch_latest_analyst_comment():
    """한지영 채널에서 모든 새 코멘트를 누적 저장하고, 최신 1건을 반환"""
    try:
        url = "https://t.me/s/hedgecat0301"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return ""

        soup = BeautifulSoup(res.text, "lxml")
        messages = soup.select(".tgme_widget_message_text")

        latest_text = ""
        for msg in messages:
            text = msg.get_text(strip=True)
            if len(text) > 200:
                _save_analyst_comment(text)
                latest_text = text

        return latest_text[:2000] if latest_text else ""
    except Exception:
        return ""


def _save_analyst_comment(comment):
    """한지영 코멘트를 analyst_raw.txt에 누적 저장 (중복 방지)"""
    try:
        existing = ""
        if os.path.exists(ANALYST_FILE):
            with open(ANALYST_FILE, "r", encoding="utf-8") as f:
                existing = f.read()

        # 첫 50자로 중복 체크 (같은 글이면 저장 안 함)
        check = comment[:50]
        if check in existing:
            return

        with open(ANALYST_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n---\n\n{comment}\n")
    except Exception:
        pass


def get_market_context_for_prompt():
    """저장된 컨텍스트 + 한지영 최신 코멘트를 프롬프트용으로 반환"""
    parts = []
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 1. 저장된 시장 컨텍스트
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                context = f.read().strip()
            if context:
                # 컨텍스트 파일의 날짜 추출
                import re
                date_match = re.search(r'(\d{4}\.\d{2}\.\d{2})', context)
                ctx_date = date_match.group(1).replace(".", "-") if date_match else "불명"
                staleness_warning = ""
                if ctx_date != "불명" and ctx_date != today:
                    staleness_warning = f"\n주의: 이 컨텍스트는 {ctx_date} 기준입니다. 오래된 이벤트(실적 발표 등)를 오늘 처음 발생한 것처럼 서술하지 마세요."
                parts.append(f"=== 시장 컨텍스트 (배경 참고용, 오늘 데이터가 아님) ==={staleness_warning}\n{context[:2000]}")
        except Exception:
            pass

    # 2. 한지영 최신 코멘트 (매일 크롤링)
    analyst = _fetch_latest_analyst_comment()
    if analyst:
        parts.append(f"=== 증권사 애널리스트 최신 코멘트 (참고용, 복사 금지, 스타일만 참고) ===\n{analyst}")

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
- 첫 줄은 반드시 "## 시장 국면 ({today} 기준)"으로 시작
- 기존 구조(지정학/매크로/섹터/수급/밸류에이션/시장국면)를 유지
- 오늘 새로 확인된 사실만 반영
- 3일 이상 지난 이벤트는 "N일 전" 표기 추가하거나 중요도가 낮으면 제거
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
        print(f"[CONTEXT] 시장 컨텍스트 업데이트 완료 ({today})")
    except Exception as e:
        print(f"[CONTEXT] 시장 컨텍스트 업데이트 실패: {e}")
        import traceback
        traceback.print_exc()
