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
    # 2026-05-28 추가 — 실제 5/28 시황 위반 사례 + v2 폐기한 14가지
    "확인하겠습니다", "살펴보겠습니다", "점검하겠습니다",
    "검토하겠습니다", "검토해보겠", "정리해보겠",
    "데이터로 살펴보면", "데이터를 보면", "데이터를 확인",
    "필요한 정보를 확인", "필요한 항목을 먼저",
    "주요 지표를 먼저", "주요 동인부터", "먼저 미국", "먼저 전일",
    "여기서 주목할 점", "주목할 부분은",
]


# 본문에서 어색한 채움말·강조 멘트 자연 치환 (룰 다이어트 — postprocess로 이동)
_AWKWARD_PHRASES = [
    ("주목됩니다", ""),
    ("주목할 만합니다", ""),
    ("참고점이 될 수 있습니다", ""),
    ("참고할 만합니다", ""),
    ("눈여겨볼 만합니다", ""),
    ("기억할 만합니다", ""),
    # 환율 "상대적" 표현 (5/28 commit으로 절대 금지된 표현)
    ("상대적 강세", "강세"),
    ("상대적 약세", "약세"),
    ("상대적으로 강세", "강세"),
    ("상대적으로 약세", "약세"),
    # 뉴스 인용 투
    ("검색 결과에 따르면 ", ""),
    ("검색해보니 ", ""),
    ("조사에 따르면 ", ""),
    ("웹에서 확인한 바 ", ""),
    ("확인한 결과 ", ""),
]


# 작업 멘트 종결형 — 미래형 + 과거형 + 검증/방침형 (5/28·6/1 시황 누락 fix)
_META_ENDINGS = [
    # 미래형 (작성 의도 표명)
    "확인하겠습니다", "살펴보겠습니다", "점검하겠습니다",
    "검토하겠습니다", "정리해보겠습니다", "정리합니다",
    "확인해보겠습니다", "살펴봅니다", "보겠습니다",
    "작성하겠습니다", "작성합니다",
    "쓰겠습니다", "전달드리겠습니다",
    # 과거형 (작성 직전 확인 멘트)
    "확인했습니다", "확인하였습니다", "살펴봤습니다", "살펴보았습니다",
    "정리했습니다", "정리하였습니다", "점검했습니다", "검토했습니다",
    "파악했습니다", "확보했습니다",
    # 6/1 추가 — 데이터 검증·방침 표명형 (현재 수동형 + 작업 의지)
    "확인됩니다", "확인된다", "확인됐습니다", "확인되었습니다",
    "언급만 하겠습니다", "언급하겠습니다", "수준 언급만",
    "단정 없이", "단정하지 않겠습니다",
    "처리합니다", "처리하겠습니다", "동일하게 처리",
]
# 작업 멘트 도입부
_META_STARTS = [
    "먼저 ", "우선 ", "데이터로 살펴보면", "데이터를 보면",
    "주요 지표를", "주요 동인부터", "주요 촉매를",
    "필요한 정보를", "필요한 항목을",
    "핵심 촉매를", "핵심 동인을", "핵심 이벤트를",
    "오늘 시장의 핵심", "오늘의 핵심",
    # 6/1 추가 — 데이터 출처·검증 사고 도입부
    "데이터 카드의", "데이터 카드는", "데이터카드",
    "제공된 데이터", "시스템 데이터",
]


