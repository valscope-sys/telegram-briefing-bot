"""RSS 헤드라인 조회 — on-demand /news 명령어 전용

사용자가 봇 DM에 `/news [날짜|키워드]` 입력 시 호출.
- 인자 없음 또는 "오늘": 핵심 매체 최근 24h 헤드라인
- "어제": 24h~48h
- 그 외: Google News RSS 키워드 검색
"""
import datetime
import time
from itertools import zip_longest

import feedparser


# 핵심 매체 RSS — 시황·테크·외신 균형
NEWS_FEEDS = [
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/"},
    {"name": "전자신문", "url": "https://rss.etnews.com/Section902.xml"},
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Bloomberg Tech", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+technology&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar"},
    {"name": "TrendForce", "url": "https://www.trendforce.com/news/feed/"},
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NODEResearchBot/1.0"


def fetch_news_headlines(max_age_hours: int = 24, max_per_feed: int = 5) -> list:
    """모든 핵심 RSS 피드에서 최신 헤드라인 수집.

    Returns:
        [{"title", "link", "source", "published"}, ...]
        피드별 인터리빙 (피드1[0], 피드2[0], ..., 피드N[0], 피드1[1], ...)
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=max_age_hours)

    feed_results = []
    for feed_info in NEWS_FEEDS:
        articles = []
        try:
            feed = feedparser.parse(feed_info["url"], agent=UA)
            for entry in feed.entries[:max_per_feed]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue

                # 발행일 필터
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    try:
                        pub_dt = datetime.datetime(*pub[:6])
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass

                articles.append({
                    "title": title,
                    "link": link,
                    "source": feed_info["name"],
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"[NEWS_QUERY] {feed_info['name']} 실패: {e}")
        feed_results.append(articles)
        time.sleep(0.1)

    # 인터리빙: 피드별 1번째 → 모든 피드 1번째 → 2번째 ...
    interleaved = [
        a for tup in zip_longest(*feed_results)
        for a in tup if a is not None
    ]
    return interleaved


def search_keyword_news(keyword: str, max_results: int = 30, lang: str = "ko") -> list:
    """Google News RSS로 키워드 검색.

    Args:
        keyword: 검색어 (한글·영문 모두 OK)
        max_results: 최대 결과 수
        lang: "ko"(한국) / "en"(영문) — 검색 언어

    Returns:
        [{"title", "link", "source", "published"}, ...]
    """
    if lang == "en":
        url = f"https://news.google.com/rss/search?q={keyword}&hl=en-US&gl=US&ceid=US:en"
    else:
        url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"

    results = []
    try:
        feed = feedparser.parse(url, agent=UA)
        for entry in feed.entries[:max_results]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            # source 추출 — entry.source.title 또는 title 끝의 "- 매체명"
            source_obj = entry.get("source")
            source = ""
            if source_obj:
                source = getattr(source_obj, "title", "") or (
                    source_obj.get("title", "") if isinstance(source_obj, dict) else ""
                )
            if not source and " - " in title:
                source = title.rsplit(" - ", 1)[1]
                title = title.rsplit(" - ", 1)[0]

            results.append({
                "title": title,
                "link": link,
                "source": source or "Google News",
                "published": entry.get("published", ""),
            })
    except Exception as e:
        print(f"[NEWS_QUERY] keyword search '{keyword}' 실패: {e}")

    return results


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트 1: 오늘 헤드라인
    items = fetch_news_headlines(max_age_hours=24, max_per_feed=3)
    print(f"== 오늘 헤드라인 {len(items)}건 ==")
    for it in items[:10]:
        print(f"  [{it['source']}] {it['title'][:80]}")

    # 테스트 2: 키워드 검색
    print("\n== '반도체' 검색 ==")
    items = search_keyword_news("반도체", max_results=10)
    for it in items[:10]:
        print(f"  [{it['source']}] {it['title'][:80]}")
