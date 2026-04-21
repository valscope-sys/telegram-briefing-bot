"""DART API 실동작 검증 스크립트 (Phase 0)

목적:
1. list.json API 응답 구조 파악
2. report_nm(공시 유형) 분포 100건 샘플링 → dart_category_map.json 기초 자료
3. KIND HTML 본문 추출 안정성 테스트

사용법:
  python scripts/test_dart_api.py
"""
import os
import sys
import json
import datetime
from collections import Counter
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Windows cp949 콘솔에서도 한글/이모지 출력 가능하게
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_env_path)

DART_API_KEY = os.getenv("DART_API_KEY", "")

if not DART_API_KEY:
    print("[ERROR] .env에 DART_API_KEY가 없습니다.")
    print("  opendart.fss.or.kr 회원가입 후 키 발급 → .env에 DART_API_KEY=... 추가")
    sys.exit(1)


def fetch_list(days_back=3):
    """최근 N일치 공시 목록 조회"""
    today = datetime.date.today()
    bgn = (today - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": 1,
        "page_count": 100,
        "last_reprt_at": "Y",
    }
    res = requests.get(url, params=params, timeout=15)
    return res.json()


def analyze_report_nm(items):
    """공시 유형(report_nm) 분포 분석"""
    counter = Counter()
    for item in items:
        report_nm = item.get("report_nm", "")
        counter[report_nm] += 1
    return counter


def fetch_kind_html(rcept_no):
    """KIND에서 공시 본문 HTML 추출 테스트"""
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    try:
        res = requests.get(url, timeout=15)
        soup = BeautifulSoup(res.text, "lxml")
        # KIND는 iframe 구조라 본문 직접 추출은 추가 요청 필요
        iframe = soup.find("iframe")
        body_size = len(res.text)
        has_iframe = iframe is not None
        return {"status_code": res.status_code, "body_size": body_size, "has_iframe": has_iframe}
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 70)
    print("DART API 실동작 검증")
    print("=" * 70)
    print()

    print("[1/3] 최근 3일치 공시 목록 조회 중...")
    data = fetch_list(days_back=3)

    status = data.get("status", "")
    message = data.get("message", "")
    items = data.get("list", [])

    print(f"  status: {status}")
    print(f"  message: {message}")
    print(f"  총 공시 건수: {len(items)}")
    print()

    if status != "000":
        print(f"[ERROR] API 호출 실패: {message}")
        sys.exit(1)

    print("[2/3] 공시 유형(report_nm) 분포 (상위 20개)...")
    distribution = analyze_report_nm(items)
    print()
    print(f"  {'공시 유형':<40} {'건수':>6}")
    print(f"  {'-' * 40} {'------':>6}")
    for name, count in distribution.most_common(20):
        print(f"  {name:<40} {count:>6}")
    print()

    print("[3/3] KIND HTML 본문 추출 테스트 (샘플 3건)...")
    for item in items[:3]:
        rcept_no = item.get("rcept_no", "")
        corp_name = item.get("corp_name", "")
        report_nm = item.get("report_nm", "")
        result = fetch_kind_html(rcept_no)
        print(f"  [{corp_name}] {report_nm}")
        print(f"    rcept_no: {rcept_no}")
        print(f"    결과: {result}")
    print()

    print("=" * 70)
    print("[OK] 검증 완료")
    print("=" * 70)
    print()
    print("첫 10건 원본 필드 샘플 (스펙 작성용):")
    print()
    for item in items[:10]:
        print(json.dumps(item, ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