def _strip_meta_before_divider(text):
    """본문 앞부분의 구분선(---/━━━/═══) 앞을 메타 사고로 보고 통째 제거.

    가장 강력한 백스톱 (6/1 시황 대응):
    LLM이 작업 메모·데이터 검증 사고(메타)와 실제 시황 본문을 '---'로 나누는 습관이 있음.
    우리 프롬프트는 서식 기호(볼드·리스트·구분선) 전면 금지 → 정상 본문 앞부분에 '---'가
    나올 일이 없음. 따라서 본문 앞쪽(첫 900자)에 등장하는 구분선은 거의 100% 메타 구분선.
    그 앞을 통째로 잘라낸다. 패턴 매칭(_is_meta_sentence)이 못 잡는 새 변형도 한 번에 해결.

    예) "5/29 마감 기준 ... 확인됩니다.\n\n데이터 카드의 2Y는 ... 하겠습니다.\n\n---\n\nKOSPI가 ..."
        → "KOSPI가 ..." 만 남김
    """
    if not text:
        return text
    # 본문 앞쪽 900자 안에서 첫 구분선 탐색
    m = re.search(r'(?:^|\n)[ \t]*[-—–━═]{3,}[ \t]*(?:\n|$)', text[:900])
    if m:
        rest = text[m.end():].lstrip()
        # 구분선 뒤에 실제 본문이 충분히 남을 때만 적용 (안전장치)
        if len(rest) >= 80:
            return rest
    return text


def _is_meta_sentence(sentence):
    """한 문장이 작업 메타 텍스트인지 판별."""
    s = sentence.strip()
    if not s:
        return False
    # 짧고 명백한 작업 멘트
    if s in ("시황 작성합니다.", "시황 작성합니다", "시황을 작성합니다.", "시황을 작성합니다"):
        return True
    # 어미·문장 안 등장 패턴
    if any(e in s for e in _META_ENDINGS):
        return True
    if any(s.startswith(p) for p in _META_STARTS):
        return True
    return False


