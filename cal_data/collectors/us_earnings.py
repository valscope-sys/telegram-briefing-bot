"""해외(미국 상장) 실적 발표 일정 — 키 없는 소스 우선

1순위 Nasdaq 실적 캘린더 — 일자별 조회, 장전/장후·시총·EPS 예상 제공, TSMC·ASML 등 ADR 포함
2순위 TradingView 스캐너 — Nasdaq 조회 구간 밖 (종목별 '다음 실적일'만 제공)
fallback Finnhub — 위 두 소스가 모두 실패할 때만 (API 키 필요)

선정: 워치리스트(한국 연관 종목, finnhub.WATCHLIST) + 시가총액 2,000억달러 이상 자동 포함
"""
import datetime
import re
import time

import requests

from cal_data.collectors.finnhub import WATCHLIST

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
# Nasdaq는 일자별 호출이라 가까운 구간만 (그 뒤는 TradingView '다음 실적일'로 보완)
NASDAQ_DAYS = 75
TV_URL = "https://scanner.tradingview.com/america/scan"
TV_HEADERS = {"User-Agent": NASDAQ_HEADERS["User-Agent"], "Origin": "https://www.tradingview.com",
              "Referer": "https://www.tradingview.com/"}

MEGA_CAP_USD = 2e11

# 워치리스트 밖 초대형주 한글명 (없으면 영문 회사명 사용)
EXTRA_KR = {
    "GOOG": "알파벳", "PM": "필립모리스", "LIN": "린데", "APH": "암페놀", "SPCX": "스페이스X",
    "BAC": "뱅크오브아메리카", "PLD": "프롤로지스", "BX": "블랙스톤", "TMUS": "T모바일",
    "HSBC": "HSBC", "SAP": "SAP", "TM": "도요타", "SHEL": "셸", "AZN": "아스트라제네카",
    "NVS": "노바티스", "BHP": "BHP", "HDB": "HDFC은행", "UBER": "우버", "BP": "BP",
}
# 한국 기업 ADR은 국내 실적(KIND·FnGuide)에서 다루므로 제외
KOREAN_ADR = {"SKHY", "KB", "SHG", "PKX", "KEP", "LPL", "WF"}
# 같은 회사의 다른 주식 클래스 — 대표 티커만
SHARE_CLASS_ALIAS = {"GOOG": "GOOGL", "BRK.B": "BRK.A", "FOXA": "FOX"}

# 직전 실행 실패 구간 — update.py가 이 구간의 기존 일정은 교체하지 않고 보존
LAST_FAILED_RANGES: list[tuple[str, str]] = []


def _money(s) -> float:
    try:
        return float(re.sub(r"[^\d.\-]", "", str(s or "")) or 0)
    except ValueError:
        return 0.0


def _short_name(name: str) -> str:
    name = re.sub(r",?\s*(Inc\.?|Corporation|Corp\.?|Holdings?|Company|Co\.|plc|N\.V\.|Ltd\.?|Limited|S\.A\.)\b.*$", "",
                  name or "", flags=re.I).strip()
    return name or "?"


def _kr_name(symbol: str, name: str) -> str:
    return WATCHLIST.get(symbol) or EXTRA_KR.get(symbol) or _short_name(name)


def _selected(symbol: str, mcap: float) -> bool:
    if symbol in KOREAN_ADR or not symbol:
        return False
    return symbol in WATCHLIST or mcap >= MEGA_CAP_USD


def _event(date: str, symbol: str, name: str, hour: str, eps=None, mcap: float = 0.0,
           fq: str = "", source: str = "nasdaq") -> dict:
    title = f"{_kr_name(symbol, name)}({symbol}) 실적발표" + (f" ({hour})" if hour else "")
    parts = []
    if hour == "장전":
        parts.append("미국 장 시작 전 발표 (KST 당일 밤)")
    elif hour == "장후":
        parts.append("미국 장 마감 후 발표 (KST 익일 새벽)")
    if fq:
        parts.append(f"회계분기 {fq}")
    if eps not in (None, "", 0):
        parts.append(f"EPS 예상 ${eps:.2f}" if isinstance(eps, float) else f"EPS 예상 {eps}")
    if mcap:
        parts.append(f"시총 ${mcap / 1e12:.2f}조" if mcap >= 1e12 else f"시총 ${mcap / 1e9:,.0f}B")
    ev = {"date": date, "time": "", "category": "미국실적", "title": title,
          "source": source, "auto": True, "country": "🇺🇸"}
    if parts:
        ev["summary"] = " · ".join(parts)
    return ev


