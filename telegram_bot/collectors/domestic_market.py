"""국내 증시 데이터 수집 (KOSPI/KOSDAQ, 수급, 섹터, 52주 신고저 등) - KIS API 사용"""
import time
from telegram_bot.kis_client import kis_get
from telegram_bot.config import SECTOR_ETFS


def _sign_symbol(sign_code):
    return {"1": "▲", "2": "▲", "3": "─", "4": "▼", "5": "▼"}.get(str(sign_code), "")


def _safe_float(val, default=0.0):
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    try:
        return int(float(val)) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def fetch_kospi_kosdaq():
    """KOSPI/KOSDAQ 현재 지수 조회"""
    results = {}
    for name, code in [("KOSPI", "0001"), ("KOSDAQ", "1001")]:
        try:
            data = kis_get(
                "/uapi/domestic-stock/v1/quotations/inquire-index-price",
                "FHPUP02100000",
                {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code},
            )
            o = data["output"]
            results[name] = {
                "현재가": _safe_float(o["bstp_nmix_prpr"]),
                "전일대비": _safe_float(o["bstp_nmix_prdy_vrss"]),
                "등락률": _safe_float(o["bstp_nmix_prdy_ctrt"]),
                "부호": _sign_symbol(o.get("prdy_vrss_sign", "3")),
                "거래대금": _safe_int(o.get("acml_tr_pbmn", 0)),
                "상승": _safe_int(o.get("ascn_issu_cnt", 0)),
                "하락": _safe_int(o.get("down_issu_cnt", 0)),
                "보합": _safe_int(o.get("stnr_issu_cnt", 0)),
            }
        except Exception as e:
            results[name] = {"error": str(e)}
        time.sleep(0.1)
    return results


def fetch_investor_trends(market_code="0001"):
    """시장별 투자자 매매동향 (외국인/기관/개인)"""
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    market_sym = "KSP" if market_code == "0001" else "KSQ"
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
            "FHPTJ04040000",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": market_code,
                "FID_INPUT_DATE_1": today,
                "FID_INPUT_ISCD_1": market_sym,
                "FID_INPUT_DATE_2": today,
                "FID_INPUT_ISCD_2": market_code,
            },
        )
        items = data.get("output", [])
        if not items:
            return {}
        # 첫 번째 항목이 가장 최근 데이터
        latest = items[0] if isinstance(items, list) else items
        return {
            "외국인": _safe_int(latest.get("frgn_ntby_qty", 0)),
            "기관": _safe_int(latest.get("orgn_ntby_qty", 0)),
            "개인": _safe_int(latest.get("prsn_ntby_qty", 0)),
            "외국인금액": _safe_int(latest.get("frgn_ntby_tr_pbmn", 0)),
            "기관금액": _safe_int(latest.get("orgn_ntby_tr_pbmn", 0)),
            "개인금액": _safe_int(latest.get("prsn_ntby_tr_pbmn", 0)),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_program_trade():
    """프로그램매매 종합현황"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/comp-program-trade-today",
            "FHPPG04600101",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_MRKT_CLS_CODE": "K",
                "FID_SCTN_CLS_CODE": "",
                "FID_INPUT_ISCD": "",
                "FID_COND_MRKT_DIV_CODE1": "",
                "FID_INPUT_HOUR_1": "",
            },
        )
        items = data.get("output", [])
        if not items:
            return {}
        latest = items[0] if isinstance(items, list) else items
        return {
            "차익순매수": _safe_int(latest.get("arbt_ntby_qty", 0)),
            "비차익순매수": _safe_int(latest.get("nrbt_ntby_qty", 0)),
            "합계순매수": _safe_int(latest.get("sum_ntby_qty", 0)),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_sector_performance():
    """섹터 ETF별 등락률 조회"""
    results = {}
    for sector_name, etf_code in SECTOR_ETFS.items():
        try:
            data = kis_get(
                "/uapi/domestic-stock/v1/quotations/inquire-price",
                "FHKST01010100",
                {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": etf_code},
            )
            o = data["output"]
            results[sector_name] = {
                "현재가": _safe_int(o.get("stck_prpr", 0)),
                "등락률": _safe_float(o.get("prdy_ctrt", 0)),
                "부호": _sign_symbol(o.get("prdy_vrss_sign", "3")),
            }
        except Exception as e:
            results[sector_name] = {"등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.05)
    return results


def fetch_new_highlow():
    """52주 신고가/신저가 종목"""
    results = {"신고가": [], "신저가": []}

    for cls_code, key in [("1", "신고가"), ("2", "신저가")]:
        try:
            data = kis_get(
                "/uapi/domestic-stock/v1/ranking/near-new-highlow",
                "FHPST01870000",
                {
                    "fid_cond_mrkt_div_code": "J",
                    "fid_cond_scr_div_code": "20187",
                    "fid_input_iscd": "0000",
                    "fid_div_cls_code": cls_code,
                    "fid_trgt_cls_code": "0",
                    "fid_trgt_exls_cls_code": "0",
                    "fid_aply_rang_prc_1": "",
                    "fid_aply_rang_prc_2": "",
                    "fid_aply_rang_vol": "0",
                    "fid_input_cnt_1": "0",
                    "fid_input_cnt_2": "0",
                    "fid_prc_cls_code": "0",
                },
            )
            for item in data.get("output", [])[:5]:
                results[key].append({
                    "종목명": item.get("hts_kor_isnm", ""),
                    "현재가": _safe_int(item.get("stck_prpr", 0)),
                    "등락률": _safe_float(item.get("prdy_ctrt", 0)),
                    "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
                })
        except Exception:
            pass
        time.sleep(0.2)
    return results


def fetch_volume_rank():
    """거래량 상위 종목"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        results = []
        for item in data.get("output", data.get("Output", []))[:10]:
            results.append({
                "종목명": item.get("hts_kor_isnm", ""),
                "종목코드": item.get("mksc_shrn_iscd", ""),
                "현재가": _safe_int(item.get("stck_prpr", 0)),
                "등락률": _safe_float(item.get("prdy_ctrt", 0)),
                "거래량": _safe_int(item.get("acml_vol", 0)),
            })
        return results
    except Exception as e:
        return [{"error": str(e)}]


def fetch_all_domestic():
    """국내 시장 데이터 전체 조회"""
    return {
        "indices": fetch_kospi_kosdaq(),
        "investors": fetch_investor_trends(),
        "program": fetch_program_trade(),
        "sectors": fetch_sector_performance(),
        "highlow": fetch_new_highlow(),
    }
