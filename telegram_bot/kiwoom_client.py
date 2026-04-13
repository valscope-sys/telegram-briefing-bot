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
