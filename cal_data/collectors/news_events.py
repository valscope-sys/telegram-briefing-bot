"""뉴스/RSS 기반 일정 자동 추출 (게임, 컨퍼런스, K-POP, 전시회, 산업 이벤트)"""
import re
import datetime
import feedparser
import requests
from bs4 import BeautifulSoup

# 카테고리별 RSS/웹 소스
SOURCES = {
    "게임": [
        {"url": "https://store.steampowered.com/feeds/newreleases.xml", "name": "Steam"},
        {"url": "https://www.gamesindustry.biz/feed", "name": "GamesIndustry"},
    ],
    "IT/컨퍼런스": [
        {"url": "https://techcrunch.com/feed/", "name": "TechCrunch"},
    ],
    "엔터/K-POP": [
        {"url": "https://www.soompi.com/feed", "name": "Soompi"},
    ],
    "전시/박람회": [],
}

# 증시 관련 산업이벤트 (2026년)
KNOWN_INDUSTRY_EVENTS_2026 = [
    # IT/반도체 컨퍼런스 (반도체·IT주 직접 영향)
    {"date": "2026-01-06", "endDate": "2026-01-09", "title": "CES 2026", "category": "산업이벤트", "link": "https://www.ces.tech/"},
    {"date": "2026-01-12", "endDate": "2026-01-15", "title": "JP모건 헬스케어 컨퍼런스", "category": "산업이벤트"},
    {"date": "2026-02-23", "endDate": "2026-02-26", "title": "MWC 바르셀로나 2026", "category": "산업이벤트", "link": "https://www.mwcbarcelona.com/"},
    {"date": "2026-03-17", "endDate": "2026-03-21", "title": "GTC 2026 (NVIDIA)", "category": "산업이벤트"},
    {"date": "2026-05-19", "endDate": "2026-05-21", "title": "Google I/O 2026", "category": "산업이벤트"},
    {"date": "2026-06-09", "endDate": "2026-06-13", "title": "WWDC 2026 (Apple)", "category": "산업이벤트"},
    {"date": "2026-06-09", "endDate": "2026-06-11", "title": "컴퓨텍스 타이베이 2026", "category": "산업이벤트"},
    {"date": "2026-09-09", "title": "Apple 아이폰 발표 (예상)", "category": "산업이벤트"},
    {"date": "2026-11-03", "endDate": "2026-11-04", "title": "OpenAI DevDay 2026", "category": "산업이벤트"},
    # 게임쇼 (게임주 직접 영향: 크래프톤, 엔씨, 넷마블, 펄어비스)
    {"date": "2026-03-16", "endDate": "2026-03-20", "title": "GDC 2026", "category": "산업이벤트"},
    {"date": "2026-08-20", "endDate": "2026-08-23", "title": "게임스컴 2026", "category": "산업이벤트"},
    {"date": "2026-09-24", "endDate": "2026-09-26", "title": "도쿄게임쇼 2026", "category": "산업이벤트"},
    {"date": "2026-11-17", "endDate": "2026-11-19", "title": "G-STAR 2026", "category": "산업이벤트"},
    # 전시/박람회 (관련 섹터주 영향)
    {"date": "2026-04-08", "endDate": "2026-04-11", "title": "서울모터쇼 2026", "category": "산업이벤트"},
    {"date": "2026-06-15", "endDate": "2026-06-19", "title": "파리 에어쇼 2026 (방산)", "category": "산업이벤트"},
    {"date": "2026-09-07", "endDate": "2026-09-10", "title": "IFA 베를린 2026 (가전)", "category": "산업이벤트"},
    {"date": "2026-10-06", "endDate": "2026-10-10", "title": "한국전자전 KES 2026", "category": "산업이벤트"},
    # 제약/바이오
    {"date": "2026-06-05", "endDate": "2026-06-09", "title": "ASCO 2026 (미국종양학회)", "category": "산업이벤트"},
    # OPEC
    {"date": "2026-05-28", "title": "OPEC+ 회의", "category": "산업이벤트"},
    {"date": "2026-12-03", "title": "OPEC+ 회의", "category": "산업이벤트"},
]

