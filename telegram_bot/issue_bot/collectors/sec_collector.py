"""SEC EDGAR 8-K 공시 수집기 — Phase 2

빅테크 + 반도체 밸류체인 Peer의 8-K Current Report 실시간 수집.
NVDA/AAPL/MSFT 등 미국 대형주의 주요 공시를 한국 시장 관점에서 필터링.

동작:
1. config.SEC_TRACKED_COMPANIES의 각 CIK별 atom RSS 조회
2. accession_number 파싱 + dedup_key 생성
3. 이슈봇 이벤트 형식으로 변환 (Template C — 영문 기사/리서치 인용)

반환 스키마 (DART와 동일):
{
  "id": "sec_{ticker}_{accession}",
  "source": "SEC",
  "source_url": "<filing URL>",
  "source_id": "<accession_number>",
  "ticker": "NVDA",
  "company_name": "NVIDIA",
  "corp_code": "<CIK>",
  "title": "8-K — <filed title or item>",
  "body_excerpt": "<atom summary>",
  "category_hint": "C",
  "priority_hint": None,  # Haiku 필터에게 맡김
  "event_type": "8K",
  "date": "YYYY-MM-DD"
}
"""
import os
import re
import sys
import time
import datetime
import requests

from telegram_bot.config import SEC_TRACKED_COMPANIES, SEC_USER_AGENT, SEC_FILING_FRESHNESS_HOURS

# 공용 세션 — TCP 재사용으로 메모리·연결 부담 완화
_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": SEC_USER_AGENT,
            "Accept": "application/atom+xml, text/html, */*",
        })
    return _session

SEC_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count={count}&output=atom"
)

# 8-K Item별 priority 힌트
# 사용자 정책(2026-04-23): "빅테크도 실적만 나오게" → Item 2.02만 HIGH, 나머지 전부 SKIP
# 필요 시 복원: 과거 파산(1.03)/중대계약(1.01)/경영권(5.01) 등은 note 참조
SEC_ITEM_RULES = {
    "2.02": ("HIGH", "분기/연간 실적(Results of Operations)"),
    # 아래는 모두 SKIP (빅테크 메인 관심사는 실적)
    "1.01": ("SKIP", "중대계약 체결"),
    "1.02": ("SKIP", "중대계약 종료"),
    "1.03": ("SKIP", "파산·법정관리"),
    "2.01": ("SKIP", "인수·처분 완료"),
    "2.03": ("SKIP", "중대 재무 채무"),
    "2.04": ("SKIP", "중대 재무 의무 발동"),
    "2.05": ("SKIP", "사업구조조정·Exit"),
    "2.06": ("SKIP", "중대 자산손상"),
    "3.01": ("SKIP", "상장폐지 예고"),
    "3.02": ("SKIP", "비공개 증권 발행"),
    "3.03": ("SKIP", "증권권리 변경"),
    "4.01": ("SKIP", "감사인 교체"),
    "4.02": ("SKIP", "재무 비신뢰"),
    "5.01": ("SKIP", "경영권 변경"),
    "5.02": ("SKIP", "임원 변경"),
    "5.03": ("SKIP", "정관 개정"),
    "5.04": ("SKIP", "임원보상계획"),
    "5.05": ("SKIP", "윤리강령"),
    "5.07": ("SKIP", "주주총회 결과"),
    "5.08": ("SKIP", "주주제안"),
    "7.01": ("SKIP", "Regulation FD 공시"),
    "8.01": ("SKIP", "기타 사건"),
    "9.01": ("SKIP", "재무제표/Exhibit"),
}

# priority 우선순위 (같은 공시에 여러 item 있을 때 가장 높은 것 채택)
_PRIORITY_RANK = {"URGENT": 4, "HIGH": 3, "NORMAL": 2, "SKIP": 1}

# Item 2.02 (실적) 등은 Exhibit 99.1 press release 파싱으로 본문 확보
_FETCH_EXHIBIT_ITEMS = {"2.02", "1.01", "8.01", "2.01", "5.01"}

# Exhibit 파싱 캐시 (filing URL → body) — 동일 filing 반복 fetch 방지
_exhibit_cache = {}
_EXHIBIT_CACHE_MAX = 200


