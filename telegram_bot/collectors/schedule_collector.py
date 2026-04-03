"""경제 일정 수집 (investing.com 크롤링 + DART 실적)"""
import datetime
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import DART_API_KEY


def fetch_economic_calendar(target_date=None):
    """investing.com 경제 캘린더 크롤링 (한국/미국 주요 일정)"""
    if target_date is None:
        target_date = datetime.date.today()

    date_str = target_date.strftime("%Y-%m-%d")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    try:
        url = f"https://kr.investing.com/economic-calendar/"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, "lxml")
        events = []

        # 경제 캘린더 테이블 파싱
        rows = soup.select("tr.js-event-item")
        for row in rows:
            try:
                time_el = row.select_one("td.time")
                country_el = row.select_one("td.flagCur span")
                event_el = row.select_one("td.event a")
                impact_el = row.select_one("td.sentiment")

                if not event_el:
                    continue

                event_time = time_el.get_text(strip=True) if time_el else ""
                country = country_el.get("title", "") if country_el else ""
                event_name = event_el.get_text(strip=True)

                # 영향도 (별 개수)
                impact = 0
                if impact_el:
                    impact = len(impact_el.select("i.grayFullBullishIcon"))

                # 한국, 미국, 중국, 일본만 필터
                target_countries = ["한국", "미국", "중국", "일본", "South Korea", "United States", "China", "Japan"]
                if not any(c in country for c in target_countries):
                    continue

                # 영향도 2 이상만
                if impact < 2:
                    continue

                events.append({
                    "시간": event_time,
                    "국가": country,
                    "이벤트": event_name,
                    "영향도": impact,
                })
            except Exception:
                continue
        return events
    except Exception as e:
        return [{"error": str(e)}]


def fetch_dart_earnings(target_date=None):
    """DART API로 실적 발표 일정 조회"""
    if not DART_API_KEY:
        return []

    if target_date is None:
        target_date = datetime.date.today()

    date_str = target_date.strftime("%Y%m%d")

    try:
        # 주요사항보고서 (실적 공시)
        url = "https://opendart.fss.or.kr/api/list.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de": date_str,
            "end_de": date_str,
            "pblntf_ty": "F",  # F: 사업보고서
            "page_count": 30,
        }
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            return []

        data = res.json()
        if data.get("status") != "000":
            return []

        results = []
        for item in data.get("list", []):
            results.append({
                "기업명": item.get("corp_name", ""),
                "보고서명": item.get("report_nm", ""),
                "접수일": item.get("rcept_dt", ""),
            })
        return results
    except Exception:
        return []


def fetch_tomorrow_schedule():
    """내일 일정 조회"""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    # 주말이면 월요일로
    while tomorrow.weekday() >= 5:
        tomorrow += datetime.timedelta(days=1)

    events = fetch_economic_calendar(tomorrow)
    earnings = fetch_dart_earnings(tomorrow)
    return {
        "date": tomorrow.strftime("%m월 %d일"),
        "events": events,
        "earnings": earnings,
    }


def fetch_today_schedule():
    """오늘 일정 조회"""
    today = datetime.date.today()
    events = fetch_economic_calendar(today)
    earnings = fetch_dart_earnings(today)
    return {
        "date": today.strftime("%m월 %d일"),
        "events": events,
        "earnings": earnings,
    }
