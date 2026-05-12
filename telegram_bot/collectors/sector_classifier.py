"""신고가 종목 → 섹터 분류 — 단일 데이터 소스 역색인.

명세서 (2026-05-12 코드방):
- 매핑 사전 폐기. WICS fetch 폐기. Claude fallback 폐기. 종목명 fallback 폐기.
- 단일 소스: sector_universe_YYYYMMDD.json (KRX 지수 + ETF 구성종목)
- 종목코드가 어떤 섹터들에 속하는지 역색인 lookup
- 한 종목이 여러 섹터에 속하면 모두 표시 (중복 허용)
- 어느 섹터에도 없으면 "기타"

운영 원칙:
1. 종목코드 → 섹터 룩업 테이블을 새로 만들지 않는다.
2. 분류 정확도 떨어지면 sector_config.json 섹터 추가/제거로만 조정.
3. Claude API는 이 분류 로직에서 호출하지 않는다.
4. "기타"가 많아 보여도 그대로 둔다.
"""
import json
import os
from collections import defaultdict
from typing import Optional


_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "history",
)


def _load_today_universe() -> Optional[dict]:
    """오늘 universe 로드. 없으면 가장 최근 fallback."""
    from telegram_bot.collectors.sector_universe_fetcher import load_universe
    return load_universe()


def classify_stocks_batch(stocks: list) -> dict:
    """신고가 종목들을 섹터별로 그룹핑.

    Args:
        stocks: [{"종목코드", "종목명", "현재가", "등락률", ...}, ...]

    Returns:
        {
          "반도체": [stock, stock, ...],
          "밸류업": [...],
          ...
          "기타": [매칭 실패 종목들]
        }
        중복 허용 — 한 종목이 여러 섹터에 속하면 각 섹터에 모두 등장.
    """
    universe = _load_today_universe()
    if not universe or not universe.get("sectors"):
        print("[CLASSIFIER] sector_universe 로드 실패 — 모두 '기타'로 처리")
        return {"기타": list(stocks)}

    sectors = universe.get("sectors", {})
    result = defaultdict(list)

    for stock in stocks:
        code = stock.get("종목코드") or stock.get("code", "")
        if not code:
            result["기타"].append(stock)
            continue

        matched = [
            name for name, codes in sectors.items()
            if code in codes
        ]
        if matched:
            for name in matched:
                result[name].append(stock)
        else:
            result["기타"].append(stock)

    return dict(result)


def get_sector_priority() -> list:
    """sector_config.json 등록 순서로 섹터 우선순위 반환. '기타'는 마지막."""
    config_path = os.path.join(_HISTORY_DIR, "sector_config.json")
    if not os.path.exists(config_path):
        return ["기타"]
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        order = [s["name"] for s in data.get("sectors", []) if s.get("name")]
        order.append("기타")
        return order
    except Exception:
        return ["기타"]


# ─── 호환: domestic_market._classify_stocks가 호출하던 시그니처 ───
def _classify_stocks_legacy(filtered_stocks: list) -> dict:
    """기존 코드 호환: {종목코드: 섹터} 단일 매핑 반환.

    한 종목이 여러 섹터일 때는 첫 번째 매칭 섹터만 반환 (호환용).
    새 흐름은 classify_stocks_batch() 사용 권장 (중복 허용).
    """
    universe = _load_today_universe()
    if not universe:
        return {s.get("종목코드", ""): "기타" for s in filtered_stocks}
    sectors = universe.get("sectors", {})

    out = {}
    for s in filtered_stocks:
        code = s.get("종목코드", "")
        if not code:
            continue
        matched = next(
            (name for name, codes in sectors.items() if code in codes),
            "기타",
        )
        out[code] = matched
    return out


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트
    test = [
        {"종목코드": "005930", "종목명": "삼성전자"},
        {"종목코드": "000660", "종목명": "SK하이닉스"},
        {"종목코드": "005380", "종목명": "현대차"},
        {"종목코드": "999999", "종목명": "없는종목"},
    ]
    result = classify_stocks_batch(test)
    for sector, items in result.items():
        names = ", ".join(it.get("종목명", "") for it in items)
        print(f"  [{sector}] {len(items)}: {names}")
