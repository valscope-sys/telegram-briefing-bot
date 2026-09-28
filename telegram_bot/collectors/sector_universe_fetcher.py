"""KRX 지수/ETF 구성종목 일괄 fetch — 매일 새벽 cron 1회.

명세서 (2026-05-12 코드방):
- 매핑 사전 폐기
- KRX 지수 + ETF 구성종목 = 단일 데이터 소스
- sector_universe_YYYYMMDD.json 생성
- 신고가 종목을 universe에서 역색인 매칭

데이터 소스:
- KRX 지수 구성종목: data.krx.co.kr/comm/bldAttendant/getJsonData.cmd
  · bld: dbms/MDC/STAT/standard/MDCSTAT00601
- ETF PDF (Portfolio Deposit File):
  · bld: dbms/MDC/STAT/standard/MDCSTAT05001
- 실제 fetch: pykrx 라이브러리 (Linux 환경에서 정상 동작)

Windows 주의:
- pykrx Windows에서 한글 컬럼 인코딩 이슈 발생 가능
- Linux 서버 배포 후 실제 동작 검증 필요

실패 처리:
- 섹터별 fetch 실패 시 빈 list로 두고 진행
- 전체 실패 시 전날 파일 fallback

2026-09-28 복구 (2026-05 이후 26개 섹터 전부 0건이었음):
- data.krx.co.kr 가 로그인 필수로 바뀌어 비로그인 요청은 HTTP 400 "LOGOUT" → pykrx 전면 실패.
- 1차 소스를 KIS ETF 구성종목 API(FHKST121600C0)로 교체, pykrx 는 2차 fallback 으로만 유지.
  · ETF 소스: 해당 ETF 구성종목 그대로
  · KRX_index 소스: 그 지수를 기초지수로 하는 추종 ETF 의 구성종목으로 대체 (_KRX_INDEX_TRACKER_ETF)
- 한계: KIS 는 비중 상위 30종목까지만 반환 (예: 코리아밸류업 101종목 중 30) → 소형 구성종목 누락.
  전 종목이 필요하면 KRX 정보데이터시스템 로그인 계정 또는 KRX Open API 키가 필요.
- sector_config.json 의 ETF 코드가 섹터와 다른 상품이면(예: 우주항공=HANARO K-뷰티) 엉뚱한 분류가
  발행되므로, ETF 소스는 KIS 상품명이 섹터 키워드와 맞는지 확인 후에만 사용 (_verify_etf_for_sector).
"""
import datetime
import json
import os
import re
import sys
import time
from typing import Optional


# KRX 지수 코드(sector_config.json "KRX_index") → 그 지수를 기초지수로 추종하는 ETF.
# 기초지수는 네이버 증권 ETF 정보(etfBaseIdx)로 2026-09-28 확인.
_KRX_INDEX_TRACKER_ETF = {
    "1028": ("091160", "KODEX 반도체", "KRX 반도체"),
    "1031": ("091180", "KODEX 자동차", "KRX 자동차"),
    "1029": ("266420", "KODEX 헬스케어", "KRX 헬스케어"),
    "1024": ("091170", "KODEX 은행", "KRX 은행"),
    "1032": ("140700", "KODEX 보험", "KRX 보험"),
    "1027": ("102970", "KODEX 증권", "KRX 증권"),
    "1026": ("117700", "KODEX 건설", "KRX 건설"),
    "1025": ("117460", "KODEX 에너지화학", "KRX 에너지화학"),
    "1023": ("117680", "KODEX 철강", "KRX 철강"),
    "1034": ("102960", "KODEX 기계장비", "KRX 기계장비"),
    "1035": ("140710", "KODEX 운송", "KRX 운송"),
    "1033": ("266370", "KODEX IT", "KRX 정보기술"),
    "1021": ("266410", "KODEX 필수소비재", "KRX 필수소비재"),
    "1022": ("266390", "KODEX 경기소비재", "KRX 경기소비재"),
    "1980": ("495850", "KODEX 코리아밸류업", "코리아 밸류업 지수"),
    # "1030" KRX 미디어통신: 추종 ETF 없음 (KODEX 266360 은 'KRX K콘텐츠' 추종으로 변경됨) → 미매핑
}

