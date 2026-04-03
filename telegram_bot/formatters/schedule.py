"""일정 메시지 포맷터 (오늘 일정 / 내일 일정)"""
import datetime


def format_today_schedule(schedule_data):
    """
    오늘 일정 메시지 (07:04 발송)

    Args:
        schedule_data: fetch_today_schedule() 결과
    """
    date_str = schedule_data.get("date", datetime.date.today().strftime("%m월 %d일"))
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    lines = []
    for ev in events[:8]:
        if isinstance(ev, dict) and "error" not in ev:
            time_str = ev.get("시간", "")
            event_name = ev.get("이벤트", "")
            country = ev.get("국가", "")
            # 국가 약칭
            country_short = {"한국": "🇰🇷", "South Korea": "🇰🇷", "미국": "🇺🇸", "United States": "🇺🇸",
                           "중국": "🇨🇳", "China": "🇨🇳", "일본": "🇯🇵", "Japan": "🇯🇵"}.get(country, "")
            lines.append(f"{time_str}  {country_short} {event_name}")

    if earnings:
        earning_names = [e.get("기업명", "") for e in earnings[:5] if isinstance(e, dict)]
        if earning_names:
            lines.append(f"실적    {', '.join(earning_names)}")

    if not lines:
        lines.append("주요 일정 없음")

    msg = f"""📅 *오늘 일정*
{date_str}

{chr(10).join(lines)}"""

    return msg.strip()


def format_tomorrow_schedule(schedule_data):
    """
    내일 일정 메시지 (16:04 발송)

    Args:
        schedule_data: fetch_tomorrow_schedule() 결과
    """
    date_str = schedule_data.get("date", "")
    events = schedule_data.get("events", [])
    earnings = schedule_data.get("earnings", [])

    lines = []
    for ev in events[:8]:
        if isinstance(ev, dict) and "error" not in ev:
            time_str = ev.get("시간", "")
            event_name = ev.get("이벤트", "")
            country = ev.get("국가", "")
            country_short = {"한국": "🇰🇷", "South Korea": "🇰🇷", "미국": "🇺🇸", "United States": "🇺🇸",
                           "중국": "🇨🇳", "China": "🇨🇳", "일본": "🇯🇵", "Japan": "🇯🇵"}.get(country, "")
            lines.append(f"{time_str}  {country_short} {event_name}")

    if earnings:
        earning_names = [e.get("기업명", "") for e in earnings[:5] if isinstance(e, dict)]
        if earning_names:
            lines.append(f"실적    {', '.join(earning_names)}")

    if not lines:
        lines.append("주요 일정 없음")

    msg = f"""📅 *내일 일정*
{date_str}

{chr(10).join(lines)}"""

    return msg.strip()
