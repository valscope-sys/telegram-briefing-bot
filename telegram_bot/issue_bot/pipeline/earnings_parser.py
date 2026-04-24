"""잠정실적 공시 전용 파서 — Sonnet 없이 rule-based로 구조화 카드 생성

배경:
- DART "영업(잠정)실적(공정공시)" / "연결재무제표기준영업(잠정)실적(공정공시)"는
  표준화된 표 구조 ("매출액 | 당해실적 | N | N | -22.07 | - | N | 26.21 | -")
- Sonnet 호출 실패 시 _build_fallback_content가 body를 그대로 덤프 → 가독성 0
- 표 구조가 고정이라 정규식으로 수치 추출 후 메리츠 Tech 스타일 bullet으로 출력 가능

입력: fetch_kind_body가 반환한 본문 (단위: 백만원)
출력: 간결한 카드 텍스트 (단위: 억원/조원 변환)

예시:
  매출액    | 당해실적 | 1,358,209 | 1,742,956 | -22.07 | - | 1,076,135 | 26.21 | -
  영업이익  | 당해실적 | 152,322   | 260,511   | -41.53 | - | 102,387  | 48.77 | -
  당기순이익| 당해실적 | 79,518    | ...
    ↓
  - 매출액: 1조 3,582억원 (+26.2% YoY, -22.1% QoQ)
  - 영업이익: 1,523억원 (+48.8% YoY, -41.5% QoQ)
  - 당기순이익: 795억원 (...)
"""
import re
from typing import Optional


# 주요 손익 계정 (우선순위 순)
_ACCOUNTS = [
    ("매출액", "매출액"),
    ("영업이익", "영업이익"),
    ("당기순이익", "당기순이익"),
    ("지배기업 소유주지분 순이익", "지배주주 순이익"),
]

# 표 한 라인 매칭:
#   (계정명) | 당해실적 | (당기) | (전기) | (전기대비%) | - | (전년동기) | (전년동기대비%) | -
# 공백·단위 변동 고려. 숫자는 ','/음수부호 허용.
_NUMBER = r"-?[\d,]+(?:\.\d+)?"
_SEP = r"\s*\|\s*"
_TABLE_ROW = re.compile(
    r"(?P<account>매출액|영업이익|당기순이익|지배기업\s*소유주지분\s*순이익)"
    + _SEP + r"당해실적"
    + _SEP + r"(?P<now>" + _NUMBER + r")"
    + _SEP + r"(?P<prev>" + _NUMBER + r")"
    + _SEP + r"(?P<qoq>" + _NUMBER + r"|\-)"
    + _SEP + r"[^|]*"       # 흑자적자전환여부 (스킵)
    + _SEP + r"(?P<yoy_prev>" + _NUMBER + r")"
    + _SEP + r"(?P<yoy>" + _NUMBER + r"|\-)",
    re.MULTILINE,
)


