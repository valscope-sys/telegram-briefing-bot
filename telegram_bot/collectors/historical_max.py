"""종목별 historical 최고가 fetch + 캐시 — "역사적 신고가" 판정용

배경:
- 키움 ka10016 (52주 신고가)는 dt=250 한계. awakeplus의 (역사적) = 상장 이래
- ka10081 (일봉차트) — 600건/페이지, 페이지네이션으로 5년+ historical 받음
- 자체 historical max 계산 → 현재가가 max보다 크면 "역사적 신고가" 판정

흐름:
1. 종목별 ka10081 fetch (1페이지 = 2.4년, 2페이지 = 5년 데이터)
2. high_pric max 추출
3. historical_max.json에 영구 캐시
4. 매일 종가로 점진적 갱신
"""
import datetime
import json
import os
import threading
import time
from typing import Optional


_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "history",
)
_CACHE_PATH = os.path.join(_HISTORY_DIR, "historical_max.json")
_lock = threading.Lock()
_cache_mem = None


def _load_cache() -> dict:
    global _cache_mem
    if _cache_mem is None:
        if os.path.exists(_CACHE_PATH):
            try:
                with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                    _cache_mem = json.load(f)
            except Exception:
                _cache_mem = {}
        else:
            _cache_mem = {}
    return _cache_mem


def _save_cache():
    if _cache_mem is None:
        return
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    tmp = _CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache_mem, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CACHE_PATH)


def _safe_int(s) -> Optional[int]:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("+", "").replace("-", "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def fetch_historical_max(stock_code: str, base_dt: str = None,
                         max_pages: int = 2) -> Optional[dict]:
    """ka10081로 종목별 historical 일봉 fetch → max(high_pric) 계산.

    Args:
        stock_code: 6자리 종목코드
        base_dt: 기준일 (YYYYMMDD), None이면 오늘
        max_pages: 페이지 수 (1=2.4년, 2=5년, 3=7년)

    Returns:
        {
          "max_high": int (역대 최고 고가),
          "max_high_dt": "YYYYMMDD",
          "first_dt": "YYYYMMDD" (가장 오래된 일자),
          "last_dt": "YYYYMMDD" (가장 최근 일자),
          "page_count": 실제 fetch한 페이지 수,
          "total_days": 누적 일봉 수,
        }
        실패 시 None.
    """
    from telegram_bot.kiwoom_client import kiwoom_post_with_meta

    if base_dt is None:
        base_dt = datetime.date.today().strftime("%Y%m%d")

    all_items = []
    cont_yn = None
    next_key = None

    for page in range(max_pages):
        try:
            data, headers = kiwoom_post_with_meta(
                "ka10081",
                {"stk_cd": stock_code, "base_dt": base_dt, "upd_stkpc_tp": "1"},
                url_path="/api/dostk/chart",
                cont_yn=cont_yn, next_key=next_key,
            )
            if data.get("return_code") != 0:
                break
            items = data.get("stk_dt_pole_chart_qry", []) or []
            all_items.extend(items)
            cont_yn = headers.get("cont-yn") or ""
            next_key = headers.get("next-key") or ""
            if cont_yn != "Y" or not next_key:
                break
            time.sleep(0.25)  # 키움 rate limit
        except Exception as e:
            print(f"[HIST_MAX] {stock_code} ka10081 page {page+1} 실패: {e}")
            break

    if not all_items:
        return None

    # max(cur_prc) 추출 — 종가 기준 (현재가도 종가라 일관됨).
    # high_pric 비교는 같은 날 고가가 종가보다 높아 거의 항상 false → 잘못된 비교.
    max_high = 0
    max_dt = ""
    for it in all_items:
        c = _safe_int(it.get("cur_prc"))
        if c is not None and c > max_high:
            max_high = c
            max_dt = it.get("dt", "")

    # 정렬해서 first/last
    dates = [it.get("dt", "") for it in all_items if it.get("dt")]
    dates.sort()
    first_dt = dates[0] if dates else ""
    last_dt = dates[-1] if dates else ""

    return {
        "max_high": max_high,
        "max_high_dt": max_dt,
        "first_dt": first_dt,
        "last_dt": last_dt,
        "page_count": page + 1,
        "total_days": len(all_items),
    }


