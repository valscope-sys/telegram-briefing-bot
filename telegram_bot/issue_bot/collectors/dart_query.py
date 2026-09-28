"""DART 공시 조회 — on-demand /dart 명령어 전용

사용자가 봇 DM에 `/dart [날짜] [기업명]` 입력 시 호출.
DART OpenAPI list.json 호출 → 공시 목록 반환.
"""
import datetime
import requests

from telegram_bot.config import DART_API_KEY

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"


def estimate_quarter_from_date(date_str: str) -> str:
    """잠정실적 발표 날짜 → 해당 분기 추정.

    한국 상장사 잠정실적 발표 일정 (대략):
    - 1Q: 4~5월
    - 2Q: 7~8월
    - 3Q: 10~11월
    - 4Q (연간 사업보고서): 다음 해 1~3월

    Args:
        date_str: "YYYYMMDD" 또는 "YYYYMMDDHHMM"

    Returns:
        "1Q26" 형식 또는 빈 문자열
    """
    if not date_str or len(date_str) < 8:
        return ""
    try:
        d = datetime.datetime.strptime(date_str[:8], "%Y%m%d")
    except ValueError:
        return ""

    month = d.month
    yy = d.year % 100

    if 4 <= month <= 6:
        return f"1Q{yy:02d}"
    if 7 <= month <= 9:
        return f"2Q{yy:02d}"
    if 10 <= month <= 12:
        return f"3Q{yy:02d}"
    # 1~3월: 직전 연도 4Q (연간 사업보고서)
    prev_yy = (d.year - 1) % 100
    return f"4Q{prev_yy:02d}"


def parse_date_arg(arg: str):
    """날짜 인자 → date 객체. 파싱 실패 시 None.

    지원:
    - "오늘", "today"
    - "어제", "yesterday"
    - "그제", "그저께"
    - "YYYY-MM-DD", "YYYYMMDD"
    - "MM-DD", "MM/DD" (올해 가정)
    """
    arg = (arg or "").strip().lower()
    if not arg:
        return None

    today = datetime.date.today()

    if arg in ("오늘", "today"):
        return today
    if arg in ("어제", "yesterday"):
        return today - datetime.timedelta(days=1)
    if arg in ("그제", "그저께"):
        return today - datetime.timedelta(days=2)

    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(arg, fmt).date()
        except ValueError:
            continue

    # MM-DD / MM/DD (올해)
    for fmt in ("%m-%d", "%m/%d"):
        try:
            d = datetime.datetime.strptime(arg, fmt).date()
            return d.replace(year=today.year)
        except ValueError:
            continue

    return None


# 클라이언트 측 필터(보고서 키워드 / 회사명 부분 매칭)가 필요할 때 최대 조회 페이지 수.
# 평일 전체 공시는 하루 600~900건(7~9페이지), 분기보고서 마감일은 4천 건 이상.
_MAX_PAGES_FILTERED = 20


