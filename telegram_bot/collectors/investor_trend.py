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
    """최근 N 영업일 리스트 (오늘 제외, 최신순).

    2026-09-28 fix: 평일만 거르던 로직이 KRX 공휴일을 영업일로 취급 → KIS 가 휴장일 조회에
    직전 거래일 데이터를 돌려줘 같은 날 수급이 여러 번 집계됨 (추석 9/24·25 → 9/23 값 3중 집계,
    '외국인 3거래일 연속 순매도 누적 -1.5조' 로 부풀려짐). market_calendar(공휴일·임시휴장 반영) 사용.
    """
    try:
        from telegram_bot.market_calendar import recent_business_days
        return recent_business_days(count, base_date)
    except Exception as e:
        print(f"[TREND] ERROR: market_calendar 사용 불가 — 평일 기준으로 대체: {e}")
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

    KIS FHPTJ04040000 은 요청일(FID_INPUT_DATE_1) 이전 일별 이력을 최신순으로 여러 행
    (행마다 stck_bsop_date) 돌려주므로 1회 호출 후 행의 실제 날짜로 선별 (중복·휴장일 방지).
    """
    market_sym = "KSP" if market_code == "0001" else "KSQ"
    biz_days = _prev_business_days(n_days)
    wanted = [d.strftime("%Y%m%d") for d in biz_days[:n_days]]
    if not wanted:
        print("[TREND] ERROR: 조회할 영업일 목록이 비어 있음")
        return {}

    daily_data = []
    try:
        data = kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
            "FHPTJ04040000",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": market_code,
                "FID_INPUT_DATE_1": wanted[0],
                "FID_INPUT_ISCD_1": market_sym,
                "FID_INPUT_DATE_2": wanted[0],
                "FID_INPUT_ISCD_2": market_code,
            },
        )
        items = data.get("output", [])
        if not isinstance(items, list):
            items = [items] if items else []
        seen = set()
        for row in items:
            date_str = row.get("stck_bsop_date", "")
            if date_str not in wanted or date_str in seen:
                continue
            seen.add(date_str)
            frgn = _safe_int(row.get("frgn_ntby_tr_pbmn", 0))
            inst = _safe_int(row.get("orgn_ntby_tr_pbmn", 0))
            if frgn != 0 or inst != 0:
                daily_data.append({
                    "날짜": date_str,
                    "외국인": frgn,  # 백만원 단위
                    "기관": inst,
                })
        daily_data.sort(key=lambda d: d["날짜"], reverse=True)
        if items and not seen:
            print(f"[TREND] ERROR: 수급 응답 {len(items)}행에 요청 영업일 매칭 0건 "
                  f"(stck_bsop_date 필드 변경 의심, 첫 행 keys={list(items[0])[:8]})")
    except Exception as e:
        print(f"[TREND] ERROR: 투자자 매매동향 N일 조회 실패 ({market_sym}): {e}")

    if not daily_data:
        print(f"[TREND] ERROR: 최근 {n_days}영업일 수급 데이터 없음 ({market_sym})")
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

    lines = [
        "=== 수급 트렌드 (최근 10거래일 조회 기준) ===",
        "※ 누적치는 '연속 매매 기간'의 누적입니다. 월간·전월·연간 누적은 제공되지 않으니 시황에서 그런 기간 수급을 쓰지 마세요.",
    ]

    frgn_s = trend_data.get("외국인연속", 0)
    frgn_t = trend_data.get("외국인누적", 0)
    inst_s = trend_data.get("기관연속", 0)
    inst_t = trend_data.get("기관누적", 0)

    if frgn_s > 0:
        lines.append(f"외국인: 최근 {frgn_s}거래일 연속 순매수 (그 기간 누적 {frgn_t:+,.0f}억원)")
    elif frgn_s < 0:
        lines.append(f"외국인: 최근 {abs(frgn_s)}거래일 연속 순매도 (그 기간 누적 {frgn_t:+,.0f}억원)")

    if inst_s > 0:
        lines.append(f"기관: 최근 {inst_s}거래일 연속 순매수 (그 기간 누적 {inst_t:+,.0f}억원)")
    elif inst_s < 0:
        lines.append(f"기관: 최근 {abs(inst_s)}거래일 연속 순매도 (그 기간 누적 {inst_t:+,.0f}억원)")

    # 최근 5일 일별
    daily = trend_data.get("일별데이터", [])
    if daily:
        lines.append("\n최근 5일 일별 수급 (억원):")
        for d in daily:
            frgn = d["외국인"] / 100
            inst = d["기관"] / 100
            lines.append(f"  {d['날짜']}: 외국인 {frgn:+,.0f}억 / 기관 {inst:+,.0f}억")

    return "\n".join(lines)
