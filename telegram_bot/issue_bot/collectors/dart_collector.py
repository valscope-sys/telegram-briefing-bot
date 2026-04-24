"""DART 공시 수집기 — Phase 1

동작:
1. opendart.fss.or.kr의 list.json 폴링 (최근 공시)
2. dart_category_map.json으로 rule-based 필터링 (빠른 1차 분류)
3. KIND(dart.fss.or.kr) HTML에서 본문 발췌 (iframe 처리)
4. seen_ids.jsonl로 중복 제외
5. 구조화된 이슈 이벤트 리스트 반환 (downstream 파이프라인으로 전달)

반환 스키마:
{
  "id": "dart_{rcept_no}",
  "source": "DART",
  "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...",
  "source_id": "20260421000123",
  "fetched_at": "ISO8601",
  "ticker": "005930",
  "company_name": "삼성전자",
  "corp_code": "00126380",
  "corp_cls": "Y",           # Y=유가, K=코스닥, N=코넥스, E=기타
  "title": "주요사항보고서(자기주식취득결정)",
  "report_nm_raw": "...",
  "body_excerpt": "본문 300자",
  "category_hint": "B",      # dart_category_map 매칭 시 Template 힌트
  "priority_hint": "URGENT", # dart_category_map 매칭 시 priority 힌트
  "event_type": "자사주",     # dedup_key 생성용
  "date": "2026-04-21"
}
"""
import os
import json
import datetime
import re
import time
import requests
from bs4 import BeautifulSoup

from telegram_bot.config import DART_API_KEY

HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
)
DART_CATEGORY_MAP_PATH = os.path.join(HISTORY_DIR, "dart_category_map.json")
LAST_RCEPT_NO_PATH = os.path.join(HISTORY_DIR, "issue_bot", "last_rcept_no.txt")

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
KIND_VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
KIND_IFRAME_URL = "https://dart.fss.or.kr{path}"  # iframe src 보통 /dsaf001/dsaf001.do?rcpNo=...&dcmNo=...


# 공용 세션 (TCP 재사용 — 메모리·연결 효율)
_dart_session = None


def _get_dart_session():
    global _dart_session
    if _dart_session is None:
        _dart_session = requests.Session()
        _dart_session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; NODEResearchBot/1.0)"
        })
    return _dart_session


# ===== 증분 폴링 커서 =====

