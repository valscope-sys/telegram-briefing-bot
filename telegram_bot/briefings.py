"""브리핑 실행 로직 (데이터 수집 → 포맷 → 발송)"""
import time
import datetime
import traceback

from telegram_bot.collectors.global_market import fetch_all_global
from telegram_bot.collectors.domestic_market import fetch_all_domestic
from telegram_bot.collectors.news_collector import (
    fetch_rss_news,
    filter_news_with_claude,
    generate_market_commentary,
    generate_morning_commentary,
    enrich_news_bodies,
)
from telegram_bot.collectors.schedule_collector import (
    fetch_today_schedule,
    fetch_tomorrow_schedule,
)
from telegram_bot.collectors.intraday_collector import (
    fetch_intraday_summary,
    format_intraday_for_prompt,
)
from telegram_bot.collectors.investor_trend import (
    fetch_investor_trend_ndays,
    format_investor_trend_for_prompt,
)
from telegram_bot.history.briefing_memory import save_briefing, format_previous_for_prompt, save_snapshot, load_snapshot
from telegram_bot.postprocess import postprocess_commentary
from telegram_bot.collectors.market_context import get_market_context_for_prompt, update_market_context
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
    raw_news = []
    filtered_news = []

    try:
        print("[MORNING] 글로벌 데이터 수집 중...")
        global_data = fetch_all_global()
        print("[MORNING] 국내 데이터 수집 중...")
        domestic_data = fetch_all_domestic()

        print("[MORNING] 뉴스 수집 중...")
        raw_news = fetch_rss_news()
        filtered_news = filter_news_with_claude(raw_news, context="장전 브리핑")

        print("[MORNING] 뉴스 본문 스크래핑 중...")
        filtered_news = enrich_news_bodies(filtered_news)

        print("[MORNING] 수급 트렌드 수집 중...")
        trend = fetch_investor_trend_ndays()
        trend_text = format_investor_trend_for_prompt(trend)

        print("[MORNING] 시장 컨텍스트 수집 중...")
        market_ctx = get_market_context_for_prompt()

        print("[MORNING] 미장 시황 생성 중...")
        prev_evening = format_previous_for_prompt("evening")
        extra_context = "\n\n".join(filter(None, [trend_text, prev_evening, market_ctx]))
        trend_text = extra_context if extra_context else trend_text
        morning_commentary = generate_morning_commentary(global_data, filtered_news[:8], trend_text=trend_text)
        save_briefing("morning", morning_commentary, {
            "KOSPI": dom_indices.get("KOSPI", {}).get("현재가", 0) if (dom_indices := domestic_data.get("indices", {})) else 0,
        })

        msg1 = format_morning_briefing(global_data, domestic_data, morning_commentary)
        snapshot_msgs = [msg1]

        send_message(msg1)
        print("[MORNING] 모닝 데이터 발송 완료")

        # 시황 별도 메시지
        commentary_msg = ""
        if morning_commentary:
            date_str = datetime.datetime.now().strftime("%m월 %d일")
            morning_commentary = postprocess_commentary(morning_commentary)
            commentary_msg = f"📋 *미장 마감 리뷰*\n{date_str}\n\n{morning_commentary}"
            time.sleep(2)
            send_message(commentary_msg)
            print("[MORNING] 미장 리뷰 발송 완료")
        snapshot_msgs.append(commentary_msg)
    except Exception as e:
        print(f"[MORNING] 모닝 브리핑 실패: {e}")
        traceback.print_exc()
        snapshot_msgs = []

    time.sleep(3)

    msg2 = ""
    try:
        print("[MORNING] 장전 뉴스 발송 중...")
        if not raw_news:
            raw_news = fetch_rss_news()
        if not filtered_news:
            filtered_news = filter_news_with_claude(raw_news, context="장전 브리핑")
        msg2 = format_premarket_news(filtered_news)
        send_message(msg2)
        print("[MORNING] 장전 뉴스 발송 완료")
    except Exception as e:
        print(f"[MORNING] 장전 뉴스 실패: {e}")
        traceback.print_exc()

    time.sleep(3)

    msg3 = ""
    try:
        print("[MORNING] 오늘 일정 수집 중...")
        schedule = fetch_today_schedule()
        msg3 = format_today_schedule(schedule)
        send_message(msg3)
        print("[MORNING] 오늘 일정 발송 완료")
    except Exception as e:
        print(f"[MORNING] 오늘 일정 실패: {e}")
        traceback.print_exc()

    # 스냅샷 저장 (재발송용)
    if snapshot_msgs:
        snapshot_msgs.extend([msg2, msg3])
        save_snapshot("morning", snapshot_msgs)

    print("[MORNING] 모닝 브리핑 전체 완료")


