"""중요도/카테고리 필터 — Claude Haiku

3단계 분류 (2026-04-29 비용 절감 개편):
0. **Pre-filter** — RSS 제목 키워드 노이즈 SKIP (Haiku 호출 전 차단, 비용 0)
1. DART rule (dart_category_map priority_hint) — Haiku 우회
2. 매칭 실패 or RSS/SEC 소스면 Haiku 분류 (system 프롬프트 캐싱 적용)
3. (Hybrid 모드) HIGH/NORMAL 경계만 Sonnet 재검증 (캐싱 적용)

출력 JSON:
{
  "priority": "URGENT|HIGH|NORMAL|SKIP",
  "sector": "반도체|IT부품|2차전지|...",
  "category": "A|B|C|D|E",
  "reason": "..."
}
"""
import json
import os
import re
import time
import anthropic

from telegram_bot.config import (
    ANTHROPIC_API_KEY,
    ISSUE_BOT_FILTER_MODEL,
    ISSUE_BOT_FILTER_VERIFIER_MODEL,
    ISSUE_BOT_FILTER_HYBRID,
)


# ===== 비용 절감 메트릭 (프로세스 수명) =====
_METRICS = {
    "pre_filter_skip": 0,        # 사전 필터로 Haiku 호출 자체 차단
    "haiku_calls": 0,            # Haiku 실제 호출
    "sonnet_calls": 0,           # Sonnet 재검증 호출
    "haiku_cache_read": 0,       # Haiku 캐시 읽힌 토큰
    "haiku_cache_create": 0,     # Haiku 캐시 생성된 토큰
    "haiku_input_uncached": 0,   # Haiku 비캐시 입력 토큰
}


def get_filter_metrics() -> dict:
    """현재까지 누적 메트릭 (관리자 진단용)"""
    return dict(_METRICS)


def reset_filter_metrics():
    for k in _METRICS:
        _METRICS[k] = 0


# ===== Pre-filter: RSS 제목 노이즈 패턴 (Haiku 호출 전 SKIP) =====
# 명백히 한국 시장과 무관한 라이프/연예/스포츠/사회 노이즈만 보수적으로 차단.
# false positive 방지를 위해 "확실한 noise"만 포함. 정치·금융·산업 단어는 제외.

_NOISE_KO = re.compile(
    # 스포츠·레저 (시장 직격 X)
    r"파크골프|야구장|축구장|등산로|캠핑장|스키장|마라톤|골프장 후기"
    # 음식·맛집·라이프
    r"|맛집|해장국|곰탕|국밥|효도템|꿀팁"
    # 황색언론 라이프 화제·동물·날씨
    r"|푹 빠진|민낯|불티난|화제 만발|뜨거운 반응|핫템|눈길 끄는|충격적|경악"
    # 사회면 일반 사건사고
    r"|노인.{0,8}(빠진|즐긴|푹)|어린이.{0,8}(사고|실종)|학생.{0,8}(폭행|실종)"
    # 부동산 분양·입찰 단독
    r"|단지\s*상가\s*입찰|아파트\s*분양\s*시작|모델하우스\s*오픈"
    # 한국 정치 단독 신경전 (인물 vs 인물)
    r"|신경전|말 바꿨|말 바꿔.{0,3}"
    # 포토·영상·갤러리·만평 prefix
    r"|^\[포토\]|^\[영상\]|^\[갤러리\]|^\[화보\]|^\[만평\]|^\[그래픽\]"
    # 산책·자전거 등 일상 활동
    r"|산책하다|자전거 타다",
    re.IGNORECASE,
)

_NOISE_EN = re.compile(
    # 제품 리뷰·가이드·언박싱 (시장 시그널 X)
    r"\b(review|hands.?on|unboxing|first look|impressions|test drive|deep dive guide)\b"
    # Top N / Best of / Buyer's guide
    r"|\b(best of|top \d+|buyer'?s guide|gift guide|holiday guide)\b"
    # 쇼핑 행사
    r"|\b(black friday|cyber monday|holiday deals|prime day|memorial day sale|labor day sale)\b"
    # 스포츠 메가 이벤트
    r"|\b(super bowl|world cup|olympics|world series|nba finals|nfl draft)\b"
    # 날씨·자연재해 (한국 시장 무관)
    r"|\b(weather forecast|hurricane warning|wildfire alert|tornado warning|blizzard)\b"
    # 미국 단독 정치 일상 (시장 직격 X)
    r"|\b(presidential debate|campaign rally|midterm election poll|primary results)\b"
    # 게임 패치노트·DLC
    r"|\b(patch notes|game update|DLC release|content drop)\b"
    # 라이프스타일·여행
    r"|\b(travel guide|vacation deals|food review|recipe)\b",
    re.IGNORECASE,
)


