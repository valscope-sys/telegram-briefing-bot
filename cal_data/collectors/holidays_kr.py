"""한국 증시 휴장일 자동 수집 — holidays 라이브러리 기반.

2026-06-02 신규: 지방선거(6/3) 같은 중요 휴장일이 calendar에서 누락되던 문제 해결.
기존 수집기(fixed_events·FnGuide·Finnhub 등)에 휴장일 collector가 없어 수동 등록만
가능했음. holidays 라이브러리가 법정공휴일·대체공휴일·선거일·음력(설/추석)을 모두
자동 계산하므로, 매년 수동으로 찾을 필요 없이 자동 반영된다.

검증: holidays 0.95가 2026-06-03 지방선거일을 정확히 포함 확인.
증시 특화 보강: 근로자의 날(5/1)·연말 폐장(12/31)은 법정공휴일이 아니지만 증시 휴장.
"""
import datetime

try:
    import holidays
    _HAS_HOLIDAYS = True
except ImportError:
    _HAS_HOLIDAYS = False


def _make_event(d: datetime.date, name: str) -> dict:
    return {
        "date": d.isoformat(),
        "time": "",
        "category": "휴장일",
        "title": f"{name} (증시 휴장)",
        "country": "🇰🇷",
        "source": "holidays",
        "auto": True,
    }


def get_market_holidays(from_date: datetime.date, to_date: datetime.date) -> list:
    """기간 내 한국 증시 휴장일 이벤트 생성.

    - holidays.SouthKorea: 법정공휴일·대체공휴일·선거일·음력(설/추석) 자동 계산
    - 증시 특화 보강: 근로자의 날(5/1), 연말 폐장(12/31)
    - 주말(토/일)에 걸린 휴장은 제외 (어차피 증시 미개장 → 시황에 표시 불필요)
    """
    if not _HAS_HOLIDAYS:
        print("[Calendar] holidays 라이브러리 미설치 — 휴장일 수집 생략")
        return []

    events = []
    seen = set()
    years = list(range(from_date.year, to_date.year + 1))

    kr = holidays.SouthKorea(years=years)
    for d, name in kr.items():
        if from_date <= d <= to_date and d.weekday() < 5:  # 평일 휴장만
            events.append(_make_event(d, name))
            seen.add(d)

    # 증시 특화 — 근로자의 날(5/1), 연말 폐장(12/31). 공휴일 아니지만 증시 휴장.
    for year in years:
        for (mm, dd), label in [((5, 1), "근로자의 날"), ((12, 31), "연말 폐장")]:
            try:
                d = datetime.date(year, mm, dd)
            except ValueError:
                continue
            if from_date <= d <= to_date and d.weekday() < 5 and d not in seen:
                events.append(_make_event(d, label))
                seen.add(d)

    return events
