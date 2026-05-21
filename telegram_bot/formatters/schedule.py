"""일정 메시지 포맷터 (오늘 일정 / 내일 일정)"""
import datetime
import re
import os
import json

CALENDAR_WEB_URL = "https://valscope-sys.github.io/telegram-briefing-bot/"

# KRX 상장사 마스터 (세션 내 캐시)
_KRX_LISTED_NAMES = None


def _load_krx_listed_names():
    """KRX 상장사 이름 집합 로드.
    1순위: telegram_bot/history/krx_listing.json (scripts/dump_krx_listing.py 로 생성, 서버 호환)
    2순위: FDR 실시간 (로컬 개발 환경)
    3순위: stock_sector_mapping.json (263종목만, 최종 폴백)
    """
    global _KRX_LISTED_NAMES
    if _KRX_LISTED_NAMES is not None:
        return _KRX_LISTED_NAMES
    names = set()
    history_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history"
    )

    # 1차: JSON 덤프 (서버 호환)
    try:
        path = os.path.join(history_dir, "krx_listing.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            n = s.get("name", "").strip()
            if n:
                names.add(n)
        if names:
            print(f"[SCHEDULE] KRX {len(names)}개 로드 (krx_listing.json)")
            _KRX_LISTED_NAMES = names
            return names
    except Exception:
        pass

    # 2차: FDR 실시간
    try:
        import FinanceDataReader as fdr
        krx = fdr.StockListing("KRX")
        for n in krx["Name"]:
            if n:
                names.add(str(n).strip())
        if names:
            print(f"[SCHEDULE] KRX {len(names)}개 로드 (FDR 실시간)")
            _KRX_LISTED_NAMES = names
            return names
    except Exception as e:
        print(f"[SCHEDULE] FDR 로드 실패: {e}")

    # 3차 폴백: stock_sector_mapping.json (263종목만)
    try:
        path = os.path.join(history_dir, "stock_sector_mapping.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if not k.startswith("_") and isinstance(v, dict) and v.get("name"):
                names.add(v["name"].strip())
        print(f"[SCHEDULE] stock_sector_mapping 폴백 {len(names)}종목")
    except Exception as e:
        print(f"[SCHEDULE] 폴백도 실패 — 상장사 필터 비활성: {e}")

    _KRX_LISTED_NAMES = names
    return names


def _is_listed_corp(name: str) -> bool:
    """실적 발표 기업명이 KRX 상장사인지 확인. 상장사 집합 비어있으면 True (필터 비활성)."""
    if not name:
        return False
    listed = _load_krx_listed_names()
    if not listed:
        return True  # 마스터 로드 실패 시 필터 비활성
    n = name.strip()
    if n in listed:
        return True
    # 간단한 변형도 시도 (공백 제거)
    n2 = n.replace(" ", "")
    for x in listed:
        if x.replace(" ", "") == n2:
            return True
    return False

COUNTRY_EMOJI = {
    "한국": "🇰🇷", "South Korea": "🇰🇷",
    "미국": "🇺🇸", "United States": "🇺🇸",
    "중국": "🇨🇳", "China": "🇨🇳",
    "일본": "🇯🇵", "Japan": "🇯🇵",
}

# 중요도 높은 이벤트 (상단 배치)
HIGH_PRIORITY_KEYWORDS = [
    "FOMC", "금통위", "금리 결정",
    "GDP (전년비)", "GDP (YoY)",
    "소비자물가 (전년비)", "CPI (YoY)",
    "ECB 금리", "BOJ 금리", "비농업", "수출입 통계", "PMI",
    "옵션만기", "선물옵션", "MSCI", "KOSPI200",
    "산업생산", "Industrial Production", "실업률", "Unemployment Rate",
    "무역수지", "Trade Balance", "수출 (전년비)", "Exports (YoY)",
    "Powell", "파월", "Chair",  # 의장 발언은 중요
]

# 중요도 낮은 이벤트 (텔레그램에서 제외)
LOW_PRIORITY_KEYWORDS = [
    "Balance Sheet", "Crude Oil Stock", "API Weekly", "Continuing Jobless",
    "Philly Fed Employment", "Chinese GDP YTD", "Chinese Industrial Production YTD",
    "NBS Press Conference", "Supervisory Board",
    "Core CPI", "CPI (MoM)", "GDP (QoQ)",
    "근원 소비자물가", "소비자물가 (전월비)", "GDP (전분기비)",
    "연속 실업수당", "고정자산투자",
    "CFTC", "Baker Hughes", "speculative net positions",
    "StrictlyVC", "Rig Count",
    # 일반 발언은 제외하되 의장급은 HIGH에서 잡힘
    "Speaks", "발언",
]


def _clean_event_name(name):
    """이벤트명 정리 (EPS est. 제거, 불필요 텍스트 정리)"""
    # [EPS est. $0.77] 또는 [EPS est. $-0.5] 제거 (음수 EPS 포함)
    name = re.sub(r'\s*\[EPS est\.\s*\$-?[\d.]+\]', '', name)
    return name.strip()


# 미국 실적 세션 → KST 대략 시간대 힌트
SESSION_KST_HINT = {
    "장전": "밤",      # US pre-market ~7am ET ≈ KST 20-22시
    "장후": "새벽",    # US after-hours ~4pm+ ET ≈ KST 05-06시 익일
}

# 해외 티커 → 한글명 매핑 (일정 실적 표기용)
US_TICKER_KR = {
    # 빅테크·반도체
    "AAPL": "애플", "MSFT": "마이크로소프트", "GOOGL": "구글(A)", "GOOG": "구글(C)",
    "AMZN": "아마존", "META": "메타", "NVDA": "엔비디아", "TSLA": "테슬라",
    "AMD": "AMD", "INTC": "인텔", "AVGO": "브로드컴", "TSM": "TSMC",
    "QCOM": "퀄컴", "TXN": "텍사스인스트루먼트", "ADI": "아날로그디바이시스",
    "MU": "마이크론", "AMAT": "어플라이드머티어리얼즈", "LRCX": "램리서치",
    "KLAC": "KLA", "ASML": "ASML", "ARM": "ARM",
    # AI·소프트웨어·클라우드
    "ORCL": "오라클", "CRM": "세일즈포스", "NOW": "서비스나우", "SNOW": "스노우플레이크",
    "PLTR": "팔란티어", "NFLX": "넷플릭스", "ADBE": "어도비", "UBER": "우버",
    # 반도체 메모리·장비
    "SNDK": "샌디스크", "WDC": "웨스턴디지털", "STX": "시게이트",
    # 전기차·배터리
    "LCID": "루시드", "RIVN": "리비안", "F": "포드", "GM": "GM",
    # 바이오·제약
    "PFE": "화이자", "MRK": "머크", "JNJ": "존슨앤드존슨", "LLY": "일라이릴리",
    "NVO": "노보노디스크", "MRNA": "모더나", "REGN": "리제네론",
    # 금융
    "JPM": "JP모건", "BAC": "뱅크오브아메리카", "GS": "골드만삭스", "MS": "모건스탠리",
    "C": "씨티그룹", "WFC": "웰스파고", "V": "비자", "MA": "마스터카드",
    # 산업·에너지
    "BA": "보잉", "CAT": "캐터필러", "GE": "GE", "LMT": "록히드마틴", "RTX": "RTX",
    "DE": "디어", "XOM": "엑슨모빌", "CVX": "쉐브론", "COP": "코노코필립스",
    # 소비재·헬스케어
    "KO": "코카콜라", "PEP": "펩시", "WMT": "월마트", "COST": "코스트코",
    "UNH": "유나이티드헬스", "NKE": "나이키", "PG": "P&G", "SBUX": "스타벅스",
    "ABBV": "애브비", "TMO": "써모피셔",
    # 미디어·기타
    "CMCSA": "컴캐스트", "AAOI": "어플라이드옵토",
    # 중국 ADR
    "BABA": "알리바바", "JD": "징둥닷컴", "PDD": "핀둬둬", "BIDU": "바이두",
}


def _format_us_ticker(ticker):
    """AAPL → 애플(AAPL) / 매핑 없으면 그대로"""
    kr = US_TICKER_KR.get(ticker.upper())
    return f"{kr}({ticker})" if kr else ticker


def _parse_us_earning(entry):
    """US 실적 entry에서 ticker/session 추출. 예: 'GE 실적발표 (장전) [EPS est. $1.6]' → ('GE', '장전')"""
    raw = _clean_event_name(entry.get("기업명", "") or entry.get("보고서명", ""))
    m = re.match(r'^(.+?)\s*실적발표\s*\(([^)]+)\)\s*$', raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw.replace(' 실적발표', '').strip(), None


def _is_us_earning(entry):
    """미국 실적 여부 판별 (Finnhub은 보고서명에 '(장전)'/'(장후)' 포함)"""
    report = entry.get("보고서명", "") or ""
    return "(장전)" in report or "(장후)" in report


def _is_high_priority(name):
    """중요 이벤트 여부"""
    # 근원(Core) 지표는 파생 → HIGH 아님
    if "근원" in name or "Core " in name:
        return False
    # 일반 위원 발언은 HIGH 아님 (의장급만 HIGH)
    if ("Speaks" in name or "발언" in name) and not any(k in name for k in ["Powell", "파월", "Chair"]):
        return False
    return any(kw in name for kw in HIGH_PRIORITY_KEYWORDS)


def _is_low_priority(name):
    """저중요 이벤트 여부 (단, HIGH_PRIORITY에 해당하면 제외 안 함)"""
    if _is_high_priority(name):
        return False
    return any(kw in name for kw in LOW_PRIORITY_KEYWORDS)


def _format_schedule(title, schedule_data):
    date_str = schedule_data.get("date", "")
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    # 저중요 필터링
    filtered = []
    for ev in events:
        if not isinstance(ev, dict) or "error" in ev:
            continue
        event_name = ev.get("이벤트", "").strip()
        if not event_name or event_name.replace(".", "").replace("-", "").isdigit():
            continue
        if _is_low_priority(event_name):
            continue
        filtered.append(ev)

    # 전체 시간순 정렬 (중요 이벤트는 ★ 표시로 구분)
    _time_key = lambda ev: ev.get("시간", "") or "99:99"
    filtered.sort(key=_time_key)
    lines = []

    for ev in filtered[:10]:
        time_str = ev.get("시간", "").strip()
        event_name = ev.get("이벤트", "").strip()
        country = ev.get("국가", "").strip()

        # 국가 이모지
        if country and not country.startswith(("\U0001f1e6", "\U0001f1e8", "\U0001f1ef", "\U0001f1f0", "\U0001f1fa")):
            country = COUNTRY_EMOJI.get(country, country)

        # 중요 이벤트 ★ 표시
        marker = "★ " if _is_high_priority(event_name) else ""
        if time_str:
            lines.append(f"{time_str}(KST)  {marker}{country} {event_name}")
        else:
            lines.append(f"{marker}{country} {event_name}")

    # 실적 발표 — 국내/해외 분리 블록
    if earnings:
        kr_official = []   # 한국 확정 실적
        kr_provisional = []  # 한국 잠정 실적
        us_by_session = {}   # {"장전": [...], "장후": [...]}

        for e in earnings:
            if not isinstance(e, dict) or not e.get("기업명"):
                continue

            if _is_us_earning(e):
                company, session = _parse_us_earning(e)
                if not company:
                    continue
                bucket = us_by_session.setdefault(session or "기타", [])
                if company not in bucket:
                    bucket.append(company)
            else:
                # 한국 실적 (확정/잠정) — KRX 상장사만 통과
                name = _clean_event_name(e["기업명"])
                if not _is_listed_corp(name):
                    continue  # 상장사 아니면 제외 (FnGuide 비상장 필터)
                report = e.get("보고서명", "") or ""
                is_prov = "잠정" in report
                target = kr_provisional if is_prov else kr_official
                if name not in target and name not in kr_official and name not in kr_provisional:
                    target.append(name)

        earnings_lines = []
        if kr_official or kr_provisional:
            parts = []
            if kr_official:
                parts.extend(kr_official)
            if kr_provisional:
                # 잠정실적은 종목 앞에 "(잠정)" 표기
                parts.extend([f"(잠정) {n}" for n in kr_provisional])
            earnings_lines.append(f"🇰🇷 국내  {', '.join(parts)}")

        for session in ["장전", "장후", "기타"]:
            companies = us_by_session.get(session, [])
            if not companies:
                continue
            hint = SESSION_KST_HINT.get(session)
            if hint:
                label = f" ({session}·KST {hint})"
            elif session != "기타":
                label = f" ({session})"
            else:
                label = ""
            # 한글 병기 적용 (AAPL → 애플(AAPL))
            formatted = [_format_us_ticker(t) for t in companies[:6]]
            earnings_lines.append(f"🇺🇸 해외{label}  {', '.join(formatted)}")

        # TSLA 실적일 자동 주목 라인 추가 (국내 2차전지·AI 밸류체인 민감)
        all_us = [t for session_list in us_by_session.values() for t in session_list]
        if "TSLA" in [t.upper() for t in all_us]:
            earnings_lines.append("※ 주목  TSLA 실적 — 국내 2차전지·AI 밸류체인 민감도 높음")

        if earnings_lines:
            lines.append("")
            lines.append("📊 *실적발표*")
            lines.extend(earnings_lines)

    if not lines:
        lines.append("주요 일정 없음")

    lines.append("")
    lines.append(f"[전체 일정 보기]({CALENDAR_WEB_URL})")

    return f"📅 *{title}*\n{date_str}\n\n" + "\n".join(lines)


def format_today_schedule(schedule_data):
    return _format_schedule("오늘 일정", schedule_data)


_WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def format_tomorrow_schedule(schedule_data):
    """이브닝 브리핑 끝에 붙는 다음 거래일 일정.

    라벨 결정:
    - 대상일이 today+1 이면 '내일 일정'
    - 주말/공휴일 건너뛴 경우 '다음 거래일 일정 (월요일 04/27)' 처럼 명시
    - target_date_obj 없으면 '내일 일정' fallback
    """
    today = datetime.date.today()
    target = schedule_data.get("target_date_obj") if isinstance(schedule_data, dict) else None

    if isinstance(target, datetime.date):
        gap_days = (target - today).days
        if gap_days == 1:
            title = "내일 일정"
        else:
            weekday_kr = _WEEKDAY_KR[target.weekday()]
            title = f"다음 거래일 일정 ({weekday_kr} {target.strftime('%m/%d')})"
    else:
        title = "내일 일정"

    return _format_schedule(title, schedule_data)
