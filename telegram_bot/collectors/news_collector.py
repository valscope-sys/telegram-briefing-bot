"""뉴스 수집 (RSS) + Claude API 필터링"""
import feedparser
from telegram_bot.config import ANTHROPIC_API_KEY


# RSS 피드 소스
RSS_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/economy/rss"),
    ("연합뉴스 증권", "https://www.yna.co.kr/stock/rss"),
    ("한경 증권", "https://www.hankyung.com/feed/stock"),
    ("매경 증권", "https://www.mk.co.kr/rss/30100041/"),
]


def fetch_rss_news(max_per_feed=15):
    """RSS 피드에서 뉴스 헤드라인 수집"""
    all_news = []
    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                all_news.append({
                    "source": source_name,
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception:
            continue
    return all_news


def filter_news_with_claude(news_list, count=5, context=""):
    """Claude API로 뉴스 중요도 필터링 (상위 N건 선정)"""
    if not ANTHROPIC_API_KEY:
        # API 키 없으면 최신 순으로 반환
        return news_list[:count]

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    headlines = "\n".join(
        [f"[{i+1}] {n['title']} ({n['source']})" for i, n in enumerate(news_list[:40])]
    )

    prompt = f"""아래는 오늘 수집된 한국 경제/증권 뉴스 헤드라인입니다.

{headlines}

{f"오늘 시장 상황: {context}" if context else ""}

주식 투자자 관점에서 가장 중요한 뉴스 {count}개를 선정해주세요.
선정 기준:
1. 시장 전체에 영향을 미치는 매크로 이벤트
2. 주요 종목/섹터에 직접적 영향
3. 정책 변화, 규제, 지정학적 이슈
4. 실적 서프라이즈 또는 쇼크

반드시 아래 형식으로만 응답하세요 (다른 설명 없이):
[번호] 제목을 15자 이내로 요약"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        # 파싱: [번호] 형태에서 원본 뉴스 매칭
        selected = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # [1] 제목... 형태 파싱
            if line.startswith("[") and "]" in line:
                try:
                    idx_str = line.split("]")[0].replace("[", "").strip()
                    idx = int(idx_str) - 1
                    summary = line.split("]", 1)[1].strip()
                    if 0 <= idx < len(news_list):
                        item = news_list[idx].copy()
                        item["summary_title"] = summary
                        selected.append(item)
                except (ValueError, IndexError):
                    continue
        return selected if selected else news_list[:count]
    except Exception:
        return news_list[:count]


def generate_market_commentary(market_data, news_list):
    """Claude API로 시황 해석 생성 (이브닝 브리핑용)"""
    if not ANTHROPIC_API_KEY:
        return "시황 해석을 생성하려면 Anthropic API 키가 필요합니다."

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 시장 데이터 요약 구성
    indices = market_data.get("indices", {})
    investors = market_data.get("investors", {})
    sectors = market_data.get("sectors", {})

    data_summary = "=== 오늘 시장 데이터 ===\n"
    for name, info in indices.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"{name}: {info.get('현재가', 0)} ({info.get('등락률', 0):+.2f}%)\n"

    if isinstance(investors, dict) and "error" not in investors:
        data_summary += f"\n수급: 외국인 {investors.get('외국인금액', 0):,}백만 / 기관 {investors.get('기관금액', 0):,}백만 / 개인 {investors.get('개인금액', 0):,}백만\n"

    data_summary += "\n섹터 등락:\n"
    for sector, info in sectors.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"  {sector}: {info.get('등락률', 0):+.2f}%\n"

    headlines = "\n".join([f"- {n['title']}" for n in news_list[:10]])
    data_summary += f"\n주요 뉴스:\n{headlines}"

    prompt = f"""{data_summary}

위 데이터를 바탕으로 오늘 시장 시황을 3~4문장으로 작성해주세요.

작성 규칙:
1. 핵심 등락 원인을 먼저 언급
2. 수급 주체별 흐름 한 줄
3. 주요 이벤트와 시장 반응 연결
4. 숫자는 반드시 데이터 기반, 추측 금지
5. 객관적이고 간결한 증권사 리포트 톤

시황만 작성하고 다른 설명은 하지 마세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"시황 해석 생성 실패: {e}"
