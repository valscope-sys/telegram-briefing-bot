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
import re
import sys
import time
import hashlib
import datetime
from typing import List

import feedparser
import requests
from bs4 import BeautifulSoup

from telegram_bot.issue_bot.utils.telegram import extract_og_image


# 이슈봇 전용 추가 피드 — 시황봇(news_collector)과 분리 운영
# 2026-04-22 점검: 전자신문 URL 교체, 디지털타임스 제거(공식 RSS 없음)
ISSUE_BOT_EXTRA_FEEDS = [
    # 글로벌 빅테크/아시아 테크
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "group": "해외"},
    {"name": "Seeking Alpha", "url": "https://seekingalpha.com/market_currents.xml", "group": "해외"},
    # 국내 IT/테크 전문
    {"name": "전자신문", "url": "https://rss.etnews.com/Section902.xml", "group": "국내"},
]

# 기사 본문 추출 대상 소스 — 제목+summary만으로 필터 판단이 어려운 전문 매체
DETAIL_FETCH_SOURCES = {"TrendForce"}  # 추후 확장: Digitimes 등

# URL → body 메모리 캐시 (프로세스 수명 동안 유효)
# 동일 기사가 여러 폴링에서 반복 조회될 때 중복 fetch 방지
_article_body_cache = {}
_CACHE_MAX_SIZE = 500


def _cached_fetch_article_body(url: str) -> str:
    if url in _article_body_cache:
        return _article_body_cache[url]
    body = _fetch_article_body(url)
    # 간단한 LRU: 크기 초과 시 가장 오래된 것부터 제거
    if len(_article_body_cache) >= _CACHE_MAX_SIZE:
        for k in list(_article_body_cache.keys())[:50]:
            _article_body_cache.pop(k, None)
    _article_body_cache[url] = body
    return body


_rss_session = None


def _get_rss_session():
    global _rss_session
    if _rss_session is None:
        _rss_session = requests.Session()
        _rss_session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; NODEResearchBot/1.0)"
        })
    return _rss_session


def _fetch_article_body(url: str, max_chars: int = 1500) -> str:
    """기사 URL에서 본문 텍스트 추출 (heuristic).

    TrendForce 같이 RSS summary가 짧은 전문 매체용.
    """
    if not url:
        return ""
    try:
        res = _get_rss_session().get(url, timeout=12)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        # article 우선, 없으면 content 클래스, 없으면 body
        target = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile(r"(article|content|post|body|entry)", re.I))
        )
        if not target:
            target = soup.body or soup

        text = target.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:max_chars]
    except Exception as e:
        print(f"[RSS] 본문 fetch 실패 ({url[:60]}): {e}")
        return ""


def _hash_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _fetch_extra_feeds(max_per_feed: int = 15) -> List[dict]:
    """이슈봇 전용 추가 피드 수집 (news_collector 형식과 호환)."""
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    out = []
    for feed_info in ISSUE_BOT_EXTRA_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"], agent=UA)
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


def collect_rss_events(limit: int = 50, fetch_images: bool = False,
                       max_age_hours: int = 168) -> List[dict]:
    """
    이슈봇용 RSS 이벤트 수집:
    - news_collector.fetch_rss_news() (시황봇과 공유 피드)
    - ISSUE_BOT_EXTRA_FEEDS (이슈봇 전용)

    Args:
        max_age_hours: 기사 나이 제한 (기본 168 = 7일).
            이슈봇은 섹터 전문지(TrendForce 등 주 1~3회) 기사도 커버해야 하므로
            시황봇의 48h보다 크게 설정. dedup이 중복 제거 역할.
    """
    from telegram_bot.collectors.news_collector import fetch_rss_news

    raw = []
    try:
        raw.extend(fetch_rss_news(max_age_hours=max_age_hours))
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
        source_name = article.get("source", "")
        summary = article.get("summary", "") or ""

        # 전문 매체(TrendForce 등): RSS summary 짧음 → 기사 본문 추가 추출 (URL 캐시)
        body = summary
        if source_name in DETAIL_FETCH_SOURCES:
            cache_hit = url in _article_body_cache
            detailed = _cached_fetch_article_body(url)
            if detailed and len(detailed) > len(summary):
                body = detailed
            if not cache_hit:
                time.sleep(0.3)  # rate limit (캐시 히트 시엔 대기 불필요)

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
            "company_name": source_name,
            "corp_code": "",
            "corp_cls": "",
            "title": title,
            "report_nm_raw": None,
            "report_nm_clean": None,
            "body_excerpt": body[:1500],
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
