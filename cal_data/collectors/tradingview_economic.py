"""TradingView 경제 캘린더 수집 (경제지표 주 소스)

Investing.com이 데이터센터 IP(GitHub Actions/Lightsail)에서 429로 막혀 주 소스를 교체.
- 인증키 불필요 JSON API, 약 4~5주 앞까지 게시
- 시각은 UTC → KST 변환해서 저장
- 화이트리스트(RULES)에 있는 핵심 지표만 수집하고, 같은 시각에 함께 나오는
  세부 항목(CPI 전년비·전월비·근원 등)은 한 줄로 묶음
- 중앙은행 금리결정은 fixed_events가 공식 일정으로 관리하므로 제외 (중복 방지)
"""
import datetime
import time

import requests

URL = "https://economic-calendar.tradingview.com/events"
HEADERS = {
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
COUNTRIES = "US,KR,CN,JP,EU"
FLAGS = {"US": "🇺🇸", "KR": "🇰🇷", "CN": "🇨🇳", "JP": "🇯🇵", "EU": "🇪🇺"}
CHUNK_DAYS = 14
KST = datetime.timezone(datetime.timedelta(hours=9))
# 직전 실행에서 조회 실패한 구간 — update.py가 이 구간의 기존 일정은 교체하지 않고 보존
LAST_FAILED_RANGES: list[tuple[str, str]] = []

# (국가, 제목 접두어 목록, 한글 제목, 카테고리)
# 같은 국가·같은 시각에 같은 그룹 항목이 여러 개면 하나로 합침. 목록 첫 접두어가 대표 지표.
RULES = [
    ("US", ["Inflation Rate YoY", "Inflation Rate MoM", "Core Inflation Rate", "CPI"], "소비자물가(CPI)", "경제지표"),
    ("US", ["Non Farm Payrolls", "Unemployment Rate", "Average Hourly Earnings", "Participation Rate"], "고용보고서(비농업·실업률)", "경제지표"),
    ("US", ["Core PCE Price Index", "PCE Price Index", "Personal Income", "Personal Spending"], "PCE 물가·개인소득/지출", "경제지표"),
    ("US", ["GDP Growth Rate", "GDP Price Index"], "GDP 성장률", "경제지표"),
    ("US", ["PPI MoM", "PPI YoY", "Core PPI", "PPI"], "생산자물가(PPI)", "경제지표"),
    ("US", ["Retail Sales MoM", "Retail Sales Ex Autos", "Retail Sales Control Group"], "소매판매", "경제지표"),
    ("US", ["ISM Manufacturing PMI"], "ISM 제조업 PMI", "경제지표"),
    ("US", ["ISM Services PMI"], "ISM 서비스업 PMI", "경제지표"),
    ("US", ["JOLTs Job Openings"], "JOLTs 구인건수", "경제지표"),
    ("US", ["ADP Employment Change"], "ADP 민간고용", "경제지표"),
    ("US", ["Michigan Consumer Sentiment Prel"], "미시간대 소비자심리", "경제지표"),
    ("US", ["Durable Goods Orders MoM"], "내구재 주문", "경제지표"),
    ("US", ["FOMC Minutes"], "FOMC 의사록 공개", "통화정책"),
    ("US", ["Fed Chair"], "연준 의장 발언", "통화정책"),
    ("US", ["Jackson Hole"], "잭슨홀 미팅", "통화정책"),
    ("KR", ["Exports YoY", "Imports YoY", "Balance of Trade"], "수출입 동향", "경제지표"),
    ("KR", ["Inflation Rate YoY", "Inflation Rate MoM"], "소비자물가", "경제지표"),
    ("KR", ["GDP Growth Rate"], "GDP 성장률", "경제지표"),
    ("CN", ["Inflation Rate YoY", "Inflation Rate MoM", "PPI"], "물가(CPI·PPI)", "경제지표"),
    ("CN", ["Exports YoY", "Imports YoY", "Balance of Trade"], "수출입", "경제지표"),
    ("CN", ["GDP Growth Rate"], "GDP 성장률", "경제지표"),
    ("CN", ["Industrial Production", "Retail Sales", "Fixed Asset Investment"], "산업생산·소매판매", "경제지표"),
    ("CN", ["NBS Manufacturing PMI", "NBS Non Manufacturing PMI"], "국가통계국 PMI", "경제지표"),
    ("CN", ["RatingDog Manufacturing PMI"], "RatingDog 제조업 PMI", "경제지표"),
    ("CN", ["Loan Prime Rate"], "대출우대금리(LPR) 발표", "통화정책"),
    ("CN", ["Communist Party"], "공산당 전체회의", "정치/외교"),
    ("EU", ["Inflation Rate YoY Flash", "Core Inflation Rate YoY Flash", "Inflation Rate MoM Flash"], "유로존 소비자물가(속보)", "경제지표"),
    ("EU", ["GDP Growth Rate"], "유로존 GDP", "경제지표"),
    ("JP", ["Inflation Rate YoY", "Core Inflation Rate YoY"], "소비자물가", "경제지표"),
    ("JP", ["Tankan Large Manufacturers"], "단칸 지수(대기업 제조업)", "경제지표"),
]

# 중요도 '상'이어도 제외 — 금리결정은 fixed_events와 중복, 나머지는 한국 증시 영향 미미
EXCLUDE_PREFIXES = [
    "Fed Interest Rate Decision", "Fed Press Conference", "FOMC Economic Projections",
    "ECB Interest Rate Decision", "ECB Press Conference", "Deposit Facility Rate",
    "Main Refinancing Rate", "Marginal Lending",
    "BoJ Interest Rate Decision", "BoJ Press Conference", "Interest Rate Decision",
    "Building Permits", "Housing Starts", "Existing Home Sales", "New Home Sales",
    "Consumer Confidence", "Balance of Trade",
]

PERIOD_KR = {
    "Jan": "1월", "Feb": "2월", "Mar": "3월", "Apr": "4월", "May": "5월", "Jun": "6월",
    "Jul": "7월", "Aug": "8월", "Sep": "9월", "Oct": "10월", "Nov": "11월", "Dec": "12월",
    "Q1": "1분기", "Q2": "2분기", "Q3": "3분기", "Q4": "4분기",
}
# GDP 등 발표 단계 표기
STAGE_KR = [(" Adv", "속보치"), (" Prel", "예비치"), (" Second", "잠정치"), (" 2nd Est", "잠정치"),
            (" Third", "확정치"), (" 3rd Est", "확정치"), (" Final", "확정치")]


def _match_rule(country: str, title: str):
    for idx, (cty, prefixes, kr, cat) in enumerate(RULES):
        if cty != country:
            continue
        for p in prefixes:
            if title.startswith(p):
                return idx
    return None


def _fetch_chunk(from_date: datetime.date, to_date: datetime.date) -> list[dict] | None:
    params = {
        "from": f"{from_date.isoformat()}T00:00:00.000Z",
        "to": f"{to_date.isoformat()}T23:59:59.000Z",
        "countries": COUNTRIES,
    }
    try:
        res = requests.get(URL, params=params, headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"[TradingView] 요청 실패 ({from_date}~{to_date}): {e}")
        return None
    if res.status_code != 200:
        print(f"[TradingView] HTTP {res.status_code} ({from_date}~{to_date}) - 수집 실패")
        return None
    try:
        rows = res.json().get("result", [])
    except ValueError:
        print(f"[TradingView] JSON 파싱 실패 ({from_date}~{to_date}) - 차단 페이지 가능성")
        return None
    return rows


def fetch_tradingview_economic(from_date: datetime.date, to_date: datetime.date) -> list[dict] | None:
    """핵심 경제지표 수집. 전 구간 요청이 실패하면 None (호출부가 fallback 판단)."""
    LAST_FAILED_RANGES.clear()
    raw = []
    any_ok = False
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + datetime.timedelta(days=CHUNK_DAYS - 1), to_date)
        rows = _fetch_chunk(chunk_start, chunk_end)
        if rows is not None:
            any_ok = True
            raw.extend(rows)
        else:
            LAST_FAILED_RANGES.append((chunk_start.isoformat(), chunk_end.isoformat()))
        chunk_start = chunk_end + datetime.timedelta(days=1)
        if chunk_start <= to_date:
            time.sleep(0.5)

    if not any_ok:
        return None

    # (그룹 키) → 병합 이벤트
    groups: dict[tuple, dict] = {}
    seen_ids = set()
    for x in raw:
        if x.get("id") in seen_ids:
            continue
        seen_ids.add(x.get("id"))

        country = x.get("country", "")
        title = (x.get("title") or "").strip()
        if country not in FLAGS or not title or "Weekly" in title:
            continue
        importance = x.get("importance")
        importance = importance if importance is not None else -1

        rule_idx = _match_rule(country, title)
        if rule_idx is None:
            # 화이트리스트 밖이라도 '상' 중요도의 일회성 이벤트(정상회담 등)는 수집
            if importance < 1 or any(title.startswith(p) for p in EXCLUDE_PREFIXES):
                continue

        try:
            dt_utc = datetime.datetime.fromisoformat(x["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        dt_kst = dt_utc.astimezone(KST)
        ev_date = dt_kst.date()
        if not (from_date <= ev_date <= to_date):
            continue

        key = (country, rule_idx if rule_idx is not None else title, ev_date.isoformat())
        g = groups.get(key)
        if g is None:
            g = {"country": country, "rule": rule_idx, "title": title, "dt": dt_kst,
                 "period": x.get("period") or "", "importance": importance, "items": []}
            groups[key] = g
        g["importance"] = max(g["importance"], importance)
        if dt_kst < g["dt"]:
            g["dt"] = dt_kst
        g["items"].append(x)

    results = []
    for g in groups.values():
        country = g["country"]
        flag = FLAGS[country]
        if g["rule"] is not None:
            _, prefixes, kr_title, category = RULES[g["rule"]]
            # 대표 지표: 규칙의 첫 접두어와 일치하는 항목, 없으면 첫 항목
            lead = next((it for p in prefixes for it in g["items"] if it["title"].startswith(p)), g["items"][0])
        else:
            kr_title = g["title"]
            category = "정치/외교" if any(k in g["title"] for k in ("Summit", "Election", "Plenum")) else "경제지표"
            lead = g["items"][0]

        stage = next((kr for suffix, kr in STAGE_KR if suffix in lead["title"]), "")
        period = PERIOD_KR.get(g["period"], g["period"])
        label = kr_title + (f" {stage}" if stage else "")
        title = f"{flag} {label}" + (f" ({period})" if period else "")

        summary_parts = []
        forecast, previous = lead.get("forecast"), lead.get("previous")
        unit = lead.get("unit") or ""
        if forecast is not None:
            summary_parts.append(f"예상 {forecast}{unit}")
        if previous is not None:
            summary_parts.append(f"이전 {previous}{unit}")
        if len(g["items"]) > 1:
            summary_parts.append("포함: " + ", ".join(sorted({it["title"] for it in g["items"]})))
        elif g["rule"] is not None:
            summary_parts.append(lead["title"])

        ev = {
            "date": g["dt"].date().isoformat(),
            "time": g["dt"].strftime("%H:%M"),
            "category": category,
            "title": title,
            "source": "tradingview",
            "auto": True,
            "country": flag,
            "importance": g["importance"],
        }
        if summary_parts:
            ev["summary"] = " · ".join(summary_parts)
        results.append(ev)

    results.sort(key=lambda e: (e["date"], e["time"]))
    return _merge_multiday(results)


def _merge_multiday(events: list[dict]) -> list[dict]:
    """같은 제목의 정치/외교 이벤트가 연속 날짜에 반복되면 endDate로 묶음"""
    merged = []
    for ev in events:
        prev = next((m for m in reversed(merged)
                     if m["title"] == ev["title"] and m["category"] == "정치/외교"), None)
        if prev is not None:
            last = datetime.date.fromisoformat(prev.get("endDate", prev["date"]))
            if datetime.date.fromisoformat(ev["date"]) - last == datetime.timedelta(days=1):
                prev["endDate"] = ev["date"]
                continue
        merged.append(ev)
    return merged
