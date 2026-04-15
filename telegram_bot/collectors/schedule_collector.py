"""경제 일정 수집 (calendar.json 기반 + DART 실시간 보완)"""
import datetime
import json
import requests
from pathlib import Path
from telegram_bot.config import DART_API_KEY

CALENDAR_JSON = Path(__file__).resolve().parent.parent.parent / "cal_data" / "calendar.json"

# 카테고리 → 국가 이모지 매핑
CATEGORY_COUNTRY = {
    "통화정책": "",       # country 필드 사용
    "경제지표": "",       # country 필드 사용
    "한국실적": "🇰🇷",
    "한국실적(잠정)": "🇰🇷",
    "미국실적": "🇺🇸",
    "IPO/공모": "🇰🇷",
    "산업컨퍼런스": "",
    "게임": "",
    "반도체": "",
    "자동차/배터리": "",
    "제약/바이오": "",
    "에너지": "",
    "방산": "",
    "전시/박람회": "",
    "만기일": "🇰🇷",
}

# === 텔레그램 필터 기준 ===

# 무조건 포함
ALWAYS_INCLUDE_CATS = {"경제지표", "통화정책", "만기일"}

# 실적 카테고리 (별도 earnings 섹션)
EARNINGS_CATS = {"한국실적", "한국실적(잠정)", "미국실적"}

# 이벤트로 포함 (조건부)
EVENT_CATS = {"IPO/공모", "산업컨퍼런스", "게임", "반도체", "자동차/배터리",
              "제약/바이오", "에너지", "방산", "전시/박람회", "K-콘텐츠",
              "정치/외교", "부동산", "수동"}

# 완전 제외
EXCLUDE_CATS = {"기업이벤트", "IR"}

# 기업이벤트 중 제외할 키워드
NOISE_KEYWORDS = ["액면분할", "액면병합", "유상증자", "무상증자", "기업합병", "주식소각"]

