"""경제 일정 수집 (고정 일정 + FnGuide 실적 + DART)"""
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


def fetch_fnguide_earnings(target_date=None):
    """FnGuide 실적 캘린더 크롤링 (잠정실적/실적발표)"""
    if target_date is None:
        target_date = datetime.date.today()

    month_str = target_date.strftime("%Y%m")
    target_day = target_date.day

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://comp.fnguide.com/SVO2/ASP/SVD_comp_calendar.asp",
    }

    try:
        url = "https://comp.fnguide.com/SVO2/ASP/svd_comp_calendarData.asp"
        params = {
            "gicode": "",
            "eventType": "all,AN,10;22;23,20,30,52,53;54,40;41,21;24,17,25,50,IR1,IR2",
            "fromdt": month_str,
        }
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, "lxml")
        earnings = []
        for td in soup.select("td"):
            h3 = td.select_one("h3")
            if not h3:
                continue
            day_text = h3.get_text(strip=True)
            if not day_text.isdigit():
                continue
            day = int(day_text)
            if day != target_day:
                continue

            for a in td.select("a.ico_01"):  # ico_01 = 잠정실적/실적발표
                name = a.get_text(strip=True)
                if name:
                    # "(연결/분기)" 등 중복 제거 → 기업명만
                    corp = name.split("(")[0].strip()
                    earnings.append({"기업명": corp, "보고서명": name})

        # 중복 기업명 제거
        seen = set()
        unique = []
        for e in earnings:
            if e["기업명"] not in seen:
                seen.add(e["기업명"])
                unique.append(e)
        return unique
    except Exception:
        return []


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


def _build_schedule(target_date):
    """일정 통합 조회 (고정 일정 + FnGuide 실적 + DART)"""
    major = _get_major_events(target_date)
    fnguide = fetch_fnguide_earnings(target_date)
    dart = fetch_dart_earnings(target_date)

    events = []
    for e in major:
        events.append({
            "시간": e["time"],
            "국가": e["country"],
            "이벤트": e["event"],
        })

    # FnGuide + DART 실적 합치기 (중복 제거)
    all_earnings = fnguide[:]
    seen = {e["기업명"] for e in fnguide}
    for e in dart:
        if e["기업명"] not in seen:
            all_earnings.append(e)
            seen.add(e["기업명"])

    return {
        "date": target_date.strftime("%m월 %d일"),
        "events": events,
        "earnings": all_earnings,
    }


def fetch_today_schedule():
    """오늘 일정 조회"""
    return _build_schedule(datetime.date.today())


def fetch_tomorrow_schedule():
    """내일 일정 조회 (주말이면 다음 월요일)"""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow += datetime.timedelta(days=1)
    return _build_schedule(tomorrow)
