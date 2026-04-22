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

from telegram_bot.config import SEC_TRACKED_COMPANIES, SEC_USER_AGENT

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
# 참고: https://www.sec.gov/forms 8-K current report items
SEC_ITEM_RULES = {
    # URGENT — 사업 존속·중대 긴급성
    "1.03": ("URGENT", "파산·법정관리"),
    "2.04": ("URGENT", "중대 재무 의무 발동(Triggering Events)"),
    "4.02": ("URGENT", "과거 재무제표 신뢰성 상실"),
    # HIGH — 실적·M&A·상장·중대계약
    "1.01": ("HIGH", "중대계약 체결(Material Definitive Agreement)"),
    "1.02": ("HIGH", "중대계약 종료"),
    "2.01": ("HIGH", "인수·처분 완료"),
    "2.02": ("HIGH", "분기/연간 실적(Results of Operations)"),
    "2.03": ("HIGH", "중대 재무 채무 창출"),
    "2.05": ("HIGH", "사업구조조정·Exit 비용"),
    "2.06": ("HIGH", "중대 자산손상(Impairment)"),
    "3.01": ("HIGH", "상장폐지 예고"),
    "3.03": ("HIGH", "증권권리 변경"),
    "4.01": ("HIGH", "감사인 교체"),
    "5.01": ("HIGH", "경영권 변경(Changes in Control)"),
    "8.01": ("HIGH", "기타 중대 사건(Other Events)"),
    # NORMAL — 정보성·정기
    "3.02": ("NORMAL", "비공개 증권 발행"),
    "5.03": ("NORMAL", "정관 개정"),
    "5.04": ("NORMAL", "임원보상계획 변경"),
    "5.08": ("NORMAL", "주주제안"),
    "7.01": ("NORMAL", "Regulation FD 공시"),
    "9.01": ("NORMAL", "재무제표/Exhibit 첨부"),
    # SKIP — 대부분 시장 영향 미미
    "5.02": ("SKIP", "임원 변경(Departure of Directors/Officers)"),
    "5.05": ("SKIP", "윤리강령 변경"),
    "5.07": ("SKIP", "주주총회 결과(Submission of Matters to a Vote)"),
}

# priority 우선순위 (같은 공시에 여러 item 있을 때 가장 높은 것 채택)
_PRIORITY_RANK = {"URGENT": 4, "HIGH": 3, "NORMAL": 2, "SKIP": 1}

# Item 2.02 (실적) 등은 Exhibit 99.1 press release 파싱으로 본문 확보
_FETCH_EXHIBIT_ITEMS = {"2.02", "1.01", "8.01", "2.01", "5.01"}

# Exhibit 파싱 캐시 (filing URL → body) — 동일 filing 반복 fetch 방지
_exhibit_cache = {}
_EXHIBIT_CACHE_MAX = 200


def _fetch_sec_filing_exhibits(filing_index_url: str, max_chars: int = 3500) -> str:
    """SEC 8-K filing index 페이지에서 Exhibit 99.1 (press release) 본문 추출.

    실적·중대계약 공시는 Exhibit에 실제 수치·상세 있음.
    Filing은 atom entry의 link로 받음 (주로 -index.htm 페이지).
    """
    if not filing_index_url:
        return ""
    if filing_index_url in _exhibit_cache:
        return _exhibit_cache[filing_index_url]

    try:
        from bs4 import BeautifulSoup
        sess = _get_session()

        # 1) Index 페이지에서 Exhibit 파일 링크 찾기
        res = sess.get(filing_index_url, timeout=12)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")

        exhibit_urls = []
        for tr in soup.find_all("tr"):
            row_text = tr.get_text(" ", strip=True).lower()
            # Exhibit 99.1 (press release) 우선. 2.02 실적이면 99.1에 수치
            if any(marker in row_text for marker in ["ex-99.1", "ex99.1", "exhibit 99.1", "press release"]):
                a = tr.find("a", href=True)
                if a:
                    href = a["href"]
                    if not href.startswith("http"):
                        href = f"https://www.sec.gov{href}"
                    # 실제 문서 (htm/html/pdf). PDF는 스킵.
                    if href.lower().endswith((".htm", ".html")):
                        exhibit_urls.append(href)

        # fallback: 아무 99 계열 exhibit이나 시도
        if not exhibit_urls:
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                if "ex-99" in href and href.endswith((".htm", ".html")):
                    full = a["href"] if a["href"].startswith("http") else f"https://www.sec.gov{a['href']}"
                    exhibit_urls.append(full)

        if not exhibit_urls:
            _exhibit_cache[filing_index_url] = ""
            return ""

        # 2) 첫 번째 Exhibit 본문 fetch
        ex_res = sess.get(exhibit_urls[0], timeout=15)
        if ex_res.status_code != 200:
            _exhibit_cache[filing_index_url] = ""
            return ""
        ex_soup = BeautifulSoup(ex_res.text, "lxml")
        for tag in ex_soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # 3) 본문 추출 — 표 셀은 구분자로 유지 (실적표 많음)
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
        body = body[:max_chars]

        # LRU 캐시
        if len(_exhibit_cache) >= _EXHIBIT_CACHE_MAX:
            for k in list(_exhibit_cache.keys())[:50]:
                _exhibit_cache.pop(k, None)
        _exhibit_cache[filing_index_url] = body
        return body
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


def collect_sec_8k_filings(per_cik_limit: int = 5, days_back: int = 2) -> list:
    """
    추적 기업 전체의 최근 8-K 수집.

    seen_ids 기반 dedup은 상위(main.py)에서 처리.
    여기선 raw event list만 반환.

    Args:
        per_cik_limit: CIK당 최근 N건 (기본 5, dedup 여유분)
        days_back: 최근 N일 이내 공시만 유지 (첫 실행 몰빵 방지, 기본 2일)

    Returns:
        list of 이슈 이벤트 dict. 발행시간 내림차순(최신이 앞).
    """
    events = []
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")

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
