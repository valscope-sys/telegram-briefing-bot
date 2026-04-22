"""중요도/카테고리 필터 — Claude Haiku

2단계 분류:
1. DART는 dart_category_map에서 이미 priority_hint 받은 경우 그대로 사용 (비용 절감)
2. 매칭 실패 or RSS/SEC 소스면 Haiku에게 분류 의뢰 (Hybrid 시 Sonnet 재검증)

출력 JSON:
{
  "priority": "URGENT|HIGH|NORMAL|SKIP",
  "sector": "반도체|IT부품|2차전지|...",
  "category": "A|B|C|D|E",
  "reason": "..."
}

Phase 2:
- market_context.txt (한지영 + 브리핑 기억) 컨텍스트 주입 → "요즘 테마" 반영
- 부각 감지 조항: 빅테크 Peer / 거래량 급증 / 52주 신고가 → HIGH 가점
"""
import os
import json
import re
import anthropic

from telegram_bot.config import (
    ANTHROPIC_API_KEY,
    ISSUE_BOT_FILTER_MODEL,
    ISSUE_BOT_FILTER_VERIFIER_MODEL,
    ISSUE_BOT_FILTER_HYBRID,
)

_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
)
_MARKET_CONTEXT_PATH = os.path.join(_HISTORY_DIR, "market_context.txt")


