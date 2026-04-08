"""모닝 브리핑 메시지 포맷터 (장전 07:00 - 메시지 1/3)"""
import datetime


def _arrow(value):
    if value > 0:
        return "▲"
    elif value < 0:
        return "▼"
    return "─"


def _fmt_pct(value):
    return f"{_arrow(value)} {value:+.2f}%"


def _fmt_diff(value):
    return f"{_arrow(value)} {value:+.2f}"


def _fmt_inv(val_million):
    val_eok = val_million / 100
    if val_eok >= 0:
        return f"▲ +{val_eok:,.0f}억"
    return f"▼ {val_eok:,.0f}억"


def format_morning_briefing(global_data, domestic_data, morning_commentary=""):
    """모닝 브리핑 메시지 생성"""
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")

    indices = global_data.get("indices", {})
    fx = global_data.get("fx", {})
    bonds = global_data.get("bonds", {})
    commodities = global_data.get("commodities", {})
    us_sectors = global_data.get("us_sectors", {})
    us_stocks = global_data.get("us_stocks", {})
    dom_indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})

    lines = []
    lines.append("🌐 *모닝 브리핑*")
    lines.append(f"{date_str} · 07:00 기준")
    lines.append("")

    # 미국 증시
    lines.append("*미국 증시*")
    for name in ["S&P 500", "NASDAQ", "DOW"]:
        d = indices.get(name, {})
        if "error" not in d and d.get("현재가"):
            lines.append(f"{name}  {d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}")
    vix = indices.get("VIX", {})
    if vix and "error" not in vix and vix.get("현재가"):
        lines.append(f"VIX  {vix['현재가']:.2f}  {_fmt_pct(vix['등락률'])}")
    lines.append("")

    # 환율 · 금리
    lines.append("*환율 · 금리*")
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw and usdkrw.get("현재가"):
        lines.append(f"USD/KRW  {usdkrw['현재가']:,.1f}  {_fmt_diff(usdkrw['전일대비'])}")
    dxy = fx.get("DXY", {})
    if dxy and "error" not in dxy and dxy.get("현재가"):
        lines.append(f"DXY  {dxy['현재가']:.2f}  {_fmt_pct(dxy['등락률'])}")
    us_2y = bonds.get("미국 2Y", {})
    us_10y = bonds.get("미국 10Y", {})
    if us_10y and us_10y.get("금리"):
        rate_2y = us_2y.get("금리", 0)
        rate_10y = us_10y.get("금리", 0)
        spread = int((rate_2y - rate_10y) * 100)
        lines.append(f"미국채 2Y {rate_2y:.2f}% / 10Y {rate_10y:.2f}%  ({spread:+d}bp)")
    lines.append("")

    # 원자재
    lines.append("*원자재*")
    for name in ["WTI", "금", "구리"]:
        d = commodities.get(name, {})
        if "error" not in d and d.get("현재가"):
            lines.append(f"{name}  ${d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}")
    lines.append("")

    # 야간 프록시 (KORU, EWY)
    korea_proxies = global_data.get("korea_proxies", {})
    proxy_parts = []
    for name in ["KORU", "EWY"]:
        d = korea_proxies.get(name, {})
        if d and "error" not in d and d.get("현재가"):
            proxy_parts.append(f"{name} {d['현재가']:.2f} {_fmt_pct(d['등락률'])}")
    if proxy_parts:
        lines.append("*야간 프록시*")
        lines.append(" · ".join(proxy_parts))
        lines.append("")

    # 전일 국내 증시
    lines.append("*전일 국내 증시*")
    for name in ["KOSPI", "KOSDAQ"]:
        d = dom_indices.get(name, {})
        if "error" in d:
            continue
        trade_val = d.get("거래대금", 0)
        trade_tril = trade_val / 1_000_000 if trade_val > 0 else 0
        lines.append(f"{name}  {d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}  ({trade_tril:.1f}조)")

    kospi = dom_indices.get("KOSPI", {})
    up = kospi.get("상승", 0) if kospi and "error" not in kospi else 0
    down = kospi.get("하락", 0) if kospi and "error" not in kospi else 0
    flat = kospi.get("보합", 0) if kospi and "error" not in kospi else 0
    if up + down + flat > 0:
        lines.append(f"상승 {up} · 하락 {down} · 보합 {flat}")
    lines.append("")

    # 수급
    if investors and "error" not in investors:
        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)
        lines.append(f"외국인 {_fmt_inv(frgn)} · 기관 {_fmt_inv(inst)}")
        lines.append(f"개인 {_fmt_inv(pers)}")

    return "\n".join(lines).strip()
