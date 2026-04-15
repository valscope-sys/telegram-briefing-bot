"""이번 주 일정 수동 추가"""
import json
import shutil
from pathlib import Path

CAL = Path(__file__).parent / "calendar.json"
DOCS = Path(__file__).parent.parent / "docs" / "calendar.json"

new_events = [
    # === 4/14 (월) ===
    {"date": "2026-04-14", "time": "", "category": "경제지표", "title": "일본 산업생산", "source": "manual", "auto": False, "country": "\U0001f1ef\U0001f1f5"},
    {"date": "2026-04-14", "time": "", "category": "경제지표", "title": "중국 수출입통계", "source": "manual", "auto": False, "country": "\U0001f1e8\U0001f1f3"},
    {"date": "2026-04-14", "time": "21:30", "category": "경제지표", "title": "미국 생산자물가지수(PPI)", "source": "manual", "auto": False, "country": "\U0001f1fa\U0001f1f8"},
    {"date": "2026-04-14", "time": "", "category": "산업컨퍼런스", "title": "IMF 경제전망보고서 발표", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "에너지", "title": "IEA 원유시장 보고서", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "미국실적", "title": "JP모건(JPM) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "미국실적", "title": "J&J(JNJ) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "미국실적", "title": "웰스파고(WFC) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "미국실적", "title": "씨티그룹(C) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-14", "time": "", "category": "미국실적", "title": "블랙록(BLK) 실적발표 (장전)", "source": "manual", "auto": False},
    # === 4/15 (화) ===
    {"date": "2026-04-15", "time": "", "category": "정치/외교", "title": "한국 디지털자산기본법 논의", "source": "manual", "auto": False, "country": "\U0001f1f0\U0001f1f7"},
    {"date": "2026-04-15", "time": "", "category": "경제지표", "title": "한국 수입물가지수", "source": "manual", "auto": False, "country": "\U0001f1f0\U0001f1f7"},
    {"date": "2026-04-15", "time": "", "category": "경제지표", "title": "유로존 산업생산", "source": "manual", "auto": False, "country": "\U0001f1ea\U0001f1fa"},
    {"date": "2026-04-15", "time": "", "category": "경제지표", "title": "미국 뉴욕연은지수, 수출입물가지수", "source": "manual", "auto": False, "country": "\U0001f1fa\U0001f1f8"},
    {"date": "2026-04-15", "time": "", "category": "통화정책", "title": "연준 베이지북 공개", "source": "manual", "auto": False, "country": "\U0001f1fa\U0001f1f8"},
    {"date": "2026-04-15", "time": "", "category": "미국실적", "title": "ASML(ASML) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-15", "time": "", "category": "미국실적", "title": "BOA(BAC) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-15", "time": "", "category": "미국실적", "title": "모건스탠리(MS) 실적발표 (장전)", "source": "manual", "auto": False},
    # === 4/16 (수) ===
    {"date": "2026-04-16", "time": "", "category": "경제지표", "title": "중국 GDP성장률, 산업생산, 소매판매", "source": "manual", "auto": False, "country": "\U0001f1e8\U0001f1f3"},
    {"date": "2026-04-16", "time": "", "category": "통화정책", "title": "케빈워시 청문회 (예정)", "source": "manual", "auto": False, "country": "\U0001f1fa\U0001f1f8"},
    {"date": "2026-04-16", "time": "", "category": "경제지표", "title": "미국 필라델피아 연은지수, 산업생산", "source": "manual", "auto": False, "country": "\U0001f1fa\U0001f1f8"},
    {"date": "2026-04-16", "time": "", "category": "미국실적", "title": "TSMC(TSM) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-16", "time": "", "category": "미국실적", "title": "넷플릭스(NFLX) 실적발표 (장후)", "source": "manual", "auto": False},
    {"date": "2026-04-16", "time": "", "category": "미국실적", "title": "펩시코(PEP) 실적발표 (장전)", "source": "manual", "auto": False},
    {"date": "2026-04-16", "time": "", "category": "미국실적", "title": "에보트(ABT) 실적발표 (장전)", "source": "manual", "auto": False},
    # === 4/17 (목) ===
    {"date": "2026-04-17", "time": "", "category": "제약/바이오", "title": "AACR (미국 암학회) 개최", "source": "manual", "auto": False},
    # === 4월 개별 ===
    {"date": "2026-04-20", "time": "", "category": "반도체", "title": "샌디스크(SNDK) 나스닥100 신규편입", "source": "manual", "auto": False},
    {"date": "2026-04-21", "time": "", "category": "제약/바이오", "title": "ASCO 초록 제목 온라인 공개", "source": "manual", "auto": False},
    {"date": "2026-04-21", "time": "", "category": "산업컨퍼런스", "title": "스페이스X 애널리스트 데이", "source": "manual", "auto": False},
    {"date": "2026-04-22", "time": "", "category": "에너지", "title": "국제 그린에너지 엑스포", "source": "manual", "auto": False, "country": "\U0001f1f0\U0001f1f7"},
    {"date": "2026-04-23", "time": "", "category": "산업컨퍼런스", "title": "AI국제학술대회(ICLR 2026)", "source": "manual", "auto": False},
    {"date": "2026-04-24", "time": "", "category": "정치/외교", "title": "기업지배구조보고서 가이드라인", "source": "manual", "auto": False, "country": "\U0001f1f0\U0001f1f7"},
    # === 5월 ===
    {"date": "2026-05-21", "time": "", "category": "제약/바이오", "title": "ASCO 일반 초록 전문 공개", "source": "manual", "auto": False},
    # === 하반기 (undated) ===
    {"date": "2026-07-01", "endDate": "2026-09-30", "time": "", "category": "반도체", "title": "엔비디아 베라 Rubin 출시 (예상)", "source": "manual", "auto": False, "undated": True, "unconfirmed": True},
]

data = json.loads(CAL.read_text(encoding="utf-8"))
existing_keys = {e["date"] + "|" + e["title"] for e in data}

added = 0
for ev in new_events:
    key = ev["date"] + "|" + ev["title"]
    if key not in existing_keys:
        data.append(ev)
        existing_keys.add(key)
        added += 1

data.sort(key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("category", "")))

CAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copy(str(CAL), str(DOCS))

print(f"{added}건 추가. 총 {len(data)}건")