# 주요 게임 출시 (게임주 영향)
KNOWN_GAME_RELEASES_2026 = [
    {"date": "2026-04-25", "title": "몬스터헌터 와일즈 PC (캡콤)", "category": "산업이벤트"},
]

# 옵션/선물 만기일 (2026년)
EXPIRY_DATES_2026 = [
    # 옵션만기일 (매월 둘째주 목요일)
    {"date": "2026-01-08", "title": "1월 옵션만기일", "category": "만기일"},
    {"date": "2026-02-12", "title": "2월 옵션만기일", "category": "만기일"},
    {"date": "2026-03-12", "title": "3월 선물옵션 동시만기 (쿼드러플위칭)", "category": "만기일"},
    {"date": "2026-04-09", "title": "4월 옵션만기일", "category": "만기일"},
    {"date": "2026-05-14", "title": "5월 옵션만기일", "category": "만기일"},
    {"date": "2026-06-11", "title": "6월 선물옵션 동시만기 (쿼드러플위칭)", "category": "만기일"},
    {"date": "2026-07-09", "title": "7월 옵션만기일", "category": "만기일"},
    {"date": "2026-08-13", "title": "8월 옵션만기일", "category": "만기일"},
    {"date": "2026-09-10", "title": "9월 선물옵션 동시만기 (쿼드러플위칭)", "category": "만기일"},
    {"date": "2026-10-08", "title": "10월 옵션만기일", "category": "만기일"},
    {"date": "2026-11-12", "title": "11월 옵션만기일", "category": "만기일"},
    {"date": "2026-12-10", "title": "12월 선물옵션 동시만기 (쿼드러플위칭)", "category": "만기일"},
]

