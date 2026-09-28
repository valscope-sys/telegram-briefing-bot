"""밸류에이션 데이터 수집 (선행 PER, PBR 등)

2026-09-28: 구버전 comp.fnguide.com/SVO2 폐쇄 → 신버전 wcomp.fnguide.com 으로 이전.
  GET https://wcomp.fnguide.com/CompanyInfo/Consensus?cmp_cd=005930
  페이지 상단 #corp_group2 블록 (서버 렌더링 HTML, 구버전과 같은 id):
    <ul><li>…<button id="h_per">PER</button></li><li>43.50</li></ul>
    h_per = PER / h_12m = PER(Fwd.12M) / h_u_per = 업종 PER / h_pbr = PBR / h_rate = 배당수익률
  주의: 신버전은 gicode 파라미터를 무시하고 기본 종목(삼성전자)을 렌더링하므로 cmp_cd 사용 +
  <title>의 종목코드가 요청 코드와 일치하는지 검증.
"""
import requests
from bs4 import BeautifulSoup
import re

_VAL_URL = "https://wcomp.fnguide.com/CompanyInfo/Consensus"
_VAL_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
}
# #corp_group2 버튼 id → 반환 키
_VAL_IDS = {"h_per": "PER", "h_12m": "12M_PER", "h_u_per": "업종PER", "h_pbr": "PBR"}


def _label_to_key(label):
    """버튼 id가 바뀌었을 때 라벨 텍스트로 대체 매칭."""
    label = (label or "").replace("\xa0", " ").strip()
    if "12M" in label:
        return "12M_PER"
    if "업종" in label and "PER" in label:
        return "업종PER"
    if label.startswith("PBR"):
        return "PBR"
    if label.startswith("PER"):
        return "PER"
    return None


def _to_float(text):
    s = (text or "").replace(",", "").replace("배", "").strip()
    try:
        return float(s)
    except ValueError:
        return None  # "-" (적자·추정치 없음) 등


def fetch_stock_valuation(stock_code):
    """
    FnGuide에서 개별 종목 밸류에이션 조회
    - 반환: {"PER": 29.42, "12M_PER": 6.53, "업종PER": 24.01, "PBR": 3.02}
      (값이 "-"인 항목은 키 생략, 전부 없으면 None)
    """
    try:
        res = requests.get(_VAL_URL, params={"cmp_cd": stock_code}, headers=_VAL_HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[VALUATION] ERROR: {stock_code} FnGuide HTTP {res.status_code}")
            return None
        soup = BeautifulSoup(res.text, "lxml")

        # 요청 종목 페이지가 맞는지 확인 (파라미터 무시 시 삼성전자 기본 페이지가 옴)
        title = soup.title.get_text(strip=True) if soup.title else ""
        m = re.search(r"\((\d{6})\)", title)
        if not m or m.group(1) != stock_code:
            print(f"[VALUATION] ERROR: {stock_code} FnGuide 페이지 종목 불일치/없음 (title={title[:60]!r})")
            return None

        box = soup.select_one("#corp_group2")
        if not box:
            print(f"[VALUATION] ERROR: {stock_code} FnGuide #corp_group2 블록 없음 — 페이지 구조 변경 의심")
            return None

        result = {}
        for ul in box.find_all("ul"):
            btn = ul.find("button")
            if not btn:
                continue
            key = _VAL_IDS.get(btn.get("id", "")) or _label_to_key(btn.get_text(" ", strip=True))
            if not key or key in result:
                continue
            lis = ul.find_all("li", recursive=False)
            if len(lis) < 2:
                continue
            val = _to_float(lis[-1].get_text(strip=True))
            if val is not None:
                result[key] = val

        if not result:
            print(f"[VALUATION] ERROR: {stock_code} FnGuide PER/PBR 값 추출 실패 — 페이지 구조 변경 의심")
            return None
        return result
    except Exception as e:
        print(f"[VALUATION] ERROR: {stock_code} FnGuide 밸류에이션 조회 실패: {type(e).__name__}: {e}")
        return None


def fetch_market_valuation():
    """
    주요 종목 밸류에이션 + 코스피 수준 판단용 데이터
    """
    import time
    results = {}
    targets = [
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
    ]
    for name, code in targets:
        val = fetch_stock_valuation(code)
        if val:
            results[name] = val
        time.sleep(0.3)
    return results


def format_valuation_for_prompt(val_data):
    """밸류에이션 데이터를 프롬프트용 텍스트로 변환"""
    if not val_data:
        return ""

    lines = ["=== 밸류에이션 ==="]
    for name, data in val_data.items():
        per = data.get("PER", 0)
        per12m = data.get("12M_PER", 0)
        sector_per = data.get("업종PER", 0)
        pbr = data.get("PBR", 0)
        lines.append(f"{name}: PER {per}배 / 12M선행PER {per12m}배 / 업종PER {sector_per}배 / PBR {pbr}배")

    lines.append("\n참고: 코스피 역사상 선행PER 8배 이하는 08년 금융위기(6.3배), 11년 유럽재정위기(7.6배), 18년 미중무역분쟁(7.7배) 단 3차례. 장기평균 약 10배.")

    return "\n".join(lines)
