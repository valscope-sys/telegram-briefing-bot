"""일정 메시지 포맷터 (오늘 일정 / 내일 일정)"""
import datetime

COUNTRY_EMOJI = {
    "한국": "🇰🇷", "South Korea": "🇰🇷",
    "미국": "🇺🇸", "United States": "🇺🇸",
    "중국": "🇨🇳", "China": "🇨🇳",
    "일본": "🇯🇵", "Japan": "🇯🇵",
}


def _format_schedule(title, schedule_data):
    date_str = schedule_data.get("date", "")
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    lines = []
    for ev in events[:10]:
        if not isinstance(ev, dict) or "error" in ev:
            continue
        time_str = ev.get("시간", "").strip()
        event_name = ev.get("이벤트", "").strip()
        country = ev.get("국가", "").strip()

        # 빈 이벤트 또는 숫자만 있는 쓰레기 데이터 필터
        if not event_name or event_name.replace(".", "").replace("-", "").isdigit():
            continue

        # 국가 이모지 (이미 이모지면 그대로)
        if country and not country.startswith(("\U0001f1e6", "\U0001f1e8", "\U0001f1ef", "\U0001f1f0", "\U0001f1fa")):
            country = COUNTRY_EMOJI.get(country, country)

        if time_str:
            lines.append(f"{time_str}  {country} {event_name}")
        else:
            lines.append(f"{country} {event_name}")

    if earnings:
        earning_names = [e.get("기업명", "") for e in earnings[:5] if isinstance(e, dict) and e.get("기업명")]
        if earning_names:
            lines.append(f"실적  {', '.join(earning_names)}")

    if not lines:
        lines.append("주요 일정 없음")

    return f"📅 *{title}*\n{date_str}\n\n" + "\n".join(lines)


def format_today_schedule(schedule_data):
    return _format_schedule("오늘 일정", schedule_data)


def format_tomorrow_schedule(schedule_data):
    return _format_schedule("내일 일정", schedule_data)