def run_evening_briefing():
    """
    장후 브리핑 실행 (16:00)
    메시지 3개: 이브닝 브리핑 → 장중 뉴스 → 내일 일정
    """
    print("[EVENING] 이브닝 브리핑 시작...")

    domestic_data = {}
    global_data = {}
    raw_news = []
    filtered_news = []

    try:
        # 데이터 수집
        print("[EVENING] 국내 데이터 수집 중...")
        domestic_data = fetch_all_domestic()
        print("[EVENING] 글로벌 데이터 수집 중...")
        global_data = fetch_all_global()
        print("[EVENING] 뉴스 수집 중...")
        raw_news = fetch_rss_news()
        filtered_news = filter_news_with_claude(raw_news, context="시황 분석용")

        print("[EVENING] 뉴스 본문 스크래핑 중...")
        filtered_news = enrich_news_bodies(filtered_news)

        # 추가 데이터 수집
        print("[EVENING] 장중 흐름 수집 중...")
        intraday = fetch_intraday_summary()
        intraday_text = format_intraday_for_prompt(intraday)

        print("[EVENING] 수급 트렌드 수집 중...")
        trend = fetch_investor_trend_ndays()
        trend_text = format_investor_trend_for_prompt(trend)

        # 밸류에이션
        print("[EVENING] 밸류에이션 수집 중...")
        try:
            from telegram_bot.collectors.valuation_collector import fetch_market_valuation, format_valuation_for_prompt
            val_data = fetch_market_valuation()
            val_text = format_valuation_for_prompt(val_data)
            if val_text:
                trend_text = trend_text + "\n\n" + val_text if trend_text else val_text
        except Exception:
            pass

        # 컨센서스 (오늘 실적 발표 종목이 있으면)
        consensus_text = ""
        try:
            from telegram_bot.collectors.consensus_collector import fetch_consensus
            from telegram_bot.collectors.schedule_collector import fetch_today_schedule
            today_schedule = fetch_today_schedule()
            earnings = today_schedule.get("earnings", [])
            if earnings:
                consensus_lines = ["=== 실적 컨센서스 ==="]
                for e in earnings[:3]:
                    name = e.get("기업명", "").replace("(잠정) ", "")
                    # 종목코드 매핑 (주요 대형주만)
                    code_map = {
                        "삼성전자": "005930", "SK하이닉스": "000660",
                        "LG전자": "066570", "현대차": "005380",
                        "삼성바이오": "207940", "셀트리온": "068270",
                        "NAVER": "035420", "카카오": "035720",
                        "LG에너지솔루션": "373220",
                    }
                    code = code_map.get(name)
                    if code:
                        cons = fetch_consensus(code)
                        if cons:
                            op_cons = cons.get("영업이익컨센", 0)
                            quarter = cons.get("분기", "")
                            consensus_lines.append(f"{name} {quarter}: 영업이익 컨센서스 {op_cons:,}억원")
                if len(consensus_lines) > 1:
                    consensus_text = "\n".join(consensus_lines)
        except Exception:
            pass

        # 시장 컨텍스트 + 이전 모닝 시황 참고
        market_ctx = get_market_context_for_prompt()
        prev_morning = format_previous_for_prompt("morning")
        extra_context = "\n\n".join(filter(None, [trend_text, prev_morning, market_ctx]))
        trend_text = extra_context if extra_context else trend_text

        # Claude 시황 해석 생성
        print("[EVENING] 시황 해석 생성 중...")
        commentary = generate_market_commentary(
            domestic_data, filtered_news,
            intraday_text=intraday_text,
            trend_text=trend_text,
            consensus_text=consensus_text,
            global_data=global_data,
        )
        save_briefing("evening", commentary, {
            "KOSPI": domestic_data.get("indices", {}).get("KOSPI", {}).get("현재가", 0),
            "KOSDAQ": domestic_data.get("indices", {}).get("KOSDAQ", {}).get("현재가", 0),
        })

        # 시장 컨텍스트 업데이트 (이브닝 후에만)
        print("[EVENING] 시장 컨텍스트 업데이트 중...")
        update_market_context(commentary)

        sector_data = domestic_data.get("sectors", {})
        highlow_data = domestic_data.get("highlow", {})

        msg1 = format_evening_briefing(
            domestic_data, global_data, commentary, sector_data, highlow_data
        )
        snapshot_msgs = [msg1]

        send_message(msg1)
        print("[EVENING] 이브닝 데이터 발송 완료")

        # 시황 별도 메시지
        commentary_msg = ""
        if commentary:
            date_str = datetime.datetime.now().strftime("%m월 %d일")
            commentary = postprocess_commentary(commentary)
            commentary_msg = f"📋 *오늘 시장*\n{date_str}\n\n{commentary}"
            time.sleep(2)
            send_message(commentary_msg)
            print("[EVENING] 시황 리뷰 발송 완료")
        snapshot_msgs.append(commentary_msg)
    except Exception as e:
        print(f"[EVENING] 이브닝 브리핑 실패: {e}")
        traceback.print_exc()
        snapshot_msgs = []

    time.sleep(3)

    msg2 = ""
    try:
        print("[EVENING] 장중 뉴스 필터링 중...")
        if not raw_news:
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

    msg3 = ""
    try:
        print("[EVENING] 내일 일정 수집 중...")
        schedule = fetch_tomorrow_schedule()
        msg3 = format_tomorrow_schedule(schedule)
        send_message(msg3)
        print("[EVENING] 내일 일정 발송 완료")
    except Exception as e:
        print(f"[EVENING] 내일 일정 실패: {e}")
        traceback.print_exc()

    # 스냅샷 저장 (재발송용)
    if snapshot_msgs:
        snapshot_msgs.extend([msg2, msg3])
        save_snapshot("evening", snapshot_msgs)

    print("[EVENING] 이브닝 브리핑 전체 완료")


def resend_briefing(briefing_type, date_str=None):
    """
    저장된 스냅샷을 그대로 재발송 (재생성 없음)
    - briefing_type: "morning" or "evening"
    - date_str: "2026-04-16" 형식. None이면 오늘.
    """
    snapshot = load_snapshot(briefing_type, date_str)
    if not snapshot:
        target = date_str or datetime.date.today().strftime("%Y-%m-%d")
        print(f"[RESEND] {target} {briefing_type} 스냅샷이 없습니다. 재생성 없이 종료.")
        return

    messages = snapshot.get("messages", [])
    ts = snapshot.get("timestamp", "")
    print(f"[RESEND] {snapshot['date']} {briefing_type} 스냅샷 로드 (생성: {ts})")
    print(f"[RESEND] 메시지 {len(messages)}개 재발송 시작...")

    for i, msg in enumerate(messages):
        if not msg:
            continue
        send_message(msg)
        print(f"[RESEND] 메시지 {i+1}/{len(messages)} 발송 완료")
        if i < len(messages) - 1:
            time.sleep(2)

    print(f"[RESEND] {briefing_type} 재발송 완료")
