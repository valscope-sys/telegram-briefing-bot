"""뉴스/RSS 기반 일정 자동 추출 (게임, 컨퍼런스, K-POP, 전시회, 산업 이벤트)"""
import re
import datetime
import feedparser
import requests
from bs4 import BeautifulSoup

# 카테고리별 RSS/웹 소스
SOURCES = {
    "게임": [
        # Steam: feeds/newreleases.xml 은 2026-07-11 이후 갱신 중단 → Steam 공식 뉴스 허브(앱 593110) 피드
        {"url": "https://store.steampowered.com/feeds/news/app/593110/", "name": "Steam"},
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

# 증시 관련 이벤트 (2026년) — 카테고리별 세분화
KNOWN_INDUSTRY_EVENTS_2026 = [
    # 산업컨퍼런스
    {"date": "2026-01-06", "endDate": "2026-01-09", "title": "CES 2026", "category": "산업컨퍼런스", "link": "https://www.ces.tech/"},
    {"date": "2026-02-23", "endDate": "2026-02-26", "title": "MWC 바르셀로나 2026", "category": "산업컨퍼런스", "link": "https://www.mwcbarcelona.com/"},
    {"date": "2026-03-17", "endDate": "2026-03-21", "title": "GTC 2026 (NVIDIA)", "category": "산업컨퍼런스"},
    {"date": "2026-05-19", "endDate": "2026-05-21", "title": "Google I/O 2026", "category": "산업컨퍼런스"},
    {"date": "2026-06-09", "endDate": "2026-06-13", "title": "WWDC 2026 (Apple)", "category": "산업컨퍼런스"},
    {"date": "2026-06-09", "endDate": "2026-06-11", "title": "컴퓨텍스 타이베이 2026", "category": "산업컨퍼런스"},
    # 2026-09-28 교정: OpenAI DevDay 11/3-4 → 9/29 (샌프란시스코 Fort Mason, 키노트 10am PT = KST 9/30 02:00)
    #   https://openai.com/index/devday-2026/  https://devday.openai.com/
    {"date": "2026-09-29", "title": "OpenAI DevDay 2026", "category": "산업컨퍼런스", "link": "https://devday.openai.com/"},
    # 반도체
    {"date": "2026-09-09", "title": "Apple 신제품 발표 이벤트 (아이폰 18)", "category": "산업컨퍼런스"},  # apple.com 공식 초대장
    # 게임
    {"date": "2026-03-16", "endDate": "2026-03-20", "title": "GDC 2026", "category": "게임"},
    {"date": "2026-08-20", "endDate": "2026-08-23", "title": "게임스컴 2026", "category": "게임"},
    {"date": "2026-09-24", "endDate": "2026-09-26", "title": "도쿄게임쇼 2026", "category": "게임"},
    # 2026-09-28 교정: G-STAR 11/17-19 → 11/19-22 (BTC·BTB 전시, 11/18 게임대상 전야)
    #   https://gstar.or.kr/gstar/gstar_info.do
    {"date": "2026-11-19", "endDate": "2026-11-22", "title": "G-STAR 2026", "category": "게임", "link": "https://gstar.or.kr/"},
    # 자동차/배터리
    {"date": "2026-04-08", "endDate": "2026-04-11", "title": "서울모터쇼 2026", "category": "자동차/배터리"},
    # 방산
    # 전시/박람회
    {"date": "2026-09-07", "endDate": "2026-09-10", "title": "IFA 베를린 2026 (가전)", "category": "전시/박람회"},
    # 2026-09-28 교정: KES 10/6-10 → 10/13-16 (코엑스 A·B홀)
    #   https://www.kes.org/eng/intro/info.asp
    {"date": "2026-10-13", "endDate": "2026-10-16", "title": "한국전자전 KES 2026", "category": "전시/박람회", "link": "https://www.kes.org/"},
    # 제약/바이오
    {"date": "2026-01-12", "endDate": "2026-01-15", "title": "JP모건 헬스케어 컨퍼런스", "category": "제약/바이오"},
    {"date": "2026-06-05", "endDate": "2026-06-09", "title": "ASCO 2026 (미국종양학회)", "category": "제약/바이오"},
    # 에너지
    {"date": "2026-05-28", "title": "OPEC+ 회의", "category": "에너지"},
    # 2026-09-28 교정: 12/3 → 11/29. 41차 ONOMM(6/7) 성명 "Hold the 42nd ONOMM on 29 November 2026"
    #   https://en.shana.ir/news/2120157/OPEC-reaffirms-cooperation-eyes-2027-targets (opec.org 성명 인용)
    {"date": "2026-11-29", "title": "OPEC+ 장관회의 (ONOMM)", "category": "에너지"},
    # 통화정책 (잭슨홀 등 — 고정이벤트 FOMC와 별도)
    {"date": "2026-08-27", "endDate": "2026-08-29", "title": "잭슨홀 심포지엄", "category": "통화정책"},

    # ===== 2026-09-28 추가: 10~12월 굵직한 이벤트 (공식 발표 일정만) =====
    # 산업컨퍼런스 / 반도체
    # OCP Global Summit — https://www.opencompute.org/summit/global-summit
    {"date": "2026-10-12", "endDate": "2026-10-15", "title": "OCP 글로벌 서밋 2026 (데이터센터)", "category": "산업컨퍼런스", "link": "https://www.opencompute.org/summit/global-summit"},
    # SEMICON West 2026 (샌프란시스코 Moscone) — https://www.semi.org/en/semi-press-release/semicon-west-2026-to-spotlight-1-trillion-dollars-semiconductor-milestone-and-technologies-powering-the-industrys-next-era
    {"date": "2026-10-13", "endDate": "2026-10-15", "title": "SEMICON West 2026", "category": "반도체", "link": "https://www.semiconwest.org/"},
    # NVIDIA GTC 베를린 (젠슨 황 키노트 10/21) — https://www.nvidia.com/en-eu/gtc/
    {"date": "2026-10-20", "endDate": "2026-10-22", "title": "GTC 베를린 2026 (NVIDIA)", "category": "산업컨퍼런스", "link": "https://www.nvidia.com/en-eu/gtc/"},
    # AWS re:Invent — https://aws.amazon.com/events/reinvent/faqs/
    {"date": "2026-11-30", "endDate": "2026-12-04", "title": "AWS re:Invent 2026", "category": "산업컨퍼런스", "link": "https://aws.amazon.com/events/reinvent/"},
    # NVIDIA GTC 워싱턴 D.C. (젠슨 황 키노트 12/1 14:00 ET) — https://www.nvidia.com/gtc/dc/
    {"date": "2026-11-30", "endDate": "2026-12-03", "title": "GTC 워싱턴DC 2026 (NVIDIA)", "category": "산업컨퍼런스", "link": "https://www.nvidia.com/gtc/dc/"},
    # SEMICON Japan (도쿄 빅사이트) — https://www.semiconjapan.org/en/about
    {"date": "2026-12-09", "endDate": "2026-12-11", "title": "SEMICON Japan 2026", "category": "반도체", "link": "https://www.semiconjapan.org/en"},
    # 제약/바이오
    # ESMO 2026 (마드리드) — https://www.esmo.org/meeting-calendar/esmo-congress-2026
    {"date": "2026-10-23", "endDate": "2026-10-27", "title": "ESMO 2026 (유럽종양학회)", "category": "제약/바이오", "link": "https://www.esmo.org/meeting-calendar/esmo-congress-2026"},
    # SITC 2026 (피닉스) — https://www.sitcancer.org/2026/home
    {"date": "2026-11-04", "endDate": "2026-11-08", "title": "SITC 2026 (면역항암학회)", "category": "제약/바이오", "link": "https://www.sitcancer.org/2026/home"},
    # EORTC-NCI-AACR (ENA 2026, 바르셀로나) — https://event.eortc.org/ena2026/
    {"date": "2026-11-18", "endDate": "2026-11-20", "title": "EORTC-NCI-AACR 2026 (분자표적 항암 심포지엄)", "category": "제약/바이오", "link": "https://event.eortc.org/ena2026/"},
    # ASH 2026 (뉴올리언스) — https://www.hematology.org/meetings/annual-meeting
    {"date": "2026-12-12", "endDate": "2026-12-15", "title": "ASH 2026 (미국혈액학회)", "category": "제약/바이오", "link": "https://www.hematology.org/meetings/annual-meeting"},
    # 정치/외교
    # 미국 중간선거 — 연방법(11월 첫 월요일 다음 화요일) https://www.fec.gov/
    {"date": "2026-11-03", "title": "미국 중간선거", "category": "정치/외교"},
    # APEC 정상회의 (중국 선전) — https://www.sz.gov.cn/en_szgov/news/infocus/APEC2026/News/content/post_12979720.html
    {"date": "2026-11-18", "endDate": "2026-11-19", "title": "APEC 정상회의 2026 (중국 선전)", "category": "정치/외교"},
    # G20 정상회의 (미국 마이애미 도랄) — https://www.cbsnews.com/news/trump-g20-summit-2026-doral-resort-florida/
    {"date": "2026-12-14", "endDate": "2026-12-15", "title": "G20 정상회의 2026 (미국 마이애미)", "category": "정치/외교"},
]

# 증시 관련 이벤트 (2027년) — 2026-09-28 작성, 공식 발표 일정만 수록
# 미공표(추가 금지, 공표 시 반영): Google I/O·MS Build·WWDC·Hot Chips·TSMC 테크 심포지엄·
#   삼성 파운드리 포럼/SAFE·갤럭시 언팩·Meta Connect·ASH 2027·SEMICON Japan 2027·re:Invent 2027·
#   잭슨홀 2027·APEC 2027(베트남 푸꾸옥, 11월 예정)·G20 2027·OPEC+ 2027 장관회의
KNOWN_INDUSTRY_EVENTS_2027 = [
    # 산업컨퍼런스 / 반도체
    # CES — https://www.ces.tech/plan-your-visit/dates-and-hours/ (미디어데이 1/4-5)
    {"date": "2027-01-06", "endDate": "2027-01-09", "title": "CES 2027", "category": "산업컨퍼런스", "link": "https://www.ces.tech/"},
    # SEMICON Korea (코엑스) — https://www.semiconkorea.org/en
    {"date": "2027-02-17", "endDate": "2027-02-19", "title": "SEMICON Korea 2027", "category": "반도체", "link": "https://www.semiconkorea.org/"},
    # MWC — https://www.mwcbarcelona.com/about/
    {"date": "2027-03-01", "endDate": "2027-03-04", "title": "MWC 바르셀로나 2027", "category": "산업컨퍼런스", "link": "https://www.mwcbarcelona.com/"},
    # NVIDIA GTC (새너제이) — https://www.nvidia.com/gtc/
    {"date": "2027-03-15", "endDate": "2027-03-18", "title": "GTC 2027 (NVIDIA)", "category": "산업컨퍼런스", "link": "https://www.nvidia.com/gtc/"},
    # SEMICON West — 2027년부터 봄 개최(피닉스)
    #   https://www.semi.org/en/semi-press-release/semi-announces-new-spring-schedule-for-semicon-west-beginning-march-30-april-1-2027
    {"date": "2027-03-30", "endDate": "2027-04-01", "title": "SEMICON West 2027 (피닉스)", "category": "반도체", "link": "https://www.semiconwest.org/"},
    # COMPUTEX (타이베이 난강) — https://www.computextaipei.com.tw/en/index.html
    {"date": "2027-06-01", "endDate": "2027-06-04", "title": "컴퓨텍스 타이베이 2027", "category": "산업컨퍼런스", "link": "https://www.computextaipei.com.tw/"},
    # SEMICON Taiwan — 2027년 8월로 앞당김 https://focustaiwan.tw/sci-tech/202609080007
    {"date": "2027-08-18", "endDate": "2027-08-20", "title": "SEMICON Taiwan 2027", "category": "반도체", "link": "https://www.semicontaiwan.org/en"},
    # OCP Global Summit (샌프란시스코 Moscone) — https://www.opencompute.org/blog/ocp-global-summit-is-moving-to-a-new-location
    {"date": "2027-10-04", "endDate": "2027-10-07", "title": "OCP 글로벌 서밋 2027 (데이터센터)", "category": "산업컨퍼런스", "link": "https://www.opencompute.org/summit/global-summit"},
    # 제약/바이오
    # J.P. Morgan Healthcare — https://www.jpmorgan.com/about-us/events-conferences/health-care-conference
    {"date": "2027-01-11", "endDate": "2027-01-14", "title": "JP모건 헬스케어 컨퍼런스 2027", "category": "제약/바이오"},
    # AACR Annual Meeting (올랜도) — https://www.aacr.org/professionals/meetings/future-annual-meetings/
    {"date": "2027-04-02", "endDate": "2027-04-07", "title": "AACR 2027 (미국암연구학회)", "category": "제약/바이오", "link": "https://www.aacr.org/meeting/aacr-annual-meeting-2027/"},
    # ASCO (시카고) — https://www.asco.org/annual-meeting
    {"date": "2027-06-04", "endDate": "2027-06-08", "title": "ASCO 2027 (미국종양학회)", "category": "제약/바이오", "link": "https://www.asco.org/annual-meeting"},
    # BIO International Convention (필라델피아) — https://convention.bio.org/future-dates
    {"date": "2027-06-07", "endDate": "2027-06-10", "title": "BIO 인터내셔널 컨벤션 2027", "category": "제약/바이오", "link": "https://convention.bio.org/"},
    # EHA (바르셀로나) — https://ehaweb.org/connect-network/future-congresses
    {"date": "2027-06-10", "endDate": "2027-06-13", "title": "EHA 2027 (유럽혈액학회)", "category": "제약/바이오", "link": "https://ehaweb.org/connect-network/eha2027-congress"},
    # ADA Scientific Sessions (워싱턴DC) — https://professional.diabetes.org/scientific-sessions
    {"date": "2027-06-18", "endDate": "2027-06-21", "title": "ADA 2027 (미국당뇨병학회)", "category": "제약/바이오", "link": "https://professional.diabetes.org/scientific-sessions"},
    # IASLC WCLC (덴버) — https://www.iaslc.org/meetings-webinars/2027-world-conference-lung-cancer
    {"date": "2027-09-11", "endDate": "2027-09-14", "title": "WCLC 2027 (세계폐암학회)", "category": "제약/바이오", "link": "https://www.iaslc.org/meetings-webinars/2027-world-conference-lung-cancer"},
    # ESMO 2027 (바르셀로나) — https://www.esmo.org/meeting-calendar/esmo-congress-2027
    {"date": "2027-09-17", "endDate": "2027-09-21", "title": "ESMO 2027 (유럽종양학회)", "category": "제약/바이오", "link": "https://www.esmo.org/meeting-calendar/esmo-congress-2027"},
    # AACR-NCI-EORTC (시카고) — https://www.aacr.org/meeting/aacr-nci-eortc-international-conference-molecular-targets-and-cancer-therapeutics/
    {"date": "2027-10-26", "endDate": "2027-10-30", "title": "AACR-NCI-EORTC 2027 (분자표적 항암 학회)", "category": "제약/바이오"},
    # SITC 2027 (내셔널하버) — https://www.sitcancer.org/edu/41st-annual-meeting/archive
    {"date": "2027-11-03", "endDate": "2027-11-07", "title": "SITC 2027 (면역항암학회)", "category": "제약/바이오"},
]

# 주요 게임 출시 (게임주 영향)
KNOWN_GAME_RELEASES_2026 = [
    {"date": "2026-04-25", "title": "몬스터헌터 와일즈 PC (캡콤)", "category": "게임"},
]

# 옵션/선물 만기일 (KOSPI200 옵션만기·동시만기)
# 2026-09-28: 중복 방지를 위해 fixed_events.py(FIXED_EVENTS_2026/2027)로 이관 — 여기서는 생성하지 않음

# 날짜 미확정 일정 (월간/주간) — FnGuide에 확정 날짜 없는 것만
UNDATED_EVENTS_2026 = [
    {"month": "2026-04", "title": "테슬라 1Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-07", "title": "테슬라 2Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-10", "title": "테슬라 3Q 실적발표 (예상)", "category": "미국실적"},
    {"month": "2026-06", "title": "닌텐도 스위치2 출시 (예상)", "category": "게임"},
    # 삼성전자/SK하이닉스는 FnGuide에서 확정 날짜가 자동 수집되므로 제거
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
    # 옵션만기/동시만기는 fixed_events.py 에서 생성 (중복 방지)
    all_known = KNOWN_INDUSTRY_EVENTS_2026 + KNOWN_GAME_RELEASES_2026 + KNOWN_INDUSTRY_EVENTS_2027

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
                "source": "known",  # 하드코딩 스냅샷 소스 (RSS 유래만 "news")
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
                "source": "known",
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
                "source": "known",
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
    stats = {"feeds": 0, "failed": 0, "entries": 0}

    for category, feeds in SOURCES.items():
        for feed_info in feeds:
            stats["feeds"] += 1
            try:
                feed = feedparser.parse(feed_info["url"])
                # feedparser는 HTTP 오류·연결 실패에도 예외 없이 entries=[] → 직접 확인
                status = getattr(feed, "status", None)
                if (status and status >= 400) or not feed.entries:
                    stats["failed"] += 1
                    reason = (f"HTTP {status}" if status else
                              f"연결 실패: {str(feed.get('bozo_exception', '') or '')[:80]}")
                    print(f"[NewsEvents] ERROR: {feed_info['name']} RSS 0건 ({reason}) {feed_info['url']}")
                    continue
                stats["entries"] += len(feed.entries[:20])
                dates = [e.get("published_parsed") or e.get("updated_parsed") for e in feed.entries]
                dates = [datetime.datetime(*d[:6]) for d in dates if d]
                now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                if dates and (now_utc - max(dates)).days > 14:
                    print(f"[NewsEvents] WARN: {feed_info['name']} RSS 최신 글이 {max(dates):%Y-%m-%d} — "
                          f"피드 갱신 중단 의심 {feed_info['url']}")
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
                stats["failed"] += 1
                print(f"[NewsEvents] ERROR: {feed_info['name']} 실패: {type(e).__name__}: {e}")
                continue

    print(f"[NewsEvents] RSS {stats['feeds']}개 피드 (실패 {stats['failed']}) · 기사 {stats['entries']}건 스캔 "
          f"→ 일정 {len(results)}건")
    return results


def fetch_news_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """고정 산업이벤트 반환 (옵션만기는 fixed_events.py, RSS 수집은 ai_news_scanner.py에서 담당)"""
    return fetch_known_events(from_date, to_date)
