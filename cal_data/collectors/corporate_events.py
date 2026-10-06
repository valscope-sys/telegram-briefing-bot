"""기업 행사 수집 — 인베스터데이·애널리스트데이·신제품 공개 키노트 등

실적 캘린더(Nasdaq 등)는 실적만 다루고, 일반 뉴스 피드에는 "OO, 10/6 인베스터데이 개최" 같은
보도자료가 거의 안 걸려서 마벨 인베스터데이(2026-10-06) 같은 굵직한 행사가 누락됐음.

1) 후보 수집: Bing 뉴스 RSS(키 불필요) — 회사별 문구 검색 + 일반 문구 검색, 최근 45일 기사만
2) 추출: Claude 사용 가능하면 Claude가 헤드라인에서 행사·날짜 추출(정확도 높음),
   항상 함께 엄격한 패턴("to Host Investor Day on October 27" 등)으로도 추출해 병합
대상: 한국 증시와 연관된 해외 주요 기업 (PRIORITY) — 소형주 행사는 제외
"""
import calendar
import datetime
import json
import re
import time
from collections import Counter, defaultdict
from email.utils import parsedate_to_datetime

import feedparser
import requests

from cal_data.collectors.finnhub import WATCHLIST

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
BING_RSS = "https://www.bing.com/news/search"
RECENT_DAYS = 45
HORIZON_DAYS = 120

# 티커 → 영문 검색명 (한국 연관 해외 주요 기업). 한글명은 WATCHLIST 사용
PRIORITY = {
    "NVDA": "Nvidia", "AMD": "AMD", "AVGO": "Broadcom", "MRVL": "Marvell", "MU": "Micron",
    "INTC": "Intel", "QCOM": "Qualcomm", "TSM": "TSMC", "ASML": "ASML", "AMAT": "Applied Materials",
    "LRCX": "Lam Research", "KLAC": "KLA", "ARM": "Arm Holdings", "SNDK": "SanDisk",
    "WDC": "Western Digital", "SMCI": "Supermicro", "DELL": "Dell", "ANET": "Arista",
    "CSCO": "Cisco", "COHR": "Coherent", "CRDO": "Credo", "ALAB": "Astera Labs", "CLS": "Celestica",
    "VRT": "Vertiv", "ETN": "Eaton", "GEV": "GE Vernova", "CEG": "Constellation Energy",
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google", "AMZN": "Amazon", "META": "Meta",
    "TSLA": "Tesla", "ORCL": "Oracle", "PLTR": "Palantir", "LLY": "Eli Lilly", "NVO": "Novo Nordisk",
    "AMGN": "Amgen", "MRK": "Merck", "BA": "Boeing", "LMT": "Lockheed Martin", "HII": "Huntington Ingalls",
    "CCJ": "Cameco", "OKLO": "Oklo", "SMR": "NuScale", "FSLR": "First Solar", "ALB": "Albemarle",
    "GM": "General Motors", "RIVN": "Rivian", "CPNG": "Coupang", "AMKR": "Amkor", "JBL": "Jabil",
}
# 비상장이지만 한국 증시에 영향 큰 곳 (티커 대신 이름 사용)
PRIVATE = {"OpenAI": "OpenAI", "SpaceX": "스페이스X"}

# Bing 뉴스는 OR 조합 시 결과가 0건이 되므로 단순 문구 검색을 여러 번 호출
COMPANY_QUERIES = ['{name} "investor day"', '{name} "analyst day"']
BIGTECH_EVENT_QUERIES = ['{name} keynote', '{name} "special event"']
BIGTECH = {"AAPL", "GOOGL", "META", "TSLA", "MSFT", "AMZN", "NVDA", "AMD", "OpenAI", "SpaceX"}
GENERIC_QUERIES = [
    '"to host" "investor day"', '"to host" "analyst day"', '"to host" "capital markets day"',
    '"investor day" 2026', '"financial analyst day"', '"to deliver keynote" 2026',
]

EVENT_TYPES = [  # (패턴, 한글 행사명)
    (re.compile(r"financial analyst day|analyst day", re.I), "애널리스트데이"),
    (re.compile(r"capital markets day", re.I), "캐피털마켓데이"),
    (re.compile(r"investor day|investor and analyst day|investor event", re.I), "인베스터데이"),
    (re.compile(r"keynote|unveil|launch event|product event|send(?:s)? invites|special event", re.I), "신제품 공개·키노트"),
]
MONTH = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
DATE_RE = re.compile(MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(20\d\d))?")
MONTH_NUM = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
# 패턴 추출은 "행사 + on/for + 날짜"가 가까이 붙은 경우만 (오탐 방지)
STRICT_RE = re.compile(
    r"(investor day|analyst day|capital markets day|investor and analyst day|keynote|special event|launch event|product event)"
    r"[^.]{0,40}?\b(?:on|for)\s+" + MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(20\d\d))?", re.I)
