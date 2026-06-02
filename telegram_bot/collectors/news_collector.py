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

# 프롬프트 버전 — v2 전용 (v1은 2026-06 제거, A/B 검증 후 v2 완전 정착).
# 환경변수는 로그/호환성 위해 유지하나 v2만 지원.
_PROMPT_VERSION = os.environ.get("COMMENTARY_PROMPT_VERSION", "v2").lower()


# ── RSS 피드 목록 ──
# 2026-04-22 대대적 점검: 11개 피드 검증 → 유효 URL로 교체 or 제거
#   · UA 헤더 없으면 WSJ 등 일부 피드가 0건 반환 → fetch_rss_news에서 agent 지정
#   · Reuters 공식 RSS 서비스 종료 → Google News 프록시 대체
#   · 공식 RSS가 사라진 피드는 제거 (이데일리/금융위/한은/산자부/디지털타임스)
RSS_FEEDS = [
    # ── 국내 종합·산업 ──
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news", "group": "국내"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/", "group": "국내"},
    {"name": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml", "group": "국내"},
    {"name": "이데일리 증시", "url": "https://rss.edaily.co.kr/stock_news.xml", "group": "국내"},
    {"name": "전자신문", "url": "https://rss.etnews.com/Section902.xml", "group": "국내"},
    # ── 해외 종합 ──
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "group": "해외"},
    {"name": "WSJ", "url": "https://news.google.com/rss/search?q=site:wsj.com+markets&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    {"name": "Bloomberg Tech", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+technology&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "group": "해외"},
    {"name": "Financial Times", "url": "https://news.google.com/rss/search?q=site:ft.com+markets&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    # ── 산업·리서치 (반도체·전기전자) ──
    # 시황 정확도 ↑ — 미래/SK 등 증권사가 인용하는 1차 소스 추가
    {"name": "TrendForce", "url": "https://www.trendforce.com/news/feed/", "group": "해외"},
    {"name": "Digitimes", "url": "https://news.google.com/rss/search?q=site:digitimes.com+chips+OR+semiconductor&hl=en-US&gl=US&ceid=US:en", "group": "해외"},
    {"name": "SemiAnalysis", "url": "https://semianalysis.com/feed/", "group": "해외"},
    # ── 섹터 전문 ──
    {"name": "Electrek", "url": "https://electrek.co/feed/", "group": "해외"},
    {"name": "InsideEVs", "url": "https://insideevs.com/feed/", "group": "해외"},
    {"name": "FiercePharma", "url": "https://www.fiercepharma.com/rss/xml", "group": "해외"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "group": "해외"},
    {"name": "World Nuclear News", "url": "https://www.world-nuclear-news.org/rss", "group": "해외"},
]


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

    from telegram_bot.prompts_v2 import PROMPT_ANALYZE_V2, PROMPT_SYSTEM_V2
    prompt = PROMPT_ANALYZE_V2.format(article_list=article_list)
    sys_prompt = PROMPT_SYSTEM_V2

    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
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


def _build_news_section(news_list, max_items=6):
    """뉴스 데이터를 프롬프트용 텍스트로 변환.

    2026-05-29 축소: 뉴스 블록이 비대(10개×최대500자≈5,000자)해 LLM이 "다 써야 하나"
    압박을 받고 본문에 뉴스를 과다 삽입. 6개·요약 150자로 줄이고 본문(body 300자) 제거.
    뉴스는 시황의 '왜'를 붙이는 증거일 뿐 — 전문 주입 불필요. 깊은 맥락은 web_search로.
    """
    lines = ["\n주요 뉴스 (시황 해석의 증거용 — 본문에 나열·전재 금지):"]
    for n in news_list[:max_items]:
        title = n.get('summary_title', n.get('title', ''))
        detail = n.get('detail', '')
        sector = n.get('sector', '')
        direction = n.get('direction', '')

        header = f"- [{sector}] {title}" if sector else f"- {title}"
        if direction:
            header += f" ({direction})"
        lines.append(header)

        if detail:
            lines.append(f"  요약: {detail[:150]}")
    return "\n".join(lines)


def _build_upcoming_schedule_section():
    """차주 5영업일 일정 — 시황 본문 'D-day' 자연 녹임용.

    별도 일정 카드와 다른 용도: 시황 마지막 문단에서 다가오는 매크로 이벤트(PCE·FOMC·CPI)나
    중요 실적 발표를 한지영처럼 본문에 녹이도록 LLM에 컨텍스트로 전달.
    """
    try:
        from telegram_bot.collectors.schedule_collector import fetch_upcoming_week_schedule
        upcoming = fetch_upcoming_week_schedule()
    except Exception:
        return ""

    if not upcoming:
        return ""

    lines = ["다가오는 5영업일 주요 일정 (시황 본문 D-day 자연 녹임용 — 별도 리스트 형식 금지):"]
    for s in upcoming:
        date_label = s.get("date", "")
        events = s.get("events", [])
        earnings = s.get("earnings", [])
        if not events and not earnings:
            continue
        bits = []
        for ev in events[:6]:
            t = ev.get("이벤트", "").strip()
            tm = ev.get("시간", "")
            if tm:
                bits.append(f"{tm} {t}")
            else:
                bits.append(t)
        for er in earnings[:4]:
            bits.append(f"실적 {er.get('기업명','')}")
        if bits:
            lines.append(f"  {date_label}: {' / '.join(bits)}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _build_period_returns_section(period_returns):
    """지수 기간 수익률 — 쏠림 정량화용 (압축). 본문엔 의미있는 격차만 인용 유도."""
    if not period_returns:
        return ""
    lines = [
        "지수 기간 수익률 % (5일/20일/60일) — 시장 쏠림 정량화용 (예: 대형주 vs 소형주 격차).",
        "  ※ 본문엔 그 날 의미있는 격차 1~2개만 압축 인용. 전부 나열 금지.",
    ]
    has_data = False
    for name in ["KOSPI", "KOSDAQ", "대형주", "중형주", "소형주"]:
        r = period_returns.get(name)
        if not r:
            continue
        parts = []
        for k in ["5일", "20일", "60일"]:
            v = r.get(k)
            parts.append(f"{v:+.1f}" if v is not None else "—")
        lines.append(f"  {name}: {' / '.join(parts)}")
        has_data = True
    return "\n".join(lines) if has_data else ""


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
    period_returns = market_data.get("period_returns", {})

    data_summary = "=== 오늘 시장 데이터 ===\n"
    for name, info in indices.items():
        if isinstance(info, dict) and "error" not in info:
            line = f"{name}: {info.get('현재가', 0)} ({info.get('등락률', 0):+.2f}%)"
            adv = info.get("상승")
            dec = info.get("하락")
            stl = info.get("보합")
            if adv is not None and dec is not None:
                diff = adv - dec
                line += f" — 상승 {adv} / 하락 {dec}"
                if stl is not None:
                    line += f" / 보합 {stl}"
                line += f" (차이 {diff:+d})"
            trv = info.get("거래대금")
            trv_avg = info.get("거래대금_20일평균")
            if trv:
                line += f", 거래대금 {trv/1e8:,.0f}억"
                if trv_avg:
                    ratio = trv / trv_avg * 100
                    line += f" (20일 평균 대비 {ratio:.0f}%)"
            data_summary += line + "\n"

    if isinstance(investors, dict) and "error" not in investors:
        frgn = investors.get("외국인금액", 0) / 100
        inst = investors.get("기관금액", 0) / 100
        pers = investors.get("개인금액", 0) / 100
        # 당일 수급은 장 직후 잠정치 — 익일 확정 시 조정 가능 (이브닝↔익일 모닝 값 불일치 원인 명시)
        inv_date = investors.get("날짜", "")
        today_str = datetime.date.today().strftime("%Y%m%d")
        label = " (장 직후 잠정치, 익일 확정 시 소폭 조정 가능)" if inv_date == today_str else ""
        data_summary += f"\n수급{label}: 외국인 {frgn:+,.0f}억 / 기관 {inst:+,.0f}억 / 개인 {pers:+,.0f}억\n"

    # 지수 기간 수익률 (쏠림 정량화용 — 압축 인용)
    pr_text = _build_period_returns_section(period_returns)
    if pr_text:
        data_summary += f"\n{pr_text}\n"

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
        data_summary += "\n거래대금 상위 30종목 (단위: 억원):\n"
        for i, item in enumerate(trade_rank):
            trv = item.get("거래대금", 0) / 1e8
            data_summary += f"  {i+1}. {item.get('종목명', '')} {item.get('등락률', 0):+.2f}%  {trv:,.0f}억\n"

        # 거래대금 집중도 자동 계산 (시장 전체 거래대금 vs 상위 N종목)
        kospi_trv = indices.get("KOSPI", {}).get("거래대금", 0) if isinstance(indices.get("KOSPI"), dict) else 0
        kosdaq_trv = indices.get("KOSDAQ", {}).get("거래대금", 0) if isinstance(indices.get("KOSDAQ"), dict) else 0
        market_total = kospi_trv + kosdaq_trv
        if market_total > 0:
            top2 = sum(item.get("거래대금", 0) for item in trade_rank[:2])
            top5 = sum(item.get("거래대금", 0) for item in trade_rank[:5])
            top10 = sum(item.get("거래대금", 0) for item in trade_rank[:10])
            data_summary += (
                f"  ※ 거래대금 집중도: "
                f"상위 2종목 {top2/market_total*100:.1f}% / "
                f"상위 5종목 {top5/market_total*100:.1f}% / "
                f"상위 10종목 {top10/market_total*100:.1f}% (KOSPI+KOSDAQ 합계 대비)\n"
            )

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

    # 뉴스 (제목 + 요약)
    data_summary += _build_news_section(news_list)

    # 장중 흐름 데이터
    if intraday_text:
        data_summary += f"\n{intraday_text}\n"

    # 수급 트렌드 데이터
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    # 실적 컨센서스 데이터
    if consensus_text:
        data_summary += f"\n{consensus_text}\n"

    # 차주 일정 (시황 본문 D-day 자연 녹임용)
    upcoming_text = _build_upcoming_schedule_section()
    if upcoming_text:
        data_summary += f"\n{upcoming_text}\n"

    from telegram_bot.prompts_v2 import PROMPT_EVENING_TEMPLATE_V2, PROMPT_SYSTEM_V2
    prompt = PROMPT_EVENING_TEMPLATE_V2.format(data_summary=data_summary)
    sys_prompt = PROMPT_SYSTEM_V2

    print(f"[COMMENTARY] 이브닝 시황 모델: {COMMENTARY_MODEL} / prompt {_PROMPT_VERSION} / thinking=ON")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=8000,  # thinking 5K + output 3K 여유
            # temperature 명시 X — Extended thinking 모드는 temperature=1 강제
            thinking={
                "type": "enabled",
                "budget_tokens": 5000,  # 사고 깊이 — 김경민·한지영 수준의 사건 연결·테마 묶기 유도
            },
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 2,
                "allowed_callers": ["direct"],
            }],
            system=sys_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        for b in response.content:
            if b.type == "server_tool_use" and getattr(b, "name", "") == "web_search":
                q = (b.input or {}).get("query", "")
                print(f"[WEB_SEARCH] \"{q}\"")
        search_count = sum(1 for b in response.content if b.type == "server_tool_use")
        thinking_tokens = sum(
            len(getattr(b, "thinking", "")) for b in response.content if b.type == "thinking"
        )
        u = response.usage
        print(
            f"[USAGE] 이브닝 시황 — 검색 {search_count}회, thinking 블록 글자수 {thinking_tokens}, "
            f"input={u.input_tokens}, output={u.output_tokens}"
        )
        # type="text" 블록만 추출 (thinking 블록 자동 제외)
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
                # 전일 시장 폭 + 거래대금 (한지영 수준 인용 가능하게)
                kospi_adv = kospi.get("상승")
                kospi_dec = kospi.get("하락")
                kosdaq_adv = kosdaq.get("상승") if isinstance(kosdaq, dict) else None
                kosdaq_dec = kosdaq.get("하락") if isinstance(kosdaq, dict) else None
                if kospi_adv is not None and kospi_dec is not None:
                    kr_investors_section += (
                        f"전일 시장 폭 — KOSPI 상승 {kospi_adv} / 하락 {kospi_dec} (차이 {kospi_adv-kospi_dec:+d})"
                    )
                    if kosdaq_adv is not None and kosdaq_dec is not None:
                        kr_investors_section += (
                            f", KOSDAQ 상승 {kosdaq_adv} / 하락 {kosdaq_dec} (차이 {kosdaq_adv-kosdaq_dec:+d})"
                        )
                    kr_investors_section += "\n"
                kospi_trv = kospi.get("거래대금", 0)
                kospi_trv_avg = kospi.get("거래대금_20일평균", 0)
                if kospi_trv:
                    line = f"전일 KOSPI 거래대금: {kospi_trv/1e8:,.0f}억"
                    if kospi_trv_avg:
                        line += f" (20일 평균 대비 {kospi_trv/kospi_trv_avg*100:.0f}%)"
                    kr_investors_section += line + "\n"
        # 전일 한국 지수 기간 수익률 (쏠림 정량화 — 대형 vs 소형 격차)
        pr_text = _build_period_returns_section(domestic_data.get("period_returns", {}))
        if pr_text:
            kr_investors_section += f"\n{pr_text}\n"

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
    data_summary += _build_news_section(news_list, max_items=6)

    # 수급 트렌드
    if trend_text:
        data_summary += f"\n{trend_text}\n"

    # 차주 일정 (시황 본문 D-day 자연 녹임용)
    upcoming_text = _build_upcoming_schedule_section()
    if upcoming_text:
        data_summary += f"\n{upcoming_text}\n"

    from telegram_bot.prompts_v2 import PROMPT_MORNING_TEMPLATE_V2, PROMPT_SYSTEM_V2
    prompt = PROMPT_MORNING_TEMPLATE_V2.format(data_summary=data_summary)
    sys_prompt = PROMPT_SYSTEM_V2

    print(f"[COMMENTARY] 모닝 시황 모델: {COMMENTARY_MODEL} / prompt {_PROMPT_VERSION} / thinking=ON")
    try:
        response = client.messages.create(
            model=COMMENTARY_MODEL,
            max_tokens=8000,  # thinking 5K + output 3K 여유
            # temperature 명시 X — Extended thinking 모드는 temperature=1 강제
            thinking={
                "type": "enabled",
                "budget_tokens": 5000,
            },
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 3,
                "allowed_callers": ["direct"],
            }],
            system=sys_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        for b in response.content:
            if b.type == "server_tool_use" and getattr(b, "name", "") == "web_search":
                q = (b.input or {}).get("query", "")
                print(f"[WEB_SEARCH] \"{q}\"")
        search_count = sum(1 for b in response.content if b.type == "server_tool_use")
        thinking_tokens = sum(
            len(getattr(b, "thinking", "")) for b in response.content if b.type == "thinking"
        )
        u = response.usage
        print(
            f"[USAGE] 모닝 시황 — 검색 {search_count}회, thinking 블록 글자수 {thinking_tokens}, "
            f"input={u.input_tokens}, output={u.output_tokens}"
        )
        text_parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_parts).strip()
    except Exception as e:
        return f"미장 시황 생성 실패: {e}"
