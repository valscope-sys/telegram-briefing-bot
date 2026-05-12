"""이브닝 브리핑 메시지 생성

명세서 (2026-05-12 코드방):
- 신고가 분류 = 단일 데이터 소스 (KRX 지수/ETF 구성종목 역색인)
- theme_groups 10개 묶음 폐기
- sector_config.json 등록 순서로 직접 출력
- 한 종목이 여러 섹터 해당 시 모두 표시 (중복 허용)
- 매칭 안 되면 "기타"
"""
import datetime


def _safe_pct(value):
    if value is None:
        return "0.0%"
    try:
        v = float(value)
        return f"{v:+.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _fmt_won_eok(value):
    """원 → 억원 변환 (음수면 ▼)"""
    if value is None or value == 0:
        return "-"
    try:
        val_eok = float(value) / 100_000_000
    except (TypeError, ValueError):
        return "-"
    if val_eok >= 0:
        return f"▲ {val_eok:,.0f}억"
    return f"▼ {val_eok:,.0f}억"


def format_evening_briefing(domestic_data, global_data, commentary, sector_data, highlow_data):
    """이브닝 브리핑 메시지 생성"""
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")
    lines = [f"📊 *오늘 시장* ({date_str})\n"]

    # KOSPI / KOSDAQ
    kospi = domestic_data.get("KOSPI", {})
    kosdaq = domestic_data.get("KOSDAQ", {})
    if kospi:
        lines.append(f"🇰🇷 KOSPI {kospi.get('현재가','-')} ({_safe_pct(kospi.get('등락률'))})")
    if kosdaq:
        lines.append(f"🇰🇷 KOSDAQ {kosdaq.get('현재가','-')} ({_safe_pct(kosdaq.get('등락률'))})")
    lines.append("")

    # 수급
    inv = domestic_data.get("수급", {})
    if inv:
        for label in ["외국인", "기관", "개인"]:
            section = inv.get(label, {})
            if section:
                kospi_amt = section.get("KOSPI", 0)
                kosdaq_amt = section.get("KOSDAQ", 0)
                ks_str = _fmt_won_eok(kospi_amt)
                kq_str = _fmt_won_eok(kosdaq_amt)
                lines.append(f"📊 {label}: KOSPI {ks_str} · KOSDAQ {kq_str}")
        lines.append("")

    # 섹터 (요약)
    if sector_data:
        sect_pairs = []
        for name, info in sector_data.items():
            if isinstance(info, dict):
                rate = info.get("등락률")
                if rate is not None:
                    sect_pairs.append((name, rate))
        if sect_pairs:
            sect_pairs.sort(key=lambda x: x[1], reverse=True)
            top_str = " · ".join(f"{n} {_safe_pct(r)}" for n, r in sect_pairs[:3])
            bot_str = " · ".join(f"{n} {_safe_pct(r)}" for n, r in sect_pairs[-3:])
            lines.append(f"▲ {top_str}")
            lines.append(f"▼ {bot_str}")
            lines.append("")

    # 🔺 52주 신고가 — 단일 데이터 소스 (KRX 지수/ETF 구성종목) 역색인
    # 명세서 (2026-05-12 코드방): theme_groups 10개 묶음 폐기, sector_config.json 순서로 직접 출력
    if highlow_data:
        highs = [h for h in highlow_data.get("신고가", []) if h.get("현재가", 0) > 0]
        if highs:
            lines.append(f"🔺 *52주 신고가* ({len(highs)}종목)")
            lines.append("")

            # classify_stocks_batch: {섹터명: [종목, ...]} — 중복 허용
            from telegram_bot.collectors.sector_classifier import (
                classify_stocks_batch, get_sector_priority,
            )
            grouped = classify_stocks_batch(highs)

            # 출력 순서: sector_config.json 등록 순. '기타'는 마지막.
            order = get_sector_priority()
            seen = set()

            def _emit_sector(name, items):
                if not items:
                    return
                items.sort(key=lambda x: x.get("등락률", 0), reverse=True)
                tagged = [
                    (f"{it.get('종목명','')}(역)"
                     if it.get("신고가종류") == "역사적"
                     else it.get("종목명", ""))
                    for it in items
                ]
                names = ", ".join(tagged)
                lines.append(f"✅ *{name}* ({len(items)}종목)")
                lines.append(names)
                lines.append("")

            for name in order:
                if name == "기타":
                    continue
                items = grouped.get(name)
                if items:
                    _emit_sector(name, items)
                    seen.add(name)

            # config에 없는 새 섹터 (있다면) — 종목수 많은 순
            extras = [
                (name, items) for name, items in grouped.items()
                if name not in seen and name != "기타"
            ]
            extras.sort(key=lambda x: -len(x[1]))
            for name, items in extras:
                _emit_sector(name, items)

            # 기타 마지막
            if grouped.get("기타"):
                _emit_sector("기타", grouped["기타"])

    return "\n".join(lines).strip()
