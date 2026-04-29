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

    if cmd in ("/help", "/h"):
        _cmd_help()
    elif cmd in ("/card", "/c"):
        _cmd_card(args)
    elif cmd in ("/dart", "/d"):
        _cmd_dart(args)
    elif cmd in ("/news", "/n"):
        _cmd_news(args)
    else:
        return False

    return True


def _cmd_help():
    """/help — 명령어 안내"""
    text = (
        "<b>이슈봇 (on-demand 모드)</b>\n\n"
        "💬 <b>자연어로 말해도 OK</b>\n"
        "예: \"어제 9시부터 12시까지 반도체 뉴스\"\n"
        "예: \"오늘 삼성전자 공시 봐줘\"\n"
        "예: \"최근 3시간 뉴스\"\n\n"
        "─" * 25 + "\n\n"
        "<b>명령어 (직접 입력도 OK)</b>\n\n"
        "<b>📰 카드 생성</b>\n"
        "• /card &lt;URL&gt; — URL로 카드 생성 (메리츠 스타일 가공 후 발송)\n"
        "• URL만 단독 입력해도 자동 인식\n\n"
        "<b>📋 DART 공시 조회</b>\n"
        "• /dart — 오늘 주요 공시 목록\n"
        "• /dart 어제 — 어제 공시\n"
        "• /dart 삼성전자 — 특정 기업 (오늘)\n"
        "• /dart 어제 삼성전자 — 어제 + 특정 기업\n"
        "• /dart 2026-04-29 — 특정 날짜\n\n"
        "<b>📰 뉴스 헤드라인 조회</b>\n"
        "• /news — 오늘 (최근 24h) 핵심 매체\n"
        "• /news 어제 — 어제 전체\n"
        "• /news 3h — 최근 3시간 (또는 30m)\n"
        "• /news 09:00-12:00 — 오늘 9~12시\n"
        "• /news 어제 14:00-18:00 — 어제 14~18시\n"
        "• /news 반도체 — 키워드 검색\n"
        "• /news 반도체 3h — 키워드 + 최근 3시간\n"
        "• /news 반도체 어제 09-12 — 키워드 + 어제 9~12시\n\n"
        "<b>⚙️ 기타</b>\n"
        "• /help — 이 메시지"
    )
    send_admin_dm(text, parse_mode="HTML")


# ===== /dart 명령어 (DART 공시 조회) =====

