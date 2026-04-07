"""장중 흐름 데이터 수집 (분봉, 시가-고가-저가-종가 분석)"""
import time
from telegram_bot.kis_client import kis_get


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


def fetch_index_intraday(index_code="0001"):
    """
    국내 업종 지수 장중 흐름 (시가/고가/저가/현재가)
    KIS 업종현재지수 API에서 시가/고가/저가 제공
    """
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            "FHPUP02100000",
            {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": index_code},
        )
        o = data["output"]
        close = _safe_float(o.get("bstp_nmix_prpr"))
        opn = _safe_float(o.get("bstp_nmix_oprc"))
        high = _safe_float(o.get("bstp_nmix_hgpr"))
        low = _safe_float(o.get("bstp_nmix_lwpr"))

        # 장중 흐름 판단
        if opn > 0 and close > 0:
            gap_from_open = ((close - opn) / opn) * 100
            high_from_open = ((high - opn) / opn) * 100
            low_from_open = ((low - opn) / opn) * 100
        else:
            gap_from_open = high_from_open = low_from_open = 0

        return {
            "시가": opn,
            "고가": high,
            "저가": low,
            "종가": close,
            "시가대비": round(gap_from_open, 2),
            "고점대비시가": round(high_from_open, 2),
            "저점대비시가": round(low_from_open, 2),
        }
    except Exception:
        return {}


def fetch_stock_intraday(stock_code):
    """
    개별 종목 장중 흐름 (시가/고가/저가/현재가)
    """
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code},
        )
        o = data["output"]
        close = _safe_int(o.get("stck_prpr"))
        opn = _safe_int(o.get("stck_oprc"))
        high = _safe_int(o.get("stck_hgpr"))
        low = _safe_int(o.get("stck_lwpr"))
        prev = _safe_int(o.get("stck_sdpr"))  # 기준가

        return {
            "시가": opn,
            "고가": high,
            "저가": low,
            "종가": close,
            "기준가": prev,
        }
    except Exception:
        return {}


def fetch_foreign_ownership(stock_code):
    """외국인 소진율 (지분율) 조회"""
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code},
        )
        o = data["output"]
        return _safe_float(o.get("hts_frgn_ehrt", 0))
    except Exception:
        return 0


def fetch_intraday_summary():
    """장중 흐름 요약 데이터 수집"""
    result = {}

    # KOSPI / KOSDAQ 장중 흐름
    for name, code in [("KOSPI", "0001"), ("KOSDAQ", "1001")]:
        result[name] = fetch_index_intraday(code)
        time.sleep(0.1)

    # 주요 종목 장중 흐름
    major_stocks = [
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
        ("LG에너지솔루션", "373220"),
        ("현대차", "005380"),
        ("셀트리온", "068270"),
    ]
    stocks = {}
    for name, code in major_stocks:
        stocks[name] = fetch_stock_intraday(code)
        time.sleep(0.05)
    result["주요종목"] = stocks

    # 외국인 지분율 (핵심 종목)
    frgn_ownership = {}
    for name, code in [("삼성전자", "005930"), ("SK하이닉스", "000660")]:
        frgn_ownership[name] = fetch_foreign_ownership(code)
        time.sleep(0.05)
    result["외국인지분율"] = frgn_ownership

    return result


def format_intraday_for_prompt(intraday_data):
    """장중 흐름 데이터를 시황 프롬프트용 텍스트로 변환"""
    lines = ["=== 장중 흐름 ==="]

    for name in ["KOSPI", "KOSDAQ"]:
        d = intraday_data.get(name, {})
        if d:
            opn = d.get("시가", 0)
            high = d.get("고가", 0)
            low = d.get("저가", 0)
            close = d.get("종가", 0)
            gap = d.get("시가대비", 0)

            if opn > 0:
                if gap > 0.3:
                    flow = "장초 강세 출발 후 상승 유지"
                elif gap < -0.3:
                    flow = "장초 강세 출발 후 상승분 반납" if close < opn and opn > low else "장중 하락 전환"
                else:
                    flow = "장초 대비 보합권 마감"

                # 고점-저점 시간대 판단은 분봉 없이도 가능
                high_gap = ((high - opn) / opn * 100) if opn > 0 else 0
                low_gap = ((low - opn) / opn * 100) if opn > 0 else 0

                lines.append(f"{name}: 시가 {opn:.2f} → 고가 {high:.2f}(시가 대비 {high_gap:+.2f}%) → 저가 {low:.2f}(시가 대비 {low_gap:+.2f}%) → 종가 {close:.2f}")

    stocks = intraday_data.get("주요종목", {})
    if stocks:
        lines.append("\n주요 종목 장중 흐름:")
        for name, d in stocks.items():
            if d and d.get("시가"):
                opn = d["시가"]
                high = d["고가"]
                low = d["저가"]
                close = d["종가"]
                prev = d.get("기준가", opn)
                open_chg = ((opn - prev) / prev * 100) if prev > 0 else 0
                close_chg = ((close - prev) / prev * 100) if prev > 0 else 0
                lines.append(f"  {name}: 시가 {opn:,}({open_chg:+.1f}%) → 종가 {close:,}({close_chg:+.1f}%) | 고가 {high:,} / 저가 {low:,}")

    # 외국인 지분율
    frgn = intraday_data.get("외국인지분율", {})
    if frgn:
        lines.append("\n외국인 지분율:")
        for name, rate in frgn.items():
            if rate > 0:
                lines.append(f"  {name}: {rate:.1f}%")

    return "\n".join(lines)
