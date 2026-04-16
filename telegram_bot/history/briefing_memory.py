"""이전 브리핑 저장/조회 — 시황 연속성을 위한 기억 모듈"""
import json
import os
import datetime

HISTORY_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_path(briefing_type):
    return os.path.join(HISTORY_DIR, f"latest_{briefing_type}.json")


def save_briefing(briefing_type, commentary, key_data=None):
    """
    시황 텍스트 + 핵심 데이터를 저장
    - briefing_type: "morning" or "evening"
    - commentary: 시황 해석 텍스트
    - key_data: 핵심 수치 dict (선택)
    """
    data = {
        "date": datetime.date.today().strftime("%Y-%m-%d"),
        "timestamp": datetime.datetime.now().isoformat(),
        "commentary": commentary,
        "key_data": key_data or {},
    }
    try:
        with open(_get_path(briefing_type), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_previous_briefing(briefing_type):
    """
    이전 시황 텍스트 조회
    - 반환: {"date": "2026-04-06", "commentary": "...", "key_data": {...}}
    - 없으면 None
    """
    path = _get_path(briefing_type)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 오늘 날짜와 같으면 이전 게 아님 (이미 오늘 저장된 것)
        # 오늘과 다르면 이전 브리핑
        return data
    except Exception:
        return None


def save_snapshot(briefing_type, messages):
    """
    발송된 메시지 전체를 스냅샷으로 저장 (재발송용)
    - briefing_type: "morning" or "evening"
    - messages: [msg1, msg2, msg3, msg4] 텍스트 리스트
    """
    today = datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join(HISTORY_DIR, f"snapshot_{briefing_type}_{today}.json")
    data = {
        "date": today,
        "timestamp": datetime.datetime.now().isoformat(),
        "briefing_type": briefing_type,
        "messages": messages,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SNAPSHOT] {briefing_type} 스냅샷 저장: {path}")
    except Exception as e:
        print(f"[SNAPSHOT] 저장 실패: {e}")


def load_snapshot(briefing_type, date_str=None):
    """
    저장된 스냅샷 로드 (재발송용)
    - date_str: "2026-04-16" 형식. None이면 오늘 날짜.
    - 반환: {"date", "timestamp", "messages": [...]} or None
    """
    if not date_str:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join(HISTORY_DIR, f"snapshot_{briefing_type}_{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def format_previous_for_prompt(briefing_type):
    """이전 시황을 프롬프트 삽입용 텍스트로 변환"""
    prev = load_previous_briefing(briefing_type)
    if not prev or not prev.get("commentary"):
        return ""

    date = prev.get("date", "")
    commentary = prev.get("commentary", "")
    key_data = prev.get("key_data", {})

    lines = [f"=== 이전 시황 ({date}) ==="]
    lines.append(commentary[:500])  # 최대 500자만

    if key_data:
        lines.append("\n이전 핵심 수치:")
        for k, v in list(key_data.items())[:5]:
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)
