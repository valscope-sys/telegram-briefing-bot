"""글로벌 시장 데이터 수집 (해외지수, 환율, 금리, 원자재)
- 지수/환율: KIS API (정상 동작 확인됨)
- VIX/DXY/원자재: yfinance (KIS에서 미지원)
- 금리: KIS 금리종합 API
"""
import datetime
import time
from telegram_bot.kis_client import kis_get
from telegram_bot.config import GLOBAL_INDICES, FX_CODES


def _sign_symbol(sign_code):
    """KIS 대비부호 → 화살표"""
    return {"1": "▲", "2": "▲", "3": "─", "4": "▼", "5": "▼"}.get(sign_code, "")


def _safe_float(val, default=0.0):
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _yf_quote(ticker):
    """yfinance로 단일 종목 현재가 조회 (선물 등락률 정확도 개선)"""
    import yfinance as yf
    t = yf.Ticker(ticker)
    # history 기반 계산 (선물의 fast_info.previous_close 부정확 문제 해결)
    try:
        hist = t.history(period="5d")
        if len(hist) >= 2:
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
        else:
            info = t.fast_info
            last = info.last_price
            prev = info.previous_close
    except Exception:
        info = t.fast_info
        last = info.last_price
        prev = info.previous_close
    diff = last - prev if prev else 0
    rate = (diff / prev * 100) if prev else 0
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "─")
    return {
        "현재가": round(last, 2),
        "전일대비": round(diff, 2),
        "등락률": round(rate, 2),
        "부호": sign,
    }


def fetch_global_indices():
    """미국 주요 지수 (S&P500, NASDAQ, DOW) - KIS API"""
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


def fetch_vix():
    """VIX 변동성지수 - yfinance"""
    try:
        return _yf_quote("^VIX")
    except Exception as e:
        return {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}


def fetch_fx_rates():
    """환율 (USD/KRW: KIS API, DXY: yfinance)"""
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=7)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    results = {}
    # USD/KRW - KIS API
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

    # DXY - yfinance
    try:
        results["DXY"] = _yf_quote("DX-Y.NYB")
    except Exception as e:
        results["DXY"] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}

    return results


def fetch_bond_rates():
    """국내외 금리 - KIS 금리종합 API"""
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
        result = {
            "미국 2Y": overseas.get("Y0203", {}),
            "미국 10Y": overseas.get("Y0202", {}),
            "연방기금금리": overseas.get("Y0204", {}),
            "국고채 3Y": domestic.get("Y0101", {}),
            "국고채 10Y": domestic.get("Y0106", {}),
        }
        result["_raw_overseas"] = overseas
        result["_raw_domestic"] = domestic
        return result
    except Exception as e:
        return {"error": str(e)}


def fetch_commodities():
    """원자재 (WTI, 금, 구리) - yfinance"""
    yf_codes = {
        "WTI": "CL=F",
        "금": "GC=F",
        "구리": "HG=F",
    }
    results = {}
    for name, ticker in yf_codes.items():
        try:
            results[name] = _yf_quote(ticker)
        except Exception as e:
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
    return results


def fetch_us_sectors():
    """미국 S&P 섹터 ETF 등락률 - yfinance"""
    sector_etfs = {
        "기술": "XLK",
        "반도체": "SOXX",
        "에너지": "XLE",
        "헬스케어": "XLV",
        "금융": "XLF",
        "산업재": "XLI",
        "소비재": "XLY",
        "유틸리티": "XLU",
        "소재": "XLB",
        "통신": "XLC",
        "부동산": "XLRE",
    }
    results = {}
    for name, ticker in sector_etfs.items():
        try:
            results[name] = _yf_quote(ticker)
        except Exception as e:
            results[name] = {"현재가": 0, "등락률": 0, "부호": "─", "error": str(e)}
    return results


def fetch_us_major_stocks():
    """미국 주요 종목 등락률 - yfinance"""
    from telegram_bot.config import US_MAJOR_STOCKS
    stocks = US_MAJOR_STOCKS
    results = {}
    for ticker, name in stocks.items():
        try:
            data = _yf_quote(ticker)
            data["종목명"] = name
            results[ticker] = data
        except Exception as e:
            results[ticker] = {"종목명": name, "현재가": 0, "등락률": 0, "부호": "─", "error": str(e)}
    return results


def fetch_korea_proxies():
    """한국 관련 해외 프록시 지표 (KORU, EWY, 코스피200)"""
    proxies = {
        "KORU": ("KORU", "한국3x레버리지"),
        "EWY": ("EWY", "한국ETF"),
        "코스피200": ("^KS200", "코스피200"),
    }
    results = {}
    for name, (ticker, desc) in proxies.items():
        try:
            data = _yf_quote(ticker)
            data["설명"] = desc
            results[name] = data
        except Exception as e:
            results[name] = {"현재가": 0, "등락률": 0, "부호": "─", "설명": desc, "error": str(e)}
    return results


def fetch_sentiment_indicators():
    """시장 심리 지표 수집 (Fear & Greed Index, Put/Call Ratio)"""
    result = {}

    # CNN Fear & Greed Index
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=headers, timeout=5,
        )
        data = res.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score", 0)
        rating = fg.get("rating", "")
        # rating: Extreme Fear, Fear, Neutral, Greed, Extreme Greed
        rating_kr = {
            "Extreme Fear": "극단적 공포",
            "Fear": "공포",
            "Neutral": "중립",
            "Greed": "탐욕",
            "Extreme Greed": "극단적 탐욕",
        }.get(rating, rating)
        result["Fear & Greed"] = {
            "점수": round(score),
            "등급": rating_kr,
            "원문": rating,
        }
    except Exception as e:
        result["Fear & Greed"] = {"error": str(e)}

    # CBOE Put/Call Ratio (VIX 옵션 비율 → yfinance)
    try:
        import yfinance as yf
        # Total equity put/call ratio는 직접 API 없음, VIX로 대체 가능
        # 대신 CBOE 사이트에서 직접 가져오기
        import requests
        res = requests.get(
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/PCALL.json",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=5,
        )
        data = res.json()
        latest = data.get("data", [{}])[-1] if data.get("data") else {}
        pc_ratio = latest.get("close", 0)
        result["Put/Call Ratio"] = {
            "비율": round(pc_ratio, 2) if pc_ratio else 0,
            "해석": "풋 우세 (약세 심리)" if pc_ratio and pc_ratio > 1.0 else "콜 우세 (강세 심리)" if pc_ratio else "",
        }
    except Exception:
        # 폴백: 생략
        pass

    return result


def fetch_all_global():
    """글로벌 시장 데이터 전체 조회"""
    indices = fetch_global_indices()
    indices["VIX"] = fetch_vix()
    return {
        "indices": indices,
        "fx": fetch_fx_rates(),
        "bonds": fetch_bond_rates(),
        "commodities": fetch_commodities(),
        "us_sectors": fetch_us_sectors(),
        "us_stocks": fetch_us_major_stocks(),
        "korea_proxies": fetch_korea_proxies(),
        "sentiment": fetch_sentiment_indicators(),
    }
