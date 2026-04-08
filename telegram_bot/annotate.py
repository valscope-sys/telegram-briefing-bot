"""데이터 의미 주석 — 원시 숫자에 맥락을 붙여서 Claude에 전달"""


def annotate_investor(investors, trend_data):
    """외국인/기관 수급에 의미 주석 추가"""
    if not investors or "error" in investors:
        return ""

    lines = []
    frgn = investors.get("외국인금액", 0) / 100
    inst = investors.get("기관금액", 0) / 100
    pers = investors.get("개인금액", 0) / 100

    # 외국인 주석
    frgn_note = f"외국인: {frgn:+,.0f}억"
    if trend_data:
        streak = trend_data.get("외국인연속", 0)
        cumul = trend_data.get("외국인누적", 0)
        if streak > 0:
            frgn_note += f" ({streak}거래일 연속 순매수, 누적 {cumul:+,.0f}억)"
        elif streak < 0:
            frgn_note += f" ({abs(streak)}거래일 연속 순매도, 누적 {cumul:+,.0f}억)"
        elif frgn > 0:
            frgn_note += " (순매수 전환)"
    lines.append(frgn_note)

    # 기관 주석
    inst_note = f"기관: {inst:+,.0f}억"
    if trend_data:
        streak = trend_data.get("기관연속", 0)
        if abs(streak) >= 2:
            direction = "순매수" if streak > 0 else "순매도"
            inst_note += f" ({abs(streak)}거래일 연속 {direction})"
    lines.append(inst_note)

    lines.append(f"개인: {pers:+,.0f}억")
    return "\n".join(lines)


def annotate_consensus(stock_name, actual, consensus):
    """실적 발표 종목 컨센 경로 주석"""
    if not actual or not consensus:
        return ""

    diff_pct = ((actual - consensus) / consensus) * 100
    if diff_pct > 0:
        return f"{stock_name}: 영업이익 {actual/10000:.1f}조원 발표 (컨센 {consensus/10000:.1f}조원 대비 {diff_pct:.0f}% 상회)"
    else:
        return f"{stock_name}: 영업이익 {actual/10000:.1f}조원 발표 (컨센 {consensus/10000:.1f}조원 대비 {abs(diff_pct):.0f}% 하회)"


def annotate_index(name, data):
    """지수에 의미 주석"""
    if not data or "error" in data:
        return ""

    price = data.get("현재가", 0)
    rate = data.get("등락률", 0)
    trade = data.get("거래대금", 0)

    note = f"{name}: {price:,.2f} ({rate:+.2f}%)"

    if abs(rate) > 3:
        note += " — 급등" if rate > 0 else " — 급락"
    if trade > 0:
        tril = trade / 1_000_000
        note += f", 거래대금 {tril:.1f}조"

    return note


def annotate_fx(usdkrw_data):
    """환율 의미 주석"""
    if not usdkrw_data or "error" in usdkrw_data:
        return ""

    price = usdkrw_data.get("현재가", 0)
    diff = usdkrw_data.get("전일대비", 0)

    note = f"USD/KRW: {price:,.1f} ({diff:+.1f}원)"

    if price < 1500:
        note += " — 1,500원 하회, 외국인 환차손 부담 완화"
    elif price > 1500:
        note += " — 1,500원대 유지, 외국인 환차손 부담 지속"

    return note


def build_annotated_summary(domestic_data, global_data, trend_data, consensus_data=None):
    """전체 데이터를 의미 주석이 달린 텍스트로 조합"""
    lines = ["=== 오늘 시장 데이터 (의미 주석 포함) ==="]

    # 지수
    indices = domestic_data.get("indices", {})
    for name in ["KOSPI", "KOSDAQ"]:
        d = indices.get(name, {})
        if d and "error" not in d:
            lines.append(annotate_index(name, d))

    lines.append("")

    # 수급
    investors = domestic_data.get("investors", {})
    inv_text = annotate_investor(investors, trend_data)
    if inv_text:
        lines.append(inv_text)
    lines.append("")

    # 환율
    fx = global_data.get("fx", {})
    usdkrw = fx.get("USD/KRW", {})
    fx_text = annotate_fx(usdkrw)
    if fx_text:
        lines.append(fx_text)

    # 원자재
    commodities = global_data.get("commodities", {})
    for name in ["WTI", "금", "구리"]:
        d = commodities.get(name, {})
        if d and "error" not in d:
            rate = d.get("등락률", 0)
            note = f"{name}: ${d['현재가']:,.2f} ({rate:+.2f}%)"
            if abs(rate) > 5:
                note += " — 급등" if rate > 0 else " — 급락"
            lines.append(note)

    lines.append("")

    # 컨센서스
    if consensus_data:
        lines.append(consensus_data)

    return "\n".join(lines)