def _cmd_dart(args: list):
    """/dart [날짜] [시간범위] [기업명] — DART 공시 목록 조회.

    인자 규칙 (자유 순서):
    - 날짜: "오늘"/"어제"/"그제"/"YYYY-MM-DD"
    - 시간 범위: "09:00-12:00" / "9-12" / "3h" / "30m"
    - 기업명: 그 외 인자 합침

    예시:
    - /dart → 오늘 전체
    - /dart 어제 → 어제 전체
    - /dart 09:00-12:00 → 오늘 9~12시
    - /dart 3h → 최근 3시간
    - /dart 삼성전자 → 오늘 + 삼성전자
    - /dart 어제 09-15 삼성전자 → 어제 9~15시 + 삼성전자
    """
    import datetime as _dt
    from telegram_bot.issue_bot.collectors.dart_query import (
        parse_date_arg, fetch_dart_list, filter_signal_disclosures,
    )
    from telegram_bot.issue_bot.collectors.rss_query import parse_time_arg

    date = _dt.date.today()
    from_dt = None
    to_dt = None
    corp_parts = []

    for arg in args:
        # 1. 날짜?
        parsed_date = parse_date_arg(arg)
        if parsed_date and from_dt is None:
            date = parsed_date
            continue
        # 2. 시간 범위 / 상대 시간?
        parsed_time = parse_time_arg(arg, base_date=date)
        if parsed_time:
            from_dt, to_dt = parsed_time
            continue
        # 3. 그 외는 기업명
        corp_parts.append(arg)

    corp_name = " ".join(corp_parts) if corp_parts else None

    label_date = date.strftime("%Y-%m-%d (%a)")
    label_extra = f" — <b>{_html_escape(corp_name)}</b>" if corp_name else ""
    label_time = ""
    if from_dt is not None:
        label_time = (
            f" · {from_dt.strftime('%H:%M')}~{to_dt.strftime('%H:%M')}"
        )

    send_admin_dm(
        f"📋 DART 조회 중... ({label_date}{label_time}{label_extra})",
        parse_mode="HTML",
    )

    items = fetch_dart_list(date, corp_name=corp_name, page_count=100)

    # 시간 범위 필터 (rcept_dt = YYYYMMDDHHMM)
    if from_dt is not None and to_dt is not None:
        filtered_by_time = []
        for it in items:
            dt_str = it.get("rcept_dt", "")
            if len(dt_str) >= 12:
                try:
                    item_dt = _dt.datetime.strptime(dt_str[:12], "%Y%m%d%H%M")
                    if from_dt <= item_dt <= to_dt:
                        filtered_by_time.append(it)
                except ValueError:
                    continue
            # rcept_dt가 시간 정보 없으면 (YYYYMMDD만): 통과시킴
            else:
                filtered_by_time.append(it)
        items = filtered_by_time

    items_filtered = filter_signal_disclosures(items)

    if not items_filtered:
        if items:
            msg = (
                f"📭 <b>주요 공시 없음</b> — {label_date}{label_time}{label_extra}\n"
                f"<i>전체 {len(items)}건 중 노이즈 필터 후 0건.</i>\n"
                f"기업명·시간 범위 다시 확인하거나 다른 날짜 시도."
            )
        else:
            msg = (
                f"📭 <b>공시 없음</b> — {label_date}{label_time}{label_extra}\n"
                f"<i>DART 응답 0건 (해당 조건에 매칭 X).</i>\n"
                f"기업명 정확히 입력했는지 확인 (예: \"대한전선\")."
            )
        send_admin_dm(msg, parse_mode="HTML")
        return

    # 매체 다양성 cap — DART는 기업별 cap (한 기업이 여러 공시 동시 발표 시 편중 방지)
    from collections import Counter
    MAX_PER_CORP = 3   # 한 기업당 최대 3건 (corp_name 검색이면 제한 풀림)
    MAX_TOTAL = 12     # 전체 최대 12건

    if corp_name:
        # 특정 기업 검색이면 cap 풀고 다 보여줌
        MAX_PER_CORP = 100

    shown_per_corp = Counter()
    final_items = []
    for it in items_filtered:
        cn = it.get("corp_name", "")
        if shown_per_corp[cn] >= MAX_PER_CORP:
            continue
        final_items.append(it)
        shown_per_corp[cn] += 1
        if len(final_items) >= MAX_TOTAL:
            break

    # 메시지 조립
    header = (
        f"<b>📋 DART 공시 — {label_date}{label_time}{label_extra}</b>\n"
        f"<i>{len(final_items)}건 · 기업 {len(shown_per_corp)}곳 (전체 {len(items)}건 중 시그널 {len(items_filtered)}건)</i>\n"
        + "─" * 25
    )

    lines = [header]
    cur_len = len(header)

    for i, it in enumerate(final_items, 1):
        dt_str = it.get("rcept_dt", "")
        time_label = "--:--"
        if len(dt_str) >= 12:
            time_label = f"{dt_str[8:10]}:{dt_str[10:12]}"

        corp = _html_escape(it.get("corp_name", ""))
        report = _html_escape(it.get("report_nm", "").strip())

        # 새 형식:
        # [HH:MM] 기업명 — 보고서명 (헤드라인)
        # 📋 DART · 원본 (작게)
        head_line = f"\n<b>{i}.</b> [{time_label}] <b>{corp}</b> — {report}"
        meta_line = f"   <i>📋 DART · <a href=\"{it['url']}\">원본</a></i>"
        block = head_line + "\n" + meta_line + "\n"

        if cur_len + len(block) > 3800:
            lines.append(f"\n<i>... (이하 {len(final_items) - i + 1}건 생략)</i>")
            break

        lines.append(block)
        cur_len += len(block)

    lines.append(
        "\n💡 <b>카드 만들기</b>: 위 URL을 그대로 보내거나 <code>/card &lt;URL&gt;</code>"
    )

    send_admin_dm("\n".join(lines), parse_mode="HTML")


