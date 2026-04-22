"""뉴스 수집 (RSS + 크롤링) + Claude API 분석/필터링"""
import os
import json
import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import ANTHROPIC_API_KEY

# 시황 생성 모델 선택 (환경변수 또는 기본값)
# COMMENTARY_MODEL 옵션:
#   - shorthand: sonnet, opus, haiku, sonnet-4, sonnet-4-5, sonnet-4-6, opus-4, opus-4-5, opus-4-6, opus-4-7
#   - full id:   claude-sonnet-4-6, claude-opus-4-7, claude-haiku-4-5-20251001 등 (claude- 접두어)
# 기본값: Sonnet 4.6 (2026-04-22 업그레이드)
_MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "sonnet-4": "claude-sonnet-4-20250514",
    "sonnet-4-5": "claude-sonnet-4-5-20250929",
    "sonnet-4-6": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
    "opus-4": "claude-opus-4-20250514",
    "opus-4-1": "claude-opus-4-1-20250805",
    "opus-4-5": "claude-opus-4-5-20251101",
    "opus-4-6": "claude-opus-4-6",
    "opus-4-7": "claude-opus-4-7",
    "haiku": "claude-haiku-4-5-20251001",
    "haiku-4-5": "claude-haiku-4-5-20251001",
}
_raw_model = os.environ.get("COMMENTARY_MODEL", "sonnet").lower().strip()
if _raw_model.startswith("claude-"):
    COMMENTARY_MODEL = _raw_model  # full id 직접 전달
else:
    COMMENTARY_MODEL = _MODEL_MAP.get(_raw_model, "claude-sonnet-4-6")

# 프롬프트 버전 선택 (환경변수)
# COMMENTARY_PROMPT_VERSION=v2 → 슬림화된 v2 프롬프트 (정적 ~61% 감축)
# 기본 v1 유지 — A/B 검증 후 전환
_PROMPT_VERSION = os.environ.get("COMMENTARY_PROMPT_VERSION", "v1").lower()


# ── RSS 피드 목록 ──
# 2026-04-22 대대적 점검: 11개 피드 검증 → 유효 URL로 교체 or 제거
#   · UA 헤더 없으면 WSJ 등 일부 피드가 0건 반환 → fetch_rss_news에서 agent 지정
#   · Reuters 공식 RSS 서비스 종료 → Google News 프록시 대체
#   · 공식 RSS가 사라진 피드는 제거 (이데일리/금융위/한은/산자부/디지털타임스)
RSS_FEEDS = [
    # 국내 종합
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news", "group": "국내"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/", "group": "국내"},
    # 해외 종합
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "group": "해외"},
    {"name": "WSJ", "url": "https://news.google.com/rss/search?q=site:wsj.com+markets&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    # 섹터 전문
    {"name": "TrendForce", "url": "https://www.trendforce.com/news/feed/", "group": "해외"},
    {"name": "Electrek", "url": "https://electrek.co/feed/", "group": "해외"},
    {"name": "InsideEVs", "url": "https://insideevs.com/feed/", "group": "해외"},
    {"name": "FiercePharma", "url": "https://www.fiercepharma.com/rss/xml", "group": "해외"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "group": "해외"},
    {"name": "World Nuclear News", "url": "https://www.world-nuclear-news.org/rss", "group": "해외"},
]


PROMPT_SYSTEM = """당신은 한국 주식시장 전문 투자 리서치 애널리스트이며, 텔레그램 증시 브리핑 채널을 운영합니다.

절대 규칙:
1. 시스템이 제공한 데이터와 뉴스에 있는 내용만 사용하세요. 데이터에 없는 수치, 이벤트를 절대 만들어내지 마세요.
2. 뉴스 목록에 없는 뉴스를 인용하거나 참조하지 마세요.
3. 수급 연속일수는 '수급 트렌드' 데이터에 명시된 숫자만 사용하세요.
4. 시장 방향성을 단정하지 마세요. "추진력을 제공합니다", "강세 출발" 같은 단정 금지. "우호적 환경", "가능성" 수준으로.
5. 컨텍스트에 있는 과거 이벤트를 오늘 처음 발생한 것처럼 쓰지 마세요.
6. 실적 추정치(매출, 영업이익 등)를 쓸 때 반드시 출처를 명시하세요. "시장 컨센서스 기준", "○○증권 추정" 등. 출처를 모르면 "실적 호전 기대감" 수준으로 톤 다운.
7. 경제지표(취업자, PPI, CPI 등) 수치를 인용할 때 비교 기준(전년동월비/전월비)과 시장 예상 대비 서프라이즈 방향을 반드시 포함.
8. VIX는 등락률뿐 아니라 절대 레벨도 함께 표기. 예: "VIX 19.5(-4.0%)"
9. 목표가 상향/하향을 언급하려면 구체적 수치(종목명, 이전가, 변경가, 증권사)가 있어야 합니다. 없으면 쓰지 마세요."""

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