CALENDAR_RE = re.compile(r"mark your calendars? for\s+" + MONTH + r"\s+(\d{1,2})", re.I)

# 직전 실행 실패 쿼리 수 (로그용)
LAST_ERRORS = 0


def _bing(query: str) -> list[dict] | None:
    try:
        res = requests.get(BING_RSS, params={"format": "rss", "q": query}, headers=UA, timeout=20)
        if res.status_code != 200:
            print(f"[기업행사] ERROR: Bing HTTP {res.status_code} — {query}")
            return None
        return feedparser.parse(res.content).entries
    except Exception as e:
        print(f"[기업행사] ERROR: Bing 요청 실패 — {query} — {e}")
        return None


def _to_date(mon: str, day: str, year: str, ref: datetime.date) -> datetime.date | None:
    try:
        m = MONTH_NUM[mon[:3].lower()]
        d = int(day)
        if year:
            return datetime.date(int(year), m, d)
        # 연도 없으면 기사 발행일 이후 가장 가까운 날짜
        for y in (ref.year, ref.year + 1):
            cand = datetime.date(y, m, d)
            if cand >= ref - datetime.timedelta(days=3):
                return cand
    except (KeyError, ValueError):
        return None
    return None


def _event_kind(text: str) -> str:
    for pat, kind in EVENT_TYPES:
        if pat.search(text):
            return kind
    return "기업행사"


def collect_candidates(today: datetime.date) -> list[dict]:
    """Bing 뉴스에서 최근 기업 행사 관련 기사 수집 → [{key, name, title, summary, published}]"""
    global LAST_ERRORS
    LAST_ERRORS = 0
    names = list(PRIORITY.items()) + [(k, k) for k in PRIVATE]
    jobs = [(t, q.format(name=n)) for t, n in names for q in COMPANY_QUERIES]
    jobs += [(t, q.format(name=PRIORITY.get(t, t))) for t in BIGTECH for q in BIGTECH_EVENT_QUERIES]
    jobs += [(None, q) for q in GENERIC_QUERIES]

    out, seen = [], set()
    cutoff = today - datetime.timedelta(days=RECENT_DAYS)
    for key, query in jobs:
        entries = _bing(query)
        time.sleep(0.6)
        if entries is None:
            LAST_ERRORS += 1
            continue
        for e in entries:
            title = (e.get("title") or "").strip()
            summary = re.sub(r"<[^>]+>", " ", e.get("summary") or "").strip()
            try:
                pub = parsedate_to_datetime(e.get("published")).date()
            except Exception:
                pub = today
            if pub < cutoff or (key, title) in seen:
                continue
            seen.add((key, title))
            company = key
            if company is None:  # 일반 쿼리 → 제목에 우선순위 기업명이 있어야 채택
                company = next((t for t, n in list(PRIORITY.items()) + [(k, k) for k in PRIVATE]
                                if re.search(rf"\b{re.escape(n)}\b", title)), None)
                if company is None:
                    continue
            qkind = _event_kind(query) if key is not None else ""
            out.append({"key": company, "title": title, "summary": summary[:300],
                        "published": pub.isoformat(), "qkind": qkind})
    return out


def extract_by_pattern(cands: list[dict], today: datetime.date) -> list[dict]:
    """엄격한 패턴 추출 — 회사별로 가장 많이 언급된 미래 날짜를 채택"""
    votes = defaultdict(Counter)
    kinds = defaultdict(Counter)
    heads = {}
    for c in cands:
        text = f"{c['title']}. {c['summary']}"
        ref = datetime.date.fromisoformat(c["published"])
        for m in list(STRICT_RE.finditer(text)) + list(CALENDAR_RE.finditer(text)):
            g = m.groups()
            mon, day, year = (g[1], g[2], g[3]) if len(g) == 4 else (g[0], g[1], "")
            d = _to_date(mon, day, year, ref)
            if d and today <= d <= today + datetime.timedelta(days=HORIZON_DAYS):
                votes[c["key"]][d] += 1
                kind = _event_kind(text)
                if kind == "기업행사" and c.get("qkind"):
                    kind = c["qkind"]  # 본문에 행사명이 없으면 검색어("investor day" 등)로 판단
                kinds[(c["key"], d)][kind] += 1
                heads.setdefault((c["key"], d), c["title"])
    events = []
    for key, cnt in votes.items():
        d, _ = cnt.most_common(1)[0]
        kind = kinds[(key, d)].most_common(1)[0][0]
        events.append({"key": key, "date": d.isoformat(), "kind": kind, "headline": heads[(key, d)]})
    return events


