"""RSS 어댑터 — 이슈봇 전용 파이프라인

두 가지 소스를 통합:
1. 기존 news_collector.RSS_FEEDS (브리핑봇과 공유되는 기본 피드 15개)
2. ISSUE_BOT_EXTRA_FEEDS — 이슈봇 전용 추가 피드 (브리핑봇엔 영향 없음)

DART와의 차이:
- ticker/corp_code 없음
- report_nm 없음 → rule-based 분류 불가 → Haiku 필터 100% 호출
- og:image 추출 가능 (approval/bot.py에서 lazy 처리)
- dedup_key는 URL 해시 기반
"""
import os
import sys
import time
import hashlib
import datetime
from typing import List

import feedparser

from telegram_bot.issue_bot.utils.telegram import extract_og_image


# 이슈봇 전용 추가 피드 — 시황봇(news_collector)과 분리 운영
ISSUE_BOT_EXTRA_FEEDS = [
    # 글로벌 빅테크/아시아 테크
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "group": "해외"},
    {"name": "Seeking Alpha", "url": "https://seekingalpha.com/market_currents.xml", "group": "해외"},
    # 국내 IT/테크 전문 (반도체·IT부품 밸류체인)
    {"name": "전자신문", "url": "https://www.etnews.com/rss/section/IT.xml", "group": "국내"},
    {"name": "디지털타임스", "url": "http://www.dt.co.kr/rss/rss_industry.xml", "group": "국내"},
]


def _hash_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _fetch_extra_feeds(max_per_feed: int = 15) -> List[dict]:
    """이슈봇 전용 추가 피드 수집 (news_collector 형식과 호환)."""
    out = []
    for feed_info in ISSUE_BOT_EXTRA_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:max_per_feed]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                out.append({
                    "title": title,
                    "link": link,
                    "summary": (entry.get("summary") or "").strip(),
                    "source": feed_info["name"],
                    "group": feed_info["group"],
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"[RSS-EXTRA] {feed_info['name']} 실패: {e}")
        time.sleep(0.1)
    return out


def collect_rss_events(limit: int = 50, fetch_images: bool = False) -> List[dict]:
    """
    이슈봇용 RSS 이벤트 수집:
    - news_collector.fetch_rss_news() (기본 15개 — 시황봇과 공유)
    - ISSUE_BOT_EXTRA_FEEDS (이슈봇 전용 4개)
    """
    from telegram_bot.collectors.news_collector import fetch_rss_news

    raw = []
    try:
        raw.extend(fetch_rss_news())
    except Exception as e:
        print(f"[RSS] 기본 피드 수집 실패: {e}")

    try:
        raw.extend(_fetch_extra_feeds())
    except Exception as e:
        print(f"[RSS] 이슈봇 전용 피드 수집 실패: {e}")

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