[우선 포함 — 이 키워드가 포함된 뉴스는 중요도를 높게 평가]
- 한국 수출·통상에 직접 영향: Korea tariff, 한국 관세, 한국 수출, 한국 무역, Korea trade, Korea sanction
- 한국 기업 직접 언급: Samsung, Hyundai, SK, LG, Kia
- 원달러/환율 급변: won, KRW, dollar-won
- 한국 시장 급락/급등 원인: KORU, Korea ETF
- 중동 지정학/종전 관련 (이란 전쟁 하위 이벤트까지 모두 포함):
  · 이란/Iran, 이스라엘/Israel, 레바논/Lebanon, 헤즈볼라/Hezbollah, 하마스/Hamas
  · 휴전/ceasefire, 정전/truce, 평화협정/peace deal, 종전/end of war, 협상 타결/agreement reached
  · 호르무즈/Hormuz, 핵 협상/nuclear deal, 중동 리스크/Middle East risk
  · 트럼프 중동 발언/Trump Middle East, 네타냐후/Netanyahu, 아운/Aoun
- 미국 장후 실적 발표 (Netflix, NFLX, TSLA 등 주요 기업 earnings release)
- 역사적 마일스톤: N거래일 연속 상승/하락, longest streak, ATH, record high, N년 만의 최대

하 수준(단순 해설, 반복, 증시 무관)은 출력하지 마세요.

