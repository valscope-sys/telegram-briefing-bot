"""롱폴링 루프 — 콜백 버튼 + 수정 답장 수신

실행 구조:
- main.py가 threading.Thread로 run_poller()를 백그라운드 실행
- getUpdates(long_poll=25s)로 업데이트 수신
- callback_query → 해당 액션(preview/approve/reject/edit/approve_direct)
- message(reply) → edit 답장 매칭 → 수정본 발송
- offset 관리로 중복 방지
"""
import os
import json
import time
import datetime
import traceback
import pytz

from telegram_bot.issue_bot.utils.telegram import (
    get_updates,
    answer_callback_query,
    send_admin_dm,
    edit_admin_message,
    is_issue_bot_blocked,
    acquire_poller_lock,
    refresh_poller_lock,
    release_poller_lock,
    batch_keyboard_by_priority,
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)
from telegram_bot.issue_bot.approval.bot import (
    load_pending,
    save_pending,
    mark_decision,
    generate_preview_for_issue,
    send_to_channel,
    approve_and_send,
    reject_issue,
    format_preview_card,
    approve_batch_by_priority,
    reject_batch_by_priority,
    get_pending_summary,
)
from telegram_bot.issue_bot.pipeline.linter import lint_r1_r8

KST = pytz.timezone("Asia/Seoul")

OFFSET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history", "issue_bot", "poller_offset.txt",
)


# ===== offset 관리 =====

def _load_offset():
    try:
        with open(OFFSET_PATH, "r") as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0


def _save_offset(offset):
    os.makedirs(os.path.dirname(OFFSET_PATH), exist_ok=True)
    with open(OFFSET_PATH, "w") as f:
        f.write(str(offset))


# ===== 콜백 처리 =====

_SENT_MARKER_KB = {"inline_keyboard": [[{"text": "✅ 발송됨", "callback_data": "noop"}]]}
_REJECTED_MARKER_KB = {"inline_keyboard": [[{"text": "❌ 스킵됨", "callback_data": "noop"}]]}
_EDIT_WAITING_KB = {"inline_keyboard": [[{"text": "✏️ 답장 대기중", "callback_data": "noop"}]]}


_processed_callbacks = {}  # callback_query id → 처리 시각 (중복 방지)
_CALLBACK_DEDUP_WINDOW_S = 300  # 5분


def _is_callback_duplicate(cb_id):
    """같은 콜백이 최근에 이미 처리됐는지 확인 (이중 배달 방지)"""
    now = time.time()
    # 오래된 엔트리 청소
    expired = [k for k, t in _processed_callbacks.items() if now - t > _CALLBACK_DEDUP_WINDOW_S]
    for k in expired:
        _processed_callbacks.pop(k, None)
    if cb_id in _processed_callbacks:
        return True
    _processed_callbacks[cb_id] = now
    return False