def _strip_first_sentence_if_meta(text):
    """본문 앞부분의 작업 메타 문장·구분선을 연속 제거.

    5/28 이브닝 시황 사례:
        "이란 혁명수비대의 미군 기지 공격, 한은 금통위, ... 핵심 촉매를 확인했습니다.

        시황 작성합니다.

        ---

        코스피(8,185.29, ...)"
    → 본문 시작까지 메타 문장·구분선이 연속될 수 있음. 한 문장만 자르면 못 잡음.
    실제 시장 데이터 문장 만날 때까지 메타 문장·빈 줄·구분선을 잘라낸다.
    """
    if not text:
        return text

    lines = text.split("\n")
    head_strip_idx = 0
    consumed_any = False

    # 문장 단위로 잘라보며 메타 여부 검사 (한 줄에 여러 문장 있을 수 있어 문장 split도 함께)
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        # 빈 줄·구분선은 건너뜀 (앞부분에 있을 때만)
        if ln == "" or re.match(r"^[-━═─=]{3,}\s*$", ln):
            head_strip_idx = i + 1
            i += 1
            continue
        # 줄 안의 첫 문장이 메타면 라인 통째 제거
        # 라인에 여러 문장 있을 수 있어 첫 마침표 기준 split
        sentences = re.split(r"(?<=[.!?])\s+", ln, maxsplit=1)
        first = sentences[0]
        if _is_meta_sentence(first):
            # 첫 문장이 메타 — 그 문장만 제거하고 나머지는 보존
            rest = sentences[1] if len(sentences) > 1 else ""
            if rest.strip():
                # 나머지 문장이 있으면 그것부터 시작 (메타만 잘라냄)
                lines[i] = rest
                head_strip_idx = i
                consumed_any = True
                break
            else:
                # 라인 전체가 메타 — 통째 제거
                head_strip_idx = i + 1
                consumed_any = True
                i += 1
                continue
        # 메타 아님 — 멈춤
        break

    if not consumed_any and head_strip_idx == 0:
        return text

    return "\n".join(lines[head_strip_idx:]).lstrip()


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
    """시황 텍스트를 후처리해서 가독성 개선.

    역할 (룰 다이어트 — 2026-05-28):
    - 프롬프트에 박혀있던 표현 룰을 여기로 이동. LLM은 본문 사고에 집중하고,
      형식·금지어·메타 텍스트 같은 기계적 룰은 후처리가 잡음.
    """
    if not text:
        return text

    # 0a. Extended thinking 블록이 본문에 누설된 경우 제거 (드물지만 안전 가드)
    # Anthropic API의 thinking은 별도 content 블록이라 type 분리로 이미 필터되지만,
    # 모델이 본문 안에 <thinking>...</thinking> 형태로 새 쓸 경우만 대비.
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # 0b. 앞부분 구분선(---) 앞 메타 통째 제거 (가장 강력 — 6/1 시황 사례 fix)
    #     패턴 매칭이 못 잡는 새 메타 변형도 구분선 앞이면 한 번에 제거
    text = _strip_meta_before_divider(text)
    # 0c. 첫 문장이 작업 도입부면 통째 제거 (구분선 없는 케이스 — 5/28 사례)
    text = _strip_first_sentence_if_meta(text)
    # 0d. 첫 이모지 소제목 전 메타 prefix 라인 제거 (기존 로직)
    text = _strip_meta_preface(text)

    # 1. 화살표(→) 제거 — 자연어로 변환 (하이픈 보존)
    text = text.replace(" → ", ", ")
    text = text.replace("→ ", ", ")
    text = text.replace(" →", ",")

    # 1-1. 하이픈 누락 복원 (미-이란, 미-중 등)
    text = text.replace("미이란", "미-이란")
    text = text.replace("미중", "미-중")

    # 2. 어색한 채움말 + 금지 표현 자동 치환 (prompts_v2 룰 다이어트)
    for old, new in _AWKWARD_PHRASES:
        text = text.replace(old, new)

    # 3. 전환어 앞에 빈 줄
    transition_words = [
        "다만 ", "다만,", "반면 ", "반면,",
        "한편 ", "한편,", "한편으로",
    ]
    for word in transition_words:
        text = text.replace(f". {word}", f".\n\n{word}")
        text = text.replace(f".\n{word}", f".\n\n{word}")

    # 4. 주제 전환 앞에 빈 줄
    topic_changes = [
        "오늘 한국 증시", "오늘 국내 증시",
        "수급 측면", "수급에서", "수급 면에서",
        "원달러 환율", "원/달러",
    ]
    for phrase in topic_changes:
        text = text.replace(f". {phrase}", f".\n\n{phrase}")
        text = text.replace(f".\n{phrase}", f".\n\n{phrase}")

    # 5. 국면 정의 첫 문장 뒤 빈 줄
    # "~습니다." "~입니다." 등 한국어 서술형 마침표 뒤에서만 줄바꿈
    # 숫자 뒤 마침표(0.08%)나 영문 약어(S&P) 등에서 잘리지 않도록
    match = re.search(r'[가-힣]\.\s', text[:200])
    if match:
        pos = match.start() + 1  # 마침표 위치
        after = text[pos + 1:pos + 3]
        if after and not after.startswith("\n\n"):
            text = text[:pos + 1] + "\n\n" + text[pos + 1:].lstrip("\n ")

    # 6. 중복 빈 줄 정리 (3줄 이상 → 2줄로) + 치환 후 발생한 이중 공백
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    # 치환 결과 ". ." 같은 공허한 마침표 정리
    text = re.sub(r'\.\s+\.', '.', text)
    # 어색한 치환 잔여물 — "단어 ." → "단어." (공백+마침표 결합)
    text = re.sub(r'\s+\.', '.', text)
    text = re.sub(r'\s+,', ',', text)
    # 치환 결과 어미 비어 끝나는 라인 — "강세로 마감해." 같은 자연스러운 마무리 보장
    # "단어해."·"단어어." 같은 어색한 한 글자 어미는 LLM이 잘 안 쓰므로 별도 처리 X

    # 7. 어색한 관용 표현 치환
    awkward = [
        ("반가운 신호입니다", "긍정적 요인입니다"),
        ("쌍끌이 수급을 형성했습니다", "동반 순매수에 나섰습니다"),
        ("긍정적 인과관계가 형성됩니다", "긍정적 영향이 예상됩니다"),
    ]
    for old, new in awkward:
        text = text.replace(old, new)

    # 8. 한영 혼용 오타 수정 (Sonnet 한영 전환 버그)
    mixed_fixes = [
        ("아마zon", "아마존"), ("테슬la", "테슬라"), ("구글le", "구글"),
    ]
    for old, new in mixed_fixes:
        text = text.replace(old, new)

    return text.strip()
