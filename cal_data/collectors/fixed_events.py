"""고정 경제 일정 (수동 관리, 연 1~2회 업데이트)"""
import datetime


FIXED_EVENTS_2026 = [
    # 통화정책
    {"date": "2026-01-28", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-03-18", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-05-06", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-06-17", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-07-29", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-09-16", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-10-28", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-12-16", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-04-16", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-05-28", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-07-16", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    # 경제지표
    {"date": "2026-04-14", "time": "21:30", "category": "경제지표", "title": "미국 CPI (3월)", "country": "🇺🇸"},
    {"date": "2026-05-13", "time": "21:30", "category": "경제지표", "title": "미국 CPI (4월)", "country": "🇺🇸"},
    {"date": "2026-06-10", "time": "21:30", "category": "경제지표", "title": "미국 CPI (5월)", "country": "🇺🇸"},
    {"date": "2026-07-15", "time": "21:30", "category": "경제지표", "title": "미국 CPI (6월)", "country": "🇺🇸"},
    {"date": "2026-04-10", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (3월)", "country": "🇺🇸"},
    {"date": "2026-05-08", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (4월)", "country": "🇺🇸"},
    {"date": "2026-06-05", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (5월)", "country": "🇺🇸"},
    {"date": "2026-04-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (3월)", "country": "🇰🇷"},
    {"date": "2026-05-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (4월)", "country": "🇰🇷"},
    {"date": "2026-04-30", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (4월)", "country": "🇨🇳"},
    {"date": "2026-05-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (5월)", "country": "🇨🇳"},
]


def get_fixed_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """고정 일정에서 날짜 범위 내 이벤트 반환"""
    results = []
    for ev in FIXED_EVENTS_2026:
        ev_date = datetime.date.fromisoformat(ev["date"])
        if from_date <= ev_date <= to_date:
            results.append({
                "date": ev["date"],
                "time": ev.get("time", ""),
                "category": ev["category"],
                "title": ev["title"],
                "source": "fixed",
                "auto": False,
                "country": ev.get("country", ""),
            })
    return results
