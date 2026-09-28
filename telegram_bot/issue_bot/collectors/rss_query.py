"""RSS 헤드라인 조회 — on-demand /news 명령어 전용

사용자가 봇 DM에 `/news [날짜|키워드]` 입력 시 호출.
- 인자 없음 또는 "오늘": 핵심 매체 최근 24h 헤드라인
- "어제": 24h~48h
- 그 외: Google News RSS 키워드 검색 (503 차단·0건 시 Bing News RSS fallback)

영문 기사는 Haiku로 한국어 번역 + 1줄 요약 (translate_summarize_batch).
"""
import datetime
import re
import time
from itertools import zip_longest

from telegram_bot.llm_client import get_client
import feedparser

from telegram_bot.config import ANTHROPIC_API_KEY


# 핵심 매체 RSS — 시황·테크·외신 균형 (18개)
NEWS_FEEDS = [
    # ── 한국 종합·시황 (7개) ──
    {"name": "한국경제", "url": "https://www.hankyung.com/feed/all-news", "lang": "ko"},
    {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/", "lang": "ko"},
    {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/economy.xml", "lang": "ko"},
    # 이데일리: https 호스트는 연결 리셋(2026-09) → http 만 응답
    {"name": "이데일리", "url": "http://rss.edaily.co.kr/stock_news.xml", "lang": "ko"},
    {"name": "머니투데이", "url": "https://rss.mt.co.kr/mt_news.xml", "lang": "ko"},
    # 조선비즈·인포맥스: Google News site: 검색(503 차단 잦음) → 매체 공식 RSS
    {"name": "조선비즈", "url": "https://biz.chosun.com/arc/outboundfeeds/rss/category/stock/?outputType=xml", "lang": "ko"},
    # 인포맥스 pubDate 는 타임존 없는 KST ('2026-09-28 10:46:27') → naive_kst 보정
    {"name": "인포맥스", "url": "https://news.einfomax.co.kr/rss/allArticle.xml", "lang": "ko", "naive_kst": True},
    # ── 한국 테크 1차 ──
    {"name": "전자신문", "url": "https://rss.etnews.com/Section902.xml", "lang": "ko"},
    # ── 외신 광역 (4개) ──
    # Reuters는 공식 RSS 없음 → Google News 유지, 실패 시 Bing News RSS 자동 fallback
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
    {"name": "Bloomberg Tech", "url": "https://feeds.bloomberg.com/technology/news.rss", "lang": "en"},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "lang": "en"},
    # WSJ: 구 feeds.a.dj.com 은 2025-01 이후 갱신 중단 → Dow Jones 신규 피드 도메인
    {"name": "WSJ Markets", "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "lang": "en"},
    {"name": "Financial Times", "url": "https://www.ft.com/markets?format=rss", "lang": "en"},
    # ── 아시아 ──
    # Nikkei Asia RSS 1.0 은 발행일 필드 없음 → 기간 필터 없이 통과 (최신순 피드)
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "lang": "en"},
    # ── 반도체·테크 전문 (4개) ──
    # TrendForce: /news/feed/ → /news/feed_v2/ 로 301, 쿼리 없는 URL은 7/1자 캐시가 고정 반환됨
    #   → cache_bust 로 매 호출 쿼리스트링 부착해야 최신 기사 수신
    {"name": "TrendForce", "url": "https://www.trendforce.com/news/feed_v2/", "lang": "en", "cache_bust": True},
    {"name": "Digitimes", "url": "https://www.digitimes.com/rss/daily.xml", "lang": "en"},
    # SemiAnalysis: semianalysis.com/feed 는 2025-09 이후 갱신 중단 → Substack 뉴스레터 피드
    {"name": "SemiAnalysis", "url": "https://newsletter.semianalysis.com/feed", "lang": "en"},
    {"name": "Tom's Hardware", "url": "https://www.tomshardware.com/feeds/all", "lang": "en"},
    # AnandTech: 2024-08 폐간(아카이브만 유지, RSS 0건) → 제거
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NODEResearchBot/1.0"


def _feed_url(feed_info: dict) -> str:
    """피드 URL (cache_bust 피드는 시간 단위 쿼리 부착 — CDN 고정 캐시 회피)."""
    url = feed_info["url"]
    if feed_info.get("cache_bust"):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}_={datetime.datetime.now().strftime('%Y%m%d%H')}"
    return url


def _google_to_bing_url(google_url: str, since: datetime.datetime = None) -> str:
    """Google News RSS 검색 URL → 같은 검색어의 Bing News RSS URL (Google 503 차단 대비 fallback).

    Bing 기본 정렬은 관련도라 몇 주 전 기사가 섞임 → since 가 있으면 기간 필터(qft interval) 부착
    (interval "7"=24시간, "8"=7일, "9"=30일).
    """
    from urllib.parse import urlparse, parse_qs, quote_plus
    qs = parse_qs(urlparse(google_url).query)
    q = (qs.get("q") or [""])[0]
    hl = (qs.get("hl") or ["ko"])[0]
    if hl.lower().startswith("ko"):
        url = f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss&setlang=ko-KR&cc=KR"
    else:
        url = f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss&setlang=en-US&cc=US"
    if since is not None:
        age = datetime.datetime.now() - since
        if age <= datetime.timedelta(hours=24):
            interval = "7"
        elif age <= datetime.timedelta(days=7):
            interval = "8"
        else:
            interval = "9"
        url += f"&qft=interval%3d%22{interval}%22"
    return url


def _struct_utc_to_local(pub, naive_kst: bool = False) -> datetime.datetime:
    """feedparser *_parsed(항상 UTC struct_time) → 서버 로컬 naive datetime.

    호출부의 from_dt/to_dt 는 datetime.now() (로컬 naive) 기준인데, 예전엔 UTC 값을 그대로
    naive 로 만들어 비교 → KST 서버에서 '최근 24h' 가 실제로는 15h 창 + 표시 시각 9h 어긋남.
    """
    import calendar
    ts = calendar.timegm(pub)
    if naive_kst:
        # 타임존 표기 없는 KST 시각(예: 인포맥스 '2026-09-28 10:46:27') — feedparser가 UTC로 간주하므로 보정
        ts -= 9 * 3600
    elif ts > time.time() + 600 and ts - 9 * 3600 <= time.time() + 600:
        # 미래 시각이면 KST를 UTC로 잘못 표기한 피드로 보고 보정
        ts -= 9 * 3600
    return datetime.datetime.fromtimestamp(ts)


def _unwrap_bing_link(link: str) -> str:
    """Bing News RSS 링크(apiclick.aspx?...&url=원문) → 원문 URL."""
    if "bing.com/news/apiclick" not in (link or ""):
        return link
    from urllib.parse import urlparse, parse_qs
    target = (parse_qs(urlparse(link).query).get("url") or [""])[0]
    return target or link


# Google News가 "automated queries" 503 을 주면 일정 시간 Google 호출 생략
_GOOGLE_BLOCK_COOLDOWN_S = 30 * 60
_google_blocked_until = 0.0


def _parse_feed_loud(url: str, label: str, since: datetime.datetime = None):
    """feedparser.parse + 실패 시 ERROR 출력. Google News 실패 시 Bing News로 1회 fallback.

    feedparser는 HTTP 4xx/5xx·연결 실패에도 예외 없이 entries=[] 를 반환하므로
    상태를 직접 확인해 조용한 실패를 막는다.
    Returns: (feed, used_url)
    """
    global _google_blocked_until
    is_google = "news.google.com/rss/search" in url
    if is_google and time.time() < _google_blocked_until:
        # 직전 503 차단 후 쿨다운 중 — Google 재시도(건당 ~8초 낭비) 없이 바로 Bing
        feed = feedparser.FeedParserDict(entries=[], bozo=0)
        print(f"[NEWS_QUERY] {label}: Google News 차단 쿨다운 중 → Bing 직행")
    else:
        feed = feedparser.parse(url, agent=UA)
        status = getattr(feed, "status", None)
        if feed.entries and not (status and status >= 400):
            return feed, url
        if is_google and status in (429, 503):
            _google_blocked_until = time.time() + _GOOGLE_BLOCK_COOLDOWN_S
        if status and status >= 400:
            reason = f"HTTP {status}"
        elif not status:
            reason = f"연결 실패: {str(feed.get('bozo_exception', '') or '')[:100]}"
        elif feed.get("bozo"):
            reason = f"HTTP {status}, 파싱 실패: {str(feed.get('bozo_exception', '') or '')[:100]}"
        else:
            reason = f"HTTP {status}, 항목 없음"
        print(f"[NEWS_QUERY] ERROR: {label} 피드 0건 ({reason}) url={url[:120]}")
    if is_google:
        bing_url = _google_to_bing_url(url, since=since)
        # Bing News RSS 는 가끔(5회 중 1회꼴) HTTP 200 + 0건을 줌 → 최대 3회 시도
        for attempt in range(3):
            fb = feedparser.parse(bing_url, agent=UA)
            fb_status = getattr(fb, "status", None)
            if fb.entries or (fb_status and fb_status >= 400):
                break
            time.sleep(0.7)
        if fb.entries and not (fb_status and fb_status >= 400):
            print(f"[NEWS_QUERY] {label}: Bing News RSS fallback 사용 ({len(fb.entries)}건)")
            return fb, bing_url
        print(f"[NEWS_QUERY] ERROR: {label} Bing fallback 도 실패 (HTTP {fb_status}, {len(fb.entries)}건)")
    return feed, url


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
    failed_feeds = []
    for feed_info in NEWS_FEEDS:
        articles = []
        try:
            feed, _used_url = _parse_feed_loud(_feed_url(feed_info), feed_info["name"], since=from_dt)
            if not feed.entries:
                failed_feeds.append(feed_info["name"])
            for entry in feed.entries[:max_per_feed]:
                title = (entry.get("title") or "").strip()
                link = _unwrap_bing_link((entry.get("link") or "").strip())
                if not title or not link:
                    continue

                # 발행일 파싱 + 범위 필터
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_dt = None
                if pub:
                    try:
                        pub_dt = _struct_utc_to_local(pub, naive_kst=feed_info.get("naive_kst", False))
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
            print(f"[NEWS_QUERY] ERROR: {feed_info['name']} 실패: {type(e).__name__}: {e}")
            failed_feeds.append(feed_info["name"])
        feed_results.append(articles)
        time.sleep(0.1)

    if failed_feeds:
        print(f"[NEWS_QUERY] ERROR: {len(failed_feeds)}/{len(NEWS_FEEDS)}개 피드 수집 실패: {', '.join(failed_feeds)}")

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
    from urllib.parse import quote_plus
    # 공백·특수문자 인코딩 필수 — 예전엔 "SK하이닉스 HBM" 처럼 공백 포함 시
    # "URL can't contain control characters" 예외로 0건 반환
    q = quote_plus(keyword or "")
    if lang == "en":
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    else:
        url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"

    results = []
    try:
        feed, _used_url = _parse_feed_loud(url, f"keyword '{keyword}'", since=from_dt)
        for entry in feed.entries[:max_results]:
            title = (entry.get("title") or "").strip()
            link = _unwrap_bing_link((entry.get("link") or "").strip())
            if not title or not link:
                continue

            # 발행일 파싱
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt = None
            if pub:
                try:
                    pub_dt = _struct_utc_to_local(pub)
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
            if not source and entry.get("news_source"):  # Bing News RSS
                source = str(entry.get("news_source")).strip()
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
        print(f"[NEWS_QUERY] ERROR: keyword search '{keyword}' 실패: {type(e).__name__}: {e}")

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
        client = get_client(ANTHROPIC_API_KEY)
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