def get_last_rcept_no() -> str:
    """마지막으로 처리한 rcept_no. 없으면 빈 문자열 (=첫 실행)."""
    if not os.path.exists(LAST_RCEPT_NO_PATH):
        return ""
    try:
        with open(LAST_RCEPT_NO_PATH, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def save_last_rcept_no(rcept_no: str):
    """rcept_no 커서 갱신 (다음 폴링에서 이 값 이후만 처리)."""
    if not rcept_no:
        return
    os.makedirs(os.path.dirname(LAST_RCEPT_NO_PATH), exist_ok=True)
    try:
        with open(LAST_RCEPT_NO_PATH, "w") as f:
            f.write(rcept_no)
    except Exception as e:
        print(f"[DART] last_rcept_no 저장 실패: {e}")


# ===== category_map 로딩 (모듈 load 시 1회) =====

_CATEGORY_MAP = None


def _load_category_map():
    global _CATEGORY_MAP
    if _CATEGORY_MAP is not None:
        return _CATEGORY_MAP
    try:
        with open(DART_CATEGORY_MAP_PATH, "r", encoding="utf-8") as f:
            _CATEGORY_MAP = json.load(f)
    except FileNotFoundError:
        print(f"[DART] category_map 없음: {DART_CATEGORY_MAP_PATH}")
        _CATEGORY_MAP = {"mappings": {}, "skip_patterns": [], "prefix_rules": {}}
    return _CATEGORY_MAP


# ===== report_nm 정규화 =====

def _normalize_report_nm(raw: str) -> tuple:
    """
    report_nm에서 공백 정리 + 접두사 분리.
    Returns: (clean_name, prefix)
      예: "[기재정정]단일판매ㆍ공급계약체결   " -> ("단일판매ㆍ공급계약체결", "[기재정정]")
    """
    if not raw:
        return "", ""
    s = raw.strip()
    prefix = ""
    m = re.match(r"^(\[기재정정\]|\[정정\]|\[첨부정정\]|\[기재수정\])\s*(.*)$", s)
    if m:
        prefix = m.group(1)
        s = m.group(2).strip()
    # 내부 연속 공백 정리
    s = re.sub(r"\s+", " ", s)
    return s, prefix


# ===== 키워드 패턴 분류 (2026-04-23 추가) =====
#
# 설계 철학: category_map.json의 exact match 한계 (괄호 위치·조사 차이로 누락 발생)를
# 극복하기 위한 report_nm 정규식 기반 fallback.
#
# 매칭 순서: skip_patterns → exact_map → substring fallback → **키워드 정규식** → None(Haiku)
#
# 2026-04-23 치명적 누락 사례:
#   - "연결재무제표기준영업(잠정)실적(공정공시)" — 삼성SDS/하이닉스/현대차 등
#     매핑엔 "영업실적등에대한전망(공정공시)"(미래 가이던스)만 있어서 miss
#   - 그 외 report_nm이 매분기 조금씩 변형되어 exact match 실패 다수
# 이 패턴 기반 분류로 report_nm 변형에 강건하게 대응.

_KEYWORD_PATTERNS = [
    # ===== URGENT — 시장 즉각 반응 =====
    # 잠정실적 공시 (개별/연결 모두, "(잠정)실적" 키워드로 통합 커버)
    ("URGENT", r"\(잠정\)실적", "잠정실적 공시"),
    # 실적 전망·가이던스 ("실적등에대한전망")
    ("URGENT", r"영업실적등에대한전망", "영업실적 전망(가이던스)"),
    # 손익구조 변동 (매출액·영업이익·순이익 30%/15%+ 변동)
    ("URGENT", r"손익구조.*?변경|손익구조.*?변동", "손익구조 대폭 변경"),
    # 바이오: 품목허가 승인 (신청과 구분, (?<!신청) 부정 lookbehind)
    ("URGENT", r"(?<!신청[(])품목허가(?!신청)", "품목허가 승인"),
    # 자기주식 소각 (주주환원 시그널은 유지하지만 사용자 정책상 NORMAL — 이 라인은 주석)
    # ("URGENT", r"자기주식소각결정", "자사주 소각"),

    # ===== HIGH — 밸류체인·중기 영향 =====
    ("HIGH", r"신규시설투자", "Capex·증설"),
    ("HIGH", r"임상시험계획승인", "임상 진입"),
    ("HIGH", r"품목허가신청", "바이오 허가 신청"),

    # ===== SKIP — 노이즈 =====
    ("SKIP", r"주권매매거래정지|매매거래정지", "거래정지"),
    ("SKIP", r"은행거래정지", "은행거래정지"),
    ("SKIP", r"감사보고서", "감사보고서"),
    ("SKIP", r"특정증권등소유상황보고서|대량보유상황보고서", "지분공시"),
    ("SKIP", r"결산실적공시예고", "결산 일정 예고(실체 無)"),
    ("SKIP", r"증권신고서|증권발행실적보고서|투자설명서|일괄신고", "증권발행 관련"),
]


def _classify_by_keywords(clean_name: str) -> dict:
    """
    report_nm 키워드 정규식 기반 분류. exact/substring 매핑 실패 시 fallback.

    매핑보다 관대하지만 확실한 키워드만 잡음 — 모호하면 None 반환해 Haiku에 위임.
    """
    for priority, pattern, label in _KEYWORD_PATTERNS:
        if re.search(pattern, clean_name):
            return {
                "template": "B",
                "priority": priority,
                "reason": f"keyword_pattern: {label} (re: {pattern})",
                "matched_key": clean_name,
            }
    return None


def classify_by_rules(report_nm_raw: str) -> dict:
    """
    report_nm을 category_map + 키워드 패턴으로 매칭해 template/priority 힌트 반환.
    매칭 실패 시 None 반환 → downstream에서 Haiku 필터가 분류.

    순서:
      1. skip_patterns (substring contains)
      2. mappings exact match
      3. mappings substring fallback (양방향)
      4. **키워드 정규식 패턴** (2026-04-23 추가 — exact 실패 보완)
      5. prefix_rules (강등)
    """
    cat_map = _load_category_map()
    clean_name, prefix = _normalize_report_nm(report_nm_raw)

    # 1. skip_patterns 매칭 (우선)
    for sp in cat_map.get("skip_patterns", []):
        if sp in clean_name:
            return {
                "template": None,
                "priority": "SKIP",
                "reason": f"skip_pattern 매칭: {sp}",
                "prefix": prefix,
            }

    # 2. 직접 매핑
    mappings = cat_map.get("mappings", {})
    mapping = mappings.get(clean_name)
    if not mapping:
        # 부분 일치 fallback (예: "주요사항보고서(자기주식취득결정)"이 정확히 없어도 "자기주식취득결정"만 있을 때)
        for key, val in mappings.items():
            if key in clean_name or clean_name in key:
                mapping = val
                break

    # 3. 키워드 정규식 fallback (2026-04-23 추가)
    # mapping이 없거나 NORMAL(카드 미발송 기본값)인데 키워드 매칭되면 키워드 결과 우선
    # — 예: "단일판매ㆍ공급계약체결"(매핑 NORMAL)엔 키워드 안 잡힘 → 매핑 유지.
    #   "연결재무제표기준영업(잠정)실적(공정공시)"(매핑 없음) → 키워드 URGENT 매칭.
    if not mapping:
        kw_result = _classify_by_keywords(clean_name)
        if kw_result:
            # prefix_rules 적용 (기재정정 → 강등)
            if prefix:
                prefix_rules = cat_map.get("prefix_rules", {})
                rule = prefix_rules.get(prefix)
                if rule and rule.get("priority_override"):
                    kw_result["priority"] = rule["priority_override"]
            kw_result["prefix"] = prefix
            return kw_result
        return None  # 키워드도 실패 → Haiku에게 맡김

    priority = mapping.get("priority", "NORMAL")
    template = mapping.get("template", "B")

    # 4. prefix_rules 적용 ([기재정정] 등 → 우선순위 강등)
    if prefix:
        prefix_rules = cat_map.get("prefix_rules", {})
        rule = prefix_rules.get(prefix)
        if rule and rule.get("priority_override"):
            priority = rule["priority_override"]

    return {
        "template": template,
        "priority": priority,
        "reason": f"dart_category_map: {clean_name}",
        "prefix": prefix,
        "matched_key": clean_name,
    }


def infer_event_type(report_nm_raw: str) -> str:
    """dedup_key 생성에 쓰일 event_type 추정"""
    clean_name, _ = _normalize_report_nm(report_nm_raw)
    patterns = [
        (r"자사주|자기주식", "자사주"),
        (r"실적|영업이익|매출|분기보고|반기보고|사업보고", "실적"),
        (r"유상증자|무상증자|감자", "증자감자"),
        (r"합병|분할|영업양도|영업양수", "M&A"),
        (r"타법인주식", "M&A"),
        (r"전환사채|신주인수권부사채|교환사채|전환청구", "채권"),
        (r"단일판매|공급계약|수주", "계약"),
        (r"대량보유|최대주주|주주변경", "지분변동"),
        (r"임상|품목허가", "임상"),
        (r"거래정지|상장폐지", "거래정지"),
        (r"기업가치제고", "밸류업"),
        (r"IR|기업설명회", "IR"),
    ]
    for pat, etype in patterns:
        if re.search(pat, clean_name):
            return etype
    return "misc"


# ===== DART API =====

def fetch_recent_disclosures(days_back: int = 1, page_count: int = 100, corp_cls=None):
    """
    DART list.json으로 최근 공시 목록 조회.

    Args:
        days_back: 며칠치 (기본 1 = 오늘)
        page_count: 페이지당 조회 건수 (최대 100)
        corp_cls: "Y"(유가)/"K"(코스닥)/"N"(코넥스). None=전체

    Returns:
        list of dict (원본 DART 응답 아이템 그대로)
    """
    if not DART_API_KEY:
        print("[DART] DART_API_KEY 없음 — 빈 리스트 반환")
        return []

    today = datetime.date.today()
    bgn = (today - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": 1,
        "page_count": page_count,
        "last_reprt_at": "Y",
    }
    if corp_cls:
        params["corp_cls"] = corp_cls

    try:
        res = _get_dart_session().get(DART_LIST_URL, params=params, timeout=15)
        data = res.json()
    except Exception as e:
        print(f"[DART] API 호출 실패: {e}")
        return []

    if data.get("status") != "000":
        print(f"[DART] API 오류: {data.get('message')}")
        return []

    return data.get("list", [])


def fetch_kind_body(rcept_no: str, max_chars: int = 1800) -> str:
    """
    KIND HTML에서 본문 추출. iframe 구조를 2-step으로 처리.
    표/목록/문장 모두 텍스트화하여 Sonnet이 의미 파악 가능한 정보량 확보.

    Returns:
        본문 발췌 (최대 max_chars자). 실패 시 빈 문자열.
    """
    sess = _get_dart_session()
    try:
        # 1단계: 뷰어 페이지에서 iframe URL 추출
        view_url = KIND_VIEW_URL.format(rcept_no=rcept_no)
        res = sess.get(view_url, timeout=15)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")

        iframe_url = None
        # viewDoc(rcpNo, dcmNo, eleId, offset, ...) JS 호출 파싱
        # 2026-04-24 수정: DART가 single quote 'X' → double quote "X" 로 변경.
        # 기존 regex는 single quote만 허용 → 전체 DART 공시 본문 0자 반환되는 치명 버그.
        # 첫 매칭이 변수형태(viewDoc(original.rcpNo, ...))일 수 있어 숫자 리터럴만 매칭.
        m = re.search(
            r"""viewDoc\(\s*['"](\d+)['"]\s*,\s*['"](\d+)['"]""",
            res.text,
        )
        if m:
            dcm_no = m.group(2)
            iframe_url = (
                f"https://dart.fss.or.kr/report/viewer.do?rcpNo={rcept_no}&dcmNo={dcm_no}"
                f"&eleId=0&offset=0&length=0&dtd=HTML"
            )
        else:
            iframe = soup.find("iframe")
            if iframe and iframe.get("src"):
                src = iframe["src"]
                iframe_url = src if src.startswith("http") else f"https://dart.fss.or.kr{src}"

        if not iframe_url:
            return ""

        # 2단계: iframe 본문 요청
        res2 = sess.get(iframe_url, timeout=15)
        if res2.status_code != 200:
            return ""

        soup2 = BeautifulSoup(res2.text, "lxml")
        for tag in soup2(["script", "style", "noscript"]):
            tag.decompose()

        parts = []

        # 테이블 셀도 개별 토큰으로 유지 (DART 공시는 표 위주)
        for table in soup2.find_all("table"):
            for tr in table.find_all("tr"):
                row_cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                row_cells = [c for c in row_cells if c]
                if row_cells:
                    parts.append(" | ".join(row_cells))
            table.decompose()

        # 나머지 텍스트 (문장, 목록 등)
        remaining = soup2.get_text(separator=" ", strip=True)
        if remaining:
            parts.append(remaining)

        text = "\n".join(parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]
    except Exception as e:
        print(f"[DART] KIND 본문 추출 실패 ({rcept_no}): {e}")
        return ""


# ===== 통합 수집 인터페이스 =====

def collect_disclosures(days_back: int = 1, fetch_body: bool = True,
                       incremental: bool = True, first_run_limit: int = 10) -> list:
    """
    최근 공시를 수집하여 이슈봇 파이프라인 형식으로 반환.

    Args:
        days_back: 며칠 전까지 (기본 1일)
        fetch_body: True면 KIND HTML 본문 추출 (느림, N+1 요청)
        incremental: True면 seen_ids 기반 증분 (미처리만 반환)
        first_run_limit: 첫 실행 시 최근 N건만 처리 (부팅 몰빵 방지)

    Returns:
        list of 이슈 이벤트 dict (SKIP 판정된 항목 제외).
        rcept_no 오름차순 정렬 (오래된 것부터).

    2026-04-24 수정: rcept_no 문자열 커서 방식 폐기.
    DART rcept_no는 'YYYYMMDD + 6자리' 구조이며 앞 3자리는 시스템 prefix
    (800xxx=KIND, 900xxx=특수 등). 같은 날짜 내에서도 시간 순서와 번호 순서가
    일치하지 않아 문자열 비교로 cursor 추적 시 800xxx 공시가 통째로 누락되는
    버그 발생 (예: 기아 잠정실적 20260424800317이 한국 실적 공시의 대부분인
    800xxx 계열인데, 이전 폴링에서 900xxx 하나 들어오면 전부 차단).

    대안: 매 폴링마다 어제~오늘 전체 조회 + seen_ids 기반 dedup으로 위임.
    main.py의 is_duplicate() 체크가 이미 dedup_key 기반으로 정확히 작동.
    last_rcept_no 파일은 호환성 유지 위해 존재만 하고 실제 필터링 로직에선 미사용.
    """
    raw_items = fetch_recent_disclosures(days_back=days_back)

    # rcept_dt(YYYYMMDD) 우선, 동일 날짜 내 rcept_no로 정렬
    # 완벽한 시간순은 아니지만 날짜 단위 정렬은 유효
    raw_items.sort(key=lambda x: (x.get("rcept_dt", ""), x.get("rcept_no", "")))

    if incremental:
        # seen_ids 파일 크기로 첫 실행 여부 판단 (몰빵 방지)
        from telegram_bot.issue_bot.pipeline.dedup import SEEN_IDS_PATH, _ensure_seen_file
        _ensure_seen_file()
        try:
            seen_size = os.path.getsize(SEEN_IDS_PATH)
        except OSError:
            seen_size = 0

        if seen_size < 200:  # 거의 비었으면 첫 실행으로 간주
            raw_items = raw_items[-first_run_limit:]
            print(f"[DART] 첫 실행(seen_ids 비어있음) — 최근 {first_run_limit}건으로 제한")
        else:
            # 전체 반환 — 증분 dedup은 main.py의 is_duplicate()로 위임
            print(f"[DART] 스캔 — {len(raw_items)}건 (중복은 seen_ids로 필터)")

    events = []
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    for item in raw_items:
        rcept_no = item.get("rcept_no", "")
        report_nm_raw = item.get("report_nm", "")

        # 1차 rule-based 분류
        cls = classify_by_rules(report_nm_raw)

        # SKIP 판정이면 스킵 (rcept_dt 형식만 YYYYMMDD → YYYY-MM-DD)
        if cls and cls.get("priority") == "SKIP":
            continue

        rcept_dt = item.get("rcept_dt", "")
        date_str = (
            f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"
            if len(rcept_dt) == 8 else datetime.date.today().strftime("%Y-%m-%d")
        )

        event = {
            "id": f"dart_{rcept_no}",
            "source": "DART",
            "source_url": KIND_VIEW_URL.format(rcept_no=rcept_no),
            "source_id": rcept_no,
            "fetched_at": now_iso,
            "ticker": item.get("stock_code", "") or None,
            "company_name": item.get("corp_name", ""),
            "corp_code": item.get("corp_code", ""),
            "corp_cls": item.get("corp_cls", ""),
            "title": report_nm_raw.strip(),
            "report_nm_raw": report_nm_raw,
            "report_nm_clean": _normalize_report_nm(report_nm_raw)[0],
            "body_excerpt": "",
            "category_hint": cls.get("template") if cls else None,
            "priority_hint": cls.get("priority") if cls else None,
            "rule_match_reason": cls.get("reason") if cls else "매칭 실패(Haiku 필터 필요)",
            "event_type": infer_event_type(report_nm_raw),
            "date": date_str,
        }

        # 2단계: KIND 본문 (선택)
        if fetch_body:
            event["body_excerpt"] = fetch_kind_body(rcept_no)
            time.sleep(0.2)  # KIND rate limit 예방

        events.append(event)

    return events


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 70)
    print("DART 수집기 실행 (최근 1일, 본문 스킵)")
    print("=" * 70)
    events = collect_disclosures(days_back=1, fetch_body=False)
    print(f"\n수집된 이슈: {len(events)}건 (SKIP 제외)\n")

    # priority별 집계
    from collections import Counter
    prio_cnt = Counter(e.get("priority_hint") for e in events)
    print(f"priority 분포: {dict(prio_cnt)}\n")

    # 상위 10건 출력
    for ev in events[:10]:
        print(f"  [{ev['priority_hint'] or '?':<7}] [{ev['category_hint'] or '?'}] "
              f"{ev['company_name'][:15]:<15} | {ev['report_nm_clean'][:50]}")
        print(f"    → {ev['rule_match_reason']}")
        print()
