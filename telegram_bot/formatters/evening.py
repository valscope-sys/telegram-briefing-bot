"""이브닝 브리핑 메시지 포맷터 (장후 16:00 - 메시지 1/3)"""
import datetime


def _fmt_change(value, is_pct=True):
    if value > 0:
        return f"▲ +{value:.2f}{'%' if is_pct else ''}"
    elif value < 0:
        return f"▼ {value:.2f}{'%' if is_pct else ''}"
    return f"─ {value:.2f}{'%' if is_pct else ''}"


def _fmt_price(value, decimals=2):
    if decimals == 0:
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def format_evening_briefing(domestic_data, global_data, commentary, sector_data, highlow_data):
    """
    이브닝 브리핑 메시지 생성

    Args:
        domestic_data: 당일 국내 시장 데이터
        global_data: 당일 글로벌 데이터 (환율/원자재)
        commentary: Claude가 생성한 시황 해석
        sector_data: 섹터별 등락률
        highlow_data: 52주 신고가/신저가
    """
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")

    indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})
    program = domestic_data.get("program", {})
    fx = global_data.get("fx", {})
    commodities = global_data.get("commodities", {})

    # 당일 증시
    idx_lines = []
    for name in ["KOSPI", "KOSDAQ"]:
        d = indices.get(name, {})
        if "error" in d:
            continue
        price = _fmt_price(d["현재가"])
        change = _fmt_change(d["등락률"])
        trade_val = d.get("거래대금", 0)
        trade_tril = trade_val / 1_000_000 if trade_val > 0 else 0
        idx_lines.append(f"{name:<8}{price:>10}   {change}  ({trade_tril:.1f}조)")

    kospi = indices.get("KOSPI", {})
    if kospi and "error" not in kospi:
        up = kospi.get("상승", 0)
        down = kospi.get("하락", 0)
        flat = kospi.get("보합", 0)
        idx_lines.append(f"상승 {up} · 하락 {down} · 보합 {flat}")

    # 수급
    inv_lines = []
    if investors and "error" not in investors:
        def fmt_inv(val):
            if val >= 0:
                return f"▲ +{abs(val):,}억"
            return f"▼ {val:,}억"

        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)
        inv_lines.append(f"외국인 {fmt_inv(frgn)} · 기관 {fmt_inv(inst)}")
        inv_lines.append(f"개인 {fmt_inv(pers)}")

    if program and "error" not in program:
        pgm_val = program.get("합계순매수", 0)
        pgm_str = f"▲ +{pgm_val:,}억" if pgm_val >= 0 else f"▼ {pgm_val:,}억"
        inv_lines.append(f"프로그램 {pgm_str}")

    # 환율 · 원자재
    fx_comm_lines = []
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw:
        fx_comm_lines.append(f"USD/KRW {_fmt_price(usdkrw['현재가'])} {_fmt_change(usdkrw['전일대비'], is_pct=False)}")

    comm_parts = []
    for name, prefix in [("WTI", "$"), ("금", "$"), ("구리", "$")]:
        d = commodities.get(name, {})
        if "error" not in d:
            comm_parts.append(f"{name} {prefix}{_fmt_price(d['현재가'])} {_fmt_change(d['등락률'])}")
    if comm_parts:
        fx_comm_lines.append(" · ".join(comm_parts))

    # 섹터 강세/약세
    sector_lines = []
    if sector_data:
        sorted_sectors = sorted(
            [(k, v) for k, v in sector_data.items() if isinstance(v, dict) and "error" not in v],
            key=lambda x: x[1].get("등락률", 0),
            reverse=True,
        )
        strong = [s for s in sorted_sectors if s[1].get("등락률", 0) > 0][:3]
        weak = [s for s in sorted_sectors if s[1].get("등락률", 0) < 0][-3:]
        weak.reverse()

        if strong:
            for name, info in strong:
                sector_lines.append(f"강세  {name} {info['등락률']:+.1f}%")
        if weak:
            for name, info in weak:
                sector_lines.append(f"약세  {name} {info['등락률']:+.1f}%")

    # 52주 신고가/신저가
    hl_lines = []
    if highlow_data:
        for item in highlow_data.get("신고가", [])[:2]:
            hl_lines.append(f"신고가  {item['종목명']} {item['현재가']:,} {_fmt_change(item['등락률'])}")
        for item in highlow_data.get("신저가", [])[:2]:
            hl_lines.append(f"신저가  {item['종목명']} {item['현재가']:,} {_fmt_change(item['등락률'])}")

    # 조합
    msg = f"""📋 *이브닝 브리핑*
{date_str} · 16:00 기준

*당일 증시*
{chr(10).join(idx_lines)}

{chr(10).join(inv_lines)}

*환율 · 원자재*
{chr(10).join(fx_comm_lines)}
"""

    if commentary:
        msg += f"\n*오늘 시장*\n{commentary}\n"

    if sector_lines:
        msg += f"\n*섹터*\n{chr(10).join(sector_lines)}\n"

    if hl_lines:
        msg += f"\n*52주*\n{chr(10).join(hl_lines)}\n"

    return msg.strip()
