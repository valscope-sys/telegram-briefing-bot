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

    # 확정 날짜가 있으면 같은 기업의 undated "예상" 자동 제거
    # 티커 → 한글명 매핑 (Finnhub은 영문, undated는 한글)
    TICKER_KR = {
        "TSLA": "테슬라", "NVDA": "엔비디아", "AAPL": "애플", "MSFT": "마이크로소프트",
        "GOOGL": "구글", "AMZN": "아마존", "META": "메타", "NFLX": "넷플릭스",
        "TSM": "TSMC", "AMD": "AMD", "ASML": "ASML", "AVGO": "브로드컴",
    }
    confirmed_corps = set()
    for ev in result:
        if not ev.get("undated") and ev.get("category", "") in ("한국실적", "한국실적(잠정)", "미국실적"):
            title = ev.get("title", "")
            corp = title.split(" 실적발표")[0].split(" 잠정실적발표")[0].strip()
            if corp:
                confirmed_corps.add(corp)
                # 티커에서 한글명도 추가
                ticker = corp.split("(")[0].strip()
                if ticker in TICKER_KR:
                    confirmed_corps.add(TICKER_KR[ticker])

    if confirmed_corps:
        result = [ev for ev in result if not (
            ev.get("undated") and
            any(corp in ev.get("title", "") for corp in confirmed_corps)
        )]

    # AI 스캐너 노이즈 카테고리 차단 (증시 직접 영향 없는 항목)
    AI_BLACKLIST_CATEGORIES = {"부동산", "전시/박람회", "게임", "K-콘텐츠"}
    result = [ev for ev in result if not (
        ev.get("source") == "ai_scan"
        and ev.get("category", "") in AI_BLACKLIST_CATEGORIES
    )]

    # 같은 기업 잠정→정식 dedupe: 잠정 발표 후 0~2일 이내 정식 발표 일정은 노이즈
    # (FnGuide가 예정으로 잡은 정식 일정인데 회사가 잠정으로 선공시한 경우)
    # 정상 발표 패턴: 잠정 후 3일+ 후 정식 분기보고서 — 보존
    result = _dedupe_provisional_official_close(result)

    result.sort(key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("category", "")))
    return result


def _dedupe_provisional_official_close(events: list[dict]) -> list[dict]:
    """같은 기업의 잠정/정식이 같은 날(0일) 동시 등록되어 있으면 잠정 제거 (정식 보존).
    하루라도 차이나면 별개 발표로 간주 — 둘 다 보존."""
    from collections import defaultdict
    by_corp = defaultdict(list)
    for ev in events:
        cat = ev.get("category", "")
        if cat in ("한국실적", "한국실적(잠정)"):
            title = ev.get("title", "")
            corp = title.replace(" 잠정실적발표", "").replace(" 실적발표", "").strip()
            if corp:
                by_corp[corp].append(ev)

    drop_ids = set()
    for corp, evs in by_corp.items():
        prov = [e for e in evs if e.get("category") == "한국실적(잠정)"]
        off = [e for e in evs if e.get("category") == "한국실적"]
        if not prov or not off:
            continue
        off_dates = {o.get("date", "") for o in off}
        for p in prov:
            # 정식과 같은 날짜에 잠정이 있으면 잠정 제거
            if p.get("date", "") in off_dates:
                drop_ids.add(id(p))

    if drop_ids:
        return [ev for ev in events if id(ev) not in drop_ids]
    return events


def collect_all(from_date: datetime.date, to_date: datetime.date, skip_ai: bool = False) -> list[dict]:
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

    # 3. Finnhub (미국 실적)
    try:
        from cal_data.collectors.finnhub import fetch_finnhub_all
        finnhub = fetch_finnhub_all(from_date, to_date)
        print(f"[Calendar] Finnhub: {len(finnhub)}건")
        all_events.extend(finnhub)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Calendar] Finnhub 실패: {e}")

    # 3.5. Investing.com (경제지표)
    try:
        from cal_data.collectors.investing_economic import fetch_investing_economic
        inv = fetch_investing_economic(from_date, to_date)
        print(f"[Calendar] 경제지표(Investing): {len(inv)}건")
        all_events.extend(inv)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Calendar] Investing 실패: {e}")

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

    # 6. AI 뉴스 스캐너 (Claude API) - skip_ai 시 생략 (비용 절감)
    if skip_ai:
        print("[Calendar] AI스캔: 생략 (--skip-ai)")
    else:
        try:
            from cal_data.collectors.ai_news_scanner import scan_news_for_events
            ai_events = scan_news_for_events()
            print(f"[Calendar] AI스캔: {len(ai_events)}건")
            all_events.extend(ai_events)
        except ImportError:
            pass
        except Exception as e:
            print(f"[Calendar] AI스캔 실패: {e}")

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
    parser.add_argument("--skip-ai", action="store_true", help="AI 뉴스 스캐너 생략 (Claude API 비용 절감)")
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
    new_events = collect_all(from_date, to_date, skip_ai=args.skip_ai)
    merged = merge_events(existing, new_events)
    save_calendar(merged)


if __name__ == "__main__":
    main()
