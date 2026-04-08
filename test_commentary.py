"""시황 텍스트만 생성해서 출력 (텔레그램 발송 안 함)"""
import sys
import datetime

def test_morning():
    """모닝 시황만 생성"""
    print("=" * 60)
    print("[TEST] 모닝 시황 생성 시작...")
    print("=" * 60)

    from telegram_bot.collectors.global_market import fetch_all_global
    from telegram_bot.collectors.domestic_market import fetch_all_domestic
    from telegram_bot.collectors.news_collector import (
        fetch_rss_news, filter_news_with_claude, generate_morning_commentary, enrich_news_bodies,
    )
    from telegram_bot.collectors.investor_trend import (
        fetch_investor_trend_ndays, format_investor_trend_for_prompt,
    )
    from telegram_bot.history.briefing_memory import format_previous_for_prompt
    from telegram_bot.collectors.market_context import get_market_context_for_prompt
    from telegram_bot.postprocess import postprocess_commentary

    print("[1/7] 글로벌 데이터 수집...")
    global_data = fetch_all_global()

    print("[2/7] 국내 데이터 수집...")
    domestic_data = fetch_all_domestic()

    print("[3/7] 뉴스 수집 + 필터링...")
    raw_news = fetch_rss_news()
    filtered_news = filter_news_with_claude(raw_news, context="장전 브리핑")
    print(f"  RSS {len(raw_news)}건 -> 필터링 {len(filtered_news)}건")

    print("[4/7] 뉴스 본문 스크래핑...")
    filtered_news = enrich_news_bodies(filtered_news)

    print("[5/7] 수급 트렌드...")
    trend = fetch_investor_trend_ndays()
    trend_text = format_investor_trend_for_prompt(trend)

    print("[6/7] 시장 컨텍스트...")
    market_ctx = get_market_context_for_prompt()
    prev_evening = format_previous_for_prompt("evening")
    extra_context = "\n\n".join(filter(None, [trend_text, prev_evening, market_ctx]))

    print("[7/7] Claude API 시황 생성...")
    commentary = generate_morning_commentary(
        global_data, filtered_news[:8],
        trend_text=extra_context if extra_context else trend_text
    )

    # 후처리
    commentary = postprocess_commentary(commentary)

    date_str = datetime.datetime.now().strftime("%m월 %d일")
    print("\n" + "=" * 60)
    print(f"  미장 마감 리뷰 ({date_str})")
    print("=" * 60)
    print(commentary)
    print("=" * 60)
    print(f"문장 수: {len([s for s in commentary.split('.') if s.strip()])}")
    print(f"글자 수: {len(commentary)}")

    return commentary


