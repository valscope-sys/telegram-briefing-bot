"""신고가 종목 → 섹터 분류 — 하이브리드 (수동 매핑 + 네이버 WICS + Claude fallback)

기존 _classify_stocks의 매핑률 ~10% (273/2,800 종목) 문제 + 잘못된 매핑(가온전선=통신/5G,
하나마이크론=메모리 등) 해결.

흐름:
1. **stock_sector_mapping.json** (수동 큐레이션, 가장 정확)
2. **wics_cache.json** (네이버에서 fetch 후 캐시, 영구)
3. **fetch_naver_industry()** (캐시 미스 → 네이버 종목 페이지에서 WICS 추출)
4. **wics_to_sector.json** (WICS 한국 표준 분류 → 우리 카테고리)
5. **Claude fallback** (네이버 fetch 실패 시 종목명 추측)

캐시 정책:
- WICS는 산업분류 거의 안 바뀜 → 영구 캐시 (TTL 없음)
- 매일 새 종목만 fetch → 점진적 누적
"""
import datetime
import json
import os
import re
import threading
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup


_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "history",
)
_MAPPING_PATH = os.path.join(_HISTORY_DIR, "stock_sector_mapping.json")
_WICS_CACHE_PATH = os.path.join(_HISTORY_DIR, "wics_cache.json")
_WICS_MAP_PATH = os.path.join(_HISTORY_DIR, "wics_to_sector.json")

_lock = threading.Lock()

# 메모리 캐시 (모듈 수명)
_manual_mapping = None  # {code: {"name", "sector"}}
_wics_cache = None      # {code: {"name", "wics", "fetched_at"}}
_wics_to_sector = None  # {wics: sector}


