"""텔레그램 메시지 발송 모듈"""
import requests
from telegram_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID


def send_message(text, parse_mode="Markdown"):
    """
    텔레그램 채널에 메시지 발송

    Args:
        text: 발송할 메시지 (Markdown 지원)
        parse_mode: "Markdown" 또는 "HTML"
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print(f"[TELEGRAM] 봇 토큰 또는 채널 ID가 설정되지 않았습니다.")
        print(f"[TELEGRAM] 메시지 미리보기:\n{text}")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        result = res.json()
        if result.get("ok"):
            print(f"[TELEGRAM] 메시지 발송 성공")
            return result
        else:
            print(f"[TELEGRAM] 발송 실패: {result.get('description', '')}")
            # Markdown 파싱 실패 시 일반 텍스트로 재시도
            if "parse" in result.get("description", "").lower():
                payload["parse_mode"] = None
                res = requests.post(url, json=payload, timeout=10)
                return res.json()
            return result
    except Exception as e:
        print(f"[TELEGRAM] 발송 오류: {e}")
        return None


def send_messages_sequential(messages, delay=2):
    """
    여러 메시지를 순차 발송 (간격 유지)

    Args:
        messages: 메시지 리스트
        delay: 메시지 간 대기 시간 (초)
    """
    import time
    results = []
    for msg in messages:
        result = send_message(msg)
        results.append(result)
        if delay > 0 and msg != messages[-1]:
            time.sleep(delay)
    return results
