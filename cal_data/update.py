"""
캘린더 일정 수집 오케스트레이터

Usage:
    python -m cal_data.update              # 향후 60일 업데이트
    python -m cal_data.update --full       # 연말까지 업데이트
    python -m cal_data.update --month 202604  # 특정 월 업데이트
"""
import json
import datetime
import argparse
import shutil
from pathlib import Path

CALENDAR_DIR = Path(__file__).resolve().parent
CALENDAR_JSON = CALENDAR_DIR / "calendar.json"
DOCS_DIR = CALENDAR_DIR.parent / "docs"
DOCS_JSON = DOCS_DIR / "calendar.json"


def load_existing() -> list[dict]:
    """기존 calendar.json 로드"""
    if CALENDAR_JSON.exists():
        try:
            return json.loads(CALENDAR_JSON.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def normalize_title(title: str) -> str:
    """제목 정규화 (중복 비교용)"""
    t = title.strip()
    for suffix in ["(잠정)", "(예정)", "(확정)"]:
        t = t.replace(suffix, "")
    return t.strip()


def merge_events(existing: list[dict], new_events: list[dict]) -> list[dict]:
    """
    기존 + 신규 이벤트 병합.
    수동(auto=False) 이벤트는 절대 덮어쓰지 않음.
    동일 (date, category, normalized_title) → 소스 우선순위로 결정.
    """
    SOURCE_PRIORITY = {"fixed": 10, "fnguide": 8, "finnhub": 6, "38cr": 4, "manual": 100}

    indexed = {}
    for ev in existing:
        if not ev.get("auto", True):
            key = (ev["date"], ev.get("category", ""), normalize_title(ev.get("title", "")))
            indexed[key] = ev
            continue
        key = (ev["date"], ev.get("category", ""), normalize_title(ev.get("title", "")))
        indexed[key] = ev

    for ev in new_events:
        key = (ev["date"], ev.get("category", ""), normalize_title(ev.get("title", "")))
        if key in indexed:
            old = indexed[key]
            if not old.get("auto", True):
                continue
            old_pri = SOURCE_PRIORITY.get(old.get("source", ""), 0)
            new_pri = SOURCE_PRIORITY.get(ev.get("source", ""), 0)
            if new_pri >= old_pri:
                indexed[key] = ev
        else:
            indexed[key] = ev

    result = list(indexed.values())
    result.sort(key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("category", "")))
    return result


def collect_all(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """모든 collector 실행 후 결과 합산"""
    all_events = []

    # 1. 고정 이벤트
    try:
        from cal_data.collectors.fixed_events import get_fixed_events
        fixed = get_fixed_events(from_date, to_date)
        print(f"[Calendar] 고정이벤트: {len(fixed)}건")
        all_events.extend(fixed)
    except Exception as e:
        print(f"[Calendar] 고정이벤트 실패: {e}")

    # 2. FnGuide
    try:
        from cal_data.collectors.fnguide import fetch_fnguide_range
        fnguide = fetch_fnguide_range(from_date, to_date)
        print(f"[Calendar] FnGuide: {len(fnguide)}건")
        all_events.extend(fnguide)
    except Exception as e:
        print(f"[Calendar] FnGuide 실패: {e}")

    # 3. Finnhub (Phase B에서 추가)
    try:
        from cal_data.collectors.finnhub import fetch_finnhub_all
        finnhub = fetch_finnhub_all(from_date, to_date)
        print(f"[Calendar] Finnhub: {len(finnhub)}건")
        all_events.extend(finnhub)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Calendar] Finnhub 실패: {e}")

    # 4. 38.co.kr
    try:
        from cal_data.collectors.ipo_listing import fetch_all_ipo
        ipo = fetch_all_ipo()
        print(f"[Calendar] IPO: {len(ipo)}건")
        all_events.extend(ipo)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Calendar] IPO 실패: {e}")

    # 5. 뉴스/컨퍼런스/게임/엔터
    try:
        from cal_data.collectors.news_events import fetch_news_events
        news = fetch_news_events(from_date, to_date)
        print(f"[Calendar] 뉴스이벤트: {len(news)}건")
        all_events.extend(news)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Calendar] 뉴스이벤트 실패: {e}")

    return all_events


def save_calendar(events: list[dict]):
    """calendar.json 저장 + docs/ 복사"""
    CALENDAR_JSON.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Calendar] {CALENDAR_JSON} 저장 ({len(events)}건)")

    if DOCS_DIR.exists():
        DOCS_JSON.write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[Calendar] {DOCS_JSON} 복사 완료")


def main():
    parser = argparse.ArgumentParser(description="캘린더 일정 업데이트")
    parser.add_argument("--full", action="store_true", help="연말까지 전체 업데이트")
    parser.add_argument("--month", type=str, help="특정 월 업데이트 (YYYYMM)")
    args = parser.parse_args()

    today = datetime.date.today()

    if args.month:
        year = int(args.month[:4])
        month = int(args.month[4:6])
        from_date = datetime.date(year, month, 1)
        if month == 12:
            to_date = datetime.date(year, 12, 31)
        else:
            to_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    elif args.full:
        from_date = today
        to_date = datetime.date(today.year, 12, 31)
    else:
        from_date = today
        to_date = today + datetime.timedelta(days=60)

    print(f"[Calendar] 수집 범위: {from_date} ~ {to_date}")

    existing = load_existing()
    new_events = collect_all(from_date, to_date)
    merged = merge_events(existing, new_events)
    save_calendar(merged)


if __name__ == "__main__":
    main()
