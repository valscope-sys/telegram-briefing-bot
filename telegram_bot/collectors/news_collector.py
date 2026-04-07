"""뉴스 수집 (RSS + 크롤링) + Claude API 분석/필터링"""
import json
import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import ANTHROPIC_API_KEY


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
    # 커뮤니티
    {"name": "r/investing", "url": "https://www.reddit.com/r/investing/top/.rss?t=day", "group": "해외"},
    {"name": "r/wallstreetbets", "url": "https://www.reddit.com/r/wallstreetbets/top/.rss?t=day", "group": "해외"},
    {"name": "r/stocks", "url": "https://www.reddit.com/r/stocks/top/.rss?t=day", "group": "해외"},
]


PROMPT_SYSTEM = "당신은 한국 주식시장 전문 투자 리서치 애널리스트이며, 텔레그램 증시 브리핑 채널을 운영합니다."

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
    "detail": "원문을 안 읽어도 내용이 파악되는 상세 요약. 배경, 수치, 시장 영향, 수혜/피해 섹터까지 포함해서 3~5문장으로 작성.",
    "direction": "긍정"
  }}
]

index는 위 뉴스 목록의 [번호]와 정확히 일치해야 합니다. 중복 기사를 합칠 경우 대표 기사의 번호를 사용하세요.

[뉴스 목록]
{article_list}
"""


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


def generate_market_commentary(market_data, news_list, intraday_text="", trend_text="", consensus_text=""):
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

    # 뉴스 (제목 + 상세 요약 포함)
    data_summary += "\n주요 뉴스:\n"
    for n in news_list[:10]:
        title = n.get('summary_title', n.get('title', ''))
        detail = n.get('detail', '')
        data_summary += f"- {title}\n"
        if detail:
            data_summary += f"  {detail[:150]}\n"

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
당신은 증권사 리서치센터 수석 애널리스트입니다. 텔레그램 채널 구독자(개인 투자자)에게 전달하는 시황 코멘트를 작성합니다.

[문체]
- 짧은 단정형("~했습니다. ~보입니다.")을 지양하고, 흐름이 느껴지는 서술형으로 작성
- 한 문장이 짧으면 다음 문장과 연결해서 맥락을 만드세요
- 좋은 예: "장 초반 삼성전자 호실적에 힘입어 5500선을 돌파하는 듯했으나, 오후 들어 트럼프의 이란 공격 최후통첩이 재부각되면서 매물이 쏟아져 나왔고, 결국 상승분의 대부분을 반납한 채 보합권에서 마감했습니다."
- 나쁜 예: "코스피가 상승했습니다. 삼성전자가 올랐습니다. 외국인이 매도했습니다."

[핵심 원칙]
1. 인과관계 체인: "A 때문에 B가 발생했고, 이는 C로 이어졌습니다" — 모든 현상에는 이유가 있어야 함. 구체적 경로 제시 (예: "유가 급등 → 인플레 우려 → 금리 인하 지연 → 성장주 디레이팅")
2. 장중 흐름 서술: 시가→고가→저가→종가의 변화를 스토리로 풀어내세요
3. 과거 사례 비교: 유사한 상황이 과거에 있었다면 구체적 수치와 함께 언급
4. 컨센서스 대비 분석: 실적 발표 종목은 "컨센 N조 → 실제 N조 = N% 상회" 식으로. 발표된 실적은 "발표", 미발표는 "전망"으로 정확히 구분
5. 수급 해석: 외국인 매도를 과잉 해석하지 말 것. 개인 매도는 대부분 News Sell이나 손절이지 고차원 분석이 아님. 외국인 지분율 하락은 "바닥"이 아니라 "추세적 이탈" 가능성도 함께 제시
6. 밸류에이션 맥락: 12M 선행 PER이 제공되면 역사적 위치에서 해석하되, 낮은 PER이 반드시 저평가를 의미하지 않을 수 있음 (시장이 실적 지속성을 불신할 가능성)도 언급
7. 전략: 모호한 결론("선별적 접근") 금지. 방향성은 잡되 "~가 적절합니다", "~아닐까 싶습니다" 수준으로 제시. "20% 덜어내라", "지금 사라" 같은 구체적 비중 수치나 명령형은 절대 금지. 투자자문이 아니라 시황 해석이 목적.
8. 환율-외국인 연결: 환율 급등 시 외국인의 환차손 방어 매도 가능성, 금리 경로(인플레→금리인하 지연→디레이팅) 반드시 포함
9. 이전 시황 연결: 이전 시황 데이터가 있으면 연속성 부여
10. 톤: 한지영 애널리스트 스타일 참고. 데이터 기반으로 냉정하게 분석하되 결론은 "~생각합니다", "~싶습니다"로 부드럽게. 시장 참여자의 심리와 피로감도 읽어주는 톤.

[구조]

1단락: 시장 정의 + 장중 흐름 (4~5문장)
- 오늘 장을 한마디로 정의
- 장초부터 장마감까지 흐름을 스토리로 서술
- 이 흐름이 나온 배경/원인 (지정학, 실적, 글로벌 등)
- 현재 시장이 어떤 국면에 있는지 큰 그림

2단락: 섹터·종목 분석 (5~6문장)
- 강세/약세 섹터를 대표 종목과 함께 인과관계로 서술
- 거래대금/상승률 상위에서 특이 종목은 왜 움직였는지 뉴스와 매칭
- 개별 이슈 급등이 섹터 확산인지 단발성인지 판단
- 실적 발표 종목: 컨센 대비 서프라이즈/쇼크 구체적 분석
- 밸류에이션 관점 코멘트 (선행 PER 등)

3단락: 수급 + 전략 (4~5문장)
- 외국인/기관 연속 매수/매도 트렌드 해석 + 지분율 맥락
- 이 흐름이 지속될지 판단 근거
- 내일/이번 주 핵심 변수
- 방향성 제시 ("~가 적절합니다" 수준. 구체적 비중 수치나 명령형 금지)

[규칙]
- 지수 숫자 단순 나열 금지. 숫자는 맥락 속 의미 해석에만 사용.
- 한 문장에 숫자는 2개 이하. 숫자가 많으면 문장을 나누세요.
- 한 문단은 3~5문장. 텔레그램 모바일에서 읽기 편하게.
- 오늘 실적을 발표한 종목은 "발표"로, 아직 미발표인 종목은 "전망/추정"으로 정확히 구분.
- "N거래일 연속"은 2일 이상일 때만 사용. 1일은 "전환", "기록" 등으로 표현.
- 섹터 ETF 등락률과 개별 종목 등락률이 반대일 경우, 그 괴리를 반드시 설명.
- 핵심 변수는 긍정/부정 양쪽 시나리오 모두 언급 (예: "협상 타결 시 반등, 군사행동 시 추가 하락 가능")
- 데이터에 없는 사실을 만들지 마세요.
- 별표(**), 괄호([]), 제목, 번호 매기기 등 서식 없이 순수 텍스트만.
- 총 15~20문장.

시황만 작성하세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
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

    # 뉴스
    headlines = "\n".join([f"- {n.get('summary_title', n['title'])}" for n in news_list[:8]])
    data_summary += f"\n주요 뉴스:\n{headlines}"

    # 수급 트렌드
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    prompt = f"""{data_summary}

