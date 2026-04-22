"""RSS 어댑터 — 기존 news_collector.py 재활용 + 이슈봇 파이프라인 연결

DART와의 차이:
- ticker/corp_code 없음
- report_nm 없음 → rule-based 분류 불가 → Haiku 필터 100% 호출
- og:image 추출 가능 (approval/bot.py에서 lazy 처리)
- dedup_key는 URL 해시 기반
"""
import os
import sys
import hashlib
import datetime
from typing import List

from telegram_bot.issue_bot.utils.telegram import extract_og_image


def _hash_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def collect_rss_events(limit: int = 50, fetch_images: bool = False) -> List[dict]:
    """기존 news_collector의 RSS 수집 결과를 이슈봇 이벤트 형식으로 변환."""
    from telegram_bot.collectors.news_collector import fetch_rss_news

    try:
        raw = fetch_rss_news()
    except Exception as e:
        print(f"[RSS] fetch_rss_news 실패: {e}")
        return []

    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    events = []

    for article in raw[:limit]:
        url = article.get("link", "").strip()
        title = article.get("title", "").strip()
        if not url or not title:
            continue

        uid = _hash_url(url)
        summary = article.get("summary", "") or ""

        image_url = None
        if fetch_images:
            image_url = extract_og_image(url)

        event = {
            "id": f"rss_{uid}",
            "source": "RSS",
            "source_url": url,
            "source_id": url,
            "fetched_at": now_iso,
            "ticker": None,
            "company_name": article.get("source", ""),
            "corp_code": "",
            "corp_cls": "",
            "title": title,
            "report_nm_raw": None,
            "report_nm_clean": None,
            "body_excerpt": summary[:1500],
            "category_hint": None,
            "priority_hint": None,
            "rule_match_reason": "RSS — Haiku 필터 필요",
            "event_type": "rss",
            "date": now_iso[:10],
            "image_url": image_url,
            "article_group": article.get("group", ""),
            "article_published": article.get("published", ""),
        }
        events.append(event)

    return events


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    events = collect_rss_events(limit=20, fetch_images=False)
    print(f"RSS 수집: {len(events)}건\n")
    for ev in events[:15]:
        print(f"  [{ev['article_group']:<4}] [{ev['company_name'][:12]:<12}] {ev['title'][:60]}")
