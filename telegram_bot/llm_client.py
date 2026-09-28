"""Claude 호출 공통 모듈 — API 크레딧이 없으면 로컬 Claude Code(구독 로그인)로 자동 전환

사용법 (기존 anthropic 코드와 호출 형태 동일):
    from telegram_bot.llm_client import get_client
    client = get_client()                      # anthropic.Anthropic(api_key=...) 대체
    resp = client.messages.create(model=..., max_tokens=..., system=..., messages=[...])
    resp.content[0].text, resp.usage.input_tokens  # 그대로 동작

백엔드 선택 — 환경변수 LLM_BACKEND:
    auto (기본) API 키가 있으면 API 먼저, 크레딧 부족·인증 실패 시 Claude Code CLI로 전환
    api         API만 사용
    cli         Claude Code CLI만 사용 (구독 로그인, 서버는 CLAUDE_CODE_OAUTH_TOKEN)

CLI 모드 주의:
- ANTHROPIC_API_KEY가 환경에 있으면 CLI가 구독 대신 API 키를 쓰므로 자식 프로세스에서 제거
- 프로젝트 CLAUDE.md·훅·MCP가 끼어들지 않도록 빈 작업 디렉터리 + 설정 소스 차단
- temperature·thinking 파라미터는 CLI에 없어 무시됨 (응답 품질에 큰 영향 없음)
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

_BACKEND = os.getenv("LLM_BACKEND", "auto").strip().lower()
_CLI_TIMEOUT = int(os.getenv("LLM_CLI_TIMEOUT", "300"))
# API가 크레딧 부족으로 실패하면 이 시간 동안은 API를 건너뛰고 바로 CLI 사용 (충전 후 자동 복귀)
_API_RETRY_AFTER_SEC = 6 * 3600
_api_disabled_until = 0.0

_API_FALLBACK_MARKERS = (
    "credit balance", "billing", "authentication_error", "invalid x-api-key",
    "permission_error", "api key",
)


class LLMError(RuntimeError):
    pass


class _Block:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, d: dict):
        d = d or {}
        self.input_tokens = d.get("input_tokens", 0) or 0
        self.output_tokens = d.get("output_tokens", 0) or 0
        self.cache_read_input_tokens = d.get("cache_read_input_tokens", 0) or 0
        self.cache_creation_input_tokens = d.get("cache_creation_input_tokens", 0) or 0


class _Response:
    def __init__(self, text: str, usage: dict, model: str):
        self.content = [_Block(text)]
        self.usage = _Usage(usage)
        self.model = model
        self.stop_reason = "end_turn"
        self.backend = "cli"


def _cli_path() -> str | None:
    return shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")


def _cli_model(model: str) -> str:
    m = (model or "").lower()
    if "haiku" in m:
        return "haiku"
    if "opus" in m:
        return "opus"
    if "fable" in m:
        return "fable"
    return "sonnet"


def _text_of(content) -> str:
    """system/message content (문자열 또는 블록 리스트) → 텍스트"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if isinstance(b, dict):
            if b.get("type", "text") == "text":
                parts.append(b.get("text", ""))
        elif hasattr(b, "text"):
            parts.append(b.text)
    return "\n\n".join(p for p in parts if p)


def _messages_to_prompt(messages: list) -> str:
    if len(messages) == 1:
        return _text_of(messages[0].get("content"))
    # 다회 대화는 순서대로 이어붙임 (현재 코드베이스는 단일 user 메시지만 사용)
    lines = []
    for m in messages:
        role = "사용자" if m.get("role") == "user" else "어시스턴트"
        lines.append(f"[{role}]\n{_text_of(m.get('content'))}")
    return "\n\n".join(lines)


# WebSearch 도구가 결과 끝에 붙이는 출처 목록 제거 (텔레그램 본문에 불필요)
_SOURCES_TAIL = re.compile(r"\n+\s*(Sources|출처)\s*:\s*\n(\s*[-*]\s*\[[^\]]*\]\([^)]*\)\s*\n?)+\s*$")


