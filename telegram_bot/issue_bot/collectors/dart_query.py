"""DART 공시 조회 — on-demand /dart 명령어 전용

사용자가 봇 DM에 `/dart [날짜] [기업명]` 입력 시 호출.
DART OpenAPI list.json 호출 → 공시 목록 반환.
"""
import datetime
import requests

from telegram_bot.config import DART_API_KEY

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"


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


def fetch_dart_list(date: datetime.date, corp_name: str = None,
                    corp_code: str = None, page_count: int = 100,
                    report_patterns: list = None) -> list:
    """DART list.json 조회.

    Args:
        date: 조회 날짜
        corp_name: 회사명 — corp_code 매핑 시도 후 정확한 corp_code로 호출.
            매칭 실패 시 클라이언트 측 부분 매칭 fallback.
        corp_code: 직접 corp_code 지정 (8자리). corp_name보다 우선.
        page_count: 최대 결과 수 (기본 100)

    Returns:
        [{"rcept_no", "corp_name", "report_nm", "rcept_dt", "url"}, ...]
    """
    if not DART_API_KEY:
        return []

    date_str = date.strftime("%Y%m%d")
    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": date_str,
        "end_de": date_str,
        "page_count": min(page_count, 100),
    }

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

    try:
        res = requests.get(DART_LIST_URL, params=params, timeout=15)
        if res.status_code != 200:
            print(f"[DART_QUERY] HTTP {res.status_code}")
            return []
        data = res.json()
        status = data.get("status")
        if status not in ("000", "013"):
            print(f"[DART_QUERY] status={status} message={data.get('message','')}")
            return []
        if status == "013":
            return []

        results = []
        for item in data.get("list", []):
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
        print(f"[DART_QUERY] 조회 실패: {e}")
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
