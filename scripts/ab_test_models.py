"""Sonnet vs Opus 실제 시황 생성 비교.

동일 데이터·동일 v2 프롬프트로 모델만 바꿔 호출.
결과는 telegram_bot/history/ab_test_models.md 에 저장.

주의: 실 API 호출 — Sonnet 1회 + Opus 1회 (~$1 소요).
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from telegram_bot.config import ANTHROPIC_API_KEY
from telegram_bot.prompts_v2 import PROMPT_SYSTEM_V2, PROMPT_EVENING_TEMPLATE_V2


# 2026-04-21 이브닝 실제 데이터 재구성 (감수 리포트에서 언급된 숫자들)
SAMPLE_DATA = """=== 오늘 시장 데이터 ===
KOSPI: 6,287.23 (+1.09%)
KOSDAQ: 1,186.45 (+0.98%)
상승 482 · 하락 380 · 보합 45

수급: 외국인 +11,565억 / 기관 +3,820억 / 개인 -15,840억
전일: 외국인 -3,210억 / 기관 -1,250억 / 개인 +4,680억 (8거래일 연속 매도 후 전환)

업종별 외국인 순매수 (억원):
  전기전자: 외국인 +8,420억 / 기관 +2,180억
  화학: 외국인 +1,850억 / 기관 +520억
  금융업: 외국인 +620억 / 기관 +180억
  운수장비: 외국인 -420억 / 기관 +80억
  건설업: 외국인 -180억 / 기관 -95억

섹터 ETF 등락:
  반도체: +0.75%  삼성전자(+0.5%), SK하이닉스(+2.1%)
  2차전지: +2.35%  LG에너지솔루션(+3.2%), 에코프로비엠(+2.8%)
  방산: +1.12%
  바이오: +0.40%
  금융: +0.80%
  자동차: -0.65%  현대차(-0.8%), 기아(-0.5%)

거래대금 상위 10종목:
  1. 삼성전자 +0.52%
  2. SK하이닉스 +2.10%
  3. LG에너지솔루션 +3.20%
  4. 에코프로비엠 +2.80%
  5. 삼성SDI +4.80%
  6. 이수페타시스 +5.20%
  7. 한미반도체 +3.40%
  8. LG이노텍 -2.50%
  9. 현대차 -0.80%
  10. HD한국조선해양 +1.20%

52주 신고가 (15종목)
(반도체소재) 솔브레인, 덕산네오룩스, 동진쎄미켐
(2차전지소재) 대주전자재료, 나노신소재, 엔켐
(반도체장비) 이오테크닉스, HPSP, 주성엔지니어링
(AI/소프트웨어) 포스코DX, 쿠콘
(로봇) 유일로보틱스

채권금리:
  미국 3M: 3.598% (+0.003%p)
  미국 2Y: 3.806% (+0.020%p)
  미국 10Y: 4.300% (+0.040%p)
  10Y-2Y 스프레드: +0.494%p
  10Y-3M 스프레드: +0.702%p (NY Fed 리세션 지표)

환율:
  USD/KRW: 1,478.2 (+6.90, +0.47%)
  DXY(달러인덱스): 103.80 (+0.36%)

원자재:
  WTI: $90.22 (+0.68%)
  금: $4,792.50 (-1.42%)
  구리: $6.12 (+0.33%)

심리지표:
  VIX: 19.50 (+3.34%)
  Fear & Greed: 62점 (Greed)

주요 뉴스:
- [반도체] 엔비디아, 한국 부품사와 합숙하며 부품 조달 본격화 (긍정)
  요약: 엔비디아가 한국 AI 기판·반도체 장비사와 공급망 협력 확대.
- [자동차/전자] 애플 CEO 팀 쿡 교체설 부각, 기술주 전반 단기 부담 (부정)
  요약: 외신 보도에 애플 CEO 교체 가능성 제기, 공급망 종목 변동성 확대.
- [중동] 트럼프, 이란 휴전 연장 발표 vs 이란 2차 협상 불참 통보 (중립)
  요약: 휴전 연장은 긍정, 그러나 이란 추가 협상 불참으로 불확실성 지속.
