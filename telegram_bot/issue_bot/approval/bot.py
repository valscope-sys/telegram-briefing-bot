"""승인 카드 발송 (하이브리드: 원문 → 미리보기 → 발송)

Flow:
1. [State 1 RAW] 원문 발췌 + 메타 카드 → 관리자 DM (생성 비용 $0)
   버튼: [👁 미리보기] [✅ 바로 발송] [✏️ 수정] [❌ 스킵]

2. [State 2 PREVIEW] 관리자가 미리보기 클릭 → Sonnet 생성 → 카드 업데이트
   버튼: [✅ 발송] [✏️ 수정] [❌ 스킵]

3. 바로 발송 / 수정 클릭 시에도 생성 발생 (lazy generation).

비용 절감:
- 거절 시: 생성 비용 $0
- 바로 발송: 생성 1회만
- 미리보기 → 발송: 생성 1회 (프리뷰 후 버튼 연계)
"""
import os
import json
import datetime
import html
import pytz

from telegram_bot.config import (
    ISSUE_BOT_URGENT_TIMEOUT_MIN,
    ISSUE_BOT_HIGH_TIMEOUT_MIN,
    ISSUE_BOT_NORMAL_TIMEOUT_MIN,
)
from telegram_bot.issue_bot.utils.telegram import (
    send_admin_dm,
    send_admin_dm_photo,
    edit_admin_message,
    approval_keyboard_raw,
    approval_keyboard_preview,
    send_channel_message,
    send_channel_photo,
    extract_og_image,
)

KST = pytz.timezone("Asia/Seoul")

PENDING_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history", "issue_bot", "pending",
)

PRIORITY_EMOJI = {"URGENT": "🔴", "HIGH": "🟡", "NORMAL": "🟢"}
TIMEOUT_MIN = {
    "URGENT": ISSUE_BOT_URGENT_TIMEOUT_MIN,
    "HIGH": ISSUE_BOT_HIGH_TIMEOUT_MIN,
    "NORMAL": ISSUE_BOT_NORMAL_TIMEOUT_MIN,
}
MAX_CARD_LEN = 3500


def _escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def _card_header(issue: dict) -> str:
    priority = issue.get("priority", "NORMAL")
    emoji = PRIORITY_EMOJI.get(priority, "⚪")
    sector = issue.get("sector", "기타")
    category = issue.get("category", "C")
    return f'{emoji} <b>{priority}</b> | {sector} | Template {category}'


def _card_meta_tail(issue: dict) -> str:
    """카드 하단 메타 영역. Peer는 '영향 해석 대상'으로 표기.

    Peer는 단순 나열이 아니라 "이 이벤트가 한국 종목에 미칠 영향 해석용 재료".
    본문 생성 시 Sonnet이 영향 방향·근거까지 본문에 녹임.
    """
    timeout_min = TIMEOUT_MIN.get(issue.get("priority", "NORMAL"), 60)
    peers = issue.get("peer_map_used", [])
    peer_conf = issue.get("peer_confidence")

    peer_line = ""
    if peers:
        peer_line = f"📊 <i>영향 해석 대상</i>: {', '.join(peers)}"
        if peer_conf is not None:
            peer_line += f" <i>(conf {peer_conf:.2f})</i>"
        peer_line += "\n"

    violations = issue.get("violations", [])
    v_line = ""
    if violations:
        vs = "; ".join(f"{v['rule']}" for v in violations[:3])
        v_line = f"⚠️ <b>R1~R8 위반 경고</b>: {vs}\n"

    from telegram_bot.config import ISSUE_BOT_AUTO_TIMEOUT

    if ISSUE_BOT_AUTO_TIMEOUT:
        expires_at = issue.get("expires_at", "")
        try:
            dt = datetime.datetime.fromisoformat(expires_at) if expires_at else None
            expires_str = dt.strftime("%H:%M") if dt else "?"
        except Exception:
            expires_str = "?"
        timeout_line = f'⏰ 만료: {expires_str} ({timeout_min}분)'
    else:
        timeout_line = '⏳ <i>수동 처리 전까지 유지</i>'

    return (
        f'\n━━━━━━━━━━━━━━━━━━━━━\n'
        f'{peer_line}'
        f'{v_line}'
        f'{timeout_line}'
    )


