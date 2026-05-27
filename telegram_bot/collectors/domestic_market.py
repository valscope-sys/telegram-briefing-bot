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
    """직전 KRX 거래일 (주말 + 한국 공휴일 + KRX 임시휴장 모두 건너뜀)."""
    from telegram_bot.market_calendar import prev_business_day
    return prev_business_day(base_date)


def _recent_business_days(count=5, base_date=None):
    """최근 N KRX 거래일 리스트 (공휴일·임시휴장 정확 반영)."""
    from telegram_bot.market_calendar import recent_business_days
    return recent_business_days(count, base_date)


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


_SECTOR_MAPPING_CACHE = None


def _load_sector_mapping():
    """stock_sector_mapping.json 로드 (lazy, 모듈 수명 동안 캐시)"""
    global _SECTOR_MAPPING_CACHE
    if _SECTOR_MAPPING_CACHE is not None:
        return _SECTOR_MAPPING_CACHE
    import json
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "history", "stock_sector_mapping.json"
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _SECTOR_MAPPING_CACHE = {k: v for k, v in data.items() if not k.startswith("_")}
        print(f"[SECTOR_MAP] 수동 매핑 {len(_SECTOR_MAPPING_CACHE)}종목 로드")
    except Exception as e:
        print(f"[SECTOR_MAP] 매핑 파일 로드 실패, Claude 폴백만 사용: {e}")
        _SECTOR_MAPPING_CACHE = {}
    return _SECTOR_MAPPING_CACHE


