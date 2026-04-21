"""DART 공시 수집기 — Phase 1

동작:
1. opendart.fss.or.kr의 list.json 폴링 (최근 공시)
2. dart_category_map.json으로 rule-based 필터링 (빠른 1차 분류)
3. KIND(dart.fss.or.kr) HTML에서 본문 발췌 (iframe 처리)
4. seen_ids.jsonl로 중복 제외
5. 구조화된 이슈 이벤트 리스트 반환 (downstream 파이프라인으로 전달)

반환 스키마:
{
  "id": "dart_{rcept_no}",
  "source": "DART",
  "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...",
  "source_id": "20260421000123",
  "fetched_at": "ISO8601",
  "ticker": "005930",
  "company_name": "삼성전자",
  "corp_code": "00126380",
  "corp_cls": "Y",           # Y=유가, K=코스닥, N=코넥스, E=기타
  "title": "주요사항보고서(자기주식취득결정)",
  "report_nm_raw": "...",
  "body_excerpt": "본문 300자",
  "category_hint": "B",      # dart_category_map 매칭 시 Template 힌트
  "priority_hint": "URGENT", # dart_category_map 매칭 시 priority 힌트
  "event_type": "자사주",     # dedup_key 생성용
  "date": "2026-04-21"
}
"""
import os
import json
import datetime
import re
import time
import requests
from bs4 import BeautifulSoup

from telegram_bot.config import DART_API_KEY

HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
)
DART_CATEGORY_MAP_PATH = os.path.join(HISTORY_DIR, "dart_category_map.json")

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
KIND_VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
KIND_IFRAME_URL = "https://dart.fss.or.kr{path}"  # iframe src 보통 /dsaf001/dsaf001.do?rcpNo=...&dcmNo=...


# ===== category_map 로딩 (모듈 load 시 1회) =====

_CATEGORY_MAP = None


def _load_category_map():
    global _CATEGORY_MAP
    if _CATEGORY_MAP is not None:
        return _CATEGORY_MAP
    try:
        with open(DART_CATEGORY_MAP_PATH, "r", encoding="utf-8") as f:
            _CATEGORY_MAP = json.load(f)
    except FileNotFoundError:
        print(f"[DART] category_map 없음: {DART_CATEGORY_MAP_PATH}")
        _CATEGORY_MAP = {"mappings": {}, "skip_patterns": [], "prefix_rules": {}}
    return _CATEGORY_MAP


# ===== report_nm 정규화 =====

def _normalize_report_nm(raw: str) -> tuple:
    """
    report_nm에서 공백 정리 + 접두사 분리.
    Returns: (clean_name, prefix)
      예: "[기재정정]단일판매ㆍ공급계약체결   " -> ("단일판매ㆍ공급계약체결", "[기재정정]")
    """
    if not raw:
        return "", ""
    s = raw.strip()
    prefix = ""
    m = re.match(r"^(\[기재정정\]|\[정정\]|\[첨부정정\]|\[기재수정\])\s*(.*)$", s)
    if m:
        prefix = m.group(1)
        s = m.group(2).strip()
    # 내부 연속 공백 정리
    s = re.sub(r"\s+", " ", s)
    return s, prefix


