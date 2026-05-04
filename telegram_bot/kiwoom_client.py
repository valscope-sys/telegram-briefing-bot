"""키움증권 REST API 클라이언트 (52주 신고가 전용)"""
import datetime
import time
import requests
from telegram_bot.config import KIWOOM_APP_KEY, KIWOOM_APP_SECRET

KIWOOM_BASE_URL = "https://api.kiwoom.com"

_token_cache = {"token": None, "expires": None}


def get_kiwoom_token():
    """키움 접근토큰 발급 (캐싱)"""
    now = datetime.datetime.now()
    if _token_cache["token"] and _token_cache["expires"] and _token_cache["expires"] > now:
        return _token_cache["token"]

    res = requests.post(
        f"{KIWOOM_BASE_URL}/oauth2/token",
        json={
            "grant_type": "client_credentials",
            "appkey": KIWOOM_APP_KEY,
            "secretkey": KIWOOM_APP_SECRET,
        },
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    data = res.json()
    if data.get("return_code") != 0:
        raise Exception(f"키움 토큰 발급 실패: {data}")

    _token_cache["token"] = data["token"]
    # expires_dt: YYYYMMDDHHMMSS
    exp_str = data.get("expires_dt", "")
    if exp_str:
        _token_cache["expires"] = datetime.datetime.strptime(exp_str, "%Y%m%d%H%M%S")
    else:
        _token_cache["expires"] = now + datetime.timedelta(hours=12)

    return _token_cache["token"]


def kiwoom_post(api_id, body, url_path="/api/dostk/stkinfo",
                cont_yn=None, next_key=None):
    """키움 REST API POST 호출.

    페이지네이션 헤더 (선택):
    - cont_yn = "Y" + next_key = "000125000010000001"
      → 두 헤더 같이 보내면 키움이 다음 페이지 반환
    """
    token = get_kiwoom_token()
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "api-id": api_id,
        "authorization": f"Bearer {token}",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key
    res = requests.post(
        f"{KIWOOM_BASE_URL}{url_path}",
        headers=headers,
        json=body,
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def kiwoom_post_with_meta(api_id, body, url_path="/api/dostk/stkinfo",
                          cont_yn=None, next_key=None):
    """페이지네이션 메타까지 같이 반환.

    Returns:
        (json_body, response_headers) — 호출 측에서 cont-yn, next-key 활용 가능.
    """
    token = get_kiwoom_token()
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "api-id": api_id,
        "authorization": f"Bearer {token}",
    }
    if cont_yn:
        headers["cont-yn"] = cont_yn
    if next_key:
        headers["next-key"] = next_key
    res = requests.post(
        f"{KIWOOM_BASE_URL}{url_path}",
        headers=headers,
        json=body,
        timeout=10,
    )
    res.raise_for_status()
    return res.json(), dict(res.headers)


def kiwoom_paginated(api_id, body, url_path="/api/dostk/stkinfo",
                     result_field="ntl_pric", max_pages=20):
    """페이지네이션 자동 누적. 모든 페이지를 하나의 list로 반환.

    Args:
        api_id: ka10016 등
        body: 요청 body (페이지네이션 무관 파라미터)
        result_field: 응답 list가 들어있는 키 (ka10016 = "ntl_pric")
        max_pages: 안전 limit (무한 루프 방지)

    Returns:
        list — 모든 페이지의 결과 누적.
    """
    all_items = []
    cont_yn = None
    next_key = None

    for page in range(max_pages):
        data, headers = kiwoom_post_with_meta(
            api_id, body, url_path,
            cont_yn=cont_yn, next_key=next_key,
        )
        items = data.get(result_field, []) or []
        all_items.extend(items)

        cont_yn = headers.get("cont-yn") or headers.get("Cont-Yn") or ""
        next_key = headers.get("next-key") or headers.get("Next-Key") or ""

        if cont_yn != "Y" or not next_key:
            break
        # rate limit (키움 초당 5건 안전)
        time.sleep(0.25)

    return all_items


def fetch_stock_info(stock_code: str) -> dict:
    """ka10001 — 주식기본정보 조회 (업종 정보 포함).

    응답 주요 필드 (키움 ka10001):
    - stk_cd, stk_nm: 종목코드/명
    - upName / sect_nm / idu_nm: 업종명 (필드명은 키움 응답 따라 다름)
    - mac: 시가총액
    - per, pbr, eps, bps: 재무지표
    - 등 30+

    Returns:
        키움 raw 응답 dict 그대로 (업종 추출은 sector_classifier에서)
    """
    return kiwoom_post("ka10001", {"stk_cd": stock_code})


# 키움 ka10001 응답 중 업종 후보 필드명 (응답마다 다를 수 있어 fallback 순서)
_INDUSTRY_FIELD_CANDIDATES = (
    "upName",       # 업종명
    "up_nm",
    "sect_nm",      # 섹터명
    "idu_nm",       # 업종명
    "induty_nm",
    "indst_nm",
    "stk_class_nm", # 종목분류명
    "biz_nm",
)


def extract_industry_from_stock_info(info: dict) -> str:
    """ka10001 응답에서 업종 문자열 추출 (필드명 fallback)."""
    if not info:
        return ""
    for field in _INDUSTRY_FIELD_CANDIDATES:
        v = info.get(field)
        if v and isinstance(v, str) and v.strip():
            return v.strip()
    return ""
