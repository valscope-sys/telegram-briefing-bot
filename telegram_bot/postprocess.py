"""시황 텍스트 후처리 — 줄바꿈 + 표현 정리 + 중요 데이터 누락 방지"""
import re


def ensure_critical_data_mentioned(text, global_data):
    """후처리 백스톱 — KORU ≥5% 인데 시황에 완전 누락된 경우만 보완.

    설계 원칙 (2026-04-24 변경):
    - 1순위: 프롬프트에서 본문 1문단에 KORU 녹이도록 강제 (prompts_v2.py).
    - 2순위(여기): 모델이 완전 누락한 극소수 케이스에만 백스톱. 라벨 `(후주입)` 제거 — 본문 결론과 별개 꼬리로 오해되지 않도록 자연스러운 경고 문장으로.
    - |등락률| ≥ 5% (3x 레버리지 실제 예상 갭 1.67%+, 확실한 시그널).
    - 3~5% 구간은 모델 재량 (매일 반복되는 AI 템플릿 느낌 방지).
    """
    if not text or not global_data:
        return text

    korea_proxies = global_data.get("korea_proxies", {})
    koru = korea_proxies.get("KORU", {})
    if not koru or "error" in koru:
        return text

    koru_pct = koru.get("등락률", 0)
    if abs(koru_pct) < 5.0:
        return text

    # 이미 언급됐으면 그대로
    if "KORU" in text or "야간 프록시" in text:
        return text

    # 임플라이드 갭 (3x 레버리지)
    implied = koru_pct / 3.0
    direction = "급락" if koru_pct < 0 else "급등"
    # 라벨 제거 — 본문 톤에 녹이기 (백스톱이지만 덜 어색하게)
    risk_note = (
        f"\n\n※ 야간 KORU {koru_pct:+.2f}% {direction} — "
        f"3배 레버리지 특성상 실제 예상 갭 약 {implied:+.1f}% 수준이라 "
        f"한국 특유의 리스크(관세·환율·지정학) 반영 가능성을 염두에 두어야 합니다."
    )

    # 🇰🇷 한국 체크포인트 섹션 끝에 붙이기 (모닝 전용 구조)
    kr_marker = "🇰🇷 오늘 한국 증시 체크포인트"
    idx = text.find(kr_marker)
    if idx >= 0:
        return text.rstrip() + risk_note
    # 이브닝 구조거나 마커 없으면 그냥 끝에 추가
    return text.rstrip() + risk_note


_META_PREFIXES = [
    "I'll search", "Let me search", "Let me first", "I'll first",
    "I'll look up", "I need to search", "Let me check", "I'll check",
    "Before writing", "Let me start by", "First, let me", "I'll begin",
    "검색 결과를", "검색해보겠", "먼저 검색",
    # 2026-04-24 추가 — 한글 메타 텍스트 (팀장 리뷰 지적)
    "충분한 정보", "충분히 확인", "정보를 확보",
    "시황을 작성", "시황 작성합니다", "시황을 정리",
    "정보를 종합", "정보를 모두", "분석을 시작",
    "지금부터 작성", "이제 작성", "작성하겠습니다",
]


def _strip_meta_preface(text):
    """모델의 '사고 과정' 메타 텍스트 제거 (첫 소제목 전까지만)

    예: "I'll search for additional context..." / "충분한 정보를 확보했습니다."
    → 첫 이모지 소제목(🇺🇸·📈·🔍 등) 앞 영문/한글 메타 설명 줄 제거.
    선행 `---`, `━━━` 구분선도 제거.
    """
    if not text:
        return text
    # 첫 소제목(이모지 + 공백 + 한글) 위치 찾기
    m = re.search(r"^\s*(🇺🇸|🇰🇷|📈|🔍|🔄|💰|⚠️).*$", text, re.MULTILINE)
    if not m:
        return text
    head = text[:m.start()].strip()
    body = text[m.start():]
    # head 가 없으면 그대로
    if not head:
        return body.lstrip()
    head_lines = [ln for ln in head.split("\n") if ln.strip()]
    kept = []
    for ln in head_lines:
        stripped = ln.strip()
        # 구분선(---, ━━━, ===) 제거
        if re.match(r"^[-━═]{3,}\s*$", stripped):
            continue
        # 메타 prefix 포함 라인 제거
        if any(p.lower() in stripped.lower() for p in _META_PREFIXES):
            continue
        # 영문 전용 라인 제거 (한글 4자 이상 없으면 메타로 간주)
        if not re.search(r"[가-힣]{4,}", stripped):
            continue
        kept.append(ln)
    if kept:
        return ("\n".join(kept) + "\n\n" + body).lstrip()
    return body.lstrip()


def postprocess_commentary(text):
    """시황 텍스트를 후처리해서 가독성 개선"""
    if not text:
        return text

    # 0. 메타 텍스트 제거 (모델이 생각 과정 노출한 경우)
    text = _strip_meta_preface(text)

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
