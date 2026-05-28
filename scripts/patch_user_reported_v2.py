"""사용자가 5/12 보고한 잘못 분류된 종목 정정.

원본 카드:
✅ 반도체 (4): 라온텍·기가비스·한솔테크닉스·브이엠
✅ 전력/원전 (6): 가온전선·선도전기·RFHIC·SK텔레콤·대한광통신·한울반도체  ← 통신 4개 잘못
✅ 자동차 (1): LG전자
✅ 바이오 (2): 코오롱티슈진·휴온스
✅ 금융/지주/소비재 (5): 에스비비테크·크레오에스지·핑거·케이바이오랩스·솔트웨어  ← 4개 잘못
✅ 기타 (3): PS일렉트로닉스·경인전자·원풍물산  ← 3개 모두 매핑 필요
"""
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "telegram_bot", "history", "stock_sector_mapping.json",
)

with open(PATH, "r", encoding="utf-8") as f:
    d = json.load(f)

# 종목코드 + 한국 투자 테마 정확 매핑
PATCHES = {
    # ── 반도체 (라온텍은 마이크로디스플레이, OLED 그룹) ──
    "327260": {"name": "라온텍", "sector": "디스플레이"},
    "420770": {"name": "기가비스", "sector": "반도체장비"},
    "338100": {"name": "브이엠", "sector": "반도체장비"},

    # ── 통신/5G (전력 아님!) ──
    "017670": {"name": "SK텔레콤", "sector": "통신/5G"},
    "030200": {"name": "KT", "sector": "통신/5G"},
    "032640": {"name": "LG유플러스", "sector": "통신/5G"},
    "218410": {"name": "RFHIC", "sector": "통신장비"},
    "010170": {"name": "대한광통신", "sector": "통신장비"},
    "078890": {"name": "가온그룹", "sector": "통신장비"},
    "115440": {"name": "우리넷", "sector": "통신장비"},
    "036630": {"name": "세종텔레콤", "sector": "통신/5G"},

    # ── 전력/원전 (정확) ──
    "007610": {"name": "선도전기", "sector": "원전/전력"},
    "043260": {"name": "성광벤드", "sector": "원전/전력"},
    "095190": {"name": "이엠코리아", "sector": "원전/전력"},
    "238090": {"name": "PS일렉트로닉스", "sector": "원전/전력"},

    # ── 자동차 — LG전자는 가전·B2B (전기차 부품 일부)
    "066570": {"name": "LG전자", "sector": "자동차부품"},

    # ── 바이오/제약 ──
    "950160": {"name": "코오롱티슈진", "sector": "바이오/제약"},
    "243070": {"name": "휴온스", "sector": "바이오/제약"},
    "203400": {"name": "케이바이오랩스", "sector": "바이오/제약"},
    "120240": {"name": "크레오에스지", "sector": "바이오/제약"},

    # ── 방산/기계 (베어링·로봇·항공 부품) ──
    "389500": {"name": "에스비비테크", "sector": "방산"},

    # ── AI/소프트웨어 ──
    "163730": {"name": "핑거", "sector": "AI/소프트웨어"},
    "108860": {"name": "셀바스AI", "sector": "AI/소프트웨어"},
    "032280": {"name": "솔트웨어", "sector": "AI/소프트웨어"},

    # ── 전기전자 ──
    "009160": {"name": "경인전자", "sector": "전기전자"},

    # ── 섬유/패션 ──
    "008290": {"name": "원풍물산", "sector": "섬유/패션"},

    # ── 한울반도체 (지속 등장하는 매핑 미상) ──
    "215360": {"name": "한울반도체", "sector": "반도체"},

    # ── 추가 자주 등장 종목 (5/4~5/6 사용자 보고 등) ──
    "049950": {"name": "미래컴퍼니", "sector": "반도체장비"},
    "036930": {"name": "주성엔지니어링", "sector": "반도체장비"},
    "036010": {"name": "아비코전자", "sector": "전기전자"},
    "036090": {"name": "심텍", "sector": "반도체부품"},
    "353200": {"name": "대덕전자", "sector": "반도체부품"},
    "002240": {"name": "고려제강", "sector": "철강/소재"},
    "003620": {"name": "쌍용차", "sector": "자동차"},
    "047050": {"name": "포스코인터내셔널", "sector": "지주"},
    "138930": {"name": "BNK금융지주", "sector": "금융"},

    # ── 자주 보이는 신고가 — 사용자 보고 누락 ──
    "067160": {"name": "아프리카TV", "sector": "미디어/엔터"},
    "112040": {"name": "위메이드", "sector": "게임"},
    "036570": {"name": "엔씨소프트", "sector": "게임"},
    "035900": {"name": "JYP Ent.", "sector": "미디어/엔터"},
    "041510": {"name": "에스엠", "sector": "미디어/엔터"},
    "035250": {"name": "강원랜드", "sector": "유통/소비재"},
    "008770": {"name": "호텔신라", "sector": "유통/소비재"},
    "005850": {"name": "에스엘", "sector": "자동차부품"},
    "003670": {"name": "포스코퓨처엠", "sector": "2차전지소재"},
    "020150": {"name": "롯데에너지머티리얼즈", "sector": "2차전지소재"},
    "086520": {"name": "에코프로", "sector": "지주"},
}

before = len([k for k in d if not k.startswith("_")])
d.update(PATCHES)
after = len([k for k in d if not k.startswith("_")])

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"매핑: {before} → {after} (+{after - before}, 패치 입력 {len(PATCHES)})")
