"""FMP (Financial Modeling Prep) 경제지표 캘린더 수집"""
import os
import datetime
import requests
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
BASE_URL = "https://financialmodelingprep.com/stable/economic-calendar"

# 관심 국가
COUNTRIES = {"US", "CN", "JP", "KR", "EU", "GB", "DE"}

# 영향도 필터 (High만 가져옴)
MIN_IMPACT = {"High", "Medium"}

# 국가 → 이모지
COUNTRY_EMOJI = {
    "US": "🇺🇸", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷",
    "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪",
}

# 통화정책 키워드 (경제지표와 분리)
MONETARY_KEYWORDS = [
    "interest rate", "rate decision", "fomc", "금리", "금통위",
    "ecb", "boj", "boe", "jackson hole",
]


def fetch_fmp_economic(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """FMP 경제지표 캘린더 수집"""
    if not FMP_API_KEY:
        print("[FMP] API key not set")
        return []

    # 최대 90일 제한
    delta = (to_date - from_date).days
    if delta > 90:
        to_date = from_date + datetime.timedelta(days=90)

    results = []

    # 국가별로 조회 (또는 전체 조회 후 필터)
    try:
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "apikey": FMP_API_KEY,
        }
        res = requests.get(BASE_URL, params=params, timeout=15)
        if res.status_code != 200:
            print(f"[FMP] HTTP {res.status_code}")
            return []

        data = res.json()
        if not isinstance(data, list):
            print(f"[FMP] Unexpected response: {type(data)}")
            return []

        for item in data:
            country = item.get("country", "")
            if country not in COUNTRIES:
                continue

            impact = item.get("impact", "")
            if impact not in MIN_IMPACT:
                continue

            event_name = item.get("event", "")
            if not event_name:
                continue

            # 날짜/시간 파싱
            raw_date = item.get("date", "")
            if not raw_date:
                continue

            ev_date = raw_date[:10]  # "2026-04-14"
            ev_time = ""
            if len(raw_date) > 10:
                # "2026-04-14 21:30:00" → KST 변환 (UTC+9)
                try:
                    parts = raw_date.split(" ")
                    if len(parts) >= 2:
                        time_parts = parts[1].split(":")
                        utc_h = int(time_parts[0])
                        utc_m = int(time_parts[1])
                        kst_h = utc_h + 9
                        if kst_h >= 24:
                            kst_h -= 24
                            d = datetime.date.fromisoformat(ev_date) + datetime.timedelta(days=1)
                            ev_date = d.isoformat()
                        ev_time = f"{kst_h:02d}:{utc_m:02d}"
                except (ValueError, IndexError):
                    pass

            emoji = COUNTRY_EMOJI.get(country, "")
            title = f"{emoji} {event_name}".strip() if emoji else event_name

            # 카테고리 판별
            is_monetary = any(kw in event_name.lower() for kw in MONETARY_KEYWORDS)
            category = "통화정책" if is_monetary else "경제지표"

            # 예상치/이전치 요약
            estimate = item.get("estimate")
            previous = item.get("previous")
            summary_parts = []
            if estimate is not None:
                summary_parts.append(f"예상: {estimate}")
            if previous is not None:
                summary_parts.append(f"이전: {previous}")
            summary = " | ".join(summary_parts) if summary_parts else ""

            ev = {
                "date": ev_date,
                "time": ev_time,
                "category": category,
                "title": title,
                "source": "fmp",
                "auto": True,
                "country": emoji,
            }
            if summary:
                ev["summary"] = summary

            results.append(ev)

        print(f"[FMP] {len(results)}건 수집 (전체 {len(data)}건 중)")
        return results

    except Exception as e:
        print(f"[FMP] Error: {e}")
        return []