def _load_market_context(max_chars: int = 1800) -> str:
    """현재 시장 컨텍스트 로딩 (한지영 채널 + briefing_memory 기반).

    누적 파일 가정 → 끝부분 max_chars만 (최신 유지).
    실패 시 빈 문자열 (필터는 그대로 동작).
    """
    try:
        with open(_MARKET_CONTEXT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return content[-max_chars:] if len(content) > max_chars else content
    except Exception:
        return ""


FILTER_SYSTEM = """당신은 NODE Research 투자 분석가이자 이슈 필터입니다.
**핵심 임무**: "투자 의사결정에 유의미한 시사점이 있는 이벤트만" 통과시키기.
시사점 없는 단순 공시/정치 뉴스/평론은 SKIP.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[시사점 있음 — 통과 기준 (하나라도 해당되면)]

1) 밸류체인 파급 — 이 뉴스가 다른 종목·업종에 영향?
   예: TSMC 매출 최고 → HBM 수요 확대, CCL 가격 인상 → 국내 소재 밸류체인
2) 사이클 시그널 — 업종 사이클 변곡점 암시?
   예: 특정 부품 공급부족 심화, 원자재 가격 +10%, 가동률 풀가동
3) 구조적 변화 — 경쟁구도/재무구조/전략 변화?
   예: 자사주 소각(취득 X), 지분 매각/인수, 대규모 Capex 발표
4) 시급성 — 투자자가 즉시 알아야?
   예: 거래정지, 부도, 최대주주 변경, FDA 승인/반려, 지정학 돌발

[시사점 없음 — SKIP 대상]

- 소규모/정기 공시: 수주 100억 이하, 정관변경, 주총소집, 감사보고서, 배당결정, 임원변경
- 재탕·중복: 이미 반복 보도된 정치/외교, 유가·환율 일상 변동 해설
- 평론·칼럼: "~의 시각", "~의 분석", 개인 인터뷰, 경영자 평가
- 일반 사회 뉴스: 연예, 스포츠, 식당/소비 트렌드, 부동산 개별 분양
- 제품 개별 리뷰·기능 소개: 핸드폰 후기, 게임 패치노트 등
- 정부 일반 정책: 구체 기업 영향 불명확한 거시 발언

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[우선순위 — 시사점 강도에 따라]

- URGENT: 밸류체인+시급성 모두 해당 (대형 M&A, 거래정지, 자사주 소각, 실적 서프라이즈, FDA 승인, 지진/돌발)
- HIGH: 밸류체인·사이클·구조 변화 중 하나 강함 (Peer 실적, 가격 인상, Capex 1000억+, 5% 공시, BW/CB 발행)
- NORMAL: 의미는 있으나 즉시성 낮음 (월별 수출통계, 산업 리서치 리포트, 잠정실적)
- SKIP: 시사점 없거나 노이즈

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[부각 감지 — HIGH 가점 규칙]

다음에 해당하면 "밸류체인 파급" 또는 "사이클 시그널" 기준 충족으로 보고 판단 상향:
- 시장 컨텍스트(제공 시)에 언급된 "현재 테마" 관련 종목·섹터
  (예: HBM/AI 반도체/원전/조선/방산 등)
- 빅테크 Peer 8-K(NVDA/TSM/AVGO/AMD/MU 등)의 실적·가이던스·대규모 계약
  → 한국 반도체·IT부품 밸류체인 직결
- 거래량·거래대금 급증 언급, 52주 신고가 달성 종목 언급
  → 시장이 이미 주목하고 있다는 강한 시그널
- 한국 Peer 관계(밸류체인 대기업·소부장) 직접 언급

단, "테마 편승 잡종목"은 여전히 SKIP. 실제 사실/수치/계약이 있을 때만 HIGH.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Template 카테고리]

- A: 해외 Peer 월매출/분기실적 (대만/일본/중국/미국 기업 IR)
- B: 국내 공시 (DART, KIND)
- C: 영문 기사/리서치 인용 (Reuters, Digitimes, Nikkei, TrendForce)
- D: 월별 수출통계 (TRASS, 관세청)
- E: 돌발 속보

[섹터]
반도체, 디스플레이, 반도체 장비, IT부품, 스마트폰, PC/서버, 2차전지, 전기차, 석유/가스, LNG, 원전, 신재생, 수소, 철강/금속, 화학, 조선, 해운, 자동차, 방산, 우주항공, 건설, 바이오/제약, 의료기기, 식품/농업, 유통/커머스, 엔터/미디어, 게임, 호텔/레저/항공, 금융/은행, 보험, 증권, 부동산, 가상자산, 기타

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
반드시 유효한 JSON만 출력 (다른 텍스트 금지):
{"priority": "...", "sector": "...", "category": "...", "significance": "시사점 한 줄(내부 판단 근거, Telegram에는 표시되지 않음)", "reason": "한 줄"}

**중요: 애매하면 SKIP으로 판정. 과잉 통과보다 과소 통과가 낫습니다.**"""


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def filter_event(event: dict) -> dict:
    """
    Hybrid 필터: rule → Haiku → (HIGH/NORMAL이면) Sonnet 재검증.

    Returns:
        {"priority", "sector", "category", "reason", "significance",
         "source_method": "rule|haiku|hybrid_sonnet", ...}
    """
    # 1. DART rule-based 결과 재사용
    if event.get("priority_hint") and event.get("category_hint"):
        sector = event.get("sector") or _infer_sector_from_name(event.get("company_name", ""))
        return {
            "priority": event["priority_hint"],
            "category": event["category_hint"],
            "sector": sector,
            "reason": event.get("rule_match_reason", "dart_category_map"),
            "significance": "",
            "source_method": "rule",
        }

    # 2. Haiku 1차 분류
    haiku_result = _haiku_classify(event)

    # 3. Hybrid OFF이면 Haiku 결과 그대로 반환
    if not ISSUE_BOT_FILTER_HYBRID:
        return haiku_result

    # 4. Haiku가 SKIP/URGENT면 신뢰도 높음 → 그대로 사용 (Sonnet 호출 스킵, 비용 절감)
    haiku_priority = haiku_result.get("priority")
    if haiku_priority in ("SKIP", "URGENT") or haiku_result.get("source_method") == "fallback":
        return haiku_result

    # 5. HIGH/NORMAL 경계 영역 → Sonnet 재검증
    sonnet_result = _sonnet_verify(event, haiku_hint=haiku_result)
    if sonnet_result:
        sonnet_result["haiku_was"] = haiku_priority
        sonnet_result["source_method"] = "hybrid_sonnet"
        return sonnet_result

    # Sonnet 실패 시 Haiku fallback
    return haiku_result


def _build_filter_user_msg(event: dict, haiku_hint: dict = None) -> str:
    """필터용 user 메시지. market_context 컨텍스트 자동 주입."""
    source = event.get("source", "?")
    title = event.get("title", "")[:200]
    company = event.get("company_name", "")
    ticker = event.get("ticker") or ""
    body = event.get("body_excerpt") or event.get("original_content", "")
    body = body[:1200] if body else ""

    context_block = ""
    ctx = _load_market_context()
    if ctx:
        context_block = (
            "\n[현재 시장 컨텍스트 — 부각 감지 판단용]\n"
            "(한지영 채널·이전 브리핑 기반 '지금 테마·수급 맥락'. 맹신 금지)\n"
            f"{ctx}\n"
        )

    base = (
        f"[소스] {source}\n"
        f"[기업/주체] {company}" + (f" ({ticker})" if ticker else "") + "\n"
        f"[제목] {title}\n"
        f"[본문 요약]\n{body}\n"
        f"{context_block}"
    )

    if haiku_hint:
        haiku_priority = haiku_hint.get("priority", "?")
        haiku_reason = haiku_hint.get("significance") or haiku_hint.get("reason", "")
        base += (
            f"\n[Haiku 1차 판정]\n"
            f"priority: {haiku_priority}\n"
            f"significance: {haiku_reason}\n\n"
            f"이제 당신이 **더 엄격히 재판단**하세요.\n"
            f"- 규모·맥락 정확히 판단하여 HIGH/NORMAL 경계를 재평가\n"
            f"- 의심스러우면 낮추세요(과잉 통과보다 과소 통과)\n"
            f"- 구체적 근거(규모·피어 관계·사이클)가 약하면 NORMAL 또는 SKIP\n\n"
            f"JSON만 출력."
        )
    else:
        base += "\n이 이벤트를 분류해주세요. JSON만."

    return base


def _sonnet_verify(event: dict, haiku_hint: dict) -> dict:
    """Sonnet 재검증 — Haiku가 HIGH/NORMAL 판정한 이벤트에 대해 더 엄격히 판단."""
    if not ANTHROPIC_API_KEY:
        return None

    user_msg = _build_filter_user_msg(event, haiku_hint=haiku_hint)

    try:
        client = _get_client()
        response = client.messages.create(
            model=ISSUE_BOT_FILTER_VERIFIER_MODEL,
            max_tokens=300,
            system=FILTER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        parsed = _parse_filter_json(text)
        if parsed:
            parsed["tokens_used"] = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }
            return parsed
    except Exception as e:
        print(f"[FILTER] Sonnet verifier 실패: {e}")
    return None


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

    user_msg = _build_filter_user_msg(event)

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
                # significance는 내부 필터 판단 근거 (텔레그램 출력엔 사용 안 함, 로그/이력에만)
                "significance": data.get("significance", ""),
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