def fetch_nasdaq(from_date: datetime.date, to_date: datetime.date) -> list[dict] | None:
    """Nasdaq 일자별 실적 캘린더. 전 구간 실패 시 None"""
    results, any_ok = [], False
    d = from_date
    while d <= to_date:
        if d.weekday() < 5:
            try:
                res = requests.get(NASDAQ_URL, params={"date": d.isoformat()}, headers=NASDAQ_HEADERS, timeout=20)
                rows = ((res.json().get("data") or {}).get("rows") or []) if res.status_code == 200 else None
            except Exception as e:
                print(f"[Nasdaq] ERROR: {d} 요청 실패 — {e}")
                rows = None
            if rows is None:
                LAST_FAILED_RANGES.append((d.isoformat(), d.isoformat()))
            else:
                any_ok = True
                for x in rows:
                    symbol = (x.get("symbol") or "").replace("/", ".")
                    mcap = _money(x.get("marketCap"))
                    if not _selected(symbol, mcap):
                        continue
                    t = x.get("time") or ""
                    hour = "장전" if "pre-market" in t else ("장후" if "after-hours" in t else "")
                    eps = _money(x.get("epsForecast")) if x.get("epsForecast") else None
                    results.append(_event(d.isoformat(), symbol, x.get("name", ""), hour, eps, mcap,
                                          x.get("fiscalQuarterEnding") or ""))
            time.sleep(0.3)
        d += datetime.timedelta(days=1)
    if not any_ok:
        print(f"[Nasdaq] ERROR: {from_date}~{to_date} 전 구간 실패")
        return None
    return results


def fetch_tradingview(from_date: datetime.date, to_date: datetime.date) -> list[dict] | None:
    """TradingView 스캐너 — 종목별 다음 실적일 (Nasdaq 구간 밖 보완용)"""
    ts = lambda d: int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())
    body = {
        "columns": ["name", "description", "market_cap_basic", "earnings_release_next_date",
                    "earnings_release_next_time", "earnings_per_share_forecast_next_fq"],
        "filter": [
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "is_primary", "operation": "equal", "right": True},
            {"left": "earnings_release_next_date", "operation": "in_range",
             "right": [ts(from_date), ts(to_date + datetime.timedelta(days=1))]},
        ],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 3000],
    }
    try:
        res = requests.post(TV_URL, json=body, headers=TV_HEADERS, timeout=30)
        data = res.json().get("data") if res.status_code == 200 else None
    except Exception as e:
        print(f"[TradingView 실적] ERROR: 요청 실패 — {e}")
        data = None
    if data is None:
        LAST_FAILED_RANGES.append((from_date.isoformat(), to_date.isoformat()))
        return None
    results = []
    for x in data:
        symbol, name, mcap, nd, nt, eps = x["d"]
        symbol = (symbol or "").replace("/", ".")
        if not nd or not _selected(symbol, mcap or 0):
            continue
        date = datetime.datetime.fromtimestamp(nd, datetime.timezone.utc).date()
        # -1만 '장전'으로 신뢰 가능 (0은 장후·미정이 섞여 있어 비워둠)
        hour = "장전" if nt == -1 else ""
        results.append(_event(date.isoformat(), symbol, name, hour,
                              float(eps) if eps is not None else None, mcap or 0, source="tv_earnings"))
    return results


def _dedupe(events: list[dict]) -> list[dict]:
    """같은 날·같은 회사(주식 클래스 포함) 1건만 — 장전/장후 정보가 있는 쪽 우선"""
    best: dict[tuple, dict] = {}
    for ev in events:
        m = re.search(r"\(([A-Z.]+)\) 실적발표", ev["title"])
        sym = SHARE_CLASS_ALIAS.get(m.group(1), m.group(1)) if m else ev["title"]
        key = (ev["date"], sym)
        cur = best.get(key)
        if cur is None or ("(장" in ev["title"] and "(장" not in cur["title"]):
            best[key] = ev
    return sorted(best.values(), key=lambda e: e["date"])


def fetch_us_earnings_all(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    LAST_FAILED_RANGES.clear()
    near_end = min(to_date, from_date + datetime.timedelta(days=NASDAQ_DAYS))
    nasdaq = fetch_nasdaq(from_date, near_end)
    print(f"[Calendar] 해외실적(Nasdaq {from_date}~{near_end}): {len(nasdaq) if nasdaq is not None else '실패'}")

    far = []
    if to_date > near_end:
        far_start = near_end + datetime.timedelta(days=1)
        tv = fetch_tradingview(far_start, to_date)
        far = tv or []
        print(f"[Calendar] 해외실적(TradingView {far_start}~{to_date}): {len(tv) if tv is not None else '실패'}")
        # Nasdaq 게시 범위(약 2.5개월) 밖은 Finnhub 추정 일정으로 보강 (키 있을 때만)
        try:
            from cal_data.collectors.finnhub import FINNHUB_API_KEY, fetch_us_earnings
            if FINNHUB_API_KEY:
                fh = fetch_us_earnings(far_start, to_date)
                print(f"[Calendar] 해외실적(Finnhub 원거리 보강 {far_start}~{to_date}): {len(fh)}")
                far += fh
        except Exception as e:
            print(f"[Calendar] ERROR: Finnhub 원거리 보강 실패 — {e}")

    if nasdaq is None:
        # Nasdaq 전면 실패 — Finnhub fallback (키 필요)
        try:
            from cal_data.collectors.finnhub import fetch_us_earnings
            fb = fetch_us_earnings(from_date, near_end)
            print(f"[Calendar] 해외실적(Finnhub fallback): {len(fb)}")
            nasdaq = fb
        except Exception as e:
            print(f"[Calendar] ERROR: Finnhub fallback 실패 — {e}")
            nasdaq = []
    return _dedupe(nasdaq + far)