# ETF 소스 섹터명 → ETF 상품명에 있어야 할 키워드 (없으면 섹터명 자체로 검사)
_SECTOR_NAME_KEYWORDS = {
    "원전": ["원전", "원자력"],
    "우주항공": ["우주", "항공"],
    "K뷰티": ["뷰티", "화장품"],
    "AI반도체": ["반도체"],
    "2차전지": ["2차전지", "이차전지", "배터리"],
    "방산": ["방산", "방위"],
}

_KR_STOCK_CODE_RE = re.compile(r"^[0-9][0-9A-Z]{5}$")  # 005930, 0080G0 (신규 영숫자 코드)


def _fetch_etf_components_kis(etf_code: str) -> list:
    """KIS ETF 구성종목시세(FHKST121600C0) → 국내 주식 종목코드 list (비중 상위 최대 30)."""
    from telegram_bot.kis_client import kis_get
    data = kis_get(
        "/uapi/etfetn/v1/quotations/inquire-component-stock-price",
        "FHKST121600C0",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": etf_code, "FID_COND_SCR_DIV_CODE": "11216"},
    )
    rows = data.get("output2") or []
    codes = []
    for r in rows:
        c = str(r.get("stck_shrn_iscd", "")).strip()
        if _KR_STOCK_CODE_RE.match(c) and c not in codes:
            codes.append(c)
    # etf_cnfg_issu_cnt 는 현금(원화예금) 1행을 포함하므로 +1 차이는 정상
    total = str((data.get("output1") or {}).get("etf_cnfg_issu_cnt", "")).strip()
    if total.isdigit() and int(total) > len(rows) + 1:
        print(f"[FETCHER] {etf_code}: KIS 구성종목 {len(rows)}/{total}개만 제공 "
              f"(비중 상위 30 제한 또는 해외자산 — 나머지 미포함)")
    return codes


def _fetch_etf_name_kis(etf_code: str) -> str:
    """KIS 상품기본조회(CTPF1002R) → ETF 약식명 (예: 'PLUS K방산')."""
    from telegram_bot.kis_client import kis_get
    data = kis_get(
        "/uapi/domestic-stock/v1/quotations/search-stock-info",
        "CTPF1002R",
        {"PRDT_TYPE_CD": "300", "PDNO": etf_code},
    )
    out = data.get("output") or {}
    return str(out.get("prdt_abrv_name") or out.get("prdt_name") or "").strip()


def _verify_etf_for_sector(sector: str, etf_code: str) -> tuple:
    """ETF 상품명이 섹터 키워드를 포함하는지 확인. (ok, etf_name).

    상품명을 확인할 수 없으면 False — 잘못된 코드로 엉뚱한 종목이 섹터에 묶여 발행되는 것보다
    그 섹터를 비워 두는 편이 안전(해당 종목은 '기타'로 표시).
    """
    try:
        etf_name = _fetch_etf_name_kis(etf_code)
    except Exception as e:
        print(f"[FETCHER] ERROR: {sector} ETF {etf_code} 상품명 조회 실패 — 검증 불가로 제외: {e}")
        return False, ""
    if not etf_name:
        print(f"[FETCHER] ERROR: {sector} ETF {etf_code} 상품명 없음 (상장폐지/오기 의심) — 제외")
        return False, ""
    normalized = etf_name.replace(" ", "").upper()
    keywords = _SECTOR_NAME_KEYWORDS.get(sector, [sector])
    if any(k.replace(" ", "").upper() in normalized for k in keywords):
        return True, etf_name
    print(f"[FETCHER] ERROR: sector_config '{sector}' 의 ETF {etf_code} = '{etf_name}' — 섹터와 불일치, "
          f"제외 (sector_config.json 코드 수정 필요)")
    return False, etf_name


_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "history",
)
_CONFIG_PATH = os.path.join(_HISTORY_DIR, "sector_config.json")
_LATEST_LINK = os.path.join(_HISTORY_DIR, "sector_universe_latest.json")


