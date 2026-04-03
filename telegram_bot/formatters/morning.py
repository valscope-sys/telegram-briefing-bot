"""모닝 브리핑 메시지 포맷터 (장전 07:00 - 메시지 1/3)"""
import datetime


def _fmt_change(value, is_pct=True, prefix=""):
    """등락 포맷: ▲ +1.23% 또는 ▼ -0.45"""
    if value > 0:
        sign = "▲"
        fmt = f"+{value:.2f}{'%' if is_pct else ''}"
    elif value < 0:
        sign = "▼"
        fmt = f"{value:.2f}{'%' if is_pct else ''}"
    else:
        sign = "─"
        fmt = f"{value:.2f}{'%' if is_pct else ''}"
    return f"{sign} {prefix}{fmt}"


def _fmt_price(value, decimals=2):
    """가격 포맷 (천단위 콤마)"""
    if decimals == 0:
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def format_morning_briefing(global_data, domestic_data):
    """
    모닝 브리핑 메시지 생성 (글로벌 시황 + 전일 국내)

    Args:
        global_data: fetch_all_global() 결과
        domestic_data: fetch_all_domestic() 결과
    """
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")
    time_str = "07:00"

    indices = global_data.get("indices", {})
    fx = global_data.get("fx", {})
    bonds = global_data.get("bonds", {})
    commodities = global_data.get("commodities", {})
    dom_indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})

    # 미국 증시
    us_lines = []
    for name in ["S&P 500", "NASDAQ", "DOW"]:
        d = indices.get(name, {})
        if "error" in d:
            continue
        price = _fmt_price(d["현재가"])
        change = _fmt_change(d["등락률"])
        us_lines.append(f"{name:<12}{price:>12}   {change}")
    vix = indices.get("VIX", {})
    if vix and "error" not in vix:
        us_lines.append(f"{'VIX':<12}{_fmt_price(vix['현재가']):>12}")

    # 환율 · 금리
    fx_lines = []
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw:
        fx_lines.append(f"USD/KRW   {_fmt_price(usdkrw['현재가'])}   {_fmt_change(usdkrw['전일대비'], is_pct=False)}")
    dxy = fx.get("DXY", {})
    if dxy and "error" not in dxy:
        fx_lines.append(f"DXY         {_fmt_price(dxy['현재가'])}   {_fmt_change(dxy['등락률'])}")

    # 미 국채 금리
    us_2y = bonds.get("미국 2Y", {})
    us_10y = bonds.get("미국 10Y", {})
    if us_2y and us_10y and "이름" in us_10y:
        rate_2y = us_2y.get("금리", 0)
        rate_10y = us_10y.get("금리", 0)
        spread = int((rate_2y - rate_10y) * 100)
        fx_lines.append(f"미 국채 2Y {rate_2y:.2f}%  /  10Y {rate_10y:.2f}%  ({spread:+d}bp)")

    # 원자재
    comm_lines = []
    for name, prefix in [("WTI", "$"), ("금", "$"), ("구리", "$")]:
        d = commodities.get(name, {})
        if "error" in d:
            continue
        price = _fmt_price(d["현재가"])
        change = _fmt_change(d["등락률"])
        comm_lines.append(f"{name:<6}  {prefix}{price}   {change}")

    # 전일 국내 증시
    dom_lines = []
    for name in ["KOSPI", "KOSDAQ"]:
        d = dom_indices.get(name, {})
        if "error" in d:
            continue
        price = _fmt_price(d["현재가"])
        change = _fmt_change(d["등락률"])
        trade_val = d.get("거래대금", 0)
        # 거래대금을 조 단위로 변환 (백만원 → 조)
        trade_tril = trade_val / 1_000_000 if trade_val > 0 else 0
        dom_lines.append(f"{name:<8}{price:>10}   {change}  ({trade_tril:.1f}조)")

    # 상승/하락/보합
    kospi = dom_indices.get("KOSPI", {})
    if kospi and "error" not in kospi:
        up = kospi.get("상승", 0)
        down = kospi.get("하락", 0)
        flat = kospi.get("보합", 0)
        dom_lines.append(f"상승 {up} · 하락 {down} · 보합 {flat}")

    # 수급
    inv_lines = []
    if investors and "error" not in investors:
        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)

        def fmt_inv(val):
            if val >= 0:
                return f"▲ +{abs(val):,}억"
            return f"▼ {val:,}억"

        inv_lines.append(f"외국인 {fmt_inv(frgn)} · 기관 {fmt_inv(inst)}")
        inv_lines.append(f"개인 {fmt_inv(pers)}")

    # 조합
    msg = f"""🌐 *모닝 브리핑*
{date_str} · {time_str} 기준

*미국 증시*
{chr(10).join(us_lines)}

*환율 · 금리*
{chr(10).join(fx_lines)}

*원자재*
{chr(10).join(comm_lines)}

*전일 국내 증시*
{chr(10).join(dom_lines)}
"""

    if inv_lines:
        msg += "\n" + "\n".join(inv_lines) + "\n"

    return msg.strip()
