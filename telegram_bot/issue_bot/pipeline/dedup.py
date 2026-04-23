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
    "실적": ["실적", "영업이익", "영업익", "매출액", "매출", "순이익", "잠정실적",
           "분기보고서", "반기보고서", "사업보고서", "어닝", "earnings",
           "역대 최대", "역대최대", "사상최대", "서프라이즈"],
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


# 뉴스 제목에서 기업명 추출용 매핑 (한국어 별칭 포함).
# RSS의 `company_name`은 매체명(한국경제 등)이라 그것만으로는 같은 기업 뉴스
# 중복 제거 불가. 제목에서 기업 식별 후 dedup 키 사용.
# 동일 기업의 별칭을 정식명 1개로 정규화.
_COMPANY_ALIASES = {
    # 반도체·IT
    "SK하이닉스": ["SK하이닉스", "SK 하이닉스", "하이닉스", "SK하닉", "하닉"],
    "삼성전자": ["삼성전자", "삼전"],
    "TSMC": ["TSMC", "Tsmc", "tsmc", "타이완반도체"],
    "엔비디아": ["엔비디아", "NVIDIA", "Nvidia", "NVDA"],
    "애플": ["애플", "Apple", "AAPL"],
    "마이크론": ["마이크론", "Micron", "MU"],
    "인텔": ["인텔", "Intel", "INTC"],
    "브로드컴": ["브로드컴", "Broadcom", "AVGO"],
    "AMD": ["AMD"],
    "ARM": ["ARM", "Arm"],
    "ASML": ["ASML"],
    "테슬라": ["테슬라", "Tesla", "TSLA"],
    "마이크로소프트": ["마이크로소프트", "Microsoft", "MSFT"],
    "구글": ["구글", "Google", "알파벳", "Alphabet", "GOOGL"],
    "메타": ["메타", "Meta", "META"],
    "아마존": ["아마존", "Amazon", "AMZN"],
    "넷플릭스": ["넷플릭스", "Netflix", "NFLX"],
    # 2차전지·EV
    "LG에너지솔루션": ["LG에너지솔루션", "LG엔솔", "엘지엔솔"],
    "삼성SDI": ["삼성SDI", "SDI"],
    "SK온": ["SK온"],
    "에코프로": ["에코프로", "에코프로비엠", "에코프로BM"],
    "포스코퓨처엠": ["포스코퓨처엠", "퓨처엠"],
    "현대차": ["현대차", "현대자동차"],
    "기아": ["기아", "기아차"],
    # 디스플레이·부품
    "LG디스플레이": ["LG디스플레이", "LGD"],
    "LG이노텍": ["LG이노텍"],
    "삼성전기": ["삼성전기", "삼전기"],
    "삼성디스플레이": ["삼성디스플레이", "삼디"],
    "심텍": ["심텍"],
    "대덕전자": ["대덕전자"],
    "이수페타시스": ["이수페타시스"],
    # 바이오·제약
    "삼성바이오로직스": ["삼성바이오로직스", "삼성바이오", "삼바"],
    "셀트리온": ["셀트리온"],
    "유한양행": ["유한양행"],
    "알테오젠": ["알테오젠"],
    # 기타 대형
    "현대중공업": ["현대중공업", "HD현대중공업"],
    "한화오션": ["한화오션"],
    "삼성중공업": ["삼성중공업"],
    "한화에어로스페이스": ["한화에어로스페이스", "한화에어로"],
    "LIG넥스원": ["LIG넥스원"],
    "두산에너빌리티": ["두산에너빌리티", "두산에너빌"],
    "POSCO": ["POSCO", "포스코", "포스코홀딩스"],
    "크래프톤": ["크래프톤"],
    "NAVER": ["NAVER", "네이버", "Naver"],
    "카카오": ["카카오"],
}


def _extract_company_from_title(title: str) -> str:
    """뉴스 제목에서 주요 상장사 추출. 못 찾으면 빈 문자열."""
    if not title:
        return ""
    for canonical, aliases in _COMPANY_ALIASES.items():
        for alias in aliases:
            if alias in title:
                return canonical
    return ""


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
        # RSS 뉴스는 company_name이 매체명(한국경제 등). 제목에서 실제 기업 추출.
        extracted = _extract_company_from_title(event.get("title", "")) if event.get("source") == "RSS" else ""
        if extracted:
            ticker = f"C_{extracted}"
        else:
            # fallback: 회사명 앞 8자
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
