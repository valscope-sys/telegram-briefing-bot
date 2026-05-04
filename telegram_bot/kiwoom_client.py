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


def kiwoom_post(api_id, body, url_path="/api/dostk/stkinfo"):
    """키움 REST API POST 호출"""
    token = get_kiwoom_token()
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "api-id": api_id,
        "authorization": f"Bearer {token}",
    }
    res = requests.post(
        f"{KIWOOM_BASE_URL}{url_path}",
        headers=headers,
        json=body,
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


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
