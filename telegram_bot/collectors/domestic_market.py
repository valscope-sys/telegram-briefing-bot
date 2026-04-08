"""국내 증시 데이터 수집 (KOSPI/KOSDAQ, 수급, 섹터, 52주 신고저 등) - KIS API 사용"""
import time
import datetime
from telegram_bot.kis_client import kis_get
from telegram_bot.config import SECTOR_ETFS, SECTOR_STOCKS


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


def _prev_business_day(base_date=None):
    """전 영업일 계산 (주말 건너뜀)"""
    if base_date is None:
        base_date = datetime.date.today()
    d = base_date - datetime.timedelta(days=1)
    while d.weekday() >= 5:  # 5=토, 6=일
        d -= datetime.timedelta(days=1)
    return d


def _recent_business_days(count=5, base_date=None):
    """최근 N 영업일 리스트"""
    if base_date is None:
        base_date = datetime.date.today()
    days = []
    d = base_date
    while len(days) < count:
        d -= datetime.timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return days


def fetch_kospi_kosdaq():
    """KOSPI/KOSDAQ 지수 (장중이면 현재가, 장전이면 전일 종가)"""
    results = {}
    for name, code in [("KOSPI", "0001"), ("KOSDAQ", "1001")]:
        try:
            # 현재 지수 조회 (장전에도 전일 종가를 반환함)
            data = kis_get(
                "/uapi/domestic-stock/v1/quotations/inquire-index-price",
                "FHPUP02100000",
                {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code},
            )
            o = data["output"]
            trade_vol = _safe_int(o.get("acml_tr_pbmn", 0))

            # 장전(거래대금 0)이면 일별 시세에서 전일 데이터 가져오기
            if trade_vol == 0:
                prev = _prev_business_day()
                start = (prev - datetime.timedelta(days=14)).strftime("%Y%m%d")
                end = prev.strftime("%Y%m%d")
                daily = kis_get(
                    "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
                    "FHKUP03500100",
                    {
                        "FID_COND_MRKT_DIV_CODE": "U",
                        "FID_INPUT_ISCD": code,
                        "FID_INPUT_DATE_1": start,
                        "FID_INPUT_DATE_2": end,
                        "FID_PERIOD_DIV_CODE": "D",
                    },
                )
                daily_list = daily.get("output2", [])
                if len(daily_list) >= 2:
                    today_d = daily_list[0]   # 전일 (가장 최근)
                    prev_d = daily_list[1]    # 전전일
                    close = _safe_float(today_d.get("bstp_nmix_prpr"))
                    prev_close = _safe_float(prev_d.get("bstp_nmix_prpr"))
                    diff = close - prev_close
                    rate = (diff / prev_close * 100) if prev_close > 0 else 0
                    results[name] = {
                        "현재가": close,
                        "전일대비": round(diff, 2),
                        "등락률": round(rate, 2),
                        "부호": "▲" if diff > 0 else ("▼" if diff < 0 else "─"),
                        "거래대금": _safe_int(today_d.get("acml_tr_pbmn", 0)),
                        "상승": _safe_int(o.get("ascn_issu_cnt", 0)),
                        "하락": _safe_int(o.get("down_issu_cnt", 0)),
                        "보합": _safe_int(o.get("stnr_issu_cnt", 0)),
                        "날짜": today_d.get("stck_bsop_date", ""),
                    }
                    continue

            results[name] = {
                "현재가": _safe_float(o["bstp_nmix_prpr"]),
                "전일대비": _safe_float(o["bstp_nmix_prdy_vrss"]),
                "등락률": _safe_float(o["bstp_nmix_prdy_ctrt"]),
                "부호": _sign_symbol(o.get("prdy_vrss_sign", "3")),
                "거래대금": trade_vol,
                "상승": _safe_int(o.get("ascn_issu_cnt", 0)),
                "하락": _safe_int(o.get("down_issu_cnt", 0)),
                "보합": _safe_int(o.get("stnr_issu_cnt", 0)),
            }
        except Exception as e:
            results[name] = {"error": str(e)}
        time.sleep(0.15)
    return results


