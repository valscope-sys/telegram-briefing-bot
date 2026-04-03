"""글로벌 시장 데이터 수집 (해외지수, 환율, 금리, 원자재) - KIS API 사용"""
import datetime
import time
from telegram_bot.kis_client import kis_get
from telegram_bot.config import GLOBAL_INDICES, FX_CODES, OVERSEAS_FUTURES_CODES


def _sign_symbol(sign_code):
    """KIS 대비부호 → 화살표"""
    return {"1": "▲", "2": "▲", "3": "─", "4": "▼", "5": "▼"}.get(sign_code, "")


def _safe_float(val, default=0.0):
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def fetch_global_indices():
    """미국 주요 지수 (S&P500, NASDAQ, DOW, VIX) 조회"""
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=7)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    results = {}
    for name, code in GLOBAL_INDICES.items():
        try:
            data = kis_get(
                "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice",
                "FHKST03030100",
                {
                    "FID_COND_MRKT_DIV_CODE": "N",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": start,
                    "FID_INPUT_DATE_2": end,
                    "FID_PERIOD_DIV_CODE": "D",
                },
            )
            o1 = data.get("output1", {})
            results[name] = {
                "현재가": _safe_float(o1.get("ovrs_nmix_prpr")),
                "전일대비": _safe_float(o1.get("ovrs_nmix_prdy_vrss")),
                "등락률": _safe_float(o1.get("prdy_ctrt")),
                "부호": _sign_symbol(o1.get("prdy_vrss_sign", "3")),
            }
        except Exception as e:
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.2)
    return results


def fetch_fx_rates():
    """환율 (USD/KRW, DXY) 조회"""
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=7)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    results = {}
    for name, code in FX_CODES.items():
        try:
            data = kis_get(
                "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice",
                "FHKST03030100",
                {
                    "FID_COND_MRKT_DIV_CODE": "X",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": start,
                    "FID_INPUT_DATE_2": end,
                    "FID_PERIOD_DIV_CODE": "D",
                },
            )
            o1 = data.get("output1", {})
            results[name] = {
                "현재가": _safe_float(o1.get("ovrs_nmix_prpr")),
                "전일대비": _safe_float(o1.get("ovrs_nmix_prdy_vrss")),
                "등락률": _safe_float(o1.get("prdy_ctrt")),
                "부호": _sign_symbol(o1.get("prdy_vrss_sign", "3")),
            }
        except Exception as e:
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.2)
    return results


def fetch_bond_rates():
    """국내외 금리 (미국 2Y/10Y, 국내 국고채 등) 조회"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/comp-interest",
            "FHPST07020000",
            {
                "FID_COND_MRKT_DIV_CODE": "I",
                "FID_COND_SCR_DIV_CODE": "20702",
                "FID_DIV_CLS_CODE": "1",
                "FID_DIV_CLS_CODE1": "",
            },
        )
        overseas = {}
        for item in data.get("output1", []):
            code = item.get("bcdt_code", "")
            overseas[code] = {
                "이름": item.get("hts_kor_isnm", ""),
                "금리": _safe_float(item.get("bond_mnrt_prpr")),
                "전일대비": _safe_float(item.get("bond_mnrt_prdy_vrss")),
                "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
            }
        domestic = {}
        for item in data.get("output2", []):
            code = item.get("bcdt_code", "")
            domestic[code] = {
                "이름": item.get("hts_kor_isnm", ""),
                "금리": _safe_float(item.get("bond_mnrt_prpr")),
                "전일대비": _safe_float(item.get("bond_mnrt_prdy_vrss")),
                "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
            }
        # 핵심 금리만 추출
        result = {
            "미국 2Y": overseas.get("Y0203", overseas.get("Y0201", {})),  # T-BILL or T-BOND
            "미국 10Y": overseas.get("Y0202", {}),
            "연방기금금리": overseas.get("Y0204", {}),
            "국고채 3Y": domestic.get("Y0101", {}),
            "국고채 10Y": domestic.get("Y0106", {}),
        }
        # Y0203이 1년T-BILL이므로 2Y는 별도로 계산 필요할 수 있음
        # 실제 미국 2Y는 KIS에서 직접 제공하지 않을 수 있어 output1 전체 반환
        result["_raw_overseas"] = overseas
        result["_raw_domestic"] = domestic
        return result
    except Exception as e:
        return {"error": str(e)}


def fetch_commodities():
    """원자재 (WTI, 금, 구리) 조회 - 해외선물 API 사용"""
    results = {}
    for name, symbol in OVERSEAS_FUTURES_CODES.items():
        try:
            data = kis_get(
                "/uapi/overseas-futureoption/v1/quotations/inquire-price",
                "HHDFC55010000",
                {"SRS_CD": symbol},
            )
            o = data.get("output", {})
            last = _safe_float(o.get("last_prpr"))       # 현재가
            base = _safe_float(o.get("base_prpr"))        # 전일종가
            diff = last - base if base > 0 else 0
            rate = (diff / base * 100) if base > 0 else 0
            sign = "▲" if diff > 0 else ("▼" if diff < 0 else "─")
            results[name] = {
                "현재가": last,
                "전일대비": diff,
                "등락률": rate,
                "부호": sign,
            }
        except Exception as e:
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.2)
    return results


def fetch_all_global():
    """글로벌 시장 데이터 전체 조회 (한번에)"""
    return {
        "indices": fetch_global_indices(),
        "fx": fetch_fx_rates(),
        "bonds": fetch_bond_rates(),
        "commodities": fetch_commodities(),
    }