def _classify_themes_with_claude(stock_names):
    """Claude API로 종목명 → 투자 테마 분류 (수동 매핑 미커버 종목 폴백용)"""
    from telegram_bot.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY or not stock_names:
        return {name: "기타" for name in stock_names}

    import anthropic
    import json
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    names_str = ", ".join(stock_names)
    prompt = f"""다음 한국 주식 종목들을 투자 테마별로 분류해주세요.

종목: {names_str}

테마 예시: 반도체/메모리, 반도체장비, 반도체소재, 반도체부품, 디스플레이, 전기전자, 2차전지, 2차전지소재, 2차전지장비, 바이오/제약, 의료기기, AI/소프트웨어, 로봇, 자동차, 자동차부품, 조선, 기계, 원전/전력, 방산, 화장품/K-뷰티, 건설/재건, 부동산, 철강/소재, 금속/비철, 정유/화학, 에너지, 금융, 지주, 게임, 미디어/엔터, 음식료, 유통/소비재, 통신/5G, 통신장비, 섬유/패션, 항공/해운, 농업/사료, 기타

핵심 규칙:
- 종목의 실제 사업 내용을 정확히 알 때만 분류하세요.
- 종목명에 "반도체"가 들어있다고 반도체로 분류하지 마세요. 실제 사업을 확인하세요.
- 잘 모르는 종목은 반드시 "기타"로 분류하세요. 추측으로 반도체나 다른 테마에 넣지 마세요.
- 지주사는 주된 자회사 섹터로. 예: 솔브레인홀딩스 → 반도체소재.
- 카테고리 세분 가이드 (한국 투자 시장 시각):
  · 반도체/메모리 = 삼성전자·SK하이닉스 같은 메모리 IDM
  · 반도체부품 = OSAT(후공정·하나마이크론), PCB(심텍·코리아써키트), 패키지 자재
  · 반도체장비 = 노광·식각·증착·검사 장비 (브이엠·기가비스·HB테크놀러지)
  · 반도체소재 = 포토레지스트·CMP·솔더볼·식각액
  · 디스플레이 = LED·OLED·LCD·디스플레이장비 (라온텍·서울반도체·아바코)
  · 전기전자 = MLCC·전선·케이블·전원공급장치 (삼성전기·가온전선·KBI메탈)
  · 원전/전력 = 한전·중전기(효성중공업·LS ELECTRIC)·원전 정비·전력 케이블
  · 통신/5G = SK텔레콤·KT·LG유플러스 (이동통신 서비스)
  · 통신장비 = RFHIC·대한광통신·오이솔루션·케이엠더블유 (네트워크 장비)
  · 기계 = 건설중장비·산업기계·진성티이씨 등

⚠️ 통신과 전력은 절대 같은 카테고리 아님:
- SK텔레콤·KT = 통신/5G (전력 X)
- RFHIC·대한광통신·오이솔루션 = 통신장비 (전력 X)
- 효성중공업·LS ELECTRIC·산일전기 = 원전/전력
- 주요 오분류 사례:
  레이 = 치과의료기기 (반도체 아님)
  에이치케이 = 부동산 (반도체 아님)
  영화테크 = 자동차부품 (반도체 아님)
  케이엠더블유 = 5G통신장비 (반도체 아님, 통신장비)
  비츠로셀 = 배터리/방산 (반도체 아님)
  기가레인 = RF통신부품 (AI가 아님, 통신장비)
  가온전선/대원전선/대한전선 = 전기전자 (전력 케이블, 통신/5G 아님)
  하나마이크론 = 반도체부품 (OSAT 후공정, 메모리 아님)
  서울반도체 = 디스플레이 (LED 광반도체)
  비나텍 = 전기전자 (슈퍼캡, 2차전지 아님)
  진성티이씨 = 기계 (건설중장비 부품, 반도체 아님)
  PI첨단소재 = 2차전지소재 (PI필름, 반도체 아님)
  솔루엠 = 전기전자 (전자부품, 반도체 아님)

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


def _classify_stocks(filtered_stocks):
    """종목 리스트 → {종목코드: 섹터} 매핑 (하이브리드).

    1차: stock_sector_mapping.json (수동 큐레이션, 가장 정확)
    2차: wics_cache.json (네이버 fetch 결과 영구 캐시)
    3차: 네이버 종목 페이지 fetch (WICS → 우리 카테고리)
    4차: Claude API fallback (네이버 fetch 실패 시 종목명 추측)

    sector_classifier.classify_stocks_batch가 1~3차 처리.
    Claude fallback은 동일 모듈에서 수행.
    """
    from telegram_bot.collectors.sector_classifier import classify_stocks_batch
    code_to_sector = classify_stocks_batch(
        filtered_stocks,
        allow_fetch=True,
        allow_claude=True,
        max_fetch_per_call=30,
    )
    total = len(filtered_stocks)
    other_count = sum(1 for v in code_to_sector.values() if v == "기타")
    classified = total - other_count
    print(f"[SECTOR_MAP] 분류 {classified}/{total} ({100*classified/max(1,total):.0f}%), 기타 {other_count}")
    return code_to_sector


def fetch_new_highlow():
    """52주 신고가 종목 조회 — 키움 REST API (ka10016)
    종가기준 + 우선주제외 + 거래량 1만주 이상
    Claude API로 테마 분류
    데이터 미확정 시 60초 대기 후 재시도 (장 마감 직후 데이터 정산 지연 대응)
    휴장일에는 빈 결과 반환 (전 영업일 데이터 잘못 표시되던 버그 fix).
    """
    results = {"신고가": []}

    # 휴장일 가드 — 5/1 근로자의 날 같은 케이스에 전 영업일 데이터를 그대로
    # 가져와 "오늘자 신고가"로 표시되던 문제 차단.
    from telegram_bot.market_calendar import is_market_day
    if not is_market_day():
        print("[KIWOOM] 휴장일 — 신고가 조회 스킵")
        results["휴장일"] = True
        return results

    try:
        from telegram_bot.kiwoom_client import kiwoom_paginated

        # 키움 ka10016 — 신고가 (한 페이지 100건 limit, cont-yn=Y면 next-key로 다음 페이지)
        # 페이지네이션 자동 누적 → awakeplus 수준의 전체 신고가 cover.
        # dt=9999 (상장 이래)는 키움이 미지원 (응답 0건 확인됨) → 250(=52주)만 사용.
        def _query_kiwoom_paginated():
            return kiwoom_paginated(
                "ka10016",
                {
                    "mrkt_tp": "000",           # 전체 (코스피+코스닥)
                    "ntl_tp": "1",              # 신고가
                    "high_low_close_tp": "2",   # 종가기준
                    "stk_cnd": "3",             # 우선주제외
                    "trde_qty_tp": "00010",     # 만주이상
                    "crd_cnd": "0",             # 전체
                    "updown_incls": "0",        # 상하한 미포함
                    "dt": "250",                # 250일 = 52주
                    "stex_tp": "1",             # KRX
                },
                result_field="ntl_pric",
                max_pages=20,                   # 100*20 = 2000건 안전 limit
            )

        stocks = _query_kiwoom_paginated()
        # 모든 종목 (52주) 표기 — 키움 ka10016이 dt=9999 미지원이라 분리 불가
        for item in stocks:
            item["_high_kind"] = "52주"

        print(f"[KIWOOM] 신고가 raw {len(stocks)}건 (페이지네이션 누적)")

        # 데이터 미확정 대응: 5종목 미만이면 60초 대기 후 재시도
        if len(stocks) < 5:
            print(f"[KIWOOM] {len(stocks)}종목 — 데이터 미확정 가능, 60초 후 재시도")
            time.sleep(60)
            stocks = _query_kiwoom_paginated()
            for item in stocks:
                item["_high_kind"] = "52주"
            print(f"[KIWOOM] 재시도 결과: {len(stocks)}종목")

        # ETF/ETN/리츠/머니마켓/펀드 필터 (사용자 보고 5/13·5/27 — IBK·HK 등 누락 보강)
        exclude_kw = [
            # 운용사 브랜드 (전부 ETF 또는 펀드)
            "TIGER", "KODEX", "KBSTAR", "HANARO", "SOL", "ARIRANG", "ACE", "KOSEF",
            "BNK", "WOORI", "마이다스", "마이티", "FOCUS", "히어로즈", "WON",
            "RISE", "KIWOOM", "1Q ",
            "ITF ", "ITF", "PLUS ", "PLUS", "KoAct",
            "TIMEFOLIO", "TIME ", "TIME", "DAISHIN", "UNICORN",
            "IBK ", "IBK", "HK ", "KCGI", "한국투자", "미래에셋",
            "삼성자산", "신한자산", "신한운용", "흥국", "한화자산", "DB자산",
            "스팩", "SPAC", "리츠", "KOFR", "머니마켓",
            # 상품 키워드
            "인프라", "액티브", "파워",
            "레버리지", "인버스", "ETN", "ETF",
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
            # 거래대금 5천만원 미만 제외 (거래정지 종목은 전일 잔존 데이터라 낮음)
            # awakeplus 수준의 신고가 커버를 위해 1억 → 5천만 완화
            trade_value = price * vol
            if trade_value < 50_000_000:
                continue
            # 거래량 1만주 미만 제외 (서버 측 trde_qty_tp="00010"과 동일)
            # 기존 10만주 제한이 코스닥 중소형주 신고가 절반 이상 누락의 원인
            if vol < 10_000:
                continue
            # 등락률 정확히 0% + 소량 거래는 거래정지 의심 → 제외
            if rate == 0 and vol < 100_000:
                continue

            filtered_stocks.append({
                "종목명": name,
                "종목코드": code,
                "현재가": price,
                "등락률": rate,
                "부호": "▲" if rate > 0 else ("▼" if rate < 0 else "─"),
                "신고가종류": item.get("_high_kind", "52주"),
            })

        # ─── 신고가 종목 그대로 반환 (분류는 evening.py에서 KRX universe 역색인) ───
        # 명세서 (2026-05-12 코드방):
        # - 매핑·WICS·Claude·self_new_high·historical_max 의존 분류 모두 폐기
        # - 단일 데이터 소스 = sector_universe_*.json (KRX 지수/ETF 구성종목)
        # - 분류는 formatters/evening.py에서 classify_stocks_batch로 처리
        if filtered_stocks:
            print(f"[NEW_HIGH] {len(filtered_stocks)}종목 신고가 확보 (분류는 evening 단계)")
            for s in filtered_stocks:
                # 섹터 필드 비워둠 — evening.py가 sector_universe로 분류
                s.setdefault("신고가종류", "52주")
                results["신고가"].append(s)

    except Exception as e:
        print(f"[KIWOOM] 52주 신고가 조회 실패: {e}")
        import traceback
        traceback.print_exc()
        # 사용자 정책 (2026-05-04): 신고가 단일 소스 = 키움.
        # KIS API fallback 제거 — 이중 출처 차단.
        results["오류"] = f"키움 조회 실패: {str(e)[:200]}"

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
        # KOSPI 업종 집계 레벨은 제외 — 하위 업종과 중복 집계 방지
        # 종합/대형/중형/소형 = 시총 집계, 제조업/서비스업 = 산업 집계
        AGGREGATE_NAMES = {"제조업", "서비스업"}
        for item in items:
            name = item.get("inds_nm", "").strip()
            if not name:
                continue
            if "종합" in name or "대형" in name or "중형" in name or "소형" in name:
                continue
            if name in AGGREGATE_NAMES:
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
