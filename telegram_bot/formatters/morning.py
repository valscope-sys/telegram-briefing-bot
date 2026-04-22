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
    dom_indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})
    sentiment = global_data.get("sentiment", {})

    lines = []
    lines.append("🌐 *모닝 브리핑*")
    lines.append(f"{date_str} · 07:00 기준")
    lines.append("")

    # 📊 미국 증시
    lines.append("📊 *미국 증시*")
    for name in ["S&P 500", "NASDAQ", "DOW"]:
        d = indices.get(name, {})
        if "error" not in d and d.get("현재가"):
            lines.append(f"{name}  {d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}")
    vix = indices.get("VIX", {})
    if vix and "error" not in vix and vix.get("현재가"):
        lines.append(f"VIX  {vix['현재가']:.2f}  {_fmt_pct(vix['등락률'])}")
    lines.append("")

    # 🏷 미국 섹터 (상위3 · 하위3)
    if us_sectors:
        # 등락률 기준 정렬
        sector_list = []
        for name, data in us_sectors.items():
            if isinstance(data, dict) and "error" not in data and data.get("등락률") is not None:
                sector_list.append((name, data["등락률"]))
        if sector_list:
            sector_list.sort(key=lambda x: x[1], reverse=True)
            top3 = sector_list[:3]
            bottom3 = sector_list[-3:]
            lines.append("🏷 *미국 섹터*")
            top_str = " · ".join(f"{n} {v:+.2f}%" for n, v in top3)
            bot_str = " · ".join(f"{n} {v:+.2f}%" for n, v in bottom3)
            lines.append(f"▲ {top_str}")
            lines.append(f"▼ {bot_str}")
            lines.append("")

    # 💱 환율 · 금리
    lines.append("💱 *환율 · 금리*")
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
        diff_2y_bp = round(us_2y.get("전일대비", 0) * 100)
        diff_10y_bp = round(us_10y.get("전일대비", 0) * 100)
        if rate_2y:
            spread = round((rate_10y - rate_2y) * 100)  # 10Y-2Y (표준 리세션 시그널)
            lines.append(f"미국채 2Y {rate_2y:.2f}%({diff_2y_bp:+d}bp) / 10Y {rate_10y:.2f}%({diff_10y_bp:+d}bp)  스프레드 {spread:+d}bp")
        else:
            # 2Y 데이터 없으면 10Y만 표기
            lines.append(f"미국채 10Y {rate_10y:.2f}%({diff_10y_bp:+d}bp)")
    # 국고채
    kr_3y = bonds.get("국고채 3Y", {})
    kr_10y = bonds.get("국고채 10Y", {})
    kr_parts = []
    if kr_3y and kr_3y.get("금리"):
        diff_3y_bp = round(kr_3y.get("전일대비", 0) * 100)
        kr_parts.append(f"3Y {kr_3y['금리']:.2f}%({diff_3y_bp:+d}bp)")
    if kr_10y and kr_10y.get("금리"):
        diff_10y_bp = round(kr_10y.get("전일대비", 0) * 100)
        kr_parts.append(f"10Y {kr_10y['금리']:.2f}%({diff_10y_bp:+d}bp)")
    if kr_parts:
        lines.append(f"국고채 {' / '.join(kr_parts)}")
    lines.append("")

    # 🛢 원자재
    lines.append("🛢 *원자재*")
    commodity_unit = {"WTI": "/bbl", "금": "/oz", "구리": "/lb"}
    for name in ["WTI", "금", "구리"]:
        d = commodities.get(name, {})
        if "error" not in d and d.get("현재가"):
            unit = commodity_unit.get(name, "")
            lines.append(f"{name}  ${d['현재가']:,.2f}{unit}  {_fmt_pct(d['등락률'])}")
    lines.append("")

    # 😱 심리지표 (Fear & Greed만)
    fg = sentiment.get("Fear & Greed", {})
    if fg and fg.get("value") is not None:
        fg_val = fg["value"]
        fg_label = fg.get("label", "")
        label_str = f" ({fg_label})" if fg_label else ""
        lines.append(f"😱 *심리지표*")
        lines.append(f"Fear & Greed  {fg_val}{label_str}")
        lines.append("")

    # 🌙 야간 프록시 (KORU·EWY·코스피200 — NY close 기준, 시점 명시)
    korea_proxies = global_data.get("korea_proxies", {})
    proxy_lines = []
    koru = korea_proxies.get("KORU", {})
    if koru and "error" not in koru and koru.get("현재가"):
        proxy_lines.append(f"KORU(3x) {koru['현재가']:.2f} {_fmt_pct(koru['등락률'])}")
    ewy = korea_proxies.get("EWY", {})
    if ewy and "error" not in ewy and ewy.get("현재가"):
        proxy_lines.append(f"EWY {ewy['현재가']:.2f} {_fmt_pct(ewy['등락률'])}")
    ks200 = korea_proxies.get("코스피200", {})
    if ks200 and "error" not in ks200 and ks200.get("현재가"):
        proxy_lines.append(f"코스피200 {ks200['현재가']:.2f} {_fmt_pct(ks200['등락률'])}")
    if proxy_lines:
        lines.append("🌙 *야간 프록시* (NY close 기준)")
        lines.extend(proxy_lines)
        lines.append("")

    # 🇰🇷 전일 국내 증시 (수급 포함) — 날짜 명시
    inv_date_raw = (investors.get("날짜", "") if investors else "") or ""
    if len(inv_date_raw) == 8:
        inv_date_label = f" ({inv_date_raw[4:6]}-{inv_date_raw[6:8]} 종가)"
    else:
        inv_date_label = ""
    lines.append(f"🇰🇷 *전일 국내 증시*{inv_date_label}")
    for name in ["KOSPI", "KOSDAQ"]:
        d = dom_indices.get(name, {})
        if "error" in d:
            continue
        trade_val = d.get("거래대금", 0)
        trade_tril = trade_val / 1_000_000 if trade_val > 0 else 0
        avg_val = d.get("거래대금_20일평균", 0)
        avg_str = ""
        if avg_val > 0 and trade_val > 0:
            ratio = ((trade_val - avg_val) / avg_val) * 100
            arrow = "▲" if ratio > 0 else "▼" if ratio < 0 else ""
            avg_str = f", {arrow}{abs(ratio):.0f}% vs 20d"
        lines.append(f"{name}  {d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}  ({trade_tril:.1f}조{avg_str})")

    kospi = dom_indices.get("KOSPI", {})
    up = kospi.get("상승", 0) if kospi and "error" not in kospi else 0
    down = kospi.get("하락", 0) if kospi and "error" not in kospi else 0
    flat = kospi.get("보합", 0) if kospi and "error" not in kospi else 0
    if up + down + flat > 0:
        lines.append(f"상승 {up} · 하락 {down} · 보합 {flat}")

    # 수급 (전일 국내 증시 섹션에 합침)
    if investors and "error" not in investors:
        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)
        lines.append(f"외국인 {_fmt_inv(frgn)} · 기관 {_fmt_inv(inst)} · 개인 {_fmt_inv(pers)}")

    return "\n".join(lines).strip()
