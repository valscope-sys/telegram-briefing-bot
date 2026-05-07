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

    indices = domestic_data.get("indices", {})
    investors = domestic_data.get("investors", {})
    program = domestic_data.get("program", {})
    fx = global_data.get("fx", {})
    commodities = global_data.get("commodities", {})
    sectors = domestic_data.get("sectors", {})

    lines = []
    lines.append("📋 *이브닝 브리핑*")
    lines.append(f"{date_str} · 16:00 기준")
    lines.append("")

    # 📊 당일 증시
    lines.append("📊 *당일 증시*")
    for name in ["KOSPI", "KOSDAQ"]:
        d = indices.get(name, {})
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

    kospi = indices.get("KOSPI", {})
    if kospi and "error" not in kospi:
        lines.append(f"상승 {kospi.get('상승', 0)} · 하락 {kospi.get('하락', 0)} · 보합 {kospi.get('보합', 0)}")
    lines.append("")

    # 💰 수급 (개인을 같은 줄로 압축)
    lines.append("💰 *수급*")
    if investors and "error" not in investors:
        frgn = investors.get("외국인금액", 0)
        inst = investors.get("기관금액", 0)
        pers = investors.get("개인금액", 0)
        lines.append(f"외국인 {_fmt_inv(frgn)} · 기관 {_fmt_inv(inst)} · 개인 {_fmt_inv(pers)}")

    if program and "error" not in program:
        pgm_val = program.get("합계순매수", 0)
        pgm_eok = pgm_val / 100
        if pgm_eok != 0:
            pgm_str = f"▲ +{pgm_eok:,.0f}억" if pgm_eok >= 0 else f"▼ {pgm_eok:,.0f}억"
            lines.append(f"프로그램 {pgm_str}")
    lines.append("")

    # 💱 환율 · 원자재
    lines.append("💱 *환율 · 원자재*")
    usdkrw = fx.get("USD/KRW", {})
    if usdkrw and "error" not in usdkrw and usdkrw.get("현재가"):
        lines.append(f"USD/KRW  {usdkrw['현재가']:,.1f}  {_fmt_diff(usdkrw['전일대비'])}")
    commodity_unit = {"WTI": "/bbl", "금": "/oz", "구리": "/lb"}
    for name in ["WTI", "금", "구리"]:
        d = commodities.get(name, {})
        if "error" not in d and d.get("현재가"):
            unit = commodity_unit.get(name, "")
            lines.append(f"{name}  ${d['현재가']:,.2f}{unit}  {_fmt_pct(d['등락률'])}")
    lines.append("")

    # 🏷 섹터 (상위3 · 하위3)
    if sectors:
        sector_list = []
        for name, data in sectors.items():
            if isinstance(data, dict) and "error" not in data and data.get("등락률") is not None:
                sector_list.append((name, data["등락률"]))
        if sector_list:
            sector_list.sort(key=lambda x: x[1], reverse=True)
            top3 = sector_list[:3]
            bottom3 = sector_list[-3:]
            lines.append("🏷 *섹터*")
            top_str = " · ".join(f"{n} {v:+.2f}%" for n, v in top3)
            bot_str = " · ".join(f"{n} {v:+.2f}%" for n, v in bottom3)
            lines.append(f"▲ {top_str}")
            lines.append(f"▼ {bot_str}")
            lines.append("")

    # 🔺 52주 신고가 — 한국 투자 테마 큰 묶음 (반도체·2차전지·전력·자동차·바이오·산업재·금융지주)
    if highlow_data:
        highs = [h for h in highlow_data.get("신고가", []) if h.get("현재가", 0) > 0]
        if highs:
            lines.append(f"🔺 *52주 신고가* ({len(highs)}종목)")

            # theme_groups.json 매핑: 21개 세분 카테고리 → 7개 큰 묶음
            sector_to_theme = _load_theme_mapping()

            # 큰 묶음별 종목 모음
            theme_groups = {}
            for item in highs:
                sector = item.get("섹터", "기타")
                theme = sector_to_theme.get(sector, "기타")
                if theme not in theme_groups:
                    theme_groups[theme] = []
                # 등락률 표시까지 같이
                theme_groups[theme].append({
                    "name": item["종목명"],
                    "rate": item.get("등락률", 0),
                    "sector": sector,
                })

            # 우선순위 정렬: 반도체·2차전지·전력·자동차·바이오·산업재·금융지주·기타
            priority = ["반도체", "2차전지", "전력/원전", "자동차", "바이오",
                        "조선/방산/산업재", "금융/지주/소비재", "기타"]
            for theme in priority:
                items = theme_groups.get(theme)
                if not items:
                    continue
                # 등락률 높은 순 정렬
                items.sort(key=lambda x: x["rate"], reverse=True)
                names = ", ".join(it["name"] for it in items)
                lines.append(f"✅ *{theme}* ({len(items)}종목)")
                lines.append(names)
                lines.append("")

            # 우선순위에 안 들어간 그룹 (있다면)
            for theme, items in theme_groups.items():
                if theme in priority:
                    continue
                items.sort(key=lambda x: x["rate"], reverse=True)
                names = ", ".join(it["name"] for it in items)
                lines.append(f"✅ *{theme}* ({len(items)}종목)")
                lines.append(names)
                lines.append("")

    return "\n".join(lines).strip()


# 메모리 캐시
_THEME_MAP_CACHE = None


def _load_theme_mapping():
    """theme_groups.json 로드 → {세분카테고리: 큰묶음} 변환."""
    global _THEME_MAP_CACHE
    if _THEME_MAP_CACHE is not None:
        return _THEME_MAP_CACHE
    import json as _json
    import os as _os
    path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "history", "theme_groups.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        groups = data.get("groups", {})
        # 큰 묶음 → 세분 카테고리 list 를 역매핑: 세분 → 큰 묶음
        result = {}
        for theme, sectors in groups.items():
            for s in sectors:
                result[s] = theme
        _THEME_MAP_CACHE = result
        return result
    except Exception as e:
        print(f"[FORMATTER] theme_groups.json 로드 실패: {e}")
        _THEME_MAP_CACHE = {}
        return {}