def classify_by_rules(report_nm_raw: str) -> dict:
    """
    report_nm을 category_map과 매칭해 template/priority 힌트 반환.
    매칭 실패 시 None 반환 → downstream에서 Haiku 필터가 분류.
    """
    cat_map = _load_category_map()
    clean_name, prefix = _normalize_report_nm(report_nm_raw)

    # 1. skip_patterns 매칭 (우선)
    for sp in cat_map.get("skip_patterns", []):
        if sp in clean_name:
            return {
                "template": None,
                "priority": "SKIP",
                "reason": f"skip_pattern 매칭: {sp}",
                "prefix": prefix,
            }

    # 2. 직접 매핑
    mappings = cat_map.get("mappings", {})
    mapping = mappings.get(clean_name)
    if not mapping:
        # 부분 일치 fallback (예: "주요사항보고서(자기주식취득결정)"이 정확히 없어도 "자기주식취득결정"만 있을 때)
        for key, val in mappings.items():
            if key in clean_name or clean_name in key:
                mapping = val
                break

    if not mapping:
        return None  # 매칭 실패, Haiku에게 맡김

    priority = mapping.get("priority", "NORMAL")
    template = mapping.get("template", "B")

    # 3. prefix_rules 적용 ([기재정정] 등 → 우선순위 강등)
    if prefix:
        prefix_rules = cat_map.get("prefix_rules", {})
        rule = prefix_rules.get(prefix)
        if rule and rule.get("priority_override"):
            priority = rule["priority_override"]

    return {
        "template": template,
        "priority": priority,
        "reason": f"dart_category_map: {clean_name}",
        "prefix": prefix,
        "matched_key": clean_name,
    }


def infer_event_type(report_nm_raw: str) -> str:
    """dedup_key 생성에 쓰일 event_type 추정"""
    clean_name, _ = _normalize_report_nm(report_nm_raw)
    patterns = [
        (r"자사주|자기주식", "자사주"),
        (r"실적|영업이익|매출|분기보고|반기보고|사업보고", "실적"),
        (r"유상증자|무상증자|감자", "증자감자"),
        (r"합병|분할|영업양도|영업양수", "M&A"),
        (r"타법인주식", "M&A"),
        (r"전환사채|신주인수권부사채|교환사채|전환청구", "채권"),
        (r"단일판매|공급계약|수주", "계약"),
        (r"대량보유|최대주주|주주변경", "지분변동"),
        (r"임상|품목허가", "임상"),
        (r"거래정지|상장폐지", "거래정지"),
        (r"기업가치제고", "밸류업"),
        (r"IR|기업설명회", "IR"),
    ]
    for pat, etype in patterns:
        if re.search(pat, clean_name):
            return etype
    return "misc"


# ===== DART API =====

def fetch_recent_disclosures(days_back: int = 1, page_count: int = 100, corp_cls=None):
    """
    DART list.json으로 최근 공시 목록 조회.

    Args:
        days_back: 며칠치 (기본 1 = 오늘)
        page_count: 페이지당 조회 건수 (최대 100)
        corp_cls: "Y"(유가)/"K"(코스닥)/"N"(코넥스). None=전체

    Returns:
        list of dict (원본 DART 응답 아이템 그대로)
    """
    if not DART_API_KEY:
        print("[DART] DART_API_KEY 없음 — 빈 리스트 반환")
        return []

    today = datetime.date.today()
    bgn = (today - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": 1,
        "page_count": page_count,
        "last_reprt_at": "Y",
    }
    if corp_cls:
        params["corp_cls"] = corp_cls

    try:
        res = requests.get(DART_LIST_URL, params=params, timeout=15)
        data = res.json()
    except Exception as e:
        print(f"[DART] API 호출 실패: {e}")
        return []

    if data.get("status") != "000":
        print(f"[DART] API 오류: {data.get('message')}")
        return []

    return data.get("list", [])


def fetch_kind_body(rcept_no: str, max_chars: int = 800) -> str:
    """
    KIND HTML에서 본문 추출. iframe 구조를 2-step으로 처리.

    Returns:
        본문 발췌 (최대 max_chars자). 실패 시 빈 문자열.
    """
    try:
        # 1단계: 뷰어 페이지에서 iframe URL 추출
        view_url = KIND_VIEW_URL.format(rcept_no=rcept_no)
        res = requests.get(view_url, timeout=15)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")

        # iframe src 또는 스크립트 내 'viewDoc' 호출 파싱
        # KIND 구조: JS로 iframe을 로드함. window.open('/dsaf001/dsaf001.do?...') 형태.
        # 정규식으로 추출 시도.
        m = re.search(r"viewDoc\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'", res.text)
        if m:
            # viewDoc(rcpNo, dcmNo, eleId, offset, ...)
            dcm_no = m.group(2)
            iframe_url = f"https://dart.fss.or.kr/report/viewer.do?rcpNo={rcept_no}&dcmNo={dcm_no}"
        else:
            # fallback: iframe 태그 직접 찾기
            iframe = soup.find("iframe")
            if iframe and iframe.get("src"):
                src = iframe["src"]
                iframe_url = src if src.startswith("http") else f"https://dart.fss.or.kr{src}"
            else:
                return ""

        # 2단계: iframe 본문 요청
        res2 = requests.get(iframe_url, timeout=15)
        if res2.status_code != 200:
            return ""

        soup2 = BeautifulSoup(res2.text, "lxml")
        # 텍스트 위주로 추출
        for tag in soup2(["script", "style"]):
            tag.decompose()
        text = soup2.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:max_chars]
    except Exception as e:
        print(f"[DART] KIND 본문 추출 실패 ({rcept_no}): {e}")
        return ""


