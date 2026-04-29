"""자연어 → 명령어 변환 (NLU)

전략: Rule 우선 → Haiku fallback (옵션 C)
- Rule이 90% 케이스 처리 (비용 0)
- 모호한 표현만 Haiku 호출 (비용 ~$0.001/회)

사용자 자유 텍스트 → "/news 어제 09:00-12:00 반도체" 같은 명령어 문자열.
"""
import re
import anthropic

from telegram_bot.config import ANTHROPIC_API_KEY


# ===== Rule 패턴 =====

# 의도 키워드 (확장)
NEWS_KEYWORDS = (
    "뉴스", "기사", "헤드라인", "보도", "보도자료", "리포트", "소식", "news",
)
DART_KEYWORDS = (
    "공시", "공시자료", "공시내역", "전자공시", "기업공시",
    "DART", "dart", "KIND", "kind",
)
CARD_KEYWORDS = ("카드", "정리", "요약")  # URL과 함께 쓰일 때
HELP_KEYWORDS = ("도움", "도움말", "help", "명령어", "사용법", "메뉴", "안내")

# 보고서 종류 키워드 → DART report_nm 매칭 패턴
# 사용자가 "실적·자사주·M&A" 같은 표현 쓰면 dart_query에서 결과 필터
REPORT_KEYWORDS = {
    "실적": ["실적", "손익구조", "30%변경", "15%변경"],
    "잠정실적": ["(잠정)실적", "잠정실적"],
    "자사주": ["자기주식"],
    "공급계약": ["단일판매", "공급계약"],
    "수주": ["단일판매", "공급계약"],
    "유상증자": ["유상증자"],
    "무상증자": ["무상증자"],
    "증자": ["유상증자", "무상증자"],
    "전환사채": ["전환사채"],
    "신주인수권부사채": ["신주인수권부사채"],
    "CB": ["전환사채"],
    "BW": ["신주인수권부사채"],
    "EB": ["교환사채"],
    "M&A": ["회사합병", "회사분할", "타법인주식및출자증권취득", "영업양도", "영업양수"],
    "합병": ["회사합병"],
    "분할": ["회사분할"],
    "인수": ["타법인주식및출자증권취득"],
    "Capex": ["신규시설투자"],
    "투자": ["신규시설투자"],
    "증설": ["신규시설투자"],
    "품목허가": ["품목허가"],
    "FDA": ["품목허가"],
    "임상": ["임상시험계획승인"],
    "IR": ["기업설명회(IR)"],
    "기업설명회": ["기업설명회"],
    "배당": ["현금ㆍ현물배당", "주식배당", "배당"],
    "주총": ["주주총회"],
    "주주총회": ["주주총회"],
    "정관": ["정관변경"],
    "최대주주": ["최대주주"],
    "감자": ["감자결정"],
    "주식분할": ["주식분할"],
    "주식병합": ["주식병합"],
    "기업가치제고": ["기업가치제고계획"],
    "Value-Up": ["기업가치제고계획"],
    "밸류업": ["기업가치제고계획"],
    "특허": ["특허권취득"],
    "지분매각": ["타법인주식및출자증권처분"],
    "거래정지": ["거래정지", "주권매매거래정지"],
    "부도": ["부도발생"],
    "회생": ["회생절차"],
    "상장폐지": ["상장폐지"],
}


def extract_report_keyword(text: str) -> tuple:
    """텍스트에서 보고서 종류 키워드 추출.

    Returns:
        (matched_keyword, report_patterns) 또는 (None, None)
        예: "대한전선 실적 공시" → ("실적", ["실적", "손익구조", ...])
    """
    text_lower = text.lower()
    # 긴 키워드 먼저 매칭 (Value-Up이 "Value"보다 먼저)
    sorted_keys = sorted(REPORT_KEYWORDS.keys(), key=lambda k: -len(k))
    for kw in sorted_keys:
        if kw.lower() in text_lower:
            return (kw, REPORT_KEYWORDS[kw])
    return (None, None)

# 날짜 표현 (한국어 → 정규화, 광범위 추가)
DATE_PATTERNS = {
    "오늘": "오늘",
    "지금": "오늘",
    "당일": "오늘",
    "금일": "오늘",
    "오늘자": "오늘",
    "어제": "어제",
    "어제자": "어제",
    "어젯밤": "어제",
    "어젯저녁": "어제",
    "어제부터": "어제",
    "전일": "어제",
    "그제": "그제",
    "그저께": "그제",
    "그제자": "그제",
}

