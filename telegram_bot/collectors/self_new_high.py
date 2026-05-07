"""자체 252일 신고가 판정 — ka10001 활용

배경:
- 키움 ka10016 (신고가 목록)이 awakeplus 잡는 종목 절반 누락
- 페이지네이션·파라미터 변경해도 한계
- 그러나 ka10001 (주식기본정보) 응답에 250hgst_pric_dt(250일 최고가 일자)
  + 250hgst_pric_pre_rt(대비율) 있음
- 종목별 호출해서 250hgst_pric_dt = 오늘 → 252일 신고가 판정 가능

흐름:
1. 후보 종목 리스트 (매핑된 종목 + 거래량 상위 + 직전 신고가 종목)
2. 각 종목 ka10001 fetch (rate limit 0.25s)
3. 250hgst_pric_dt = 오늘 → 신고가 판정
4. 결과 캐시

매일 새벽 cron으로 전체 KRX 처리 → 신고가 카드 발송 시 캐시 활용.
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
_CACHE_PATH = os.path.join(_HISTORY_DIR, "self_new_high_cache.json")
_lock = threading.Lock()


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


def _safe_float(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("+", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_stock_high_info(stock_code: str) -> Optional[dict]:
    """ka10001 호출 → 신고가 판정 정보 추출.

    Returns:
        {
          "code", "name",
          "cur_prc": 종가,
          "flu_rt": 등락률,
          "trde_qty": 거래량,
          "high_pric": 당일 고가,
          "low_pric": 당일 저가,
          "h250_dt": 250일 신고가 일자 (YYYYMMDD),
          "h250_pre_rt": 250일 신고가 대비율 (음수=못미침, 0=신고가),
          "oyr_hgst": 연중최고가,
          "is_new_high_252d": 250hgst_pric_dt가 최근 거래일이면 True,
        }
        실패 시 None.
    """
    from telegram_bot.kiwoom_client import kiwoom_post

    try:
        d = kiwoom_post("ka10001", {"stk_cd": stock_code})
        if d.get("return_code") != 0:
            return None

        cur = _safe_int(d.get("cur_prc"))
        flu = _safe_float(d.get("flu_rt"))
        h250_dt = (d.get("250hgst_pric_dt") or "").strip()
        h250_rt = _safe_float(d.get("250hgst_pric_pre_rt"))

        return {
            "code": stock_code,
            "name": (d.get("stk_nm") or "").strip(),
            "cur_prc": cur,
            "flu_rt": flu,
            "trde_qty": _safe_int(d.get("trde_qty")),
            "high_pric": _safe_int(d.get("high_pric")),
            "low_pric": _safe_int(d.get("low_pric")),
            "h250_dt": h250_dt,
            "h250_pre_rt": h250_rt,
            "oyr_hgst": _safe_int(d.get("oyr_hgst")),
        }
    except Exception as e:
        print(f"[SELF_HIGH] {stock_code} ka10001 실패: {str(e)[:80]}")
        return None


def is_new_high_today(info: dict, today_str: str = None,
                      tolerance_pct: float = 0.0) -> bool:
    """ka10001 응답에서 오늘 252일 신고가 여부 판정.

    Args:
        info: fetch_stock_high_info 결과
        today_str: 오늘 YYYYMMDD. None이면 자동.
        tolerance_pct: 250일 신고가 대비율 허용 한계
            (예: -0.5 → 250hgst -0.5% 이내도 신고가로 인정. awakeplus 호환용)

    Returns:
        True if 252일 신고가
    """
    if not info:
        return False
    if today_str is None:
        today_str = datetime.date.today().strftime("%Y%m%d")

    h250_dt = info.get("h250_dt", "")

    # 1차: 250hgst_pric_dt = 오늘 → 정확한 252일 신고가
    if h250_dt == today_str:
        return True

    # 2차: 250hgst_pric_pre_rt가 0% 또는 양수 (드물지만)
    rt = info.get("h250_pre_rt")
    if rt is not None and rt >= tolerance_pct:
        return True

    return False


def detect_new_highs(candidate_codes: list,
                     today_str: str = None,
                     tolerance_pct: float = 0.0,
                     max_fetch: int = 1000,
                     verbose: bool = True) -> list:
    """후보 종목 리스트 → 오늘 252일 신고가 종목 추출.

    Args:
        candidate_codes: [{"종목코드", "종목명"}, ...] 또는 ["005930", ...]
        today_str: YYYYMMDD. None이면 자동.
        tolerance_pct: 250일 대비 허용 (음수 — 예: -1.0 = -1% 까지 신고가)
        max_fetch: 1회 최대 호출 (rate limit)

    Returns:
        [{
          "종목코드", "종목명", "현재가", "등락률",
          "h250_dt", "h250_pre_rt", "신고가종류"
        }, ...]
    """
    if today_str is None:
        today_str = datetime.date.today().strftime("%Y%m%d")

    # 입력 정규화
    items = []
    for c in candidate_codes:
        if isinstance(c, dict):
            items.append({
                "code": c.get("종목코드") or c.get("code", ""),
                "name": c.get("종목명") or c.get("name", ""),
            })
        else:
            items.append({"code": c, "name": ""})
    items = [i for i in items if i["code"]]

    new_highs = []
    fetched = 0
    failed = 0

    for i in items[:max_fetch]:
        try:
            info = fetch_stock_high_info(i["code"])
            fetched += 1
            time.sleep(0.22)  # 키움 rate limit (초당 5건)
            if not info:
                failed += 1
                continue
            if is_new_high_today(info, today_str=today_str, tolerance_pct=tolerance_pct):
                # 신고가 판정 — 통합 dict 반환
                new_highs.append({
                    "종목코드": i["code"],
                    "종목명": info.get("name") or i["name"],
                    "현재가": info.get("cur_prc") or 0,
                    "등락률": info.get("flu_rt") or 0,
                    "거래량": info.get("trde_qty") or 0,
                    "h250_dt": info.get("h250_dt", ""),
                    "h250_pre_rt": info.get("h250_pre_rt"),
                    "신고가종류": "역사적" if (info.get("h250_pre_rt") or -99) >= 0 else "52주",
                })
        except Exception as e:
            failed += 1
            if verbose and failed <= 5:
                print(f"[SELF_HIGH] {i['code']} 실패: {str(e)[:80]}")

    if verbose:
        print(f"[SELF_HIGH] 검사 {fetched}건, 실패 {failed}, 신고가 발견 {len(new_highs)}건")

    return new_highs


def load_krx_listing() -> list:
    """KRX 전 종목 리스트 (krx_listing.json)에서 종목코드/명 추출.

    지원 형식:
    - {"_meta":{...}, "stocks": [{"code", "name", "market"}, ...]}
    - {"005930": "삼성전자", ...}
    - [{"code", "name"}, ...]
    """
    path = os.path.join(_HISTORY_DIR, "krx_listing.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # 1) {"stocks": [...]} 형식
            stocks = data.get("stocks")
            if isinstance(stocks, list):
                return [
                    {"code": it.get("code", ""), "name": it.get("name", "")}
                    for it in stocks if isinstance(it, dict) and it.get("code")
                ]
            # 2) {"005930": "삼성전자"} 또는 {"005930": {"name": ...}}
            out = []
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, str):
                    out.append({"code": k, "name": v})
                elif isinstance(v, dict):
                    out.append({"code": k, "name": v.get("name", "")})
            return out
        elif isinstance(data, list):
            return [
                {"code": it.get("code", ""), "name": it.get("name", "")}
                for it in data if isinstance(it, dict) and it.get("code")
            ]
    except Exception as e:
        print(f"[SELF_HIGH] krx_listing 로드 실패: {e}")
    return []


def merge_with_kiwoom_raw(kiwoom_results: list, self_results: list) -> list:
    """ka10016 raw 결과 + 자체 판정 결과 dedup 통합.

    종목코드 기준 dedup. 키움 raw 우선 (cur_prc·등락률 등 풍부한 정보).
    자체 판정에서만 잡힌 종목은 추가.
    """
    seen = set()
    merged = []

    # 1차: 키움 raw (이미 분류된 정보 풍부)
    for it in kiwoom_results:
        code = it.get("종목코드", "")
        if code and code not in seen:
            merged.append(it)
            seen.add(code)

    # 2차: 자체 판정 (raw에 없는 신고가 종목)
    for it in self_results:
        code = it.get("종목코드", "")
        if code and code not in seen:
            merged.append(it)
            seen.add(code)

    return merged


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # awakeplus 종목들 검사
    candidates = [
        {"종목코드": "094820", "종목명": "일진파워"},
        {"종목코드": "298040", "종목명": "효성중공업"},
        {"종목코드": "010120", "종목명": "LS ELECTRIC"},
        {"종목코드": "042700", "종목명": "한미반도체"},
        {"종목코드": "000660", "종목명": "SK하이닉스"},
        {"종목코드": "005930", "종목명": "삼성전자"},
    ]
    today = datetime.date.today().strftime("%Y%m%d")
    print(f"오늘 ({today}) 자체 252일 신고가 판정:")
    result = detect_new_highs(candidates, today_str=today)
    for it in result:
        print(f"  ✓ {it['종목코드']} {it['종목명']:15s} {it['신고가종류']:5s} {it['등락률']:+6.2f}%")