def _handle_callback(cb):
    """callback_query 처리"""
    cb_id = cb["id"]
    data = cb.get("data", "")
    action, _, issue_id = data.partition(":")

    if not action or action == "noop":
        answer_callback_query(cb_id)
        return

    # 중복 콜백 차단 (Telegram 이중 배달 또는 더블클릭)
    if _is_callback_duplicate(cb_id):
        answer_callback_query(cb_id)
        return

    issue = load_pending(issue_id)
    if not issue and action != "batch_approve":
        answer_callback_query(cb_id, text="이미 처리되었거나 만료됨", show_alert=True)
        return

    try:
        if action == "preview":
            answer_callback_query(cb_id, text="프리뷰 생성 중...")
            result = generate_preview_for_issue(issue_id)
            if not result.get("ok"):
                send_admin_dm(f"⚠️ 프리뷰 생성 실패: {result.get('error')}")

        elif action == "approve":
            answer_callback_query(cb_id, text="채널로 발송 중...")
            result = approve_and_send(issue_id)
            if result.get("ok"):
                edit_admin_message(
                    issue["telegram_admin_msg_id"],
                    reply_markup=_SENT_MARKER_KB,
                )
            else:
                send_admin_dm(f"⚠️ 발송 실패: {result.get('error')}")

        elif action == "approve_direct":
            answer_callback_query(cb_id, text="생성 + 발송 중...")
            result = approve_and_send(issue_id)
            if result.get("ok"):
                edit_admin_message(
                    issue["telegram_admin_msg_id"],
                    reply_markup=_SENT_MARKER_KB,
                )
            else:
                send_admin_dm(f"⚠️ 발송 실패: {result.get('error')}")

        elif action == "reject":
            answer_callback_query(cb_id, text="스킵됨")
            reject_issue(issue_id)

        elif action == "edit":
            answer_callback_query(cb_id, text="수정 모드 진입...")
            _start_edit_flow(issue_id)

        elif action == "batch_approve":
            # issue_id 자리에 priority_filter (URGENT/HIGH/NORMAL/ALL)
            priority_filter = issue_id
            answer_callback_query(cb_id, text=f"{priority_filter} 일괄 발송 중...")
            res = approve_batch_by_priority(priority_filter)
            send_admin_dm(
                f"📦 일괄 승인 완료 ({priority_filter})\n"
                f"• 대상: {res['total']}건\n"
                f"• 발송: {res['sent']}건\n"
                f"• 실패: {res['failed']}건"
            )

        elif action == "batch_reject":
            priority_filter = issue_id
            answer_callback_query(cb_id, text=f"{priority_filter} 일괄 스킵 중...")
            res = reject_batch_by_priority(priority_filter)
            send_admin_dm(
                f"🗑️ 일괄 스킵 완료 ({priority_filter})\n"
                f"• 대상: {res['total']}건\n"
                f"• 스킵: {res['rejected']}건"
            )

        else:
            answer_callback_query(cb_id, text=f"알 수 없는 액션: {action}")
    except Exception as e:
        print(f"[POLLER] 콜백 처리 오류 ({action}:{issue_id}): {e}")
        traceback.print_exc()
        answer_callback_query(cb_id, text=f"오류 발생: {e}", show_alert=True)


# ===== 커맨드 처리 (/queue /mute /stop /resume) =====

def _handle_command(msg: dict):
    """DM 텍스트 메시지 중 '/'로 시작하는 것 처리."""
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return False

    parts = text.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/queue", "/q", "/status"):
        _cmd_queue()
    elif cmd in ("/mute", "/pause"):
        _cmd_mute(args)
    elif cmd == "/stop":
        _cmd_stop()
    elif cmd in ("/resume", "/start_again"):
        _cmd_resume()
    elif cmd in ("/help", "/h"):
        _cmd_help()
    else:
        return False

    return True


def _cmd_queue():
    """/queue — 대기 카드 요약 + 일괄 승인/스킵 버튼"""
    summary = get_pending_summary()
    total = summary["total"]
    counts = summary["counts"]

    if total == 0:
        send_admin_dm("📭 대기 카드 없음")
        return

    lines = [f"📋 <b>대기 카드 요약</b> — 총 {total}건\n"]
    for pri in ["URGENT", "HIGH", "NORMAL"]:
        cnt = counts.get(pri, 0)
        if cnt:
            lines.append(f"• {pri}: {cnt}건")
    lines.append("")
    lines.append("<i>아래 버튼으로 우선순위별 일괄 처리 가능.</i>")

    kb = batch_keyboard_by_priority(counts)
    send_admin_dm("\n".join(lines), reply_markup=kb, parse_mode="HTML")


def _cmd_mute(args: list):
    """/mute [분] — N분간 알림 중지 (기본 60분)"""
    minutes = 60
    if args:
        try:
            minutes = max(1, min(int(args[0]), 1440))  # 1분 ~ 24시간
        except ValueError:
            send_admin_dm("⚠️ 사용법: /mute [분] (예: /mute 120)")
            return
    activate_kill_switch(minutes=minutes)
    send_admin_dm(
        f"🔕 이슈봇 <b>{minutes}분 중지</b>\n"
        f"대기 중 공시/뉴스 수집 및 카드 발송을 멈춥니다.\n"
        f"해제: /resume",
        parse_mode="HTML",
    )


