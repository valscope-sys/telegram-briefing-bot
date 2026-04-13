"""뉴스 수집 (RSS + 크롤링) + Claude API 분석/필터링"""
import os
import json
import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import ANTHROPIC_API_KEY

# 시황 생성 모델 선택 (환경변수 또는 기본값)
# COMMENTARY_MODEL=opus → claude-opus-4-20250514
# COMMENTARY_MODEL=sonnet (기본) → claude-sonnet-4-20250514
_MODEL_MAP = {
    "opus": "claude-opus-4-20250514",
    "sonnet": "claude-sonnet-4-20250514",
}
COMMENTARY_MODEL = _MODEL_MAP.get(
    os.environ.get("COMMENTARY_MODEL", "sonnet").lower(),
    "claude-sonnet-4-20250514"
)


# ── RSS 피드 목록 ──
RSS_FEEDS = [
    # 국내 종합
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news", "group": "국내"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/", "group": "국내"},
    {"name": "이데일리", "url": "https://www.edaily.co.kr/rss/article.xml", "group": "국내"},
    # 국내 정책
    {"name": "금융위원회", "url": "https://www.fsc.go.kr/comm/rss.do", "group": "국내"},
    {"name": "한국은행", "url": "https://www.bok.or.kr/portal/bbs/rss.do?menuNo=200688", "group": "국내"},
    {"name": "산업통상자원부", "url": "https://www.motie.go.kr/rss/rssNews.do", "group": "국내"},
    # 해외 종합
    {"name": "Reuters", "url": "https://feeds.reuters.com/reuters/businessNews", "group": "해외"},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "group": "해외"},
    {"name": "WSJ", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "group": "해외"},
    # 섹터 전문
    {"name": "TrendForce", "url": "https://www.trendforce.com/rss", "group": "해외"},
    {"name": "Electrek", "url": "https://electrek.co/feed/", "group": "해외"},
    {"name": "InsideEVs", "url": "https://insideevs.com/rss/articles/", "group": "해외"},
    {"name": "FiercePharma", "url": "https://www.fiercepharma.com/rss/xml", "group": "해외"},
    {"name": "Defense News", "url": "https://www.defensenews.com/rss/", "group": "해외"},
    {"name": "World Nuclear News", "url": "https://www.world-nuclear-news.org/rss", "group": "해외"},
]


PROMPT_SYSTEM = """당신은 한국 주식시장 전문 투자 리서치 애널리스트이며, 텔레그램 증시 브리핑 채널을 운영합니다.

절대 규칙:
1. 시스템이 제공한 데이터와 뉴스에 있는 내용만 사용하세요. 데이터에 없는 제품명, 기업명, 기술명, 수치, 이벤트를 절대 만들어내지 마세요.
2. 뉴스 목록에 없는 뉴스를 인용하거나 참조하지 마세요.
3. 수급 연속일수는 '수급 트렌드' 데이터에 명시된 숫자만 사용하세요. 임의로 연속일수를 쓰지 마세요.
4. 시장 방향성을 단정하지 마세요. "강세로 출발", "약세 예상" 같은 표현 금지. 긍정/부정 요인을 병렬 제시하세요.
5. 컨텍스트에 있는 과거 이벤트를 오늘 처음 발생한 것처럼 쓰지 마세요."""

