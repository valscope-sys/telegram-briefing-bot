"""중요도/카테고리 필터 — Claude Haiku

2단계 분류:
1. DART는 dart_category_map에서 이미 priority_hint 받은 경우 그대로 사용 (비용 절감)
2. 매칭 실패 or RSS 소스면 Haiku에게 분류 의뢰

출력 JSON:
{
  "priority": "URGENT|HIGH|NORMAL|SKIP",
  "sector": "반도체|IT부품|2차전지|...",
  "category": "A|B|C|D|E",
  "reason": "..."
}
"""
import json
import re
import anthropic

from telegram_bot.config import (
    ANTHROPIC_API_KEY,
    ISSUE_BOT_FILTER_MODEL,
)


FILTER_SYSTEM = """당신은 NODE Research 이슈 필터입니다.
주어진 금융/증시 이벤트를 4단계 우선순위와 Template 카테고리로 분류합니다.

우선순위(priority):
- URGENT: 국내 Top30 대형 공시(M&A, 자사주 소각, 대형 증자), 대형 실적 서프라이즈, 돌발 이슈(지진/파업/규제), 원자재±3% 급변, FDA 승인/반려
- HIGH: Top100 분기 실적, 해외 Peer 월매출, 가격 인상/인하 발표, Capex 1000억+, 컨센 대비 ±10%
- NORMAL: 월별 수출통계, 산업 리서치 리포트, 정기 IR, 중소형주 잠정실적
- SKIP: 인사/채용/CSR, 보험/카드 광고, 범죄/연예/스포츠, 중복, 클릭베이트

Template 카테고리:
- A: 해외 Peer 월매출/분기실적 (대만/일본/중국/미국 기업 IR)
- B: 국내 공시 (DART, KIND 기반)
- C: 영문 기사/리서치 인용 (Reuters, Digitimes, Nikkei, TrendForce 등)
- D: 월별 수출통계 (TRASS, 관세청)
- E: 돌발 속보 (지진, 긴급 이슈)

섹터(sector):
반도체, 디스플레이, 반도체 장비, IT부품, 스마트폰, PC/서버, 2차전지, 전기차, 석유/가스, LNG, 원전, 신재생, 수소, 철강/금속, 화학, 조선, 해운, 자동차, 방산, 우주항공, 건설, 바이오/제약, 의료기기, 식품/농업, 유통/커머스, 엔터/미디어, 게임, 호텔/레저/항공, 금융/은행, 보험, 증권, 부동산, 가상자산, 기타

반드시 유효한 JSON만 출력:
{"priority": "...", "sector": "...", "category": "...", "reason": "한 줄"}"""


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def filter_event(event: dict) -> dict:
    """
    이벤트에 priority + category + sector 부여.

    Args:
        event: dart_collector 또는 rss_adapter가 생성한 dict

    Returns:
        {"priority", "sector", "category", "reason", "source_method": "rule|haiku"}
    """
    # 1. DART rule-based 결과 재사용
    if event.get("priority_hint") and event.get("category_hint"):
        sector = event.get("sector") or _infer_sector_from_name(event.get("company_name", ""))
        return {
            "priority": event["priority_hint"],
            "category": event["category_hint"],
            "sector": sector,
            "reason": event.get("rule_match_reason", "dart_category_map"),
            "source_method": "rule",
        }

    # 2. Haiku 필터
    return _haiku_classify(event)


