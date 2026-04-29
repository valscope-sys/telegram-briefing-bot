"""RSS 헤드라인 조회 — on-demand /news 명령어 전용

사용자가 봇 DM에 `/news [날짜|키워드]` 입력 시 호출.
- 인자 없음 또는 "오늘": 핵심 매체 최근 24h 헤드라인
- "어제": 24h~48h
- 그 외: Google News RSS 키워드 검색

영문 기사는 Haiku로 한국어 번역 + 1줄 요약 (translate_summarize_batch).
"""
import datetime
import re
import time
from itertools import zip_longest

import anthropic
import feedparser

from telegram_bot.config import ANTHROPIC_API_KEY


# 핵심 매체 RSS — 시황·테크·외신 균형 (13개)
NEWS_FEEDS = [
    # ── 한국 종합·시황 ──
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news", "lang": "ko"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/", "lang": "ko"},
    {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/economy.xml", "lang": "ko"},
    {"name": "이데일리", "url": "https://rss.edaily.co.kr/stock_news.xml", "lang": "ko"},
    {"name": "머니투데이", "url": "https://rss.mt.co.kr/mt_news.xml", "lang": "ko"},
    # ── 한국 테크 1차 ──
    {"name": "전자신문", "url": "https://rss.etnews.com/Section902.xml", "lang": "ko"},
    # ── 외신 광역 ──
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
    {"name": "Bloomberg Tech", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+technology&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "lang": "en"},
    {"name": "Financial Times", "url": "https://news.google.com/rss/search?q=site:ft.com+markets&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
    # ── 아시아 ──
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "lang": "en"},
    # ── 반도체·테크 전문 ──
    {"name": "TrendForce", "url": "https://www.trendforce.com/news/feed/", "lang": "en"},
    {"name": "Digitimes", "url": "https://news.google.com/rss/search?q=site:digitimes.com+chips+OR+semiconductor&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NODEResearchBot/1.0"


def _attach_lang(article: dict, feed_info: dict) -> dict:
    """피드 lang 정보를 article에 부착."""
    article["lang"] = feed_info.get("lang", "en")
    return article


def fetch_news_headlines(max_age_hours: int = 24, max_per_feed: int = 5,
                         from_dt: datetime.datetime = None,
                         to_dt: datetime.datetime = None) -> list:
    """모든 핵심 RSS 피드에서 헤드라인 수집.

    Args:
        max_age_hours: from_dt가 None일 때 fallback. 최근 N시간.
        max_per_feed: 피드당 최대 fetch 수
        from_dt: 시작 시각 (포함). 명시되면 max_age_hours 무시.
        to_dt: 끝 시각 (포함). 명시 X면 현재.

    Returns:
        [{"title", "link", "source", "published", "published_dt"}, ...]
        피드별 인터리빙 + 시간 정렬 (최신 우선).
    """
    if from_dt is None:
        from_dt = datetime.datetime.now() - datetime.timedelta(hours=max_age_hours)
    if to_dt is None:
        to_dt = datetime.datetime.now()

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

                # 발행일 파싱 + 범위 필터
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_dt = None
                if pub:
                    try:
                        pub_dt = datetime.datetime(*pub[:6])
                        if pub_dt < from_dt or pub_dt > to_dt:
                            continue
                    except Exception:
                        pass
                # pub_dt 없으면 통과시킴 (RSS가 published 안 줄 때 보수적)

                articles.append({
                    "title": title,
                    "link": link,
                    "source": feed_info["name"],
                    "lang": feed_info.get("lang", "en"),
                    "published": entry.get("published", ""),
                    "published_dt": pub_dt,
                })
        except Exception as e:
            print(f"[NEWS_QUERY] {feed_info['name']} 실패: {e}")
        feed_results.append(articles)
        time.sleep(0.1)

    # 인터리빙
    interleaved = [
        a for tup in zip_longest(*feed_results)
        for a in tup if a is not None
    ]
    # published_dt 있는 것은 최신 우선 정렬, 없는 것은 뒤
    interleaved.sort(
        key=lambda x: x.get("published_dt") or datetime.datetime.min,
        reverse=True,
    )
    return interleaved


def search_keyword_news(keyword: str, max_results: int = 30, lang: str = "ko",
                        from_dt: datetime.datetime = None,
                        to_dt: datetime.datetime = None) -> list:
    """Google News RSS로 키워드 검색.

    Args:
        keyword: 검색어 (한글·영문)
        max_results: 최대 결과 수
        lang: "ko"(한국) / "en"(영문)
        from_dt, to_dt: 시간 범위 (포함). None이면 무시.
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

            # 발행일 파싱
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt = None
            if pub:
                try:
                    pub_dt = datetime.datetime(*pub[:6])
                    if from_dt and pub_dt < from_dt:
                        continue
                    if to_dt and pub_dt > to_dt:
                        continue
                except Exception:
                    pass

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
                "lang": lang,
                "published": entry.get("published", ""),
                "published_dt": pub_dt,
            })
    except Exception as e:
        print(f"[NEWS_QUERY] keyword search '{keyword}' 실패: {e}")

    # 시간 정렬 (최신 우선)
    results.sort(
        key=lambda x: x.get("published_dt") or datetime.datetime.min,
        reverse=True,
    )
    return results


# ===== 인자 파싱 (시간 범위 / 상대 시간) =====

import re as _re

_TIME_RANGE_RE = _re.compile(r"^(\d{1,2}):?(\d{2})?-(\d{1,2}):?(\d{2})?$")
_RELATIVE_RE = _re.compile(r"^(\d+)\s*([hmHM])$")


def parse_time_arg(arg: str, base_date: datetime.date = None):
    """시간 인자 파싱.

    Args:
        arg: "09:00-12:00" / "0900-1200" / "9-12" / "3h" / "30m"
        base_date: 시간 범위의 기준 날짜 (default: 오늘)

    Returns:
        (from_dt, to_dt) 또는 None (파싱 실패)
    """
    arg = (arg or "").strip()
    if not arg:
        return None

    base_date = base_date or datetime.date.today()
    now = datetime.datetime.now()

    # 1. 상대 시간: "3h", "30m"
    m = _RELATIVE_RE.match(arg)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "h":
            return (now - datetime.timedelta(hours=n), now)
        if unit == "m":
            return (now - datetime.timedelta(minutes=n), now)

    # 2. 시간 범위: "09:00-12:00" / "9-12" / "0900-1200"
    m = _TIME_RANGE_RE.match(arg)
    if m:
        h1 = int(m.group(1))
        m1 = int(m.group(2)) if m.group(2) else 0
        h2 = int(m.group(3))
        m2 = int(m.group(4)) if m.group(4) else 0
        if 0 <= h1 < 24 and 0 <= h2 < 24 and 0 <= m1 < 60 and 0 <= m2 < 60:
            from_dt = datetime.datetime.combine(
                base_date, datetime.time(h1, m1)
            )
            to_dt = datetime.datetime.combine(
                base_date, datetime.time(h2, m2)
            )
            if to_dt < from_dt:  # 자정 넘김
                to_dt += datetime.timedelta(days=1)
            return (from_dt, to_dt)

    return None


# ===== Haiku 번역 + 요약 (영문 기사 batch 처리) =====

_TRANSLATE_SYSTEM = """당신은 금융·산업 뉴스 헤드라인 번역·요약 전문가입니다.
영문 → 간결한 한국어 헤드라인 + 1줄 요약. 핵심만, 마크다운/이모지 금지.

응답 형식 (각 항목, 정확히 이 형식만):
1. {한국어 헤드라인}
   {1줄 요약 (50자 이내)}

2. {한국어 헤드라인}
   {1줄 요약}

다른 설명·인사·번호 외 텍스트 금지."""


def _parse_translation_response(text: str) -> list:
    """Haiku 응답을 [{title, summary}] 리스트로 파싱."""
    items = []
    blocks = re.split(r'\n(?=\d+\.\s)', text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        block = re.sub(r'^\d+\.\s*', '', block)
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        title = lines[0]
        summary = ' '.join(lines[1:]) if len(lines) > 1 else ""
        items.append({"title": title, "summary": summary})
    return items


def translate_summarize_batch(items: list, max_items: int = 10) -> list:
    """영문 기사 batch 번역 + 1줄 요약. 한글은 그대로 + 요약은 비워둠.

    Args:
        items: fetch 결과 (lang 필드 'en' / 'ko')
        max_items: 한 번에 처리할 최대 건수 (Haiku 컨텍스트 한계 + 비용)

    Returns:
        items에 'title_kr', 'summary_kr' 필드 추가하여 반환.
        영문 기사: title_kr=번역된 한국어 / summary_kr=1줄 요약
        한글 기사: title_kr=원본 / summary_kr="" (요약 생략, 비용 절감)
    """
    targets = items[:max_items]

    # 모든 항목에 기본값 채움
    for it in targets:
        it["title_kr"] = it.get("title", "")
        it["summary_kr"] = ""

    # 영문 항목만 추출 (한글은 번역 불필요)
    en_indices = [i for i, it in enumerate(targets) if it.get("lang") == "en"]
    if not en_indices or not ANTHROPIC_API_KEY:
        return targets

    # batch 프롬프트 조립
    lines = []
    for batch_idx, orig_idx in enumerate(en_indices, 1):
        title = targets[orig_idx].get("title", "")[:200]
        lines.append(f"{batch_idx}. {title}")

    user_msg = (
        f"다음 영문 헤드라인 {len(en_indices)}건을 한국어로 번역 + 1줄 요약:\n\n"
        + "\n".join(lines)
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_TRANSLATE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        translated = _parse_translation_response(text)

        # 매칭: 응답 순서대로 영문 항목에 채움
        for batch_idx, orig_idx in enumerate(en_indices):
            if batch_idx < len(translated):
                tr = translated[batch_idx]
                if tr.get("title"):
                    targets[orig_idx]["title_kr"] = tr["title"]
                if tr.get("summary"):
                    targets[orig_idx]["summary_kr"] = tr["summary"]
    except Exception as e:
        print(f"[TRANSLATE] Haiku 호출 실패: {e}")
        # 실패 시 원본 그대로 (title_kr=원본 영문)

    return targets


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
        print(f"  [{it['source']} {it['lang']}] {it['title'][:80]}")
