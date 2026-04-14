"""FnGuide 실적 캘린더 JSON API 수집"""
import datetime
import json
import requests

# FnGuide 이벤트코드 → 캘린더 카테고리 매핑
EVENT_CODE_MAP = {
    "IR1": "한국실적",       # 실적발표
    "IR2": "IR",              # 경영현황 IR
    "10": "기업이벤트",       # 유상증자(주주배정)
    "22": "기업이벤트",       # 유상증자(3자배정)
    "23": "기업이벤트",       # 유상증자(일반공모)
    "20": "기업이벤트",       # 무상증자
    "17": "IPO/공모",         # 신규상장
    "52": "기업이벤트",       # 기업합병
    "41": "기업이벤트",       # 액면분할
    "40": "기업이벤트",       # 액면병합
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://comp.fnguide.com/SVO2/ASP/SVD_comp_calendar.asp",
}

# 스팩/우선주 필터
SKIP_KEYWORDS = ["스팩", "SPAC", "우B", "우C"]


def _parse_date(raw_date: str, year: int, month: int) -> str | None:
    """FnGuide 일자 필드 파싱 → YYYY-MM-DD"""
    if not raw_date:
        return None
    raw = raw_date.strip()

    # "2026-04-23 09:00" 형식
    if "-" in raw and len(raw) >= 10:
        return raw[:10]

    # "20260423" 형식
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    # "23" (일자만) → 해당 월의 일자
    if raw.isdigit() and len(raw) <= 2:
        day = int(raw)
        if 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"

    return None


def _parse_time(raw_date: str) -> str:
    """일자 필드에서 시간 추출"""
    if not raw_date:
        return ""
    raw = raw_date.strip()
    if " " in raw and ":" in raw:
        parts = raw.split(" ")
        if len(parts) >= 2:
            t = parts[-1].strip()
            if t and t != "--:--" and ":" in t:
                return t
    return ""


def fetch_fnguide_month(year: int, month: int) -> list[dict]:
    """FnGuide 한 달 캘린더 데이터를 JSON API로 수집"""
    yyyymm = f"{year}{month:02d}"
    url = f"https://comp.fnguide.com/SVO2/json/data/05_01/{yyyymm}.json"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[FnGuide] HTTP {res.status_code} for {yyyymm}")
            return []

        for enc in ("utf-8-sig", "utf-8", "euc-kr", "cp949"):
            try:
                text = res.content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            print(f"[FnGuide] Decode failed for {yyyymm}")
            return []
        data = json.loads(text)

        items = data.get("comp", [])
        if not isinstance(items, list):
            print(f"[FnGuide] Unexpected format for {yyyymm}")
            return []
    except Exception as e:
        print(f"[FnGuide] Error fetching {yyyymm}: {e}")
        return []

    events = []
    seen = {}  # (date, company) → index (중복 제거용)

    for item in items:
        try:
            code = item.get("이벤트코드", "")
            category = EVENT_CODE_MAP.get(code)
            if not category:
                continue

            company = item.get("기업명", "").strip()
            if not company:
                continue

            # 스팩/우선주 필터
            if any(kw in company for kw in SKIP_KEYWORDS):
                continue

            raw_date = item.get("일자", "")
            ev_date = _parse_date(raw_date, year, month)
            if not ev_date:
                # 기준일자(day of month)로 폴백
                day_str = item.get("기준일자", "")
                if day_str and day_str.isdigit():
                    ev_date = f"{year}-{month:02d}-{int(day_str):02d}"
                else:
                    continue

            ev_time = _parse_time(raw_date)

            kind = item.get("종류", "")
            if code == "IR1":
                title = f"{company} 실적발표"
            elif code == "IR2":
                title = f"{company} IR ({kind})" if kind else f"{company} IR"
            elif code == "17":
                title = f"{company} 신규상장"
            elif code in ("10", "22", "23"):
                title = f"{company} {kind}" if kind else f"{company} 유상증자"
            elif code == "20":
                title = f"{company} 무상증자"
            else:
                title = f"{company} {kind}" if kind else company

            key = (ev_date, company)
            if key in seen:
                # IR1(실적발표)이 다른 코드보다 우선
                old_idx = seen[key]
                old_code = events[old_idx].get("_code", "")
                if code == "IR1" and old_code != "IR1":
                    events[old_idx] = None
                else:
                    continue

            ev = {
                "date": ev_date,
                "time": ev_time,
                "category": category,
                "title": title,
                "source": "fnguide",
                "auto": True,
                "_code": code,
            }
            seen[key] = len(events)
            events.append(ev)

        except Exception as e:
            continue

    # HTML 보조 스크래핑: 잠정실적 판별 (ico_01 + popuplayerannounce)
    provisional_corps = _fetch_provisional_earnings(year, month)

    # _code 필드 제거 + 잠정 태깅
    result = []
    for e in events:
        if e is not None:
            code = e.pop("_code", "")
            if e["category"] == "한국실적":
                corp = e["title"].replace(" 실적발표", "")
                if corp in provisional_corps:
                    e["category"] = "한국실적(잠정)"
                    e["title"] = f"{corp} 잠정실적발표"
            result.append(e)
    return result


def _fetch_provisional_earnings(year: int, month: int) -> set[str]:
    """HTML 스크래핑으로 잠정실적 기업명 세트 반환"""
    from bs4 import BeautifulSoup
    yyyymm = f"{year}{month:02d}"
    try:
        url = "https://comp.fnguide.com/SVO2/ASP/svd_comp_calendarData.asp"
        params = {
            "gicode": "",
            "eventType": "all,AN,10;22;23,20,30,52,53;54,40;41,21;24,17,25,50,IR1,IR2",
            "fromdt": yyyymm,
        }
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return set()
        soup = BeautifulSoup(res.text, "lxml")
        corps = set()
        for a in soup.select("a.ico_01.popuplayerannounce"):
            name = a.get_text(strip=True)
            if name:
                corp = name.split("(")[0].strip()
                corps.add(corp)
        return corps
    except Exception:
        return set()


def fetch_fnguide_range(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """날짜 범위의 FnGuide 데이터 수집 (월 경계 자동 처리)"""
    results = []
    current = from_date.replace(day=1)

    while current <= to_date:
        month_events = fetch_fnguide_month(current.year, current.month)
        for ev in month_events:
            try:
                ev_date = datetime.date.fromisoformat(ev["date"])
                if from_date <= ev_date <= to_date:
                    results.append(ev)
            except ValueError:
                continue

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return results
