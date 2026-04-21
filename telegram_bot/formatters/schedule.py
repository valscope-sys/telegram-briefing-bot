"""일정 메시지 포맷터 (오늘 일정 / 내일 일정)"""
import datetime
import re

CALENDAR_WEB_URL = "https://valscope-sys.github.io/telegram-briefing-bot/"

COUNTRY_EMOJI = {
    "한국": "🇰🇷", "South Korea": "🇰🇷",
    "미국": "🇺🇸", "United States": "🇺🇸",
    "중국": "🇨🇳", "China": "🇨🇳",
    "일본": "🇯🇵", "Japan": "🇯🇵",
}

# 중요도 높은 이벤트 (상단 배치)
HIGH_PRIORITY_KEYWORDS = [
    "FOMC", "금통위", "금리 결정",
    "GDP (전년비)", "GDP (YoY)",
    "소비자물가 (전년비)", "CPI (YoY)",
    "ECB 금리", "BOJ 금리", "비농업", "수출입 통계", "PMI",
    "옵션만기", "선물옵션", "MSCI", "KOSPI200",
    "산업생산", "Industrial Production", "실업률", "Unemployment Rate",
    "무역수지", "Trade Balance", "수출 (전년비)", "Exports (YoY)",
    "Powell", "파월", "Chair",  # 의장 발언은 중요
]

# 중요도 낮은 이벤트 (텔레그램에서 제외)
LOW_PRIORITY_KEYWORDS = [
    "Balance Sheet", "Crude Oil Stock", "API Weekly", "Continuing Jobless",
    "Philly Fed Employment", "Chinese GDP YTD", "Chinese Industrial Production YTD",
    "NBS Press Conference", "Supervisory Board",
    "Core CPI", "CPI (MoM)", "GDP (QoQ)",
    "근원 소비자물가", "소비자물가 (전월비)", "GDP (전분기비)",
    "연속 실업수당", "고정자산투자",
    "CFTC", "Baker Hughes", "speculative net positions",
    "StrictlyVC", "Rig Count",
    # 일반 발언은 제외하되 의장급은 HIGH에서 잡힘
    "Speaks", "발언",
]


def _clean_event_name(name):
    """이벤트명 정리 (EPS est. 제거, 불필요 텍스트 정리)"""
    # [EPS est. $0.77] 또는 [EPS est. $-0.5] 제거 (음수 EPS 포함)
    name = re.sub(r'\s*\[EPS est\.\s*\$-?[\d.]+\]', '', name)
    return name.strip()


# 미국 실적 세션 → KST 대략 시간대 힌트
SESSION_KST_HINT = {
    "장전": "밤",      # US pre-market ~7am ET ≈ KST 20-22시
    "장후": "새벽",    # US after-hours ~4pm+ ET ≈ KST 05-06시 익일
}