def test_evening():
    """이브닝 시황만 생성"""
    print("=" * 60)
    print("[TEST] 이브닝 시황 생성 시작...")
    print("=" * 60)

    from telegram_bot.collectors.global_market import fetch_all_global
    from telegram_bot.collectors.domestic_market import fetch_all_domestic
    from telegram_bot.collectors.news_collector import (
        fetch_rss_news, filter_news_with_claude, generate_market_commentary, enrich_news_bodies,
    )
    from telegram_bot.collectors.intraday_collector import (
        fetch_intraday_summary, format_intraday_for_prompt,
    )
    from telegram_bot.collectors.investor_trend import (
        fetch_investor_trend_ndays, format_investor_trend_for_prompt,
    )
    from telegram_bot.history.briefing_memory import format_previous_for_prompt
    from telegram_bot.collectors.market_context import get_market_context_for_prompt
    from telegram_bot.postprocess import postprocess_commentary

    print("[1/8] 국내 데이터 수집...")
    domestic_data = fetch_all_domestic()

    print("[2/8] 글로벌 데이터 수집...")
    global_data = fetch_all_global()

    print("[3/8] 뉴스 수집 + 필터링...")
    raw_news = fetch_rss_news()
    filtered_news = filter_news_with_claude(raw_news, context="시황 분석용")
    print(f"  RSS {len(raw_news)}건 -> 필터링 {len(filtered_news)}건")

    print("[4/8] 뉴스 본문 스크래핑...")
    filtered_news = enrich_news_bodies(filtered_news)

    print("[5/8] 장중 흐름...")
    intraday = fetch_intraday_summary()
    intraday_text = format_intraday_for_prompt(intraday)

    print("[6/8] 수급 트렌드...")
    trend = fetch_investor_trend_ndays()
    trend_text = format_investor_trend_for_prompt(trend)

    # 밸류에이션
    try:
        from telegram_bot.collectors.valuation_collector import fetch_market_valuation, format_valuation_for_prompt
        val_data = fetch_market_valuation()
        val_text = format_valuation_for_prompt(val_data)
        if val_text:
            trend_text = trend_text + "\n\n" + val_text if trend_text else val_text
    except Exception:
        pass

    print("[7/8] 시장 컨텍스트...")
    market_ctx = get_market_context_for_prompt()
    prev_morning = format_previous_for_prompt("morning")
    extra_context = "\n\n".join(filter(None, [trend_text, prev_morning, market_ctx]))

    print("[8/8] Claude API 시황 생성...")
    commentary = generate_market_commentary(
        domestic_data, filtered_news,
        intraday_text=intraday_text,
        trend_text=extra_context if extra_context else trend_text,
        global_data=global_data,
    )

    # 후처리
    commentary = postprocess_commentary(commentary)

    date_str = datetime.datetime.now().strftime("%m월 %d일")
    print("\n" + "=" * 60)
    print(f"  오늘 시장 ({date_str})")
    print("=" * 60)
    print(commentary)
    print("=" * 60)
    print(f"문장 수: {len([s for s in commentary.split('.') if s.strip()])}")
    print(f"글자 수: {len(commentary)}")

    return commentary


def send_to_telegram(morning_text, evening_text):
    """확인 후 텔레그램 발송"""
    import datetime
    from telegram_bot.sender import send_message

    date_str = datetime.datetime.now().strftime("%m월 %d일")

    if morning_text:
        msg = f"\U0001f4cb *미장 마감 리뷰*\n{date_str}\n\n{morning_text}"
        send_message(msg)
        print("[SENT] 모닝 시황 발송 완료")

    if evening_text:
        import time
        if morning_text:
            time.sleep(3)
        msg = f"\U0001f4cb *오늘 시장*\n{date_str}\n\n{evening_text}"
        send_message(msg)
        print("[SENT] 이브닝 시황 발송 완료")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"

    morning_text = None
    evening_text = None

    if mode in ("morning", "both", "send"):
        morning_text = test_morning()

    if mode in ("evening", "both", "send"):
        evening_text = test_evening()

    # 결과를 파일로 저장
    with open("test_result.txt", "w", encoding="utf-8") as f:
        if morning_text:
            date_str = datetime.datetime.now().strftime("%m월 %d일")
            f.write(f"=== 미장 마감 리뷰 ({date_str}) ===\n\n")
            f.write(morning_text)
            f.write(f"\n\n[문장 수: {len([s for s in morning_text.split('.') if s.strip()])}]")
            f.write(f"\n[글자 수: {len(morning_text)}]")
            f.write("\n\n" + "=" * 60 + "\n\n")
        if evening_text:
            date_str = datetime.datetime.now().strftime("%m월 %d일")
            f.write(f"=== 오늘 시장 ({date_str}) ===\n\n")
            f.write(evening_text)
            f.write(f"\n\n[문장 수: {len([s for s in evening_text.split('.') if s.strip()])}]")
            f.write(f"\n[글자 수: {len(evening_text)}]")
    print("결과가 test_result.txt에 저장됨")

    if mode == "send":
        send_to_telegram(morning_text, evening_text)
