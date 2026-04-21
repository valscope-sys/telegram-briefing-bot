"""v1/v2 프롬프트 A/B 품질 비교 스크립트.

동일 data_summary 로 v1·v2 각 1회씩 호출하고 결과를 파일로 저장.
사용자가 출력 품질을 직접 비교.

사용:
    python scripts/ab_test_prompts.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from telegram_bot.config import ANTHROPIC_API_KEY
from telegram_bot.prompts_v2 import (
    PROMPT_SYSTEM_V2,
    PROMPT_EVENING_TEMPLATE_V2,
    PROMPT_MORNING_TEMPLATE_V2,
)
from telegram_bot.collectors.news_collector import PROMPT_SYSTEM as V1_SYS


# 2026-04-20 실제 snapshot 기반 재구성 데이터
SAMPLE_EVENING_DATA = """=== 오늘 시장 데이터 ===
KOSPI: 6,219.09 (+0.44%)
KOSDAQ: 1,174.85 (+0.41%)

수급: 외국인 -1,598억 / 기관 +1,815억 / 개인 -2,774억

업종별 외국인 순매수 (억원):
  반도체: 외국인 +2,103억 / 기관 +512억
  2차전지: 외국인 +845억 / 기관 +1,120억
  ...
  자동차: 외국인 -3,251억 / 기관 -180억
  건설: 외국인 -420억 / 기관 -95억

섹터 ETF 등락:
  2차전지: +2.18%  LG에너지솔루션(+1.2%), 에코프로비엠(+2.8%)
  반도체: +1.81%  삼성전자(+0.5%), SK하이닉스(+3.37%)
  방산: +0.47%
  바이오: -0.16%
  금융: -0.37%
  자동차: -1.57%  현대차(-2.0%), 기아(-1.1%)

거래대금 상위 10종목:
  1. 삼성전자 +0.52%
  2. SK하이닉스 +3.37%
  3. LG에너지솔루션 +1.20%
  4. 에코프로비엠 +2.80%
  5. 삼성SDI +4.50%
  6. 현대차 -2.00%
  7. 기아 -1.10%
  8. 셀트리온 -0.80%
  9. 크래프톤 +1.80%
  10. HD한국조선해양 +0.90%

채권금리:
  미국 10Y: 4.260% (-0.060%p)
  국고채 3Y: 3.120% (-0.015%p)

환율:
  USD/KRW: 1,472.7 (+12.70)
  DXY(달러인덱스): 103.45 (+0.15%)

원자재:
  WTI: $83.85 (-11.45%)
  금: $4,857.60 (+1.51%)
  구리: $6.10 (+0.61%)

주요 뉴스:
- [2차전지] 삼성SDI, 벤츠와 차세대 하이니켈 NCM 배터리 공급계약 체결 (긍정)
  요약: 삼성SDI가 메르세데스-벤츠와 고성능 NCM 배터리 장기 공급 계약을 체결.
- [중동] 호르무즈 해협 선박 공격 재개, 이란 휴전 협상 불확실성 증대 (부정)
  요약: 주말 선박 공격으로 중동 긴장 재고조, 4/22 휴전 만료 앞두고 협상 난항.
- [반도체] SK하이닉스 HBM3E 양산 본격화, 엔비디아 추가 공급 기대 (긍정)
  요약: SK하이닉스 HBM3E 12단 양산 돌입, 엔비디아 H200 공급 확대 전망.
- [자동차] 현대차 1분기 판매 부진, 북미 재고 증가 우려 (부정)
  요약: 현대차 1분기 글로벌 판매 전년 대비 2.3% 감소, 북미 재고 조정 필요.
"""

V1_EVENING_STATIC = """

위 데이터를 바탕으로 오늘 시장 시황을 작성해주세요.
증권사 리서치센터 애널리스트 팀장이 텔레그램 채널 구독자(개인 투자자)에게 장 마감 시황을 전달합니다.

[작성 방식 — 3단계 사고]
1단계: 데이터로 큰 그림
2단계: 필요 시 웹 검색
3단계: 뉴스는 증거로

[해석 vs 팩트]
해석은 자유, 팩트는 데이터/뉴스에 있을 때만.

[구조]
📈 오늘의 국면
🔍 핵심 동인
🔄 섹터 로테이션
💰 수급
⚠️ 리스크 체크

각 섹션별 2~4문장. 소제목 정확히 복사. 서식 없이 텍스트만. 14~18문장.

[금지]
화살표, 주목됩니다, 뉴스 재탕, 단일 종목 확대 해석, 개인 매도 긍정 편향.

시황만 작성하세요."""


def run_one(client, model, system, user_prompt, label):
    """단일 API 호출 + 결과 저장."""
    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        temperature=0.3,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed = time.time() - t0
    text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
    u = resp.usage
    return {
        "label": label,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "elapsed_sec": elapsed,
        "text": text,
    }


def main():
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY 없음 — .env 확인")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    model = "claude-sonnet-4-20250514"

    # v1 (간소화된 v1 스터브 — 원본은 너무 길어서 5000 tokens 상회)
    v1_prompt = SAMPLE_EVENING_DATA + V1_EVENING_STATIC

    # v2
    v2_prompt = PROMPT_EVENING_TEMPLATE_V2.format(data_summary=SAMPLE_EVENING_DATA)

    print("[AB] v1 호출 중...")
    v1_result = run_one(client, model, V1_SYS, v1_prompt, "v1 (간소 스터브)")
    print(f"  input={v1_result['input_tokens']}, output={v1_result['output_tokens']}, {v1_result['elapsed_sec']:.1f}s")

    print("[AB] v2 호출 중...")
    v2_result = run_one(client, model, PROMPT_SYSTEM_V2, v2_prompt, "v2")
    print(f"  input={v2_result['input_tokens']}, output={v2_result['output_tokens']}, {v2_result['elapsed_sec']:.1f}s")

    # 결과 파일
    out_path = Path(__file__).parent.parent / "telegram_bot" / "history" / "ab_test_output.md"
    with out_path.open("w", encoding="utf-8") as f:
        f.write("# v1 vs v2 프롬프트 A/B 테스트 결과\n\n")
        f.write(f"- 모델: `{model}`\n")
        f.write(f"- 데이터: 2026-04-20 snapshot 재구성\n\n")
        f.write("## 토큰·시간\n\n")
        f.write(f"| 버전 | input | output | 시간 |\n|---|---|---|---|\n")
        f.write(f"| v1 (간소 스터브) | {v1_result['input_tokens']} | {v1_result['output_tokens']} | {v1_result['elapsed_sec']:.1f}s |\n")
        f.write(f"| v2 | {v2_result['input_tokens']} | {v2_result['output_tokens']} | {v2_result['elapsed_sec']:.1f}s |\n\n")
        f.write("주의: v1 스터브는 원본 v1(~5000 tokens) 대비 간소화된 참고용. 실제 운영 v1은 더 무거움.\n\n")
        f.write("---\n\n## v1 출력\n\n```\n")
        f.write(v1_result["text"])
        f.write("\n```\n\n---\n\n## v2 출력\n\n```\n")
        f.write(v2_result["text"])
        f.write("\n```\n")

    print(f"\n[AB] 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