def _parse_us_earning(entry):
    """US 실적 entry에서 ticker/session 추출. 예: 'GE 실적발표 (장전) [EPS est. $1.6]' → ('GE', '장전')"""
    raw = _clean_event_name(entry.get("기업명", "") or entry.get("보고서명", ""))
    m = re.match(r'^(.+?)\s*실적발표\s*\(([^)]+)\)\s*$', raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw.replace(' 실적발표', '').strip(), None


def _is_us_earning(entry):
    """미국 실적 여부 판별 (Finnhub은 보고서명에 '(장전)'/'(장후)' 포함)"""
    report = entry.get("보고서명", "") or ""
    return "(장전)" in report or "(장후)" in report


def _is_high_priority(name):
    """중요 이벤트 여부"""
    # 근원(Core) 지표는 파생 → HIGH 아님
    if "근원" in name or "Core " in name:
        return False
    # 일반 위원 발언은 HIGH 아님 (의장급만 HIGH)
    if ("Speaks" in name or "발언" in name) and not any(k in name for k in ["Powell", "파월", "Chair"]):
        return False
    return any(kw in name for kw in HIGH_PRIORITY_KEYWORDS)


def _is_low_priority(name):
    """저중요 이벤트 여부 (단, HIGH_PRIORITY에 해당하면 제외 안 함)"""
    if _is_high_priority(name):
        return False
    return any(kw in name for kw in LOW_PRIORITY_KEYWORDS)


def _format_schedule(title, schedule_data):
    date_str = schedule_data.get("date", "")
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    # 저중요 필터링
    filtered = []
    for ev in events:
        if not isinstance(ev, dict) or "error" in ev:
            continue
        event_name = ev.get("이벤트", "").strip()
        if not event_name or event_name.replace(".", "").replace("-", "").isdigit():
            continue
        if _is_low_priority(event_name):
            continue
        filtered.append(ev)

    # 전체 시간순 정렬 (중요 이벤트는 ★ 표시로 구분)
    _time_key = lambda ev: ev.get("시간", "") or "99:99"
    filtered.sort(key=_time_key)
    lines = []

    for ev in filtered[:10]:
        time_str = ev.get("시간", "").strip()
        event_name = ev.get("이벤트", "").strip()
        country = ev.get("국가", "").strip()

        # 국가 이모지
        if country and not country.startswith(("\U0001f1e6", "\U0001f1e8", "\U0001f1ef", "\U0001f1f0", "\U0001f1fa")):
            country = COUNTRY_EMOJI.get(country, country)

        # 중요 이벤트 ★ 표시
        marker = "★ " if _is_high_priority(event_name) else ""
        if time_str:
            lines.append(f"{time_str}(KST)  {marker}{country} {event_name}")
        else:
            lines.append(f"{marker}{country} {event_name}")

    # 실적 발표 — 국내/해외 분리 블록
    if earnings:
        kr_official = []   # 한국 확정 실적
        kr_provisional = []  # 한국 잠정 실적
        us_by_session = {}   # {"장전": [...], "장후": [...]}

        for e in earnings:
            if not isinstance(e, dict) or not e.get("기업명"):
                continue

            if _is_us_earning(e):
                company, session = _parse_us_earning(e)
                if not company:
                    continue
                bucket = us_by_session.setdefault(session or "기타", [])
                if company not in bucket:
                    bucket.append(company)
            else:
                # 한국 실적 (확정/잠정)
                name = _clean_event_name(e["기업명"])
                report = e.get("보고서명", "") or ""
                is_prov = "잠정" in report
                target = kr_provisional if is_prov else kr_official
                if name not in target and name not in kr_official and name not in kr_provisional:
                    target.append(name)

        earnings_lines = []
        if kr_official or kr_provisional:
            parts = []
            if kr_official:
                parts.extend(kr_official)
            if kr_provisional:
                parts.extend([f"{n} (잠정)" for n in kr_provisional])
            earnings_lines.append(f"🇰🇷 국내  {', '.join(parts)}")

        for session in ["장전", "장후", "기타"]:
            companies = us_by_session.get(session, [])
            if not companies:
                continue
            hint = SESSION_KST_HINT.get(session)
            if hint:
                label = f" ({session}·KST {hint})"
            elif session != "기타":
                label = f" ({session})"
            else:
                label = ""
            earnings_lines.append(f"🇺🇸 해외{label}  {', '.join(companies[:6])}")

        if earnings_lines:
            lines.append("")
            lines.append("📊 *실적발표*")
            lines.extend(earnings_lines)

    if not lines:
        lines.append("주요 일정 없음")

    lines.append("")
    lines.append(f"[전체 일정 보기]({CALENDAR_WEB_URL})")

    return f"📅 *{title}*\n{date_str}\n\n" + "\n".join(lines)


def format_today_schedule(schedule_data):
    return _format_schedule("오늘 일정", schedule_data)


def format_tomorrow_schedule(schedule_data):
    return _format_schedule("내일 일정", schedule_data)
