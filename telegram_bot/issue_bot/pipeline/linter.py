"""R1~R8 자동 린트 — 생성된 본문이 스타일 규칙을 위반하는지 검증

위반 발견 시:
1. 1차 재생성 시도 (generator.py가 위반 항목을 프롬프트에 추가)
2. 재생성 후에도 위반 남으면 승인 카드에 ⚠️ 경고 표시

반환: [{"rule": "R1", "detail": "헤더 누락"}, ...]
"""
import re


# === 정규식 패턴 ===

RE_FORBIDDEN_EMOJI_TITLE = re.compile(r"[🔥📈💹🚀💥⚡💰💸🎉✨⭐🌟]")
# * 는 메리츠 샘플상 section marker(* 과거 12개월..., * 1Q26 컨센...) 및 면책에만 사용되므로 금지 대상 아님.
# 실제 금지: •, ·
RE_FORBIDDEN_BULLET = re.compile(r"^[•·]\s", re.MULTILINE)
RE_NUMBERED_LIST = re.compile(r"^\d+\.\s", re.MULTILINE)
RE_VAGUE_NUMBER = re.compile(r"(?:약|대략|거의)\s*\d+")
RE_FIRST_PERSON = re.compile(r"당사는|저희는|우리는|당사에|저희가")
RE_CERTAINTY = re.compile(r"확실히|분명히|반드시|틀림없이")
RE_SPECULATION = re.compile(r"~한다는\s*얘기|~로\s*알려진|것으로\s*보여")
RE_R8_EXTREME = re.compile(r"급등|폭등|수직상승|급락|폭락")
RE_R8_RECOMMEND = re.compile(r"매수\s*추천|매도\s*권고|투자\s*의견")
RE_R8_GOODBAD = re.compile(r"호재|악재")
RE_R8_CROWD = re.compile(r"시장은\s[^.]*?\s?본")


def lint_r1_r8(text: str, template: str) -> list:
    """
    본문 text가 Template(A/B/C/D/E)의 R1~R8 규칙을 위반하는지 검사.

    Returns:
        list of dict: [{"rule": "R1", "detail": "..."}]. 빈 리스트면 통과.
    """
    violations = []

    if not text or not text.strip():
        return [{"rule": "GENERAL", "detail": "본문이 비어있음"}]

    lines = text.split("\n")
    first_line = lines[0].strip() if lines else ""

    # R1. 헤더
    if template in ("A", "C", "D"):
        if not first_line.startswith("[NODE Research "):
            violations.append({
                "rule": "R1",
                "detail": f"Template {template}은 헤더 '[NODE Research {{섹터}}]'로 시작해야 함. 현재: {first_line[:40]}"
            })
    elif template == "B":
        if not first_line.startswith("["):
            violations.append({
                "rule": "R1",
                "detail": f"Template B는 '[...]' 대괄호 헤더로 시작해야 함. 현재: {first_line[:40]}"
            })
    # E는 헤더 자유

    # R2. 제목 이모지
    title_zone = "\n".join(lines[:3])
    if RE_FORBIDDEN_EMOJI_TITLE.search(title_zone):
        violations.append({"rule": "R2", "detail": "제목부에 금지 이모지 사용"})

    # R3. bullet 기호 (•, ·만 금지. *는 메리츠 샘플상 section marker/disclaimer 용도로 허용)
    if RE_FORBIDDEN_BULLET.search(text):
        violations.append({"rule": "R3", "detail": "금지 bullet 기호(• 또는 ·) 사용"})
    if RE_NUMBERED_LIST.search(text):
        violations.append({"rule": "R3", "detail": "번호 매김 리스트 사용 (1. 2. 3.)"})

    # R4. 모호 수치
    if RE_VAGUE_NUMBER.search(text):
        m = RE_VAGUE_NUMBER.search(text)
        violations.append({"rule": "R4", "detail": f"모호 수치 표현: '{m.group(0)}'"})

    # R5. 1인칭 / 확정 표현
    if RE_FIRST_PERSON.search(text):
        m = RE_FIRST_PERSON.search(text)
        violations.append({"rule": "R5", "detail": f"1인칭 사용: '{m.group(0)}'"})
    if RE_CERTAINTY.search(text):
        m = RE_CERTAINTY.search(text)
        violations.append({"rule": "R5", "detail": f"확정 표현: '{m.group(0)}'"})

    # R6. 추정 인용
    if RE_SPECULATION.search(text):
        m = RE_SPECULATION.search(text)
        violations.append({"rule": "R6", "detail": f"추정 인용: '{m.group(0)}'"})

    # R8. 금지 표현
    for pattern, name in [
        (RE_R8_EXTREME, "급등/폭등/급락 등 극단 표현"),
        (RE_R8_RECOMMEND, "매수추천/매도권고/투자의견"),
        (RE_R8_GOODBAD, "호재/악재"),
        (RE_R8_CROWD, "시장은 ~라고 본다 (근거 없는 집단추정)"),
    ]:
        m = pattern.search(text)
        if m:
            violations.append({"rule": "R8", "detail": f"{name}: '{m.group(0)}'"})

    # R7. 면책 문구 (A/B/C/D 필수, E 면제)
    if template in ("A", "C", "D"):
        if "본 내용은 당사의 코멘트 없이" not in text:
            violations.append({
                "rule": "R7",
                "detail": f"Template {template}은 면책 문구 필수"
            })

    # 부가 검증: 금액 단위
    # 숫자 뒤에 단위(조/억/만/백만/천/$, %, 달러 등) 없는 순수 큰 숫자 탐지
    # 과민 탐지 위험 있어 경고만 표시 (R4_MINOR)
    bare_number_pattern = re.compile(r"(?<![.\d,%])(\d{4,})(?!\s*[조억만달원%.원])")
    # 너무 공격적이라 일단 비활성. 필요 시 활성화.

    return violations


def lint_summary(violations: list) -> str:
    """위반 결과를 사람이 읽기 좋은 요약으로"""
    if not violations:
        return "통과 (R1~R8 위반 없음)"
    grouped = {}
    for v in violations:
        grouped.setdefault(v["rule"], []).append(v["detail"])
    lines = []
    for rule, details in sorted(grouped.items()):
        lines.append(f"  {rule}: {', '.join(details[:2])}")
        if len(details) > 2:
            lines[-1] += f" (외 {len(details) - 2}건)"
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # 빠른 자체 테스트
    good = """[NODE Research 반도체]

▶ 3월 대만 TSMC 매출액 415,191백만대만달러(+30.7% MoM, +45.2% YoY) 발표

- 1Q26 매출액 1,134,103.1백만대만달러(+8.4% QoQ, +35.1% YoY) 기록

- 1Q26 매출액 컨센서스 대비 1.1% 상회

(자료: TSMC ir)

* 본 내용은 당사의 코멘트 없이 국내외 언론사 뉴스 및 전자공시자료 등을 인용한 것으로 별도의 승인 절차 없이 제공합니다."""

    bad = """[잘못된 헤더]

🔥 TSMC 매출액 대략 4천억 폭등!!

• 매수 추천
1. 당사는 호재로 판단

분명히 급등 예상"""

    print("== Good 샘플 ==")
    print(lint_summary(lint_r1_r8(good, "A")))
    print()
    print("== Bad 샘플 ==")
    print(lint_summary(lint_r1_r8(bad, "A")))
