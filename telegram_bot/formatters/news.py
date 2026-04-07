"""뉴스 메시지 포맷터 (장전/장후 뉴스 메시지)"""
import datetime


NUM = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
DIR_EMOJI = {"긍정": "🟢", "부정": "🔴", "중립": "⚪"}


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
        num = NUM[i] if i < len(NUM) else f"{i+1}."

        # 섹터 + 방향 태그
        dir_dot = DIR_EMOJI.get(direction, "")
        tag = f"[{sector}] {dir_dot}" if sector else ""

        # 제목 (링크 포함)
        if link:
            lines.append(f"{num} {tag} [{title}]({link})")
        else:
            lines.append(f"{num} {tag} {title}")

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
