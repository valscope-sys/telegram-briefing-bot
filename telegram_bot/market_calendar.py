"""한국 KRX 휴장일 캘린더

기존 `is_weekday()`는 토/일만 제외 → 5/1 근로자의 날, 5/5 어린이날, 6/3 선거일 등에
시황 강제 발송되던 버그. 이 모듈로 교체.

데이터 소스:
- holidays.KR() — 한국 공식 공휴일 (어린이날, 부처님오신날, 추석, 광복절 등)
- krx_extra_holidays.json — 근로자의 날 5/1, 폐장일 12/31, 임시휴장 (KRX 정책)
- not_holiday — 제헌절 등 holidays는 잡지만 KRX 휴장 아닌 날 보정

사용:
    from telegram_bot.market_calendar import is_market_day, prev_business_day
    is_market_day()                    # 오늘 한국 증시 거래일 여부
    is_market_day(date(2026, 5, 1))    # False (근로자의 날)
    prev_business_day()                # 직전 거래일
    recent_business_days(5)            # 최근 5거래일 리스트
"""
import datetime
import json
import os
import threading
from typing import Optional

try:
    import holidays
    _holidays_pkg_available = True
except ImportError:
    _holidays_pkg_available = False
    holidays = None


_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "history",
)
_EXTRA_PATH = os.path.join(_HISTORY_DIR, "krx_extra_holidays.json")

_lock = threading.Lock()
_extra_holidays = None  # set of date
_not_holiday = None     # set of date (제외)
_kr_holidays_cache = {}  # year → holidays.KR(years=[year])


def _load_extra():
    """krx_extra_holidays.json 로드 (1회 캐시)."""
    global _extra_holidays, _not_holiday
    if _extra_holidays is not None:
        return
    extra = set()
    not_h = set()
    if os.path.exists(_EXTRA_PATH):
        try:
            with open(_EXTRA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for s in data.get("extra", []):
                try:
                    extra.add(datetime.date.fromisoformat(s))
                except ValueError:
                    pass
            for s in data.get("not_holiday", []):
                try:
                    not_h.add(datetime.date.fromisoformat(s))
                except ValueError:
                    pass
        except Exception as e:
            print(f"[MARKET_CAL] krx_extra_holidays.json 로드 실패: {e}")
    _extra_holidays = extra
    _not_holiday = not_h


def _kr_holidays_for(year: int):
    """holidays.KR(years=[year]) 캐시. 패키지 미설치면 빈 dict."""
    if not _holidays_pkg_available:
        return {}
    with _lock:
        cache = _kr_holidays_cache.get(year)
        if cache is None:
            try:
                cache = holidays.KR(years=[year])
            except Exception as e:
                print(f"[MARKET_CAL] holidays.KR({year}) 로드 실패: {e}")
                cache = {}
            _kr_holidays_cache[year] = cache
        return cache


def is_holiday(d: datetime.date = None) -> bool:
    """한국 공휴일 + KRX 임시 휴장일 여부 (토/일 제외, 평일만 체크)."""
    if d is None:
        d = datetime.date.today()
    _load_extra()

    # KRX 정책으로 휴일이 아닌 날 (제헌절 등)
    if d in _not_holiday:
        return False

    # 추가 휴장일 (근로자의 날, 폐장일, 임시휴장)
    if d in _extra_holidays:
        return True

    # holidays 패키지 — 한국 공식 공휴일
    kr = _kr_holidays_for(d.year)
    if d in kr:
        return True

    return False


def is_market_day(d: datetime.date = None) -> bool:
    """한국 증시 거래일 여부.

    - 토/일 X
    - 한국 공휴일 (어린이날, 추석, 광복절 등) X
    - KRX 추가 휴장 (근로자의 날 5/1, 폐장일 12/31, 임시휴장) X
    """
    if d is None:
        d = datetime.date.today()
    if d.weekday() >= 5:  # 5=토, 6=일
        return False
    return not is_holiday(d)


def prev_business_day(base_date: Optional[datetime.date] = None) -> datetime.date:
    """직전 거래일 (한국 공휴일·KRX 휴장일 모두 건너뜀)."""
    if base_date is None:
        base_date = datetime.date.today()
    d = base_date - datetime.timedelta(days=1)
    while not is_market_day(d):
        d -= datetime.timedelta(days=1)
    return d


def next_business_day(base_date: Optional[datetime.date] = None) -> datetime.date:
    """다음 거래일."""
    if base_date is None:
        base_date = datetime.date.today()
    d = base_date + datetime.timedelta(days=1)
    while not is_market_day(d):
        d += datetime.timedelta(days=1)
    return d


def recent_business_days(count: int = 5,
                         base_date: Optional[datetime.date] = None) -> list:
    """최근 N 거래일 리스트 (오늘 제외, 과거 방향)."""
    if base_date is None:
        base_date = datetime.date.today()
    days = []
    d = base_date
    while len(days) < count:
        d -= datetime.timedelta(days=1)
        if is_market_day(d):
            days.append(d)
    return days


# 호환: 기존 main.py is_weekday 대체용 alias
def is_weekday(d: datetime.date = None) -> bool:
    """후방 호환 — `is_market_day`를 호출. 기존 코드 깨지지 않게."""
    return is_market_day(d)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 2026년 주요 케이스 검증
    test_dates = [
        (datetime.date(2026, 5, 1),  False, "근로자의 날 (KRX 휴장)"),
        (datetime.date(2026, 5, 4),  True,  "월요일 평일"),
        (datetime.date(2026, 5, 5),  False, "어린이날"),
        (datetime.date(2026, 5, 25), False, "부처님오신날 대체"),
        (datetime.date(2026, 6, 3),  False, "지방선거일"),
        (datetime.date(2026, 6, 6),  False, "현충일 (토요일)"),
        (datetime.date(2026, 7, 17), True,  "제헌절 (KRX 휴장 X)"),
        (datetime.date(2026, 8, 15), False, "광복절 (토요일)"),
        (datetime.date(2026, 9, 25), False, "추석"),
        (datetime.date(2026, 10, 9), False, "한글날 (금요일)"),
        (datetime.date(2026, 12, 25), False, "크리스마스"),
        (datetime.date(2026, 12, 31), False, "연말 폐장일"),
    ]
    print(f"{'date':<12} {'예상':<6} {'결과':<6} {'설명'}")
    print("-" * 70)
    pass_count = 0
    for d, expected, desc in test_dates:
        actual = is_market_day(d)
        ok = "✓" if actual == expected else "✗"
        if actual == expected:
            pass_count += 1
        print(f"{d.isoformat():<12} {str(expected):<6} {str(actual):<6} {ok}  {desc}")
    print("-" * 70)
    print(f"통과: {pass_count}/{len(test_dates)}")

    # 5/4 기준 직전 거래일 = 5/1 휴장이라 4/30 (목)이어야
    print(f"\n2026-05-04 직전 거래일: {prev_business_day(datetime.date(2026, 5, 4))} (4/30 기대)")
    print(f"2026-05-04 최근 5거래일: {recent_business_days(5, datetime.date(2026, 5, 4))}")