def format_raw_card(issue: dict) -> str:
    """State 1: 원문 발췌 카드 (생성 전)"""
    header = _card_header(issue)
    source_url = issue.get("source_url", "")
    source_link = f'<a href="{_escape(source_url)}">원본</a>' if source_url else "원본 없음"

    company = issue.get("company_name", "")
    title = issue.get("title", "")
    excerpt = issue.get("original_excerpt", "")[:500]

    body_block = (
        f'<b>{_escape(company)}</b>\n'
        f'{_escape(title)}\n\n'
        f'<i>[원문 발췌]</i>\n'
        f'{_escape(excerpt)}\n\n'
        f'<i>💡 요약본 생성은 아직 안됨. 미리보기로 생성 or 바로 발송으로 생성+발송</i>'
    )

    meta_tail = _card_meta_tail(issue)

    return (
        f'{header}\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'📰 {source_link}\n\n'
        f'{body_block}\n'
        f'{meta_tail}'
    )


def format_preview_card(issue: dict) -> str:
    """State 2: 생성본 프리뷰 카드 (발송될 본문 그대로)"""
    header = _card_header(issue) + " | <i>프리뷰됨</i>"
    source_url = issue.get("source_url", "")
    source_link = f'<a href="{_escape(source_url)}">원본</a>' if source_url else "원본 없음"

    generated = issue.get("generated_content", "")
    meta_tail = _card_meta_tail(issue)

    return (
        f'{header}\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'📰 {source_link}\n\n'
        f'{_escape(generated)}\n'
        f'{meta_tail}'
    )


# ===== Pending 저장소 =====

def _ensure_pending_dir():
    os.makedirs(PENDING_DIR, exist_ok=True)


def save_pending(issue: dict):
    _ensure_pending_dir()
    with open(os.path.join(PENDING_DIR, f"{issue['id']}.json"), "w", encoding="utf-8") as f:
        json.dump(issue, f, ensure_ascii=False, indent=2)


