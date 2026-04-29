"""분기 추이 카드 — 네이버 증권 분기 데이터 + DART 잠정실적 공시 통합

사용 시나리오:
- "두산 실적" / "두산 분기 추이" → 최근 4개 분기 카드
- "두산 1Q26" → 단일 분기 카드 (잠정실적 발표 직후 vs 컨센 비교)

데이터 소스:
- 네이버 증권 분기 추이 (consensus_fetcher.fetch_naver_consensus)
  - 단위: 억원
  - 매출액·영업이익·당기순이익 + (E) 표시
- DART 잠정실적 공시 (해당 분기 발표 URL 매칭)

카드 형식 (사용자 정책 2026-04-29):
- 분기별 빈 줄 구분
- 매출액·영업이익·순이익만 (해석/시사점 X)
- (E) 분기는 "예상치" 표기
- 발표된 분기는 vs 컨센 비교 (잠정실적 카드와 동일)
- 면책 미리보기 X (채널 발송 시에만)
"""
import datetime
import re
from typing import Optional


# 네이버 분기 라벨 → 표시용 분기 (예: "2026.03" → "1Q26")
_MONTH_TO_QUARTER = {"03": "1Q", "06": "2Q", "09": "3Q", "12": "4Q"}


def naver_label_to_period(label: str) -> Optional[str]:
    """네이버 라벨('2026.03') → period('1Q26'). 매칭 실패 시 None."""
    m = re.match(r"(\d{4})\.(\d{2})", label or "")
    if not m:
        return None
    yyyy, mm = m.group(1), m.group(2)
    q = _MONTH_TO_QUARTER.get(mm)
    if not q:
        return None
    return f"{q}{yyyy[2:]}"


def period_to_year_month(period: str) -> Optional[tuple]:
    """period('1Q26') → (year, month_end). 예: ('2026', '03')."""
    m = re.match(r"([1-4])Q(\d{2})", period or "")
    if not m:
        return None
    q, yy = m.group(1), m.group(2)
    month_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
    month = month_map.get(q)
    if not month:
        return None
    return (f"20{yy}", month)


