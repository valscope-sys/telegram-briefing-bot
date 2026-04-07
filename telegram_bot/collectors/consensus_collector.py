"""FnGuide 컨센서스 데이터 크롤링"""
import requests
from bs4 import BeautifulSoup


def fetch_consensus(stock_code):
    """
    FnGuide에서 분기 컨센서스(영업이익) 조회
    - stock_code: 6자리 종목코드 (ex: "005930")
    - 반환: {"매출액컨센": ..., "영업이익컨센": ..., "분기": "2026/03(E)", ...}
    """
    gicode = f"A{stock_code}"
    url = "https://comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp"
    params = {
        "pGB": "1",
        "gicode": gicode,
        "cID": "AA",
        "MenuYn": "Y",
        "ReportGB": "",
        "NewMenuID": "108",
        "stkGb": "701",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "lxml")

        # 분기 컨센서스 테이블 찾기
        # "IFRS (연결) | 분기" 또는 "IFRS (연결) | 연간" 포함 테이블
        result = {}

        for table in soup.select("table"):
            header_row = table.select_one("tr")
            if not header_row:
                continue
            header_text = header_row.get_text(strip=True)

            # 분기 테이블 찾기
            if "분기" not in header_text:
                continue

            rows = table.select("tr")
            if len(rows) < 5:
                continue

            # 헤더에서 분기 컬럼 추출
            headers_cells = [c.get_text(strip=True) for c in rows[0].select("td,th")]

            # (E) 가 포함된 첫 번째 컬럼이 다음 분기 추정치
            e_col_idx = None
            e_quarter = ""
            for i, h in enumerate(headers_cells):
                if "(E)" in h:
                    e_col_idx = i
                    # "2026/03(E)" 같은 형태 추출
                    e_quarter = h.replace("(E) : Estimate", "").strip()
                    if "/" in e_quarter:
                        e_quarter = e_quarter.split("\t")[0].strip()
                    break

            if e_col_idx is None:
                continue

            # 매출액, 영업이익 행 찾기
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.select("td,th")]
                if len(cells) <= e_col_idx:
                    continue

                row_label = cells[0] if cells else ""

                if "매출액" in row_label and "대비" not in row_label and "컨센" not in row_label:
                    try:
                        val = cells[e_col_idx].replace(",", "")
                        result["매출액컨센"] = int(float(val))
                    except (ValueError, IndexError):
                        pass

                if "영업이익" in row_label and "대비" not in row_label and "컨센" not in row_label:
                    try:
                        val = cells[e_col_idx].replace(",", "")
                        result["영업이익컨센"] = int(float(val))
                    except (ValueError, IndexError):
                        pass

            if result:
                result["분기"] = e_quarter
                return result

        return None
    except Exception:
        return None


def fetch_earnings_consensus(stock_codes):
    """
    여러 종목의 컨센서스를 한번에 조회
    - stock_codes: [("삼성전자", "005930"), ("LG전자", "066570"), ...]
    - 반환: {"삼성전자": {"영업이익컨센": 401923, "분기": "2026/03(E)"}, ...}
    """
    import time
    results = {}
    for name, code in stock_codes:
        data = fetch_consensus(code)
        if data:
            results[name] = data
        time.sleep(0.3)
    return results