PROMPT_ANALYZE = """아래 뉴스 목록을 분석하여 KOSPI/KOSDAQ에 영향을 줄 수 있는 기사만 평가하세요.

[고정 섹터 트리거]
- 반도체/메모리: HBM 수요·가격, TSMC 가동률, DRAM 고정가, 미중 수출규제
- 2차전지/EV: IRA 정책, 테슬라 딜리버리, 리튬·양극재 가격, 유럽 탄소규제
- 원전/에너지: 에너지기본계획, 해외 원전 수주, SMR 정책, 전력요금
- 조선: 신규 수주, LNG선 발주, BDI/SCFI 운임
- 화장품/K-뷰티: 중국 소비지표, 면세점 매출, 위안화 환율
- 방산: 나토 국방비 증액, 한국 수출 계약, 전황 변화
- 바이오/제약: FDA 허가·임상 결과, 기술수출, 빅파마 M&A
- 자동차: 글로벌 판매량, 관세, 하이브리드 전환
- 철강/소재: 철광석·원료탄 가격, LME 비철금속
- 금융: 한은 금통위, DSR·LTV 정책, 금투세, NIM, PF 부실
- 건설/부동산: PF 리스크, 주택공급 정책, 해외건설 수주
- 매크로/환율: Fed 발언, 미 경제지표, 원달러 환율, 외국인 수급
- 빅테크/AI: 엔비디아·애플·MS·TSMC 실적·가이던스, 데이터센터 투자

[importance 기준]
- 상: 당일 주가 즉각 영향 (정책 확정, 실적 서프라이즈, 수급 변화)
- 중: 단기 1주 이내 영향 (업황 시그널, 트렌드 변화)

하 수준(단순 해설, 반복, 증시 무관)은 출력하지 마세요.

[direction]
- 긍정 / 부정 / 중립

[절대 제외]
- 개별 기업 인사/채용/CSR/사회공헌/후원
- 보험/카드/대출/저축 상품 광고
- 범죄/사건사고/연예/스포츠/골프/쇼트트랙
- 전쟁 전투 상세 (증시 영향 없는 전장 소식, 군사작전 묘사)
- 미국 국내 사회/정치 이슈 (증시 무관)
- 과거 뉴스 (이미 시장에 반영된 옛날 이벤트, 수일~수주 전 사건)
- 부동산/전세/재건축/골프회원권
- 편의점/식품 신제품 출시
- 클릭베이트/낚시성 기사 ("상위 1% 투자자", "개미들 울었다", "폭탄 발언", "충격" 등)
- 출처 불명의 투자자 행동 추측 ("큰손들이 매도", "세력이 움직인다" 등)
- 개인 블로그, 커뮤니티 게시물, 투자 카페 글

[중요]
- 해외 영문 뉴스(CNBC, WSJ, Reuters 등)도 한국 증시에 영향 있으면 반드시 포함하고 한국어로 요약
- 같은 이슈의 중복 기사는 반드시 하나로 합치세요. 예를 들어 "브로드컴 AI칩 계약" 기사가 한경과 CNBC에 각각 있으면, 대표 1건만 선택하고 나머지는 제외. 중복 출력 절대 금지
- 중요한 뉴스가 3개면 3개, 10개면 10개. 억지로 채우거나 빼지 마세요
- 반드시 뉴스 목록에 있는 [번호]를 정확히 사용하세요. 번호를 임의로 매기지 마세요.

[출력 형식 - JSON 배열만 출력, 다른 텍스트 없음]
[
  {{
    "index": 22,
    "importance": "상",
    "sector": "반도체",
    "title": "뉴스 핵심을 담은 한국어 제목 (30자 이내)",
    "detail": "기사 제목과 요약에 쓰여있는 팩트만 정리. 원문에 없는 수치, 제품명, 기업명, 예측, 수혜 종목을 절대 추가하지 마세요. 제목만으로 내용을 유추해서 쓰지 마세요. 모르면 제목을 그대로 옮기세요.",
    "direction": "긍정"
  }}
]

index는 위 뉴스 목록의 [번호]와 정확히 일치해야 합니다. 중복 기사를 합칠 경우 대표 기사의 번호를 사용하세요.

[뉴스 목록]
{article_list}
"""


def _fetch_article_body(url, max_chars=500):
    """기사 본문 스크래핑 (제목만으로 부족한 맥락 보강)"""
    if not url:
        return ""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "lxml")

        # 일반적인 기사 본문 셀렉터 시도
        selectors = [
            "article", ".article-body", ".article_body", ".news_body",
            "#articleBodyContents", "#newsct_article", ".story-body",
            "[itemprop='articleBody']", ".post-content", ".entry-content",
        ]
        body = None
        for sel in selectors:
            body = soup.select_one(sel)
            if body:
                break

        if not body:
            # 가장 긴 <p> 블록들을 합치기
            paragraphs = soup.find_all("p")
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50]
            return " ".join(texts)[:max_chars] if texts else ""

        # 스크립트/스타일 제거
        for tag in body.find_all(["script", "style", "iframe", "figure", "figcaption"]):
            tag.decompose()

        text = body.get_text(separator=" ", strip=True)
        return text[:max_chars] if text else ""
    except Exception:
        return ""


def enrich_news_bodies(news_list, max_items=10):
    """필터링된 뉴스의 본문을 스크래핑해서 detail 보강"""
    import concurrent.futures

    def _enrich_one(item):
        if item.get("detail") and len(item["detail"]) > 100:
            return item  # 이미 충분한 detail이 있으면 스킵
        body = _fetch_article_body(item.get("link", ""))
        if body:
            item["body_text"] = body
        return item

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_enrich_one, n): n for n in news_list[:max_items]}
        concurrent.futures.wait(futures, timeout=15)

    return news_list


