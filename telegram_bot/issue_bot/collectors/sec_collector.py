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

SEC_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count={count}&output=atom"
)


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
        res = requests.get(
            url,
            headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/atom+xml"},
            timeout=15,
        )
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

            title_clean = ent["title"].replace("8-K", "").strip(" -—:")
            display_title = f"[{ticker}] 8-K — {title_clean}" if title_clean else f"[{ticker}] 8-K Current Report"

            summary = _strip_html(ent["summary"])[:1200]

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
                "body_excerpt": summary,
                "category_hint": "C",  # Template C (영문 공시/리서치)
                "priority_hint": None,   # Haiku에게 맡김
                "rule_match_reason": "SEC 8-K — Haiku 필터 필요",
                "event_type": "8K",
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
