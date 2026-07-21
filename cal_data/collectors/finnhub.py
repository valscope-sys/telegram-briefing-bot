"""Finnhub API - 미국 실적 + 경제지표 수집"""
import os
import time
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
    # 빅테크/AI
    "NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "META", "NFLX",
    # 반도체
    "AVGO", "TSM", "AMD", "INTC", "QCOM", "MU", "ASML", "AMAT", "LRCX",
    "MRVL", "SNDK", "ON", "KLAC", "TXN",
    # SW/클라우드
    "CRM", "ORCL", "ADBE", "NOW", "PLTR", "SNOW", "PANW",
    # 금융 (실적시즌 핵심)
    "JPM", "BAC", "WFC", "C", "MS", "GS", "BLK", "SCHW",
    "V", "MA", "BRK.B",
    # 헬스케어
    "UNH", "JNJ", "PFE", "LLY", "ABT", "ABBV", "MRK", "TMO",
    # 에너지/산업
    "XOM", "CVX", "BA", "CAT", "DE", "RTX", "LMT", "GE",
    # 소비재
    "WMT", "COST", "HD", "MCD", "SBUX", "NKE", "PEP", "KO", "PG",
    # 미디어/엔터
    "DIS", "CMCSA", "ABNB",
    # 기타 관심
    "FN", "AAOI",
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


# Finnhub /calendar/earnings 하드캡: 날짜 내림차순 1500행에서 무음 절단됨
_EARNINGS_ROW_CAP = 1500
# 어닝시즌 피크(하루 수백 건)에도 캡을 안 넘도록 분할 단위는 7일
_EARNINGS_CHUNK_DAYS = 7


def _fetch_earnings_raw(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """실적 캘린더 raw 조회 (청크 단위).

    1500행 하드캡 감지 시 청크를 반으로 쪼개 재귀 재요청 — 무음 소실 방지.
    """
    data = _get("/calendar/earnings", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    })
    if not data:
        return []

    rows = data.get("earningsCalendar", [])
    print(f"[Finnhub] 실적 청크 {from_date}~{to_date}: raw {len(rows)}행")

    if len(rows) >= _EARNINGS_ROW_CAP:
        if from_date >= to_date:
            # 단일 일자가 캡에 걸리면 더 쪼갤 수 없음 — 경고만 남기고 그대로 사용
            # 주의: 로그에 em-dash 대신 하이픈 사용 (Windows cp949 콘솔 인코딩 크래시 방지)
            print(f"[Finnhub] WARNING: 1500행 절단 - 단일 일자({from_date}) 재분할 불가, 일부 소실 가능")
            return rows
        print("[Finnhub] WARNING: 1500행 절단 - 청크 재분할")
        mid = from_date + (to_date - from_date) // 2
        left = _fetch_earnings_raw(from_date, mid)
        time.sleep(0.5)
        right = _fetch_earnings_raw(mid + datetime.timedelta(days=1), to_date)
        return left + right

    return rows


def fetch_us_earnings(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """미국 실적 발표 일정 (관심종목만)

    Finnhub은 날짜 내림차순 + 1500행 하드캡이라 긴 범위 단일 호출 시
    앞쪽(가까운) 날짜가 통째로 절단됨 → 7일 청크로 분할 순회 후 합산.
    """
    earnings_list = []
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + datetime.timedelta(days=_EARNINGS_CHUNK_DAYS - 1), to_date)
        earnings_list.extend(_fetch_earnings_raw(chunk_start, chunk_end))
        chunk_start = chunk_end + datetime.timedelta(days=1)
        if chunk_start <= to_date:
            time.sleep(0.5)  # rate limit 여유 (429 재시도는 _get에서 처리)

    results = []
    seen = set()

    for item in earnings_list:
        symbol = item.get("symbol", "")
        if symbol not in WATCHLIST:
            continue

        ev_date = item.get("date", "")
        if not ev_date:
            continue

        # 청크 경계/재분할 시 중복 방지
        dedupe_key = (ev_date, symbol)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

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
    """Finnhub 수집 (미국 실적만 — 경제지표는 Investing.com으로 대체)"""
    return fetch_us_earnings(from_date, to_date)
