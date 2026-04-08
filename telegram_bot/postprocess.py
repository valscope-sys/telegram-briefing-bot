"""시황 텍스트 후처리 — 줄바꿈 + 표현 정리"""
import re


def postprocess_commentary(text):
    """시황 텍스트를 후처리해서 가독성 개선"""
    if not text:
        return text

    # 1. 화살표(→) 제거 — 자연어로 변환
    text = text.replace(" → ", ", ")
    text = text.replace("→ ", ", ")
    text = text.replace(" →", ",")

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
    first_period = text.find(".")
    if first_period > 0 and first_period < 100:
        after = text[first_period + 1:first_period + 3]
        if after and not after.startswith("\n\n"):
            text = text[:first_period + 1] + "\n\n" + text[first_period + 1:].lstrip("\n ")

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

    return text.strip()
