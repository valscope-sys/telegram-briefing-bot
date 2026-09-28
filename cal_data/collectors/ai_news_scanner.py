"""AI 뉴스 스캐너 — RSS에서 증시 관련 일정을 Claude API로 자동 추출"""
import os
import json
import datetime
import feedparser
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 스캐너 모델 — 비용 최저 원칙(사용자 정책). 환경변수 CALENDAR_SCANNER_MODEL로 교체 가능
CALENDAR_SCANNER_MODEL = os.getenv("CALENDAR_SCANNER_MODEL", "claude-haiku-4-5-20251001")

# RSS 소스 — 경제·산업 + 신제품/학회/전시 발표가 잘 잡히는 IT·반도체 매체
# (구 Reuters 피드는 폐쇄, 한경은 기본 UA 차단 → 브라우저 UA로 요청)
RSS_FEEDS = [
    # 국내 경제/산업
    "https://www.hankyung.com/feed/finance",
    "https://www.hankyung.com/feed/it",
    "https://rss.donga.com/economy.xml",
    "https://www.mk.co.kr/rss/30100041/",
    "https://rss.etnews.com/Section901.xml",
    "https://feeds.feedburner.com/zdkorea",
    # 해외 시장·테크
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.tomshardware.com/feeds/all",
]
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

SYSTEM_PROMPT = """당신은 한국 증시 캘린더 AI 어시스턴트입니다.
뉴스 헤드라인 목록을 받아서, 한국 상장사 주가에 영향을 줄 **미래 일정/이벤트**만 추출합니다.

추출 기준:
- 구체적인 날짜(또는 "~월 중", "~월 초/중순/말")가 언급된 미래 이벤트만. 이미 일어난 일은 제외
- 한국 공급망·관련주가 반응하는 것만 (관련주를 summary에 명시할 수 있어야 함)
- 적극 포함:
  · 빅테크 신제품 공개·키노트 (예: 메타 커넥트 AI 글라스, 애플 신제품 이벤트, 삼성 갤럭시 언팩,
    엔비디아·AMD 키노트, 테슬라 로보택시/옵티머스 행사)
  · 산업 학회·전시 (예: 광통신 OFC·ECOC, 디스플레이 SID, 배터리 인터배터리, 반도체 SEMICON,
    바이오 ASCO·ESMO·ASH, 방산 ADEX·AUSA, 조선 SMM, 원전 WNE)
  · FDA 허가 결정일(PDUFA)·임상 결과 발표 예정일, 대형 수주·계약 발표 예정
  · 정책·외교 일정 (정상회담, 관세 발효, 규제 시행일)
- 제외: 스포츠, 패션/뷰티 팝업, 지역 축제, 분양·청약, 게임쇼, 콘서트, 개인 금융상품 출시
- 제외: 기업 실적발표 일정 (별도 수집기가 담당)

카테고리 (이 중 하나만):
- 산업컨퍼런스: 빅테크 키노트·신제품 공개, IT/광통신/디스플레이 학회·전시
- 반도체: 반도체 학회·발표·팹 가동
- 자동차/배터리: 신차·배터리 행사, 모터쇼
- 제약/바이오: FDA 결정일, 임상 발표, 바이오 학회
- 에너지: OPEC, 원전·전력 행사
- 방산: 방산 전시회, 무기 계약
- 정치/외교: 정상회담, G7/G20, 무역협상, 관세·규제 시행
- 수동: 위에 안 맞지만 증시 영향이 분명한 것

"이미 등록된 일정" 목록에 있는 행사는 이름이 조금 달라도 같은 행사면 추출하지 마세요.
응답은 반드시 JSON 배열만 출력하세요. 추출할 일정이 없으면 빈 배열 [].
"""

USER_PROMPT_TEMPLATE = """오늘 날짜: {today}

이미 등록된 일정 (중복 추출 금지):
{existing}

아래 뉴스 헤드라인에서 증시 관련 미래 일정을 추출하세요.

{headlines}

JSON 형식 (배열만 출력):
[
  {{
    "date": "2026-04-25",  // 확정 날짜 (YYYY-MM-DD) 또는 null
    "month": "2026-04",    // 날짜 미확정 시 월만 (YYYY-MM) 또는 null
    "title": "삼성전자 갤럭시 언팩",
    "category": "산업컨퍼런스",
    "summary": "삼성전자 신제품 발표회. 관련주: 삼성전자, 삼성전기, LG이노텍",
    "confidence": "high"   // high / medium / low
  }}
]"""


def fetch_headlines() -> list[str]:
    """RSS에서 최근 기사 수집 (헤드라인 + 본문 요약)"""
    import requests
    headlines = []

    for url in RSS_FEEDS:
        try:
            res = requests.get(url, headers=_UA, timeout=15)
            feed = feedparser.parse(res.content)
            if res.status_code != 200 or not feed.entries:
                print(f"[AI Scanner] ERROR: RSS 수집 실패 (HTTP {res.status_code}, {len(feed.entries)}건) {url}")
                continue
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
        except Exception as e:
            print(f"[AI Scanner] ERROR: RSS 수집 예외 {url} — {e}")

    return headlines[:150]


def extract_events_with_ai(headlines: list[str], existing: list[str] | None = None) -> list[dict]:
    """Claude API로 헤드라인에서 일정 추출"""
    if not headlines:
        return []
    from telegram_bot.llm_client import get_client, llm_available
    if not llm_available():
        print("[AI Scanner] ERROR: ANTHROPIC_API_KEY도 Claude Code CLI도 없음 — AI 일정 추출 건너뜀")
        return []

    client = get_client(ANTHROPIC_API_KEY)
    today = datetime.date.today().isoformat()

    headlines_text = "\n".join(f"- {h}" for h in headlines)

    try:
        response = client.messages.create(
            model=CALENDAR_SCANNER_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    today=today, headlines=headlines_text,
                    existing="\n".join(existing or []) or "(없음)"),
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
            print(f"[AI Scanner] ERROR: 응답이 JSON 배열이 아님 — {text[:100]}")
            return []

        return events
    except Exception as e:
        print(f"[AI Scanner] ERROR: Claude API 호출/파싱 실패 (model={CALENDAR_SCANNER_MODEL}) — {e}")
        return []


def scan_news_for_events(existing_events: list[dict] | None = None) -> list[dict]:
    """뉴스 스캔 → AI 분석 → calendar.json 형식 변환

    existing_events: 이번 실행에서 다른 수집기가 가져온 일정 — 같은 행사 중복 추출 방지용
    """
    print("[AI Scanner] 헤드라인 수집 중...")
    headlines = fetch_headlines()
    print(f"[AI Scanner] {len(headlines)}개 헤드라인 수집")

    if not headlines:
        return []

    today = datetime.date.today().isoformat()
    horizon = (datetime.date.today() + datetime.timedelta(days=120)).isoformat()
    existing = sorted({
        f"{e['date']} {e['title']}" for e in (existing_events or [])
        if e.get("source") in ("known", "fixed") and today <= e.get("date", "") <= horizon
        and e.get("category") not in ("만기일", "휴장일", "경제지표")
    })[:150]

    print("[AI Scanner] Claude 분석 중...")
    raw_events = extract_events_with_ai(headlines, existing)
    print(f"[AI Scanner] {len(raw_events)}개 일정 추출")

    results = []
    for ev in raw_events:
        title = ev.get("title", "")
        if not title or "실적" in title:  # 실적 일정은 전용 수집기(Nasdaq/KIND/FnGuide) 담당
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