def _cmd_stop():
    """/stop — 오늘 하루(KST 자정까지) 중지"""
    now = datetime.datetime.now(KST)
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = max(1, int((midnight - now).total_seconds() // 60))
    activate_kill_switch(minutes=minutes)
    send_admin_dm(
        f"🛑 이슈봇 <b>오늘 자정까지 중지</b> ({minutes}분)\n"
        f"해제: /resume",
        parse_mode="HTML",
    )


def _cmd_resume():
    """/resume — 즉시 재개"""
    deactivate_kill_switch()
    send_admin_dm("✅ 이슈봇 <b>재개</b>. 다음 폴링부터 정상 수집.", parse_mode="HTML")


def _cmd_help():
    """/help — 명령어 안내"""
    text = (
        "<b>이슈봇 관리 명령</b>\n\n"
        "• /queue — 대기 카드 요약 + 일괄 승인/스킵\n"
        "• /mute [분] — N분간 중지 (기본 60분, 최대 1440)\n"
        "• /stop — 오늘 자정까지 중지\n"
        "• /resume — 즉시 재개\n"
        "• /help — 이 메시지"
    )
    send_admin_dm(text, parse_mode="HTML")


def _start_edit_flow(issue_id: str):
    """수정 플로우 시작: 생성 없으면 먼저 생성 → force_reply DM"""
    from telegram_bot.config import ISSUE_BOT_EDIT_TIMEOUT_MIN

    issue = load_pending(issue_id)
    if not issue:
        return

    # 아직 생성 전이면 먼저 생성
    if not issue.get("has_generated"):
        gen_res = generate_preview_for_issue(issue_id)
        if not gen_res.get("ok"):
            send_admin_dm(f"⚠️ 수정 전 생성 실패: {gen_res.get('error')}")
            return
        issue = load_pending(issue_id)

    # 기존 카드 버튼을 "답장 대기중"으로 변경
    edit_admin_message(issue["telegram_admin_msg_id"], reply_markup=_EDIT_WAITING_KB)

    # force_reply 안내 메시지 (issue_id를 숨긴 마커로 포함)
    guide = (
        f"✏️ <b>[{issue_id}] 수정본 요청</b>\n\n"
        f"이 메시지에 <b>답장(reply)</b>으로 수정본 전체를 보내주세요.\n"
        f"제한 시간: {ISSUE_BOT_EDIT_TIMEOUT_MIN}분\n"
        f"취소하려면 답장 없이 기다리세요."
    )
    res = send_admin_dm(guide, force_reply=True, parse_mode="HTML")
    if res and res.get("ok"):
        issue["edit_guide_msg_id"] = res["result"]["message_id"]
        issue["edit_requested_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
        issue["status"] = "pending_edit"
        save_pending(issue)


def _handle_edit_reply(msg):
    """수정 답장 처리"""
    reply_to = msg.get("reply_to_message", {})
    reply_text = reply_to.get("text", "")
    reply_to_msg_id = reply_to.get("message_id")

    if not reply_to_msg_id or "수정본 요청" not in reply_text:
        return

    # edit_guide_msg_id가 이 답장 대상인 pending 찾기
    from telegram_bot.issue_bot.approval.bot import list_pending, send_to_channel

    target = None
    for p in list_pending():
        if p.get("edit_guide_msg_id") == reply_to_msg_id:
            target = p
            break

    if not target:
        send_admin_dm("⚠️ 해당 수정 요청을 찾을 수 없음. 이미 만료되었거나 다른 세션입니다.")
        return

    new_content = msg.get("text", "").strip()
    if not new_content:
        send_admin_dm("⚠️ 수정본이 비어있음.")
        return

    # R8 린트
    violations = lint_r1_r8(new_content, target.get("category", "C"))
    if violations:
        v_summary = "; ".join(f"{v['rule']}" for v in violations[:5])
        send_admin_dm(
            f"⚠️ <b>수정본 R1~R8 위반 의심</b>: {v_summary}\n\n"
            f"그대로 발송하려면 /confirm_send, 재수정하려면 답장 다시.",
            parse_mode="HTML",
        )
        target["edit_pending_violations"] = violations
        target["edit_pending_content"] = new_content
        save_pending(target)
        return

    # 린트 통과 → 발송
    issue_id = target["id"]
    send_res = send_to_channel(issue_id, content_override=new_content)
    if send_res.get("ok"):
        mark_decision(issue_id, "edited", updated_content=new_content)
        send_admin_dm(f"✅ 수정본 발송 완료 (채널 msg_id: {send_res['channel_msg_id']})")
        edit_admin_message(target["telegram_admin_msg_id"], reply_markup=_SENT_MARKER_KB)
    else:
        send_admin_dm(f"⚠️ 발송 실패: {send_res.get('error')}")


# ===== 타임아웃 정리 =====

def check_timeouts():
    """만료된 pending을 timeout 처리. main 루프에서 주기적 호출."""
    from telegram_bot.issue_bot.approval.bot import list_pending, mark_decision
    now = datetime.datetime.now(KST)
    for p in list_pending():
        expires_at_str = p.get("expires_at")
        if not expires_at_str:
            continue
        try:
            expire = datetime.datetime.fromisoformat(expires_at_str)
        except Exception:
            continue
        if expire < now:
            # 타임아웃 처리
            print(f"[POLLER] 타임아웃: {p['id']}")
            try:
                edit_admin_message(
                    p["telegram_admin_msg_id"],
                    reply_markup={"inline_keyboard": [[{"text": "⏰ 타임아웃 스킵", "callback_data": "noop"}]]},
                )
            except Exception:
                pass
            mark_decision(p["id"], "timeout")


# ===== 메인 폴링 루프 =====

def run_poller(stop_event=None, interval_s: int = 2):
    """백그라운드 롱폴링. stop_event.is_set() 되면 종료.
    단일 인스턴스 락 획득 실패 시 즉시 반환 (중복 실행 방지)."""
    if not acquire_poller_lock():
        print("[POLLER] 락 획득 실패 — 다른 poller가 실행 중. 종료.")
        return

    offset = _load_offset()
    print(f"[POLLER] 시작 (offset={offset}, pid={os.getpid()})")

    try:
        while True:
            if stop_event and stop_event.is_set():
                print("[POLLER] stop_event 감지 — 종료")
                break

            # 락 타임스탬프 갱신 (stale 판정 방지)
            refresh_poller_lock()

            # KILL_SWITCH 체크
            blocked, reason = is_issue_bot_blocked()
            if blocked and "KILL_SWITCH" in (reason or ""):
                time.sleep(30)
                continue

            try:
                updates = get_updates(offset=offset if offset > 0 else None, timeout=25)
                for upd in updates:
                    offset = max(offset, upd["update_id"] + 1)
                    try:
                        if "callback_query" in upd:
                            _handle_callback(upd["callback_query"])
                        elif "message" in upd:
                            msg = upd["message"]
                            # 관리자 채팅만 처리 (보안)
                            from telegram_bot.config import TELEGRAM_ADMIN_CHAT_ID
                            if TELEGRAM_ADMIN_CHAT_ID and str(msg.get("chat", {}).get("id", "")) != str(TELEGRAM_ADMIN_CHAT_ID):
                                continue
                            if "reply_to_message" in msg:
                                _handle_edit_reply(msg)
                            elif (msg.get("text") or "").startswith("/"):
                                _handle_command(msg)
                    except Exception as e:
                        print(f"[POLLER] 업데이트 처리 오류: {e}")
                        traceback.print_exc()
                _save_offset(offset)
            except Exception as e:
                print(f"[POLLER] getUpdates 오류: {e}")
                time.sleep(interval_s)
                continue

            # 타임아웃 정리
            try:
                check_timeouts()
            except Exception as e:
                print(f"[POLLER] 타임아웃 체크 오류: {e}")

            time.sleep(interval_s)
    finally:
        release_poller_lock()
        print("[POLLER] 종료 (락 해제 완료)")


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("Poller 테스트 실행 — Ctrl+C로 중단")
    run_poller()
