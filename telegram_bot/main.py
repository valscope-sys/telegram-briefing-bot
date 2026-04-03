"""NODE Research 텔레그램 자동 브리핑 봇 - 메인 엔트리포인트"""
import sys
import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from telegram_bot.briefings import run_morning_briefing, run_evening_briefing


def is_weekday():
    """평일 여부 확인 (토/일 제외)"""
    return datetime.date.today().weekday() < 5


def morning_job():
    """모닝 브리핑 스케줄 작업"""
    if not is_weekday():
        print("[SCHEDULER] 주말 - 모닝 브리핑 스킵")
        return
    print(f"[SCHEDULER] 모닝 브리핑 실행 - {datetime.datetime.now()}")
    run_morning_briefing()


def evening_job():
    """이브닝 브리핑 스케줄 작업"""
    if not is_weekday():
        print("[SCHEDULER] 주말 - 이브닝 브리핑 스킵")
        return
    print(f"[SCHEDULER] 이브닝 브리핑 실행 - {datetime.datetime.now()}")
    run_evening_briefing()


def main():
    """메인 실행"""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "morning":
            print("=== 모닝 브리핑 수동 실행 ===")
            run_morning_briefing()
            return
        elif cmd == "evening":
            print("=== 이브닝 브리핑 수동 실행 ===")
            run_evening_briefing()
            return
        elif cmd == "test":
            print("=== 테스트 모드: 데이터 수집만 ===")
            from telegram_bot.collectors.global_market import fetch_all_global
            from telegram_bot.collectors.domestic_market import fetch_all_domestic

            print("\n--- 글로벌 데이터 ---")
            global_data = fetch_all_global()
            for category, data in global_data.items():
                print(f"\n{category}:")
                if isinstance(data, dict):
                    for key, val in data.items():
                        if not key.startswith("_"):
                            print(f"  {key}: {val}")
                elif isinstance(data, list):
                    for item in data[:3]:
                        print(f"  {item}")

            print("\n--- 국내 데이터 ---")
            domestic_data = fetch_all_domestic()
            for category, data in domestic_data.items():
                print(f"\n{category}:")
                if isinstance(data, dict):
                    for key, val in data.items():
                        print(f"  {key}: {val}")
                elif isinstance(data, list):
                    for item in data[:3]:
                        print(f"  {item}")
            return
        else:
            print(f"사용법: python -m telegram_bot.main [morning|evening|test]")
            print(f"  morning  - 모닝 브리핑 즉시 실행")
            print(f"  evening  - 이브닝 브리핑 즉시 실행")
            print(f"  test     - 데이터 수집 테스트")
            print(f"  (인자 없음) - 스케줄러 모드로 실행")
            return

    # 스케줄러 모드
    print("=" * 50)
    print("NODE Research 텔레그램 브리핑 봇")
    print("=" * 50)
    print(f"시작 시간: {datetime.datetime.now()}")
    print(f"스케줄:")
    print(f"  모닝 브리핑: 평일 07:00")
    print(f"  이브닝 브리핑: 평일 16:00")
    print("=" * 50)

    scheduler = BlockingScheduler(timezone="Asia/Seoul")

    # 모닝 브리핑: 평일 07:00
    scheduler.add_job(
        morning_job,
        CronTrigger(hour=7, minute=0, day_of_week="mon-fri"),
        id="morning_briefing",
        name="모닝 브리핑",
    )

    # 이브닝 브리핑: 평일 16:00
    scheduler.add_job(
        evening_job,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri"),
        id="evening_briefing",
        name="이브닝 브리핑",
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[SCHEDULER] 종료")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
