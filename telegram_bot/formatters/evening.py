"""이브닝 브리핑 메시지 포맷터 (장후 16:00 - 메시지 1/3)"""
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
    """수급 금액 포맷 (백만원 → 억원 변환)"""
    val_eok = val_million / 100
    if val_eok >= 0:
        return f"▲ +{val_eok:,.0f}억"
    return f"▼ {val_eok:,.0f}억"


def format_evening_briefing(domestic_data, global_data, commentary, sector_data, highlow_data):
    """이브닝 브리핑 메시지 생성"""
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")
    sector_stocks = domestic_data.get("sector_stocks", {})

    indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})
    program = domestic_data.get("program", {})
    fx = global_data.get("fx", {})
    commodities = global_data.get("commodities", {})

    lines = []
    lines.append("📋 *이브닝 브리핑*")
    lines.append(f"{date_str} · 16:00 기준")
    lines.append("")

    # 당일 증시
    lines.append("*당일 증시*")
    for name in ["KOSPI", "KOSDAQ"]:
        d = indices.get(name, {})
        if "error" in d:
            continue
        trade_val = d.get("거래대금", 0)
        trade_tril = trade_val / 1_000_000 if trade_val > 0 else 0
        lines.append(f"{name}  {d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}  ({trade_tril:.1f}조)")

    kospi = indices.get("KOSPI", {})
    if kospi and "error" not in kospi:
        lines.append(f"상승 {kospi.get('상승', 0)} · 하락 {kospi.get('하락', 0)} · 보합 {kospi.get('보합', 0)}")
    lines.append("")

    # 수급
    if investors and "error" not in investors:
        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)
        lines.append(f"외국인 {_fmt_inv(frgn)} · 기관 {_fmt_inv(inst)}")
        lines.append(f"개인 {_fmt_inv(pers)}")

    if program and "error" not in program:
        pgm_val = program.get("합계순매수", 0)
        pgm_eok = pgm_val / 100
        if pgm_eok != 0:
            pgm_str = f"▲ +{pgm_eok:,.0f}억" if pgm_eok >= 0 else f"▼ {pgm_eok:,.0f}억"
            lines.append(f"프로그램 {pgm_str}")
    lines.append("")

    # 환율 · 원자재
    lines.append("*환율 · 원자재*")
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw and usdkrw.get("현재가"):
        lines.append(f"USD/KRW  {usdkrw['현재가']:,.1f}  {_fmt_diff(usdkrw['전일대비'])}")
    for name in ["WTI", "금", "구리"]:
        d = commodities.get(name, {})
        if "error" not in d and d.get("현재가"):
            lines.append(f"{name}  ${d['현재가']:,.2f}  {_fmt_pct(d['등락률'])}")
    lines.append("")

    # 시황 해석
    if commentary:
        lines.append("*오늘 시장*")
        lines.append(commentary)
        lines.append("")

    # 섹터 강세/약세
    if sector_data:
        sorted_sectors = sorted(
            [(k, v) for k, v in sector_data.items()
             if isinstance(v, dict) and "error" not in v and v.get("등락률", 0) != 0],
            key=lambda x: x[1]["등락률"],
            reverse=True,
        )
        strong = [s for s in sorted_sectors if s[1]["등락률"] > 0.3][:3]
        weak = [s for s in sorted_sectors if s[1]["등락률"] < -0.3]
        weak = weak[-3:] if len(weak) > 3 else weak
        weak.reverse()

        if strong or weak:
            lines.append("*섹터*")
            for name, info in strong:
                stocks = sector_stocks.get(name, [])
                stock_str = ", ".join([f"{s['종목명']} {s['등락률']:+.1f}%" for s in stocks]) if stocks else ""
                lines.append(f"강세  {name} {info['등락률']:+.1f}%")
                if stock_str:
                    lines.append(f"   └ {stock_str}")
            for name, info in weak:
                stocks = sector_stocks.get(name, [])
                stock_str = ", ".join([f"{s['종목명']} {s['등락률']:+.1f}%" for s in stocks]) if stocks else ""
                lines.append(f"약세  {name} {info['등락률']:+.1f}%")
                if stock_str:
                    lines.append(f"   └ {stock_str}")
            lines.append("")

    # 52주 신고가/신저가 (등락률 0%인 항목은 제외)
    if highlow_data:
        highs = [h for h in highlow_data.get("신고가", [])[:5] if h.get("등락률", 0) != 0][:2]
        lows = [l for l in highlow_data.get("신저가", [])[:5] if l.get("등락률", 0) != 0][:2]
        if highs or lows:
            lines.append("*52주*")
            for item in highs:
                lines.append(f"신고가  {item['종목명']} {item['현재가']:,}  {_fmt_pct(item['등락률'])}")
            for item in lows:
                lines.append(f"신저가  {item['종목명']} {item['현재가']:,}  {_fmt_pct(item['등락률'])}")

    return "\n".join(lines).strip()