# ===== 통합 수집 인터페이스 =====

def collect_disclosures(days_back: int = 1, fetch_body: bool = True) -> list:
    """
    최근 공시를 수집하여 이슈봇 파이프라인 형식으로 반환.

    Args:
        days_back: 며칠 전까지 (기본 1일)
        fetch_body: True면 KIND HTML 본문 추출 (느림, N+1 요청)

    Returns:
        list of 이슈 이벤트 dict (SKIP 판정된 항목 제외)
    """
    raw_items = fetch_recent_disclosures(days_back=days_back)
    events = []
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    for item in raw_items:
        rcept_no = item.get("rcept_no", "")
        report_nm_raw = item.get("report_nm", "")

        # 1차 rule-based 분류
        cls = classify_by_rules(report_nm_raw)

        # SKIP 판정이면 스킵 (rcept_dt 형식만 YYYYMMDD → YYYY-MM-DD)
        if cls and cls.get("priority") == "SKIP":
            continue

        rcept_dt = item.get("rcept_dt", "")
        date_str = (
            f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"
            if len(rcept_dt) == 8 else datetime.date.today().strftime("%Y-%m-%d")
        )

        event = {
            "id": f"dart_{rcept_no}",
            "source": "DART",
            "source_url": KIND_VIEW_URL.format(rcept_no=rcept_no),
            "source_id": rcept_no,
            "fetched_at": now_iso,
            "ticker": item.get("stock_code", "") or None,
            "company_name": item.get("corp_name", ""),
            "corp_code": item.get("corp_code", ""),
            "corp_cls": item.get("corp_cls", ""),
            "title": report_nm_raw.strip(),
            "report_nm_raw": report_nm_raw,
            "report_nm_clean": _normalize_report_nm(report_nm_raw)[0],
            "body_excerpt": "",
            "category_hint": cls.get("template") if cls else None,
            "priority_hint": cls.get("priority") if cls else None,
            "rule_match_reason": cls.get("reason") if cls else "매칭 실패(Haiku 필터 필요)",
            "event_type": infer_event_type(report_nm_raw),
            "date": date_str,
        }

        # 2단계: KIND 본문 (선택)
        if fetch_body:
            event["body_excerpt"] = fetch_kind_body(rcept_no)
            time.sleep(0.2)  # KIND rate limit 예방

        events.append(event)

    return events


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 70)
    print("DART 수집기 실행 (최근 1일, 본문 스킵)")
    print("=" * 70)
    events = collect_disclosures(days_back=1, fetch_body=False)
    print(f"\n수집된 이슈: {len(events)}건 (SKIP 제외)\n")

    # priority별 집계
    from collections import Counter
    prio_cnt = Counter(e.get("priority_hint") for e in events)
    print(f"priority 분포: {dict(prio_cnt)}\n")

    # 상위 10건 출력
    for ev in events[:10]:
        print(f"  [{ev['priority_hint'] or '?':<7}] [{ev['category_hint'] or '?'}] "
              f"{ev['company_name'][:15]:<15} | {ev['report_nm_clean'][:50]}")
        print(f"    → {ev['rule_match_reason']}")
        print()
