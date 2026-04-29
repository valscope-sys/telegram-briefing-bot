"""본문 생성기 — Claude Sonnet + style_canon.md

파이프라인:
1. style_canon.md 로딩 (캐시)
2. Template(A~E)에 맞는 프롬프트 조립
3. Claude Sonnet 호출 with cache_control (few-shot 캐싱)
4. 생성 후 linter로 자체 검증
5. 위반 발견 시 1회 재생성 (위반 항목 제약으로 추가)
6. 캐시 히트율 로깅
"""
import os
import json
import datetime
import anthropic

from telegram_bot.config import (
    ANTHROPIC_API_KEY,
    ISSUE_BOT_GENERATOR_MODEL,
    ISSUE_BOT_ENABLE_CACHING,
)
from telegram_bot.issue_bot.pipeline.linter import lint_r1_r8, lint_summary

HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
)
STYLE_CANON_PATH = os.path.join(HISTORY_DIR, "style_canon.md")
CACHE_STATS_PATH = os.path.join(HISTORY_DIR, "issue_bot", "cache_stats.jsonl")


_style_canon_cache = None
_client = None


def _load_style_canon():
    global _style_canon_cache
    if _style_canon_cache is not None:
        return _style_canon_cache
    try:
        with open(STYLE_CANON_PATH, "r", encoding="utf-8") as f:
            _style_canon_cache = f.read()
    except FileNotFoundError:
        print(f"[GENERATOR] style_canon.md 없음: {STYLE_CANON_PATH}")
        _style_canon_cache = ""
    return _style_canon_cache


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _log_cache_stats(usage):
    """캐시 히트율 누적 로깅"""
    os.makedirs(os.path.dirname(CACHE_STATS_PATH), exist_ok=True)
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
    }
    try:
        with open(CACHE_STATS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _build_fallback_content(event: dict, classification: dict) -> str:
    """Sonnet 실패 / 빈 응답 / 본문 극히 짧은 경우 — 최소 본문 자동 구성.

    채널에 '본문 없음' 상태로 발송되는 UX 버그 방지.
    """
    company = (event.get("company_name") or "").strip()
    title = (event.get("title") or "").strip()
    url = event.get("source_url", "")
    source = event.get("source", "")
    template = classification.get("category", "C")

    header_line = f"[{company} {title}]" if company else f"[{title}]"
    parts = [header_line, ""]

    body = (event.get("body_excerpt") or event.get("original_content") or "").strip()
    if body:
        parts.append(body[:600])
    else:
        parts.append("※ 상세 내용은 원본 링크를 참조하세요.")
    parts.append("")

    if url:
        parts.append(f"원문: {url}")
    if source:
        parts.append(f"(자료: {source})")

    if template != "E":
        parts.append("")
        parts.append(
            "* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, "
            "투자 판단과 그 결과의 책임은 본인에게 있습니다."
        )

    return "\n".join(parts)


def _build_user_message(event: dict, classification: dict) -> str:
    """이벤트 → user 프롬프트"""
    template = classification.get("category", "C")
    sector = classification.get("sector", "기타")

    title = event.get("title", "").strip()
    company = event.get("company_name", "")
    # SEC 실적(Exhibit 99.1 포함)은 Shareholder Update PDF → 재무 테이블이 뒷부분.
    # 3000자로 자르면 매출/영업이익 Key Metrics 표 절단 → 6000자로 확대.
    body = event.get("body_excerpt") or event.get("original_content", "")
    body_limit = 6000 if event.get("has_exhibit_body") else 1500
    body = body.strip()[:body_limit] if body else ""
    source_url = event.get("source_url", "")
    source_type = event.get("source", "")
    report_clean = event.get("report_nm_clean") or ""

    # SEC 8-K 실적·중대공시 전용 지시
    sec_note = ""
    if event.get("source") == "SEC" and event.get("has_exhibit_body"):
        sec_primary = event.get("sec_primary_item", "?")
        sec_note = (
            f"\n\n[SEC 8-K Item {sec_primary} — Exhibit 본문 포함]\n"
            "본문은 Exhibit 99.1 (press release) + 99.2 (IR presentation) 통합본.\n"
            "**⚠️ 절대 원칙**: 본문에 실제 매출·영업이익·EPS 숫자가 **반드시 있음**. "
            "못 찾겠으면 본문 끝까지 스캔하세요 (재무 테이블은 보통 본문 중간~후반부).\n\n"
            "**본문에서 다음 수치를 반드시 추출해 bullet으로 나열**:\n"
            "  - 매출 / Revenue / Total revenues (절대액 + YoY%)\n"
            "  - 영업이익 / Operating income / Income from operations\n"
            "  - 순이익 / Net income (GAAP + non-GAAP 구분)\n"
            "  - EPS / Diluted EPS\n"
            "  - 사업부별 매출 분해 (Automotive / Services / Energy 등)\n"
            "  - 가이던스·Outlook (본문에 있으면)\n\n"
            "**금지 문구** (이 표현 쓰면 카드 리젝):\n"
            "  × '제출했다' '공시했다' '발표했다'\n"
            "  × '공개 예정' '별도 첨부를 통해 공개'\n"
            "  × '상세 수치는 원문 참조' '세부 내용은 링크에서'\n"
            "  × 'Form 8-K를 제출하며 ~관련 정보를 공시'\n"
            "→ 본문에 숫자가 있는 것을 그대로 씁니다. 원문 링크로 떠넘기지 말 것.\n\n"
            "**만약 본문을 아무리 봐도 구체 수치가 0개면**: 응답 맨 끝에 정확히 `[NO_DATA]` 태그 추가. "
            "이 태그가 붙으면 파이프라인이 카드 발송을 자동 보류합니다."
        )

    # 본문이 짧은 경우: 제목·유형의 의미 중심으로 구성
    short_body_note = ""
    if len(body) < 120:
        short_body_note = (
            "\n\n[⚠️ 원문 발췌가 짧음]\n"
            f"공시/기사 유형: '{report_clean or title[:60]}'\n"
            "구체 수치가 본문에 없을 때 작성 원칙:\n"
            "1) 제목·유형의 의미를 투자자 관점에서 2~3 bullet으로 구조화 (예: '자기주식 소각 = 주주환원 + EPS 제고')\n"
            "2) 해당 공시/이벤트가 통상 어떤 밸류체인 영향을 주는지 일반 상식 기반 해설 (창작 금지, 원문 사실 기반)\n"
            "3) 본문에 없는 구체 수치·금액·날짜·목표가 **절대 창작 금지**\n"
            "4) '제출', '공시', '발표 예정' 같은 메타 문구 단독 사용 금지 — 내용 없이 끝내지 말 것\n"
            "5) 정말로 쓸 말이 없으면 응답 맨 끝에 정확히 `[NO_DATA]` 태그 추가. 카드 발송 보류됨."
        )

    # Peer는 "영향 해석 대상" — 단순 나열이 아니라 본문에서 분석 재료로 활용
    peers = event.get("peer_map_used", [])
    if peers:
        peer_block = (
            f"[영향 해석 대상 (국내 Peer)]\n"
            f"{', '.join(peers)}\n\n"
            f"**중요 지시**: 본 이벤트가 위 Peer들에 미칠 수 있는 영향을 **본문 내에서** 자연스럽게 풀어 설명하세요.\n"
            f"- 긍정/부정/중립 방향을 수치·사실 근거와 함께 제시 (예: 'HBM 가동률 상향 → SK하이닉스 Q2 출하 확대 가능')\n"
            f"- 근거 없는 추측성 전망 금지 — 원문에 수치/사실이 있을 때만 영향 추론\n"
            f"- Peer 이름은 본문 내 문장으로 녹이세요 (별도 나열 금지)\n"
        )
    else:
        peer_block = "[영향 해석 대상] (없음 — Peer 영향 언급 없이 원문 사실만 재구성)\n"

    return f"""새 이벤트를 Template {template} 형식으로 변환하세요.

[이벤트 메타]
- 소스: {source_type}
- 원본 URL: {source_url}
- 기업/주체: {company}
- 제목: {title}
- 공시/기사 유형: {report_clean or '(해당없음)'}
- Template: {template}
- 섹터: {sector}

[원문 발췌]
{body}
{short_body_note}{sec_note}

{peer_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[작성 3단계 — 반드시 순서대로]

1) **번역**: 원문이 영어/일어/중어면 한국어로 먼저 번역. 표·수치는 그대로 유지.

2) **정리**: 번역된 내용에서 투자자 관점 **핵심 수치·사실** 추출:
   - 실적이면: 매출/영업이익/EPS (절대액 + YoY%)
   - M&A면: 규모·대상·완료 예정일
   - Capex/증설이면: 투자 규모·공장 위치·가동 예정
   - 공시 유형이면: 그 유형의 의미 1문장 설명
   → 숫자와 팩트만 남기고 군더더기 제거.

3) **해석 (필수)**: 이 이벤트가 **한국 시장/투자자에게 어떻게 해석될지** 1~2문장:
   - 밸류체인 파급 (예: "TSMC 가이던스 상향 → HBM 수요 견조 → SK하이닉스 수혜 가능")
   - 섹터 사이클 시그널
   - 경쟁구도 변화
   - 이미 [영향 해석 대상] Peer가 주어졌으면 그들 중심으로 서술
   → 단, **근거 없는 전망·목표가·수혜종목 창작 금지**. 원문·Peer 사실 기반만.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[작성 원칙]
- R1~R8 규칙 절대 준수
- Template {template} 형식 (구조·길이)
- {'면책 문구 포함' if template != 'E' else '면책 문구 생략 (E 속보)'}
- "제출했다" "발표할 예정" 같은 메타 문구 지양 — 실제 수치·사실이 핵심
- Exhibit 99.2 (IR presentation) 본문이 있으면 가이던스·컨콜 코멘트 반영

본문만 출력. 다른 설명 금지."""


def generate_message(event: dict, classification: dict, retry_violations: list = None) -> dict:
    """
    이벤트 → Template 본문 생성.

    Args:
        event: dart_collector/rss_adapter 결과 + peer_map_used 포함
        classification: filter.filter_event() 결과
        retry_violations: 재시도 시 이전 위반 내역 (프롬프트에 추가 제약으로 주입)

    Returns:
        {
          "generated_content": "...",
          "violations": [...],
          "retry_count": 0,
          "tokens_used": {...},
        }
    """
    # 2026-04-24: DART 잠정실적 공시는 rule-based 파서 우선 — Sonnet 실패 시
    # body 덤프되던 "| | | |" 표 형식 카드 방지. 구조 고정이라 정확도·속도·비용
    # 모두 Sonnet보다 우수.
    try:
        from telegram_bot.issue_bot.pipeline.earnings_parser import try_generate_earnings_card
        earnings_card = try_generate_earnings_card(event)
        if earnings_card:
            return {
                "generated_content": earnings_card,
                "violations": [],  # rule-based 파서는 R1~R8 준수 보장
                "retry_count": 0,
                "tokens_used": {},
                "used_parser": "earnings",
            }
    except Exception as e:
        # 파서 예외 발생해도 Sonnet 경로로 떨어지도록
        print(f"[GENERATOR] earnings_parser 예외 (Sonnet으로 fallback): {e}")

    if not ANTHROPIC_API_KEY:
        return {
            "generated_content": _build_fallback_content(event, classification),
            "violations": [{"rule": "GENERAL", "detail": "ANTHROPIC_API_KEY 없음 — 폴백 본문"}],
            "retry_count": 0,
            "tokens_used": {},
            "used_fallback": True,
        }

    # 본문 짧아도 Sonnet 호출 유지 — 제목+공시유형의 의미를 풀어 설명하도록 지시
    # (과거엔 30자 미만이면 폴백이었으나, 사용자 피드백: "원문 참조" 대신 의미 설명 요구)

    style_canon = _load_style_canon()
    user_msg = _build_user_message(event, classification)

    if retry_violations:
        retry_note = "\n\n[이전 생성본 위반 내역 — 이번엔 반드시 피하세요]\n" + \
                     "\n".join(f"- {v['rule']}: {v['detail']}" for v in retry_violations)
        user_msg += retry_note

    # System prompt에 style_canon 삽입 + 캐시 컨트롤
    system_blocks = [
        {
            "type": "text",
            "text": "당신은 NODE Research 이슈 봇의 본문 생성기입니다. "
                    "아래 스타일 경전의 R1~R8 규칙과 Template 완벽 예시를 따릅니다.\n\n" + style_canon,
        }
    ]
    if ISSUE_BOT_ENABLE_CACHING:
        # TTL 1h: 폴링 주기(10분)보다 길게 잡아 폴링간 캐시 hit 보장.
        # 기본 5분 ttl로는 다음 폴링 첫 호출이 항상 miss → cache 무력화.
        # cache create 단가 2배지만 hit율 60% → 90%+ 상승 효과가 훨씬 큼.
        system_blocks[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}

    try:
        client = _get_client()
        # 1h cache_control TTL은 베타 헤더 필요 (extended-cache-ttl-2025-04-11)
        extra_headers = (
            {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
            if ISSUE_BOT_ENABLE_CACHING else {}
        )
        response = client.messages.create(
            model=ISSUE_BOT_GENERATOR_MODEL,
            max_tokens=1500,
            system=system_blocks,
            messages=[{"role": "user", "content": user_msg}],
            extra_headers=extra_headers,
        )
        generated = response.content[0].text.strip()
        _log_cache_stats(response.usage)

        # Sonnet이 빈 응답 반환 시 폴백
        if not generated:
            print("[GENERATOR] Sonnet 빈 응답 — 폴백 본문 사용")
            return {
                "generated_content": _build_fallback_content(event, classification),
                "violations": [{"rule": "GENERAL", "detail": "Sonnet 빈 응답 — 폴백 본문"}],
                "retry_count": 1 if retry_violations else 0,
                "tokens_used": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens,
                },
                "used_fallback": True,
            }

        # 린트
        template = classification.get("category", "C")
        violations = lint_r1_r8(generated, template)

        return {
            "generated_content": generated,
            "violations": violations,
            "retry_count": 1 if retry_violations else 0,
            "tokens_used": {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "cache_creation": getattr(response.usage, "cache_creation_input_tokens", 0),
                "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
            },
        }
    except Exception as e:
        print(f"[GENERATOR] Sonnet 호출 실패: {e} — 폴백 본문 사용")
        return {
            "generated_content": _build_fallback_content(event, classification),
            "violations": [{"rule": "GENERAL", "detail": f"Sonnet 실패 — 폴백 본문: {e}"}],
            "retry_count": 0,
            "tokens_used": {},
            "used_fallback": True,
        }


def generate_with_retry(event: dict, classification: dict, max_retry: int = 1) -> dict:
    """
    generate_message + 린트 실패 시 자동 재시도 (최대 1회).

    Returns: generate_message 결과 + 최종 violations.
    """
    result = generate_message(event, classification)

    if not result["violations"] or max_retry == 0:
        return result

    # 위반 있으면 1회 재시도
    retry = generate_message(event, classification, retry_violations=result["violations"])
    if len(retry["violations"]) < len(result["violations"]):
        # 개선된 경우에만 교체
        retry["retry_count"] = 1
        return retry
    # 개선 안 됐으면 원본 반환 (violations 유지)
    return result


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트: 가상의 자사주 소각 이벤트
    event = {
        "source": "DART",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260421000999",
        "company_name": "삼성전자",
        "title": "주요사항보고서(자기주식소각결정)",
        "body_excerpt": "이사회 결의에 따라 보통주 5,000만주(약 3.5조원 규모)를 소각하기로 결정. "
                        "소각 예정일: 2026-05-15. 자사주 매입 공시 금액 7.17조원 중 완료된 물량 중 일부를 소각. "
                        "소각 후 자본금 감소 없음. 자사주 매입·소각은 주주환원 정책 일환.",
        "peer_map_used": [],
    }
    classification = {
        "priority": "URGENT",
        "category": "B",
        "sector": "반도체",
        "reason": "dart_category_map: 자기주식소각결정",
    }

    print("Generator 테스트 — 삼성전자 자사주 소각")
    print("=" * 70)
    result = generate_with_retry(event, classification)
    print("\n[생성된 본문]")
    print("-" * 70)
    print(result["generated_content"])
    print("-" * 70)
    print(f"\n[위반]: {lint_summary(result['violations'])}")
    print(f"[재시도]: {result['retry_count']}회")
    print(f"[토큰]: {result['tokens_used']}")
