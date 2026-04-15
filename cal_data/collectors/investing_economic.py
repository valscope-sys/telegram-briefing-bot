"""Investing.com 경제지표 캘린더 스크래핑 (AJAX API)"""
import re
import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
}

AJAX_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"

# 국가 코드 (Investing.com 내부 ID)
COUNTRY_IDS = {
    "72": "US", "5": "CN", "25": "JP", "34": "KR",
    "32": "EU", "6": "GB", "37": "DE",
}
COUNTRY_EMOJI = {"US": "🇺🇸", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷", "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪"}

MONETARY_KEYWORDS = [
    "interest rate", "rate decision", "fomc", "fed ", "ecb", "boj", "boe",
    "monetary policy", "beige book",
]

SKIP_KEYWORDS = [
    "auction", "bond auction", "bobl auction", "bund auction", "bill auction",
    "tic ", "redbook", "cushing",
]


def fetch_investing_economic(from_date: datetime.date = None, to_date: datetime.date = None) -> list[dict]:
    """Investing.com 경제지표 캘린더 스크래핑 (날짜 범위 지원)"""
    if from_date is None:
        from_date = datetime.date.today()
    if to_date is None:
        to_date = from_date + datetime.timedelta(days=7)

    # 최대 30일씩 나눠서 호출 (서버 부하 방지)
    all_results = []
    current = from_date
    while current < to_date:
        chunk_end = min(current + datetime.timedelta(days=30), to_date)
        chunk = _fetch_chunk(current, chunk_end)
        all_results.extend(chunk)
        current = chunk_end + datetime.timedelta(days=1)

    # 중복 제거
    seen = set()
    unique = []
    for ev in all_results:
        key = ev["date"] + "|" + ev["title"]
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    print(f"[Investing] {len(unique)}건 수집 ({from_date} ~ {to_date})")
    return unique


def _fetch_chunk(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """한 번의 AJAX 호출로 데이터 가져오기"""
    try:
        data = {
            "country[]": list(COUNTRY_IDS.keys()),
            "dateFrom": from_date.isoformat(),
            "dateTo": to_date.isoformat(),
            "timeZone": 18,  # KST
            "timeFilter": "timeRemain",
            "currentTab": "custom",
            "limit_from": 0,
        }
        res = requests.post(AJAX_URL, data=data, headers=HEADERS, timeout=20)
        if res.status_code != 200:
            print(f"[Investing] HTTP {res.status_code}")
            return []

        json_data = res.json()
        html = json_data.get("data", "")
        if not html:
            return []

        return _parse_html(html)
    except Exception as e:
        print(f"[Investing] Error: {e}")
        return []


def _parse_html(html: str) -> list[dict]:
    """AJAX 응답 HTML 파싱"""
    soup = BeautifulSoup(html, "lxml")
    results = []
    current_date = ""

    for tr in soup.select("tr"):
        # 날짜 헤더
        td_day = tr.select_one("td.theDay")
        if td_day:
            text = td_day.get_text(strip=True)
            m = re.search(r"(\w+),\s+(\w+)\s+(\d+),\s+(\d{4})", text)
            if m:
                month_map = {
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "may": 5, "june": 6, "july": 7, "august": 8,
                    "september": 9, "october": 10, "november": 11, "december": 12,
                }
                month = month_map.get(m.group(2).lower(), 0)
                if month:
                    current_date = f"{int(m.group(4))}-{month:02d}-{int(m.group(3)):02d}"
            continue

        if not current_date:
            continue

        # 이벤트 행
        cls = " ".join(tr.get("class", []))
        if "js-event-item" not in cls:
            continue

        tds = tr.select("td")
        if len(tds) < 5:
            continue

        # 시간
        time_td = tds[0]
        time_text = time_td.get_text(strip=True)

        # 국가
        flag_span = tr.select_one("td.flagCur span")
        country_code = ""
        if flag_span:
            title = flag_span.get("title", "")
            # title은 국가 전체 이름
            country_map = {
                "United States": "US", "China": "CN", "Japan": "JP",
                "South Korea": "KR", "Euro Zone": "EU", "United Kingdom": "GB",
                "Germany": "DE",
            }
            country_code = country_map.get(title, "")

        if not country_code:
            continue

        # 이벤트명
        event_td = tr.select_one("td.event")
        if not event_td:
            continue
        event_a = event_td.select_one("a")
        event_name = event_a.get_text(strip=True) if event_a else event_td.get_text(strip=True)
        if not event_name:
            continue

        # 스킵
        if any(kw in event_name.lower() for kw in SKIP_KEYWORDS):
            continue

        # 영향도 (bull 아이콘 수)
        sentiment_td = tr.select_one("td.sentiment")
        if sentiment_td:
            bulls = len(sentiment_td.select("i.grayFullBullishIcon"))
            if bulls < 2:
                continue
        else:
            continue

        # 예상/이전
        forecast = ""
        previous = ""
        for td in tds:
            td_id = td.get("id", "")
            if "forecast" in td_id:
                forecast = td.get_text(strip=True)
            elif "previous" in td_id:
                previous = td.get_text(strip=True)

        emoji = COUNTRY_EMOJI.get(country_code, "")
        is_monetary = any(kw in event_name.lower() for kw in MONETARY_KEYWORDS)
        category = "통화정책" if is_monetary else "경제지표"

        ev = {
            "date": current_date,
            "time": time_text if time_text and ":" in time_text else "",
            "category": category,
            "title": f"{emoji} {event_name}".strip(),
            "source": "investing",
            "auto": True,
            "country": emoji,
        }
        summary_parts = []
        if forecast and forecast != "\xa0":
            summary_parts.append(f"예상: {forecast}")
        if previous and previous != "\xa0":
            summary_parts.append(f"이전: {previous}")
        if summary_parts:
            ev["summary"] = " | ".join(summary_parts)

        results.append(ev)

    return results
