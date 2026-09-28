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


def _warn_if_universe_unhealthy(universe: dict, max_age_days: int = 7) -> None:
    """universe 가 비었거나 오래됐으면 ERROR 로그.

    2026-05 ~ 09 동안 KRX 로그인 필수화로 전 섹터 0건 universe 가 쓰이며 모든 신고가가
    '기타'로만 분류됐는데 아무 로그도 없어 넉 달간 발견되지 않았음 → 조용한 실패 방지.
    """
    sectors = universe.get("sectors", {}) or {}
    filled = sum(1 for v in sectors.values() if v)
    trd_dd = str(universe.get("trd_dd", ""))
    if sectors and filled == 0:
        print(f"[CLASSIFIER] ERROR: sector_universe(trd_dd={trd_dd}) 전 {len(sectors)}개 섹터 0건 "
              f"— 모든 종목 '기타' 처리됨 (sector_universe_fetcher 확인)")
    elif sectors and filled < len(sectors) * 0.5:
        print(f"[CLASSIFIER] ERROR: sector_universe(trd_dd={trd_dd}) {filled}/{len(sectors)}개 섹터만 데이터 있음")
    try:
        import datetime
        age = (datetime.date.today() - datetime.datetime.strptime(trd_dd, "%Y%m%d").date()).days
        if age > max_age_days:
            print(f"[CLASSIFIER] ERROR: sector_universe 가 {age}일 전(trd_dd={trd_dd}) 데이터 — 06:00 갱신 잡 확인")
    except ValueError:
        print(f"[CLASSIFIER] ERROR: sector_universe trd_dd 형식 이상: {trd_dd!r}")


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
        print("[CLASSIFIER] ERROR: sector_universe 로드 실패 — 모두 '기타'로 처리")
        return {"기타": list(stocks)}

    sectors = universe.get("sectors", {})
    _warn_if_universe_unhealthy(universe)
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
        print(f"[CLASSIFIER] ERROR: sector_config.json 없음 ({config_path}) — 섹터 순서 없이 진행")
        return ["기타"]
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        order = [s["name"] for s in data.get("sectors", []) if s.get("name")]
        order.append("기타")
        return order
    except Exception as e:
        print(f"[CLASSIFIER] ERROR: sector_config.json 로드 실패: {e}")
        return ["기타"]


# ─── 호환: domestic_market._classify_stocks가 호출하던 시그니처 ───
def _classify_stocks_legacy(filtered_stocks: list) -> dict:
    """기존 코드 호환: {종목코드: 섹터} 단일 매핑 반환.

    한 종목이 여러 섹터일 때는 첫 번째 매칭 섹터만 반환 (호환용).
    새 흐름은 classify_stocks_batch() 사용 권장 (중복 허용).
    """
    universe = _load_today_universe()
    if not universe:
        print("[CLASSIFIER] ERROR: sector_universe 로드 실패 — 모두 '기타'로 처리")
        return {s.get("종목코드", ""): "기타" for s in filtered_stocks}
    sectors = universe.get("sectors", {})
    _warn_if_universe_unhealthy(universe)

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
