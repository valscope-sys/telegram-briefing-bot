"""FnGuide 컨센서스 데이터 조회 (wcomp.fnguide.com 신버전)

2026-09-28: 구버전 comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp 폐쇄
("페이지가 없습니다 / 신버전 바로가기" HTML만 반환) → 신버전 JSON 엔드포인트로 이전.

  GET https://wcomp.fnguide.com/CompanyInfo/getCnsPerforTrend
      ?cmp_cd=005930&consol_typ=C&freq_typ=Q&data_typ=2
  → {"dataset": {"header": [{"YYMM": "2026/09", "EP_CHK": "E", "CD": "VAL4"}, ...],
                 "data":   [{"NAME": "매출액", "LVL": 1, "VAL1": "938373.71", ...}, ...]}}

  - 단위: 억원 (구버전 테이블과 동일)
  - EP_CHK: "E" = 컨센서스 추정치, "P" = 잠정실적, " " = 확정실적
  - consol_typ: "C" 연결 / "P" 별도 (연결 추정치가 없으면 별도로 재시도)
  - 신버전은 종목 지정 파라미터가 gicode=A005930 → cmp_cd=005930 로 바뀜
"""
import requests

_CNS_URL = "https://wcomp.fnguide.com/CompanyInfo/getCnsPerforTrend"
_CNS_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://wcomp.fnguide.com/CompanyInfo/Consensus",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _to_num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _get_perfor_trend(stock_code, consol_typ):
    """getCnsPerforTrend(분기, 영업이익 기준) → (header, data). 응답 이상 시 RuntimeError."""
    params = {"cmp_cd": stock_code, "consol_typ": consol_typ, "freq_typ": "Q", "data_typ": "2"}
    res = requests.get(_CNS_URL, params=params, headers=_CNS_HEADERS, timeout=10)
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    text = res.text.lstrip("﻿").strip()
    if text.startswith("<"):
        raise RuntimeError("JSON 대신 HTML 응답 (종목코드 오류 또는 엔드포인트 폐쇄/변경 의심)")
    ds = res.json().get("dataset")
    if not isinstance(ds, dict) or not isinstance(ds.get("header"), list) or not isinstance(ds.get("data"), list):
        raise RuntimeError(f"예상과 다른 응답 구조: {str(ds)[:120]}")
    return ds["header"], ds["data"]


def fetch_consensus(stock_code):
    """
    FnGuide에서 분기 컨센서스(영업이익) 조회
    - stock_code: 6자리 종목코드 (ex: "005930")
    - 반환: {"매출액컨센": ..., "영업이익컨센": ..., "분기": "2026/03(E)", ...}  (단위: 억원)
      컨센서스(E) 없으면 None
    """
    try:
        saw_op_row = False
        for consol_typ in ("C", "P"):
            header, data = _get_perfor_trend(stock_code, consol_typ)
            names = {(row.get("NAME") or "").strip() for row in data if row.get("LVL") == 1}
            saw_op_row = saw_op_row or "영업이익" in names

            # (E) 첫 번째 컬럼 = 다음 분기 추정치 (구버전 로직과 동일)
            e_col = next((h for h in header if (h.get("EP_CHK") or "").strip() == "E"), None)
            if not e_col or not e_col.get("CD"):
                continue
            col = e_col["CD"]

            result = {}
            for row in data:
                if row.get("LVL") != 1:  # 전년동기대비·컨센서스대비 같은 하위 행 제외
                    continue
                name = (row.get("NAME") or "").strip()
                val = _to_num(row.get(col))
                if val is None:
                    continue
                if name == "매출액":
                    result["매출액컨센"] = int(val)
                elif name == "영업이익":
                    result["영업이익컨센"] = int(val)

            if result:
                result["분기"] = f"{(e_col.get('YYMM') or '').strip()}(E)"
                return result

        if not saw_op_row:
            print(f"[CONSENSUS] ERROR: {stock_code} FnGuide 응답에 '영업이익' 행 없음 — 응답 구조 변경 의심")
        else:
            print(f"[CONSENSUS] {stock_code} 분기 컨센서스(E) 없음 (커버리지 없음)")
        return None
    except Exception as e:
        print(f"[CONSENSUS] ERROR: {stock_code} FnGuide 컨센서스 조회 실패: {type(e).__name__}: {e}")
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
