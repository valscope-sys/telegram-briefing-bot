"""Investing.com 경제지표 캘린더 스크래핑"""
import re
import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

COUNTRIES_WANT = {"US", "CN", "JP", "KR", "EU", "GB", "DE"}
COUNTRY_EMOJI = {"US": "🇺🇸", "CN": "🇨🇳", "JP": "🇯🇵", "KR": "🇰🇷", "EU": "🇪🇺", "GB": "🇬🇧", "DE": "🇩🇪"}

MONETARY_KEYWORDS = [
    "interest rate", "rate decision", "fomc", "fed", "ecb", "boj", "boe",
    "monetary policy", "jackson hole", "beige book",
]

# 중요도 낮은 이벤트 제외
SKIP_KEYWORDS = [
    "auction", "bond auction", "bobl auction", "bund auction", "bill auction",
    "tic", "redbook", "cushing",
]


def _parse_month(name: str) -> int:
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    return months.get(name.lower(), 0)


def fetch_investing_economic() -> list[dict]:
    """Investing.com 경제지표 캘린더 이번 주 스크래핑"""
    try:
        res = requests.get("https://www.investing.com/economic-calendar/", headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"[Investing] HTTP {res.status_code}")
            return []
    except Exception as e:
        print(f"[Investing] Request error: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")
    results = []
    current_date = ""

    for tr in soup.select("tr"):
        classes = tr.get("class", [])
        text = tr.get_text(strip=True)

        # 날짜 헤더 감지: "Tuesday, April 14, 2026"
        if "datatable-v2_no-hover__MTs36" in " ".join(classes) or "w-full" in " ".join(classes):
            m = re.search(r"(\w+),\s+(\w+)\s+(\d+),\s+(\d{4})", text)
            if m:
                month = _parse_month(m.group(2))
                day = int(m.group(3))
                year = int(m.group(4))
                if month:
                    current_date = f"{year}-{month:02d}-{day:02d}"
                continue

        if not current_date:
            continue

        tds = tr.select("td")
        if len(tds) < 4:
            continue

        # 국가
        country = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        if country not in COUNTRIES_WANT:
            continue

        # 이벤트명
        event_td = tds[3] if len(tds) > 3 else None
        if not event_td:
            continue
        raw_event = event_td.get_text(strip=True)
        if not raw_event:
            continue

        # Act/Cons/Prev 제거해서 이벤트명만 추출
        event_name = re.split(r"Act:|Cons:|Prev\.?:", raw_event)[0].strip()
        if not event_name:
            continue

        # 스킵 키워드
        if any(kw in event_name.lower() for kw in SKIP_KEYWORDS):
            continue

        # 영향도 (아이콘 개수)
        impact_td = tds[4] if len(tds) > 4 else None
        impact_count = len(impact_td.select("svg, i")) if impact_td else 0
        if impact_count < 2:  # 2개 이상만 (중요도 Medium 이상)
            continue

        # 요약 (Actual/Consensus/Previous)
        summary_parts = []
        actual_m = re.search(r"Act:([\d.\-,%BCM]+)", raw_event)
        cons_m = re.search(r"Cons:([\d.\-,%BCM]+)", raw_event)
        prev_m = re.search(r"Prev\.?:([\d.\-,%BCM]+)", raw_event)
        if cons_m and cons_m.group(1) != "-":
            summary_parts.append(f"예상: {cons_m.group(1)}")
        if prev_m and prev_m.group(1) != "-":
            summary_parts.append(f"이전: {prev_m.group(1)}")

        emoji = COUNTRY_EMOJI.get(country, "")
        is_monetary = any(kw in event_name.lower() for kw in MONETARY_KEYWORDS)
        category = "통화정책" if is_monetary else "경제지표"

        ev = {
            "date": current_date,
            "time": "",
            "category": category,
            "title": f"{emoji} {event_name}".strip(),
            "source": "investing",
            "auto": True,
            "country": emoji,
        }
        if summary_parts:
            ev["summary"] = " | ".join(summary_parts)

        results.append(ev)

    # 중복 제거 (같은 날짜+이벤트명)
    seen = set()
    unique = []
    for ev in results:
        key = ev["date"] + "|" + ev["title"]
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    print(f"[Investing] {len(unique)}건 수집")
    return unique
