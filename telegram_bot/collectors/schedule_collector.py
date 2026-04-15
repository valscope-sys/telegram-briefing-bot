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