def fetch_dart_list(date: datetime.date, corp_name: str = None,
                    corp_code: str = None, page_count: int = 100,
                    report_patterns: list = None,
                    end_date: datetime.date = None,
                    pblntf_ty: str = None,
                    max_pages: int = None) -> list:
    """DART list.json 조회.

    Args:
        date: 조회 날짜 (end_date 지정 시 시작일)
        corp_name: 회사명 — corp_code 매핑 시도 후 정확한 corp_code로 호출.
            매칭 실패 시 클라이언트 측 부분 매칭 fallback.
        corp_code: 직접 corp_code 지정 (8자리). corp_name보다 우선.
        page_count: 페이지당 결과 수 (최대 100)
        end_date: 기간 조회 종료일 (선택). corp_code 없으면 DART 제한상 최대 3개월.
        pblntf_ty: 공시유형 (선택) — "A"=정기공시, "B"=주요사항보고, "I"=거래소공시 등.
        max_pages: 최대 조회 페이지 수. None이면 클라이언트 측 필터가 필요할 때만
            _MAX_PAGES_FILTERED 까지 넘겨 보고, 아니면 1페이지.

    Returns:
        [{"rcept_no", "corp_name", "report_nm", "rcept_dt", "url"}, ...]
    """
    if not DART_API_KEY:
        print("[DART_QUERY] ERROR: DART_API_KEY 없음 — 공시 조회 불가")
        return []

    date_str = date.strftime("%Y%m%d")
    end_str = (end_date or date).strftime("%Y%m%d")
    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": date_str,
        "end_de": end_str,
        "page_count": min(page_count, 100),
    }
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty

    # corp_code 매핑 시도 (corp_name → corp_code)
    resolved_corp_code = corp_code
    if not resolved_corp_code and corp_name:
        from telegram_bot.issue_bot.collectors.dart_corp_codes import find_corp_code
        match = find_corp_code(corp_name, limit=1)
        if match.get("exact"):
            resolved_corp_code = match["exact"]
            print(f"[DART_QUERY] '{corp_name}' → corp_code {resolved_corp_code} (정확 매칭)")
        elif match.get("candidates"):
            # 부분 매칭 후보가 1건이면 그걸 사용 (예: "삼전" → 삼성전자만 매칭)
            cands = match["candidates"]
            if len(cands) == 1:
                resolved_corp_code = cands[0]["code"]
                print(f"[DART_QUERY] '{corp_name}' → corp_code {resolved_corp_code} ({cands[0]['name']}, 단일 후보)")

    if resolved_corp_code:
        params["corp_code"] = resolved_corp_code
    elif corp_name:
        print(f"[DART_QUERY] '{corp_name}' corp_code 매칭 실패 → 전체 공시에서 회사명 부분 매칭")

    # 클라이언트 측 필터가 있으면 1페이지(최신 100건)만 보고 거르면 누락 → 여러 페이지 조회
    needs_client_filter = bool(report_patterns) or (bool(corp_name) and not resolved_corp_code)
    if max_pages is None:
        max_pages = _MAX_PAGES_FILTERED if needs_client_filter else 1

    try:
        raw_items = []
        page_no = 1
        total_page = 1
        total_count = 0
        while True:
            params["page_no"] = page_no
            res = requests.get(DART_LIST_URL, params=params, timeout=15)
            if res.status_code != 200:
                print(f"[DART_QUERY] ERROR: list.json HTTP {res.status_code} (page {page_no}) body={res.text[:120]!r}")
                if not raw_items:
                    return []
                break
            data = res.json()
            status = data.get("status")
            if status == "013":  # 조회된 데이터 없음 (정상)
                break
            if status != "000":
                print(f"[DART_QUERY] ERROR: list.json status={status} message={data.get('message','')} "
                      f"(page {page_no}, {params.get('bgn_de')}~{params.get('end_de')})")
                if not raw_items:
                    return []
                break
            raw_items.extend(data.get("list", []))
            total_page = int(data.get("total_page") or 1)
            total_count = int(data.get("total_count") or 0)
            if page_no >= total_page or page_no >= max_pages:
                break
            page_no += 1

        if total_page > page_no and needs_client_filter:
            print(f"[DART_QUERY] WARN: 전체 {total_count}건 중 {len(raw_items)}건({page_no}/{total_page}페이지)만 "
                  f"조회 후 필터 — 일부 누락 가능")

        results = []
        for item in raw_items:
            rcept_no = item.get("rcept_no", "")
            results.append({
                "rcept_no": rcept_no,
                "corp_name": item.get("corp_name", ""),
                "corp_code": item.get("corp_code", ""),
                "report_nm": item.get("report_nm", "").strip(),
                "rcept_dt": item.get("rcept_dt", ""),
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "",
            })

        # corp_code 매핑 실패 시 (corp_name 입력했으나 매칭 X)
        # 클라이언트 측 부분 매칭 fallback
        if corp_name and not resolved_corp_code:
            cname = corp_name.strip().lower()
            if cname:
                results = [
                    r for r in results
                    if cname in r.get("corp_name", "").lower()
                ]

        # 보고서 종류 필터 (사용자가 "실적", "자사주" 등 명시한 경우)
        if report_patterns:
            patterns_lower = [p.lower() for p in report_patterns]
            results = [
                r for r in results
                if any(p in r.get("report_nm", "").lower() for p in patterns_lower)
            ]

        return results
    except Exception as e:
        print(f"[DART_QUERY] ERROR: list.json 조회 실패: {type(e).__name__}: {e}")
        return []


def get_corp_code_candidates(query: str, limit: int = 5) -> list:
    """회사명 → corp_code 후보 목록 (정확 매칭 X 케이스에서 사용자 안내용)."""
    from telegram_bot.issue_bot.collectors.dart_corp_codes import find_corp_code
    result = find_corp_code(query, limit=limit)
    return result.get("candidates", [])


# 노이즈 보고서명 (조회 결과에서 자동 숨김)
_NOISE_REPORT_PATTERNS = (
    "감사보고서", "연결감사보고서",
    "주식등의대량보유상황보고서",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "공정거래자율준수프로그램",
    "결산공고", "기타시장안내",
    "효력발생안내", "주주명부폐쇄",
)


def filter_signal_disclosures(items: list) -> list:
    """노이즈 보고서명 제거. 조회 가독성 ↑."""
    out = []
    for it in items:
        rep = it.get("report_nm", "")
        if any(p in rep for p in _NOISE_REPORT_PATTERNS):
            continue
        out.append(it)
    return out


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트: 오늘 + 삼성전자
    date = datetime.date.today()
    items = fetch_dart_list(date, corp_name="삼성전자")
    print(f"== {date} 삼성전자 공시 {len(items)}건 ==")
    for it in items[:10]:
        print(f"  [{it['rcept_dt']}] {it['corp_name']} — {it['report_nm']}")
        print(f"    {it['url']}")