def _call_cli(model: str, system, messages: list, web_search: bool) -> _Response:
    exe = _cli_path()
    if not exe:
        raise LLMError("Claude Code CLI(claude)를 찾을 수 없음 — 설치 후 로그인 필요 "
                       "(서버: curl -fsSL https://claude.ai/install.sh | bash + CLAUDE_CODE_OAUTH_TOKEN)")

    workdir = tempfile.mkdtemp(prefix="node_llm_")
    try:
        cmd = [exe, "-p", "--model", _cli_model(model), "--output-format", "json",
               "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
        sys_text = _text_of(system)
        if sys_text:
            sys_file = os.path.join(workdir, "system.txt")
            with open(sys_file, "w", encoding="utf-8") as f:
                f.write(sys_text)
            cmd += ["--system-prompt-file", sys_file]
        if web_search:
            cmd += ["--tools", "WebSearch", "--allowedTools", "WebSearch", "--max-turns", "8"]
        else:
            cmd += ["--tools", "", "--max-turns", "1"]

        env = dict(os.environ)
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)

        started = time.time()
        proc = subprocess.run(
            cmd, input=_messages_to_prompt(messages), capture_output=True,
            text=True, encoding="utf-8", errors="replace", cwd=workdir, env=env,
            timeout=_CLI_TIMEOUT,
        )
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise LLMError(f"CLI 응답 파싱 실패 (rc={proc.returncode}): "
                           f"{(proc.stdout or proc.stderr)[:300]}")
        if data.get("is_error") or proc.returncode != 0:
            raise LLMError(f"CLI 오류: {str(data.get('result') or data.get('error') or proc.stderr)[:300]}")

        text = (data.get("result") or "").strip()
        if web_search:
            text = _SOURCES_TAIL.sub("", text).strip()
        print(f"[LLM] Claude Code CLI 응답 ({_cli_model(model)}, {time.time() - started:.1f}s"
              f"{', 웹검색' if web_search else ''})")
        return _Response(text, data.get("usage") or {}, model)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _should_fallback(err: Exception) -> bool:
    s = str(err).lower()
    status = getattr(err, "status_code", None)
    return status in (401, 402, 403) or any(m in s for m in _API_FALLBACK_MARKERS)


class _Messages:
    def __init__(self, api_key: str | None):
        self._api_key = api_key

    def create(self, *, model: str, messages: list, max_tokens: int = 1024, system=None,
               tools=None, **kwargs):
        global _api_disabled_until
        web_search = any(
            (t.get("name") == "web_search" or str(t.get("type", "")).startswith("web_search"))
            for t in (tools or []) if isinstance(t, dict)
        )

        use_api = _BACKEND in ("auto", "api") and self._api_key
        if _BACKEND == "auto" and time.time() < _api_disabled_until:
            use_api = False

        if use_api:
            import anthropic
            try:
                params = dict(model=model, messages=messages, max_tokens=max_tokens, **kwargs)
                if system is not None:
                    params["system"] = system
                if tools:
                    params["tools"] = tools
                return anthropic.Anthropic(api_key=self._api_key).messages.create(**params)
            except Exception as e:
                if _BACKEND == "api" or not _should_fallback(e):
                    raise
                _api_disabled_until = time.time() + _API_RETRY_AFTER_SEC
                print(f"[LLM] API 사용 불가 ({str(e)[:120]}) → Claude Code CLI로 전환 (6시간 후 API 재시도)")

        if _BACKEND == "api":
            raise LLMError("LLM_BACKEND=api 인데 ANTHROPIC_API_KEY가 없음")
        return _call_cli(model, system, messages, web_search)


class LLMClient:
    """anthropic.Anthropic 호환 최소 클라이언트 (messages.create만 지원)"""

    def __init__(self, api_key: str | None = None):
        self.messages = _Messages(api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", ""))


def get_client(api_key: str | None = None) -> LLMClient:
    return LLMClient(api_key)


def llm_available() -> bool:
    """API 키 또는 Claude Code CLI 중 하나라도 있으면 True (API 키 없는 로컬 구독 환경 지원)"""
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if _BACKEND == "api":
        return has_key
    if _BACKEND == "cli":
        return _cli_path() is not None
    return has_key or _cli_path() is not None