def _today_str() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def _universe_path(date_str: str) -> str:
    return os.path.join(_HISTORY_DIR, f"sector_universe_{date_str}.json")


def _load_config() -> list:
    if not os.path.exists(_CONFIG_PATH):
        return []
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sectors", [])


def fetch_krx_index_constituents(index_code: str, date_str: str) -> list:
    """KRX 지수 구성종목.

    1차: 추종 ETF 의 KIS 구성종목 (_KRX_INDEX_TRACKER_ETF, 비중 상위 최대 30)
    2차: pykrx (data.krx.co.kr — 2026 로그인 필수화 이후 비로그인 실패)

    Args:
        index_code: '1028' (반도체), '1031' (자동차) 등
        date_str: YYYYMMDD (pykrx fallback 용)

    Returns:
        종목코드 list. 실패 시 [].
    """
    tracker = _KRX_INDEX_TRACKER_ETF.get(index_code)
    if tracker:
        etf_code, etf_name, base_idx = tracker
        try:
            codes = _fetch_etf_components_kis(etf_code)
            if codes:
                return codes
            print(f"[FETCHER] ERROR: KRX index {index_code} — 추종 ETF {etf_name}({etf_code}) KIS 구성종목 0건")
        except Exception as e:
            print(f"[FETCHER] ERROR: KRX index {index_code} — 추종 ETF {etf_name}({etf_code}) KIS 조회 실패: {str(e)[:100]}")
    else:
        print(f"[FETCHER] KRX index {index_code}: 추종 ETF 매핑 없음 → pykrx 시도")
    try:
        from pykrx import stock
        # pykrx — 지수 코드는 4자리 (KRX 산업분류) 또는 1xxx
        tickers = stock.get_index_portfolio_deposit_file(date_str, index_code)
        if tickers:
            return list(tickers)
        print(f"[FETCHER] ERROR: KRX index {index_code} pykrx 0건 (data.krx.co.kr 로그인 필수 — 비로그인 차단)")
    except Exception as e:
        print(f"[FETCHER] ERROR: KRX index {index_code} pykrx 실패: {str(e)[:100]}")
    return []


def fetch_etf_pdf(etf_code: str, date_str: str) -> list:
    """ETF PDF 구성종목.

    1차: KIS ETF 구성종목 (비중 상위 최대 30) / 2차: pykrx

    Args:
        etf_code: 6자리 ETF 종목코드 (예: '445290' = KODEX 로봇액티브)
        date_str: YYYYMMDD (pykrx fallback 용)

    Returns:
        종목코드 list.
    """
    try:
        codes = _fetch_etf_components_kis(etf_code)
        if codes:
            return codes
        print(f"[FETCHER] ERROR: ETF {etf_code} KIS 구성종목 0건")
    except Exception as e:
        print(f"[FETCHER] ERROR: ETF {etf_code} KIS 조회 실패: {str(e)[:100]}")
    try:
        from pykrx import stock
        df = stock.get_etf_portfolio_deposit_file(etf_code, date_str)
        if df is not None and len(df) > 0:
            return list(df.index.tolist())
        print(f"[FETCHER] ERROR: ETF {etf_code} pykrx 0건 (data.krx.co.kr 로그인 필수 — 비로그인 차단)")
    except Exception as e:
        print(f"[FETCHER] ERROR: ETF {etf_code} pykrx 실패: {str(e)[:100]}")
    return []


