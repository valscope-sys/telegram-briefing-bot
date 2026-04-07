"""시장 컨텍스트 수집 — 증권사 애널리스트 채널에서 맥락 학습"""
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import ANTHROPIC_API_KEY


# 참고할 텔레그램 채널 (공개 채널만)
ANALYST_CHANNELS = [
    "hedgecat0301",  # 키움 한지영
]


def fetch_analyst_messages(max_messages=10):
    """공개 텔레그램 채널에서 최근 메시지 수집"""
    all_messages = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for channel in ANALYST_CHANNELS:
        try:
            url = f"https://t.me/s/{channel}"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "lxml")
            messages = soup.select(".tgme_widget_message_text")

            for msg in messages[-max_messages:]:
                text = msg.get_text(strip=True)
                if len(text) > 100:  # 짧은 메시지 제외
                    all_messages.append({
                        "channel": channel,
                        "text": text[:2000],  # 최대 2000자
                    })
        except Exception:
            continue

    return all_messages


def extract_market_context(messages):
    """수집된 메시지에서 시장 컨텍스트 추출 (Claude API)"""
    if not ANTHROPIC_API_KEY or not messages:
        return ""

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 최근 5개 메시지만 사용 (토큰 절약)
    recent = messages[-5:]
    combined = "\n\n---\n\n".join([m["text"] for m in recent])

    prompt = f"""아래는 증권사 애널리스트의 최근 시황 코멘트입니다.
이 내용을 분석해서 현재 시장의 핵심 컨텍스트를 추출해주세요.

{combined[:4000]}

아래 항목별로 간결하게 정리해주세요 (각 항목 2~3줄):
1. 지정학 상황 (전쟁, 협상 진행 상황)
2. 매크로 환경 (유가, 금리, 환율 흐름과 방향)
3. 주도 섹터 업황 (반도체, 2차전지 등 핵심 이슈)
4. 수급 트렌드 (외국인 누적 매도/매수 규모와 방향 전환 여부)
5. 밸류에이션 위치 (PER 수준, 역사적 비교)
6. 시장 국면 판단 (조정기/회복기/상승기 등)

JSON이 아닌 일반 텍스트로 작성하세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


def get_market_context_for_prompt():
    """시황 프롬프트에 삽입할 시장 컨텍스트 반환"""
    messages = fetch_analyst_messages(max_messages=7)
    if not messages:
        return ""

    context = extract_market_context(messages)
    if context:
        return f"=== 현재 시장 컨텍스트 (증권사 애널리스트 참고) ===\n{context}"
    return ""
