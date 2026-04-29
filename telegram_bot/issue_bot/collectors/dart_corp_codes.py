"""DART 회사 고유번호(corp_code) 매핑

DART OpenAPI list.json은 corp_name 파라미터가 없고 corp_code 8자리만 받음.
회사명 검색 위해 corp_code.xml (전체 회사 목록) 다운로드 후 캐시 + 매칭.

흐름:
1. corpCode.xml.zip 다운로드 (~3MB, 1회)
2. 압축 해제 후 XML 파싱 → JSON 캐시 (~5MB)
3. 회사명 매칭: 정확 일치 → 부분 일치 → 후보 목록 반환
4. 캐시 30일 후 자동 재다운로드 (신규 상장 반영)

사용:
    from telegram_bot.issue_bot.collectors.dart_corp_codes import find_corp_code

    code = find_corp_code("대한전선")  # → "00112004" (정확 매칭 1건)
    matches = find_corp_code("삼성", limit=5)  # → ["00126380(삼성전자)", "00164742(삼성전기)", ...]
"""
import datetime
import io
import json
import os
import re
import threading
import xml.etree.ElementTree as ET
import zipfile

import requests

from telegram_bot.config import DART_API_KEY


HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history", "issue_bot",
)
CACHE_PATH = os.path.join(HISTORY_DIR, "dart_corp_codes.json")
CACHE_META_PATH = os.path.join(HISTORY_DIR, "dart_corp_codes.meta.json")
CACHE_TTL_DAYS = 30  # 30일 후 재다운로드

DART_CORPCODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


# 메모리 캐시
_corp_map_cache = None  # {corp_code: {"name", "stock_code", ...}}
_name_index = None      # {정규화된 회사명: corp_code}

# 백그라운드 다운로드 상태
_download_lock = threading.Lock()
_download_in_progress = False


def _normalize_name(name: str) -> str:
    """회사명 정규화 — 공백·괄호·특수문자 제거 + 소문자."""
    if not name:
        return ""
    n = re.sub(r"[\s\(\)\[\]주식회사㈜()]", "", name)
    return n.lower()


def _is_cache_fresh() -> bool:
    """캐시가 TTL 내에 있는지."""
    if not os.path.exists(CACHE_PATH) or not os.path.exists(CACHE_META_PATH):
        return False
    try:
        with open(CACHE_META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
        downloaded_at = datetime.datetime.fromisoformat(meta.get("downloaded_at", ""))
        age = datetime.datetime.now() - downloaded_at
        return age.days < CACHE_TTL_DAYS
    except Exception:
        return False


def _download_and_cache():
    """DART corpCode.xml 다운로드 + JSON 캐시."""
    if not DART_API_KEY:
        print("[DART_CORP_CODES] DART_API_KEY 없음")
        return False

    try:
        print(f"[DART_CORP_CODES] corpCode.xml 다운로드 중...")
        res = requests.get(
            DART_CORPCODE_URL,
            params={"crtfc_key": DART_API_KEY},
            timeout=30,
        )
        if res.status_code != 200:
            print(f"[DART_CORP_CODES] HTTP {res.status_code}")
            return False

        # 응답이 zip 파일
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            xml_data = zf.read("CORPCODE.xml")

        # XML 파싱
        root = ET.fromstring(xml_data)
        corp_map = {}
        for elem in root.findall("list"):
            corp_code = (elem.findtext("corp_code") or "").strip()
            corp_name = (elem.findtext("corp_name") or "").strip()
            stock_code = (elem.findtext("stock_code") or "").strip()
            modify_date = (elem.findtext("modify_date") or "").strip()
            if not corp_code or not corp_name:
                continue
            corp_map[corp_code] = {
                "name": corp_name,
                "stock_code": stock_code,
                "modify_date": modify_date,
            }

        # 캐시 저장
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(corp_map, f, ensure_ascii=False)
        with open(CACHE_META_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "total": len(corp_map),
            }, f, ensure_ascii=False)

        print(f"[DART_CORP_CODES] 캐시 저장 완료 ({len(corp_map):,}개 회사)")
        return True
    except Exception as e:
        print(f"[DART_CORP_CODES] 다운로드 실패: {e}")
        return False