def fetch_rss_news(max_per_feed=50, max_age_hours=48):
    """모든 RSS 피드에서 뉴스 수집 (최근 N시간 이내만)"""
    from email.utils import parsedate_to_datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=max_age_hours)

    all_news = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                # 날짜 필터: 48시간 이내 기사만
                pub_str = entry.get("published", "")
                if pub_str:
                    try:
                        pub_dt = parsedate_to_datetime(pub_str)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass
                all_news.append({
                    "source": feed_info["name"],
                    "group": feed_info["group"],
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": pub_str,
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception:
            continue
    return all_news


def fetch_naver_finance_news():
    """네이버 금융 많이 본 뉴스 스크래핑"""
    urls = [
        "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258",
        "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=261",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    news = []
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "lxml")
            for item in soup.select("li.block1"):
                a = item.select_one("a")
                if a:
                    title = a.get_text(strip=True)
                    link = "https://finance.naver.com" + a.get("href", "")
                    news.append({
                        "source": "네이버금융",
                        "group": "국내",
                        "title": title,
                        "link": link,
                        "published": "",
                        "summary": "",
                    })
        except Exception:
            continue
    return news


def filter_news_with_claude(news_list, count=5, context=""):
    """Claude API로 뉴스 분석 + 필터링 + 요약"""
    if not ANTHROPIC_API_KEY:
        return news_list[:count]

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 뉴스 목록 구성 (최대 150건)
    article_list = "\n".join(
        [f"[{i+1}] [{n['group']}] {n['title']} ({n['source']})"
         for i, n in enumerate(news_list[:150])]
    )

    prompt = PROMPT_ANALYZE.format(article_list=article_list)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=PROMPT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # JSON 파싱
        if text.startswith("["):
            results = json.loads(text)
        else:
            # JSON이 텍스트에 섞여있을 경우
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                results = json.loads(text[start:end])
            else:
                return news_list[:count]

        # 중요도순 정렬 (상 → 중)
        importance_order = {"상": 0, "중": 1}
        results.sort(key=lambda x: importance_order.get(x.get("importance", "중"), 1))

        # 원본 뉴스와 매칭
        selected = []
        for r in results:
            idx = r.get("index", 0) - 1
            if 0 <= idx < len(news_list):
                item = news_list[idx].copy()
                item["summary_title"] = r.get("title", item["title"])
                item["detail"] = r.get("detail", "")
                item["sector"] = r.get("sector", "")
                item["importance"] = r.get("importance", "중")
                item["direction"] = r.get("direction", "중립")
                selected.append(item)
        return selected if selected else news_list[:count]
    except Exception as e:
        print(f"[NEWS FILTER ERROR] {e}")
        import traceback
        traceback.print_exc()
        return news_list[:count]


def _build_news_section(news_list, max_items=10):
    """뉴스 데이터를 프롬프트용 텍스트로 변환 (본문 포함)"""
    lines = ["\n주요 뉴스:"]
    for n in news_list[:max_items]:
        title = n.get('summary_title', n.get('title', ''))
        detail = n.get('detail', '')
        sector = n.get('sector', '')
        body = n.get('body_text', '')
        direction = n.get('direction', '')

        header = f"- [{sector}] {title}" if sector else f"- {title}"
        if direction:
            header += f" ({direction})"
        lines.append(header)

        if detail:
            lines.append(f"  요약: {detail[:200]}")
        if body:
            lines.append(f"  본문: {body[:300]}")
    return "\n".join(lines)


def _match_news_to_movers(news_list, top_gainers, top_losers, sectors):
    """급등락 종목/섹터와 뉴스를 자동 매칭"""
    matches = []

    # 섹터별 키워드
    sector_keywords = {
        "반도체": ["반도체", "HBM", "메모리", "DRAM", "NAND", "파운드리", "AI칩"],
        "2차전지": ["배터리", "2차전지", "리튬", "양극재", "EV", "전기차"],
        "자동차": ["자동차", "현대차", "기아", "테슬라", "EV"],
        "건설": ["건설", "재건", "인프라", "주택", "부동산"],
        "조선": ["조선", "LNG선", "발주", "수주"],
        "방산": ["방산", "국방", "무기", "전쟁", "휴전", "재건"],
        "바이오": ["바이오", "제약", "FDA", "임상", "신약"],
        "에너지": ["원유", "유가", "WTI", "원전", "에너지"],
        "철강": ["철강", "철광석", "포스코"],
        "해운": ["해운", "운임", "컨테이너", "BDI"],
    }

    # 급등 섹터 추출
    hot_sectors = []
    for sec_name, info in sectors.items():
        if isinstance(info, dict) and "error" not in info:
            rate = info.get("등락률", 0)
            if abs(rate) > 2:
                hot_sectors.append((sec_name, rate))

    # 급등 종목에서 키워드 매칭
    big_movers = []
    for item in (top_gainers or [])[:10] + (top_losers or [])[:10]:
        name = item.get("종목명", "")
        rate = item.get("등락률", 0)
        if abs(rate) > 5:
            big_movers.append((name, rate))

    # 뉴스와 매칭
    for news in news_list:
        title = news.get("summary_title", news.get("title", ""))
        body = news.get("body_text", "")
        combined = title + " " + body
        news_sector = news.get("sector", "")

        for sec_name, keywords in sector_keywords.items():
            for kw in keywords:
                if kw in combined:
                    # 해당 섹터가 급등락했는지 확인
                    for hot_sec, rate in hot_sectors:
                        if sec_name in hot_sec or hot_sec in sec_name:
                            matches.append(f"  [{sec_name} 섹터 {rate:+.1f}%] 관련 뉴스: {title}")
                            break
                    break

    if matches:
        return "\n=== 섹터-뉴스 매칭 ===\n" + "\n".join(list(dict.fromkeys(matches))[:8])
    return ""


def generate_market_commentary(market_data, news_list, intraday_text="", trend_text="", consensus_text="", global_data=None):
    """Claude API로 시황 해석 생성 (이브닝 브리핑용)"""
    if not ANTHROPIC_API_KEY:
        return "시황 해석을 생성하려면 Anthropic API 키가 필요합니다."

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    indices = market_data.get("indices", {})
    investors = market_data.get("investors", {})
    sectors = market_data.get("sectors", {})
    sector_stocks = market_data.get("sector_stocks", {})
    trade_rank = market_data.get("trade_value_rank", [])
    top_gainers = market_data.get("top_gainers", [])
    top_losers = market_data.get("top_losers", [])

    data_summary = "=== 오늘 시장 데이터 ===\n"
    for name, info in indices.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"{name}: {info.get('현재가', 0)} ({info.get('등락률', 0):+.2f}%)\n"

    if isinstance(investors, dict) and "error" not in investors:
        frgn = investors.get("외국인금액", 0) / 100
        inst = investors.get("기관금액", 0) / 100
        pers = investors.get("개인금액", 0) / 100
        data_summary += f"\n수급: 외국인 {frgn:+,.0f}억 / 기관 {inst:+,.0f}억 / 개인 {pers:+,.0f}억\n"

    data_summary += "\n섹터 ETF 등락:\n"
    for sector, info in sectors.items():
        if isinstance(info, dict) and "error" not in info:
            stocks = sector_stocks.get(sector, [])
            stock_str = ", ".join([f"{s['종목명']}({s['등락률']:+.1f}%)" for s in stocks]) if stocks else ""
            data_summary += f"  {sector}: {info.get('등락률', 0):+.2f}%  {stock_str}\n"

    if trade_rank:
        data_summary += "\n거래대금 상위 30종목:\n"
        for i, item in enumerate(trade_rank):
            data_summary += f"  {i+1}. {item.get('종목명', '')} {item.get('등락률', 0):+.2f}%\n"

    if top_gainers:
        data_summary += "\n상승률 상위 종목:\n"
        for item in top_gainers[:15]:
            data_summary += f"  {item.get('종목명', '')} {item.get('등락률', 0):+.2f}%\n"

    if top_losers:
        data_summary += "\n하락률 상위 종목:\n"
        for item in top_losers[:15]:
            data_summary += f"  {item.get('종목명', '')} {item.get('등락률', 0):+.2f}%\n"

    # 채권금리 + 심리지표 (글로벌 데이터에서)
    if global_data:
        bonds = global_data.get("bonds", {})
        if bonds and "error" not in bonds:
            data_summary += "\n채권금리:\n"
            for name in ["미국 2Y", "미국 10Y", "국고채 3Y", "국고채 10Y"]:
                b = bonds.get(name, {})
                if b and "error" not in b:
                    data_summary += f"  {name}: {b.get('금리', 0):.3f}% ({b.get('전일대비', 0):+.3f}%p)\n"
            # 장단기 스프레드
            us2y = bonds.get("미국 2Y", {}).get("금리", 0)
            us10y = bonds.get("미국 10Y", {}).get("금리", 0)
            if us2y and us10y:
                spread = us10y - us2y
                data_summary += f"  10Y-2Y 스프레드: {spread:+.3f}%p"
                if spread < 0:
                    data_summary += " (장단기 역전, 경기침체 우려 시그널)"
                data_summary += "\n"

        sentiment = global_data.get("sentiment", {})
        if sentiment:
            data_summary += "\n심리지표:\n"
            fg = sentiment.get("Fear & Greed", {})
            if fg and "error" not in fg:
                data_summary += f"  Fear & Greed Index: {fg.get('점수', 0)}점 ({fg.get('등급', '')})\n"
            pc = sentiment.get("Put/Call Ratio", {})
            if pc:
                data_summary += f"  Put/Call Ratio: {pc.get('비율', 0)} ({pc.get('해석', '')})\n"

    # 뉴스 (제목 + 본문 포함)
    data_summary += _build_news_section(news_list)

    # 종목-뉴스 자동 매칭
    news_match = _match_news_to_movers(news_list, top_gainers, top_losers, sectors)
    if news_match:
        data_summary += f"\n{news_match}\n"

    # 장중 흐름 데이터
    if intraday_text:
        data_summary += f"\n{intraday_text}\n"

    # 수급 트렌드 데이터
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    # 실적 컨센서스 데이터
    if consensus_text:
        data_summary += f"\n{consensus_text}\n"

    prompt = f"""{data_summary}

위 데이터를 바탕으로 오늘 시장 시황을 작성해주세요.
증권사 리서치센터 애널리스트가 텔레그램 채널 구독자(개인 투자자)에게 장 마감 시황을 전달합니다.

[문체]
- 서술형. 기본 어미는 "~습니다/입니다". 부드러운 표현이 필요할 때만 "~싶습니다", "~봅니다"
- "~네요" 어미 사용 금지. 가벼워짐.
- 동료 애널리스트가 메신저로 보내는 느낌. 보고서도 아니고 뉴스 앵커도 아님.
- 단, 너무 가볍지 않게. 전문성 유지.
- 투자자의 심리와 피로감을 이해하는 톤

[첫 문장]
- 헤드라인/선언문 스타일 절대 금지.
- 나쁜 예: "휴전 선언이라는 굵은 재료가 나왔습니다."
- 좋은 예: "3월 이후 조정 장세가 전환점을 맞이한 하루였습니다."
- 바로 시장 국면을 한마디로 정의하세요.

[인과관계]
- 반드시 3단계 이상 자연어로 연결.
- 나쁜 예: "유가 하락으로 외국인 부담이 완화됐습니다" (2단계)
- 좋은 예: "유가 급락이 에너지 비용 완화로 이어지고, 이는 인플레이션 압력을 낮추며, 성장주 밸류에이션 부담을 덜어주는 구조입니다" (3단계)
- 인과관계를 추론할 때 실제 산업 구조를 반드시 고려하세요. 관련 없는 산업끼리 억지로 연결하지 마세요.

[큰 그림]
- 마무리 전에 "지금이 어떤 국면인지" 한 줄 반드시 포함.
- 예: "3월 이후의 조정 장세가 전환점을 맞이할 가능성이 높아지고 있습니다"

[구조]
1: 국면 정의 — 첫 문장에 시장 국면 한마디 정의. 두 번째 문장에 그 배경.
2: 장중 흐름 — 시가에서 고가, 저가, 종가까지 시간순 스토리. "왜" 올랐고 "왜" 눌렸는지 인과관계 체인.
   종가 기준 상승 마감이면 상승 흐름 중심 서술. 전강후약으로 종가가 시가보다 크게 밀린 경우에만 장중 하락 서술.
   개인 매도는 차익실현. 심리를 고차원적으로 해석하지 말 것.
3: 섹터·종목 — 매크로와 별도 문단. 강세 섹터 3개 이상 + 약세 섹터 3개 이상, 양쪽 균형.
   주도 섹터 + 대표 종목 등락률 + 이유. 거래대금 상위 특이 종목 + 뉴스 매칭.
   섹터별로 양면 서술. 수혜만 쓰지 말고 리스크도 함께.
   실적 발표 종목은 컨센 경로 표시. 전강후약이면 "시장이 뭘 고민하는지" 구조적 의문.
   개별 종목 뉴스는 "섹터" 단위로 묶어서 서술. 개별 기업명+금액+사업내용을 구체적으로 쓰면 종목 추천처럼 보입니다.
   시총 상위(삼성전자, SK하이닉스, 현대차 등)만 기업명 직접 언급 가능. 중소형주는 섹터명으로 대체.
4: 수급 + 큰 그림 — 외국인뿐 아니라 기관 수급도 반드시 포함. 수급 엇갈림 구조가 중요.
   컨텍스트의 시장 역사(사이드카/서킷 횟수, 전쟁 경과 등)를 큰 그림에 활용.
   향후 핵심 변수 + 구체적 시간대 (예: "4월 말 컨콜, 5월 초 M7 실적까지").
   방향성: "~적절하지 않을까 싶습니다" 수준. 구체적 비중 수치 금지.

[줄바꿈]
- 내용이 달라지는 곳에서 빈 줄
- 전환어("다만", "반면", "한편") 앞에서 빈 줄
- 종목 강세/약세는 매크로와 별도 문단
- 문장 중간 줄바꿈 절대 금지

[데이터 활용 — 가장 중요한 원칙]
- 시황에서 언급하는 모든 종목명은 반드시 시스템이 제공한 데이터(상승률 순위/거래대금 순위/섹터 ETF/장중 흐름)에 있어야 합니다. 데이터에 없는 종목명을 절대 만들어내지 마세요.
- 원칙: 데이터(뼈)에 있는 종목을 먼저 선택하고, 뉴스(살)로 이유를 붙이세요. 뉴스가 먼저가 아닙니다.
- 환율/지수 등 수치는 시스템이 제공한 종가 데이터만 사용. 장중 고가/저가를 종가처럼 쓰지 마세요. 장중 수치를 쓸 때는 "장중 한때 1,495원까지 상승했으나"처럼 명확히 구분하세요.
- 등락률 크기에 맞는 표현을 사용하세요. 0.3% 이하는 "소폭/보합권", 0.3~1%는 "하락/상승", 1% 이상은 "큰 폭/급등/급락".
- 제공된 데이터를 최대한 빠짐없이 활용하세요. 데이터를 무시하면 시황의 깊이가 얕아집니다.
- 채권금리(10Y-2Y 스프레드)가 제공되면 매크로 해석에 반영.
- 심리지표(Fear & Greed)가 제공되면 시장 심리 판단 근거로 활용.
- 환율 데이터가 있으면 외국인 수급 해석에 연결.
- 수급 트렌드에 기관 데이터가 있으면 외국인과 함께 반드시 서술.
- "밸류에이션"같은 전문용어를 쓸 때는 자연어로 풀어서.

[팩트 검증]
- 숫자는 제공된 데이터 그대로 사용. 임의 반올림 금지. 코스피 5,857이면 "5,857", "5860선"이나 "5880선"으로 바꾸지 마세요.
- 등락률도 데이터 그대로. 4.8%를 "5% 넘게"로 부풀리지 마세요.
- 시스템이 제공한 데이터만 사용. 제공되지 않은 수치(선행 PER, 지분율 등)를 만들어내지 마세요.
- 종목의 시장 지위(선두, 1위, 독점 등)를 데이터 없이 임의로 부여 금지.
- 우려나 기대를 쓰려면 근거(뉴스, 데이터)가 있어야 함.
- 등락 사유는 공신력 있는 뉴스 데이터에 근거가 있을 때만 서술.
- 출처 불명이거나 검증 안 된 주장("상위 1% 투자자 매도", "큰손 물량", "세력 매집" 등)은 절대 인용하지 마세요. 공식 수급 데이터(외국인/기관/개인)만 사용.
- 섹터/종목 급등락 이유를 추론할 때, 당일 가장 큰 재료(휴전, 실적 등)와 직접 연결되는 인과관계를 우선 선택. 우회적이거나 간접적인 이유를 갖다 붙이지 마세요.
  나쁜 예: 건설주 급등 + "유가 하락으로 건설 원가 완화" (간접적, 억지)
  좋은 예: 건설주 급등 + "휴전에 따른 재건 기대감" (직접적, 자명)

[금지]
- 화살표(→) 금지. 자연어로.
- 교과서/증권방송 용어 금지 ("위험자산 선호 심리", "쌍끌이 수급", "반가운 신호")
- 데이터 용어 변경 금지 (영업이익을 매출로 바꾸지 마세요)
- 데이터에 없는 팩트 금지
- "독점", "유일", "최초", "역대" 같은 극단적 표현은 데이터 확인 시에만
- "N거래일 연속"은 2일 이상만. 1일은 "전환"
- ETF vs 종목 괴리 시 설명 필수
- 뉴스 데이터에 없는 제품명, 기술명, 이벤트를 만들어내지 마세요. 뉴스 목록에 있는 내용만 언급.
- 컨텍스트에 있는 과거 이벤트(예: 실적 발표)가 이미 수일 전 반영된 것이면 "기대감을 높이고 있다"처럼 현재형으로 쓰지 마세요. "N일 전 발표된 실적이 여전히 지지력을 제공하고 있다" 정도로.
- 개별 중소형주 뉴스에 별도 문단을 할애하지 마세요. 시총 상위 종목이 아니면 한 줄 이내로 언급하거나 생략.
- "주목됩니다", "주목받을 것으로 보입니다" 같은 의미 없는 채움말 금지. 왜 중요한지 이유를 쓰거나 쓰지 마세요.
- 서식(별표, 괄호, 번호, 제목) 없이 텍스트만
- 마무리에 긍정만 쓰지 말고 리스크 요인도 반드시 한 줄 포함
- 총 14~18문장

시황만 작성하세요."""

    print(f"[COMMENTARY] 이브닝 시황 모델: {COMMENTARY_MODEL}")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=2000,
            system=PROMPT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"시황 해석 생성 실패: {e}"


def generate_morning_commentary(global_data, news_list, trend_text=""):
    """Claude API로 전일 미장 시황 해석 생성 (모닝 브리핑용)"""
    if not ANTHROPIC_API_KEY:
        return ""

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    indices = global_data.get("indices", {})
    us_sectors = global_data.get("us_sectors", {})
    us_stocks = global_data.get("us_stocks", {})
    commodities = global_data.get("commodities", {})
    fx = global_data.get("fx", {})

    data_summary = "=== 전일 미국 증시 데이터 ===\n"
    for name, info in indices.items():
        if isinstance(info, dict) and "error" not in info and info.get("현재가"):
            data_summary += f"{name}: {info['현재가']:,.2f} ({info.get('등락률', 0):+.2f}%)\n"

    data_summary += "\n미국 섹터:\n"
    for name, info in us_sectors.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"  {name}: {info.get('등락률', 0):+.2f}%\n"

    data_summary += "\n주요 종목:\n"
    for ticker, info in us_stocks.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"  {info.get('종목명', ticker)}: ${info.get('현재가', 0):,.2f} ({info.get('등락률', 0):+.2f}%)\n"

    data_summary += "\n원자재/환율:\n"
    for name, info in commodities.items():
        if isinstance(info, dict) and "error" not in info:
            data_summary += f"  {name}: ${info.get('현재가', 0):,.2f} ({info.get('등락률', 0):+.2f}%)\n"
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw:
        data_summary += f"  USD/KRW: {usdkrw.get('현재가', 0):,.1f} ({usdkrw.get('전일대비', 0):+.2f})\n"

    # 채권금리
    bonds = global_data.get("bonds", {})
    if bonds and "error" not in bonds:
        data_summary += "\n채권금리:\n"
        for name in ["미국 2Y", "미국 10Y"]:
            b = bonds.get(name, {})
            if b and "error" not in b:
                data_summary += f"  {name}: {b.get('금리', 0):.3f}% ({b.get('전일대비', 0):+.3f}%p)\n"
        us2y = bonds.get("미국 2Y", {}).get("금리", 0)
        us10y = bonds.get("미국 10Y", {}).get("금리", 0)
        if us2y and us10y:
            spread = us10y - us2y
            data_summary += f"  10Y-2Y 스프레드: {spread:+.3f}%p"
            if spread < 0:
                data_summary += " (장단기 역전)"
            data_summary += "\n"

    # 심리지표
    sentiment = global_data.get("sentiment", {})
    if sentiment:
        fg = sentiment.get("Fear & Greed", {})
        if fg and "error" not in fg:
            data_summary += f"\n심리지표:\n  Fear & Greed Index: {fg.get('점수', 0)}점 ({fg.get('등급', '')})\n"
        pc = sentiment.get("Put/Call Ratio", {})
        if pc:
            data_summary += f"  Put/Call Ratio: {pc.get('비율', 0)} ({pc.get('해석', '')})\n"

    # 뉴스 (본문 포함)
    data_summary += _build_news_section(news_list, max_items=8)

    # 수급 트렌드
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    prompt = f"""{data_summary}

위 데이터를 바탕으로 전일 미국 증시 마감 리뷰 + 오늘 한국 증시 체크포인트를 작성해주세요.
증권사 리서치센터 애널리스트가 텔레그램 채널 구독자(개인 투자자)에게 보내는 모닝 시황입니다.

[문체]
- 서술형. 기본 어미는 "~습니다/입니다". 부드러운 표현이 필요할 때만 "~싶습니다", "~봅니다"
- "~네요" 어미 사용 금지. 가벼워짐.
- 동료 애널리스트가 메신저로 보내는 느낌. 보고서도 아니고 뉴스 앵커도 아님.
- 단, 너무 가볍지 않게. 전문성 유지.

[첫 문장]
- 헤드라인/선언문 스타일 절대 금지.
- 나쁜 예: "휴전 선언이라는 굵은 재료가 나왔습니다."
- 좋은 예: "전일 미국 증시는 휴전 기대감 속에 혼조 마감했습니다."
- 바로 구체적 내용으로 진입하세요.

[인과관계]
- 반드시 3단계 이상 자연어로 연결.
- 나쁜 예: "유가 하락으로 외국인 부담이 완화됐습니다" (2단계)
- 좋은 예: "유가 급락이 에너지 비용 완화로 이어지고, 이는 인플레이션 압력을 낮추며, 달러 강세 압력이 누그러지면서 원화가 강세를 보이는 구조입니다" (4단계)
- 인과관계를 추론할 때 실제 산업 구조를 반드시 고려하세요. 관련 없는 산업끼리 억지로 연결하지 마세요.
  나쁜 예: "호르무즈 해협 봉쇄로 반도체 물류 차질" (반도체는 호르무즈를 통해 운송되지 않음)
  좋은 예: "호르무즈 해협 봉쇄로 원유 공급 차질 우려, 에너지주 강세" (에너지는 실제 영향받는 산업)

[큰 그림]
- 마무리 전에 "지금이 어떤 국면인지" 한 줄 반드시 포함.
- 예: "3월 이후의 조정 장세가 전환점을 맞이할 가능성이 높아지고 있습니다"

[구조]
1: 미장 과정 — 숫자만 나열하지 말고 "장 흐름"을 서술하세요.
   나쁜 예: "다우 -0.56%, S&P -0.11%, 나스닥 +0.35%로 마감했습니다." (결과 나열)
   좋은 예: "장 초반 종전협상 결렬 소식에 하락 출발했으나, 반도체 강세가 나스닥을 지지하며 낙폭을 제한한 채 혼조 마감했습니다." (과정 서술)
   지수 숫자는 흐름 서술 뒤에 별도 문장으로.
2: 섹터·종목 — 강세 섹터 3개 이상 + 약세 섹터 3개 이상. 양쪽 균형.
   강세 종목과 약세 종목 모두 서술. 강세만 나열하면 편향됩니다.
   원자재(금, 구리 등)도 데이터가 있으면 반드시 언급. 금 하락/상승은 심리 시그널로 해석 가능.
3: 한국 체크포인트 — 첫 문장은 반드시 매크로(유가/환율/지정학)부터.
   인과관계 3단계 이상. "강세/약세로 출발할 것" 같은 방향성 단정 금지. 긍정 요인과 부정 요인을 병렬 서술.
   섹터별로 양면 서술. "정유주 수혜 가능"만 쓰지 말고 "vs 마진 압박 우려"도 함께.
   개별 종목 뉴스는 "섹터" 단위로 묶어서 서술. 개별 기업명+금액+사업내용을 구체적으로 쓰면 종목 추천(세일즈)처럼 보입니다.
   나쁜 예: "한솔테크닉스가 900억원 유상증자로 월테크놀러지를 인수하며 사업 확장에 나섰습니다" (세일즈)
   좋은 예: "반도체 장비 업종에서 M&A 움직임이 포착되고 있습니다" (섹터 트렌드)
   시총 상위 종목(삼성전자, SK하이닉스, 현대차 등)만 기업명 직접 언급 가능.
4: 수급 + 큰 그림 — 외국인뿐 아니라 기관 수급도 반드시 포함. 수급 엇갈림이 있으면 서술.
   컨텍스트에 있는 시장 역사(사이드카/서킷브레이커 횟수, 전쟁 이후 경과 등)를 큰 그림에 활용.
   "~적절하지 않을까 싶습니다" 수준. 구체적 방향 예측 금지.

[줄바꿈]
- 내용이 달라지는 곳에서 빈 줄
- 전환어("다만", "반면", "한편") 앞에서 빈 줄
- 종목 강세/약세는 매크로와 별도 문단
- 문장 중간 줄바꿈 절대 금지

[데이터 활용 — 가장 중요한 원칙]
- 시황에서 언급하는 모든 종목명은 반드시 시스템이 제공한 데이터에 있어야 합니다. 데이터에 없는 종목명을 절대 만들어내지 마세요.
- 원칙: 데이터(뼈)에 있는 종목을 먼저 선택하고, 뉴스(살)로 이유를 붙이세요.
- 수치는 시스템이 제공한 종가 데이터만 사용. 장중 수치를 쓸 때는 "장중 한때"로 명확히 구분하세요.
- 등락률 크기에 맞는 표현: 0.3% 이하 "소폭/보합권", 0.3~1% "하락/상승", 1% 이상 "큰 폭/급등/급락".
- 제공된 데이터를 최대한 빠짐없이 활용하세요.
- 채권금리(10Y-2Y 스프레드)가 제공되면 매크로 해석에 반영.
- 심리지표(Fear & Greed)가 제공되면 시장 심리 판단 근거로 활용.
- 원자재(금, 구리)가 제공되면 반드시 언급. 금 하락은 위험자산 선호, 금 상승은 안전자산 선호 시그널.
- 수급 트렌드에 기관 데이터가 있으면 외국인과 함께 반드시 서술.
- "밸류에이션"같은 전문용어는 자연어로 풀어서.

[팩트 검증]
- 숫자는 제공된 데이터 그대로 사용. 임의 반올림 금지.
- 등락률도 데이터 그대로. 0.08%를 "소폭"이라고만 쓰지 말고 수치 포함.
- 시스템이 제공한 데이터만 사용. 제공되지 않은 수치(지분율 등)를 만들어내지 마세요.
- 출처 불명 주장 인용 금지. 공식 수급 데이터만 사용.
- 종목 급등락 이유 추론 시 당일 가장 큰 재료와 직접 연결되는 인과관계 우선.

[금지]
- 화살표(→) 금지. 자연어로.
- 교과서/증권방송 용어 금지 ("위험자산 선호 심리", "쌍끌이 수급", "반가운 신호")
- 데이터 용어 변경 금지 (영업이익을 매출로 바꾸지 마세요)
- 데이터에 없는 팩트 금지
- 종목 시장 지위 임의 부여 금지
- 구체적 수치 예측 금지
- 구체적 비중 수치 금지
- "강세/약세로 출발", "상승/하락 출발" 같은 방향성 단정 금지. 긍정·부정 요인을 균형있게 제시하고 판단은 투자자에게 맡기세요.
- 뉴스 데이터에 없는 제품명, 기술명, 이벤트를 만들어내지 마세요. 뉴스 목록에 있는 내용만 언급.
- 컨텍스트에 있는 과거 이벤트(예: 삼성전자 실적)가 이미 수일 전 반영된 것이면 "기대감을 높이고 있다"처럼 현재형으로 쓰지 마세요.
- 이 시황은 07:00(장 개장 전)에 발송됩니다. 한국 장은 09:00에 열립니다. 장 개장 전이므로 국내 종목의 현재 움직임을 알 수 없습니다. "장 초반 상승세", "프리마켓에서 약세", "이미 강세를 보이고 있다" 같은 장중/프리마켓 묘사는 시스템이 제공하지 않은 데이터입니다. 절대 쓰지 마세요.
- "~예상됩니다"는 전체 시황에서 1~2회 이내로. 매 문단마다 쓰면 리딩이 됩니다. 나머지는 "~가능성이 있습니다", "~요인으로 작용할 수 있습니다"로 대체.
- "주목됩니다", "주목받을 것으로 보입니다" 같은 의미 없는 채움말 금지. 왜 중요한지 이유를 쓰거나, 아예 쓰지 마세요.
- 서식 없이 텍스트만
- 마무리에 긍정만 쓰지 말고 리스크 요인도 한 줄 포함
- 총 12~16문장

시황만 작성하세요."""

    print(f"[COMMENTARY] 모닝 시황 모델: {COMMENTARY_MODEL}")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=2000,
            system=PROMPT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"미장 시황 생성 실패: {e}"