def fetch_investor_trends(market_code="0001"):
    """시장별 투자자 매매동향 (당일 우선, 없으면 전영업일)"""
    market_sym = "KSP" if market_code == "0001" else "KSQ"

    # 당일 포함해서 시도 (16:00 이후면 당일 데이터가 있음)
    today = datetime.date.today()
    dates_to_try = [today]  # 당일 먼저 시도
    dates_to_try.extend(_recent_business_days(5))  # 없으면 이전 영업일

    for biz_day in dates_to_try:
        date_str = biz_day.strftime("%Y%m%d")
        try:
            data = kis_get(
                "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
                "FHPTJ04040000",
                {
                    "FID_COND_MRKT_DIV_CODE": "U",
                    "FID_INPUT_ISCD": market_code,
                    "FID_INPUT_DATE_1": date_str,
                    "FID_INPUT_ISCD_1": market_sym,
                    "FID_INPUT_DATE_2": date_str,
                    "FID_INPUT_ISCD_2": market_code,
                },
            )
            items = data.get("output", [])
            if items and isinstance(items, list) and len(items) > 0:
                latest = items[0]
                # 실제 데이터가 있는지 확인
                frgn = _safe_int(latest.get("frgn_ntby_tr_pbmn", 0))
                if frgn != 0 or _safe_int(latest.get("orgn_ntby_tr_pbmn", 0)) != 0:
                    return {
                        "외국인": _safe_int(latest.get("frgn_ntby_qty", 0)),
                        "기관": _safe_int(latest.get("orgn_ntby_qty", 0)),
                        "개인": _safe_int(latest.get("prsn_ntby_qty", 0)),
                        "외국인금액": frgn,
                        "기관금액": _safe_int(latest.get("orgn_ntby_tr_pbmn", 0)),
                        "개인금액": _safe_int(latest.get("prsn_ntby_tr_pbmn", 0)),
                        "날짜": date_str,
                    }
        except Exception:
            pass
        time.sleep(0.15)
    return {"error": "최근 5영업일 데이터 없음"}


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
    """52주 신고가 종목 (근접 API + 현재가 >= 52주최고가 필터)"""
    results = {"신고가": []}

    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/ranking/near-new-highlow",
            "FHPST01870000",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_cond_scr_div_code": "20187",
                "fid_input_iscd": "0000",
                "fid_div_cls_code": "1",  # 신고가 근접
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
        for item in data.get("output", []):
            price = _safe_int(item.get("stck_prpr", 0))
            new_hg = _safe_int(item.get("new_hgpr", 0))
            rate = _safe_float(item.get("prdy_ctrt", 0))
            name = item.get("hts_kor_isnm", "").strip()

            # 실제 52주 신고가 달성: 현재가 >= 52주 최고가
            if not name or price == 0 or new_hg == 0:
                continue
            if price < new_hg:
                continue

            results["신고가"].append({
                "종목명": name,
                "현재가": price,
                "등락률": rate,
                "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
            })
            if len(results["신고가"]) >= 5:
                break
    except Exception:
        pass

    return results


def fetch_sector_stocks():
    """섹터별 대표 종목 시세 조회"""
    results = {}
    for sector_name, stocks in SECTOR_STOCKS.items():
        sector_results = []
        for stock_name, code in stocks:
            try:
                data = kis_get(
                    "/uapi/domestic-stock/v1/quotations/inquire-price",
                    "FHKST01010100",
                    {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
                )
                o = data["output"]
                sector_results.append({
                    "종목명": stock_name,
                    "현재가": _safe_int(o.get("stck_prpr", 0)),
                    "등락률": _safe_float(o.get("prdy_ctrt", 0)),
                })
            except Exception:
                pass
            time.sleep(0.05)
        results[sector_name] = sector_results
    return results


def fetch_trade_value_rank():
    """거래대금 상위 30종목"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "3",   # 3: 거래금액순
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        results = []
        for item in data.get("output", data.get("Output", []))[:30]:
            results.append({
                "종목명": item.get("hts_kor_isnm", ""),
                "종목코드": item.get("mksc_shrn_iscd", ""),
                "현재가": _safe_int(item.get("stck_prpr", 0)),
                "등락률": _safe_float(item.get("prdy_ctrt", 0)),
                "거래량": _safe_int(item.get("acml_vol", 0)),
                "거래대금": _safe_int(item.get("acml_tr_pbmn", 0)),
            })
        return results
    except Exception as e:
        return []


def fetch_fluctuation_rank(sort_order="1"):
    """등락률 상위/하위 30종목 (1:상승률순, 2:하락률순)"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/ranking/fluctuation",
            "FHPST01700000",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_cond_scr_div_code": "20170",
                "fid_input_iscd": "0000",
                "fid_rank_sort_cls_code": sort_order,
                "fid_input_cnt_1": "0",
                "fid_prc_cls_code": "1",         # 1: 보통주만
                "fid_input_price_1": "1000",      # 1000원 이상
                "fid_input_price_2": "",
                "fid_vol_cnt": "10000",           # 거래량 1만주 이상
                "fid_trgt_cls_code": "0",
                "fid_trgt_exls_cls_code": "0",
                "fid_div_cls_code": "0",
                "fid_rsfl_rate1": "",
                "fid_rsfl_rate2": "",
            },
        )
        results = []
        for item in data.get("output", [])[:30]:
            results.append({
                "종목명": item.get("hts_kor_isnm", ""),
                "종목코드": item.get("stck_shrn_iscd", item.get("mksc_shrn_iscd", "")),
                "현재가": _safe_int(item.get("stck_prpr", 0)),
                "등락률": _safe_float(item.get("prdy_ctrt", 0)),
                "거래대금": _safe_int(item.get("acml_tr_pbmn", 0)),
            })
        return results
    except Exception:
        return []


def fetch_all_domestic():
    """국내 시장 데이터 전체 조회"""
    return {
        "indices": fetch_kospi_kosdaq(),
        "investors": fetch_investor_trends(),
        "program": fetch_program_trade(),
        "sectors": fetch_sector_performance(),
        "sector_stocks": fetch_sector_stocks(),
        "highlow": fetch_new_highlow(),
        "trade_value_rank": fetch_trade_value_rank(),
        "top_gainers": fetch_fluctuation_rank("1"),
        "top_losers": fetch_fluctuation_rank("2"),
    }
