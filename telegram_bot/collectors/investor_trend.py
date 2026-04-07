"""외국인/기관 수급 트렌드 분석 (N일 연속 매수/매도)"""
import datetime
import time
from telegram_bot.kis_client import kis_get


def _safe_int(val, default=0):
    try:
        return int(float(val)) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _prev_business_days(count=20, base_date=None):
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


def fetch_investor_trend_ndays(market_code="0001", n_days=10):
    """
    시장별 투자자매매동향 N일 추이 조회
    → 외국인/기관 연속 매수/매도일수 + 누적금액 계산
    """
    market_sym = "KSP" if market_code == "0001" else "KSQ"
    biz_days = _prev_business_days(n_days)

    daily_data = []
    for biz_day in biz_days[:n_days]:
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
                frgn = _safe_int(latest.get("frgn_ntby_tr_pbmn", 0))
                inst = _safe_int(latest.get("orgn_ntby_tr_pbmn", 0))
                if frgn != 0 or inst != 0:
                    daily_data.append({
                        "날짜": date_str,
                        "외국인": frgn,  # 백만원 단위
                        "기관": inst,
                    })
        except Exception:
            pass
        time.sleep(0.15)

    if not daily_data:
        return {}

    # 연속 매수/매도일수 계산
    def count_consecutive(data_list, key):
        if not data_list:
            return 0, 0
        direction = 1 if data_list[0][key] > 0 else -1
        count = 0
        total = 0
        for d in data_list:
            val = d[key]
            if (direction > 0 and val > 0) or (direction < 0 and val < 0):
                count += 1
                total += val
            else:
                break
        return count * direction, total  # 양수면 N일 연속 매수, 음수면 N일 연속 매도

    frgn_streak, frgn_total = count_consecutive(daily_data, "외국인")
    inst_streak, inst_total = count_consecutive(daily_data, "기관")

    return {
        "외국인연속": frgn_streak,  # 양수: N일 연속 매수, 음수: N일 연속 매도
        "외국인누적": frgn_total / 100,  # 억원 변환
        "기관연속": inst_streak,
        "기관누적": inst_total / 100,
        "일별데이터": daily_data[:5],  # 최근 5일만
    }


def format_investor_trend_for_prompt(trend_data):
    """수급 트렌드를 시황 프롬프트용 텍스트로 변환"""
    if not trend_data:
        return ""

    lines = ["=== 수급 트렌드 ==="]

    frgn_s = trend_data.get("외국인연속", 0)
    frgn_t = trend_data.get("외국인누적", 0)
    inst_s = trend_data.get("기관연속", 0)
    inst_t = trend_data.get("기관누적", 0)

    if frgn_s > 0:
        lines.append(f"외국인: {frgn_s}거래일 연속 순매수 (누적 {frgn_t:+,.0f}억원)")
    elif frgn_s < 0:
        lines.append(f"외국인: {abs(frgn_s)}거래일 연속 순매도 (누적 {frgn_t:+,.0f}억원)")

    if inst_s > 0:
        lines.append(f"기관: {inst_s}거래일 연속 순매수 (누적 {inst_t:+,.0f}억원)")
    elif inst_s < 0:
        lines.append(f"기관: {abs(inst_s)}거래일 연속 순매도 (누적 {inst_t:+,.0f}억원)")

    # 최근 5일 일별
    daily = trend_data.get("일별데이터", [])
    if daily:
        lines.append("\n최근 5일 수급 (백만원):")
        for d in daily:
            frgn = d["외국인"] / 100
            inst = d["기관"] / 100
            lines.append(f"  {d['날짜']}: 외국인 {frgn:+,.0f}억 / 기관 {inst:+,.0f}억")

    return "\n".join(lines)