# YYYY-MM-DD 또는 YYYYMMDD
DATE_RE = re.compile(r"\b(20\d{2})[\-/]?(\d{1,2})[\-/]?(\d{1,2})\b")

# 시간 범위: "9시부터 12시까지", "9~12시", "9-12시", "오전 9시 ~ 오후 3시"
HOUR_RANGE_RE = re.compile(
    r"(오전|오후|아침|저녁|밤)?\s*(\d{1,2})\s*시\s*"
    r"(?:부터|에서|~|-|–|—)\s*"
    r"(오전|오후|아침|저녁|밤)?\s*(\d{1,2})\s*시\s*(?:까지)?"
)
# 단일 시간 ("9시")은 안 잡음 (모호)

# 상대 시간: "최근 3시간", "3시간 전부터", "30분 전"
RELATIVE_RE = re.compile(r"(?:최근\s*)?(\d+)\s*(시간|분)\s*(?:전|동안|이내|간)?")

# URL
URL_RE = re.compile(r"https?://\S+")

# 분기 패턴: "1Q26", "1Q", "1분기", "2분기"
QUARTER_RE = re.compile(
    r"\b([1-4])\s*[Qq]\s*(\d{2,4})?\b|"
    r"\b([1-4])\s*분기\b",
    re.IGNORECASE,
)


def extract_quarter(text: str) -> str:
    """텍스트에서 분기 표현 추출.

    Returns:
        "1Q26" (정확) / "1Q" (연도 미명시) / None
    """
    if not text:
        return None
    m = QUARTER_RE.search(text)
    if not m:
        return None
    # 그룹 1·2: "1Q26" 패턴
    if m.group(1):
        q = m.group(1)
        yr = m.group(2)
        if yr:
            # 4자리 → 뒤 2자리
            yr = yr[-2:]
            return f"{q}Q{yr}"
        return f"{q}Q"
    # 그룹 3: "1분기" 패턴
    if m.group(3):
        return f"{m.group(3)}Q"
    return None


def _normalize_hour(hour: int, period: str) -> int:
    """오전/오후/아침/저녁/밤 + hour → 24h."""
    period = (period or "").strip()
    if period in ("오후", "저녁", "밤"):
        return hour + 12 if hour < 12 else hour
    if period == "아침":
        return hour
    if period == "오전" and hour == 12:
        return 0
    return hour