# IR 포함 기준: 시총 상위 50 기업만
TOP50_CORPS = {
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성바이오로직스", "현대차",
    "기아", "셀트리온", "KB금융", "신한지주", "POSCO홀딩스",
    "NAVER", "삼성SDI", "LG화학", "현대모비스", "카카오",
    "하나금융지주", "우리금융지주", "SK이노베이션", "LG전자", "삼성물산",
    "SK텔레콤", "KT", "삼성생명", "한국전력", "SK",
    "LG", "크래프톤", "HD현대중공업", "고려아연", "한화에어로스페이스",
    "두산에너빌리티", "HD한국조선해양", "카카오뱅크", "LG이노텍", "에코프로비엠",
    "한화오션", "삼성에스디에스", "한미반도체", "SK스퀘어", "엔씨소프트",
    "HD현대", "포스코퓨처엠", "삼성화재", "KT&G", "기업은행",
    "현대건설", "대한항공", "SK바이오팜", "HLB", "에코프로",
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


def _extract_corp_name(title):
    """제목에서 기업명 추출"""
    for suffix in [" 실적발표", " 잠정실적발표", " IR (경영현황)", " IR (실적발표)",
                   " 신규상장", " 공모청약"]:
        if title.endswith(suffix):
            return title[:-len(suffix)]
    if " IR (" in title:
        return title.split(" IR (")[0]
    return title


def _build_schedule(target_date):
    """일정 통합 조회 (calendar.json + DART 실시간)

    텔레그램 필터 기준:
    - 무조건 포함: 경제지표, 통화정책, 만기일
    - 실적: 한국실적(정식/잠정), 미국실적 → earnings 섹션
    - IR: 시총 상위 50 기업만 → earnings 섹션
    - 이벤트: IPO, 산업컨퍼런스, 게임 등 → events 섹션
    - 제외: 기업이벤트(액면분할/유증/합병), 소형주 IR
    """
    cal_events = _load_calendar_events(target_date)
    dart = fetch_dart_earnings(target_date)

    events = []
    earnings = []

    for e in cal_events:
        # 미확인(AI 스캔) / 미확정(월중/주차) 일정은 텔레그램에서 제외
        if e.get("unconfirmed") or e.get("undated"):
            continue

        cat = e.get("category", "")
        title = e.get("title", "")
        corp = _extract_corp_name(title)

        # 1. 실적 → earnings
        if cat in EARNINGS_CATS:
            earnings.append({"기업명": corp, "보고서명": title})
            continue

        # 2. IR → 시총 상위 50만 earnings에 포함
        if cat == "IR":
            if corp in TOP50_CORPS:
                earnings.append({"기업명": corp, "보고서명": title})
            continue

        # 3. 기업이벤트 → 노이즈 제외
        if cat == "기업이벤트":
            if any(kw in title for kw in NOISE_KEYWORDS):
                continue
            # 노이즈 아닌 기업이벤트 (대형 유증 등)는 이벤트로 포함
            country = e.get("country", "") or "🇰🇷"
            events.append({"시간": e.get("time", ""), "국가": country, "이벤트": title})
            continue

        # 4. 무조건 포함 카테고리 → events
        if cat in ALWAYS_INCLUDE_CATS:
            # title에 이미 이모지가 포함되어 있으면 country 생략 (중복 방지)
            has_emoji = any(ord(c) > 0x1F000 for c in title)
            country = "" if has_emoji else (e.get("country", "") or CATEGORY_COUNTRY.get(cat, ""))
            events.append({"시간": e.get("time", ""), "국가": country, "이벤트": title})
            continue

        # 5. 이벤트 카테고리 → events
        if cat in EVENT_CATS:
            has_emoji = any(ord(c) > 0x1F000 for c in title)
            country = "" if has_emoji else (e.get("country", "") or CATEGORY_COUNTRY.get(cat, ""))
            events.append({"시간": e.get("time", ""), "국가": country, "이벤트": title})
            continue

        # 6. 그 외 제외 (EXCLUDE_CATS 등)

    # 경제지표 후처리: 파생 지표 제거 + 영문→한글 + 중복 병합
    events = _filter_economic_events(events)

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


# 파생/중복 경제지표 제거 키워드
_DERIVATIVE_KEYWORDS = [
    "YTD", "QoQ", "Press Conference", "NBS Press",
    "Chinese GDP YTD", "Chinese Industrial Production YTD",
    "Core CPI", "Core 소비자물가",  # CPI YoY가 있으면 Core는 파생
    "CPI (MoM)", "소비자물가 (전월비)",  # YoY가 있으면 MoM은 파생
    "Supervisory Board", "감독위원",  # ECB 금리 결정 있으면 부속
    "Publishes Account", "의사록 공개",  # 금리 결정 당일이면 부속
    "Core PPI", "Core 생산자물가",  # PPI YoY가 있으면 Core는 파생
    "Continuing Jobless", "연속 실업수당",  # Initial이 메인, Continuing은 파생
]

# 영문 → 한글 번역 매핑
_EN_TO_KR = {
    "GDP (YoY)": "GDP (전년비)",
    "GDP (QoQ)": "GDP (전분기비)",
    "Industrial Production (YoY)": "산업생산 (전년비)",
    "Fixed Asset Investment (YoY)": "고정자산투자 (전년비)",
    "Unemployment Rate": "실업률",
    "Retail Sales (MoM)": "소매판매 (전월비)",
    "Retail Sales (YoY)": "소매판매 (전년비)",
    "CPI (YoY)": "소비자물가 (전년비)",
    "CPI (MoM)": "소비자물가 (전월비)",
    "PPI (YoY)": "생산자물가 (전년비)",
    "PPI (MoM)": "생산자물가 (전월비)",
    "Nonfarm Payrolls": "비농업 고용",
    "Initial Jobless Claims": "신규 실업수당 청구",
    "Manufacturing PMI": "제조업 PMI",
    "Services PMI": "서비스업 PMI",
    "Trade Balance": "무역수지",
    "ECB Interest Rate Decision": "ECB 금리 결정",
    "ECB's Lane Speaks": "ECB 렌 수석이코노미스트 발언",
    "ECB Supervisory Board Member Tuominen Speaks": "ECB 투오미넨 감독위원 발언",
    "ECB Publishes Account of Monetary Policy Meeting": "ECB 통화정책회의 의사록 공개",
    "Fed Chair Powell Speaks": "연준 파월 의장 발언",
    "FOMC Meeting Minutes": "FOMC 의사록 공개",
    "BOJ Interest Rate Decision": "일본은행 금리 결정",
    "Building Permits": "건축허가",
    "Housing Starts": "주택착공",
    "Empire State Manufacturing Index": "뉴욕 제조업지수",
    "Philadelphia Fed Manufacturing Index": "필라델피아 제조업지수",
    "Michigan Consumer Sentiment": "미시간 소비자심리",
    "Existing Home Sales": "기존주택판매",
    "New Home Sales": "신규주택판매",
    "Durable Goods Orders": "내구재주문",
    "PCE Price Index": "PCE 물가지수",
    "Core PCE Price Index": "핵심 PCE 물가지수",
    "Consumer Confidence": "소비자신뢰지수",
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "Continuing Jobless Claims": "연속 실업수당 청구",
    "Retail Sales": "소매판매",
    "Industrial Production": "산업생산",
    "Capacity Utilization Rate": "설비가동률",
    "Import Price Index": "수입물가지수",
    "Export Price Index": "수출물가지수",
    "Business Inventories": "기업재고",
    "Crude Oil Inventories": "원유재고",
}


def _filter_economic_events(events):
    """경제지표 후처리: 파생 제거 + 영문→한글 + 같은 시간 중복 병합"""
    filtered = []
    seen_keys = set()  # (시간, 국가, 핵심키워드)

    for ev in events:
        title = ev.get("이벤트", "")
        time_str = ev.get("시간", "")
        country = ev.get("국가", "")

        # 1. 파생 지표 제거
        if any(kw in title for kw in _DERIVATIVE_KEYWORDS):
            continue

        # 2. 영문 → 한글 번역
        for en, kr in _EN_TO_KR.items():
            if en in title:
                title = title.replace(en, kr)
        # "Chinese " 접두어 제거 (이미 국기로 구분)
        title = title.replace("Chinese ", "")
        ev["이벤트"] = title

        # 3. 같은 시간 + 같은 국가의 중복 방지
        # 핵심 키워드 추출 (첫 3단어)
        key_words = title.split()[:3]
        dedup_key = (time_str, country, tuple(key_words))
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        filtered.append(ev)

    return filtered


def fetch_today_schedule():
    """오늘 일정 조회"""
    return _build_schedule(datetime.date.today())


def fetch_tomorrow_schedule():
    """내일 일정 조회 (주말이면 다음 월요일)"""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow += datetime.timedelta(days=1)
    return _build_schedule(tomorrow)
