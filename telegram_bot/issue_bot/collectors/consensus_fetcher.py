"""네이버 증권 분기 컨센서스 fetcher — 이슈봇 전용

네이버 종목 메인 페이지(`finance.naver.com/item/main.naver?code=NNNNNN`)의
'기업실적분석' 섹션에서 분기별 매출액/영업이익/당기순이익 + (E) 컨센서스 추출.

기존 시황봇 `telegram_bot/collectors/consensus_collector.py`(FnGuide 기반,
매출·영업이익만)는 JS 렌더링 의존도 높고 순이익 누락 → 이슈봇 잠정실적 카드
"vs 컨센" 표시용으로 부적합. 네이버는 정적 HTML이라 안정적 + 순이익 포함.

사용:
    consensus = fetch_naver_consensus("267270")
    # consensus['quarters'] 안에 분기별 dict
    # 잠정실적 분기('1Q26' → '2026.03')와 매칭해서 (E)면 컨센 비교

단위: 억원 (네이버 페이지 표기 그대로)
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional


_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
    return _session


# 분기 라벨 매핑 — earnings_parser의 period(예: "1Q26") → 네이버 라벨("2026.03")
_PERIOD_TO_NAVER = {
    "1Q": "03", "2Q": "06", "3Q": "09", "4Q": "12",
}


def period_to_naver_quarter(period: str) -> Optional[str]:
    """earnings_parser period('1Q26') → 네이버 분기 라벨('2026.03')."""
    if not period:
        return None
    m = re.match(r"([1-4]Q)(\d{2})", period)
    if not m:
        return None
    q, yy = m.group(1), m.group(2)
    month = _PERIOD_TO_NAVER.get(q)
    if not month:
        return None
    return f"20{yy}.{month}"


def _parse_int(s: str) -> Optional[int]:
    """문자열 → int. 음수 부호 + 콤마 처리. '-' 또는 빈값이면 None."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    if s in ("-", ""):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def fetch_naver_consensus(stock_code: str) -> Optional[dict]:
    """
    네이버 증권 종목 페이지에서 분기 컨센서스 + 실적 추출.

    Args:
        stock_code: 6자리 종목코드 (예: '267270')

    Returns:
        {
          'quarters': {
            '2025.12': {'revenue': 9473, 'op_income': 334, 'net_income': 185, 'is_estimate': False},
            '2026.03': {'revenue': 21946, 'op_income': 1432, 'net_income': 983, 'is_estimate': True},
            ...
          }
        }
        실패/페이지 없음/구조 깨짐 시 None.
        단위: 억원.
    """
    if not stock_code or not re.fullmatch(r"\d{6}", stock_code):
        return None

    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    try:
        r = _get_session().get(url, timeout=10)
        if r.status_code != 200:
            return None
        # 네이버는 EUC-KR 인코딩
        r.encoding = r.apparent_encoding or "euc-kr"
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"[CONSENSUS] fetch 실패 ({stock_code}): {e}")
        return None

    section = soup.select_one("div.section.cop_analysis")
    if not section:
        return None
    table = section.select_one("table")
    if not table:
        return None

    thead = table.find("thead")
    tbody = table.find("tbody")
    if not (thead and tbody):
        return None

    # ─── 헤더에서 분기 라벨 추출 ───
    # 네이버 thead 구조 (rowspan·colspan 복잡):
    #   tr1: "주요재무정보 | 최근 연간 실적 (colspan 4) | 최근 분기 실적 (colspan 6)"
    #   tr2: "2023.12 | 2024.12 | 2025.12 | 2026.12 | 2024.12 | 2025.03 | 2025.06 | 2025.09 | 2025.12 | 2026.03"
    #   tr3: " | | | (E) | | | | | | (E)"
    # 같은 컬럼 인덱스의 tr2 라벨 + tr3 (E) 표시 합쳐서 (label, is_estimate) 추출
    header_rows = thead.find_all("tr")
    if len(header_rows) < 2:
        return None

    # tr2: 분기 라벨 (YYYY.MM 패턴)
    label_cells = header_rows[1].find_all(["th", "td"])
    labels = [c.get_text(" ", strip=True) for c in label_cells]

    # tr3: (E)/(P) 등 표시
    estimate_marks = []
    if len(header_rows) >= 3:
        mark_cells = header_rows[2].find_all(["th", "td"])
        estimate_marks = [c.get_text(" ", strip=True) for c in mark_cells]

    # 정규화: YYYY.MM 패턴인 것만 살림
    quarter_meta = []  # [(label, is_estimate), ...]
    for i, lbl in enumerate(labels):
        m = re.match(r"(\d{4}\.\d{2})", lbl)
        if not m:
            continue
        clean_label = m.group(1)
        mark = estimate_marks[i] if i < len(estimate_marks) else ""
        is_est = "(E)" in mark or "(E)" in lbl
        quarter_meta.append((clean_label, is_est))

    if not quarter_meta:
        return None

    # ─── tbody에서 매출/영업이익/당기순이익 행 추출 ───
    label_to_key = {
        "매출액": "revenue",
        "영업이익": "op_income",
        "당기순이익": "net_income",
    }
    result_by_label = {}
    for row in tbody.find_all("tr"):
        th = row.find("th")
        if not th:
            continue
        row_label = th.get_text(" ", strip=True)
        if row_label not in label_to_key:
            continue
        key = label_to_key[row_label]

        cells = row.find_all("td")
        # cells의 i번째가 quarter_meta의 i번째와 매칭
        for i, (q_label, is_est) in enumerate(quarter_meta):
            if i >= len(cells):
                break
            val = _parse_int(cells[i].get_text(" ", strip=True))
            if q_label not in result_by_label:
                result_by_label[q_label] = {"is_estimate": is_est}
            result_by_label[q_label][key] = val

    if not result_by_label:
        return None

    return {"quarters": result_by_label}


def get_consensus_for_period(stock_code: str, period: str) -> Optional[dict]:
    """
    잠정실적 카드 발송 시 호출. 분기 매칭해서 컨센서스만 반환.

    Args:
        stock_code: '267270'
        period:     '1Q26' (earnings_parser period 형식)

    Returns:
        {'revenue': 21946, 'op_income': 1432, 'net_income': 983, 'is_estimate': True}
        또는 None (분기 매칭 실패·해당 분기가 (E)가 아님·fetch 실패)
    """
    naver_q = period_to_naver_quarter(period)
    if not naver_q:
        return None
    data = fetch_naver_consensus(stock_code)
    if not data:
        return None
    q = data["quarters"].get(naver_q)
    if not q:
        return None
    # (E) 표시된 분기만 컨센서스로 의미 있음.
    # (P)/실제값으로 바뀐 후엔 컨센 정보 손실.
    return q


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # HD현대건설기계
    print("=== HD현대건설기계 (267270) ===")
    data = fetch_naver_consensus("267270")
    if data:
        for q, info in sorted(data["quarters"].items()):
            est = " (E)" if info.get("is_estimate") else ""
            rev = info.get("revenue", "-")
            op = info.get("op_income", "-")
            net = info.get("net_income", "-")
            print(f"  {q}{est:<5} | 매출 {rev:>8} | 영업익 {op:>6} | 순익 {net:>6}")
    else:
        print("  실패")

    # 1Q26 컨센
    print("\n=== 1Q26 컨센서스만 ===")
    cons = get_consensus_for_period("267270", "1Q26")
    print(cons)

    # LG이노텍 (011070)
    print("\n=== LG이노텍 (011070) — 1Q26 ===")
    cons2 = get_consensus_for_period("011070", "1Q26")
    print(cons2)