# 날짜 미확정 일정 (월간/주간)
UNDATED_EVENTS_2026 = [
    {"month": "2026-04", "title": "테슬라 1Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-07", "title": "테슬라 2Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-10", "title": "테슬라 3Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-06", "title": "닌텐도 스위치2 출시 (예상)", "category": "산업이벤트"},
    {"month": "2026-09", "title": "Apple 아이폰 18 출시 (예상)", "category": "산업이벤트"},
    {"week": "2026-04-W4", "title": "삼성전자 1Q 잠정실적 (예상)", "category": "한국실적(잠정)"},
    {"week": "2026-07-W1", "title": "삼성전자 2Q 잠정실적 (예상)", "category": "한국실적(잠정)"},
    {"week": "2026-04-W4", "title": "SK하이닉스 1Q 실적발표 (예상)", "category": "한국실적"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 날짜 추출 패턴
DATE_PATTERNS = [
    re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"),
    re.compile(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})"),
]


def _parse_date_from_text(text: str) -> str | None:
    """텍스트에서 날짜 추출"""
    m = DATE_PATTERNS[0].search(text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            pass

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m2 = DATE_PATTERNS[1].search(text)
    if m2:
        month_name = m2.group(1).lower()
        if month_name in months:
            try:
                mo = months[month_name]
                d = int(m2.group(2))
                y = int(m2.group(3))
                return datetime.date(y, mo, d).isoformat()
            except ValueError:
                pass
    return None


def fetch_known_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """알려진 컨퍼런스/전시회/게임 출시 반환"""
    results = []
    all_known = KNOWN_INDUSTRY_EVENTS_2026 + KNOWN_GAME_RELEASES_2026 + EXPIRY_DATES_2026

    for ev in all_known:
        try:
            ev_start = datetime.date.fromisoformat(ev["date"])
            if ev_start > to_date:
                continue
            ev_end_str = ev.get("endDate", ev["date"])
            ev_end = datetime.date.fromisoformat(ev_end_str)
            if ev_end < from_date:
                continue

            result = {
                "date": ev["date"],
                "time": "",
                "category": ev["category"],
                "title": ev["title"],
                "source": "news",
                "auto": True,
            }
            if ev.get("endDate"):
                result["endDate"] = ev["endDate"]
            if ev.get("link"):
                result["link"] = ev["link"]
            results.append(result)
        except (ValueError, KeyError):
            continue

    # 날짜 미확정 일정 (month 필드)
    for ev in UNDATED_EVENTS_2026:
        month_str = ev.get("month", "")
        if not month_str:
            continue
        try:
            y, m = int(month_str[:4]), int(month_str[5:7])
            month_start = datetime.date(y, m, 1)
            if m == 12:
                month_end = datetime.date(y, 12, 31)
            else:
                month_end = datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)
            if month_end < from_date or month_start > to_date:
                continue
            results.append({
                "date": month_start.isoformat(),
                "endDate": month_end.isoformat(),
                "time": "",
                "category": ev["category"],
                "title": ev["title"],
                "source": "news",
                "auto": True,
                "undated": True,
                "month": month_str,
            })
        except (ValueError, KeyError):
            continue

    # 날짜 미확정 일정 (week 필드: YYYY-MM-W{n})
    for ev in UNDATED_EVENTS_2026:
        week_str = ev.get("week", "")
        if not week_str:
            continue
        try:
            # "2026-04-W4" → 2026년 4월 4째주
            parts = week_str.split("-")
            y, m = int(parts[0]), int(parts[1])
            wn = int(parts[2].replace("W", ""))
            # n째주의 월요일 = 1일 + (n-1)*7, 단 1일의 요일 보정
            first = datetime.date(y, m, 1)
            first_monday = first + datetime.timedelta(days=(7 - first.weekday()) % 7)
            if first.weekday() == 0:
                first_monday = first
            week_start = first_monday + datetime.timedelta(weeks=wn - 1)
            week_end = week_start + datetime.timedelta(days=6)
            if week_end < from_date or week_start > to_date:
                continue
            results.append({
                "date": week_start.isoformat(),
                "endDate": week_end.isoformat(),
                "time": "",
                "category": ev["category"],
                "title": ev["title"],
                "source": "news",
                "auto": True,
                "undated": True,
                "week": week_str,
            })
        except (ValueError, KeyError, IndexError):
            continue

    return results


def fetch_rss_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """RSS에서 일정 관련 기사 추출"""
    results = []

    for category, feeds in SOURCES.items():
        for feed_info in feeds:
            try:
                feed = feedparser.parse(feed_info["url"])
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    link = entry.get("link", "")
                    combined = f"{title} {summary}"

                    # 날짜 키워드 + 이벤트 키워드가 있는 기사만
                    event_keywords = [
                        "출시", "launch", "release", "발매", "개봉",
                        "컨퍼런스", "conference", "summit", "expo",
                        "콘서트", "concert", "comeback", "컴백", "앨범",
                        "전시", "exhibition", "박람회",
                    ]
                    if not any(kw in combined.lower() for kw in event_keywords):
                        continue

                    ev_date = _parse_date_from_text(combined)
                    if not ev_date:
                        continue

                    try:
                        d = datetime.date.fromisoformat(ev_date)
                        if d < from_date or d > to_date:
                            continue
                    except ValueError:
                        continue

                    # 제목에서 핵심만 추출 (80자 제한)
                    clean_title = title[:80].strip()

                    results.append({
                        "date": ev_date,
                        "time": "",
                        "category": category,
                        "title": clean_title,
                        "source": "news",
                        "auto": True,
                        "link": link,
                        "summary": summary[:200].strip() if summary else "",
                    })
            except Exception as e:
                print(f"[NewsEvents] {feed_info['name']} 실패: {e}")
                continue

    return results


def fetch_news_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """뉴스 기반 일정 전체 수집"""
    all_events = []

    known = fetch_known_events(from_date, to_date)
    all_events.extend(known)

    rss = fetch_rss_events(from_date, to_date)
    all_events.extend(rss)

    return all_events
