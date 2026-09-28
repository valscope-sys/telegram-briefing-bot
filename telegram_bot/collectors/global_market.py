"""글로벌 시장 데이터 수집 (해외지수, 환율, 금리, 원자재)
- 지수/환율: KIS API (정상 동작 확인됨)
- VIX/DXY/원자재: yfinance (KIS에서 미지원)
- 금리: KIS 금리종합 API
"""
import datetime
import re
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


def _quote_from_daily_chart(data, label):
    """KIS 해외 일별차트(FHKST03030100) 응답 → 시세 dict.

    2026-09 확인: DOW(.DJI)는 output1(요약)이 전부 0.00으로 오지만 output2(일봉)는 정상.
    output1 현재가가 0이면 output2 최근 2봉(최신순)으로 종가·전일대비·등락률을 직접 계산.
    """
    o1 = data.get("output1", {}) or {}
    price = _safe_float(o1.get("ovrs_nmix_prpr"))
    if price:
        return {
            "현재가": price,
            "전일대비": _safe_float(o1.get("ovrs_nmix_prdy_vrss")),
            "등락률": _safe_float(o1.get("prdy_ctrt")),
            "부호": _sign_symbol(o1.get("prdy_vrss_sign", "3")),
        }
    rows = [r for r in (data.get("output2") or []) if _safe_float(r.get("ovrs_nmix_prpr"))]
    if len(rows) >= 2:
        last = _safe_float(rows[0].get("ovrs_nmix_prpr"))
        prev = _safe_float(rows[1].get("ovrs_nmix_prpr"))
        diff = last - prev
        print(f"[GLOBAL] {label}: KIS output1 비어있음 → output2 일봉({rows[0].get('stck_bsop_date')})으로 계산")
        return {
            "현재가": round(last, 2),
            "전일대비": round(diff, 2),
            "등락률": round(diff / prev * 100, 2) if prev else 0,
            "부호": "▲" if diff > 0 else ("▼" if diff < 0 else "─"),
        }
    raise RuntimeError(f"KIS 일별차트 응답에 시세 없음 (output1=0, output2 {len(rows)}건)")


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
            results[name] = _quote_from_daily_chart(data, name)
        except Exception as e:
            print(f"[GLOBAL] ERROR: {name}({code}) 지수 조회 실패: {e}")
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.2)
    return results


def fetch_vix():
    """VIX 변동성지수 - yfinance"""
    try:
        return _yf_quote("^VIX")
    except Exception as e:
        print(f"[GLOBAL] ERROR: VIX(^VIX) 조회 실패: {e}")
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
            results[name] = _quote_from_daily_chart(data, name)
        except Exception as e:
            print(f"[GLOBAL] ERROR: {name}({code}) 환율 조회 실패: {e}")
            results[name] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}
        time.sleep(0.2)

    # DXY - yfinance
    try:
        results["DXY"] = _yf_quote("DX-Y.NYB")
    except Exception as e:
        print(f"[GLOBAL] ERROR: DXY(DX-Y.NYB) 조회 실패: {e}")
        results["DXY"] = {"현재가": 0, "전일대비": 0, "등락률": 0, "부호": "─", "error": str(e)}

    return results


def _is_valid_bond_row(item):
    """금리 행 무결성 검사 — 필드 밀림/깨진 행(이름칸에 'Y0109' 같은 코드, 금리칸에 문자열) 제외."""
    code = str(item.get("bcdt_code", ""))
    name = str(item.get("hts_kor_isnm", ""))
    rate = str(item.get("bond_mnrt_prpr", "")).strip()
    if not re.fullmatch(r"Y\d{4}", code) or re.fullmatch(r"Y\d{4}", name) or "�" in name:
        return False
    try:
        float(rate)
        float(str(item.get("bond_mnrt_prdy_vrss", "0")).strip() or 0)
    except ValueError:
        return False
    return True