def fetch_sector_universe(date_str: Optional[str] = None) -> dict:
    """sector_config.json 읽고 모든 섹터 fetch.

    Returns:
        {
          "generated_at": ISO timestamp,
          "trd_dd": YYYYMMDD,
          "sectors": {
            "반도체": ["005930", "000660", ...],
            "자동차": ["005380", ...],
            ...
          },
          "failures": [섹터명] (fetch 실패한 것)
        }
    """
    if date_str is None:
        # 휴장일이면 직전 영업일
        from telegram_bot.market_calendar import is_market_day, prev_business_day
        today = datetime.date.today()
        if not is_market_day(today):
            today = prev_business_day(today)
        date_str = today.strftime("%Y%m%d")

    config = _load_config()
    print(f"[FETCHER] {date_str} 섹터 {len(config)}개 fetch 시작")
    started = time.time()

    sectors_data = {}
    failures = []

    for sec in config:
        name = sec.get("name")
        source = sec.get("source")
        code = sec.get("code")
        if not name or not source or not code:
            continue

        # ETF 코드가 섹터와 다른 상품이면 제외 (잘못된 분류 발행 방지)
        if source == "ETF":
            ok, etf_name = _verify_etf_for_sector(name, code)
            if not ok:
                sectors_data[name] = []
                failures.append(name)
                print(f"  [{name:8s}] {source:10s} {code:6s} → SKIP (ETF 검증 실패: {etf_name or '이름 없음'})")
                continue

        attempts = 0
        result = []
        while attempts < 2:
            attempts += 1
            try:
                if source == "KRX_index":
                    result = fetch_krx_index_constituents(code, date_str)
                elif source == "ETF":
                    result = fetch_etf_pdf(code, date_str)
                else:
                    result = []
                if result:
                    break
            except Exception as e:
                print(f"[FETCHER] {name} attempt {attempts} 실패: {e}")
            if attempts < 2:
                time.sleep(30)

        sectors_data[name] = result
        status = f"{len(result)}건" if result else "FAIL"
        print(f"  [{name:8s}] {source:10s} {code:6s} → {status}")
        if not result:
            failures.append(name)

    elapsed = time.time() - started
    print(f"[FETCHER] 완료 — {len(sectors_data)} 섹터, 실패 {len(failures)}, 소요 {elapsed:.0f}초")

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "trd_dd": date_str,
        "sectors": sectors_data,
        "failures": failures,
    }


def save_universe(universe: dict) -> str:
    """sector_universe_YYYYMMDD.json + 최신 symlink 저장.

    가드: 전 섹터 fetch 실패 시 latest_link 덮어쓰기 스킵 — 이전 정상 데이터 보존.
    pykrx 일시 장애 / KRX API 다운 시 분류 시스템 전체가 무너지는 사고 방지.
    """
    date_str = universe.get("trd_dd", _today_str())
    path = _universe_path(date_str)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

    # 데이터 유효성 — 한 섹터라도 종목이 있어야 latest 갱신
    sectors = universe.get("sectors", {})
    has_any_data = any(len(codes) > 0 for codes in sectors.values())
    if not has_any_data:
        print(f"[FETCHER] ⚠️ 전 {len(sectors)} 섹터 fetch 실패 — latest_link 갱신 스킵 (이전 정상 데이터 보존)")
        return path

    # latest 복사 (symlink 대신 일반 복사 — Windows/Linux 호환)
    try:
        with open(_LATEST_LINK, "w", encoding="utf-8") as f:
            json.dump(universe, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[FETCHER] latest 갱신 실패: {e}")

    return path


def load_universe(date_str: Optional[str] = None) -> Optional[dict]:
    """오늘(또는 지정 일자) universe 로드. 없으면 가장 최근 파일 fallback."""
    if date_str:
        path = _universe_path(date_str)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    # latest 우선
    if os.path.exists(_LATEST_LINK):
        try:
            with open(_LATEST_LINK, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[FETCHER] ERROR: {_LATEST_LINK} 로드 실패 — 날짜별 파일로 대체: {e}")

    # 가장 최근 sector_universe_*.json 찾기
    candidates = []
    for fn in os.listdir(_HISTORY_DIR):
        if fn.startswith("sector_universe_") and fn.endswith(".json"):
            candidates.append(fn)
    candidates.sort(reverse=True)
    for fn in candidates:
        path = os.path.join(_HISTORY_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


def run_daily_fetch() -> dict:
    """매일 새벽 cron 진입점."""
    universe = fetch_sector_universe()
    path = save_universe(universe)
    return {
        "ok": True,
        "trd_dd": universe.get("trd_dd"),
        "path": path,
        "sector_count": len(universe.get("sectors", {})),
        "failure_count": len(universe.get("failures", [])),
    }


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    result = run_daily_fetch()
    print(f"\n결과: {result}")