def _format_eok(value: Optional[float]) -> str:
    """억원 단위 숫자 → "8,512억" 형식. None이면 "-"."""
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 10_000:
        jo = int(v // 10_000)
        remain = v - jo * 10_000
        if remain >= 1:
            return f"{sign}{jo:,}조 {remain:,.0f}억"
        return f"{sign}{jo:,}조"
    if v >= 100:
        return f"{sign}{v:,.0f}억"
    return f"{sign}{v:,.1f}억"


def _format_pct(pct: Optional[float]) -> str:
    if pct is None:
        return "-"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def resolve_company(query: str) -> dict:
    """회사명 → corp_code/stock_code 매핑.

    Returns:
        {
          "ok": True,
          "corp_code": "00112004",
          "stock_code": "267270",
          "name": "HD현대건설기계",
          "candidates": [...] (단일 매칭이면 길이 1, 복수면 5건 이내)
        }
        또는 {"ok": False, "candidates": [...], "reason": "..."}
    """
    from telegram_bot.issue_bot.collectors.dart_corp_codes import find_corp_code

    result = find_corp_code(query, limit=5)
    if result.get("exact"):
        ex = result["candidates"][0]
        return {
            "ok": True,
            "corp_code": result["exact"],
            "stock_code": ex.get("stock_code", ""),
            "name": ex.get("name", ""),
            "candidates": [ex],
        }

    cands = result.get("candidates", [])
    listed = [c for c in cands if c.get("stock_code")]

    if len(listed) == 1:
        c = listed[0]
        return {
            "ok": True,
            "corp_code": c["code"],
            "stock_code": c["stock_code"],
            "name": c["name"],
            "candidates": listed,
        }

    if not listed:
        return {
            "ok": False,
            "candidates": [],
            "reason": f"'{query}' 매칭되는 상장사 없음.",
        }

    return {
        "ok": False,
        "candidates": listed,
        "reason": f"'{query}' 매칭 후보 {len(listed)}곳 — 회사명 더 구체적으로.",
    }


def fetch_quarter_disclosure_url(corp_code: str, period: str) -> Optional[str]:
    """해당 분기의 DART 잠정실적/분기보고서 URL fetch.

    잠정실적 발표 시점:
    - 1Q: 4월 ~ 5월
    - 2Q: 7월 ~ 8월
    - 3Q: 10월 ~ 11월
    - 4Q: 다음 해 1월 ~ 3월 (사업보고서)

    Returns:
        DART URL 또는 None (미발표·매칭 실패)
    """
    from telegram_bot.issue_bot.collectors.dart_query import fetch_dart_list

    ym = period_to_year_month(period)
    if not ym:
        return None
    year, month_end = ym
    end_month = int(month_end)

    # 발표 가능 기간: 분기말 다음 달 ~ 3개월 후
    start_month = end_month + 1
    start_year = int(year)
    if start_month > 12:
        start_month -= 12
        start_year += 1

    fin_month = start_month + 3
    fin_year = start_year
    if fin_month > 12:
        fin_month -= 12
        fin_year += 1

    start_date = datetime.date(start_year, start_month, 1)
    fin_date = datetime.date(fin_year, fin_month, 1) - datetime.timedelta(days=1) \
        if fin_month != 1 else datetime.date(fin_year - 1, 12, 31)

    # 매일 조회는 비용 큼 — 핵심 발표 기간 가운데 1주만 샘플
    candidates_keywords = [
        "(잠정)실적", "잠정실적",
        "분기보고서", "반기보고서", "사업보고서",
    ]

    found_urls = []
    cur = start_date
    while cur <= fin_date and len(found_urls) < 1:
        items = fetch_dart_list(cur, corp_code=corp_code, page_count=20)
        for it in items:
            rep = it.get("report_nm", "")
            if any(kw in rep for kw in candidates_keywords):
                found_urls.append(it.get("url", ""))
                break
        cur += datetime.timedelta(days=7)

    return found_urls[0] if found_urls else None


def _format_quarter_block(period: str, info: dict, url: str = "") -> str:
    """분기 1개 → 카드 블록 텍스트.

    Args:
        period: "1Q26"
        info: {revenue, op_income, net_income, is_estimate}
        url: DART URL (있으면 표시)
    """
    is_est = info.get("is_estimate", False)
    suffix = " (예상)" if is_est else ""

    rev = info.get("revenue")
    op = info.get("op_income")
    net = info.get("net_income")

    lines = [
        f"<b>{period}{suffix}</b>",
        f"매출액 : {_format_eok(rev)}",
        f"영업익 : {_format_eok(op)}",
        f"순이익 : {_format_eok(net)}",
    ]
    if url:
        lines.append(f"원문 : <code>{url}</code>")
    return "\n".join(lines)


def build_trend_card(company_query: str, target_period: str = None,
                     max_quarters: int = 4) -> dict:
    """분기 추이 카드 생성.

    Args:
        company_query: 사용자 입력 회사명 (예: "두산", "삼성전자")
        target_period: 특정 분기 1개만 ("1Q26"). None이면 최근 max_quarters개.
        max_quarters: target_period 미지정 시 표시할 분기 개수 (기본 4).

    Returns:
        {
          "ok": True,
          "text": "<HTML 텍스트>",
          "company": "두산",
          "stock_code": "000150",
          "periods": ["1Q26", "4Q25", "3Q25", "2Q25"],
        }
        또는 {"ok": False, "error": "...", "candidates": [...]}
    """
    from telegram_bot.issue_bot.collectors.consensus_fetcher import fetch_naver_consensus

    resolved = resolve_company(company_query)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("reason", "회사명 매칭 실패"),
            "candidates": resolved.get("candidates", []),
        }

    stock_code = resolved.get("stock_code")
    if not stock_code:
        return {
            "ok": False,
            "error": f"'{resolved['name']}'은 비상장 회사 (네이버 데이터 없음).",
            "candidates": [],
        }

    data = fetch_naver_consensus(stock_code)
    if not data or not data.get("quarters"):
        return {
            "ok": False,
            "error": f"네이버 분기 데이터 없음 ({stock_code}). 잠시 후 재시도.",
            "candidates": [],
        }

    quarters_dict = data["quarters"]

    # 라벨 정렬 (최신 → 과거)
    sorted_labels = sorted(quarters_dict.keys(), reverse=True)

    if target_period:
        target_label = None
        # 정확 매칭 시도 (예: "1Q26")
        for lbl in sorted_labels:
            if naver_label_to_period(lbl) == target_period:
                target_label = lbl
                break
        # 연도 미명시 ("1Q") → 가장 최근 해당 분기
        if not target_label and len(target_period) == 2:
            for lbl in sorted_labels:
                p = naver_label_to_period(lbl) or ""
                if p.startswith(target_period):
                    target_label = lbl
                    target_period = p  # 정확 분기명으로 갱신
                    break
        if not target_label:
            return {
                "ok": False,
                "error": f"'{target_period}' 분기 데이터 네이버에서 찾을 수 없음 (최근 분기만 제공).",
                "candidates": [],
            }
        chosen_labels = [target_label]
    else:
        chosen_labels = sorted_labels[:max_quarters]

    if not chosen_labels:
        return {
            "ok": False,
            "error": "표시할 분기 데이터 없음.",
            "candidates": [],
        }

    # 분기별 블록 + DART URL fetch (단일 분기일 때만 — 4분기 카드는 부담 큼)
    blocks = []
    periods = []
    for lbl in chosen_labels:
        period = naver_label_to_period(lbl) or lbl
        info = quarters_dict[lbl]
        url = ""
        if target_period and not info.get("is_estimate"):
            try:
                url = fetch_quarter_disclosure_url(resolved["corp_code"], period) or ""
            except Exception as e:
                print(f"[QUARTER_CARD] DART URL fetch 실패 ({period}): {e}")
        blocks.append(_format_quarter_block(period, info, url))
        periods.append(period)

    company_label = resolved["name"]
    if target_period:
        title = f"<b>[{company_label} {target_period}]</b>"
    else:
        title = f"<b>[{company_label} — 최근 {len(blocks)}개 분기 추이]</b>"

    parts = [title, ""]
    parts.append("\n\n".join(blocks))
    parts.append("")
    parts.append("<i>(자료: 네이버 증권)</i>")

    return {
        "ok": True,
        "text": "\n".join(parts),
        "company": company_label,
        "stock_code": stock_code,
        "corp_code": resolved["corp_code"],
        "periods": periods,
    }