def _rule_pre_filter(event: dict) -> dict:
    """Haiku 호출 전 명백한 노이즈 차단 (비용 절감 1순위).

    DART/SEC는 통과 (공시는 별도 룰 + 신뢰성 높음).
    RSS만 제목으로 SKIP 판단.
    """
    src = event.get("source", "")
    if src != "RSS":
        return None

    title = event.get("title", "") or ""
    if not title:
        return None

    matched = None
    if _NOISE_KO.search(title):
        matched = "ko_noise"
    elif _NOISE_EN.search(title):
        matched = "en_noise"

    if matched:
        _METRICS["pre_filter_skip"] += 1
        return {
            "priority": "SKIP",
            "category": "C",
            "sector": "기타",
            "reason": f"pre_filter:{matched}",
            "significance": "",
            "source_method": "rule_pre",
        }
    return None


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

- 예고·추측·전망성 보도 (실체 의사결정·수치 없음):
  · "~ 실적발표 예정", "~ 앞두고" 단순 일정 공지 (결과 수치 無)
  · "~ 주목", "~ 수혜 기대", "~ 수혜주로 꼽혀", "~ 전망됨" 추측성
  · 장 마감·장 시작 해설 "오후 들어 ~ 담고", "~ 초점" 거래 해설
  → 예고·추측은 SKIP

  **⚠️ 단, 아래는 미래 이벤트여도 HIGH/URGENT 유지:**
  · 이사회 결의·Capex 집행 (예: "공장 증설 1,000억 투자 결정")
  · 공급계약·수주 체결 (미래 납품이어도 계약 체결은 실체)
  · 유상증자/자사주 소각/M&A/지분 인수 결정
  · 임상시험 진입·FDA 신청·승인
  · 공장 신설·준공·증설 발표 (규모·일정 명시 시)
  · 기업가치제고계획 구체 수치 포함
  · 실적전망·가이던스 공식 공시 (증권사 추정 아닌 회사 발표)
  → "결정됨 / 체결됨 / 집행 / 제출 / 승인" 같은 실체 동사가 있으면
    단순 예고 아닌 실체적 사업 이벤트로 판정

- 인사·조직: 임원 승진, CEO 후계, 조직개편, 회고담·인터뷰
  (매출·제품 파이프라인 직접 영향 수치가 없으면 SKIP)

- 과거 사건: 판결·수사 결과·법정 공방·벌금 (이미 시장에 반영됨)

- 원론적 거시 해설: "AI 시대 ~ 필요", "~ 중요하다", "~ 격변기" 류
  (구체 정책 수치나 당장의 밸류체인 파급 없으면)

- 단순 외신 정치 잡음: 미국 내 정치, 해외 인사 발언 (증시 직격 아니면)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[우선순위 — 시사점 강도에 따라]

- URGENT: 밸류체인+시급성 모두 해당 (대형 M&A, 거래정지, 자사주 소각, 실적 서프라이즈, FDA 승인, 지진/돌발)
- HIGH: 밸류체인·사이클·구조 변화 중 하나 강함 (Peer 실적, 가격 인상, Capex 1000억+, 5% 공시, BW/CB 발행)
- NORMAL: 의미는 있으나 즉시성 낮음 (월별 수출통계, 산업 리서치 리포트)
- SKIP: 시사점 없거나 노이즈

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[⚠️ 실적 공시 — "애매하면 SKIP" 규칙 예외 (2026-04-24 추가)]

아래 조건 중 하나라도 해당되면 **무조건 HIGH 이상**으로 판정.
"정기 공시" "반복적" 같은 이유로 SKIP/NORMAL 내리면 안 됨.

1) **국내 상장사 분기 실적 공시**:
   - report_nm에 "(잠정)실적", "손익구조30%변경", "손익구조15%변경" 포함 → URGENT
   - 본문에 매출·영업이익·순이익 절대액 또는 YoY/QoQ% 포함 → 무조건 HIGH+

2) **해외 빅테크·반도체·AI 인프라 Peer의 SEC 8-K Item 2.02**:
   - 실적 자체가 HBM·파운드리·데이터센터 등 한국 밸류체인 파급 신호
   - Intel/TSMC/Micron/Lam Research/Vertiv/Texas Instruments 등 전부 HIGH 이상
   - "관심도 낮음" "반복 공시" 이유로 내리지 말 것

