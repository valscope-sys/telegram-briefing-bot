"""NODE Research 텔레그램 자동 브리핑 봇 - 메인 엔트리포인트"""
import sys
import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from telegram_bot.briefings import run_morning_briefing, run_evening_briefing, resend_briefing

KST = pytz.timezone("Asia/Seoul")


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
            # 장중(09:00~15:30) 실행 시 스냅샷 존재하면 경고
            from telegram_bot.history.briefing_memory import load_snapshot
            now = datetime.datetime.now()
            is_market_hours = 9 <= now.hour < 16
            snapshot = load_snapshot("morning")
            if is_market_hours and snapshot and "--force" not in sys.argv:
                print(f"⚠️  장중 재실행 감지! 오늘 모닝 스냅샷이 이미 있습니다 ({snapshot['timestamp']})")
                print(f"   재발송: python -m telegram_bot.main resend morning")
                print(f"   강제 재생성: python -m telegram_bot.main morning --force")
                return
            print("=== 모닝 브리핑 수동 실행 ===")
            run_morning_briefing()
            return
        elif cmd == "evening":
            print("=== 이브닝 브리핑 수동 실행 ===")
            run_evening_briefing()
            return
        elif cmd == "resend":
            if len(sys.argv) < 3:
                print("사용법: python -m telegram_bot.main resend [morning|evening] [날짜(선택)]")
                return
            btype = sys.argv[2]
            date_arg = sys.argv[3] if len(sys.argv) > 3 else None
            print(f"=== {btype} 브리핑 재발송 (스냅샷) ===")
            resend_briefing(btype, date_arg)
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
            print(f"사용법: python -m telegram_bot.main [morning|evening|resend|test]")
            print(f"  morning  - 모닝 브리핑 즉시 실행")
            print(f"  evening  - 이브닝 브리핑 즉시 실행")
            print(f"  resend morning [날짜] - 스냅샷 재발송 (재생성 없음)")
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

    scheduler = BlockingScheduler(timezone=KST)

    # misfire_grace_time: 재시작 후 15분 이내면 놓친 스케줄 보충 실행
    # deploy.sh가 코드 pull 후 재시작해도 스케줄이 누락되지 않음
    GRACE = 900  # 15분

    # 모닝 브리핑: 평일 07:00 KST
    scheduler.add_job(
        morning_job,
        CronTrigger(hour=7, minute=0, day_of_week="mon-fri", timezone=KST),
        id="morning_briefing",
        name="모닝 브리핑",
        misfire_grace_time=GRACE,
    )

    # 이브닝 브리핑: 평일 16:00 KST
    scheduler.add_job(
        evening_job,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri", timezone=KST),
        id="evening_briefing",
        name="이브닝 브리핑",
        misfire_grace_time=GRACE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[SCHEDULER] 종료")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
