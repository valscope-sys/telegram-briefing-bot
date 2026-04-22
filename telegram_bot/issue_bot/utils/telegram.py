"""텔레그램 API 래퍼 — 이슈봇 전용

기존 telegram_bot/sender.py와 공존. 이슈봇은 HTML 모드 + 인라인 버튼 + DM 대상.
"""
import os
import time
import datetime
import requests
import pytz

from telegram_bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_ADMIN_CHAT_ID,
)

KST = pytz.timezone("Asia/Seoul")
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
ISSUE_BOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
    "issue_bot",
)
KILL_SWITCH_PATH = os.path.join(ISSUE_BOT_DIR, "KILL_SWITCH")
POLLER_LOCK_PATH = os.path.join(ISSUE_BOT_DIR, "poller.lock")
POLLER_LOCK_STALE_S = 30  # 30초 이상 갱신 없으면 stale (restart 시 대기 최소화)


# === 시간 보호 구간 ===

PROTECTED_WINDOWS = [
    ("모닝 브리핑", (6, 50), (7, 10)),      # 06:50~07:10
    ("이브닝 브리핑", (16, 20), (16, 50)),  # 16:20~16:50
]


def is_protected_time(now=None):
    """현재 시각이 기존 브리핑 보호 구간인지 체크"""
    now = now or datetime.datetime.now(KST)
    h, m = now.hour, now.minute
    cur = h * 60 + m
    for _name, (sh, sm), (eh, em) in PROTECTED_WINDOWS:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start <= cur < end:
            return True
    return False


def is_kill_switch_active():
    """KILL_SWITCH 활성 여부.

    파일 포맷:
    - 빈 파일 or 파일만 존재 → 무제한 활성 (기존 호환)
    - ISO8601 datetime 한 줄 → 그 시각 이후면 자동 삭제 + False 반환
      (예: "/mute 60" 명령 결과물)
    """
    if not os.path.exists(KILL_SWITCH_PATH):
        return False
    try:
        with open(KILL_SWITCH_PATH, "r", encoding="utf-8") as f:
            expire_str = f.read().strip()
    except Exception:
        return True  # 읽기 실패 시 안전하게 활성 유지

    if not expire_str:
        return True  # 빈 파일 = 무제한

    try:
        expire = datetime.datetime.fromisoformat(expire_str)
    except Exception:
        return True  # 파싱 실패 시 안전하게 활성

    now = datetime.datetime.now(KST) if expire.tzinfo else datetime.datetime.now()
    if now < expire:
        return True

    # 만료 → 자동 삭제
    try:
        os.remove(KILL_SWITCH_PATH)
    except Exception:
        pass
    return False