- [매크로] 미국 10년물 금리 4.3% 돌파, 예산안 협상 난항 (부정)
  요약: 예산 상한 협상 난항에 국채금리 상승, 달러 강세.
- [2차전지] 유럽 배터리 규제 강화안 통과, K-배터리 수혜 기대 (긍정)
  요약: 유럽 의회 CO2 규제 강화로 2차전지 업종 중장기 수혜 전망.
- [반도체] SK하이닉스 HBM3E 양산 본격화, 엔비디아 추가 공급 기대 (긍정)
  요약: HBM3E 12단 양산 돌입.

장중 흐름:
  KOSPI 시가 6,254 → 고가 6,295 → 저가 6,245 → 종가 6,287.23

수급 트렌드:
  외국인 1거래일 순매수 전환 (8거래일 매도 후)
  기관 3거래일 연속 순매수
"""


def run_one(client, model, label):
    """단일 모델 호출."""
    prompt = PROMPT_EVENING_TEMPLATE_V2.format(data_summary=SAMPLE_DATA)
    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        temperature=0.3,
        system=PROMPT_SYSTEM_V2,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.time() - t0
    text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
    u = resp.usage
    return {
        "label": label,
        "model": model,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "elapsed_sec": elapsed,
        "text": text,
    }


def estimate_cost(result, pricing):
    """해당 호출 단건 비용 $"""
    return result["input_tokens"] / 1_000_000 * pricing["in"] + result["output_tokens"] / 1_000_000 * pricing["out"]


def main():
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY 없음")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print("[AB] Sonnet 4 호출...")
    sonnet = run_one(client, "claude-sonnet-4-20250514", "Sonnet 4")
    print(f"  {sonnet['elapsed_sec']:.1f}s | in={sonnet['input_tokens']} out={sonnet['output_tokens']}")

    print("[AB] Opus 4 호출...")
    opus = run_one(client, "claude-opus-4-20250514", "Opus 4")
    print(f"  {opus['elapsed_sec']:.1f}s | in={opus['input_tokens']} out={opus['output_tokens']}")

    # 비용 계산
    pricing = {
        "Sonnet 4": {"in": 3, "out": 15},
        "Opus 4": {"in": 15, "out": 75},
    }
    sonnet_cost = estimate_cost(sonnet, pricing["Sonnet 4"])
    opus_cost = estimate_cost(opus, pricing["Opus 4"])

    out_path = Path(__file__).parent.parent / "telegram_bot" / "history" / "ab_test_models.md"
    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Sonnet 4 vs Opus 4 시황 생성 비교\n\n")
        f.write(f"- 데이터: 2026-04-21 이브닝 가상 데이터 (감수 리포트 반영)\n")
        f.write(f"- 프롬프트: v2 + P0/P2 보강\n\n")
        f.write("## 메트릭\n\n")
        f.write("| 모델 | input | output | 시간 | 단건 비용 | 월 추정 (44회) |\n|---|---|---|---|---|---|\n")
        f.write(f"| Sonnet 4 | {sonnet['input_tokens']} | {sonnet['output_tokens']} | {sonnet['elapsed_sec']:.1f}s | ${sonnet_cost:.4f} | ${sonnet_cost*44:.2f} |\n")
        f.write(f"| Opus 4   | {opus['input_tokens']} | {opus['output_tokens']} | {opus['elapsed_sec']:.1f}s | ${opus_cost:.4f} | ${opus_cost*44:.2f} |\n\n")
        f.write(f"→ Opus 가 Sonnet 대비 {opus_cost/sonnet_cost:.1f}배 비쌈\n\n")
        f.write("---\n\n## Sonnet 4 출력\n\n```\n")
        f.write(sonnet["text"])
        f.write("\n```\n\n---\n\n## Opus 4 출력\n\n```\n")
        f.write(opus["text"])
        f.write("\n```\n")

    print(f"\n[AB] 결과 저장: {out_path}")
    print(f"[AB] Sonnet 비용: ${sonnet_cost:.4f} / 월 추정 ${sonnet_cost*44:.2f}")
    print(f"[AB] Opus 비용:  ${opus_cost:.4f} / 월 추정 ${opus_cost*44:.2f}")


if __name__ == "__main__":
    main()