[중요 — 중동 이벤트 커버리지]
이란 전쟁은 여러 하위 이벤트로 진행됩니다. "이란" 키워드가 없어도 다음은 모두 이란 전쟁 관련으로 분류하여 우선 포함:
- 이스라엘의 레바논·시리아·헤즈볼라 관련 군사/외교 행동
- 호르무즈 해협 통항/봉쇄 관련
- 미국-이스라엘, 미국-레바논 정상 회담/통화
- 중동 내 어떤 국가든 휴전/정전 합의
이 중 하나라도 해당되면 반드시 포함 (한국 증시에 유가/지정학 경로로 영향).

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

    # WSJ 등 UA 없으면 빈 응답 주는 피드 대응
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    all_news = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"], agent=UA)
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

    if _PROMPT_VERSION == "v2":
        from telegram_bot.prompts_v2 import PROMPT_ANALYZE_V2, PROMPT_SYSTEM_V2
        prompt = PROMPT_ANALYZE_V2.format(article_list=article_list)
        sys_prompt = PROMPT_SYSTEM_V2
    else:
        prompt = PROMPT_ANALYZE.format(article_list=article_list)
        sys_prompt = PROMPT_SYSTEM

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            temperature=0,  # 뉴스 필터 재현성 보장
            system=sys_prompt,
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

    # 업종별 수급 (키움 API)
    sector_flow = market_data.get("sector_investor_flow", [])
    if sector_flow:
        data_summary += "\n업종별 외국인 순매수 (억원):\n"
        for sf in sector_flow[:5]:
            data_summary += f"  {sf['업종']}: 외국인 {sf['외국인']:+,}억 / 기관 {sf['기관']:+,}억\n"
        data_summary += "  ...\n"
        for sf in sector_flow[-3:]:
            data_summary += f"  {sf['업종']}: 외국인 {sf['외국인']:+,}억 / 기관 {sf['기관']:+,}억\n"

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
            for name in ["미국 3M", "미국 2Y", "미국 10Y", "국고채 3Y", "국고채 10Y"]:
                b = bonds.get(name, {})
                if b and "error" not in b and b.get("금리", 0):
                    data_summary += f"  {name}: {b.get('금리', 0):.3f}% ({b.get('전일대비', 0):+.3f}%p)\n"
            # 장단기 스프레드 — 2Y-10Y (표준), 3M-10Y (NY Fed 리세션 지표) 둘 다 제공
            us2y = bonds.get("미국 2Y", {}).get("금리", 0)
            us3m = bonds.get("미국 3M", {}).get("금리", 0)
            us10y = bonds.get("미국 10Y", {}).get("금리", 0)
            if us2y and us10y:
                spread = us10y - us2y
                data_summary += f"  10Y-2Y 스프레드: {spread:+.3f}%p"
                if spread < 0:
                    data_summary += " (장단기 역전, 경기침체 우려 시그널)"
                data_summary += "\n"
            if us3m and us10y:
                spread3m = us10y - us3m
                data_summary += f"  10Y-3M 스프레드: {spread3m:+.3f}%p (NY Fed 리세션 지표)\n"

        # 환율/DXY
        fx = global_data.get("fx", {})
        if fx:
            usdkrw = fx.get("USD/KRW", {})
            if usdkrw and "error" not in usdkrw:
                data_summary += f"\n환율:\n  USD/KRW: {usdkrw.get('현재가', 0):,.1f} ({usdkrw.get('전일대비', 0):+.2f})\n"
            dxy = fx.get("DXY", {})
            if dxy and "error" not in dxy and dxy.get("현재가"):
                data_summary += f"  DXY(달러인덱스): {dxy['현재가']:.2f} ({dxy.get('등락률', 0):+.2f}%)\n"

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

    if _PROMPT_VERSION == "v2":
        from telegram_bot.prompts_v2 import PROMPT_EVENING_TEMPLATE_V2, PROMPT_SYSTEM_V2
        prompt = PROMPT_EVENING_TEMPLATE_V2.format(data_summary=data_summary)
        sys_prompt = PROMPT_SYSTEM_V2
    else:
        prompt = f"""{data_summary}

위 데이터를 바탕으로 오늘 시장 시황을 작성해주세요.
증권사 리서치센터 애널리스트 팀장이 텔레그램 채널 구독자(개인 투자자)에게 장 마감 시황을 전달합니다.

[작성 방식 — 3단계 사고]

**1단계: 시장 큰 그림 먼저 (데이터 중심 + 구조적 해석 허용)**
- 제공된 데이터(지수·섹터·수급·장중 흐름·환율·원자재·금리)로 오늘 시장의 큰 그림을 그려라.
- "왜 이런 움직임이 나왔는가"를 해석하라. 매크로 맥락·섹터 로테이션 패턴·업황 사이클 같은 구조적 지식을 적극 활용해도 된다.
- 예: 외국인 대규모 매도 + 원달러 상승 → 환차손 우려로 인한 롤오버 압력 해석
- 예: 반도체 강세 + 방산 약세 → 리스크온 회귀 신호로 해석

**2단계: 필요 시 웹 검색으로 보강 (web_search 도구 — 최대 3회)**
한국 장중 발생했으나 수집된 뉴스에 빠진 중요 이벤트가 있으면 검색하라.
검색을 사용해야 하는 경우:
- 특정 종목·섹터의 이상 급등락 원인이 뉴스에 없음
- 장중 발표된 정책/공시/실적 (한국 기업 실적 가이던스, 해외 정책 발표 등)
- 한국시간 오전에 발표된 중국·일본 경제지표 결과
- 중동 지정학 사건 (유가 급변 원인 등)
검색 원칙:
- **기본 전제: 장중 수집된 뉴스·데이터·수급·장중 흐름만으로 충분히 설명되면 검색하지 마라.** 이브닝은 이미 한국 장중 정보가 풍부해서 검색이 필요한 경우가 드물다.
- 검색은 "뉴스에 빠진 중요 사실"이 있다고 판단될 때만 실행.
- 공신력 있는 언론(Reuters, Bloomberg, CNBC, 한경, 매경, 연합) 결과만 신뢰.
- 검색 결과가 모호하면 사용하지 마라.

**3단계: 뉴스는 근거·증거 자료로 배치**
- 뉴스 섹션은 시황의 주재료가 아니라, 1단계에서 해석한 시장 흐름을 **뒷받침하는 증거**로 사용하라.
- 뉴스 내용을 요약·나열하지 말고, 1단계 해석과 연결시켜 인용하라.
- 웹 검색으로 얻은 팩트도 동일하게 취급.
- "검색 결과에 따르면", "웹에서 확인한 바" 같은 인용 투 표현 금지. 애널리스트가 이미 아는 사실처럼 서술하라.

[해석 vs 팩트 — 엄격히 구분]
- **해석·맥락·로테이션·매크로 연결**: 너의 지식으로 자유롭게 작성 가능
- **구체적 팩트(인사 변경, 실적 숫자, 특정 사건 발생 여부, 목표가 변경, 정책 발표)**: 반드시 제공된 뉴스/데이터에 있어야 함. 뉴스에 없으면 절대 창작 금지.
- 불확실한 팩트는 제공된 뉴스에 명시된 경우에만 언급. 확인 안 되면 쓰지 마라.

[핵심 원칙: "So what?" — 해석과 맥락이 가치다]
- HTS에서 볼 수 있는 숫자 나열은 가치가 없다. 투자자가 이 시황을 읽고 "그래서 내일 뭘 주목해야 하는지" 판단 재료를 얻어야 한다.
- "뭐가 있었다" 나열이 아니라 "왜 그랬고, 그래서 뭐가 달라지는지" 해석을 써라.
- 뉴스 섹션과 문장 단위로 겹치지 마라. 뉴스 섹션은 개별 팩트, 시황은 종합 해석.

[문체]
- 서술형. "~습니다/입니다" 기본. "~싶습니다", "~봅니다"는 가끔만.
- "~네요" 금지. 동료 애널리스트 메신저 톤. 전문성 유지.

[구조 — 반드시 아래 템플릿을 그대로 따르세요. 소제목 이모지·텍스트를 정확히 복사할 것]

━━━ 템플릿 시작 ━━━
📈 오늘의 국면

(1번 섹션 본문)

🔍 핵심 동인

(2번 섹션 본문)

🔄 섹터 로테이션

(3번 섹션 본문)

💰 수급

(4번 섹션 본문)

⚠️ 리스크 체크

(5번 섹션 본문)
━━━ 템플릿 끝 ━━━

위 5개 소제목을 정확히 복사하여 사용하고, 추가·삭제·수정하지 마세요.
각 소제목은 한 줄 단독, 앞뒤 빈 줄 필수. 소제목 뒤에 바로 본문이 붙으면 안 됩니다.

📈 오늘의 국면

1: 국면 정의 (1~2문장)
- 오늘 시장을 한마디로. "뭐가 달라진 날인지" 정의.
- 지수 등락률은 괄호 안에 간결하게.

🔍 핵심 동인

2: 핵심 동인 (2~3문장)
- 오늘 시장을 움직인 1순위 원인이 무엇인지.
- 인과 방향: 이벤트(원인)가 먼저, 유가/금리/환율(파생 결과)이 뒤.
  나쁜 예: "유가 급락으로 인플레 완화" (파생 변수를 원인처럼 씀)
  좋은 예: "미-이란 협상 재개 기대(원인)로 유가 급락(결과), 이는 인플레 부담 완화로 이어지며 성장주에 우호적 환경 조성"
- 채권금리 방향이 데이터에 있으면 반드시 여기서 언급.

🔄 섹터 로테이션

3: 섹터 로테이션 (3~4문장)
- 어디서 빠진 돈이 어디로 갔는지. 로테이션 흐름 중심.
  나쁜 예: "반도체 +2.47%, 방산 +2.59%, 자동차 +1.87%" (숫자 나열)
  좋은 예: "에너지에서 빠진 자금이 반도체·소비재로 유입. 시장이 전쟁 종결 시나리오에 베팅하기 시작한 신호."
- 대표 종목은 등락률만 나열하지 말고 "왜" 올랐는지/빠졌는지를 반드시 붙이세요.
- ETF vs 개별종목 괴리가 있으면 설명.
- 섹터별 유가 영향 방향성을 정확히:
  유가 상승 수혜: 정유, E&P
  유가 하락 수혜: 항공, 해운(벙커유), 소비재, 화학(나프타)
  유가 하락 부정적: 정유, E&P, 에너지장비

💰 수급

4: 수급 (2~3문장)
- 외국인/기관/개인 금액 + 방향 전환 여부.
- "1거래일 연속"은 틀린 표현. 1일은 "전환"으로. 2일 이상만 "연속".
- 가능하면 업종별 집중도 언급 (반도체에 집중인지, 광범위 분산인지).
- 개인 매도는 "차익실현"으로 간결하게. 심리 과잉해석 금지.

⚠️ 리스크 체크

5: 리스크 체크 — 시나리오형 (2~3문장)
- "~할 수도 있고 ~할 수도 있다" 양비론 금지.
- 대신 구체적 시나리오 + 핵심 변수 + 시간대.
  나쁜 예: "불확실성이 여전히 변수로 남아있습니다."
  좋은 예: "핵심 변수는 4/21 휴전 만료. 협상 성공 시 유가 80달러대 진입 가능, 결렬 시 110달러 재돌파 리스크."
- 매번 같은 문구(사이드카 N회, 서킷 N회 등) 반복 인용 금지. 매일 다른 표현으로.

[데이터 활용]
- 시황에서 언급하는 모든 종목명은 반드시 제공된 데이터에 있어야 합니다. 데이터에 없는 종목 금지.
- 데이터(뼈)에 있는 종목을 먼저 선택하고, 뉴스(살)로 이유를 붙이세요.
- 환율/지수 수치는 제공된 종가 데이터만. 장중 수치는 "장중 한때"로 구분.
- 채권금리, 심리지표, 환율 데이터가 있으면 빠짐없이 활용.
- 뉴스 데이터에 없는 정책명, 펀드명, 프로젝트명을 만들어내지 마세요.
- 종목 급등락의 이유를 뉴스에서 못 찾으면 시장 전체 흐름으로 설명. 억지로 붙이지 마세요.

[금지]
- 화살표(→) 금지
- 교과서/증권방송 용어 금지. "전쟁 수혜 섹터/기대감" 같은 부정확한 범주화 금지. 실제 인과관계를 명확히.
- 종목 등락률만 줄줄이 나열 금지. 반드시 "왜"를 붙이거나, 섹터 단위로 묶어서 해석
- 개별 중소형주 별도 문단 금지. 시총 상위만 기업명 언급
- "주목됩니다", "참고점이 될 수 있습니다" 같은 채움말 금지
- 뉴스 섹션 내용 재탕 금지. 시황은 종합 해석.
- 지수가 사상 최고치를 경신했으면(S&P, NASDAQ 등) 반드시 명시. N거래일 연속 상승/N년 만의 최대 같은 마일스톤도 동일.
- 테슬라 AI칩/자율주행 이슈로 현대차·기아가 동반 상승한 것처럼 서술 금지. 각사 고유 드라이버 근거 있을 때만.
- 개인 매도를 "자연스러운 차익실현" 같은 긍정 편향으로 포장 금지. "외국인·기관 매수 vs 개인 매도 구도" 중립적 표현.
- 데이터 간 모순이 있으면(예: 미장 상승인데 KORU 급락) 반드시 지적하고 가능한 원인을 분석하세요. 긍정 데이터만 골라쓰고 부정 데이터를 무시하면 안 됩니다.
- 서식 없이 텍스트만
- 총 14~18문장

시황만 작성하세요."""
        sys_prompt = PROMPT_SYSTEM

    print(f"[COMMENTARY] 이브닝 시황 모델: {COMMENTARY_MODEL} / prompt {_PROMPT_VERSION}")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=2000,
            temperature=0.3,  # 시황 일관성 + 최소 창의성
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 2,  # 이브닝은 장중 데이터 이미 수집돼있어 2회로 제한
                "allowed_callers": ["direct"],
            }],
            system=sys_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        # 웹 검색 사용 시 server_tool_use/web_search_tool_result 블록 섞임 → text 블록만 추출
        for b in response.content:
            if b.type == "server_tool_use" and getattr(b, "name", "") == "web_search":
                q = (b.input or {}).get("query", "")
                print(f"[WEB_SEARCH] \"{q}\"")
        search_count = sum(1 for b in response.content if b.type == "server_tool_use")
        u = response.usage
        print(f"[USAGE] 이브닝 시황 — 검색 {search_count}회, input={u.input_tokens}, output={u.output_tokens}")
        text_parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_parts).strip()
    except Exception as e:
        return f"시황 해석 생성 실패: {e}"


