"""38.co.kr 신규상장 + 공모청약 일정 수집"""
import re
import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SKIP_KEYWORDS = ["스팩", "SPAC"]


def fetch_new_listings() -> list[dict]:
    """38.co.kr 신규상장 일정"""
    try:
        res = requests.get(
            "http://www.38.co.kr/html/fund/?o=nw",
            headers=HEADERS, timeout=15,
        )
        res.encoding = "euc-kr"
    except Exception as e:
        print(f"[38cr] 신규상장 요청 실패: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")
    results = []

    for table in soup.select("table"):
        rows = table.select("tr")
        for row in rows:
            tds = row.select("td")
            if len(tds) < 2:
                continue
            name = tds[0].get_text(strip=True)
            date_text = tds[1].get_text(strip=True)

            m = re.match(r"(20\d{2})/(\d{2})/(\d{2})", date_text)
            if not m:
                continue
            if not name or len(name) < 2:
                continue

            # 스팩 필터
            if any(kw in name for kw in SKIP_KEYWORDS):
                continue

            ev_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            today = datetime.date.today()
            try:
                d = datetime.date.fromisoformat(ev_date)
                if d < today - datetime.timedelta(days=7):
                    continue
            except ValueError:
                continue

            results.append({
                "date": ev_date,
                "time": "",
                "category": "IPO/공모",
                "title": f"{name} 신규상장",
                "source": "38cr",
                "auto": True,
            })

    return results


def fetch_ipo_subscriptions() -> list[dict]:
    """38.co.kr 공모청약 일정"""
    try:
        res = requests.get(
            "http://www.38.co.kr/html/fund/index.htm?o=k",
            headers=HEADERS, timeout=15,
        )
        res.encoding = "euc-kr"
    except Exception as e:
        print(f"[38cr] 공모청약 요청 실패: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")

    # 테이블에서 직접 파싱
    results = []
    today = datetime.date.today()
    seen = set()

    for table in soup.select("table"):
        rows = table.select("tr")
        for row in rows:
            tds = row.select("td")
            if len(tds) < 2:
                continue
            for j, td in enumerate(tds):
                td_text = td.get_text(strip=True)
                m = re.match(r"(20\d{2})\.(\d{2})\.(\d{2})~(\d{2})\.(\d{2})", td_text)
                if not m:
                    continue
                # 이 td 앞의 td가 종목명
                if j == 0:
                    continue
                name = tds[j - 1].get_text(strip=True)
                if not name or len(name) < 2:
                    continue

                year = m.group(1)
                month_start = m.group(2)
                day_start = m.group(3)
                month_end = m.group(4)
                day_end = m.group(5)

                if any(kw in name for kw in SKIP_KEYWORDS):
                    continue

                ev_date = f"{year}-{month_start}-{day_start}"
                try:
                    d = datetime.date.fromisoformat(ev_date)
                    if d < today - datetime.timedelta(days=7):
                        continue
                except ValueError:
                    continue

                if name in seen:
                    continue
                seen.add(name)

                date_range = f"{month_start}/{day_start}~{month_end}/{day_end}"
                results.append({
                    "date": ev_date,
                    "time": "",
                    "category": "IPO/공모",
                    "title": f"{name} 공모청약 ({date_range})",
                    "source": "38cr",
                    "auto": True,
                })

    return results


def fetch_all_ipo() -> list[dict]:
    """신규상장 + 공모청약 전체 수집"""
    all_events = []

    listings = fetch_new_listings()
    all_events.extend(listings)

    subscriptions = fetch_ipo_subscriptions()
    # 중복 제거 (같은 기업이 신규상장+공모청약 둘 다 있을 수 있음)
    listing_names = {e["title"].replace(" 신규상장", "") for e in listings}
    for sub in subscriptions:
        base_name = sub["title"].split(" 공모청약")[0]
        if base_name not in listing_names:
            all_events.append(sub)
        else:
            all_events.append(sub)  # 둘 다 유지 (다른 이벤트)

    return all_events
