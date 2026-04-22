"""시황 텍스트 후처리 — 줄바꿈 + 표현 정리 + 중요 데이터 누락 방지"""
import re


def ensure_critical_data_mentioned(text, global_data):
    """후처리 안전장치 — 중요 이벤트가 시황에 누락되면 보완 라인 추가.

    KORU: |등락률| ≥ 4% 일 때 모델이 언급 누락하면 한국 체크포인트 끝에 1줄 추가.
    (±2~4% 구간은 모델 재량으로 두어 매일 반복되는 AI 느낌 방지)
    """
    if not text or not global_data:
        return text

    korea_proxies = global_data.get("korea_proxies", {})
    koru = korea_proxies.get("KORU", {})
    if not koru or "error" in koru:
        return text

    koru_pct = koru.get("등락률", 0)
    if abs(koru_pct) < 4.0:
        return text

    # 이미 언급됐으면 그대로
    if "KORU" in text or "야간 프록시" in text:
        return text

    # 임플라이드 갭 (3x 레버리지)
    implied = koru_pct / 3.0
    direction = "급락" if koru_pct < 0 else "급등"
    risk_note = (
        f"\n\n(후주입) 야간 KORU 가 {koru_pct:+.2f}% {direction}했습니다. "
        f"3배 레버리지 특성상 실제 예상 갭은 약 {implied:+.1f}% 수준이라 "
        f"한국 특유의 리스크 반영 가능성을 염두에 둘 필요가 있습니다."
    )

    # 🇰🇷 한국 체크포인트 섹션 끝에 붙이기 (모닝 전용 구조)
    kr_marker = "🇰🇷 오늘 한국 증시 체크포인트"
    idx = text.find(kr_marker)
    if idx >= 0:
        # 마커 이후 마지막 문장 뒤에 추가
        return text.rstrip() + risk_note
    # 이브닝 구조거나 마커 없으면 그냥 끝에 추가
    return text.rstrip() + risk_note


def postprocess_commentary(text):
    """시황 텍스트를 후처리해서 가독성 개선"""
    if not text:
        return text

    # 1. 화살표(→) 제거 — 자연어로 변환 (하이픈 보존)
    text = text.replace(" → ", ", ")
    text = text.replace("→ ", ", ")
    text = text.replace(" →", ",")

    # 1-1. 하이픈 누락 복원 (미-이란, 미-중 등)
    text = text.replace("미이란", "미-이란")
    text = text.replace("미중", "미-중")

    # 2. 전환어 앞에 빈 줄
    transition_words = [
        "다만 ", "다만,", "반면 ", "반면,",
        "한편 ", "한편,", "한편으로",
    ]
    for word in transition_words:
        text = text.replace(f". {word}", f".\n\n{word}")
        text = text.replace(f".\n{word}", f".\n\n{word}")

    # 3. 주제 전환 앞에 빈 줄
    topic_changes = [
        "오늘 한국 증시", "오늘 국내 증시",
        "수급 측면", "수급에서", "수급 면에서",
        "원달러 환율", "원/달러",
    ]
    for phrase in topic_changes:
        text = text.replace(f". {phrase}", f".\n\n{phrase}")
        text = text.replace(f".\n{phrase}", f".\n\n{phrase}")

    # 4. 국면 정의 첫 문장 뒤 빈 줄
    # "~습니다." "~입니다." 등 한국어 서술형 마침표 뒤에서만 줄바꿈
    # 숫자 뒤 마침표(0.08%)나 영문 약어(S&P) 등에서 잘리지 않도록
    match = re.search(r'[가-힣]\.\s', text[:200])
    if match:
        pos = match.start() + 1  # 마침표 위치
        after = text[pos + 1:pos + 3]
        if after and not after.startswith("\n\n"):
            text = text[:pos + 1] + "\n\n" + text[pos + 1:].lstrip("\n ")

    # 5. 중복 빈 줄 정리 (3줄 이상 → 2줄로)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 6. 어색한 표현 제거
    awkward = [
        ("반가운 신호입니다", "긍정적 요인입니다"),
        ("쌍끌이 수급을 형성했습니다", "동반 순매수에 나섰습니다"),
        ("긍정적 인과관계가 형성됩니다", "긍정적 영향이 예상됩니다"),
    ]
    for old, new in awkward:
        text = text.replace(old, new)

    # 7. 한영 혼용 오타 수정 (Sonnet 한영 전환 버그)
    mixed_fixes = [
        ("아마zon", "아마존"), ("테슬la", "테슬라"), ("구글le", "구글"),
    ]
    for old, new in mixed_fixes:
        text = text.replace(old, new)

    return text.strip()