def _extract_exhibit_text(ex_url: str, max_chars: int) -> str:
    """단일 Exhibit URL fetch + HTML→텍스트 변환."""
    try:
        from bs4 import BeautifulSoup
        sess = _get_session()
        ex_res = sess.get(ex_url, timeout=15)
        if ex_res.status_code != 200:
            return ""
        ex_soup = BeautifulSoup(ex_res.text, "lxml")
        for tag in ex_soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        parts = []
        for table in ex_soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                cells = [c for c in cells if c]
                if cells:
                    parts.append(" | ".join(cells))
            table.decompose()
        remaining = ex_soup.get_text(separator=" ", strip=True)
        if remaining:
            parts.append(remaining)
        body = "\n".join(parts)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body[:max_chars]
    except Exception as e:
        print(f"[SEC] Exhibit 개별 fetch 실패 ({ex_url[:70]}): {e}")
        return ""


def _fetch_sec_filing_exhibits(filing_index_url: str, max_chars: int = 6000) -> str:
    """SEC 8-K filing index 페이지에서 Exhibit 99.1 (press release) + 99.2 (IR presentation) + 99.3 통합 추출.

    - 99.1: press release (실적 수치·요점)
    - 99.2: Investor Presentation / Supplemental / Earnings Deck (IR 자료)
    - 99.3: Additional supplemental (분기별 디테일)

    각 exhibit을 헤더로 구분해 본문에 이어 붙임. Sonnet이 press release 수치 +
    IR 자료 가이던스·코멘트까지 종합 해석 가능.
    """
    if not filing_index_url:
        return ""
    if filing_index_url in _exhibit_cache:
        return _exhibit_cache[filing_index_url]

    try:
        from bs4 import BeautifulSoup
        sess = _get_session()

        # 1) Index 페이지 fetch
        res = sess.get(filing_index_url, timeout=12)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")

        # 2) Exhibit 99.1 / 99.2 / 99.3 링크 수집
        # 99.1 = press release, 99.2 = IR presentation/supplemental, 99.3 = additional
        exhibit_map = {}  # 99.X → url
        for tr in soup.find_all("tr"):
            row_text = tr.get_text(" ", strip=True).lower()
            a = tr.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if not href.lower().endswith((".htm", ".html")):
                continue
            full = href if href.startswith("http") else f"https://www.sec.gov{href}"

            for num in ["99.1", "99.2", "99.3"]:
                markers = [f"ex-{num}", f"ex{num}", f"exhibit {num}"]
                # 99.1은 press release 표시로도 매칭
                if num == "99.1":
                    markers.append("press release")
                if any(m in row_text for m in markers):
                    if num not in exhibit_map:
                        exhibit_map[num] = full
                    break

        # fallback: 어떤 99 계열이라도
        if not exhibit_map:
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                if "ex-99" in href and href.endswith((".htm", ".html")):
                    full = a["href"] if a["href"].startswith("http") else f"https://www.sec.gov{a['href']}"
                    exhibit_map.setdefault("fallback", full)

        if not exhibit_map:
            _exhibit_cache[filing_index_url] = ""
            return ""

        # 3) 각 exhibit 별 본문 추출 + 합치기
        # 99.1에 주 수치, 99.2에 IR 가이던스/presentation
        parts = []
        budget_per_exhibit = max(1500, max_chars // max(len(exhibit_map), 1))
        for label, url in sorted(exhibit_map.items()):
            text = _extract_exhibit_text(url, budget_per_exhibit)
            if not text:
                continue
            header = {
                "99.1": "[Exhibit 99.1 — Press Release (실적 요점)]",
                "99.2": "[Exhibit 99.2 — Investor Presentation / IR 자료]",
                "99.3": "[Exhibit 99.3 — Supplemental]",
            }.get(label, f"[Exhibit {label}]")
            parts.append(f"{header}\n{text}")

        combined = "\n\n".join(parts)[:max_chars]

        # LRU 캐시
        if len(_exhibit_cache) >= _EXHIBIT_CACHE_MAX:
            for k in list(_exhibit_cache.keys())[:50]:
                _exhibit_cache.pop(k, None)
        _exhibit_cache[filing_index_url] = combined
        return combined
    except Exception as e:
        print(f"[SEC] Exhibit fetch 실패 ({filing_index_url[:70]}): {e}")
        _exhibit_cache[filing_index_url] = ""
        return ""


def _parse_items_from_summary(summary: str) -> list:
    """atom summary에서 Item 번호 추출. 예: 'Item 2.02: Results of Operations'"""
    import re as _re
    return _re.findall(r"Item\s+(\d+\.\d+)", summary or "")


def _pick_item_priority(items: list) -> tuple:
    """Items 리스트에서 가장 높은 우선순위 + 라벨 선정.

    Returns:
        (priority, label, matched_item) — 매칭 없으면 (None, "", "")
    """
    if not items:
        return (None, "", "")

    best_priority = None
    best_label = ""
    best_item = ""
    best_rank = 0

    for item in items:
        rule = SEC_ITEM_RULES.get(item)
        if not rule:
            continue
        pri, label = rule
        rank = _PRIORITY_RANK.get(pri, 0)
        if rank > best_rank:
            best_rank = rank
            best_priority = pri
            best_label = label
            best_item = item

    return (best_priority, best_label, best_item)


def _extract_accession(entry_url: str) -> str:
    """filing URL에서 accession number 추출.
    예: .../data/1045810/000104581026000123/... → 0001045810-26-000123
    """
    m = re.search(r"/data/\d+/(\d{10})(\d{2})(\d{6})", entry_url or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m2 = re.search(r"accession[-_]?number=([\d\-]+)", entry_url or "")
    if m2:
        return m2.group(1)
    return ""


def _fetch_cik_8k_atom(cik: str, count: int = 5) -> list:
    """단일 CIK의 최근 8-K atom feed 파싱."""
    try:
        import feedparser
    except ImportError:
        print("[SEC] feedparser 없음 — pip install feedparser")
        return []

    url = SEC_ATOM_URL.format(cik=cik, count=count)
    try:
        res = _get_session().get(url, timeout=15)
        if res.status_code != 200:
            print(f"[SEC] CIK={cik} HTTP {res.status_code}")
            return []
        feed = feedparser.parse(res.content)
    except Exception as e:
        print(f"[SEC] CIK={cik} fetch 실패: {e}")
        return []

    if not feed.entries:
        return []

    out = []
    for entry in feed.entries:
        out.append({
            "title": (entry.get("title") or "").strip(),
            "link": entry.get("link") or "",
            "summary": (entry.get("summary") or "").strip(),
            "published": entry.get("updated") or entry.get("published") or "",
            "atom_id": entry.get("id") or "",
        })
    return out


def _parse_iso_datetime(s: str) -> datetime.datetime:
    """'2026-04-22T13:45:00-04:00' → aware datetime. 실패 시 None."""
    if not s:
        return None
    try:
        # Python 3.11+ fromisoformat은 타임존 포함 ISO 지원
        return datetime.datetime.fromisoformat(s)
    except Exception:
        pass
    # 구버전 대비: tz offset 수동 처리
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", s or "")
    if not m:
        return None
    try:
        dt = datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
        return dt.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def collect_sec_8k_filings(per_cik_limit: int = 5, days_back: int = 2,
                           freshness_hours: int = None) -> list:
    """
    추적 기업 전체의 최근 8-K 수집.

    seen_ids 기반 dedup은 상위(main.py)에서 처리.
    여기선 raw event list만 반환.

    Args:
        per_cik_limit: CIK당 최근 N건 (기본 5, dedup 여유분)
        days_back: 최근 N일 이내 공시만 유지 (날짜 단위, 기본 2일)
        freshness_hours: 시간 단위 신선도 필터 — 이 값 초과 공시는 skip.
            None이면 config.SEC_FILING_FRESHNESS_HOURS(기본 24h) 사용.
            서버 재시작/새 기업 추가 시 backlog(이미 시장 소화된 과거 공시) 카드 방지.

    Returns:
        list of 이슈 이벤트 dict. 발행시간 내림차순(최신이 앞).
    """
    events = []
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")

    # 시간 단위 freshness cutoff (tz-aware, UTC 기준)
    hours = freshness_hours if freshness_hours is not None else SEC_FILING_FRESHNESS_HOURS
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    freshness_cutoff = now_utc - datetime.timedelta(hours=hours)
    stale_count = 0

    for ticker, (cik, company_name) in SEC_TRACKED_COMPANIES.items():
        try:
            entries = _fetch_cik_8k_atom(cik, count=per_cik_limit)
        except Exception as e:
            print(f"[SEC] {ticker} ({cik}) 수집 오류: {e}")
            entries = []

        for ent in entries:
            accession = _extract_accession(ent["link"]) or ent["atom_id"][-20:]
            if not accession:
                continue

            pub_raw = ent.get("published", "")
            date_str = _parse_iso_date(pub_raw) or datetime.date.today().strftime("%Y-%m-%d")

            # days_back 이전 공시는 스킵
            if date_str < cutoff_date:
                continue

            # 시간 단위 신선도 필터 (backlog 방지)
            pub_dt = _parse_iso_datetime(pub_raw)
            if pub_dt is not None:
                # 타임존 없으면 UTC로 가정
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                if pub_dt < freshness_cutoff:
                    stale_count += 1
                    continue

            summary = _strip_html(ent["summary"])[:1200]

            # Item 파싱 + rule-based priority 힌트
            items = _parse_items_from_summary(summary)
            item_priority, item_label, matched_item = _pick_item_priority(items)

            # HIGH/URGENT 중요 Item이면 Exhibit 99.1 (press release) 본문 추가 주입
            # → Sonnet이 "제출 사실"만 보고 생성하는 대신 실제 실적 수치로 작성
            exhibit_body = ""
            if matched_item in _FETCH_EXHIBIT_ITEMS and item_priority in ("HIGH", "URGENT"):
                exhibit_body = _fetch_sec_filing_exhibits(ent["link"])
                time.sleep(0.2)  # SEC rate limit

            # 제목에 Item 라벨 반영 (관리자 카드 UX)
            title_clean = ent["title"].replace("8-K", "").strip(" -—:")
            if matched_item and item_label:
                display_title = f"[{ticker}] 8-K Item {matched_item} — {item_label}"
            elif title_clean:
                display_title = f"[{ticker}] 8-K — {title_clean}"
            else:
                display_title = f"[{ticker}] 8-K Current Report"

            # priority_hint: 매칭된 Item 기반 규칙 (Haiku 스킵 가능)
            # 단, SKIP은 필터 호출 없이 즉시 거름 → priority_hint에 SKIP 주입
            priority_hint = item_priority  # None or URGENT/HIGH/NORMAL/SKIP
            rule_reason = (
                f"SEC 8-K Item {matched_item} ({item_label})"
                if matched_item
                else "SEC 8-K — Item 매칭 실패, Haiku 필터 사용"
            )

            # body_excerpt: Exhibit 본문이 있으면 우선, 없으면 atom summary
            body_final = exhibit_body if exhibit_body else summary

            events.append({
                "id": f"sec_{ticker.lower()}_{accession}",
                "source": "SEC",
                "source_url": ent["link"],
                "source_id": accession,
                "fetched_at": now_iso,
                "ticker": ticker,
                "company_name": company_name,
                "corp_code": cik,
                "corp_cls": "",
                "title": display_title,
                "report_nm_raw": ent["title"],
                "report_nm_clean": title_clean,
                "body_excerpt": body_final,
                "category_hint": "C",  # Template C (영문 공시/리서치)
                "priority_hint": priority_hint,
                "rule_match_reason": rule_reason,
                "event_type": "8K",
                "sec_items": items,
                "sec_primary_item": matched_item,
                "has_exhibit_body": bool(exhibit_body),
                "date": date_str,
            })

        time.sleep(0.15)  # SEC rate limit (10 req/sec) 여유있게

    if stale_count > 0:
        print(f"[SEC] 신선도 필터로 {stale_count}건 skip (> {hours}h 경과)")

    # 발행 시간 내림차순 (최신이 먼저) — 상위 파이프라인에서 증분/dedup
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return events


def _parse_iso_date(s: str) -> str:
    """'2026-04-21T13:45:00-04:00' → '2026-04-21'. 실패 시 빈 문자열."""
    if not s:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def _strip_html(s: str) -> str:
    """SEC atom summary의 HTML 태그·엔티티 간단 정리."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 70)
    print(f"SEC 8-K 수집 테스트 — 추적 {len(SEC_TRACKED_COMPANIES)}개 기업")
    print("=" * 70)
    events = collect_sec_8k_filings(per_cik_limit=3)
    print(f"\n수집 결과: {len(events)}건\n")
    for ev in events[:15]:
        print(f"  [{ev['date']}] [{ev['ticker']:<5}] {ev['title'][:60]}")
        print(f"    → {ev['source_url'][:80]}")
        if ev['body_excerpt']:
            print(f"    요약: {ev['body_excerpt'][:100]}")
        print()
