"""시장 컨텍스트 관리 — 저장된 컨텍스트 + 다중 외부 애널리스트 시각 크롤링.

2026-05-28 리팩토링: 한지영 단일 소스 → 다중 소스 지원.
새 애널리스트 추가 시 ANALYST_SOURCES 리스트에 등록만 하면 자동 수집.

지원 소스 타입:
- "telegram_channel": t.me/s/{id} HTML 파싱 (한지영 등)
- "naver_blog_rss": blog.naver.com/rss/{id} 또는 rss.blog.naver.com/{id}.xml
- "rss": 일반 RSS feed
"""
import os
import datetime
import re
import requests
import feedparser
from bs4 import BeautifulSoup

HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
CONTEXT_FILE = os.path.join(HISTORY_DIR, "market_context.txt")
# 한지영 누적 (legacy 파일명 유지 — 기존 데이터 보존)
ANALYST_FILE = os.path.join(HISTORY_DIR, "analyst_raw.txt")

# ─────────────────────────────────────────
# 외부 애널리스트 시각 소스 등록
# ─────────────────────────────────────────
# 새 소스 추가 시 이 리스트에만 등록하면 됨.
# - name: 내부 식별자 (파일명에 사용, 영문/숫자/언더스코어만)
# - type: telegram_channel | naver_blog_rss | rss
# - url: 크롤링 URL
# - label: 프롬프트에 표시될 출처명 (한글 가능)
ANALYST_SOURCES = [
    {
        "name": "hedgecat",
        "type": "telegram_channel",
        "url": "https://t.me/s/hedgecat0301",
        "label": "키움증권 한지영",
    },
    {
        "name": "kkm_cfa",
        "type": "naver_blog_rss",
        "url": "https://rss.blog.naver.com/bboyanaga.xml",
        "label": "애널리스트 김경민 CFA",
    },
]