def build_channel_text(card: dict) -> str:
    """trend card → 채널 발송용 텍스트 (HTML 태그 제거 + 면책 추가)."""
    if not card or not card.get("ok"):
        return ""
    raw = card["text"]
    # HTML 태그 제거 (Telegram 채널은 plain 또는 HTML 둘 다 허용 — 카드 전용 HTML 유지)
    return raw + "\n\n* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다."


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트 1: HD현대건설기계 — 4분기 추이
    print("=== HD현대건설기계 — 4분기 추이 ===")
    res = build_trend_card("HD현대건설기계")
    if res["ok"]:
        print(res["text"])
        print(f"\n분기: {res['periods']}")
    else:
        print(f"실패: {res['error']}")
        for c in res.get("candidates", []):
            print(f"  후보: [{c['code']}] {c['name']} (stock={c.get('stock_code', '')})")

    print()

    # 테스트 2: HD현대건설기계 — 1Q26 단일
    print("=== HD현대건설기계 — 1Q26 ===")
    res = build_trend_card("HD현대건설기계", target_period="1Q26")
    if res["ok"]:
        print(res["text"])
    else:
        print(f"실패: {res['error']}")

    print()

    # 테스트 3: 모호한 회사명 (두산)
    print("=== 두산 (모호) ===")
    res = build_trend_card("두산")
    if not res["ok"]:
        print(f"실패: {res['error']}")
        for c in res.get("candidates", [])[:5]:
            print(f"  후보: [{c['code']}] {c['name']} (stock={c.get('stock_code', '')})")
