"""중복 감지 — 구조화 해시 키 기반

키 형식: {ticker or NONE}:{event_type}:{YYYY-MM-DD}:{title_hash[:8]}

같은 이벤트가 DART + 뉴스 양쪽에서 들어올 수 있음. 첫 발견을 primary,
이후는 secondary로 표시하여 primary의 related_sources에만 링크 추가.
"""
import os
import json
import hashlib
import re
import datetime
from typing import Optional

ISSUE_BOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
    "issue_bot",
)
SEEN_IDS_PATH = os.path.join(ISSUE_BOT_DIR, "seen_ids.jsonl")


EVENT_TYPE_KEYWORDS = {
    "실적": ["실적", "영업이익", "매출액", "잠정실적", "분기보고서", "반기보고서", "사업보고서"],
    "자사주": ["자기주식", "자사주", "자사주소각", "자기주식취득", "자기주식처분"],
    "증자감자": ["유상증자", "무상증자", "감자", "주식분할", "주식병합"],
    "M&A": ["합병", "분할", "영업양도", "영업양수", "타법인주식", "지분인수"],
    "채권": ["전환사채", "신주인수권부사채", "교환사채", "전환청구권"],
    "계약": ["단일판매", "공급계약", "수주", "계약체결"],
    "지분변동": ["대량보유", "최대주주", "주주변경"],
    "임상": ["임상시험", "품목허가", "신약"],
    "가격": ["가격 인상", "가격 인하", "수출단가", "판가"],
    "통계": ["수출금액", "수출통계", "수출입"],
    "파생": ["결합증권", "파생결합"],
}


def _normalize_title(title: str) -> str:
    """제목 정규화: 공백/정정 표시 제거"""
    if not title:
        return ""
    t = re.sub(r"\s+", "", title)
    t = re.sub(r"\[기재정정\]|\[정정\]|\[기재수정\]", "", t)
    return t[:100]


def _infer_event_type(title: str, report_nm: str = "") -> str:
    """제목 + report_nm으로 이벤트 유형 추정"""
    text = f"{title} {report_nm}".lower()
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return event_type
    return "misc"


def generate_dedup_key(event: dict) -> str:
    """
    이슈 이벤트에서 중복 감지 키 생성.

    Args:
        event: {
            "ticker": "005930",              # 종목코드, 없으면 None
            "company_name": "삼성전자",
            "title": "...",
            "report_nm": "...",              # DART 전용, 없으면 ""
            "event_type": "자사주",           # 주어지면 사용, 없으면 추정
            "date": "2026-04-21",            # YYYY-MM-DD
        }

    Returns:
        "005930:자사주:2026-04-21:a3f8e9d1"
    """
    ticker = event.get("ticker") or event.get("company_id") or "NONE"
    if ticker == "NONE":
        # ticker 없으면 회사명 앞 8자로 대체
        company = event.get("company_name", "").strip()[:8] or "UNKNOWN"
        ticker = f"C_{company}"

    event_type = event.get("event_type") or _infer_event_type(
        event.get("title", ""),
        event.get("report_nm", ""),
    )

    date = event.get("date", datetime.date.today().strftime("%Y-%m-%d"))

    title_norm = _normalize_title(event.get("title", ""))
    title_hash = hashlib.sha1(title_norm.encode("utf-8")).hexdigest()[:8] if title_norm else "nohash"

    return f"{ticker}:{event_type}:{date}:{title_hash}"


def _ensure_seen_file():
    os.makedirs(os.path.dirname(SEEN_IDS_PATH), exist_ok=True)
    if not os.path.exists(SEEN_IDS_PATH):
        open(SEEN_IDS_PATH, "a", encoding="utf-8").close()


def is_duplicate(dedup_key: str) -> bool:
    """이미 본 키인지 조회"""
    _ensure_seen_file()
    try:
        with open(SEEN_IDS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("id") == dedup_key:
                        return True
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return False
    return False


def mark_seen(dedup_key: str, source_url: str = "", role: str = "primary",
              extra: Optional[dict] = None):
    """seen_ids.jsonl에 레코드 append"""
    _ensure_seen_file()
    rec = {
        "id": dedup_key,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_url": source_url,
        "role": role,
    }
    if extra:
        rec.update(extra)
    with open(SEEN_IDS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def find_recent_duplicates(base_key: str, hours: int = 24) -> list:
    """
    같은 ticker + event_type을 가진 최근 N시간 내 레코드 반환.
    primary/secondary 판별과 related_sources 병합에 사용.

    base_key 형식: "ticker:event_type:date:hash"
    """
    _ensure_seen_file()
    parts = base_key.split(":")
    if len(parts) < 4:
        return []
    ticker, event_type = parts[0], parts[1]
    prefix = f"{ticker}:{event_type}:"

    cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
    results = []
    try:
        with open(SEEN_IDS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if not rec.get("id", "").startswith(prefix):
                        continue
                    ts = rec.get("timestamp", "")
                    try:
                        rec_time = datetime.datetime.fromisoformat(ts)
                        if rec_time < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass
                    results.append(rec)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return results


def choose_primary(candidates: list) -> tuple:
    """
    여러 후보 중 더 상세한 쪽을 primary로.
    기준: text 길이 + source_trust_score (DART=10, 주요언론=7, 그외=5)

    Returns:
        (primary_event, list_of_secondary_events)
    """
    TRUST = {"DART": 10, "RSS": 6, "PRICE_API": 5}

    def score(ev):
        text_len = len(ev.get("original_content", "") or ev.get("title", ""))
        src = ev.get("source", "RSS")
        return (text_len, TRUST.get(src, 5))

    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], []
    sorted_cands = sorted(candidates, key=score, reverse=True)
    return sorted_cands[0], sorted_cands[1:]


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # 자체 테스트
    ev = {
        "ticker": "005930",
        "company_name": "삼성전자",
        "title": "자기주식취득결정",
        "report_nm": "주요사항보고서(자기주식취득결정)",
        "date": "2026-04-21",
    }
    key = generate_dedup_key(ev)
    print(f"Dedup key: {key}")
    print(f"Is duplicate: {is_duplicate(key)}")
    # mark_seen(key, source_url="https://dart.fss.or.kr/...", role="primary")
    # print(f"After mark, is duplicate: {is_duplicate(key)}")
