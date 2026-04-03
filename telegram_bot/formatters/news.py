"""뉴스 메시지 포맷터 (장전/장후 뉴스 메시지)"""
import datetime


def format_premarket_news(news_list):
    """
    장전 뉴스 메시지 (07:02 발송)

    Args:
        news_list: filter_news_with_claude() 결과 (5건)
    """
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")

    lines = []
    num_symbols = ["①", "②", "③", "④", "⑤"]
    for i, item in enumerate(news_list[:5]):
        title = item.get("summary_title", item.get("title", ""))
        num = num_symbols[i] if i < len(num_symbols) else f"{i+1}."
        lines.append(f"{num} {title}")

    msg = f"""📰 *장전 주요 뉴스*
{date_str}

{chr(10).join(lines)}"""

    return msg.strip()


def format_postmarket_news(news_list):
    """
    장중 주요 뉴스 메시지 (16:02 발송)

    Args:
        news_list: filter_news_with_claude() 결과 (5건)
    """
    now = datetime.datetime.now()
    date_str = now.strftime("%m월 %d일")

    lines = []
    num_symbols = ["①", "②", "③", "④", "⑤"]
    for i, item in enumerate(news_list[:5]):
        title = item.get("summary_title", item.get("title", ""))
        num = num_symbols[i] if i < len(num_symbols) else f"{i+1}."
        lines.append(f"{num} {title}")

    msg = f"""📰 *장중 주요 뉴스*
{date_str}

{chr(10).join(lines)}"""

    return msg.strip()