def _to_number(s: str) -> Optional[float]:
    """문자열 숫자 (",", 음수) → float. '-'면 None."""
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s == "-" or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _format_amount_kr(million_won: float) -> str:
    """
    백만원 → 억원 / 조원 표기.
    135,820.9 백만원 = 1,358.2 억원 = 0.14 조원
    1,358,209 백만원 = 13,582.09 억원 = 1.36 조원

    표기 규칙 (메리츠 tech 스타일):
      - 1조 이상: "1조 3,582억원"
      - 1000억 이상: "3,582억원"
      - 100억 이상: "524억원"
      - 그 이하: "28억원" (소수 없음)
      - 음수: 앞에 "-" 또는 "적자" 처리는 caller가.
    """
    if million_won is None:
        return "-"
    # 백만원 → 억원
    eok = million_won / 100.0
    sign = "-" if eok < 0 else ""
    eok_abs = abs(eok)

    if eok_abs >= 10_000:  # 1조 이상 (= 10,000억)
        jo = int(eok_abs // 10_000)
        remain_eok = eok_abs - jo * 10_000
        if remain_eok >= 1:
            return f"{sign}{jo:,}조 {remain_eok:,.0f}억원"
        return f"{sign}{jo:,}조원"
    # 억원 단위
    if eok_abs >= 100:
        return f"{sign}{eok_abs:,.0f}억원"
    # 100억 미만
    return f"{sign}{eok_abs:,.1f}억원"


def _format_pct(pct: Optional[float]) -> str:
    """증감률 포맷: '+26.2%' / '-22.1%'. None이면 '-'."""
    if pct is None:
        return "-"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def parse_earnings_disclosure(body: str) -> Optional[dict]:
    """
    DART 잠정실적 공시 body에서 손익 수치 추출.

    Returns:
        {
          "period": "1Q26" 추정 or None,
          "accounts": [
            {"name":"매출액", "now":1358209, "prev":1742956,
             "qoq_pct":-22.07, "yoy_prev":1076135, "yoy_pct":26.21},
            ...
          ]
        }
        본문이 잠정실적 형식이 아니거나 표가 없으면 None.
    """
    if not body or len(body) < 200:
        return None

    # 잠정실적 공시 여부 힌트 — 테이블 관련 키워드
    if "잠정" not in body and "당해실적" not in body:
        return None

    accounts = []
    seen_names = set()
    for m in _TABLE_ROW.finditer(body):
        raw_name = m.group("account")
        # 공백 정규화
        name = re.sub(r"\s+", "", raw_name)
        if name in seen_names:
            continue
        seen_names.add(name)
        accounts.append({
            "name": name,
            "now": _to_number(m.group("now")),
            "prev": _to_number(m.group("prev")),
            "qoq_pct": _to_number(m.group("qoq")),
            "yoy_prev": _to_number(m.group("yoy_prev")),
            "yoy_pct": _to_number(m.group("yoy")),
        })

    if not accounts:
        return None

    # 기간 추출: "당기실적 | YYYY-MM-DD | ~ | YYYY-MM-DD"
    period = None
    pm = re.search(
        r"당기실적\s*\|\s*(\d{4})-(\d{2})-\d{2}\s*\|\s*~\s*\|\s*\d{4}-(\d{2})-\d{2}",
        body,
    )
    if pm:
        year = pm.group(1)[2:]  # '2026' → '26'
        start_m = int(pm.group(2))
        end_m = int(pm.group(3))
        # 분기 추정 — 메리츠 스타일 "1Q26" (QN + YY)
        if (start_m, end_m) == (1, 3):
            period = f"1Q{year}"
        elif (start_m, end_m) == (4, 6):
            period = f"2Q{year}"
        elif (start_m, end_m) == (7, 9):
            period = f"3Q{year}"
        elif (start_m, end_m) == (10, 12):
            period = f"4Q{year}"
        else:
            period = f"{year}.{start_m}~{end_m}"

    return {"period": period, "accounts": accounts}


def format_earnings_card(company_name: str, parsed: dict,
                         source_url: str = "",
                         is_consolidated: bool = True) -> str:
    """
    파싱된 잠정실적 dict → 메리츠 Tech 스타일 카드 텍스트.

    Args:
        company_name: 회사명 (예: "효성중공업")
        parsed: parse_earnings_disclosure 결과
        source_url: DART 원문 URL (선택)
        is_consolidated: True면 "연결", False면 "개별"

    Returns:
        텔레그램 발송용 텍스트
    """
    period = parsed.get("period") or ""
    prefix = "연결 " if is_consolidated else "개별 "
    title_suffix = f" {period} 잠정실적" if period else " 잠정실적"

    lines = [
        f"[{company_name}{title_suffix}]",
        "",
    ]

    # 계정별 bullet
    acc_map = {a["name"]: a for a in parsed["accounts"]}
    for name_key, display_name in _ACCOUNTS:
        # _ACCOUNTS의 name_key는 공백 제거된 상태. acc_map도 마찬가지
        normalized_key = re.sub(r"\s+", "", name_key)
        acc = acc_map.get(normalized_key)
        if not acc:
            continue

        now_str = _format_amount_kr(acc["now"])
        yoy_str = _format_pct(acc["yoy_pct"])
        qoq_str = _format_pct(acc["qoq_pct"])

        # 증감률 쌍
        if yoy_str != "-" and qoq_str != "-":
            change = f"({yoy_str} YoY, {qoq_str} QoQ)"
        elif yoy_str != "-":
            change = f"({yoy_str} YoY)"
        elif qoq_str != "-":
            change = f"({qoq_str} QoQ)"
        else:
            change = ""

        lines.append(f"- {display_name}: {now_str} {change}".rstrip())
        lines.append("")  # 빈 줄 구분

    # 마지막 빈 줄 정리 후 출처·면책
    while lines and not lines[-1]:
        lines.pop()
    lines.append("")

    if source_url:
        lines.append(f"(자료: DART — {source_url})")
    else:
        lines.append("(자료: DART)")
    lines.append("")
    lines.append(
        "* 본 내용은 당사의 코멘트 없이 국내외 언론사 뉴스 및 전자공시자료 등을 "
        "인용한 것으로 별도의 승인 절차 없이 제공합니다."
    )

    return "\n".join(lines)


def is_earnings_disclosure(report_nm: str) -> bool:
    """잠정실적 공시 여부 판별."""
    if not report_nm:
        return False
    nm = report_nm.replace(" ", "")
    return "(잠정)실적" in nm


def is_consolidated(report_nm: str) -> bool:
    """연결 여부 (연결 vs 개별)"""
    return "연결재무제표" in (report_nm or "")


def try_generate_earnings_card(event: dict) -> Optional[str]:
    """
    이벤트가 잠정실적 공시면 rule-based 카드 생성. 아니면 None.

    generator.py에서 Sonnet 호출 전에 시도하는 용도.
    성공 시 Sonnet 호출 스킵 가능 (품질·일관성·비용 모두 이득).

    Args:
        event: dart_collector 반환 이벤트 dict

    Returns:
        카드 텍스트 or None (형식 미매칭·파싱 실패 시)
    """
    report_nm = event.get("report_nm_raw") or event.get("report_nm_clean") or event.get("title", "")
    if not is_earnings_disclosure(report_nm):
        return None

    body = event.get("body_excerpt") or event.get("original_content", "")
    parsed = parse_earnings_disclosure(body)
    if not parsed or not parsed.get("accounts"):
        return None

    company = event.get("company_name", "").strip() or "(회사명 미상)"
    url = event.get("source_url", "")
    is_cons = is_consolidated(report_nm)

    return format_earnings_card(company, parsed, source_url=url, is_consolidated=is_cons)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 실제 효성중공업 body 테스트
    sample = """실적기간
당기실적 | 2026-01-01 | ~ | 2026-03-31
전기실적 | 2025-10-01 | ~ | 2025-12-31
전년동기실적 | 2025-01-01 | ~ | 2025-03-31
※ 동 정보는 잠정치로서 향후 확정치와는 다를 수 있음.
1. 연결실적내용 | 단위 : 백만원, %
매출액 | 당해실적 | 1,358,209 | 1,742,956 | -22.07 | - | 1,076,135 | 26.21 | -
누계실적 | 1,358,209 | - | - | - | 1,076,135 | 26.21 | -
영업이익 | 당해실적 | 152,322 | 260,511 | -41.53 | - | 102,387 | 48.77 | -
당기순이익 | 당해실적 | 79,518 | 195,408 | -59.30 | - | 62,123 | 28.00 | -
지배기업 소유주지분 순이익 | 당해실적 | 75,000 | 190,000 | -60.00 | - | 60,000 | 25.00 | -
"""

    parsed = parse_earnings_disclosure(sample)
    print("=== 파싱 결과 ===")
    import json
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    print()
    print("=== 카드 출력 ===")
    card = format_earnings_card("효성중공업", parsed, source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260424800834")
    print(card)