3) **해외 기사에 기업명 + 수치(매출/EPS/guidance) + %증감 3요소 동시 포함**:
   - 예: "Apple Q1 revenue $95.4B (+12% YoY)" — HIGH 후보
   - 예: "SAP Q1 cloud revenue +19%" — HIGH 후보
   - 애매하게 "실적 기대", "주가 상승" 같은 논평 기사는 평소 기준 적용

4) **정확한 수치 제시 가이던스·계획**:
   - "FY26 매출 $13.5B~$14.0B" 같은 구체 레인지
   - "WFE 전망 1,350억 → 1,400억달러 상향" 같은 시장 전망 업데이트
   - 단순 "~할 것이다" 예고성은 평소 기준

이 4가지는 투자자가 텔레그램을 보는 핵심 이유 — 절대 놓치면 안 됨.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[해외 Peer 8-K 판정 기준]

빅테크·반도체 Peer(NVDA/TSM/AVGO/AMD/MU/ASML 등)의 8-K는 한국 반도체·
IT부품·2차전지 밸류체인에 직접 파급될 수 있음. Item 2.02(실적)·1.01(중대계약)·
8.01(기타 중요사건)은 HIGH 후보. 단순 Item 5.02(임원변경)·5.07(주총결과)은
대체로 NORMAL 또는 SKIP.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Template 카테고리]

- A: 해외 Peer 월매출/분기실적 (대만/일본/중국/미국 기업 IR)
- B: 국내 공시 (DART, KIND)
- C: 영문 기사/리서치 인용 (Reuters, Digitimes, Nikkei, TrendForce)
- D: 월별 수출통계 (TRASS, 관세청)
- E: 돌발 속보

[섹터]
반도체, 반도체 장비, 디스플레이, IT부품, 스마트폰, PC/서버, 빅테크/AI, 2차전지, 전기차, 석유/가스, LNG, 원전, 신재생, 수소, 철강/금속, 화학, 조선, 해운, 자동차, 방산, 우주항공, 건설, 바이오/제약, 의료기기, 식품/농업, 유통/커머스, 엔터/미디어, 게임, 호텔/레저/항공, 금융/은행, 보험, 증권, 부동산, 가상자산, 기타