def _rule_nlu(text: str) -> str:
    """자연어 → 명령어 문자열. 매칭 실패 시 None.

    Returns:
        "/news 어제 09:00-12:00 반도체" 같은 명령어 문자열 또는 None
    """
    text = (text or "").strip()
    if not text:
        return None

    text_lower = text.lower()
    original = text

    # 0. URL 단독 또는 카드 키워드 + URL → /card
    url_match = URL_RE.search(text)
    if url_match:
        return f"/card {url_match.group(0)}"

    # 1. /help
    if any(kw in text_lower for kw in HELP_KEYWORDS):
        return "/help"

    # 2. 의도 분류
    is_news = any(kw in text for kw in NEWS_KEYWORDS)
    is_dart = any(kw in text for kw in DART_KEYWORDS)

    if not is_news and not is_dart:
        return None  # 의도 모호 → Haiku fallback

    # DART 우선 (둘 다 있을 때 — "공시 뉴스" 같은 케이스에서 공시가 더 구체적)
    cmd = "/dart" if is_dart else "/news"
    args = []
    remaining = text

    # 3. 날짜 추출
    date_arg = None
    for ko_date, normalized in DATE_PATTERNS.items():
        if ko_date in remaining:
            date_arg = normalized
            remaining = remaining.replace(ko_date, " ", 1)
            break
    if not date_arg:
        # YYYY-MM-DD 형식
        m = DATE_RE.search(remaining)
        if m:
            y, mo, d = m.groups()
            date_arg = f"{y}-{int(mo):02d}-{int(d):02d}"
            remaining = remaining.replace(m.group(0), " ")
    if date_arg:
        args.append(date_arg)

    # 4. 시간 범위 추출
    time_arg = None
    m = HOUR_RANGE_RE.search(remaining)
    if m:
        period1, h1, period2, h2 = m.groups()
        try:
            hh1 = _normalize_hour(int(h1), period1 or "")
            hh2 = _normalize_hour(int(h2), period2 or period1 or "")
            if 0 <= hh1 < 24 and 0 <= hh2 < 24:
                time_arg = f"{hh1:02d}:00-{hh2:02d}:00"
                remaining = remaining.replace(m.group(0), " ")
        except ValueError:
            pass
    if not time_arg:
        # 상대 시간
        m = RELATIVE_RE.search(remaining)
        if m:
            n, unit = m.groups()
            unit_short = "h" if "시간" in unit else "m"
            time_arg = f"{n}{unit_short}"
            remaining = remaining.replace(m.group(0), " ")
    if time_arg:
        args.append(time_arg)

    # 4-5. 보고서 종류 키워드 추출 (DART일 때만 의미 있음)
    if cmd == "/dart":
        report_kw, _ = extract_report_keyword(remaining)
        if report_kw:
            args.append(f"#report:{report_kw}")
            remaining = re.sub(re.escape(report_kw), " ", remaining, flags=re.IGNORECASE)

        # 분기 추출 ("1Q26", "1분기" 등) — 회사명에서 분리
        quarter = extract_quarter(remaining)
        if quarter:
            args.append(f"#quarter:{quarter}")
            # remaining에서 분기 표현 제거
            remaining = QUARTER_RE.sub(" ", remaining)

    # 5. 의도 키워드 제거
    for kw in NEWS_KEYWORDS + DART_KEYWORDS:
        remaining = remaining.replace(kw, " ")

    # 6. 조사·부사·접미어·관용 표현 제거 (광범위 클렌징)
    # 순서 중요: 긴 패턴 먼저 (이슈나 → 이슈, 사이에 → 사이)
    remaining = re.sub(
        # 조사
        r"(관련된|관련의|관련|관한|에서의|에서|에게|에는|에도|에만|에|"
        r"의|을|를|로의|으로의|로|으로|와|과|"
        # 동사·형용사 활용
        r"있었어|있었나|있었던|있었을|있을까|있을지|있나|있는지|있는|있던|있어|있을|"
        r"있나요|있습니까|있을까요|있습니다|"
        r"나왔어|나왔나|나왔던|나왔는지|나왔을|나오는|나온|나오나|"
        r"올라왔어|올라왔나|올라왔던|올라왔는지|올라온지|올라온|올라왔을|"
        r"발생한|발생했어|발생했나|발생했던|발생|"
        r"알수\s*있어|알수\s*있나|알수\s*있나요|알수|알아봐|알아서|알려주세요|"
        r"해주세요|해주실|해주실래요|해주시면|"
        r"보내줘|보내봐|보여줘|보여줄래|찾아줘|찾아봐|봐줘|봐봐|받아와|"
        r"가져와|가져와봐|뽑아|뽑아줘|올려|올려줘|"
        r"검색해|검색해봐|검색해줘|검색해주세요|"
        r"정리해|정리해줘|정리해봐|"
        # 의문사·부사
        r"무엇이|무엇을|뭐가|뭐를|뭐|무슨|어떤|어떻게|얼마나|"
        r"어떤거|어떤게|어떤걸|어떤지|"
        r"좀|혹시나|혹시|한번|해봐|해줘|해주세요|줘봐|"
        r"알려줘|알려줄래|알려줄|확인해|확인|체크해|체크|"
        # 시간 부사
        r"방금|방금전|조금전|막|아까|지금까지|"
        r"아침에|아침|점심|점심에|점심때|오전에|오후에|저녁에|저녁|새벽에|새벽|밤에|"
        r"이번\s*주|지난\s*주|지지난\s*주|이번\s*달|지난\s*달|올해|작년|"
        # "제일 최근", "가장 최근", "최근/최신" — 가장 최신 1건 의미
        r"제일\s*최근|가장\s*최근|최근의|최근|최신의|최신|"
        r"이번\s*분기|지난\s*분기|이번분기|지난분기|"
        # 의미 약한 명사/관용 표현
        r"공시자료|공시내역|기업공시|전자공시|공시|"
        r"뉴스|기사|헤드라인|소식|보도자료|보도|리포트|정보|내용|"
        r"실적공시|실적발표|실적이|실적은|실적의|실적|"
        r"사이에|사이의|사이|동안|중에서|중에|중|"
        r"주요한|주요|중요한|중요|핵심|주된|특별한|중대한|"
        r"이슈나|이슈가|이슈는|이슈|건들|건이|건은|건|것들|것은|것이|것|"
        r"내역|상황|결과|발표|결정)",
        " ", remaining,
    )
    # 구두점 + 자연어 기호 (이모지 일부도 — 종결)
    remaining = re.sub(r"[\?\!\.\,\~\-\(\)\[\]\{\}\:\;\"\'\、\。]", " ", remaining)
    # 반복 구두점 ("????", "...") 처리
    remaining = re.sub(r"[!?.~]{2,}", " ", remaining)
    remaining = re.sub(r"\s+", " ", remaining).strip()

    # 키워드가 너무 짧거나 단일 자모/숫자만이면 제거 (의미 없음)
    if remaining:
        # 1글자 단어는 의미 없을 가능성 높음 (조사 잔재)
        words = [w for w in remaining.split() if len(w) >= 2]
        remaining = " ".join(words).strip()

    if remaining:
        args.append(remaining)

    cmd_str = f"{cmd} {' '.join(args)}".strip()
    return cmd_str


