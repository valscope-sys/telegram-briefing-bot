"""소넷 vs 오파스 시황 생성 → 노드리서치 채널 발송 (테스트 라벨).

실제 오늘 수집된 데이터로 양쪽 모델 시황 생성 후,
프로덕션 채널(@noderesearch)에 [테스트] 라벨과 함께 각각 발송.
구독자가 보고 구별할 수 있게 상단에 [테스트] 표기.
테스트 후 채널 관리자가 해당 메시지 삭제 가능.

비용: 모닝 기준 Sonnet ~$0.23 + Opus ~$2.08.
"""
import os
import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# v2 프롬프트 사용
os.environ.setdefault("COMMENTARY_PROMPT_VERSION", "v2")

from telegram_bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    ANTHROPIC_API_KEY,
)
from telegram_bot.sender import send_message
from telegram_bot.collectors.global_market import fetch_all_global
from telegram_bot.collectors.news_collector import (
    fetch_rss_news,
    enrich_news_bodies,
    filter_news_with_claude,
)
from telegram_bot.collectors.investor_trend import (
    fetch_investor_trend_ndays,
    format_investor_trend_for_prompt,
)
from telegram_bot.history.briefing_memory import format_previous_for_prompt
from telegram_bot.collectors.market_context import get_market_context_for_prompt
import telegram_bot.collectors.news_collector as nc


def send_channel(text, tag=""):
    """노드리서치 프로덕션 채널로 발송 (parse_mode 없음 — 시황 원문 그대로)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("[CHANNEL] 토큰/ID 없음")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        res = requests.post(url, json=payload, timeout=30)
        r = res.json()
        if not r.get("ok"):
            print(f"[CHANNEL] 실패: {r.get('description')}")
        else:
            print(f"[CHANNEL] 발송 OK {tag}")
        return r
    except Exception as e:
        print(f"[CHANNEL] 예외: {e}")
        return None


def main():
    print("=" * 60)
    print("Sonnet vs Opus 모닝 시황 비교 테스트")
    print("=" * 60)

    # 1. 글로벌 데이터
    print("[1/4] 글로벌 데이터 수집...")
    global_data = fetch_all_global()

    # 2. 뉴스 필터
    print("[2/4] 뉴스 수집 + 필터...")
    news_raw = fetch_rss_news()
    enriched = enrich_news_bodies(news_raw, max_items=10)
    filtered = filter_news_with_claude(enriched, count=8)

    # 3. 수급 트렌드 + 이전 시황 + 컨텍스트
    print("[3/4] 컨텍스트 준비...")
    trend = fetch_investor_trend_ndays()
    trend_text = format_investor_trend_for_prompt(trend)
    prev = format_previous_for_prompt("evening")
    try:
        ctx = get_market_context_for_prompt()
    except Exception:
        ctx = ""
    extra = "\n\n".join(filter(None, [trend_text, prev, ctx]))

    # 4. 양쪽 모델 호출
    print("[4/4] 모델별 호출...")

    # Sonnet
    print("  -> Sonnet 4...")
    nc.COMMENTARY_MODEL = "claude-sonnet-4-20250514"
    t0 = time.time()
    sonnet_out = nc.generate_morning_commentary(global_data, filtered, trend_text=extra)
    t_sonnet = time.time() - t0

    time.sleep(3)  # rate limit

    # Opus
    print("  -> Opus 4...")
    nc.COMMENTARY_MODEL = "claude-opus-4-20250514"
    t0 = time.time()
    opus_out = nc.generate_morning_commentary(global_data, filtered, trend_text=extra)
    t_opus = time.time() - t0

    # 파일로 항상 저장 (admin 발송 실패 대비)
    out_dir = Path(__file__).parent.parent / "telegram_bot" / "history"
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"commentary_compare_{ts}.md"
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Sonnet vs Opus 모닝 시황 비교\n\n")
        f.write(f"- 생성 시각: {ts}\n")
        f.write(f"- 데이터: 오늘 수집된 실 데이터\n\n")
        f.write(f"## Sonnet 4 ({t_sonnet:.0f}s)\n\n```\n{sonnet_out}\n```\n\n")
        f.write(f"## Opus 4 ({t_opus:.0f}s)\n\n```\n{opus_out}\n```\n")
    print(f"\n파일 저장: {out_path}")

    # 노드리서치 채널 발송 ([테스트] 라벨로 프로덕션 메시지와 구분)
    if TELEGRAM_CHANNEL_ID:
        header = "⚠️ [모델 비교 테스트] Sonnet vs Opus\n아래 두 메시지 확인 후 삭제하세요."
        send_channel(header, tag="헤더")
        time.sleep(2)
        send_channel(f"🟦 [테스트·Sonnet 4] ({t_sonnet:.0f}s)\n\n{sonnet_out}", tag="Sonnet")
        time.sleep(2)
        send_channel(f"🟣 [테스트·Opus 4] ({t_opus:.0f}s)\n\n{opus_out}", tag="Opus")
        print("노드리서치 채널 발송 완료 — 구분 후 삭제 필요.")
    else:
        print("TELEGRAM_CHANNEL_ID 미설정 — 파일로만 저장됨.")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
