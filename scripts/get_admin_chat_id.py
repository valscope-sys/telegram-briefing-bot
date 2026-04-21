"""관리자 chat_id 취득 스크립트 (Phase 0)

사용법:
1. 텔레그램에서 @noderesearch_bot 검색 → /start 전송
2. 이 스크립트 실행: python scripts/get_admin_chat_id.py
3. 출력된 chat_id를 .env의 TELEGRAM_ADMIN_CHAT_ID에 기록

봇 DM을 보내려면 사용자가 먼저 /start 해야 텔레그램이 봇에게 권한을 부여합니다.
"""
import os
import sys
import requests
from dotenv import load_dotenv

# Windows cp949 콘솔 한글/이모지 호환
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_env_path)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

if not TOKEN:
    print("[ERROR] .env에 TELEGRAM_BOT_TOKEN이 없습니다.")
    sys.exit(1)


def get_updates():
    """getUpdates로 봇이 받은 최근 메시지에서 chat_id 추출"""
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
    except Exception as e:
        print(f"[ERROR] API 호출 실패: {e}")
        sys.exit(1)

    if not data.get("ok"):
        print(f"[ERROR] API 오류: {data.get('description')}")
        sys.exit(1)

    return data.get("result", [])


def main():
    updates = get_updates()

    if not updates:
        print("=" * 60)
        print("⚠️  아직 봇이 받은 메시지가 없습니다.")
        print("=" * 60)
        print()
        print("다음 단계를 먼저 수행하세요:")
        print("1. 텔레그램에서 @noderesearch_bot 검색")
        print("2. 봇 채팅창 열고 '/start' 전송")
        print("3. 이 스크립트 다시 실행")
        print()
        return

    private_chats = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat", {})
        if chat.get("type") == "private":
            chat_id = chat.get("id")
            username = chat.get("username", "(no username)")
            first_name = chat.get("first_name", "")
            last_name = chat.get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()
            private_chats[chat_id] = {"username": username, "name": full_name}

    if not private_chats:
        print("=" * 60)
        print("⚠️  개인(private) 채팅 기록이 없습니다.")
        print("=" * 60)
        print()
        print("채널/그룹이 아닌 봇과의 1:1 개인 채팅에서 /start를 보내야 합니다.")
        print("텔레그램 → @noderesearch_bot 검색 → /start 전송 후 재실행")
        return

    print("=" * 60)
    print("✅ 감지된 개인 채팅:")
    print("=" * 60)
    print()
    for chat_id, info in private_chats.items():
        print(f"  chat_id: {chat_id}")
        print(f"  username: @{info['username']}")
        print(f"  name: {info['name']}")
        print()

    print("=" * 60)
    print("다음 단계:")
    print("=" * 60)
    print()
    print(".env 파일에 아래 줄 추가:")
    print()
    for chat_id in private_chats:
        print(f"  TELEGRAM_ADMIN_CHAT_ID={chat_id}")
        break  # 보통 1개만 필요
    print()


if __name__ == "__main__":
    main()