def _do_load_cache_file():
    """디스크 캐시 → 메모리 인덱싱 (다운로드 X, 파일이 있다고 가정)."""
    global _corp_map_cache, _name_index
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            _corp_map_cache = json.load(f)
        _name_index = {}
        for code, info in _corp_map_cache.items():
            normalized = _normalize_name(info.get("name", ""))
            if normalized and normalized not in _name_index:
                _name_index[normalized] = code
        print(f"[DART_CORP_CODES] 메모리 인덱싱 완료 ({len(_corp_map_cache):,}개)")
    except Exception as e:
        print(f"[DART_CORP_CODES] 캐시 로드 실패: {e}")
        _corp_map_cache = {}
        _name_index = {}


def _async_download_and_load():
    """백그라운드 스레드에서 다운로드 + 로드. 사용자 차단 X."""
    global _download_in_progress
    try:
        if _download_and_cache():
            _do_load_cache_file()
    finally:
        _download_in_progress = False


def trigger_async_download_if_needed():
    """캐시 없거나 만료면 백그라운드 다운로드 시작 (즉시 반환).

    main.py 봇 시작 시 호출해서 사용자 첫 호출 전에 미리 준비.
    """
    global _download_in_progress
    if _is_cache_fresh():
        return False  # 이미 신선
    with _download_lock:
        if _download_in_progress:
            return False  # 이미 진행 중
        _download_in_progress = True
    t = threading.Thread(target=_async_download_and_load, daemon=True)
    t.start()
    return True


def _load_cache():
    """캐시 로드 + 메모리 인덱싱.

    동작:
    - 캐시 신선하면 동기 로드 (즉시)
    - 캐시 없거나 만료면 동기 다운로드 + 로드 (4분 정도, 첫 호출만)

    백그라운드 다운로드는 trigger_async_download_if_needed() 별도 호출.
    """
    global _corp_map_cache, _name_index
    if _corp_map_cache is not None:
        return

    if not _is_cache_fresh():
        # 다운로드가 백그라운드에서 진행 중이면 즉시 빈 결과로 fallback
        # (사용자 차단 X, 클라이언트 측 부분 매칭으로 작동)
        with _download_lock:
            if _download_in_progress:
                _corp_map_cache = {}
                _name_index = {}
                return
        # 진행 중 아니면 동기 다운로드 (이전 버전 호환)
        if not _download_and_cache():
            _corp_map_cache = {}
            _name_index = {}
            return

    _do_load_cache_file()


def find_corp_code(query: str, limit: int = 5) -> dict:
    """회사명 → corp_code 매칭.

    Args:
        query: 사용자 입력 회사명 (예: "대한전선", "삼성")
        limit: 부분 매칭 시 최대 후보 수

    Returns:
        {
          "exact": str|None,    # 정확 매칭된 corp_code
          "candidates": [{"code", "name", "stock_code"}, ...],  # 부분 매칭 후보
        }
    """
    _load_cache()
    if not _corp_map_cache:
        return {"exact": None, "candidates": []}

    query_norm = _normalize_name(query)
    if not query_norm:
        return {"exact": None, "candidates": []}

    # 1. 정확 매칭
    exact = _name_index.get(query_norm)
    if exact:
        return {
            "exact": exact,
            "candidates": [{
                "code": exact,
                "name": _corp_map_cache[exact]["name"],
                "stock_code": _corp_map_cache[exact].get("stock_code", ""),
            }],
        }

    # 2. 부분 매칭 (포함)
    candidates = []
    for code, info in _corp_map_cache.items():
        name = info.get("name", "")
        name_norm = _normalize_name(name)
        if query_norm in name_norm:
            candidates.append({
                "code": code,
                "name": name,
                "stock_code": info.get("stock_code", ""),
            })
        if len(candidates) >= 200:  # 너무 많으면 중단
            break

    # 상장사 우선 정렬 (stock_code 있는 게 먼저)
    candidates.sort(key=lambda x: (not x["stock_code"], len(x["name"])))

    return {
        "exact": None,
        "candidates": candidates[:limit],
    }


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    for q in ["대한전선", "삼성전자", "삼성", "SK하이닉스", "없는회사"]:
        result = find_corp_code(q, limit=5)
        print(f"== '{q}' ==")
        if result["exact"]:
            ex = result["candidates"][0]
            print(f"  정확 매칭: [{result['exact']}] {ex['name']} (stock={ex['stock_code']})")
        else:
            print(f"  정확 매칭 없음. 후보 {len(result['candidates'])}건:")
            for c in result["candidates"]:
                print(f"    [{c['code']}] {c['name']} (stock={c['stock_code']})")
        print()