def get_or_fetch_max(stock_code: str, name: str = "",
                     refresh: bool = False) -> Optional[int]:
    """종목별 max(high_pric) 반환. 캐시 우선, 없으면 fetch.

    매일 cur_prc > 캐시 max 시 _update_max 호출해서 갱신 (외부 호출).

    Args:
        stock_code: 6자리 종목코드
        refresh: True면 fetch 강제 (캐시 무시)

    Returns:
        max 가격 (int) 또는 None.
    """
    if not stock_code:
        return None

    cache = _load_cache()
    if not refresh and stock_code in cache:
        return cache[stock_code].get("max_high")

    # fetch
    result = fetch_historical_max(stock_code, max_pages=2)
    if not result:
        return None

    with _lock:
        cache[stock_code] = {
            "name": name,
            **result,
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        _save_cache()
    return result.get("max_high")


def update_max(stock_code: str, current_price: int) -> bool:
    """매일 종가 갱신 — current_price > 누적 max면 max 업데이트.

    Returns:
        True if max 갱신 (= 역사적 신고가 신규 발생)
    """
    if not stock_code or current_price is None or current_price <= 0:
        return False
    cache = _load_cache()
    entry = cache.get(stock_code)
    if not entry:
        return False  # 캐시 없으면 update 안 함 (먼저 fetch 필요)

    if current_price > entry.get("max_high", 0):
        with _lock:
            entry["max_high"] = current_price
            entry["max_high_dt"] = datetime.date.today().strftime("%Y%m%d")
            entry["last_dt"] = datetime.date.today().strftime("%Y%m%d")
            entry["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _save_cache()
        return True
    return False


def classify_high_kind(stock_code: str, current_price: int,
                       name: str = "", auto_fetch: bool = True) -> str:
    """현재가 vs historical max 비교 → 신고가 종류 판정.

    Returns:
        "역사적" (current >= 누적 max) — 상장 이래 신고가
        "52주"  (그 외 — 키움 ka10016이 이미 잡음)
    """
    if current_price is None or current_price <= 0:
        return "52주"

    cache = _load_cache()
    entry = cache.get(stock_code)

    if not entry:
        if not auto_fetch:
            return "52주"
        # 캐시 없음 → 첫 fetch
        try:
            fetch_max = get_or_fetch_max(stock_code, name=name)
            entry = cache.get(stock_code)
        except Exception as e:
            print(f"[HIST_MAX] {stock_code} fetch 실패: {e}")
            return "52주"

    if not entry:
        return "52주"

    cached_max = entry.get("max_high", 0)
    if current_price >= cached_max:
        # 갱신 시 max 업데이트
        update_max(stock_code, current_price)
        return "역사적"
    return "52주"


def batch_classify_high_kinds(stocks: list, max_fetch: int = 100) -> dict:
    """여러 종목 일괄 (52주)/(역사적) 판정.

    Args:
        stocks: [{"종목코드", "현재가", "종목명"}, ...]
        max_fetch: 1회 호출 시 최대 신규 fetch (rate limit)

    Returns:
        {code: "역사적" or "52주"}
    """
    out = {}
    fetch_count = 0
    cache = _load_cache()

    for s in stocks:
        code = s.get("종목코드", "")
        price = s.get("현재가", 0)
        name = s.get("종목명", "")
        if not code or not price:
            out[code] = "52주"
            continue

        if code in cache:
            # 캐시에 있으면 비교만
            cached_max = cache[code].get("max_high", 0)
            if price >= cached_max:
                update_max(code, price)
                out[code] = "역사적"
            else:
                out[code] = "52주"
        else:
            # 캐시 없음 — 신규 fetch (rate limit 안에서)
            if fetch_count >= max_fetch:
                out[code] = "52주"  # fetch 못 하면 안전하게 52주로
                continue
            try:
                result = fetch_historical_max(code, max_pages=2)
                fetch_count += 1
                time.sleep(0.25)  # rate limit
                if result:
                    with _lock:
                        cache[code] = {
                            "name": name,
                            **result,
                            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        }
                    cached_max = result.get("max_high", 0)
                    if price >= cached_max:
                        out[code] = "역사적"
                    else:
                        out[code] = "52주"
                else:
                    out[code] = "52주"
            except Exception as e:
                print(f"[HIST_MAX] {code} ({name}) fetch 실패: {e}")
                out[code] = "52주"

    if fetch_count > 0:
        _save_cache()
        print(f"[HIST_MAX] 신규 fetch {fetch_count}건 → 영구 캐시 저장")

    return out


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트: SK하이닉스
    print("=== SK하이닉스 (000660) historical max ===")
    result = fetch_historical_max("000660", max_pages=2)
    if result:
        print(f"  max_high: {result['max_high']:,}")
        print(f"  max_dt: {result['max_high_dt']}")
        print(f"  range: {result['first_dt']} ~ {result['last_dt']}")
        print(f"  total_days: {result['total_days']}")