def load_pending(issue_id: str):
    path = os.path.join(PENDING_DIR, f"{issue_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def remove_pending(issue_id: str):
    path = os.path.join(PENDING_DIR, f"{issue_id}.json")
    if os.path.exists(path):
        os.remove(path)


def list_pending() -> list:
    _ensure_pending_dir()
    out = []
    for fn in os.listdir(PENDING_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(PENDING_DIR, fn), "r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except Exception:
                continue
    return out


# ===== 카드 발송 =====

def send_raw_approval_card(issue: dict) -> dict:
    """
    State 1 (원문 발췌) 카드 발송.
    issue 필수: id, priority, category, sector, source_url,
              original_content, original_excerpt, company_name, title
    """
    priority = issue.get("priority", "NORMAL")
    if not issue.get("expires_at"):
        timeout_min = TIMEOUT_MIN.get(priority, 60)
        expire = datetime.datetime.now(KST) + datetime.timedelta(minutes=timeout_min)
        issue["expires_at"] = expire.isoformat(timespec="seconds")

    issue["has_generated"] = issue.get("has_generated", False)
    issue.setdefault("generated_content", None)
    issue.setdefault("peer_map_used", [])
    issue.setdefault("violations", [])

    card_text = format_raw_card(issue)
    if len(card_text) > MAX_CARD_LEN:
        # 원문 발췌를 더 짧게
        issue["original_excerpt"] = (issue.get("original_excerpt") or "")[:300]
        card_text = format_raw_card(issue)

    keyboard = approval_keyboard_raw(issue["id"])

    # 이미지 자동 추출 (RSS 등 og:image). DART는 보통 없음.
    image_url = issue.get("image_url")
    if not image_url and issue.get("source") == "RSS":
        src_url = issue.get("source_url", "")
        if src_url:
            image_url = extract_og_image(src_url)
            if image_url:
                issue["image_url"] = image_url

    if image_url:
        res = send_admin_dm_photo(image_url, card_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        res = send_admin_dm(card_text, reply_markup=keyboard, parse_mode="HTML")

    if not res or not res.get("ok"):
        return {"ok": False, "error": res.get("description", "unknown") if res else "no response"}

    issue["status"] = "pending_raw"
    issue["telegram_admin_msg_id"] = res["result"]["message_id"]
    issue["sent_to_admin_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
    save_pending(issue)

    return {
        "ok": True,
        "admin_msg_id": issue["telegram_admin_msg_id"],
        "expires_at": issue["expires_at"],
        "status": "pending_raw",
    }


def update_to_preview_card(issue_id: str, generated_content: str, violations: list = None,
                           tokens_used: dict = None, peer_map_used: list = None,
                           peer_confidence: float = None) -> dict:
    """State 1 → State 2 전환: 생성된 본문으로 카드 교체."""
    issue = load_pending(issue_id)
    if not issue:
        return {"ok": False, "error": "pending not found"}

    issue["generated_content"] = generated_content
    issue["violations"] = violations or []
    issue["has_generated"] = True
    issue["status"] = "pending_preview"
    if tokens_used:
        issue.setdefault("tokens_used", {}).update(tokens_used)
    if peer_map_used is not None:
        issue["peer_map_used"] = peer_map_used
    if peer_confidence is not None:
        issue["peer_confidence"] = peer_confidence

    card_text = format_preview_card(issue)
    if len(card_text) > MAX_CARD_LEN:
        short = issue.get("generated_content", "")[:MAX_CARD_LEN - 300] + "\n... (본문 일부 생략)"
        issue_tmp = {**issue, "generated_content": short}
        card_text = format_preview_card(issue_tmp)

    keyboard = approval_keyboard_preview(issue_id)
    res = edit_admin_message(
        issue["telegram_admin_msg_id"],
        text=card_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    save_pending(issue)

    if not res or not res.get("ok"):
        return {"ok": False, "error": res.get("description", "edit failed") if res else "no response"}
    return {"ok": True, "status": "pending_preview"}


def send_to_channel(issue_id: str, content_override: str = None) -> dict:
    """최종 승인 후 @noderesearch 채널로 발송"""
    issue = load_pending(issue_id)
    if not issue:
        return {"ok": False, "error": "pending not found"}

    content = content_override or issue.get("generated_content") or ""
    if not content:
        return {"ok": False, "error": "no content to send"}

    # 이미지가 있으면 사진+캡션으로 발송
    image_url = issue.get("image_url")
    if image_url:
        res = send_channel_photo(image_url, content, parse_mode="HTML")
    else:
        res = send_channel_message(content, parse_mode="HTML")
    if not res or not res.get("ok"):
        return {"ok": False, "error": res.get("description", "send failed") if res else "no response"}

    issue["final_content"] = content
    issue["telegram_channel_msg_id"] = res["result"]["message_id"]
    issue["sent_to_channel_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
    save_pending(issue)

    return {
        "ok": True,
        "channel_msg_id": issue["telegram_channel_msg_id"],
    }


# ===== 고수준 액션 (poller + 테스트에서 공용) =====

def generate_preview_for_issue(issue_id: str) -> dict:
    """State 1 → State 2: Sonnet 생성 + 카드 업데이트"""
    from telegram_bot.issue_bot.pipeline.generator import generate_with_retry

    issue = load_pending(issue_id)
    if not issue:
        return {"ok": False, "error": "pending not found"}

    classification = {
        "priority": issue.get("priority"),
        "category": issue.get("category"),
        "sector": issue.get("sector"),
    }
    gen_result = generate_with_retry(issue, classification)

    return update_to_preview_card(
        issue_id,
        generated_content=gen_result["generated_content"],
        violations=gen_result["violations"],
        tokens_used=gen_result.get("tokens_used"),
    )


def _is_already_sent(issue_id: str) -> bool:
    """sent/*.jsonl에서 동일 id가 이미 발송 완료됐는지 조회 (멱등성 보장)"""
    import glob
    sent_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "history", "issue_bot", "sent",
    )
    if not os.path.isdir(sent_dir):
        return False
    for fp in glob.glob(os.path.join(sent_dir, "*.jsonl")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("id") == issue_id:
                            return True
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue
    return False


def approve_and_send(issue_id: str) -> dict:
    """
    State 1 or 2 → 채널 발송.
    State 1이면 먼저 생성(lazy) 후 발송.
    멱등성: 이미 sent에 있으면 에러 대신 {"ok": True, "already_sent": True} 반환.
    """
    issue = load_pending(issue_id)
    if not issue:
        if _is_already_sent(issue_id):
            return {"ok": True, "already_sent": True, "message": "이미 처리됨 (멱등)"}
        return {"ok": False, "error": "pending not found"}

    if not issue.get("has_generated"):
        gen_res = generate_preview_for_issue(issue_id)
        if not gen_res.get("ok"):
            return {"ok": False, "error": f"generate failed: {gen_res.get('error')}"}
        issue = load_pending(issue_id)

    send_res = send_to_channel(issue_id)
    if not send_res.get("ok"):
        return send_res

    mark_decision(issue_id, "sent")
    return send_res


def reject_issue(issue_id: str) -> dict:
    """즉시 스킵 처리"""
    issue = load_pending(issue_id)
    if not issue:
        return {"ok": False, "error": "pending not found"}
    mark_decision(issue_id, "rejected")
    # 관리자 DM 카드에 [❌ 스킵됨] 표시
    try:
        edit_admin_message(
            issue["telegram_admin_msg_id"],
            reply_markup={"inline_keyboard": [[{"text": "❌ 스킵됨", "callback_data": "noop"}]]},
        )
    except Exception:
        pass
    return {"ok": True, "status": "rejected"}


def approve_batch_by_priority(priority_filter: str) -> dict:
    """priority_filter(URGENT/HIGH/NORMAL/ALL)에 해당하는 pending 전체 승인·발송.

    Returns: {"ok": True, "total": N, "sent": M, "failed": K}
    """
    import time as _time
    targets = list_pending()
    if priority_filter != "ALL":
        targets = [p for p in targets if p.get("priority") == priority_filter]

    sent = 0
    failed = 0
    for t in targets:
        try:
            res = approve_and_send(t["id"])
            if res.get("ok"):
                sent += 1
            else:
                failed += 1
                print(f"[BATCH] 발송 실패 {t['id']}: {res.get('error')}")
        except Exception as e:
            failed += 1
            print(f"[BATCH] 예외 {t['id']}: {e}")
        _time.sleep(0.6)  # 텔레그램 rate limit

    return {"ok": True, "total": len(targets), "sent": sent, "failed": failed}


def reject_batch_by_priority(priority_filter: str) -> dict:
    """priority_filter에 해당하는 pending 전체 스킵."""
    targets = list_pending()
    if priority_filter != "ALL":
        targets = [p for p in targets if p.get("priority") == priority_filter]

    rejected = 0
    for t in targets:
        try:
            reject_issue(t["id"])
            rejected += 1
        except Exception as e:
            print(f"[BATCH] 스킵 실패 {t['id']}: {e}")

    return {"ok": True, "total": len(targets), "rejected": rejected}


def get_pending_summary() -> dict:
    """현재 pending 요약 (priority별 개수 + 총합)."""
    pending = list_pending()
    by_pri = {"URGENT": [], "HIGH": [], "NORMAL": []}
    for p in pending:
        pri = p.get("priority", "NORMAL")
        by_pri.setdefault(pri, []).append(p)
    return {
        "total": len(pending),
        "counts": {pri: len(items) for pri, items in by_pri.items()},
        "items_by_priority": by_pri,
    }


def mark_decision(issue_id: str, status: str, updated_content: str = None):
    """pending → 완료/거절/타임아웃 이력으로 이관"""
    issue = load_pending(issue_id)
    if not issue:
        return None

    today = datetime.date.today().strftime("%Y-%m-%d")
    history_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "history", "issue_bot",
    )
    dir_map = {
        "approved": "sent", "sent": "sent", "auto_approved": "sent",
        "rejected": "rejected", "timeout": "rejected",
        "edited": "edited",
    }
    sub = dir_map.get(status, "rejected")
    target_dir = os.path.join(history_root, sub)
    os.makedirs(target_dir, exist_ok=True)

    issue["status"] = status
    issue["decided_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
    if updated_content is not None and status == "edited":
        issue["edit_diff"] = {
            "original": issue.get("generated_content", ""),
            "final": updated_content,
        }
        issue["final_content"] = updated_content

    with open(os.path.join(target_dir, f"{today}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(issue, ensure_ascii=False) + "\n")

    remove_pending(issue_id)
    return issue


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    test_issue = {
        "id": "test_hybrid_20260421_001",
        "priority": "URGENT",
        "sector": "반도체",
        "category": "B",
        "source": "DART",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260421000999",
        "company_name": "KG스틸",
        "title": "주요사항보고서(타법인주식및출자증권취득결정)",
        "original_content": "KG스틸이 A사 지분 51%를 1,200억원에 인수하기로 이사회 의결. "
                            "인수 완료 예정일 2026-06-30. 자금 조달은 보유 현금 및 차입금 활용. "
                            "피인수사는 철강 가공 전문업체로 연매출 800억원 수준.",
        "original_excerpt": "KG스틸이 A사 지분 51%를 1,200억원에 인수하기로 이사회 의결. "
                            "인수 완료 예정일 2026-06-30. 자금 조달은 보유 현금 및 차입금 활용.",
        "peer_map_used": [],
    }

    print("하이브리드 테스트 - State 1 (원문 카드) 발송...")
    result = send_raw_approval_card(test_issue)
    print(f"결과: {result}")