def _haiku_classify(event: dict) -> dict:
    """Claude Haiku 호출로 분류"""
    if not ANTHROPIC_API_KEY:
        return {
            "priority": "NORMAL",
            "category": "C",
            "sector": "기타",
            "reason": "ANTHROPIC_API_KEY 없음 — 기본값",
            "source_method": "fallback",
        }

    # 이벤트 요약 문자열 조립
    source = event.get("source", "?")
    title = event.get("title", "")[:200]
    company = event.get("company_name", "")
    body = event.get("body_excerpt") or event.get("original_content", "")
    body = body[:1000] if body else ""

    user_msg = f"""[소스] {source}
[기업/주체] {company}
[제목] {title}
[본문 요약]
{body}

이 이벤트를 분류해주세요. JSON만."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=ISSUE_BOT_FILTER_MODEL,
            max_tokens=300,
            system=FILTER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        parsed = _parse_filter_json(text)
        if parsed:
            parsed["source_method"] = "haiku"
            parsed["tokens_used"] = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            return parsed
    except Exception as e:
        print(f"[FILTER] Haiku 호출 실패: {e}")

    return {
        "priority": "NORMAL",
        "category": "C",
        "sector": "기타",
        "reason": "Haiku 실패 — 기본값",
        "source_method": "fallback",
    }


def _parse_filter_json(text: str) -> dict:
    """Haiku 응답 텍스트에서 JSON 추출 (마크다운 코드블록 처리 포함)"""
    # ```json ... ``` 블록 안에 있을 수 있음
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        # 첫 { 부터 마지막 } 까지
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)

    try:
        data = json.loads(text)
        # 필수 필드 검증
        if all(k in data for k in ("priority", "category", "sector")):
            return {
                "priority": data["priority"],
                "category": data["category"],
                "sector": data["sector"],
                "reason": data.get("reason", ""),
            }
    except json.JSONDecodeError:
        pass
    return None


# ===== 섹터 추론 보조 =====

_SECTOR_KEYWORDS = {
    "반도체": ["반도체", "메모리", "DRAM", "NAND", "HBM", "파운드리", "SK하이닉스", "삼성전자"],
    "디스플레이": ["디스플레이", "OLED", "LCD", "패널", "LG디스플레이", "삼성D"],
    "IT부품": ["기판", "PCB", "CCL", "FPCB", "ABF", "MLCC", "리드프레임", "FC-BGA",
              "대덕전자", "심텍", "LG이노텍", "해성디에스", "PI첨단소재", "네오티스", "이수페타시스", "삼성전기"],
    "2차전지": ["2차전지", "배터리", "리튬", "양극재", "음극재", "LG에너지솔루션", "삼성SDI",
              "SK온", "에코프로", "포스코퓨처엠", "엘앤에프"],
    "전기차": ["전기차", "EV", "현대차", "기아", "테슬라"],
    "바이오/제약": ["바이오", "제약", "임상", "FDA", "삼성바이오", "셀트리온", "유한양행", "알테오젠"],
    "자동차": ["자동차", "현대차", "기아", "현대모비스", "한온시스템"],
    "조선": ["조선", "HD현대중공업", "한화오션", "삼성중공업"],
    "방산": ["방산", "한화에어로", "LIG넥스원", "한국항공우주", "현대로템"],
    "철강/금속": ["철강", "POSCO", "포스코홀딩스", "현대제철", "동국제강"],
    "화학": ["화학", "LG화학", "롯데케미칼", "한화솔루션"],
    "건설": ["건설", "현대건설", "삼성물산", "GS건설", "대우건설"],
    "금융/은행": ["금융", "은행", "KB금융", "신한지주", "하나금융", "우리금융"],
    "게임": ["게임", "크래프톤", "엔씨소프트", "넷마블", "펄어비스"],
    "엔터/미디어": ["엔터", "하이브", "에스엠", "JYP", "YG", "CJ ENM"],
    "원전": ["원전", "두산에너빌리티", "한전KPS"],
    "LNG": ["LNG", "SK E&S", "한국가스공사"],
    "유통/커머스": ["유통", "쿠팡", "이마트", "GS리테일", "현대백화점"],
}


def _infer_sector_from_name(company_name: str) -> str:
    """회사명으로 섹터 추정 (rule-based 빠른 매칭)"""
    if not company_name:
        return "기타"
    for sector, keywords in _SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in company_name:
                return sector
    return "기타"


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # rule-based 매칭 테스트 (Haiku 호출 X)
    ev_rule = {
        "company_name": "삼성전자",
        "title": "주요사항보고서(자기주식소각결정)",
        "priority_hint": "URGENT",
        "category_hint": "B",
        "rule_match_reason": "dart_category_map: 자기주식소각결정",
    }
    print("== Rule-based 테스트 ==")
    print(filter_event(ev_rule))
    print()

    # Haiku 테스트 (매칭 실패 이벤트)
    ev_haiku = {
        "source": "DART",
        "company_name": "KG스틸",
        "title": "유형자산처분결정",
        "body_excerpt": "KG스틸이 비핵심 유형자산을 300억원에 처분한다.",
    }
    print("== Haiku 테스트 ==")
    print(filter_event(ev_haiku))
