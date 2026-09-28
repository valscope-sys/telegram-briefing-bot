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

# 관심 종목 → 한글명 (시총 상위 + 한국 증시 연관 밸류체인)
# 제목에 한글명을 넣어 웹 캘린더에서 별도 매핑 없이 한글로 표시
WATCHLIST = {
    # 빅테크/AI
    "NVDA": "엔비디아", "AAPL": "애플", "TSLA": "테슬라", "MSFT": "마이크로소프트",
    "GOOGL": "알파벳", "AMZN": "아마존", "META": "메타", "NFLX": "넷플릭스",
    # 반도체 (삼성전자·SK하이닉스·장비주 직결)
    "AVGO": "브로드컴", "TSM": "TSMC", "AMD": "AMD", "INTC": "인텔", "QCOM": "퀄컴",
    "MU": "마이크론", "ASML": "ASML", "AMAT": "어플라이드머티어리얼즈", "LRCX": "램리서치",
    "KLAC": "KLA", "MRVL": "마벨", "SNDK": "샌디스크", "ON": "온세미", "TXN": "텍사스인스트루먼트",
    "ADI": "아날로그디바이스", "NXPI": "NXP", "ARM": "ARM", "SNPS": "시놉시스", "CDNS": "케이던스",
    "WDC": "웨스턴디지털", "STX": "시게이트", "SMCI": "슈퍼마이크로", "TER": "테라다인",
    "AMKR": "앰코", "KLIC": "쿨리케앤소파", "ENTG": "엔테그리스", "MKSI": "MKS",
    "GFS": "글로벌파운드리", "MPWR": "모놀리식파워",
    # AI 인프라·네트워크·전력 (HBM·광통신·전력기기 연관)
    "DELL": "델", "HPE": "HPE", "ANET": "아리스타", "CSCO": "시스코", "COHR": "코히런트",
    "CRDO": "크레도", "ALAB": "아스테라랩스", "CLS": "셀레스티카", "FN": "패브리넷",
    "AAOI": "어플라이드옵토", "VRT": "버티브", "ETN": "이튼", "GEV": "GE버노바",
    "CEG": "컨스텔레이션에너지", "VST": "비스트라", "IBM": "IBM", "JBL": "자빌",
    "PWR": "퀀타서비스", "ACN": "액센츄어",
    # 원전·SMR·태양광 (두산에너빌리티·한화솔루션 연관)
    "CCJ": "카메코", "BWXT": "BWXT", "SMR": "뉴스케일", "OKLO": "오클로", "FSLR": "퍼스트솔라",
    # SW/클라우드/보안
    "CRM": "세일즈포스", "ORCL": "오라클", "ADBE": "어도비", "NOW": "서비스나우",
    "PLTR": "팔란티어", "SNOW": "스노우플레이크", "PANW": "팔로알토", "CRWD": "크라우드스트라이크",
    "INTU": "인튜이트", "SHOP": "쇼피파이", "UBER": "우버", "ABNB": "에어비앤비",
    # 금융 (실적시즌 개막)
    "JPM": "JP모건", "BAC": "뱅크오브아메리카", "WFC": "웰스파고", "C": "씨티그룹",
    "MS": "모건스탠리", "GS": "골드만삭스", "BLK": "블랙록", "SCHW": "찰스슈왑",
    "V": "비자", "MA": "마스터카드", "AXP": "아메리칸익스프레스", "COIN": "코인베이스",
    "BRK.A": "버크셔해서웨이",
    # 헬스케어/바이오
    "UNH": "유나이티드헬스", "JNJ": "존슨앤드존슨", "PFE": "화이자", "LLY": "일라이릴리",
    "ABT": "애보트", "ABBV": "애브비", "MRK": "머크", "TMO": "써모피셔", "AMGN": "암젠",
    "GILD": "길리어드", "REGN": "리제네론", "VRTX": "버텍스", "ISRG": "인튜이티브서지컬",
    "NVO": "노보노디스크", "BMY": "BMS", "MRNA": "모더나",
    # 에너지/산업/방산 (조선·방산·기계 연관)
    "XOM": "엑슨모빌", "CVX": "셰브론", "COP": "코노코필립스", "BA": "보잉", "CAT": "캐터필러",
    "DE": "디어", "RTX": "RTX", "LMT": "록히드마틴", "NOC": "노스롭그루먼",
    "GD": "제너럴다이내믹스", "GE": "GE에어로스페이스", "HON": "하니웰", "FDX": "페덱스",
    "HII": "헌팅턴잉걸스", "NUE": "뉴코어", "DOW": "다우",
    # 자동차/EV/배터리 소재 (2차전지 연관)
    "GM": "GM", "F": "포드", "RIVN": "리비안", "ALB": "앨버말",
    # 소비재/리테일 (의류 OEM·화장품 ODM 연관)
    "WMT": "월마트", "COST": "코스트코", "HD": "홈디포", "MCD": "맥도날드", "SBUX": "스타벅스",
    "NKE": "나이키", "PEP": "펩시코", "KO": "코카콜라", "PG": "P&G", "TGT": "타깃",
    "LULU": "룰루레몬", "CPNG": "쿠팡",
    # 미디어/통신
    "DIS": "디즈니", "CMCSA": "컴캐스트", "TMUS": "T모바일",
    # 중국 ADR
    "BABA": "알리바바", "PDD": "PDD", "JD": "징둥", "BIDU": "바이두",
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
# 직전 실행에서 조회 실패한 구간 — update.py가 이 구간의 기존 일정은 교체하지 않고 보존
LAST_FAILED_RANGES: list[tuple[str, str]] = []


def _fetch_earnings_raw(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """실적 캘린더 raw 조회 (청크 단위).

    1500행 하드캡 감지 시 청크를 반으로 쪼개 재귀 재요청 — 무음 소실 방지.
    """
    data = _get("/calendar/earnings", {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
    })
    if not data:
        LAST_FAILED_RANGES.append((from_date.isoformat(), to_date.isoformat()))
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
    LAST_FAILED_RANGES.clear()
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

        # EPS 추정치는 매일 변동 → 제목이 아닌 summary에 (병합 키 안정화)
        title = f"{WATCHLIST[symbol]}({symbol}) 실적발표"
        if hour:
            title += f" ({hour})"

        summary_parts = []
        if hour == "장전":
            summary_parts.append("미국 장 시작 전 발표 (KST 당일 밤)")
        elif hour == "장후":
            summary_parts.append("미국 장 마감 후 발표 (KST 익일 새벽)")
        if eps_est is not None:
            summary_parts.append(f"EPS 예상 ${eps_est:.2f}")

        ev = {
            "date": ev_date,
            "time": "",
            "category": "미국실적",
            "title": title,
            "source": "finnhub",
            "auto": True,
            "country": "🇺🇸",
        }
        if summary_parts:
            ev["summary"] = " · ".join(summary_parts)
        results.append(ev)

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