# ─────────────────────────────────────────
# 소스 타입별 fetcher
# ─────────────────────────────────────────
def _fetch_telegram_channel(url):
    """텔레그램 공개 채널 HTML 파싱. 200자 이상 메시지 중 최신 1건 반환."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")
        messages = soup.select(".tgme_widget_message_text")
        latest_text = ""
        for msg in messages:
            text = msg.get_text(strip=True)
            if len(text) > 200:
                latest_text = text  # 마지막이 최신
        return latest_text[:2000] if latest_text else ""
    except Exception as e:
        print(f"[CONTEXT] telegram fetch 실패 ({url}): {str(e)[:80]}")
        return ""


def _fetch_naver_blog_rss(url):
    """네이버 블로그 RSS — feedparser로 최신 1건 본문 추출.

    네이버 RSS는 description에 HTML 본문이 들어있음. 평문 추출 + 길이 컷.
    """
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            return ""
        entry = feed.entries[0]  # 최신
        title = entry.get("title", "")
        # description은 HTML — BeautifulSoup으로 평문 추출
        raw = entry.get("description", "") or entry.get("summary", "")
        if not raw:
            return ""
        soup = BeautifulSoup(raw, "lxml")
        # 이미지·iframe 제거
        for tag in soup(["img", "iframe", "script", "style"]):
            tag.decompose()
        body = soup.get_text(separator="\n", strip=True)
        # 짧은 빈 줄 정리
        body = re.sub(r"\n{3,}", "\n\n", body)
        combined = f"[{title}]\n\n{body}"
        return combined[:2500]
    except Exception as e:
        print(f"[CONTEXT] naver rss fetch 실패 ({url}): {str(e)[:80]}")
        return ""


def _fetch_rss(url):
    """일반 RSS — 최신 1건 description 추출."""
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            return ""
        entry = feed.entries[0]
        title = entry.get("title", "")
        body = entry.get("summary", "") or entry.get("description", "")
        if body:
            soup = BeautifulSoup(body, "lxml")
            body = soup.get_text(separator="\n", strip=True)
        combined = f"[{title}]\n\n{body}"
        return combined[:2500]
    except Exception as e:
        print(f"[CONTEXT] rss fetch 실패 ({url}): {str(e)[:80]}")
        return ""


_FETCHERS = {
    "telegram_channel": _fetch_telegram_channel,
    "naver_blog_rss": _fetch_naver_blog_rss,
    "rss": _fetch_rss,
}


def _save_source_raw(source_name, text):
    """소스별 원본 누적 저장 (중복 방지). 한지영은 legacy 파일 유지."""
    if not text:
        return
    if source_name == "hedgecat":
        path = ANALYST_FILE  # legacy 호환
    else:
        path = os.path.join(HISTORY_DIR, f"analyst_raw_{source_name}.txt")
    try:
        existing = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read()
        # 첫 50자로 중복 체크
        check = text[:50]
        if check in existing:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n---\n\n{text}\n")
    except Exception:
        pass


def _fetch_source(source):
    """소스 타입 디스패치 + 원본 저장."""
    fetcher = _FETCHERS.get(source.get("type"))
    if not fetcher:
        return ""
    text = fetcher(source["url"])
    if text:
        _save_source_raw(source.get("name", "unknown"), text)
    return text


# ─────────────────────────────────────────
# 외부 API — 프롬프트용 컨텍스트 생성
# ─────────────────────────────────────────
def get_market_context_for_prompt():
    """저장된 컨텍스트 + 모든 외부 애널리스트 시각을 프롬프트용으로 통합 반환.

    여러 소스의 시각이 들어오면 LLM이 자연스럽게 교차 검증·종합 사고 유도.
    매일 다른 외부 자극 = 매일 다른 출력 (강제 다양성 X, 입력 다양성 O).
    """
    parts = []
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 1. 저장된 시장 컨텍스트 (이전 시황 누적 요약)
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                context = f.read().strip()
            if context:
                date_match = re.search(r"(\d{4}\.\d{2}\.\d{2}|\d{4}-\d{2}-\d{2})", context)
                ctx_date = date_match.group(1).replace(".", "-") if date_match else "불명"
                staleness_warning = ""
                if ctx_date != "불명" and ctx_date != today:
                    staleness_warning = (
                        f"\n주의: 이 컨텍스트는 {ctx_date} 기준입니다. "
                        f"오래된 이벤트(실적 발표 등)를 오늘 처음 발생한 것처럼 서술하지 마세요."
                    )
                parts.append(
                    f"=== 시장 컨텍스트 (배경 참고용, 오늘 데이터가 아님) ==="
                    f"{staleness_warning}\n{context[:2000]}"
                )
        except Exception:
            pass

    # 2. 다중 외부 애널리스트 시각 (각 소스별 최신 1건)
    analyst_blocks = []
    for source in ANALYST_SOURCES:
        text = _fetch_source(source)
        if text:
            label = source.get("label", source.get("name", "외부 시각"))
            analyst_blocks.append(f"[{label}]\n{text}")

    if analyst_blocks:
        # 여러 소스 묶음 — LLM이 교차 시각 비교하도록 유도
        header = (
            "=== 외부 애널리스트 시각 (참고용 — 복사·표현 차용 금지, 본인 통합 판단으로 ===\n"
            "여러 시각이 있으면 공통점·차이점을 자기 사고로 종합하세요. 한 시각을 그대로 반복하지 말 것.\n"
        )
        parts.append(header + "\n\n".join(analyst_blocks))

    return "\n\n".join(parts)


# ─────────────────────────────────────────
# 컨텍스트 자동 갱신 (이브닝 후)
# ─────────────────────────────────────────
def update_market_context(new_commentary, market_data=None):
    """시황 생성 후 컨텍스트 업데이트 (이브닝 후 호출).

    2026-05-28 fix: 하드코딩된 claude-sonnet-4-20250514 모델이 deprecated 되어
    5/13 이후 16일째 호출 실패. COMMENTARY_MODEL 환경변수 사용 + 폴백 모델.
    """
    if not new_commentary:
        print("[CONTEXT] new_commentary 없음 — 업데이트 스킵")
        return

    from telegram_bot.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        print("[CONTEXT] ANTHROPIC_API_KEY 없음 — 업데이트 스킵")
        return

    existing = ""
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            pass

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = datetime.date.today().strftime("%Y-%m-%d")

    prompt = f"""기존 시장 컨텍스트와 오늘 시황을 기반으로 컨텍스트를 업데이트해주세요.

[기존 컨텍스트]
{existing[:2000]}

[오늘 시황 ({today})]
{new_commentary[:1500]}

업데이트 규칙:
- 첫 줄은 반드시 "## 시장 국면 ({today} 기준)"으로 시작
- 기존 구조(지정학/매크로/섹터/수급/밸류에이션/시장국면)를 유지
- 오늘 새로 확인된 사실만 반영
- 3일 이상 지난 이벤트는 "N일 전" 표기 추가하거나 중요도가 낮으면 제거
- 이미 해결된 이슈는 제거
- 전체 2000자 이내

업데이트된 컨텍스트만 작성하세요."""

    # 모델 fallback 체인: 환경변수 → 최신 안정 모델들
    import os as _os
    commentary_model = _os.environ.get("COMMENTARY_MODEL", "").strip()
    model_candidates = []
    if commentary_model:
        model_candidates.append(commentary_model)
    model_candidates.extend([
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-7-20251215",
        "claude-sonnet-4-20250514",  # 옛 버전 (혹시 살아있다면)
    ])
    seen = set()
    model_candidates = [m for m in model_candidates if not (m in seen or seen.add(m))]

    last_err = None
    for model in model_candidates:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            updated = response.content[0].text.strip()

            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                f.write(updated)
            print(f"[CONTEXT] 시장 컨텍스트 업데이트 완료 ({today}, model={model})")
            return
        except Exception as e:
            err_str = str(e)
            last_err = e
            if "not_found" in err_str or "model" in err_str.lower():
                print(f"[CONTEXT] {model} 사용 불가, 다음 모델 시도: {err_str[:120]}")
                continue
            break

    print(f"[CONTEXT] 시장 컨텍스트 업데이트 실패 (모든 모델 시도): {last_err}")
    import traceback
    traceback.print_exc()
