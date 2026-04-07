"""뉴스 메시지 포맷터 (장전/장후 뉴스 메시지)"""
import datetime


DIR_EMOJI = {"긍정": "🟢", "부정": "🔴", "중립": "⚪"}

SECTOR_EMOJI = {
    "반도체": "📟",
    "반도체/메모리": "📟",
    "2차전지": "🔋",
    "2차전지/EV": "🔋",
    "바이오": "💊",
    "바이오/제약": "💊",
    "방산": "🪖",
    "에너지": "⛽",
    "원전": "☢️",
    "원전/에너지": "☢️",
    "자동차": "🚗",
    "금융": "💰",
    "건설": "🚧",
    "건설/부동산": "🚧",
    "철강": "⛏",
    "철강/소재": "⛏",
    "게임": "🎮",
    "화장품": "💄",
    "화장품/K-뷰티": "💄",
    "K뷰티": "💄",
    "조선": "🚢",
    "통신": "📡",
    "유통": "🛒",
    "유통/이커머스": "🛒",
    "이커머스": "🛒",
    "가전": "📺",
    "가전/IT": "📺",
    "빅테크": "💡",
    "빅테크/AI": "💡",
    "AI": "💡",
    "매크로": "📈",
    "매크로/환율": "📈",
    "매크로/에너지": "📈",
    "반도체/AI": "📟",
    "정책": "🏛",
    "정책/규제": "🏛",
    "부동산": "🏠",
    "미디어": "📺",
    "헬스케어": "💊",
    "로봇": "🤖",
}


def _get_sector_emoji(sector):
    """섹터명에 맞는 이모지 반환"""
    if not sector:
        return "📌"
    return SECTOR_EMOJI.get(sector, "📌")


def _format_news_list(title_prefix, news_list):
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")

    lines = []
    for i, item in enumerate(news_list[:10]):
        title = item.get("summary_title", item.get("title", ""))
        detail = item.get("detail", "")
        link = item.get("link", "")
        sector = item.get("sector", "")
        direction = item.get("direction", "")

        # 섹터 이모지 + 방향 태그
        sec_emoji = _get_sector_emoji(sector)
        dir_dot = DIR_EMOJI.get(direction, "")
        tag = f"[{sector}] {dir_dot}" if sector else ""

        # 제목 (링크 포함)
        if link:
            lines.append(f"{sec_emoji} {tag} [{title}]({link})")
        else:
            lines.append(f"{sec_emoji} {tag} {title}")

        # 상세 요약
        if detail:
            lines.append(f"   {detail}")

        lines.append("")  # 뉴스 간 빈줄

    body = "\n".join(lines).strip()
    return f"📰 *{title_prefix}*\n{date_str}\n\n{body}"


def format_premarket_news(news_list):
    """장전 뉴스 메시지"""
    return _format_news_list("장전 주요 뉴스", news_list)


def format_postmarket_news(news_list):
    """장중 주요 뉴스 메시지"""
    return _format_news_list("장중 주요 뉴스", news_list)
