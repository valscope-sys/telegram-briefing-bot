"""Investing.com 경제지표 캘린더 스크래핑 (AJAX API)

Cloudflare가 python-requests의 TLS 지문을 차단하므로
curl_cffi(impersonate='chrome')로 우회한다.
"""
import re
import time
import datetime
from urllib.parse import urlencode

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup

HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
    "Content-Type": "application/x-www-form-urlencoded",
}

AJAX_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"

# 국가 코드 (Investing.com 내부 ID)
COUNTRY_IDS = {
    "72": "US", "5": "CN", "25": "JP", "34": "KR",
    "32": "EU", "6": "GB", "37": "DE",
}
COUNTRY_EMOJI = {"US": "🇺🇸", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷", "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪"}

# Investing.com 시간대 ID.
# 88 = Asia/Seoul (KST, UTC+9) - 실측 검증: timeZone=88로 요청 시
#   '신규 실업수당 청구건수'(매주 목 21:30 KST)가 21:30으로 수신됨.
#   기존 값 18은 UTC+3(여름 기준)으로 6시간 빠른 시각이 저장되던 버그.
TIME_ZONE_ID = 88

# 응답당 최대 행 수 (서버측 캡) - 도달 시 절단 경고
ROW_CAP = 200

# 호출 간 대기 (rate limit 회피)
CALL_INTERVAL_SEC = 1.0

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

    # 7일씩 나눠서 호출 (응답당 200행 캡 - 밀집 구간 절단 방지)
    all_results = []
    current = from_date
    first_call = True
    while current <= to_date:
        chunk_end = min(current + datetime.timedelta(days=6), to_date)
        if not first_call:
            time.sleep(CALL_INTERVAL_SEC)  # 호출 간격 (429 방지)
        first_call = False
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
    """한 번의 AJAX 호출로 데이터 가져오기 (429 시 30초 대기 후 1회 재시도)"""
    # curl_cffi에 dict를 그대로 넘기면 country[] 리스트 인코딩이 깨져 404
    # → 사전 urlencode 필수
    payload = urlencode(
        [("country[]", c) for c in COUNTRY_IDS.keys()]
        + [
            ("dateFrom", from_date.isoformat()),
            ("dateTo", to_date.isoformat()),
            ("timeZone", TIME_ZONE_ID),
            ("timeFilter", "timeRemain"),
            ("currentTab", "custom"),
            ("limit_from", 0),
        ]
    )

    for attempt in range(2):
        try:
            res = cf_requests.post(
                AJAX_URL, data=payload, headers=HEADERS,
                timeout=20, impersonate="chrome",
            )
        except Exception as e:
            print(f"[Investing] Error: {e}")
            return []

        if res.status_code == 429:
            if attempt == 0:
                print("[Investing] HTTP 429 (rate limit) - 30초 대기 후 재시도")
                time.sleep(30)
                continue
            print("[Investing] HTTP 429 (rate limit) - 재시도에도 실패, 청크 스킵")
            return []

        if res.status_code == 403:
            print(f"[Investing] BLOCKED - Cloudflare 차단 감지 (HTTP 403, {from_date}~{to_date})")
            return []

        if res.status_code != 200:
            print(f"[Investing] HTTP {res.status_code} ({from_date}~{to_date})")
            return []

        try:
            json_data = res.json()
        except Exception as e:
            print(f"[Investing] JSON 파싱 실패 (차단 페이지 가능성): {e}")
            return []

        html = json_data.get("data", "")
        if not html:
            return []

        # 응답당 200행 캡 - 도달 시 절단 경고
        row_count = html.count("js-event-item")
        if row_count >= ROW_CAP:
            print(f"[Investing] 경고: 응답 {row_count}행 - {ROW_CAP}행 캡 도달, 데이터 절단 가능 ({from_date}~{to_date})")

        return _parse_html(html)

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