def _html_escape(text: str) -> str:
    """HTML 특수문자 escape (telegram parse_mode=HTML 안전)."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ===== /news 명령어 (RSS 헤드라인 조회) =====

def _cmd_news(args: list):
    """/news [날짜] [시간범위|상대시간] [키워드] — RSS 헤드라인 조회.

    인자 규칙 (자유 순서):
    - 날짜: "오늘"/"어제"/"그제"/"YYYY-MM-DD"
    - 시간 범위: "09:00-12:00" / "9-12" / "0900-1200"
    - 상대 시간: "3h" / "30m"
    - 키워드: 그 외 모든 인자 합침

    예시:
    - /news → 오늘 24h
    - /news 어제 → 24h~48h
    - /news 3h → 최근 3시간
    - /news 09:00-12:00 → 오늘 9~12시
    - /news 어제 14:00-18:00 → 어제 14~18시
    - /news 반도체 → 키워드
    - /news 반도체 3h → 키워드 + 최근 3시간
    - /news 반도체 어제 → 키워드 + 어제
    """
    import datetime as _dt
    from telegram_bot.issue_bot.collectors.rss_query import (
        fetch_news_headlines, search_keyword_news, parse_time_arg,
    )
    from telegram_bot.issue_bot.collectors.dart_query import parse_date_arg

    base_date = _dt.date.today()
    from_dt = None
    to_dt = None
    keyword_parts = []
    date_label = "오늘"
    time_label = ""

    for arg in args:
        # 1. 날짜 키워드?
        parsed_date = parse_date_arg(arg)
        if parsed_date and from_dt is None:
            base_date = parsed_date
            date_label = arg
            continue
        # 2. 시간 범위 / 상대 시간?
        parsed_time = parse_time_arg(arg, base_date=base_date)
        if parsed_time:
            from_dt, to_dt = parsed_time
            time_label = arg
            continue
        # 3. 그 외는 키워드
        keyword_parts.append(arg)

    keyword = " ".join(keyword_parts) if keyword_parts else None
    is_keyword_search = bool(keyword)

    # 시간 범위 미지정 + 날짜만 지정 시: 그 날 24h 전체
    if from_dt is None:
        if base_date == _dt.date.today():
            # 오늘: 최근 24h
            from_dt = _dt.datetime.now() - _dt.timedelta(hours=24)
            to_dt = _dt.datetime.now()
            range_label = "최근 24h"
        else:
            # 특정 날짜: 그 날 00:00 ~ 23:59
            from_dt = _dt.datetime.combine(base_date, _dt.time(0, 0))
            to_dt = _dt.datetime.combine(base_date, _dt.time(23, 59))
            range_label = base_date.strftime("%Y-%m-%d 전체")
    else:
        # 시간 범위 명시됨
        range_label = (
            f"{from_dt.strftime('%m/%d %H:%M')} ~ {to_dt.strftime('%H:%M')}"
            if from_dt.date() == to_dt.date()
            else f"{from_dt.strftime('%m/%d %H:%M')} ~ {to_dt.strftime('%m/%d %H:%M')}"
        )

    label_parts = [range_label]
    if keyword:
        label_parts.append(f"키워드: <b>{_html_escape(keyword)}</b>")
    label = " · ".join(label_parts)

    send_admin_dm(f"📰 뉴스 조회 중... ({label})", parse_mode="HTML")

    if is_keyword_search:
        items = search_keyword_news(
            keyword, max_results=50, from_dt=from_dt, to_dt=to_dt,
        )
    else:
        items = fetch_news_headlines(
            max_per_feed=10, from_dt=from_dt, to_dt=to_dt,
        )

    if not items:
        send_admin_dm(
            f"📭 <b>뉴스 없음</b> — {label}\n"
            f"<i>해당 시간/키워드 범위에 신규 헤드라인 없음.</i>\n"
            f"다른 시간대 또는 키워드로 다시 시도해보세요.",
            parse_mode="HTML",
        )
        return

    # 매체별 다양성 cap — 단일 매체 편중 방지
    from collections import Counter
    MAX_PER_SOURCE = 2  # 매체당 최대 2건
    MAX_TOTAL = 7       # 전체 최대 7건

    shown_per_source = Counter()
    filtered = []
    for it in items:
        src = it.get("source", "")
        if shown_per_source[src] >= MAX_PER_SOURCE:
            continue
        filtered.append(it)
        shown_per_source[src] += 1
        if len(filtered) >= MAX_TOTAL:
            break

    if not filtered:
        send_admin_dm(
            f"📭 <b>주요 뉴스 없음</b> — {label}\n"
            f"<i>매체별 cap 적용 후 결과 0건.</i>",
            parse_mode="HTML",
        )
        return

    # 영문 기사 번역 + 요약 (Haiku batch, 한글은 그대로)
    from telegram_bot.issue_bot.collectors.rss_query import translate_summarize_batch
    has_en = any(it.get("lang") == "en" for it in filtered)
    if has_en:
        send_admin_dm(
            f"🔄 영문 기사 번역 중... ({sum(1 for it in filtered if it.get('lang') == 'en')}건)",
            parse_mode="HTML",
        )
    filtered = translate_summarize_batch(filtered, max_items=MAX_TOTAL)

    header = (
        f"<b>📰 뉴스 헤드라인 — {label}</b>\n"
        f"<i>{len(filtered)}건 · 매체 {len(shown_per_source)}곳</i>\n"
        + "─" * 25
    )

    lines = [header]
    cur_len = len(header)

    for i, it in enumerate(filtered, 1):
        pub_dt = it.get("published_dt")
        time_str = pub_dt.strftime("%H:%M") if pub_dt else "--:--"
        src = it.get("source", "")
        title_kr = it.get("title_kr") or it.get("title", "")
        summary_kr = it.get("summary_kr", "")
        link = it.get("link", "")
        is_en = it.get("lang") == "en"

        # 새 형식:
        # [HH:MM] 한글 헤드라인
        # 1줄 요약 (영문 기사면 번역 + 요약, 한글 기사면 비어있음)
        # 📰 매체명 · 원본 (작게)

        head_line = f"\n<b>{i}.</b> [{time_str}] <b>{_html_escape(title_kr[:140])}</b>"

        body_parts = []
        if summary_kr:
            body_parts.append(f"   <i>{_html_escape(summary_kr[:200])}</i>")

        # 출처 — italic + 작은 글씨 느낌, 원본 링크
        src_line = f"   <i>📰 {_html_escape(src)}{' (영문 번역)' if is_en else ''} · <a href=\"{link}\">원본</a></i>"
        body_parts.append(src_line)

        block = head_line + "\n" + "\n".join(body_parts) + "\n"

        if cur_len + len(block) > 3800:
            lines.append(f"\n<i>... (이하 {len(filtered) - i + 1}건 생략 — 카드 길이 한계)</i>")
            break

        lines.append(block)
        cur_len += len(block)

    lines.append(
        "\n💡 <b>카드 만들기</b>: 위 URL을 그대로 보내거나 <code>/card &lt;URL&gt;</code>"
    )

    send_admin_dm("\n".join(lines), parse_mode="HTML")


# ===== /card 명령어 (on-demand 카드 생성) =====

import re as _re_mod
import hashlib as _hashlib_mod

_URL_PATTERN = _re_mod.compile(r"^https?://", _re_mod.IGNORECASE)


def _handle_natural_language(text: str):
    """자유 텍스트 → 명령어 변환 + 실행 (rule + Haiku fallback)."""
    from telegram_bot.issue_bot.utils.nlu import parse_natural_language

    cmd, args = parse_natural_language(text)

    if not cmd:
        send_admin_dm(
            "⚠️ 의도를 파악하지 못했어요.\n"
            "<code>/help</code>로 명령어 목록 확인 또는 다시 표현해주세요.\n\n"
            "<i>예: \"어제 9시부터 12시까지 반도체 뉴스\"</i>",
            parse_mode="HTML",
        )
        return

    # 인식된 명령어 실행 (slash 명령어와 동일 핸들러 재사용)
    if cmd in ("/card", "/c"):
        _cmd_card(args)
    elif cmd in ("/dart", "/d"):
        _cmd_dart(args)
    elif cmd in ("/news", "/n"):
        _cmd_news(args)
    elif cmd in ("/help", "/h"):
        _cmd_help()
    else:
        send_admin_dm(
            f"⚠️ 알 수 없는 명령: <code>{cmd}</code>\n"
            "<code>/help</code>로 명령어 목록 확인.",
            parse_mode="HTML",
        )


def _cmd_card(args: list):
    """/card <URL>  또는  /card <키워드>"""
    if not args:
        send_admin_dm(
            "📋 <b>/card 사용법</b>\n\n"
            "<b>1. URL로</b> (가장 정확):\n"
            "<code>/card https://www.etnews.com/...</code>\n\n"
            "<b>2. URL만 보내도 자동 인식</b>:\n"
            "<code>https://buly.kr/...</code>\n\n"
            "<b>3. 키워드 검색</b> (DART): <i>곧 지원 예정</i>\n"
            "<code>/card 삼성전자 자사주 소각</code>",
            parse_mode="HTML",
        )
        return

    arg = " ".join(args).strip()

    if _URL_PATTERN.match(arg):
        _create_card_from_url(arg)
    else:
        send_admin_dm(
            "⚠️ 키워드 검색은 곧 지원 예정.\n"
            "지금은 URL만 가능: <code>/card https://...</code>",
            parse_mode="HTML",
        )


def _detect_source_from_url(url: str) -> str:
    """URL 도메인으로 매체명 추론 (Haiku 매체 가점에 활용됨)."""
    u = url.lower()
    mapping = [
        ("dart.fss.or.kr", "DART"),
        ("kind.krx.co.kr", "DART"),
        ("etnews.com", "전자신문"),
        ("zdnet.co.kr", "ZDNet Korea"),
        ("businesspost.co.kr", "Business Post"),
        ("trendforce", "TrendForce"),
        ("digitimes", "Digitimes"),
        ("counterpoint", "Counterpoint"),
        ("omdia", "Omdia"),
        ("idc.com", "IDC"),
        ("gartner", "Gartner"),
        ("semianalysis", "SemiAnalysis"),
        ("reuters.com", "Reuters Tech"),
        ("bloomberg.com", "Bloomberg Tech"),
        ("nikkei.com", "Nikkei Asia"),
        ("ft.com", "FT"),
        ("wsj.com", "WSJ Tech"),
        ("seekingalpha.com", "Seeking Alpha"),
        ("sec.gov", "SEC"),
        ("hankyung.com", "한국경제"),
        ("mk.co.kr", "매일경제"),
        ("yna.co.kr", "연합뉴스"),
        ("buly.kr", "(단축URL — 매체 자동 감지 후 표시)"),
    ]
    for key, name in mapping:
        if key in u:
            return name
    return ""


def _guess_template_from_url(url: str) -> str:
    """URL로 Template 추정."""
    u = url.lower()
    if "dart.fss.or.kr" in u or "kind.krx.co.kr" in u:
        return "B"  # 국내 공시
    if "sec.gov" in u:
        return "A"  # 해외 IR (SEC 8-K)
    return "C"  # 기본: 영문/한글 기사·리서치


def _fetch_article_metadata(url: str) -> dict:
    """URL에서 title, body, og:image, 최종 redirect URL 추출."""
    import requests
    from bs4 import BeautifulSoup

    try:
        res = requests.get(
            url,
            timeout=15,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NODEResearchBot/1.0"},
        )
        if res.status_code != 200:
            return {"error": f"HTTP {res.status_code}"}

        final_url = str(res.url)
        soup = BeautifulSoup(res.text, "lxml")

        # title
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()

        # body 추출 (rss_adapter 패턴 재사용)
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        target = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=_re_mod.compile(r"(article|content|post|body|entry)", _re_mod.I))
        )
        if not target:
            target = soup.body or soup
        body = target.get_text(separator=" ", strip=True)
        body = _re_mod.sub(r"\s+", " ", body)[:3000]

        # og:image
        og_img = soup.find("meta", property="og:image")
        image_url = og_img["content"].strip() if og_img and og_img.get("content") else None

        return {
            "title": title,
            "body": body,
            "image_url": image_url,
            "final_url": final_url,
        }
    except Exception as e:
        return {"error": str(e)}


def _create_card_from_url(url: str):
    """URL → Sonnet 본문 생성 → 미리보기 카드 1회만 발송 (raw 카드 단계 X, edit X).

    2026-04-29 사용자 정책: "URL 주면 요약 정리해서 한 번에 보여줘".
    - raw 카드 발송 X (이미지 메시지 + editMessageText 충돌 회피)
    - edit_admin_message X
    - send_admin_dm으로 최종 미리보기 카드 1회 발송
    - 사용자가 그 카드의 [✅ 발송] [✏️ 수정] [❌ 스킵] 결정
    """
    from telegram_bot.issue_bot.approval.bot import (
        format_preview_card,
        save_pending,
        MAX_CARD_LEN,
    )
    from telegram_bot.issue_bot.utils.telegram import approval_keyboard_preview
    from telegram_bot.issue_bot.pipeline.generator import generate_with_retry

    send_admin_dm(
        f"📋 본문 정리 중... (10~20초)\n<code>{url[:80]}</code>",
        parse_mode="HTML",
    )

    meta = _fetch_article_metadata(url)
    if "error" in meta:
        send_admin_dm(f"⚠️ URL fetch 실패: {meta['error']}\n다시 시도하거나 다른 URL 입력.")
        return

    final_url = meta.get("final_url") or url
    title = meta.get("title") or final_url
    body = meta.get("body") or ""
    image_url = meta.get("image_url")

    if len(body) < 100:
        send_admin_dm(
            f"⚠️ 본문이 너무 짧음 ({len(body)}자). 카드 생성 불가.\n"
            f"제목: {title[:80]}\n"
            f"URL이 paywall이거나 JS 렌더링 페이지일 수 있음."
        )
        return

    source_name = _detect_source_from_url(final_url) or "사용자 요청"
    template = _guess_template_from_url(final_url)

    url_hash = _hashlib_mod.sha1(final_url.encode("utf-8")).hexdigest()[:8]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    issue_id = f"ondemand_{ts}_{url_hash}"

    issue = {
        "id": issue_id,
        "source": "ON_DEMAND",
        "source_url": final_url,
        "source_id": final_url,
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "ticker": None,
        "company_name": source_name,
        "corp_code": "",
        "corp_cls": "",
        "title": title[:200],
        "report_nm_raw": None,
        "report_nm_clean": None,
        "body_excerpt": body[:1500],
        "original_content": body,
        "original_excerpt": body[:500],
        "category_hint": template,
        "priority_hint": "HIGH",
        "rule_match_reason": "사용자 on-demand 요청",
        "event_type": "ondemand",
        "date": datetime.datetime.now().date().isoformat(),
        "image_url": image_url,
        "article_group": "사용자 요청",
        "priority": "HIGH",
        "category": template,
        "sector": "기타",
        "reason": "사용자 on-demand",
        "significance": "",
        "source_method": "ondemand",
        "peer_map_used": [],
        "violations": [],
        "has_generated": False,
        "generated_content": None,
    }

    # 1. Sonnet 본문 생성 (raw 카드 발송 X — 곧바로 본문 작업)
    classification = {
        "priority": issue["priority"],
        "category": issue["category"],
        "sector": issue["sector"],
    }
    try:
        gen_result = generate_with_retry(issue, classification)
        issue["generated_content"] = gen_result["generated_content"]
        issue["violations"] = gen_result.get("violations", [])
        issue["has_generated"] = True
        issue["status"] = "pending_preview"
    except Exception as e:
        traceback.print_exc()
        send_admin_dm(f"⚠️ 본문 생성 중 오류: {e}")
        return

    if not issue.get("generated_content"):
        send_admin_dm("⚠️ 본문 생성 실패 (빈 응답). 다시 시도하거나 다른 URL 입력.")
        return

    # 2. 본문 정리 카드 1회 발송 (raw 카드 X, edit X, "프리뷰됨" 표시 제거)
    card_text = format_preview_card(issue).replace(" | <i>프리뷰됨</i>", "")
    if len(card_text) > MAX_CARD_LEN:
        short = (issue["generated_content"] or "")[:MAX_CARD_LEN - 300] + "\n... (본문 일부 생략)"
        issue_tmp = {**issue, "generated_content": short}
        card_text = format_preview_card(issue_tmp).replace(" | <i>프리뷰됨</i>", "")

    keyboard = approval_keyboard_preview(issue_id)

    res = send_admin_dm(card_text, reply_markup=keyboard, parse_mode="HTML")

    if res and res.get("ok"):
        issue["telegram_admin_msg_id"] = res["result"]["message_id"]
        save_pending(issue)
    else:
        err = (res.get("description") if res else "no response") or "unknown"
        send_admin_dm(f"⚠️ 카드 발송 실패: {err}")


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
    """만료된 pending을 timeout 처리. main 루프에서 주기적 호출.

    기본 OFF(ISSUE_BOT_AUTO_TIMEOUT=false) — 자는 동안 중요 이슈 자동 유실 방지.
    관리자가 /queue + 일괄 스킵 or 개별 ❌ 스킵으로 처리해야 pending에서 제거됨.
    """
    from telegram_bot.config import ISSUE_BOT_AUTO_TIMEOUT
    if not ISSUE_BOT_AUTO_TIMEOUT:
        return  # 자동 타임아웃 비활성 (기본값)

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
                            cb = upd["callback_query"]
                            # 콜백 버튼 누른 chat을 컨텍스트로 (그룹/개인)
                            from telegram_bot.issue_bot.utils.telegram import (
                                set_current_chat, is_allowed_chat,
                            )
                            cb_chat = cb.get("message", {}).get("chat", {}).get("id")
                            if not is_allowed_chat(cb_chat):
                                continue
                            set_current_chat(cb_chat)
                            _handle_callback(cb)
                        elif "message" in upd:
                            msg = upd["message"]
                            chat_id = msg.get("chat", {}).get("id")
                            # 다중 chat 지원: ADMIN + ALLOWED_CHAT_IDS 화이트리스트
                            from telegram_bot.issue_bot.utils.telegram import (
                                set_current_chat, is_allowed_chat,
                            )
                            if not is_allowed_chat(chat_id):
                                continue
                            set_current_chat(chat_id)
                            text = (msg.get("text") or "").strip()
                            if "reply_to_message" in msg:
                                _handle_edit_reply(msg)
                            elif text.startswith("/"):
                                _handle_command(msg)
                            elif _URL_PATTERN.match(text):
                                # URL만 보내면 /card 로 자동 처리
                                _create_card_from_url(text.split()[0])
                            elif text:
                                # 자연어 인식 (Rule + Haiku fallback)
                                _handle_natural_language(text)
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
