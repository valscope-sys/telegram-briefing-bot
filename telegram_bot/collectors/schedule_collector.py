"""경제 일정 수집 (calendar.json 기반 + DART 실시간 보완)"""
import datetime
import json
import requests
from pathlib import Path
from telegram_bot.config import DART_API_KEY

CALENDAR_JSON = Path(__file__).resolve().parent.parent.parent / "cal_data" / "calendar.json"

# 카테고리 → 국가 이모지 매핑
CATEGORY_COUNTRY = {
    "고정이벤트": "",     # country 필드 사용
    "한국실적": "🇰🇷",
    "미국실적": "🇺🇸",
    "경제지표": "",       # title에 포함
    "IPO/공모": "🇰🇷",
    "배당": "🇰🇷",
    "유증": "🇰🇷",
    "IR": "🇰🇷",
}


def _load_calendar_events(target_date):
    """calendar.json에서 해당 날짜 이벤트 로드"""
    if not CALENDAR_JSON.exists():
        return []

    try:
        data = json.loads(CALENDAR_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    date_str = target_date.isoformat()
    return [e for e in data if e.get("date") == date_str]


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
    """일정 통합 조회 (calendar.json + DART 실시간)"""
    cal_events = _load_calendar_events(target_date)
    dart = fetch_dart_earnings(target_date)

    events = []
    earnings = []

    # 노이즈 필터 (액면분할/병합/유상증자/무상증자 등)
    noise_keywords = ["액면분할", "액면병합", "유상증자", "무상증자", "기업합병", "주식소각"]

    for e in cal_events:
        cat = e.get("category", "")
        title = e.get("title", "")

        # 실적발표
        if cat in ("한국실적", "미국실적"):
            earnings.append({
                "기업명": title.replace(" 실적발표", ""),
                "보고서명": title,
            })
        # 노이즈 제외
        elif cat == "기업이벤트" and any(kw in title for kw in noise_keywords):
            continue
        # 유증/배당 제외
        elif cat in ("유증", "배당"):
            continue
        # IR은 실적에 포함
        elif cat == "IR":
            earnings.append({
                "기업명": title.replace(" IR (경영현황)", "").replace(" IR (실적발표)", ""),
                "보고서명": title,
            })
        # 나머지 (고정이벤트, 경제지표, IPO 등)
        else:
            country = e.get("country", "") or CATEGORY_COUNTRY.get(cat, "")
            events.append({
                "시간": e.get("time", ""),
                "국가": country,
                "이벤트": title,
            })

    # DART 실시간 보완
    seen = {e["기업명"] for e in earnings}
    for d in dart:
        if d["기업명"] not in seen:
            earnings.append(d)
            seen.add(d["기업명"])

    return {
        "date": target_date.strftime("%m월 %d일"),
        "events": events,
        "earnings": earnings,
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
