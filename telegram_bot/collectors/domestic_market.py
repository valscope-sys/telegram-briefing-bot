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


def _fetch_trade_volume_avg(code, days=20):
    """지수의 N일 평균 거래대금 조회"""
    try:
        today = datetime.date.today()
        start = (today - datetime.timedelta(days=days * 2)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
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
        volumes = [_safe_int(d.get("acml_tr_pbmn", 0)) for d in daily_list[:days] if _safe_int(d.get("acml_tr_pbmn", 0)) > 0]
        if volumes:
            return sum(volumes) // len(volumes)
    except Exception:
        pass
    return 0


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
                    # 20일 평균 거래대금도 이 경로에서 함께 조회
                    avg_vol_daily = _fetch_trade_volume_avg(code)
                    time.sleep(0.35)
                    results[name] = {
                        "현재가": close,
                        "전일대비": round(diff, 2),
                        "등락률": round(rate, 2),
                        "부호": "▲" if diff > 0 else ("▼" if diff < 0 else "─"),
                        "거래대금": _safe_int(today_d.get("acml_tr_pbmn", 0)),
                        "거래대금_20일평균": avg_vol_daily,
                        "상승": _safe_int(o.get("ascn_issu_cnt", 0)),
                        "하락": _safe_int(o.get("down_issu_cnt", 0)),
                        "보합": _safe_int(o.get("stnr_issu_cnt", 0)),
                        "날짜": today_d.get("stck_bsop_date", ""),
                    }
                    continue

            # 20일 평균 거래대금
            avg_vol = _fetch_trade_volume_avg(code)
            time.sleep(0.35)

            results[name] = {
                "현재가": _safe_float(o["bstp_nmix_prpr"]),
                "전일대비": _safe_float(o["bstp_nmix_prdy_vrss"]),
                "등락률": _safe_float(o["bstp_nmix_prdy_ctrt"]),
                "부호": _sign_symbol(o.get("prdy_vrss_sign", "3")),
                "거래대금": trade_vol,
                "거래대금_20일평균": avg_vol,
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


def _fetch_condition_search_list():
    """종목조건검색 목록 조회 (HTS에서 저장한 조건식 목록)"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/psearch-title",
            "HHKST03900300",
            {"user_id": ""},
        )
        return data.get("output2", [])
    except Exception:
        return []


def _fetch_condition_search_result(seq_no):
    """종목조건검색 결과 조회 (최대 100종목)"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/psearch-result",
            "HHKST03900400",
            {"user_id": "", "seq": seq_no},
        )
        return data.get("output2", [])
    except Exception:
        return []


def _classify_themes_with_claude(stock_names):
    """Claude API로 종목명 → 투자 테마 분류"""
    from telegram_bot.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY or not stock_names:
        return {name: "기타" for name in stock_names}

    import anthropic
    import json
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    names_str = ", ".join(stock_names)
    prompt = f"""다음 한국 주식 종목들을 투자 테마별로 분류해주세요.

종목: {names_str}

테마 예시: 반도체, 반도체장비, 광통신, 통신장비, 2차전지, 방산, 화장품/K-뷰티, 바이오/제약, 의료기기, AI/소프트웨어, 자동차, 자동차부품, 조선, 원전/전력, 건설/재건, 부동산, 철강/소재, 금속/비철, 에너지, 금융, 게임, 음식료, 로봇, 포장/용기, 기타

핵심 규칙:
- 종목의 실제 사업 내용을 정확히 알 때만 분류하세요.
- 종목명에 "반도체"가 들어있다고 반도체로 분류하지 마세요. 실제 사업을 확인하세요.
- 잘 모르는 종목은 반드시 "기타"로 분류하세요. 추측으로 반도체나 다른 테마에 넣지 마세요.
- 주요 오분류 사례:
  레이 = 치과의료기기 (반도체 아님)
  에이치케이 = 부동산 (반도체 아님)
  영화테크 = 자동차부품 (반도체 아님)
  케이엠더블유 = 5G통신장비 (반도체 아님, 통신장비)
  비츠로셀 = 배터리/방산 (반도체 아님)
  기가레인 = RF통신부품 (AI가 아님, 통신장비)

JSON만 출력하세요:
{{"종목명": "테마", "종목명2": "테마2", ...}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # JSON 추출
        if "{" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
    except Exception as e:
        print(f"[THEME] Claude 테마 분류 실패: {e}")

    return {name: "기타" for name in stock_names}


def fetch_new_highlow():
    """52주 신고가 종목 조회 — 키움 REST API (ka10016)
    종가기준 + 우선주제외 + 거래량 1만주 이상
    Claude API로 테마 분류
    데이터 미확정 시 60초 대기 후 재시도 (장 마감 직후 데이터 정산 지연 대응)
    """
    results = {"신고가": []}

    try:
        from telegram_bot.kiwoom_client import kiwoom_post

        # 1차 조회
        def _query_kiwoom():
            data = kiwoom_post("ka10016", {
                "mrkt_tp": "000",           # 전체 (코스피+코스닥)
                "ntl_tp": "1",              # 신고가
                "high_low_close_tp": "2",   # 종가기준
                "stk_cnd": "3",             # 우선주제외
                "trde_qty_tp": "00010",     # 만주이상
                "crd_cnd": "0",             # 전체
                "updown_incls": "0",        # 상하한 미포함
                "dt": "250",               # 250일 = 52주
                "stex_tp": "1",             # KRX
            })
            return data.get("ntl_pric", [])

        stocks = _query_kiwoom()

        # 데이터 미확정 대응: 5종목 미만이면 60초 대기 후 재시도
        if len(stocks) < 5:
            print(f"[KIWOOM] 52주 신고가 {len(stocks)}종목 — 데이터 미확정 가능, 60초 후 재시도")
            time.sleep(60)
            stocks = _query_kiwoom()
            print(f"[KIWOOM] 재시도 결과: {len(stocks)}종목")

        # ETF/리츠/머니마켓/펀드 필터
        exclude_kw = [
            "TIGER", "KODEX", "KBSTAR", "HANARO", "SOL", "ARIRANG", "ACE", "KOSEF",
            "스팩", "SPAC", "리츠", "KOFR", "RISE", "KIWOOM", "머니마켓", "1Q ",
            "인프라", "액티브", "ITF ", "PLUS ", "KoAct", "TIMEFOLIO", "파워",
            "레버리지", "인버스", "ETN",
        ]

        filtered_stocks = []
        for item in stocks:
            name = item.get("stk_nm", "").strip()
            code = item.get("stk_cd", "")
            if not name or not code:
                continue
            if any(kw in name for kw in exclude_kw):
                continue

            rate_str = item.get("flu_rt", "0")
            rate = _safe_float(rate_str.replace("+", "").replace("%", ""))
            price_str = item.get("cur_prc", "0")
            price = _safe_int(price_str.replace("+", "").replace("-", "").replace(",", ""))

            # 거래정지/저유동성 종목 제외 (거래량 + 거래대금 + 등락률 동시 체크)
            vol_str = item.get("trde_qty", "0")
            vol = _safe_int(vol_str.replace(",", ""))
            if price == 0 or vol == 0:
                continue
            # 거래대금 1억원 미만 제외 (거래정지 종목은 전일 잔존 데이터라 낮음)
            trade_value = price * vol
            if trade_value < 100_000_000:
                continue
            # 거래량 10만주 미만 제외 (저유동성)
            if vol < 100_000:
                continue
            # 등락률 정확히 0% + 소량 거래는 거래정지 의심 → 제외
            if rate == 0 and vol < 500_000:
                continue

            filtered_stocks.append({
                "종목명": name,
                "종목코드": code,
                "현재가": price,
                "등락률": rate,
                "부호": "▲" if rate > 0 else ("▼" if rate < 0 else "─"),
            })

        # Claude API로 테마 분류 (한 번에 전체)
        if filtered_stocks:
            stock_names = [s["종목명"] for s in filtered_stocks]
            print(f"[THEME] {len(stock_names)}종목 테마 분류 중...")
            theme_map = _classify_themes_with_claude(stock_names)
            for s in filtered_stocks:
                s["섹터"] = theme_map.get(s["종목명"], "기타")
                results["신고가"].append(s)

    except Exception as e:
        print(f"[KIWOOM] 52주 신고가 조회 실패: {e}")
        import traceback
        traceback.print_exc()
        # 폴백: KIS 근접 API (기존 로직)
        try:
            for market in ["J", "Q"]:
                data = kis_get(
                    "/uapi/domestic-stock/v1/ranking/near-new-highlow",
                    "FHPST01870000",
                    {
                        "fid_cond_mrkt_div_code": market,
                        "fid_cond_scr_div_code": "20187",
                        "fid_input_iscd": "0000",
                        "fid_div_cls_code": "1",
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
                seen = set()
                for item in data.get("output", []):
                    p = _safe_int(item.get("stck_prpr", 0))
                    hg = _safe_int(item.get("new_hgpr", 0))
                    r = _safe_float(item.get("prdy_ctrt", 0))
                    n = item.get("hts_kor_isnm", "").strip()
                    c = item.get("stck_shrn_iscd", "")
                    if not n or p == 0 or hg == 0 or p < hg or c in seen:
                        continue
                    seen.add(c)
                    results["신고가"].append({
                        "종목명": n, "종목코드": c, "현재가": p,
                        "등락률": r, "부호": _sign_symbol(item.get("prdy_vrss_sign", "3")),
                        "섹터": "기타",
                    })
                time.sleep(0.35)
        except Exception:
            pass

    # 등락률 높은 순 정렬
    results["신고가"].sort(key=lambda x: x["등락률"], reverse=True)
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


def fetch_sector_investor_flow():
    """업종별 외국인/기관 순매수 — 키움 REST API (ka10051)
    시황 프롬프트에 "외국인 순매수 상위 업종" 전달용
    """
    try:
        from telegram_bot.kiwoom_client import kiwoom_post
        import datetime

        today = datetime.date.today().strftime("%Y%m%d")
        data = kiwoom_post("ka10051", {
            "mrkt_tp": "0",       # 코스피
            "amt_qty_tp": "0",    # 금액 기준
            "base_dt": today,
            "stex_tp": "1",       # KRX
        }, url_path="/api/dostk/sect")

        items = data.get("inds_netprps", [])
        results = []
        for item in items:
            name = item.get("inds_nm", "").strip()
            if not name or "종합" in name or "대형" in name or "중형" in name or "소형" in name:
                continue
            frgn = _safe_int(item.get("frgnr_netprps", "0").replace("+", "").replace(",", ""))
            orgn = _safe_int(item.get("orgn_netprps", "0").replace("+", "").replace(",", ""))
            # 부호 복원
            if item.get("frgnr_netprps", "").startswith("-"):
                frgn = -abs(frgn)
            if item.get("orgn_netprps", "").startswith("-"):
                orgn = -abs(orgn)
            results.append({"업종": name, "외국인": frgn, "기관": orgn})

        # 외국인 순매수 기준 정렬
        results.sort(key=lambda x: x["외국인"], reverse=True)
        return results
    except Exception as e:
        print(f"[KIWOOM] 업종별 수급 조회 실패: {e}")
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
        "sector_investor_flow": fetch_sector_investor_flow(),
    }
