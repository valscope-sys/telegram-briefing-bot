"""KRX 전 상장사 이름·코드 덤프 → telegram_bot/history/krx_listing.json

FDR 없는 서버에서도 상장사 필터가 작동하도록.
주기적 재생성 권장 (상장·상폐 반영).
"""
import json
from pathlib import Path

import FinanceDataReader as fdr


def main():
    print("KRX 마스터 로드...")
    krx = fdr.StockListing("KRX")
    entries = []
    for _, row in krx.iterrows():
        code = str(row["Code"]).zfill(6)
        name = str(row["Name"]).strip()
        if not name:
            continue
        market = str(row.get("Market", "") or "")
        entries.append({"code": code, "name": name, "market": market})
    print(f"총 {len(entries)}종목")

    out = {
        "_meta": {
            "count": len(entries),
            "source": "FDR StockListing('KRX')",
        },
        "stocks": entries,
    }
    path = Path(__file__).parent.parent / "telegram_bot" / "history" / "krx_listing.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
