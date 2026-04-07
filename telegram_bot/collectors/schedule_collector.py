"""경제 일정 수집 (네이버 금융 + 고정 일정 + DART)"""
import datetime
import requests
from bs4 import BeautifulSoup
from telegram_bot.config import DART_API_KEY


# 2026년 주요 글로벌 경제 일정 (수동 관리, 월 1회 업데이트)
MAJOR_EVENTS_2026 = [
    # FOMC 회의
    {"date": "20260128", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20260318", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20260506", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20260617", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20260729", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20260916", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20261028", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    {"date": "20261216", "time": "04:00", "country": "🇺🇸", "event": "FOMC 금리 결정"},
    # 미국 CPI (매월 둘째주 화/수)
    {"date": "20260414", "time": "21:30", "country": "🇺🇸", "event": "미국 CPI (3월)"},
    {"date": "20260513", "time": "21:30", "country": "🇺🇸", "event": "미국 CPI (4월)"},
    {"date": "20260610", "time": "21:30", "country": "🇺🇸", "event": "미국 CPI (5월)"},
    {"date": "20260715", "time": "21:30", "country": "🇺🇸", "event": "미국 CPI (6월)"},
    # 미국 고용
    {"date": "20260410", "time": "21:30", "country": "🇺🇸", "event": "미국 비농업 고용 (3월)"},
    {"date": "20260508", "time": "21:30", "country": "🇺🇸", "event": "미국 비농업 고용 (4월)"},
    {"date": "20260605", "time": "21:30", "country": "🇺🇸", "event": "미국 비농업 고용 (5월)"},
    # 한국은행 금통위
    {"date": "20260416", "time": "10:00", "country": "🇰🇷", "event": "한국은행 금통위 금리 결정"},
    {"date": "20260528", "time": "10:00", "country": "🇰🇷", "event": "한국은행 금통위 금리 결정"},
    {"date": "20260716", "time": "10:00", "country": "🇰🇷", "event": "한국은행 금통위 금리 결정"},
    # 한국 수출입
    {"date": "20260401", "time": "09:00", "country": "🇰🇷", "event": "한국 수출입 통계 (3월)"},
    {"date": "20260501", "time": "09:00", "country": "🇰🇷", "event": "한국 수출입 통계 (4월)"},
    # 중국 PMI
    {"date": "20260430", "time": "10:30", "country": "🇨🇳", "event": "중국 제조업 PMI (4월)"},
    {"date": "20260531", "time": "10:30", "country": "🇨🇳", "event": "중국 제조업 PMI (5월)"},
]


def _get_major_events(target_date):
    """고정 일정에서 해당 날짜 이벤트 조회"""
    date_str = target_date.strftime("%Y%m%d")
    return [e for e in MAJOR_EVENTS_2026 if e["date"] == date_str]


def fetch_naver_economic_calendar(target_date=None):
    """네이버 금융 경제 캘린더 크롤링"""
    if target_date is None:
        target_date = datetime.date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    events = []
    try:
        url = f"https://finance.naver.com/marketindex/worldDailyQuote.naver?date={date_str}"
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "lxml")
            for row in soup.select("table tbody tr"):
                cols = row.select("td")
                if len(cols) >= 3:
                    time_str = cols[0].get_text(strip=True)
                    country = cols[1].get_text(strip=True)
                    event_name = cols[2].get_text(strip=True)
                    events.append({
                        "시간": time_str,
                        "국가": country,
                        "이벤트": event_name,
                    })
    except Exception:
        pass
    return events


def fetch_dart_earnings(target_date=None):
    """DART API로 당일 공시 조회"""
    if not DART_API_KEY:
        return []

    if target_date is None:
        target_date = datetime.date.today()

    date_str = target_date.strftime("%Y%m%d")

    try:
        url = "https://opendart.fss.or.kr/api/list.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de": date_str,
            "end_de": date_str,
            "pblntf_ty": "F",
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


def fetch_today_schedule():
    """오늘 일정 조회"""
    today = datetime.date.today()

    # 고정 일정
    major = _get_major_events(today)
    # 네이버 경제 캘린더
    naver = fetch_naver_economic_calendar(today)
    # DART
    earnings = fetch_dart_earnings(today)

    events = []
    for e in major:
        events.append({
            "시간": e["time"],
            "국가": e["country"],
            "이벤트": e["event"],
        })
    for e in naver:
        events.append(e)

    return {
        "date": today.strftime("%m월 %d일"),
        "events": events,
        "earnings": earnings,
    }


def fetch_tomorrow_schedule():
    """내일 일정 조회 (주말이면 다음 월요일)"""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow += datetime.timedelta(days=1)

    major = _get_major_events(tomorrow)
    naver = fetch_naver_economic_calendar(tomorrow)
    earnings = fetch_dart_earnings(tomorrow)

    events = []
    for e in major:
        events.append({
            "시간": e["time"],
            "국가": e["country"],
            "이벤트": e["event"],
        })
    for e in naver:
        events.append(e)

    return {
        "date": tomorrow.strftime("%m월 %d일"),
        "events": events,
        "earnings": earnings,
    }