위 데이터를 바탕으로 전일 미국 증시 마감 리뷰 + 오늘 한국 증시 전망을 작성해주세요.
당신은 증권사 리서치센터 수석 애널리스트입니다.

[문체]
- 짧은 단정형을 지양하고 흐름이 느껴지는 서술형으로 작성
- 좋은 예: "트럼프의 이란 협상 회의론적 발언으로 유가가 100달러를 상회하고, 이에 따른 금리 급등이 성장주 전반의 할인율 부담을 키우면서 나스닥이 2%대 급락하는 전약후강의 흐름을 보였습니다."
- 나쁜 예: "나스닥이 하락했습니다. 유가가 상승했습니다."

[핵심 원칙]
1. 인과관계 체인으로 서술: 모든 현상에 원인과 결과를 연결
2. 과거 유사 사례 비교: 구체적 수치와 함께 (예: "딥시크 때 충격 1개월 미만, 이후 신고가 랠리")
3. 외국인 수급 트렌드: N일 연속 + 누적 금액 + 지분율 변화를 흐름으로 해석
4. 밸류에이션 맥락: 선행 PER 데이터가 있으면 역사적 위치에서 해석
5. 전략 구체성: "선별적 접근" 같은 모호한 결론 금지. 업종/비중/템포까지 구체적으로
6. 이전 시황 연결: 이전 데이터가 있으면 연속성 있게 이어가기

[구조]

1단락: 미장 큰 그림 (4~5문장)
- 전일 미장을 한마디로 정의하며 시작
- 시장을 움직인 핵심 동인과 인과관계
- 섹터·종목 흐름을 자연스럽게 녹여서 서술
- 현재 월가의 분위기/맥락

2단락: 한국 증시 전망 + 수급 + 전략 (5~6문장)
- 미장 흐름이 오늘 한국 장에 미칠 영향 (동조/수혜/피해 섹터)
- 외국인 수급 트렌드 해석과 지분율 맥락
- 오늘 핵심 이벤트/변수
- 방향성 제시 ("~가 적절합니다" 수준. 구체적 비중 수치나 명령형 금지)

[규칙]
- 지수 숫자 단순 나열 금지. 맥락 속에서만 사용.
- 데이터에 없는 사실 금지.
- 서식(별표, 괄호, 번호, 제목) 없이 순수 텍스트만.
- 한 문장에 숫자는 2개 이하. 숫자가 많으면 문장을 나누세요.
- 한 문단은 3~5문장. 텔레그램 모바일에서 읽기 편하게.
- "N거래일 연속"은 2일 이상일 때만 사용.
- 핵심 변수는 긍정/부정 양쪽 시나리오 모두 언급.
- 총 12~16문장.

시황만 작성하세요."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=PROMPT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"미장 시황 생성 실패: {e}"
