"""브리핑 실행 로직 (데이터 수집 → 포맷 → 발송)"""
import time
import traceback

from telegram_bot.collectors.global_market import fetch_all_global
from telegram_bot.collectors.domestic_market import fetch_all_domestic
from telegram_bot.collectors.news_collector import (
    fetch_rss_news,
    filter_news_with_claude,
    generate_market_commentary,
    generate_morning_commentary,
)
from telegram_bot.collectors.schedule_collector import (
    fetch_today_schedule,
    fetch_tomorrow_schedule,
)
from telegram_bot.formatters.morning import format_morning_briefing
from telegram_bot.formatters.evening import format_evening_briefing
from telegram_bot.formatters.news import format_premarket_news, format_postmarket_news
from telegram_bot.formatters.schedule import format_today_schedule, format_tomorrow_schedule
from telegram_bot.sender import send_message


def run_morning_briefing():
    """
    장전 브리핑 실행 (07:00)
    메시지 3개: 모닝 브리핑 → 장전 뉴스 → 오늘 일정
    """
    print("[MORNING] 모닝 브리핑 시작...")

    try:
        # 1. 모닝 브리핑 (글로벌 시황 + 전일 국내)
        print("[MORNING] 글로벌 데이터 수집 중...")
        global_data = fetch_all_global()
        print("[MORNING] 국내 데이터 수집 중...")
        domestic_data = fetch_all_domestic()

        print("[MORNING] 미장 시황 해석 생성 중...")
        raw_news = fetch_rss_news()
        morning_commentary = generate_morning_commentary(global_data, raw_news[:8])

        msg1 = format_morning_briefing(global_data, domestic_data, morning_commentary)
        send_message(msg1)
        print("[MORNING] 모닝 브리핑 발송 완료")
    except Exception as e:
        print(f"[MORNING] 모닝 브리핑 실패: {e}")
        traceback.print_exc()

    time.sleep(3)

    try:
        # 2. 장전 뉴스
        print("[MORNING] 뉴스 수집 중...")
        raw_news = fetch_rss_news()
        filtered_news = filter_news_with_claude(raw_news, count=5, context="장전 브리핑")

        msg2 = format_premarket_news(filtered_news)
        send_message(msg2)
        print("[MORNING] 장전 뉴스 발송 완료")
    except Exception as e:
        print(f"[MORNING] 장전 뉴스 실패: {e}")
        traceback.print_exc()

    time.sleep(3)

    try:
        # 3. 오늘 일정
        print("[MORNING] 일정 수집 중...")
        schedule = fetch_today_schedule()

        msg3 = format_today_schedule(schedule)
        send_message(msg3)
        print("[MORNING] 오늘 일정 발송 완료")
    except Exception as e:
        print(f"[MORNING] 오늘 일정 실패: {e}")
        traceback.print_exc()

    print("[MORNING] 모닝 브리핑 전체 완료")


def run_evening_briefing():
    """
    장후 브리핑 실행 (16:00)
    메시지 3개: 이브닝 브리핑 → 장중 뉴스 → 내일 일정
    """
    print("[EVENING] 이브닝 브리핑 시작...")

    domestic_data = {}
    global_data = {}

    try:
        # 1. 이브닝 브리핑 (당일 증시 + 시황 해석)
        print("[EVENING] 국내 데이터 수집 중...")
        domestic_data = fetch_all_domestic()
        print("[EVENING] 글로벌 데이터 수집 중...")
        global_data = fetch_all_global()

        # 뉴스 수집 (시황 해석에 필요)
        print("[EVENING] 뉴스 수집 중...")
        raw_news = fetch_rss_news()

        # Claude 시황 해석 생성
        print("[EVENING] 시황 해석 생성 중...")
        commentary = generate_market_commentary(domestic_data, raw_news)

        sector_data = domestic_data.get("sectors", {})
        highlow_data = domestic_data.get("highlow", {})

        msg1 = format_evening_briefing(
            domestic_data, global_data, commentary, sector_data, highlow_data
        )
        send_message(msg1)
        print("[EVENING] 이브닝 브리핑 발송 완료")
    except Exception as e:
        print(f"[EVENING] 이브닝 브리핑 실패: {e}")
        traceback.print_exc()

    time.sleep(3)

    try:
        # 2. 장중 주요 뉴스
        print("[EVENING] 뉴스 필터링 중...")
        raw_news = fetch_rss_news()
        filtered_news = filter_news_with_claude(
            raw_news, count=5, context="장후 브리핑, 장중 시장 영향 뉴스 위주"
        )

        msg2 = format_postmarket_news(filtered_news)
        send_message(msg2)
        print("[EVENING] 장중 뉴스 발송 완료")
    except Exception as e:
        print(f"[EVENING] 장중 뉴스 실패: {e}")
        traceback.print_exc()

    time.sleep(3)

    try:
        # 3. 내일 일정
        print("[EVENING] 내일 일정 수집 중...")
        schedule = fetch_tomorrow_schedule()

        msg3 = format_tomorrow_schedule(schedule)
        send_message(msg3)
        print("[EVENING] 내일 일정 발송 완료")
    except Exception as e:
        print(f"[EVENING] 내일 일정 실패: {e}")
        traceback.print_exc()

    print("[EVENING] 이브닝 브리핑 전체 완료")
