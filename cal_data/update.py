"""
캘린더 일정 수집 오케스트레이터

Usage:
    python -m cal_data.update              # 향후 60일 업데이트
    python -m cal_data.update --full       # 향후 180일 업데이트
    python -m cal_data.update --month 202604  # 특정 월 업데이트
"""
import re
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


# Finnhub EPS 추정치 패턴 (예: " [EPS est. $1.23]", " [EPS est. $-0.05]")
_EPS_EST_RE = re.compile(r"\s*\[EPS est\. \$-?[\d.,]+\]")


def normalize_title(title: str) -> str:
    """제목 정규화 (중복 비교용)"""
    t = title.strip()
    for suffix in ["(잠정)", "(예정)", "(확정)"]:
        t = t.replace(suffix, "")
    # EPS 추정치는 매일 변동 → dedupe 키에서 제거 (같은 실적 중복 축적 방지)
    t = _EPS_EST_RE.sub("", t)
    return t.strip()


def merge_events(existing: list[dict], new_events: list[dict]) -> list[dict]:
    """
    기존 + 신규 이벤트 병합.
    수동(auto=False) 이벤트는 절대 덮어쓰지 않음.
    동일 (date, category, normalized_title) → 소스 우선순위로 결정.
    """
    SOURCE_PRIORITY = {"holidays": 12, "fixed": 10, "known": 9, "fnguide": 8, "kind": 8, "tradingview": 7,
                       "nasdaq": 7, "finnhub": 6, "tv_earnings": 6, "investing": 5, "corp_events": 5, "38cr": 4, "news": 3,
                       "manual": 100}

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
                # "마이크론(MU)" 형식이면 한글명도 추가 (티커 단독은 V·C 같은 단문자 오매칭 위험으로 제외)
                m = re.match(r"^(.+?)\(([A-Z.]{1,6})\)$", corp)
                if m:
                    confirmed_corps.add(m.group(1))
                # 구형식 "TSLA" 티커 제목 호환
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

    # 국내 IR 중 인베스터데이·밸류업데이만 숨김 카테고리(IR)가 아닌 '기업행사'로 노출
    # ("기업가치 제고"는 소형주 IR 상투 문구라 기준에서 제외). 매 실행 재판정 → 기준 변경 시 자동 복구
    for ev in result:
        if ev.get("source") == "kind" and ev.get("category") in ("IR", "기업행사"):
            text = f"{ev.get('title', '')} {ev.get('summary', '')}"
            ev["category"] = "기업행사" if _KR_INVESTOR_DAY.search(text) else "IR"

    # FnGuide 유상/무상증자·합병·액면분할/병합 — 수집 중단 후 기존 잔존분도 제거
    result = [ev for ev in result if not (
        ev.get("source") == "fnguide" and ev.get("category", "") == "기업이벤트"
    )]

    # 같은 기업 잠정→정식 dedupe: 잠정 발표 후 0~2일 이내 정식 발표 일정은 노이즈
    # (FnGuide가 예정으로 잡은 정식 일정인데 회사가 잠정으로 선공시한 경우)
    # 정상 발표 패턴: 잠정 후 3일+ 후 정식 분기보고서 — 보존
    result = _dedupe_provisional_official_close(result)
    result = _dedupe_us_earnings(result)

    result.sort(key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("category", "")))
    return result


_KR_INVESTOR_DAY = re.compile(r"investor\s*day|인베스터\s*데이|밸류업\s*데이|ceo\s*investor", re.I)


def _dedupe_us_earnings(events: list[dict]) -> list[dict]:
    """미국실적 같은 날·같은 티커 중복 제거 — 장전/장후 정보가 있는 쪽 우선, 요약은 합침"""
    groups = {}
    for ev in events:
        if ev.get("category") != "미국실적":
            continue
        title = ev.get("title", "")
        m = re.search(r"\(([A-Z.]{1,6})\) 실적발표", title) or re.match(r"^([A-Z.]{1,6}) 실적발표", title)
        if m:
            groups.setdefault((ev.get("date"), m.group(1)), []).append(ev)
    drop = set()
    for evs in groups.values():
        if len(evs) < 2:
            continue
        keep = max(evs, key=lambda e: ("(장" in e.get("title", ""), e.get("source") != "fixed"))
        for e in evs:
            if e is keep:
                continue
            drop.add(id(e))
            if e.get("summary") and e["summary"] not in (keep.get("summary") or ""):
                keep["summary"] = f"{keep['summary']} · {e['summary']}" if keep.get("summary") else e["summary"]
    return [ev for ev in events if id(ev) not in drop]


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
        off_by_date = {o.get("date", ""): o for o in off}
        for p in prov:
            # 정식과 같은 날짜에 잠정이 있으면 잠정 제거 — 잠정의 실적·컨센 요약은 정식 일정으로 이관
            o = off_by_date.get(p.get("date", ""))
            if o is None:
                continue
            drop_ids.add(id(p))
            p_sum = p.get("summary")
            if p_sum and p_sum not in (o.get("summary") or ""):
                o["summary"] = f"{p_sum} · {o['summary']}" if o.get("summary") else p_sum

    if drop_ids:
        return [ev for ev in events if id(ev) not in drop_ids]
    return events


