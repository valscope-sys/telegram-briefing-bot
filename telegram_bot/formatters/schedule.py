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
    "FOMC", "금통위", "금리 결정", "CPI", "고용", "GDP", "ECB 금리", "BOJ 금리",
    "비농업", "수출입 통계", "PMI", "옵션만기", "선물옵션", "MSCI", "KOSPI200",
]

# 중요도 낮은 이벤트 (텔레그램에서 제외)
LOW_PRIORITY_KEYWORDS = [
    "Balance Sheet", "Crude Oil Stock", "API Weekly", "Continuing Jobless",
    "Philly Fed Employment", "Chinese GDP YTD", "Chinese Industrial Production YTD",
    "NBS Press Conference", "Supervisory Board", "Speaks", "발언",
    "Industrial Production (YoY)", "산업생산 (전년비)",
    "Core CPI", "CPI (MoM)", "GDP (QoQ)",
    "CFTC", "Baker Hughes", "speculative net positions",
    "StrictlyVC", "Rig Count",
]


def _clean_event_name(name):
    """이벤트명 정리 (EPS est. 제거, 불필요 텍스트 정리)"""
    # [EPS est. $0.77] 제거
    name = re.sub(r'\s*\[EPS est\.\s*\$[\d.]+\]', '', name)
    return name.strip()


def _is_high_priority(name):
    """중요 이벤트 여부"""
    return any(kw in name for kw in HIGH_PRIORITY_KEYWORDS)


def _is_low_priority(name):
    """저중요 이벤트 여부"""
    return any(kw in name for kw in LOW_PRIORITY_KEYWORDS)


def _format_schedule(title, schedule_data):
    date_str = schedule_data.get("date", "")
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    # 중요도 분류
    high = []
    normal = []
    for ev in events:
        if not isinstance(ev, dict) or "error" in ev:
            continue
        event_name = ev.get("이벤트", "").strip()
        if not event_name or event_name.replace(".", "").replace("-", "").isdigit():
            continue
        if _is_low_priority(event_name):
            continue
        if _is_high_priority(event_name):
            high.append(ev)
        else:
            normal.append(ev)

    # 중요 → 일반 순서, 최대 10건 (핵심만)
    sorted_events = high + normal
    lines = []

    for ev in sorted_events[:10]:
        time_str = ev.get("시간", "").strip()
        event_name = ev.get("이벤트", "").strip()
        country = ev.get("국가", "").strip()

        # 국가 이모지
        if country and not country.startswith(("\U0001f1e6", "\U0001f1e8", "\U0001f1ef", "\U0001f1f0", "\U0001f1fa")):
            country = COUNTRY_EMOJI.get(country, country)

        if time_str:
            lines.append(f"{time_str}(KST)  {country} {event_name}")
        else:
            lines.append(f"{country} {event_name}")

    if earnings:
        # 한국 실적 먼저, 미국 실적 나중 (한국=한글, 미국=영문)
        kr_earnings = []
        us_earnings = []
        for e in earnings:
            if not isinstance(e, dict) or not e.get("기업명"):
                continue
            name = _clean_event_name(e["기업명"])
            if any(c >= '\uac00' for c in name):  # 한글 포함
                if name not in kr_earnings:
                    kr_earnings.append(name)
            else:
                if name not in us_earnings:
                    us_earnings.append(name)
        # 한국 전부 먼저 + 미국 상위 5개
        us_clean = [_clean_event_name(n) for n in us_earnings[:5]]
        all_names = kr_earnings + us_clean
        if all_names:
            lines.append(f"실적  {', '.join(all_names)}")

    if not lines:
        lines.append("주요 일정 없음")

    lines.append("")
    lines.append(f"[전체 일정 보기]({CALENDAR_WEB_URL})")

    return f"📅 *{title}*\n{date_str}\n\n" + "\n".join(lines)


def format_today_schedule(schedule_data):
    return _format_schedule("오늘 일정", schedule_data)


def format_tomorrow_schedule(schedule_data):
    return _format_schedule("내일 일정", schedule_data)