# ===== Haiku NLU (fallback) =====

_NLU_SYSTEM_PROMPT = """당신은 텔레그램 봇 명령어 변환기입니다.
사용자 자연어 메시지를 다음 4가지 명령어 중 하나로 변환하세요.

[명령어 목록]
1. /card <URL>
   - URL로 카드 생성
   - 예: "https://buly.kr/abc 카드로" → "/card https://buly.kr/abc"

2. /dart [날짜] [시간범위] [기업명]
   - DART 공시 조회
   - 예: "어제 삼성전자 공시" → "/dart 어제 삼성전자"
   - 예: "오늘 9시부터 12시까지 공시" → "/dart 오늘 09:00-12:00"

3. /news [날짜] [시간범위] [키워드]
   - 뉴스 헤드라인 조회
   - 예: "어제 반도체 뉴스" → "/news 어제 반도체"
   - 예: "최근 3시간 뉴스" → "/news 3h"

4. /help
   - 명령어 안내

[인자 형식]
- 날짜: 오늘 / 어제 / 그제 / YYYY-MM-DD
- 시간 범위: HH:MM-HH:MM (예: 09:00-12:00) 또는 Nh / Nm (예: 3h, 30m)
- 키워드 / 기업명: 그대로

[응답 규칙]
- 명령어 한 줄만 출력 (예: "/news 어제 09:00-12:00 반도체")
- 다른 설명·인사·마크다운 절대 금지
- 의도 파악 불가능하면 정확히 "UNKNOWN" 반환
"""


def _haiku_nlu(text: str) -> str:
    """Haiku로 자유 텍스트 → 명령어 변환. 실패 시 None."""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=_NLU_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text[:300]}],
        )
        result = response.content[0].text.strip()
        # 마크다운 백틱 제거
        result = result.strip("`").strip()
        # 첫 줄만
        result = result.split("\n")[0].strip()
        if result == "UNKNOWN" or not result.startswith("/"):
            return None
        return result
    except Exception as e:
        print(f"[NLU] Haiku 호출 실패: {e}")
        return None


# ===== 진입점 =====

def parse_natural_language(text: str) -> tuple:
    """자유 텍스트 → (cmd, args) 튜플. 실패 시 (None, None).

    Returns:
        (cmd_str, args_list) — 예: ("/news", ["어제", "09:00-12:00", "반도체"])
        또는 (None, None) 실패
    """
    if not text:
        return (None, None)

    # 1. Rule 우선
    cmd_str = _rule_nlu(text)
    if cmd_str:
        parts = cmd_str.split()
        if parts:
            return (parts[0], parts[1:])

    # 2. Haiku fallback
    cmd_str = _haiku_nlu(text)
    if cmd_str:
        parts = cmd_str.split()
        if parts:
            return (parts[0], parts[1:])

    return (None, None)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    test_cases = [
        "오늘 뉴스 알려줘",
        "어제 9시부터 12시까지 뉴스",
        "최근 3시간 반도체 뉴스",
        "삼성전기 공시 봐줘",
        "오늘 무슨 공시 있었어?",
        "어제 14시-18시 SK하이닉스 공시",
        "https://www.etnews.com/12345 카드로 만들어줘",
        "도움말 보여줘",
        "주요 이슈 뭐 있어?",  # 모호 → Haiku
    ]
    for t in test_cases:
        cmd, args = parse_natural_language(t)
        print(f"입력: {t}")
        print(f"  → cmd={cmd} args={args}")
        print()
