"""URL 해시 캐시 — Telegram callback_data 64바이트 제약 우회

Telegram 인라인 버튼 callback_data는 1~64 byte 제한.
DART URL은 60~80자, 일부 RSS 링크는 200자+ → 그대로 못 넣음.

해결: URL → 8자리 해시 → 디스크 캐시 → callback에서 hash로 조회.
- 디스크 (history/issue_bot/url_cache.json) 영속화
- 24시간 TTL 자동 청소
- 봇 재시작해도 유지

사용:
    from telegram_bot.issue_bot.utils.url_cache import register_url, lookup_url

    h = register_url("https://dart.fss.or.kr/...")  # 8자리 hash
    cb_data = f"card_url:{h}"  # 17자, 안전

    url = lookup_url(h)  # 원본 URL 복원
"""
import datetime
import hashlib
import json
import os
import threading

_LOCK = threading.Lock()

_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history", "issue_bot",
)
_CACHE_PATH = os.path.join(_HISTORY_DIR, "url_cache.json")

_TTL_HOURS = 24


def _hash_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _load_cache() -> dict:
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    tmp = _CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, _CACHE_PATH)


def _cleanup_expired(cache: dict) -> dict:
    """TTL 지난 엔트리 제거. 변경된 dict 반환."""
    now = datetime.datetime.now()
    keep = {}
    for h, entry in cache.items():
        try:
            saved_at = datetime.datetime.fromisoformat(entry.get("saved_at", ""))
            age_h = (now - saved_at).total_seconds() / 3600
            if age_h < _TTL_HOURS:
                keep[h] = entry
        except Exception:
            continue
    return keep


def register_url(url: str, label: str = "") -> str:
    """URL 등록 → 8자리 해시 반환. 동일 URL 재등록 시 같은 해시.

    Args:
        url: 원본 URL
        label: 카드 라벨 (예: "삼성전자 — 잠정실적") — 진단용

    Returns:
        10자리 hex 해시
    """
    if not url:
        return ""
    h = _hash_url(url)
    with _LOCK:
        cache = _load_cache()
        cache = _cleanup_expired(cache)
        cache[h] = {
            "url": url,
            "label": label,
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        _save_cache(cache)
    return h


def lookup_url(hash_str: str) -> str:
    """해시 → URL. 만료/미등록이면 빈 문자열."""
    if not hash_str:
        return ""
    with _LOCK:
        cache = _load_cache()
        entry = cache.get(hash_str)
        if not entry:
            return ""
        try:
            saved_at = datetime.datetime.fromisoformat(entry.get("saved_at", ""))
            age_h = (datetime.datetime.now() - saved_at).total_seconds() / 3600
            if age_h >= _TTL_HOURS:
                return ""
        except Exception:
            return ""
        return entry.get("url", "")


def lookup_label(hash_str: str) -> str:
    """해시 → 라벨. 디버그용."""
    if not hash_str:
        return ""
    with _LOCK:
        cache = _load_cache()
        entry = cache.get(hash_str)
        return entry.get("label", "") if entry else ""


def cleanup():
    """수동 정리 — TTL 만료 엔트리 즉시 제거."""
    with _LOCK:
        cache = _load_cache()
        cleaned = _cleanup_expired(cache)
        if len(cleaned) != len(cache):
            _save_cache(cleaned)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 테스트
    url1 = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260424800834"
    h1 = register_url(url1, "효성중공업 잠정실적")
    print(f"등록: {url1} → {h1}")
    print(f"조회: {h1} → {lookup_url(h1)}")
    print(f"라벨: {lookup_label(h1)}")
    print(f"존재안함: {lookup_url('deadbeef00')}")