EXTRACT_SYSTEM = """너는 증시 캘린더용 기업 행사 추출기다.
기사 헤드라인 목록에서 '앞으로 열릴' 기업 행사만 뽑는다:
인베스터데이·애널리스트데이·캐피털마켓데이, 신제품 공개 이벤트·키노트, 개발자 컨퍼런스, AI데이 등.
규칙:
- 날짜(월·일)가 기사에 명시됐거나 문맥상 확정된 것만. 추측 금지
- 이미 열린 행사, 실적발표, 증권사·전시회 부대 행사(fireside chat, 브렉퍼스트, 투자자 미팅)는 제외
- 쇼핑 할인행사·스포츠 등 증시와 무관한 이벤트 제외
- 회사는 주어진 목록의 키(티커 또는 이름)로만 표시
- 한국 시간(KST) 시각을 알 수 있으면 time에 HH:MM, 모르면 ""
JSON 배열만 출력: [{"key":"MRVL","date":"2026-10-06","time":"22:00","kind":"인베스터데이",
"summary":"장기 매출·이익 목표 발표 예정. 관련: SK하이닉스(HBM), 기판",
"headline":"근거가 된 기사 제목 그대로"}]"""


def extract_by_llm(cands: list[dict], today: datetime.date) -> list[dict] | None:
    try:
        from cal_data.llm_client import get_client, llm_available
    except Exception:
        return None
    if not cands or not llm_available():
        return None
    companies = ", ".join(f"{t}={n}" for t, n in list(PRIORITY.items()) + [(k, k) for k in PRIVATE])
    lines = "\n".join(f"- [{c['key']}] ({c['published']}) {c['title']} — {c['summary'][:200]}" for c in cands[:220])
    prompt = f"오늘: {today.isoformat()}\n회사 목록: {companies}\n\n기사:\n{lines}"
    try:
        resp = get_client().messages.create(model="claude-haiku-4-5-20251001", max_tokens=3000,
                                            system=EXTRACT_SYSTEM, messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text
        text = text[text.find("["): text.rfind("]") + 1]
        items = json.loads(text) if text else []
    except Exception as e:
        print(f"[기업행사] ERROR: Claude 추출 실패 — {e}")
        return None
    out = []
    for it in items:
        try:
            d = datetime.date.fromisoformat(it["date"])
        except Exception:
            continue
        key = it.get("key")
        if key not in PRIORITY and key not in PRIVATE:
            continue
        if today <= d <= today + datetime.timedelta(days=HORIZON_DAYS):
            out.append({"key": key, "date": d.isoformat(), "kind": it.get("kind") or "기업행사",
                        "time": it.get("time") or "", "summary": it.get("summary") or "",
                        "headline": it.get("headline") or ""})
    return out


def _to_calendar_event(ev: dict) -> dict:
    key = ev["key"]
    if key in PRIVATE:
        label = PRIVATE[key]
    else:
        label = f"{WATCHLIST.get(key) or PRIORITY[key]}({key})"
    out = {"date": ev["date"], "time": ev.get("time", ""), "category": "기업행사",
           "title": f"{label} {ev['kind']}", "source": "corp_events", "auto": True}
    parts = [p for p in (ev.get("summary"), f"근거 기사: {ev['headline']}" if ev.get("headline") else "") if p]
    summary = " · ".join(parts)
    if summary:
        out["summary"] = summary
    return out


def _covered(ev: dict, existing: list[dict]) -> bool:
    """같은 회사의 행사가 이미 고정·산업 일정에 있으면 True (±1일)"""
    key = ev["key"]
    names = {n.lower() for n in (PRIORITY.get(key), WATCHLIST.get(key), PRIVATE.get(key), key) if n}
    d = datetime.date.fromisoformat(ev["date"])
    for e in existing:
        try:
            ed = datetime.date.fromisoformat(e.get("date", ""))
            end = datetime.date.fromisoformat(e.get("endDate") or e["date"])
        except ValueError:
            continue
        if ed - datetime.timedelta(days=1) <= d <= end + datetime.timedelta(days=1):
            title = (e.get("title") or "").lower()
            if any(n in title for n in names):
                return True
    return False


def fetch_corporate_events(today: datetime.date | None = None, existing_events: list[dict] | None = None) -> list[dict]:
    today = today or datetime.date.today()
    cands = collect_candidates(today)
    print(f"[기업행사] 후보 기사 {len(cands)}건 (Bing 오류 쿼리 {LAST_ERRORS}건)")
    pattern = extract_by_pattern(cands, today)
    llm = extract_by_llm(cands, today)
    print(f"[기업행사] 패턴 추출 {len(pattern)}건 / Claude 추출 "
          f"{len(llm) if llm is not None else '사용 불가'}건")
    merged = {}
    for ev in pattern + (llm or []):  # 같은 회사·날짜면 Claude 결과(뒤쪽)가 덮어씀
        merged[(ev["key"], ev["date"])] = ev
    known = [e for e in (existing_events or []) if e.get("source") in ("known", "fixed")]
    kept = [e for e in merged.values() if not _covered(e, known)]
    if len(kept) < len(merged):
        print(f"[기업행사] 고정·산업 일정과 겹쳐 제외 {len(merged) - len(kept)}건")
    return [_to_calendar_event(e) for e in sorted(kept, key=lambda e: e["date"])]