def _load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[SECTOR] {path} 로드 실패: {e}")
        return {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_manual():
    global _manual_mapping
    if _manual_mapping is None:
        raw = _load_json(_MAPPING_PATH)
        _manual_mapping = {k: v for k, v in raw.items() if not k.startswith("_")}
    return _manual_mapping


def _load_wics_cache():
    global _wics_cache
    if _wics_cache is None:
        _wics_cache = _load_json(_WICS_CACHE_PATH)
    return _wics_cache


def _load_wics_map():
    global _wics_to_sector
    if _wics_to_sector is None:
        raw = _load_json(_WICS_MAP_PATH)
        _wics_to_sector = {k: v for k, v in raw.items() if not k.startswith("_")}
    return _wics_to_sector


def fetch_naver_industry(code: str, timeout: int = 8) -> Optional[str]:
    """네이버 증권 종목 페이지에서 WICS 산업분류 추출.

    페이지: https://finance.naver.com/item/main.naver?code=NNNNNN
    찾는 위치: a[href*="sise_group_detail"] (업종 링크)

    Returns:
        WICS 분류 문자열 (예: "반도체와반도체장비") 또는 None.
    """
    if not re.fullmatch(r"\d{6}", code or ""):
        return None
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        r.encoding = r.apparent_encoding or "euc-kr"
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup.select('a[href*="sise_group_detail"]'):
            wics = tag.get_text(strip=True)
            if wics:
                return wics
    except Exception as e:
        print(f"[SECTOR] 네이버 fetch 실패 ({code}): {e}")
    return None


def _normalize_wics(wics: str) -> str:
    """WICS 문자열 정규화 (공백 제거)."""
    return re.sub(r"\s+", "", (wics or "").strip())


def wics_to_our_sector(wics: str, name: str = "") -> str:
    """WICS 한국 표준 분류 → 우리 카테고리.

    매핑 안 되면 "기타".
    name은 예외 케이스 명시적 처리용 (예: 가온전선 = 건설로 표기되지만 전기전자).
    """
    if not wics:
        return "기타"
    mp = _load_wics_map()
    norm = _normalize_wics(wics)
    return mp.get(norm) or mp.get(wics) or "기타"


def classify_stock(code: str, name: str = "",
                   allow_fetch: bool = True,
                   allow_claude: bool = True) -> str:
    """단일 종목 → 섹터 분류 (캐시·WICS·Claude 순).

    Args:
        code: 6자리 종목코드
        name: 종목명 (Claude fallback 시 사용)
        allow_fetch: 네이버 fetch 허용 여부
        allow_claude: Claude fallback 허용 여부

    Returns:
        섹터 문자열 (예: "반도체", "2차전지", "기타")
    """
    if not code:
        return "기타"

    # 1차: 수동 매핑 (가장 신뢰)
    manual = _load_manual()
    if code in manual:
        sec = manual[code].get("sector")
        if sec:
            return sec

    # 2차: WICS 캐시
    cache = _load_wics_cache()
    if code in cache:
        wics = cache[code].get("wics", "")
        if wics:
            return wics_to_our_sector(wics, name)

    # 3차: 네이버 fetch (한 번만 — 캐시 저장)
    if allow_fetch:
        wics = fetch_naver_industry(code)
        if wics:
            with _lock:
                cache[code] = {
                    "name": name,
                    "wics": wics,
                    "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
                _save_json(_WICS_CACHE_PATH, cache)
            return wics_to_our_sector(wics, name)

    # 4차: Claude fallback (호출 측에서 별도 처리)
    return None if allow_claude else "기타"


def classify_stocks_batch(stocks: list,
                          allow_fetch: bool = True,
                          allow_claude: bool = True,
                          max_fetch_per_call: int = 30) -> dict:
    """여러 종목 일괄 분류.

    Args:
        stocks: [{"종목코드", "종목명"}, ...]
        max_fetch_per_call: 1회 호출당 최대 네이버 fetch 횟수 (rate limit)

    Returns:
        {code: sector} dict. None인 케이스는 호출 측에서 Claude fallback.
    """
    code_to_sector = {}
    fetch_count = 0
    pending_for_claude = []  # [(name, code), ...]

    manual = _load_manual()
    cache = _load_wics_cache()
    wics_map = _load_wics_map()

    for s in stocks:
        code = s.get("종목코드", "")
        name = s.get("종목명", "")
        if not code:
            code_to_sector[code] = "기타"
            continue

        # 1차: 수동 매핑
        if code in manual:
            code_to_sector[code] = manual[code].get("sector", "기타")
            continue

        # 2차: WICS 캐시
        if code in cache:
            wics = cache[code].get("wics", "")
            if wics:
                code_to_sector[code] = wics_map.get(_normalize_wics(wics), "기타")
                continue

        # 3차: 네이버 fetch (rate limit 안에서)
        if allow_fetch and fetch_count < max_fetch_per_call:
            wics = fetch_naver_industry(code)
            fetch_count += 1
            time.sleep(0.5)  # 네이버 부하 분산
            if wics:
                with _lock:
                    cache[code] = {
                        "name": name,
                        "wics": wics,
                        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    }
                code_to_sector[code] = wics_map.get(_normalize_wics(wics), "기타")
                continue

        # 4차: Claude fallback 후보
        pending_for_claude.append((name, code))

    # WICS 캐시 일괄 저장 (변경됐으면)
    if fetch_count > 0:
        _save_json(_WICS_CACHE_PATH, cache)
        print(f"[SECTOR] 네이버 fetch {fetch_count}건 캐시 저장")

    # Claude fallback
    if allow_claude and pending_for_claude:
        try:
            from telegram_bot.collectors.domestic_market import _classify_themes_with_claude
            names = [n for n, _c in pending_for_claude]
            name_to_sector = _classify_themes_with_claude(names)
            for name, code in pending_for_claude:
                code_to_sector[code] = name_to_sector.get(name, "기타")
        except Exception as e:
            print(f"[SECTOR] Claude fallback 실패: {e}")
            for _name, code in pending_for_claude:
                code_to_sector[code] = "기타"
    else:
        for _name, code in pending_for_claude:
            code_to_sector[code] = "기타"

    return code_to_sector


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트 — 사용자가 본 잘못 분류 케이스
    test = [
        {"종목코드": "028050", "종목명": "가온전선"},
        {"종목코드": "178920", "종목명": "PI첨단소재"},
        {"종목코드": "248070", "종목명": "솔루엠"},
        {"종목코드": "036890", "종목명": "진성티이씨"},
        {"종목코드": "079960", "종목명": "동양이엔피"},
        {"종목코드": "067310", "종목명": "하나마이크론"},
        {"종목코드": "046890", "종목명": "서울반도체"},
        {"종목코드": "126340", "종목명": "비나텍"},
        {"종목코드": "178320", "종목명": "서진시스템"},
    ]
    result = classify_stocks_batch(test, allow_claude=False)
    for s in test:
        print(f"  {s['종목코드']} {s['종목명']:15s} → {result.get(s['종목코드'])}")