def fetch_bond_rates():
    """국내외 금리 - KIS 금리종합 API

    2026-09-28 fix: FID_DIV_CLS_CODE="1" 응답의 output2(국내)가 KIS 측에서 깨져 옴
    (앞 10행 필드 밀림 + EUC-KR 깨짐 → 국고채 3Y/10Y 소실, 금리=0). "2"는 output1 하나에
    국내(Y01xx)+해외(Y02xx) 26개가 정상으로 옴 → "2"로 조회하고 코드 접두어로 분리.
    깨진 행은 무결성 검사로 버림 (금리 0을 정상값처럼 내보내지 않도록).
    """
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/comp-interest",
            "FHPST07020000",
            {
                "FID_COND_MRKT_DIV_CODE": "I",
                "FID_COND_SCR_DIV_CODE": "20702",
                "FID_DIV_CLS_CODE": "2",
                "FID_DIV_CLS_CODE1": "",
            },
        )
        overseas = {}
        domestic = {}
        dropped = 0
        for item in (data.get("output1") or []) + (data.get("output2") or []):
            if not _is_valid_bond_row(item):
                dropped += 1
                continue
            code = item.get("bcdt_code", "")
            target = domestic if code.startswith("Y01") else overseas
            if code in target:
                continue  # output1 우선
            target[code] = {
                "이름": item.get("hts_kor_isnm", ""),
                "금리": _safe_float(item.get("bond_mnrt_prpr")),
                "전일대비": _safe_float(item.get("bond_mnrt_prdy_vrss")),
                "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
            }
        missing = [c for c in ("Y0202", "Y0101", "Y0106") if c not in overseas and c not in domestic]
        if missing:
            print(f"[BOND] ERROR: KIS 금리종합 핵심 금리 누락 {missing} (깨진 행 {dropped}개 제외)")
        # 2Y: yfinance 2YY=F futures (1일 지연 가능하나 움직임 추적 가능)
        # 3M: ^IRX (NY Fed 표준 리세션 시그널 10Y-3M 용)
        us_2y = _fetch_yf_yield("2YY=F")
        us_3m = _fetch_yf_yield("^IRX")

        result = {
            "미국 3M": us_3m,
            "미국 1Y": overseas.get("Y0203", {}),  # KIS 1년 T-BILL
            "미국 2Y": us_2y,                         # yfinance 2YY=F
            "미국 10Y": overseas.get("Y0202", {}),
            "연방기금금리": overseas.get("Y0204", {}),
            "국고채 3Y": domestic.get("Y0101", {}),
            "국고채 10Y": domestic.get("Y0106", {}),
        }
        result["_raw_overseas"] = overseas
        result["_raw_domestic"] = domestic
        return result
    except Exception as e:
        print(f"[BOND] ERROR: 금리 조회 실패: {e}")
        return {"error": str(e)}


def _fetch_yf_yield(ticker, max_stale_days=3, max_daily_bp=0.15):
    """yfinance 로 금리 지수/선물 조회 (2Y, 3M 등 KIS 미제공분).

    2026-06-02 가드 추가 — 2YY=F(2Y 선물) stale 사고 대응:
    거래량 적은 선물(2YY=F)이 며칠간 갱신 안 되면 마지막 2봉 차이가 고정되어
    매일 시황에 "+18.9bp 급등" 같은 틀린 전일대비가 박힘 (5/29~6/2 실제 발생).

    - stale 가드: 마지막 봉 날짜가 max_stale_days(3일, 주말 고려) 초과 → {} 반환 (제외)
    - delta sanity: 일간 변동 ±max_daily_bp(15bp) 초과 → 전일대비 신뢰 안 함
      (단기 금리 하루 15bp 변동은 FOMC 서프라이즈급 — 일상적으론 stale 점프 의심)
    """
    try:
        import yfinance as yf
        import datetime
        hist = yf.Ticker(ticker).history(period="10d")
        if hist.empty or len(hist) < 2:
            print(f"[BOND] ERROR: {ticker} yfinance 이력 부족 ({len(hist)}봉) — 제외")
            return {}
        # stale 가드 — 마지막 봉이 너무 오래됐으면 제외
        last_date = hist.index[-1].date()
        today = datetime.date.today()
        if (today - last_date).days > max_stale_days:
            print(f"[BOND] {ticker} stale: 마지막 봉 {last_date} ({(today-last_date).days}일 경과) — 제외")
            return {}
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        delta = last - prev
        result = {"이름": ticker, "금리": round(last, 3)}
        # delta sanity — 비현실적 일간 변동이면 전일대비 제외 (금리 레벨은 유지)
        if abs(delta) > max_daily_bp:
            print(f"[BOND] {ticker} delta 이상치 {delta*100:+.1f}bp — 전일대비 제외 (stale 점프 의심)")
            return result  # 전일대비/부호 없이 금리 레벨만
        sign = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
        result["전일대비"] = round(delta, 3)
        result["부호"] = sign
        return result
    except Exception as e:
        print(f"[BOND] ERROR: {ticker} yfinance 조회 실패: {e}")
        return {}


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
            print(f"[GLOBAL] ERROR: 원자재 {name}({ticker}) 조회 실패: {e}")
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
            print(f"[GLOBAL] ERROR: 미국 섹터 {name}({ticker}) 조회 실패: {e}")
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
            print(f"[GLOBAL] ERROR: 미국 종목 {ticker} 조회 실패: {e}")
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
            print(f"[GLOBAL] ERROR: 야간 프록시 {name}({ticker}) 조회 실패: {e}")
            results[name] = {"현재가": 0, "등락률": 0, "부호": "─", "설명": desc, "error": str(e)}
    return results