# 매 실행 해당 구간 전체를 다시 주는 소스 — 정상 수집된 구간의 기존 항목은 신규분으로 교체
# (연기·취소·날짜 교정된 일정이 옛 날짜에 유령으로 남는 문제 방지)
SNAPSHOT_SOURCES = {"fixed", "holidays", "finnhub", "tradingview", "known", "kind", "nasdaq", "tv_earnings"}


def _failed_ranges() -> dict[str, list[tuple[str, str]]]:
    """수집기별 직전 실행 실패 구간 (이 구간의 기존 일정은 교체하지 않고 보존)"""
    failed = {}
    try:
        from cal_data.collectors import finnhub
        failed["finnhub"] = list(finnhub.LAST_FAILED_RANGES)
    except Exception:
        pass
    try:
        from cal_data.collectors import us_earnings
        failed["nasdaq"] = failed["tv_earnings"] = list(us_earnings.LAST_FAILED_RANGES)
    except Exception:
        pass
    try:
        from cal_data.collectors import kind_ir
        failed["kind"] = list(kind_ir.LAST_FAILED_RANGES)
    except Exception:
        pass
    try:
        from cal_data.collectors import tradingview_economic
        failed["tradingview"] = list(tradingview_economic.LAST_FAILED_RANGES)
        failed["investing"] = failed["tradingview"]
    except Exception:
        pass
    return failed