def generate_morning_commentary(global_data, news_list, trend_text="", domestic_data=None):
    """Claude API로 전일 미장 시황 해석 생성 (모닝 브리핑용)

    domestic_data: fetch_all_domestic() 결과 — 데이터 카드와 동일 소스 주입 (정합성)
    """
    if not ANTHROPIC_API_KEY:
        return ""

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    indices = global_data.get("indices", {})
    us_sectors = global_data.get("us_sectors", {})
    us_stocks = global_data.get("us_stocks", {})
    commodities = global_data.get("commodities", {})
    fx = global_data.get("fx", {})

    # 전일 국내 수급 — 데이터 카드와 동일 소스 (정합성 확보)
    kr_investors_section = ""
    if domestic_data:
        investors = domestic_data.get("investors", {})
        if investors and "error" not in investors:
            inv_date = investors.get("날짜", "")
            date_label = f"{inv_date[:4]}-{inv_date[4:6]}-{inv_date[6:8]}" if len(inv_date) == 8 else "전일"
            frgn = investors.get("외국인금액", 0) / 100  # 백만원 → 억원
            inst = investors.get("기관금액", 0) / 100
            pers = investors.get("개인금액", 0) / 100
            kr_investors_section = (
                f"\n전일({date_label}) 국내 수급 (KOSPI, 억원):\n"
                f"  외국인 {frgn:+,.0f}억 / 기관 {inst:+,.0f}억 / 개인 {pers:+,.0f}억\n"
                f"  ※ 이 숫자가 데이터 카드에 표시된 값. 시황에서 '전일 수급'으로 인용 시 반드시 이 값을 사용.\n"
            )
        dom_indices = domestic_data.get("indices", {})
        if dom_indices:
            kospi = dom_indices.get("KOSPI", {})
            kosdaq = dom_indices.get("KOSDAQ", {})
            if kospi and "error" not in kospi:
                kr_investors_section += (
                    f"전일 KOSPI: {kospi.get('현재가', 0):,.2f} ({kospi.get('등락률', 0):+.2f}%) / "
                    f"KOSDAQ: {kosdaq.get('현재가', 0):,.2f} ({kosdaq.get('등락률', 0):+.2f}%)\n"
                )

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
    dxy = fx.get("DXY", {})
    if dxy and "error" not in dxy and dxy.get("현재가"):
        data_summary += f"  DXY(달러인덱스): {dxy['현재가']:.2f} ({dxy.get('등락률', 0):+.2f}%)\n"

    # 야간 프록시 (KORU 등)
    korea_proxies = global_data.get("korea_proxies", {})
    if korea_proxies:
        proxy_lines = []
        for name, info in korea_proxies.items():
            if isinstance(info, dict) and "error" not in info and info.get("현재가"):
                pct = info.get("등락률", 0)
                proxy_lines.append(f"  {name}: ${info['현재가']:.2f} ({pct:+.2f}%)")
        if proxy_lines:
            data_summary += "\n야간 프록시 (NY close 기준 — 한국 장 마감 후 미국 시점):\n"
            data_summary += "\n".join(proxy_lines) + "\n"
            data_summary += "  ※ 시점 주의: EWY/KORU 는 미국 장 마감 가격(KST 06:00경). 한국 장 개장 전 야간선물(^KS200)과 시점 다를 수 있음.\n"
            # KORU 경고 자동 주입 (3x 레버리지 → ±3% = 실제 갭 1%, 의미 있는 시그널 시작점)
            koru = korea_proxies.get("KORU", {})
            if koru and abs(koru.get("등락률", 0)) >= 3:
                koru_pct = koru["등락률"]
                implied = koru_pct / 3
                data_summary += f"  ⚠️ KORU {koru_pct:+.2f}% (3x 레버리지 → 실제 예상 갭 {implied:+.1f}%)\n"

    # 채권금리 — 3M / 2Y / 10Y (NY Fed 표준 + 시장 표준 스프레드)
    bonds = global_data.get("bonds", {})
    if bonds and "error" not in bonds:
        data_summary += "\n채권금리:\n"
        for name in ["미국 3M", "미국 2Y", "미국 10Y"]:
            b = bonds.get(name, {})
            if b and "error" not in b and b.get("금리", 0):
                data_summary += f"  {name}: {b.get('금리', 0):.3f}% ({b.get('전일대비', 0):+.3f}%p)\n"
        us2y = bonds.get("미국 2Y", {}).get("금리", 0)
        us3m = bonds.get("미국 3M", {}).get("금리", 0)
        us10y = bonds.get("미국 10Y", {}).get("금리", 0)
        if us2y and us10y:
            spread = us10y - us2y
            data_summary += f"  10Y-2Y 스프레드: {spread:+.3f}%p"
            if spread < 0:
                data_summary += " (장단기 역전)"
            data_summary += "\n"
        if us3m and us10y:
            data_summary += f"  10Y-3M 스프레드: {us10y - us3m:+.3f}%p\n"

    # 심리지표
    sentiment = global_data.get("sentiment", {})
    if sentiment:
        fg = sentiment.get("Fear & Greed", {})
        if fg and "error" not in fg:
            data_summary += f"\n심리지표:\n  Fear & Greed Index: {fg.get('점수', 0)}점 ({fg.get('등급', '')})\n"
        pc = sentiment.get("Put/Call Ratio", {})
        if pc:
            data_summary += f"  Put/Call Ratio: {pc.get('비율', 0)} ({pc.get('해석', '')})\n"

    # 전일 국내 수급 (데이터 카드와 동일 숫자 — 정합성 필수)
    if kr_investors_section:
        data_summary += kr_investors_section

    # 뉴스 (본문 포함)
    data_summary += _build_news_section(news_list, max_items=8)

    # 수급 트렌드
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    if _PROMPT_VERSION == "v2":
        from telegram_bot.prompts_v2 import PROMPT_MORNING_TEMPLATE_V2, PROMPT_SYSTEM_V2
        prompt = PROMPT_MORNING_TEMPLATE_V2.format(data_summary=data_summary)
        sys_prompt = PROMPT_SYSTEM_V2
    else:
        sys_prompt = PROMPT_SYSTEM
        prompt = f"""{data_summary}

위 데이터를 바탕으로 전일 미국 증시 마감 리뷰 + 오늘 한국 증시 체크포인트를 작성해주세요.
증권사 리서치센터 애널리스트 팀장이 텔레그램 채널 구독자(개인 투자자)에게 보내는 모닝 시황입니다.

[작성 방식 — 3단계 사고]

**1단계: 시장 큰 그림 먼저 (데이터 중심 + 구조적 해석 허용)**
- 제공된 데이터(지수, 섹터, 환율, 금리, 원자재, 수급, 야간 프록시)로 먼저 오늘 시장의 큰 그림을 그려라.
- 숫자만 나열하지 말고 "왜 이런 움직임이 나왔는가"를 해석하라. 이 해석에는 매크로 맥락·섹터 로테이션 패턴·지정학 흐름 같은 구조적 지식을 적극 활용해도 된다.
- 예: 10Y 금리 급등 + 성장주 약세 → 연준 매파 시나리오 재부상으로 해석
- 예: 에너지 약세 + 기술주 강세 → 리스크온 자금 이동으로 해석

**2단계: 필요 시 웹 검색으로 보강 (web_search 도구 — 최대 3회)**
수집된 뉴스 목록에서 설명되지 않는 중요한 움직임이 있으면 웹 검색을 사용하라.
검색을 사용해야 하는 경우:
- 데이터에 특정 종목·지수의 이상 급등락이 있는데 뉴스에 원인이 없음 (예: 테슬라 +8% 이유)
- 주요 지수의 N거래일 연속 상승/하락, ATH 경신, X년 만의 최대 등 마일스톤 확인
- 미국 장 마감 후 한국시간 새벽에 발표된 실적 결과 (Netflix, TSLA 등)
- 한국시간 새벽에 발생한 지정학 이벤트 (중동 휴전, 정상 통화 등)
- 중요한 경제지표 발표의 컨센 대비 서프라이즈 방향
검색 원칙:
- **기본 전제: 수집된 뉴스와 데이터만으로 시장 움직임이 충분히 설명되면 검색하지 마라.** 매번 의무적으로 쓸 필요 없음.
- 검색은 "뉴스에 빠진 중요 사실"이 있다고 판단될 때만 실행 (위 목록 기준).
- 공신력 있는 언론(Reuters, Bloomberg, CNBC, WSJ, 한경, 매경) 결과만 신뢰.
- 검색 결과가 모호하면 사용하지 마라.
- 불필요한 검색은 비용만 늘리고 시황 품질에 기여하지 않는다.

**3단계: 뉴스는 근거·증거 자료로 배치**
- 뉴스 섹션은 시황의 주재료가 아니라, 1단계에서 해석한 시장 흐름을 **뒷받침하는 증거**로 사용하라.
- 뉴스 내용을 요약·나열하지 말고, 1단계 해석과 연결시켜 인용하라.
- 웹 검색으로 얻은 팩트도 동일하게 취급 — 자연스럽게 문장에 녹여라.
- "검색 결과에 따르면", "웹에서 확인한 바", "조사에 따르면" 같은 인용 투 표현 금지. 애널리스트가 이미 아는 사실처럼 서술하라. 예: "나스닥은 13거래일 연승이 끊기며 0.26% 하락했습니다"(○) / "검색해보니 나스닥은 13거래일 연승이 끊긴 것으로 확인됩니다"(✗).

[해석 vs 팩트 — 엄격히 구분]
- **해석·맥락·로테이션·매크로 연결**: 너의 지식으로 자유롭게 작성 가능
- **구체적 팩트(인사 변경, 실적 숫자, 특정 사건 발생 여부, 목표가 변경, 정책 발표)**: 반드시 제공된 뉴스/데이터에 있어야 함. 뉴스에 없으면 절대 창작 금지.
- 불확실한 팩트(예: "애플 CEO가 교체되었다", "나스닥 13연속 상승")는 제공된 뉴스에 명시된 경우에만 언급. 확인 안 되면 쓰지 마라.
- 데이터에는 있지만 뉴스에 없는 경우: 데이터 중심으로 해석 (예: "테슬라 +8% 급등이 데이터에 있으면 뉴스에 구체 원인이 없어도 '성장주 순환매의 대장 역할' 정도로 구조적 해석 허용")

[핵심 원칙: "So what?" — 해석과 맥락이 가치다]
- 숫자 나열은 HTS에서 볼 수 있으므로 가치가 없다. "왜 그랬고, 그래서 오늘 뭘 봐야 하는지"를 써라.
- 뉴스 섹션과 문장 단위로 겹치지 마라. 시황은 종합 해석, 뉴스는 개별 팩트.

[문체]
- 서술형. "~습니다/입니다" 기본. "~네요" 금지. 동료 애널리스트 메신저 톤.

[정보 cutoff — 반드시 준수]
- 이 시황은 미국 시장 마감(한국시간 04:00~05:00) 기준 분석입니다.
- 미국 장 마감 이후에 발표된 경제지표, 뉴스, 이벤트는 '미국 증시 마감 리뷰'에 사용하지 마세요.
- 오늘 아침에 발표된 데이터(예: 중국 GDP, 아시아 경제지표)는 '오늘 한국 증시 체크포인트' 섹션에서만 언급하세요.

[구조 — 반드시 아래 템플릿을 그대로 따르세요. 소제목 이모지·텍스트를 정확히 복사할 것]

━━━ 템플릿 시작 ━━━
🇺🇸 미국 증시 마감 리뷰

(1번 섹션 본문)

(2번 섹션 본문)

🇰🇷 오늘 한국 증시 체크포인트

(3번 섹션 본문)

(4번 섹션 본문)
━━━ 템플릿 끝 ━━━

위 두 소제목(🇺🇸 미국 증시 마감 리뷰, 🇰🇷 오늘 한국 증시 체크포인트)은 반드시 한 줄로 단독 표기하고, 소제목 앞뒤로 빈 줄을 둡니다.
소제목을 빼거나, 다른 소제목(예: 📈, 🔍, 💰)을 추가하거나, 소제목 문구를 바꾸지 마세요.

1: 미장 핵심 동인 (2~3문장)
- 숫자 나열이 아니라 "왜" 올랐는지/빠졌는지 중심으로.
- 인과 방향: 이벤트(원인)가 먼저, 유가/금리(파생 결과)가 뒤.
- 경제지표(CPI, PPI, 고용 등)가 뉴스 데이터에 있으면 반드시 여기서 언급. 컨센 대비 서프라이즈 방향 포함.
- 지수 등락률은 괄호 안에 간결하게. 예: "S&P500(+1.2%), 나스닥(+2.0%)"

2: 섹터 로테이션 + 금리/통화/원자재 (3~4문장)
- 어디서 빠진 돈이 어디로 갔는지 로테이션 흐름.
- 종목 등락률만 나열 금지. "왜" 올랐는지를 반드시 붙이세요.
- 채권금리 방향(10년물 수준 + 스프레드)이 데이터에 있으면 반드시 언급.
- DXY(달러인덱스)가 데이터에 있으면 반드시 언급. 원달러만으로는 달러 약세인지 원화 강세인지 구분 불가.
- [환율 해석 규칙 — 절대 틀리지 말 것]
  · USD/KRW의 등락을 %로 환산: (전일대비원) / (현재가) × 100
  · DXY 등락률(%) vs USD/KRW 등락률(%) 비교:
    USD/KRW 상승폭 > DXY 상승폭 → "원화 상대적 약세" (바스켓 평균보다 원화가 더 많이 약세)
    USD/KRW 상승폭 < DXY 상승폭 → "원화 상대적 강세"
    USD/KRW 하락 + DXY 상승 → "원화 강세" (명확)
    USD/KRW 상승 + DXY 하락 → "원화 약세" (명확)
  · "원달러 상승에 그쳐 원화 강세" 같은 직관적 표현 금지. 반드시 % 비교.
  · 예시: DXY +0.15%, USD/KRW +0.25% → "DXY 상승폭보다 원달러 상승폭이 커 상대적 원화 약세"
- 원자재(금, 구리)도 데이터에 있으면 언급. 금 방향은 심리 시그널.
- 섹터별 유가 영향 방향성:
  유가 상승 수혜: 정유, E&P / 유가 하락 수혜: 항공, 해운, 소비재, 화학(나프타)
  유가 하락 부정적: 정유, E&P

🇰🇷 오늘 한국 증시 체크포인트

3: 오늘 한국 체크포인트 (3~4문장)
- 뉴스 섹션 내용 재탕 금지. 개별 뉴스를 종합해서 "시장 뷰"로 엮으세요.
- 첫 문장은 매크로(유가/환율/지정학)부터. 방향성 단정 금지. 긍정+부정 병렬.
- 섹터 단위로 수혜/리스크 양면 서술. 시총 상위만 기업명 언급.
- 야간 프록시(KORU 등) 데이터가 있으면 언급 여부를 강도별 차등 판단. 3x 레버리지 특성상 작은 움직임은 노이즈:
  · |KORU| < 3%: 노이즈, 언급 금지 (KOSPI 일평균 변동성 내. 매일 등장하면 AI 템플릿 느낌)
  · 3 ≤ |KORU| < 5%: 맥락에 자연스럽게 녹일 수 있을 때만
  · |KORU| ≥ 5%: 반드시 언급. 3배 레버리지(÷3=실제 갭) 설명 포함.
  미장이 올랐는데 KORU가 급락했다면 한국 특유의 리스크(관세, 환율 등) 시그널이므로 ≥5% 에서는 필수 경고.
- 이 시황은 07:00 발송. 한국 장은 09:00 개장. "장 초반 상승세", "프리마켓 약세" 같은 장중 묘사 절대 금지.

4: 수급 + 리스크 체크 (2~3문장)
- 외국인/기관 수급. "1거래일 연속"은 틀린 표현. 1일은 "전환".
- 양비론 금지. 구체적 시나리오 + 핵심 변수 + 시간대.
  나쁜 예: "불확실성이 변수로 남아있습니다"
  좋은 예: "핵심 변수는 4/21 휴전 만료. 협상 성공 시 유가 80달러대, 결렬 시 110달러 리스크."
- 매번 같은 문구 반복 금지. 매일 다른 표현으로.

[데이터 활용]
- 모든 종목명은 제공된 데이터에 있어야 합니다. 데이터(뼈) 먼저, 뉴스(살)로 이유.
- 수치는 종가 데이터만. 뉴스 데이터에 없는 정책명/펀드명 금지.
- "~예상됩니다" 1~2회 이내. "주목됩니다" 금지.
- 지수 사상 최고치(ATH) 경신 시 "사상 처음 N,000선 돌파", "N월 이후 최고" 등 반드시 역사적 맥락 명시.
- 역사적 마일스톤은 ATH뿐 아니라 N거래일 연속 상승/하락, X년 만의 최대 상승률, 특정 지수 레벨 돌파 등도 포함. 뉴스 데이터에서 확인된 마일스톤은 반드시 언급.
- 중동 지정학 이벤트는 "이란"에 국한 말고 하위 이벤트(이스라엘-레바논 휴전, 헤즈볼라 관련, 호르무즈 해협, 네타냐후·아운 통화 등)를 구체적으로 서술. 뉴스에 있으면 반드시 핵심 동인 또는 체크포인트에 반영.
- "전쟁 수혜 섹터/기대감" 부정확한 범주화 금지. 구체적 산업재/방산 등으로 분류.
- 테슬라의 AI칩/자율주행/로보택시 관련 뉴스는 반드시 "AI/자율주행" 분류. 현대차/기아가 테슬라와 함께 상승했을 때 "테슬라 급등 영향"이 아니라 각사의 고유 드라이버(피지컬AI, 하이브리드 판매 등)를 언급. 섹터 동조 표현은 근거 있을 때만.
- 수급 해석 시 순매수 "연속"뿐 아니라 금액 규모 변화도 언급. 예: "외국인 2거래일 연속 순매수이나 전일 +4,973억 대비 +46억으로 급감, 사실상 관망 전환."
- 단일 종목 뉴스(상한가, 성과급 등)를 장세 전체로 확대 해석 금지.
- 개인 매도를 "자연스러운 차익실현", "건전한 물량 소화" 같은 긍정 편향 표현 금지. 객관적으로 "외국인·기관 매수 vs 개인 매도 구도" 수준으로 기술.
- 데이터 간 모순(예: 미장 상승인데 KORU 급락) 반드시 지적. 긍정만 골라쓰기 금지.
- "전쟁 수혜 섹터" 같은 부정확한 범주화 금지.
- 서식 없이 텍스트만.
- 총 12~16문장

시황만 작성하세요."""

    print(f"[COMMENTARY] 모닝 시황 모델: {COMMENTARY_MODEL} / prompt {_PROMPT_VERSION}")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=2000,
            temperature=0.3,  # 시황 일관성 + 최소 창의성
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 3,
                "allowed_callers": ["direct"],  # 모델이 PTC 미지원 → 직접 호출만
            }],
            system=sys_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        for b in response.content:
            if b.type == "server_tool_use" and getattr(b, "name", "") == "web_search":
                q = (b.input or {}).get("query", "")
                print(f"[WEB_SEARCH] \"{q}\"")
        search_count = sum(1 for b in response.content if b.type == "server_tool_use")
        u = response.usage
        print(f"[USAGE] 모닝 시황 — 검색 {search_count}회, input={u.input_tokens}, output={u.output_tokens}")
        text_parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_parts).strip()
    except Exception as e:
        return f"미장 시황 생성 실패: {e}"
