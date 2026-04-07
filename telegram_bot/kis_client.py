"""한국투자증권 KIS Open API 클라이언트"""
import datetime
import time
import requests
from telegram_bot.config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL


_token_cache = {"token": None, "expires": None}
_last_call_time = 0  # 마지막 API 호출 시간
_MIN_INTERVAL = 0.35  # 초당 3건 = 0.33초, 여유 두고 0.35초


def _rate_limit_wait():
    """초당 3건 제한 준수를 위한 자동 대기"""
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.time()


def get_access_token():
    """접근토큰 발급 (캐싱, 유효기간 1일)"""
    now = datetime.datetime.now()
    if _token_cache["token"] and _token_cache["expires"] and _token_cache["expires"] > now:
        return _token_cache["token"]

    _rate_limit_wait()
    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }
    res = requests.post(url, json=body, headers={"Content-Type": "application/json"})
    res.raise_for_status()
    data = res.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = datetime.datetime.strptime(
        data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S"
    )
    return _token_cache["token"]


def _get_headers(tr_id):
    """공통 헤더 생성"""
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }


def kis_get(url_path, tr_id, params, retry=2):
    """KIS REST API GET 호출 (rate limit 자동 대기 포함)"""
    _rate_limit_wait()
    headers = _get_headers(tr_id)
    url = f"{KIS_BASE_URL}{url_path}"
    for attempt in range(retry + 1):
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get("rt_cd") == "0":
                return data
            if data.get("msg_cd") == "EGW00201" and attempt < retry:
                time.sleep(1)
                continue
            raise Exception(f"KIS API Error: [{data.get('msg_cd')}] {data.get('msg1')}")
        if res.status_code == 403 and attempt < retry:
            time.sleep(2)
            continue
        res.raise_for_status()
    return {}


def kis_post(url_path, tr_id, body):
    """KIS REST API POST 호출"""
    _rate_limit_wait()
    headers = _get_headers(tr_id)
    url = f"{KIS_BASE_URL}{url_path}"
    res = requests.post(url, headers=headers, json=body, timeout=10)
    res.raise_for_status()
    data = res.json()
    if data.get("rt_cd") != "0":
        raise Exception(f"KIS API Error: [{data.get('msg_cd')}] {data.get('msg1')}")
    return data
