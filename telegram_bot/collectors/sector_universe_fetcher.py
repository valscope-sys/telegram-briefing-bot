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
"""
import datetime
import json
import os
import sys
import time
from typing import Optional


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
    """KRX 지수 구성종목 — pykrx 사용.

    Args:
        index_code: '1028' (반도체), '1031' (자동차) 등
        date_str: YYYYMMDD

    Returns:
        종목코드 list. 실패 시 [].
    """
    try:
        from pykrx import stock
        # pykrx — 지수 코드는 4자리 (KRX 산업분류) 또는 1xxx
        # get_index_portfolio_deposit_file은 ETF PDF 함수라 인덱스용 X
        # 인덱스 구성종목 → stock.get_index_portfolio_deposit_file(date, index_code)
        # 또는 get_market_ticker_list 같은 다른 함수
        tickers = stock.get_index_portfolio_deposit_file(date_str, index_code)
        if tickers:
            return list(tickers)
    except Exception as e:
        print(f"[FETCHER] KRX index {index_code} 실패: {str(e)[:100]}")
    return []


def fetch_etf_pdf(etf_code: str, date_str: str) -> list:
    """ETF PDF 구성종목.

    Args:
        etf_code: 6자리 ETF 종목코드 (예: '445290' = TIGER 로봇)
        date_str: YYYYMMDD

    Returns:
        종목코드 list.
    """
    try:
        from pykrx import stock
        df = stock.get_etf_portfolio_deposit_file(etf_code, date_str)
        if df is not None and len(df) > 0:
            return list(df.index.tolist())
    except Exception as e:
        print(f"[FETCHER] ETF {etf_code} 실패: {str(e)[:100]}")
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
        except Exception:
            pass

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
