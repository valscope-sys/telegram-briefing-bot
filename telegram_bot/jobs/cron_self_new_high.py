"""KRX 전 종목 252일 신고가 일괄 검사 — 매일 새벽 cron

흐름:
1. krx_listing.json에서 2,878 종목 코드 로드
2. 종목별 ka10001 호출 (rate limit 0.22s) → 약 10분
3. 250hgst_pric_dt = 오늘 종목 추출
4. self_new_high_cache.json 저장
5. 이브닝 발송 시 캐시에서 즉시 사용 (~수 ms)

장점:
- awakeplus 수준 신고가 cover (키움 ka10016 한계 우회)
- 발송 시간에 영향 없음 (캐시만 읽음)
- 매일 자동 갱신
"""
import datetime
import json
import os
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_daily_self_new_high(today_str: str = None,
                            test_limit: int = None,
                            max_items: int = 1000) -> dict:
    """KRX 종목 신고가 검사. self_new_high_cache.json 갱신.

    Args:
        today_str: YYYYMMDD. None이면 자동 (휴장일이면 직전 영업일)
        test_limit: 테스트용 — N개만 처리
        max_items: 처리할 최대 종목 수. 기본 1,000 (시총 상위, 약 22분)
                   KRX 전체 2,878은 1시간+ 걸려 16:00 cron이 16:30 발송 전 못 끝낼 위험
                   1,000으로 제한해도 awakeplus 수준 cover 가능 (대형주 위주)
    """
    from telegram_bot.market_calendar import is_market_day, prev_business_day
    from telegram_bot.collectors.self_new_high import (
        load_krx_listing, detect_new_highs, _CACHE_PATH,
    )

    today = datetime.date.today()
    if today_str:
        try:
            today = datetime.date.fromisoformat(
                f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}"
            )
        except ValueError:
            pass

    # 휴장일이면 직전 거래일로 (키움 데이터 = 직전 거래일 종가)
    if not is_market_day(today):
        today = prev_business_day(today)
    today_str = today.strftime("%Y%m%d")

    krx = load_krx_listing()
    if not krx:
        print("[CRON_SELF_HIGH] krx_listing.json 비어있음. 중단.")
        return {"ok": False, "reason": "krx_listing empty"}

    if test_limit:
        krx = krx[:test_limit]
    elif max_items and len(krx) > max_items:
        # krx_listing 순서 = 시총 상위 → 상위만 사용
        krx = krx[:max_items]

    print(f"[CRON_SELF_HIGH] {today_str} KRX {len(krx)}종목 검사 시작 (~{len(krx)*1.4/60:.1f}분)")
    started = time.time()

    candidates = [{"종목코드": it["code"], "종목명": it["name"]} for it in krx if it.get("code")]
    new_highs = detect_new_highs(
        candidates,
        today_str=today_str,
        tolerance_pct=0.0,
        max_fetch=len(candidates),
        verbose=False,
    )

    elapsed = time.time() - started
    print(f"[CRON_SELF_HIGH] 완료 — 신고가 {len(new_highs)}건, 소요 {elapsed:.0f}초")

    # 캐시 저장
    payload = {
        "today": today_str,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_checked": len(candidates),
        "elapsed_sec": round(elapsed, 1),
        "highs": new_highs,
    }
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    tmp = _CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CACHE_PATH)
    print(f"[CRON_SELF_HIGH] 캐시 저장: {_CACHE_PATH}")

    return {
        "ok": True,
        "today": today_str,
        "total": len(candidates),
        "new_highs": len(new_highs),
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    # 명령행 실행: python -m telegram_bot.jobs.cron_self_new_high [test_limit]
    test_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run_daily_self_new_high(test_limit=test_limit)
    print(f"\n결과: {result}")