섹터 매핑 힌트 (영문 기업명 가이드):
- 반도체: NVIDIA, Intel, AMD, Micron, TSMC, Broadcom, Qualcomm, ARM, Texas Instruments
- 반도체 장비: ASML, Lam Research, Applied Materials, KLA
- IT부품: Vertiv (데이터센터 전력), Arista (AI 네트워킹), Super Micro·Dell (AI 서버)
- 빅테크/AI: Alphabet·Google, Amazon, Meta, Netflix, Oracle, ServiceNow, IBM, SAP, Salesforce
- 스마트폰: Apple
- 전기차: Tesla
- 엔터/미디어: Comcast, T-Mobile, Disney

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
    Hybrid 필터: pre-filter → DART rule → Haiku → (HIGH/NORMAL이면) Sonnet 재검증.

    Returns:
        {"priority", "sector", "category", "reason", "significance",
         "source_method": "rule_pre|rule|haiku|hybrid_sonnet", ...}
    """
    # 0. Pre-filter: RSS 제목 노이즈 사전 차단 (Haiku 호출 자체 차단 → 비용 절감)
    pre = _rule_pre_filter(event)
    if pre is not None:
        return pre

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
    """필터용 user 메시지. 이벤트 자체만 객관적으로 평가 (시황봇 컨텍스트 미사용)."""
    source = event.get("source", "?")
    title = event.get("title", "")[:200]
    company = event.get("company_name", "")
    ticker = event.get("ticker") or ""
    body = event.get("body_excerpt") or event.get("original_content", "")
    body = body[:1200] if body else ""

    base = (
        f"[소스] {source}\n"
        f"[기업/주체] {company}" + (f" ({ticker})" if ticker else "") + "\n"
        f"[제목] {title}\n"
        f"[본문 요약]\n{body}\n"
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
            system=[
                {
                    "type": "text",
                    "text": FILTER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        _METRICS["sonnet_calls"] += 1
        text = response.content[0].text.strip()
        parsed = _parse_filter_json(text)
        if parsed:
            usage = response.usage
            parsed["tokens_used"] = {
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_create": getattr(usage, "cache_creation_input_tokens", 0) or 0,
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
            system=[
                {
                    "type": "text",
                    "text": FILTER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        _METRICS["haiku_calls"] += 1
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
        _METRICS["haiku_cache_read"] += cache_read
        _METRICS["haiku_cache_create"] += cache_create
        _METRICS["haiku_input_uncached"] += usage.input_tokens

        text = response.content[0].text.strip()
        parsed = _parse_filter_json(text)
        if parsed:
            parsed["source_method"] = "haiku"
            parsed["tokens_used"] = {
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": cache_read,
                "cache_create": cache_create,
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

# 섹터 추론 사전 — 회사명 substring 매칭 (한글·영문 통합).
# 2026-04-24: SEC 추적 기업의 company_name이 영문이라 기존 사전에서 매칭 실패
# (예: "Tesla" 기사가 "기타"로 분류) → 영문 주요 기업 대폭 추가.
_SECTOR_KEYWORDS = {
    "반도체": [
        # 한글
        "반도체", "메모리", "DRAM", "NAND", "HBM", "파운드리", "SK하이닉스", "삼성전자",
        # 영문 설계·제조·메모리
        "NVIDIA", "Intel", "AMD", "Micron", "TSMC", "Broadcom", "Qualcomm",
        "Arm Holdings", "Texas Instruments", "SK Hynix",
    ],
    "반도체 장비": [
        "반도체 장비", "WFE", "lithography",
        "ASML", "Lam Research", "Applied Materials", "KLA",
    ],
    "디스플레이": ["디스플레이", "OLED", "LCD", "패널", "LG디스플레이", "삼성D", "LGD"],
    "IT부품": [
        "기판", "PCB", "CCL", "FPCB", "ABF", "MLCC", "리드프레임", "FC-BGA",
        "대덕전자", "심텍", "LG이노텍", "해성디에스", "PI첨단소재", "네오티스", "이수페타시스", "삼성전기",
        # AI 인프라 (별도 섹터로 없고, IT부품 범주로 통합 — 데이터센터 전력/네트워킹)
        "Vertiv", "Arista", "Super Micro", "Dell Technologies",
    ],
    "스마트폰": ["스마트폰", "Apple", "iPhone"],
    "PC/서버": ["PC", "서버", "Microsoft", "Dell Technologies", "HP Inc"],
    "빅테크/AI": [
        # 신규 섹터: 미국 대형 IT — 스마트폰·SaaS·검색·전자상거래 복합
        "Alphabet", "Google", "Amazon", "Meta", "Netflix", "Oracle",
        "ServiceNow", "IBM", "SAP", "Salesforce",
    ],
    "2차전지": ["2차전지", "배터리", "리튬", "양극재", "음극재", "LG에너지솔루션", "삼성SDI",
              "SK온", "에코프로", "포스코퓨처엠", "엘앤에프"],
    "전기차": ["전기차", "EV", "테슬라", "Tesla"],
    "바이오/제약": ["바이오", "제약", "임상", "FDA", "삼성바이오", "셀트리온", "유한양행", "알테오젠"],
    "자동차": ["자동차", "현대차", "기아", "현대모비스", "한온시스템", "Ford", "General Motors", "Toyota"],
    "조선": ["조선", "HD현대중공업", "한화오션", "삼성중공업"],
    "방산": ["방산", "한화에어로", "LIG넥스원", "한국항공우주", "현대로템", "Lockheed", "Raytheon"],
    "철강/금속": ["철강", "POSCO", "포스코홀딩스", "현대제철", "동국제강"],
    "화학": ["화학", "LG화학", "롯데케미칼", "한화솔루션"],
    "건설": ["건설", "현대건설", "삼성물산", "GS건설", "대우건설"],
    "금융/은행": ["금융", "은행", "KB금융", "신한지주", "하나금융", "우리금융", "JP Morgan", "Goldman Sachs"],
    "증권": ["증권", "미래에셋", "한국투자", "키움", "삼성증권", "NH투자"],
    "게임": ["게임", "크래프톤", "엔씨소프트", "넷마블", "펄어비스"],
    "엔터/미디어": ["엔터", "하이브", "에스엠", "JYP", "YG", "CJ ENM",
                 # 미국 통신·미디어
                 "Comcast", "T-Mobile", "Verizon", "AT&T", "Disney"],
    "원전": ["원전", "두산에너빌리티", "한전KPS"],
    "LNG": ["LNG", "SK E&S", "한국가스공사"],
    "유통/커머스": ["유통", "쿠팡", "이마트", "GS리테일", "현대백화점", "Walmart", "Target"],
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