def prune_for_refresh(existing: list[dict], new_events: list[dict],
                      from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """정상 수집된 스냅샷 소스의 수집 구간 내 기존 항목 제거 (수동 일정은 source=manual이라 무관)"""
    fr, to = from_date.isoformat(), to_date.isoformat()
    ok_sources = {ev.get("source") for ev in new_events} & SNAPSHOT_SOURCES
    if "tradingview" in ok_sources:
        ok_sources.add("investing")  # TradingView 정상이면 구 Investing 항목은 대체
    if "nasdaq" in ok_sources:
        ok_sources.add("finnhub")  # Nasdaq 정상이면 구 Finnhub 항목은 대체
    failed = _failed_ranges()

    def _in_failed(src, d):
        return any(a <= d <= b for a, b in failed.get(src, []))

    return [ev for ev in existing if not (
        ev.get("source") in ok_sources
        and fr <= ev.get("date", "") <= to
        and not _in_failed(ev.get("source"), ev.get("date", ""))
    )]


def drop_econ_placeholders(events: list[dict], new_events: list[dict], from_date: datetime.date) -> list[dict]:
    """TradingView 실데이터가 있는 구간의 fixed 경제지표(추정 날짜 placeholder) 제거"""
    tv_dates = [ev["date"] for ev in new_events if ev.get("source") == "tradingview"]
    if not tv_dates:
        return events
    fr, horizon = from_date.isoformat(), max(tv_dates)
    return [ev for ev in events if not (
        ev.get("source") == "fixed" and ev.get("category") == "경제지표"
        and fr <= ev.get("date", "") <= horizon
    )]


def collect_all(from_date: datetime.date, to_date: datetime.date, skip_ai: bool = False) -> list[dict]:
    """모든 collector 실행 후 결과 합산"""
    all_events = []

    # 0. 한국 증시 휴장일 (holidays 라이브러리 — 법정공휴일·대체공휴일·선거일·음력 자동)
    try:
        from cal_data.collectors.holidays_kr import get_market_holidays
        hols = get_market_holidays(from_date, to_date)
        print(f"[Calendar] 휴장일: {len(hols)}건")
        all_events.extend(hols)
    except Exception as e:
        print(f"[Calendar] 휴장일 실패: {e}")

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
        # 신버전 FnGuide는 잠정실적을 '발표 후'에만 게시 → 06:00 실행 이후 발표분을 다음날 잡도록 14일 소급
        fnguide = fetch_fnguide_range(from_date - datetime.timedelta(days=14), to_date)
        print(f"[Calendar] FnGuide: {len(fnguide)}건")
        all_events.extend(fnguide)
    except Exception as e:
        print(f"[Calendar] FnGuide 실패: {e}")

    # 2.5. KRX KIND IR 일정 — 국내 향후 실적발표(컨퍼런스콜) 일정의 주 소스
    #      (신버전 FnGuide는 IR 일정을 제공하지 않고 잠정실적은 발표 후에만 게시)
    try:
        from cal_data.collectors.kind_ir import fetch_kind_ir
        kind = fetch_kind_ir(from_date, to_date)
        print(f"[Calendar] KIND IR: {len(kind)}건")
        all_events.extend(kind)
    except Exception as e:
        print(f"[Calendar] KIND IR 실패: {e}")

    # 3. 해외 실적 — Nasdaq(키 불필요) 우선, 먼 구간은 TradingView, 둘 다 실패 시 Finnhub
    try:
        from cal_data.collectors.us_earnings import fetch_us_earnings_all
        us = fetch_us_earnings_all(from_date, to_date)
        print(f"[Calendar] 해외실적 합계: {len(us)}건")
        all_events.extend(us)
    except Exception as e:
        print(f"[Calendar] 해외실적 실패: {e}")

    # 3.5. 경제지표 — TradingView 주 소스, 전면 실패 시에만 Investing.com fallback
    #      (Investing은 데이터센터 IP에서 429 차단이 잦아 주 소스에서 제외)
    tv = None
    try:
        from cal_data.collectors.tradingview_economic import fetch_tradingview_economic
        tv = fetch_tradingview_economic(from_date, to_date)
    except Exception as e:
        print(f"[Calendar] TradingView 실패: {e}")
    if tv:
        print(f"[Calendar] 경제지표(TradingView): {len(tv)}건")
        all_events.extend(tv)
    else:
        print("[Calendar] 경제지표(TradingView): 0건 - Investing fallback 시도")
        try:
            from cal_data.collectors.investing_economic import fetch_investing_economic
            # Investing 게시 범위가 2~3주라 그 이상 요청은 429 재시도 시간만 늘림
            inv_to = min(to_date, from_date + datetime.timedelta(days=21))
            inv = fetch_investing_economic(from_date, inv_to)
            print(f"[Calendar] 경제지표(Investing fallback): {len(inv)}건")
            all_events.extend(inv)
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

    # 4.4. 해외 기업 행사 — 인베스터데이·애널리스트데이·신제품 공개 (Bing 뉴스 + Claude/패턴 추출)
    try:
        from cal_data.collectors.corporate_events import fetch_corporate_events
        from cal_data.collectors.industry_events import fetch_industry_events as _ind
        from cal_data.collectors.news_events import fetch_known_events as _known
        corp = fetch_corporate_events(existing_events=all_events + _ind(from_date, to_date) + _known(from_date, to_date))
        print(f"[Calendar] 기업행사: {len(corp)}건")
        all_events.extend(corp)
    except Exception as e:
        print(f"[Calendar] 기업행사 실패: {e}")

    # 4.5. 산업 이벤트 — 광통신·XR·배터리·디스플레이·반도체 학회·조선·방산·원전 전시 (공식 일정)
    try:
        from cal_data.collectors.industry_events import fetch_industry_events
        ind = fetch_industry_events(from_date, to_date)
        print(f"[Calendar] 산업이벤트: {len(ind)}건")
        all_events.extend(ind)
    except Exception as e:
        print(f"[Calendar] 산업이벤트 실패: {e}")

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
            ai_events = scan_news_for_events(all_events)
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
    parser.add_argument("--full", action="store_true", help="향후 180일 전체 업데이트")
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
        # 연말 고정 대신 180일 — 11~12월에 다음 해 일정이 비는 절벽 방지
        from_date = today
        to_date = today + datetime.timedelta(days=180)
    else:
        from_date = today
        to_date = today + datetime.timedelta(days=60)

    print(f"[Calendar] 수집 범위: {from_date} ~ {to_date}")

    existing = load_existing()
    new_events = collect_all(from_date, to_date, skip_ai=args.skip_ai)
    existing = prune_for_refresh(existing, new_events, from_date, to_date)
    existing = drop_econ_placeholders(existing, new_events, from_date)
    new_events = drop_econ_placeholders(new_events, new_events, from_date)
    merged = merge_events(existing, new_events)
    save_calendar(merged)


if __name__ == "__main__":
    main()
