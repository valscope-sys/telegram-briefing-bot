"""Finnhub API - 미국 실적 + 경제지표 수집"""
import os
import datetime
import requests
from dotenv import load_dotenv

# .env 로드
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
BASE_URL = "https://finnhub.io/api/v1"

# 관심 종목 (시총 상위 + 한국 투자자 관심)
WATCHLIST = {
    "NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "META", "NFLX",
    "AVGO", "TSM", "AMD", "INTC", "QCOM", "MU", "ASML", "AMAT", "LRCX",
    "FN", "AAOI", "CRM", "ORCL", "ADBE", "NOW", "PLTR",
    "JPM", "V", "MA", "BRK.B", "UNH", "JNJ", "PFE", "LLY",
    "XOM", "CVX", "BA", "CAT", "DE",
    "WMT", "COST", "HD", "MCD", "SBUX", "NKE",
    "DIS", "CMCSA", "ABNB",
}

EARNINGS_TIME_MAP = {
    "bmo": "장전",
    "amc": "장후",
    "dmh": "",
    "": "",
}


def _get(endpoint: str, params: dict) -> dict | list | None:
    """Finnhub API 호출"""
    if not FINNHUB_API_KEY:
        print("[Finnhub] API key not set")
        return None
    params["token"] = FINNHUB_API_KEY
    try:
        res = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=15)
        if res.status_code == 429:
            import time
            time.sleep(1)
            res = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=15)
        if res.status_code != 200:
            print(f"[Finnhub] HTTP {res.status_code} for {endpoint}")
            return None
        data = res.json()
        if isinstance(data, dict) and "error" in data:
            print(f"[Finnhub] Error: {data['error']}")
            return None
        return data
    except Exception as e:
        print(f"[Finnhub] Request error: {e}")
        return None


def fetch_us_earnings(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """미국 실적 발표 일정 (관심종목만)"""
    data = _get("/calendar/earnings", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    })
    if not data:
        return []

    earnings_list = data.get("earningsCalendar", [])
    results = []

    for item in earnings_list:
        symbol = item.get("symbol", "")
        if symbol not in WATCHLIST:
            continue

        ev_date = item.get("date", "")
        if not ev_date:
            continue

        hour = EARNINGS_TIME_MAP.get(item.get("hour", ""), "")
        eps_est = item.get("epsEstimate")

        title = f"{symbol} 실적발표"
        if hour:
            title += f" ({hour})"
        if eps_est is not None:
            title += f" [EPS est. ${eps_est}]"

        results.append({
            "date": ev_date,
            "time": "",
            "category": "미국실적",
            "title": title,
            "source": "finnhub",
            "auto": True,
        })

    return results


def fetch_economic_calendar(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """경제지표 일정 (고영향만)"""
    data = _get("/calendar/economic", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    })
    if not data:
        return []

    events_list = data.get("economicCalendar", [])
    results = []

    for item in events_list:
        impact = item.get("impact", "")
        if impact not in ("high", "3", 3):
            continue

        country = item.get("country", "")
        event_name = item.get("event", "")
        if not event_name:
            continue

        ev_time = item.get("time", "")
        ev_date_str = item.get("date", "")
        if not ev_date_str:
            continue

        # UTC → KST (+9h) 변환
        kst_time = ""
        if ev_time and ":" in ev_time:
            try:
                parts = ev_time.split(":")
                utc_h = int(parts[0])
                utc_m = int(parts[1])
                kst_h = utc_h + 9
                kst_date = ev_date_str
                if kst_h >= 24:
                    kst_h -= 24
                    d = datetime.date.fromisoformat(ev_date_str) + datetime.timedelta(days=1)
                    kst_date = d.isoformat()
                kst_time = f"{kst_h:02d}:{kst_m:02d}"
                ev_date_str = kst_date
            except (ValueError, IndexError):
                kst_time = ""

        country_flag = {
            "US": "🇺🇸", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷",
            "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪",
        }.get(country, "")

        title = f"{country_flag} {event_name}".strip() if country_flag else event_name

        results.append({
            "date": ev_date_str,
            "time": kst_time,
            "category": "경제지표",
            "title": title,
            "source": "finnhub",
            "auto": True,
        })

    return results


def fetch_finnhub_all(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """Finnhub 전체 수집 (실적 + 경제지표)"""
    all_events = []

    earnings = fetch_us_earnings(from_date, to_date)
    all_events.extend(earnings)

    economic = fetch_economic_calendar(from_date, to_date)
    all_events.extend(economic)

    return all_events