def activate_kill_switch(minutes: int = None):
    """KILL_SWITCH 활성화.

    Args:
        minutes: N분 후 자동 해제. None이면 무제한 (다음 수동 삭제까지).
    """
    os.makedirs(ISSUE_BOT_DIR, exist_ok=True)
    if minutes is None:
        content = ""
    else:
        expire = datetime.datetime.now(KST) + datetime.timedelta(minutes=minutes)
        content = expire.isoformat(timespec="seconds")
    with open(KILL_SWITCH_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def deactivate_kill_switch():
    """KILL_SWITCH 수동 해제."""
    try:
        if os.path.exists(KILL_SWITCH_PATH):
            os.remove(KILL_SWITCH_PATH)
    except Exception:
        pass


def is_issue_bot_blocked():
    """이슈봇 전체 중단 여부 (KILL_SWITCH 또는 보호 구간)"""
    if is_kill_switch_active():
        return True, "KILL_SWITCH 파일 존재"
    if is_protected_time():
        return True, "기존 브리핑 보호 구간"
    return False, None


# === Poller 단일 인스턴스 락 ===

def acquire_poller_lock():
    """
    Poller 프로세스 단일 실행 보장.
    Returns True: 락 획득, 안전하게 poller 실행 가능.
    Returns False: 이미 다른 poller 실행 중.
    """
    os.makedirs(ISSUE_BOT_DIR, exist_ok=True)
    if os.path.exists(POLLER_LOCK_PATH):
        try:
            with open(POLLER_LOCK_PATH, "r") as f:
                data = f.read().strip()
            parts = data.split(":")
            old_ts = float(parts[1]) if len(parts) > 1 else 0
            age = time.time() - old_ts
            if age <= POLLER_LOCK_STALE_S:
                print(f"[POLLER] 이미 다른 poller 실행 중 (lock age {age:.0f}s) — 실행 포기")
                return False
            else:
                print(f"[POLLER] stale lock 감지 (age {age:.0f}s) — 강제 해제 후 획득")
                os.remove(POLLER_LOCK_PATH)
        except Exception:
            try:
                os.remove(POLLER_LOCK_PATH)
            except Exception:
                pass

    try:
        with open(POLLER_LOCK_PATH, "w") as f:
            f.write(f"{os.getpid()}:{time.time()}")
        return True
    except Exception as e:
        print(f"[POLLER] 락 획득 실패: {e}")
        return False


def refresh_poller_lock():
    """Poller 루프 매 iteration마다 락 타임스탬프 갱신 (stale 판정 방지)"""
    try:
        with open(POLLER_LOCK_PATH, "w") as f:
            f.write(f"{os.getpid()}:{time.time()}")
    except Exception:
        pass


def release_poller_lock():
    """Poller 정상 종료 시 락 제거"""
    try:
        if os.path.exists(POLLER_LOCK_PATH):
            os.remove(POLLER_LOCK_PATH)
    except Exception:
        pass


# === 텔레그램 API 호출 ===

def _api_call(method, payload, max_retry=3):
    """Bot API POST 호출 (재시도 포함)"""
    url = f"{API_BASE}/{method}"
    retry_delays = [3, 8, 20]
    for attempt in range(max_retry):
        try:
            res = requests.post(url, json=payload, timeout=30)
            data = res.json()
            if data.get("ok"):
                return data
            desc = data.get("description", "")
            # Markdown/HTML 파싱 실패 시 parse_mode 제거 후 재시도
            if "parse" in desc.lower() and payload.get("parse_mode"):
                payload = {**payload, "parse_mode": None}
                continue
            # Chat not found / blocked 등은 재시도 무의미
            if "chat not found" in desc.lower() or "blocked" in desc.lower():
                return data
        except Exception as e:
            print(f"[TELEGRAM] API 호출 오류 (시도 {attempt+1}): {e}")
        if attempt < max_retry - 1:
            time.sleep(retry_delays[attempt])
    return {"ok": False, "description": "max retry exceeded"}


def send_channel_message(text, parse_mode="HTML", disable_preview=True):
    """@noderesearch 채널로 발송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("[ISSUE_BOT] 채널 환경변수 누락")
        return None
    return _api_call("sendMessage", {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    })


def send_channel_photo(photo_url, caption, parse_mode="HTML"):
    """@noderesearch 채널로 사진 + 캡션 발송. 캡션 1024자 초과 시 사진 + 텍스트 분할."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return None

    if caption and len(caption) > 1024:
        # 1단계: 사진만
        _api_call("sendPhoto", {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "photo": photo_url,
        })
        # 2단계: 본문은 텍스트로
        return _api_call("sendMessage", {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": caption,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })

    return _api_call("sendPhoto", {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "photo": photo_url,
        "caption": caption or "",
        "parse_mode": parse_mode,
    })


def send_admin_dm(text, reply_markup=None, parse_mode="HTML",
                  reply_to_message_id=None, force_reply=False):
    """관리자 개인 DM으로 발송 (승인 카드 등)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        print("[ISSUE_BOT] 관리자 DM 환경변수 누락")
        return None
    payload = {
        "chat_id": int(TELEGRAM_ADMIN_CHAT_ID),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if force_reply:
        payload["reply_markup"] = {
            "force_reply": True,
            "selective": True,
        }
    return _api_call("sendMessage", payload)


def send_admin_dm_photo(photo_url, caption, reply_markup=None, parse_mode="HTML"):
    """관리자 DM에 사진 + 캡션 + 버튼. 캡션 1024자 초과 시 사진+텍스트 분할."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return None

    if caption and len(caption) > 1024:
        # 1단계: 사진 (버튼 없음)
        _api_call("sendPhoto", {
            "chat_id": int(TELEGRAM_ADMIN_CHAT_ID),
            "photo": photo_url,
        })
        # 2단계: 텍스트 카드 (버튼 포함)
        payload = {
            "chat_id": int(TELEGRAM_ADMIN_CHAT_ID),
            "text": caption,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return _api_call("sendMessage", payload)

    payload = {
        "chat_id": int(TELEGRAM_ADMIN_CHAT_ID),
        "photo": photo_url,
        "caption": caption or "",
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _api_call("sendPhoto", payload)


def extract_og_image(url: str) -> str:
    """URL 페이지에서 og:image 또는 twitter:image 추출. 없으면 빈 문자열."""
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "lxml")
        for selector in [
            ("meta", {"property": "og:image"}),
            ("meta", {"property": "og:image:url"}),
            ("meta", {"name": "twitter:image"}),
            ("meta", {"name": "twitter:image:src"}),
        ]:
            tag = soup.find(selector[0], selector[1])
            if tag:
                content = tag.get("content") or tag.get("value")
                if content:
                    # 상대 URL은 절대화
                    if content.startswith("//"):
                        content = "https:" + content
                    elif content.startswith("/"):
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        content = f"{parsed.scheme}://{parsed.netloc}{content}"
                    return content
    except Exception as e:
        print(f"[TELEGRAM] og:image 추출 실패 ({url}): {e}")
    return ""


def edit_admin_message(message_id, text=None, reply_markup=None, parse_mode="HTML"):
    """관리자에게 보낸 메시지 수정 (버튼 업데이트 등)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return None
    payload = {
        "chat_id": int(TELEGRAM_ADMIN_CHAT_ID),
        "message_id": message_id,
    }
    if text is not None:
        payload["text"] = text
        payload["parse_mode"] = parse_mode
        payload["disable_web_page_preview"] = True
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    method = "editMessageText" if text is not None else "editMessageReplyMarkup"
    return _api_call(method, payload)


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    """콜백 버튼 클릭에 응답 (로딩 상태 해제)"""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    return _api_call("answerCallbackQuery", payload)


def get_updates(offset=None, timeout=25, allowed_updates=None):
    """롱폴링으로 업데이트 수신 (콜백 쿼리 + 답장 메시지)"""
    payload = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset
    if allowed_updates:
        payload["allowed_updates"] = allowed_updates
    else:
        payload["allowed_updates"] = ["message", "callback_query"]
    try:
        res = requests.post(f"{API_BASE}/getUpdates", json=payload, timeout=timeout + 5)
        data = res.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print(f"[TELEGRAM] getUpdates 오류: {e}")
    return []


# === 인라인 키보드 헬퍼 ===

def approval_keyboard_raw(issue_id):
    """State 1 (원문 카드): 아직 Sonnet 생성 전.
    [미리보기] [바로 발송] / [수정] [스킵] — 2행"""
    return {
        "inline_keyboard": [
            [
                {"text": "👁 미리보기", "callback_data": f"preview:{issue_id}"},
                {"text": "✅ 바로 발송", "callback_data": f"approve_direct:{issue_id}"},
            ],
            [
                {"text": "✏️ 수정", "callback_data": f"edit:{issue_id}"},
                {"text": "❌ 스킵", "callback_data": f"reject:{issue_id}"},
            ],
        ]
    }


def approval_keyboard_preview(issue_id):
    """State 2 (프리뷰 카드): 생성 완료, 본문 확인 후 판단.
    [발송] [수정] [스킵] — 1행"""
    return {
        "inline_keyboard": [[
            {"text": "✅ 발송", "callback_data": f"approve:{issue_id}"},
            {"text": "✏️ 수정", "callback_data": f"edit:{issue_id}"},
            {"text": "❌ 스킵", "callback_data": f"reject:{issue_id}"},
        ]]
    }


# 하위 호환 alias
approval_keyboard = approval_keyboard_preview


def batch_keyboard_by_priority(counts_by_pri: dict) -> dict:
    """우선순위별 일괄 승인/스킵 버튼.

    Args:
        counts_by_pri: {"URGENT": 2, "HIGH": 5, "NORMAL": 10}

    Layout:
        [URGENT 2 승인] [URGENT 2 스킵]
        [HIGH   5 승인] [HIGH   5 스킵]
        [NORMAL 10 승인][NORMAL 10 스킵]
        [🗑️ 전체 스킵]
    """
    rows = []
    for pri in ["URGENT", "HIGH", "NORMAL"]:
        cnt = counts_by_pri.get(pri, 0)
        if cnt:
            rows.append([
                {"text": f"✅ {pri} {cnt}건 승인", "callback_data": f"batch_approve:{pri}"},
                {"text": f"❌ {pri} {cnt}건 스킵", "callback_data": f"batch_reject:{pri}"},
            ])
    total = sum(counts_by_pri.values())
    if total:
        rows.append([
            {"text": f"🗑️ 전체 {total}건 스킵", "callback_data": "batch_reject:ALL"},
        ])
    return {"inline_keyboard": rows}


# 레거시 alias
batch_approval_keyboard = batch_keyboard_by_priority
