"""AI 뉴스 스캐너 — RSS에서 증시 관련 일정을 Claude API로 자동 추출"""
import os
import json
import datetime
import feedparser
import anthropic
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# RSS 소스 (기존 텔레그램 봇 소스 + 추가)
RSS_FEEDS = [
    # 국내 경제/산업
    "https://www.hankyung.com/feed/market",
    "https://www.hankyung.com/feed/economy",
    "https://rss.donga.com/economy.xml",
    "https://www.mk.co.kr/rss/30100041/",
    # 해외
    "https://feeds.reuters.com/reuters/businessNews",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    # 게임
    "https://www.gamesindustry.biz/feed",
    # 테크
    "https://techcrunch.com/feed/",
]

SYSTEM_PROMPT = """당신은 증시 캘린더 AI 어시스턴트입니다.
뉴스 헤드라인 목록을 받아서, 증시에 영향을 줄 수 있는 **미래 일정/이벤트**만 추출합니다.

추출 기준:
- 구체적인 날짜(또는 "~월 중", "~월 초/중순/말")가 언급된 미래 이벤트만
- 이미 일어난 과거 사건은 제외
- 한국/미국 증시에 직접 영향을 주는 이벤트만 (상장기업 관련)
- 제외: 스포츠(골프/야구/축구), 일반 패션/뷰티, 소규모 팝업, 지역 축제
- 포함: 대형 기업 제품 출시, 글로벌 컨퍼런스, 정상회담, 대형 영화/게임 출시(관련주 명확한 것만)

카테고리:
- 산업컨퍼런스: CES, GTC, WWDC, MWC 등
- 게임: 대형 게임 출시, 게임쇼
- 반도체: 반도체 관련 발표, 파운드리 가동
- 자동차/배터리: 신차 출시, 배터리 수주, 모터쇼
- 제약/바이오: FDA 승인, 임상 결과, 헬스케어 컨퍼런스
- 에너지: OPEC, 유가 관련
- 방산: 무기 계약, 방산 전시회
- 전시/박람회: IFA, 한국전자전 등
- K-콘텐츠: 대형 앨범, 콘서트 (관련주 영향 있는 것만)
- 정치/외교: 정상회담, G7/G20, 무역협상, 관세
- 부동산: 부동산 정책, 대규모 분양
- 수동: 위 카테고리에 안 맞지만 증시 영향 있는 것

응답은 반드시 JSON 배열만 출력하세요. 추출할 일정이 없으면 빈 배열 [].
"""

USER_PROMPT_TEMPLATE = """오늘 날짜: {today}

아래 뉴스 헤드라인에서 증시 관련 미래 일정을 추출하세요.

{headlines}

JSON 형식 (배열만 출력):
[
  {{
    "date": "2026-04-25",  // 확정 날짜 (YYYY-MM-DD) 또는 null
    "month": "2026-04",    // 날짜 미확정 시 월만 (YYYY-MM) 또는 null
    "title": "삼성전자 갤럭시 언팩",
    "category": "산업컨퍼런스",
    "summary": "삼성전자 신제품 발표회. 관련주: 삼성전자, 삼성전기",
    "confidence": "high"   // high / medium / low
  }}
]"""


def fetch_headlines() -> list[str]:
    """RSS에서 최근 기사 수집 (헤드라인 + 본문 요약)"""
    headlines = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                # HTML 태그 제거
                if "<" in summary:
                    from bs4 import BeautifulSoup
                    summary = BeautifulSoup(summary, "html.parser").get_text()
                summary = summary[:300].strip()
                if title:
                    text = f"[제목] {title}"
                    if summary and summary != title:
                        text += f"\n[내용] {summary}"
                    headlines.append(text)
        except Exception:
            continue

    return headlines[:100]


def extract_events_with_ai(headlines: list[str]) -> list[dict]:
    """Claude API로 헤드라인에서 일정 추출"""
    if not ANTHROPIC_API_KEY or not headlines:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today = datetime.date.today().isoformat()

    headlines_text = "\n".join(f"- {h}" for h in headlines)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(today=today, headlines=headlines_text),
            }],
        )

        text = response.content[0].text.strip()
        # JSON 추출 (```json ... ``` 래핑 제거)
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("["):
                    text = p
                    break
        # [ 찾기
        idx = text.find("[")
        end = text.rfind("]")
        if idx >= 0 and end > idx:
            text = text[idx:end+1]

        events = json.loads(text)
        if not isinstance(events, list):
            return []

        return events
    except Exception as e:
        print(f"[AI Scanner] Error: {e}")
        return []


def scan_news_for_events() -> list[dict]:
    """뉴스 스캔 → AI 분석 → calendar.json 형식 변환"""
    print("[AI Scanner] 헤드라인 수집 중...")
    headlines = fetch_headlines()
    print(f"[AI Scanner] {len(headlines)}개 헤드라인 수집")

    if not headlines:
        return []

    print("[AI Scanner] Claude API 분석 중...")
    raw_events = extract_events_with_ai(headlines)
    print(f"[AI Scanner] {len(raw_events)}개 일정 추출")

    results = []
    for ev in raw_events:
        title = ev.get("title", "")
        if not title:
            continue

        entry = {
            "category": ev.get("category", "수동"),
            "title": title,
            "source": "ai_scan",
            "auto": True,
        }

        # 날짜 처리
        if ev.get("date"):
            entry["date"] = ev["date"]
            entry["time"] = ""
        elif ev.get("month"):
            entry["month"] = ev["month"]
            entry["undated"] = True
            # month의 1일을 date로 사용
            try:
                y, m = int(ev["month"][:4]), int(ev["month"][5:7])
                entry["date"] = f"{y}-{m:02d}-01"
                last_day = (datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)).day if m < 12 else 31
                entry["endDate"] = f"{y}-{m:02d}-{last_day:02d}"
            except (ValueError, IndexError):
                continue
        else:
            continue

        # confidence → unconfirmed 태그
        confidence = ev.get("confidence", "medium")
        if confidence in ("medium", "low"):
            entry["unconfirmed"] = True

        if ev.get("summary"):
            entry["summary"] = ev["summary"]

        results.append(entry)

    return results