def fetch_sentiment_indicators():
    """시장 심리 지표 수집 (Fear & Greed Index, Put/Call Ratio)"""
    result = {}

    import requests
    # 2026-09-28: CNN은 "Mozilla/5.0" 단독 UA를 봇으로 차단 (HTTP 418 "I'm a teapot") → 전체 브라우저 UA.
    browser_ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

    # CNN Fear & Greed Index
    try:
        res = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": browser_ua, "Referer": "https://edition.cnn.com/"},
            timeout=5,
        )
        if res.status_code != 200:
            raise RuntimeError(f"HTTP {res.status_code}: {res.text[:80]}")
        data = res.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score", 0)
        rating = fg.get("rating", "")
        # rating: 2026-09 현재 소문자("fear", "extreme greed")로 옴 → 대소문자 무시 매핑
        rating_kr = {
            "extreme fear": "극단적 공포",
            "fear": "공포",
            "neutral": "중립",
            "greed": "탐욕",
            "extreme greed": "극단적 탐욕",
        }.get(str(rating).strip().lower(), rating)
        result["Fear & Greed"] = {
            "점수": round(score),
            "등급": rating_kr,
            "원문": rating,
        }
    except Exception as e:
        print(f"[SENTIMENT] ERROR: CNN Fear & Greed 조회 실패: {e}")
        result["Fear & Greed"] = {"error": str(e)}

    # CBOE Total Put/Call Ratio
    # 2026-09-28: 구 cdn.cboe.com/api/global/us_indices/daily_prices/PCALL.json 은 403(AccessDenied).
    # CBOE Daily Market Statistics JSON 사용: .../daily/{YYYY-MM-DD}_daily_options
    #   → {"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.75"}, ...]}
    # 주말·휴장일은 파일이 없으므로(403) 최근 7일을 거슬러 첫 번째 존재 파일 사용.
    try:
        pc_ratio = 0
        pc_date = ""
        base = datetime.datetime.now(datetime.timezone.utc).date()
        for back in range(8):
            d = (base - datetime.timedelta(days=back)).isoformat()
            res = requests.get(
                f"https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options",
                headers={"User-Agent": browser_ua}, timeout=5,
            )
            if res.status_code != 200:
                continue
            ratios = {r.get("name", ""): r.get("value") for r in (res.json().get("ratios") or [])}
            pc_ratio = _safe_float(ratios.get("TOTAL PUT/CALL RATIO"))
            pc_date = d
            break
        if not pc_ratio:
            raise RuntimeError("최근 7일 CBOE daily_options 파일 없음 또는 TOTAL PUT/CALL RATIO 누락")
        result["Put/Call Ratio"] = {
            "비율": round(pc_ratio, 2) if pc_ratio else 0,
            "해석": "풋 우세 (약세 심리)" if pc_ratio and pc_ratio > 1.0 else "콜 우세 (강세 심리)" if pc_ratio else "",
            "날짜": pc_date,
        }
    except Exception as e:
        # 폴백: 생략 (프롬프트에서 해당 줄만 빠짐)
        print(f"[SENTIMENT] ERROR: CBOE Put/Call Ratio 조회 실패: {e}")

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
