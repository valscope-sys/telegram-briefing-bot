# 세션 핸드오프 — 2026-04-23 말미

**새 세션에서 이 파일을 먼저 읽어주세요. 현 상태 파악에 가장 효율적.**

---

## ⚠️ 작업 도메인 경계 — 이 작업방은 "이슈봇 전용"

- ✅ **건드려도 됨**: `telegram_bot/issue_bot/**`, `telegram_bot/history/issue_bot/**`, `telegram_bot/history/dart_category_map.json`, `.claude/settings.json`
- ⚠️ **공유 파일 (건드릴 땐 주의, 알림 필요)**: `telegram_bot/main.py`, `telegram_bot/config.py`, `CLAUDE.md`
- ❌ **시황봇 영역 금지**: `telegram_bot/briefings.py`, `telegram_bot/collectors/news_collector.py` 내 RSS 피드·프롬프트, `telegram_bot/history/market_context.txt`

> **혼용 주의**: `market_context.txt`(한지영·브리핑 메모리)는 시황봇 전용. 이슈봇 필터에 주입 금지 (이슈봇은 이벤트 객관 평가).

---

## 🎯 현재 라이브 상태 (2026-04-23)

- **서비스**: AWS Lightsail — `telegram-bot.service` (systemd) — 브리핑봇 + 이슈봇 한 프로세스
- **폴링 주기**: 3분 (실시간급)
- **보호 구간**: 06:50~07:10 / 16:20~16:50 (브리핑 시간 자동 회피)
- **수집 소스**: DART 증분 + RSS 19피드 + SEC 8-K 16 CIK (빅테크·반도체 Peer)
- **최신 커밋**: `9ba826e` (2026-04-23) 공시 우선 dedup + IR 자료 통합 + 번역/해석 프롬프트

### SessionStart Hook 동작 중
`.claude/settings.json`에 설정되어 있어 새 세션 열면 **자동으로 `git pull` + 최근 커밋 5개 표시**. 별도 명령 불필요.

---

## 🔥 주요 정책 (사용자 명시)

### 1. DART 카드 대상 (대폭 간소화 2026-04-23)
**URGENT (자동 카드, 8개)**: 잠정실적 공시, 연결 잠정실적, 매출 30%+ 변동, 품목허가
**HIGH (자동 카드, 3개)**: 신규시설투자(Capex), 임상시험계획승인, 품목허가신청
**AI 판단 (매핑 제거 → Haiku)**: M&A(취득/처분/합병/분할/영업양수도), 유증/무증, CB/EB, 공급계약 해지
**NORMAL (카드 X, 32개)**: 자사주 계열, 감자, BW, 최대주주변경, 공급계약 체결, IR, 배당, 주총, 정기보고 등
**SKIP**: 거래정지(모든 변종), 감사보고서, 5% 공시, 부도/해산/회생/상폐(사용자 요청)

### 2. SEC 8-K 카드 대상
- ✅ **Item 2.02만 HIGH** (분기/연간 실적) — Exhibit 99.1 + 99.2(IR presentation) + 99.3 자동 파싱
- ❌ 나머지 23개 Item 모두 SKIP (빅테크는 실적만)

### 3. 공시 우선 Dedup
- 같은 cluster에 DART/SEC primary 있으면 → RSS는 자동 secondary
- 이전 RSS primary만 있다가 DART/SEC 나중에 와도 → **공시도 primary로 발송** (공시 반드시 도달)
- 기업명 자동 추출 (50+ 별칭) → 같은 기업의 여러 언론사 중복 뉴스 자동 필터

### 4. Generator 프롬프트 — 3단계 명시
State 2 (미리보기/발송) 시 Sonnet이 반드시 다음 순서:
1. **번역** (영문/일문 → 한글)
2. **정리** (투자자 관점 핵심 수치·사실)
3. **해석** (한국 시장 시사점·밸류체인 파급)

"제출했다/발표 예정" 같은 메타 문구 지양 — 실제 수치가 핵심.

---

## 📦 오늘(2026-04-22 ~ 04-23) 핵심 커밋

| 해시 | 내용 |
|---|---|
| `b789a00` | Phase 1 MVP 배포 (Hybrid 필터 + 증분 폴링) |
| `a18b20a` | 폴백 본문 + RSS 글로벌 확장 |
| `c82af6e` | Peer 영향해석 + SEC Item 태깅 + /queue /mute 커맨드 |
| `a559ccc` | poller auto-restart + TrendForce 본문 파싱 |
| `3173457` | 자동 타임아웃 OFF |
| `ae476dc` | poller lock 충돌 해결 (stale 30s + SIGTERM handler) |
| `655ec1b` | RSS 11개 복구 (Google News 프록시 등) |
| `228969c` | SessionStart hook (git pull 자동화) |
| `d756563` | 거래정지 전면 SKIP |
| `67dab36` | SEC Exhibit 99.1 + requests.Session + gc.collect |
| `ebaf1c6` | 기업명 추출 + cluster dedup |
| `9b5cb96` | 공시 매핑 대폭 간소화 v2 |
| **`9ba826e`** | **(최신)** 공시 우선 dedup + IR 자료(99.2/99.3) + 번역/정리/해석 프롬프트 |

---

## 🚦 남은 과제 (우선순위)

### 🔴 긴급 — 진단 필요
1. **`/preview max retry exceeded` 간헐 발생** — Anthropic API 호출 반복 실패. OOM 이후 client 상태 손상 가능성? 서버 재시작 후 관찰 필요.
2. **발송 됐다 안됐다** — Telegram API 간헐 실패? 로그 확인 필요.

### 🟡 다음 라운드
3. **서버 인스턴스 업그레이드**: Lightsail 512MB → 2GB ($10/월) 권장. 07:26 OOM 사건 재발 방지. swap 1GB 응급 추가 중.
4. **systemd 분리**: 브리핑봇 ↔ 이슈봇을 별도 systemd unit으로 격리. 한쪽 죽어도 다른 쪽 유지.
5. **Digitimes 대안 탐색**: EETimes·SemiWiki 등 반도체 전문 피드.
6. **메리츠 Tech 텔레그램 심도 학습**: 과거 샘플 크롤러 → 200~500개 → 필터 few-shot 강화.

### 🟢 관찰·미세조정
7. 사용자 정책 실제 효과 24h 관찰 — 카드 스팸 줄었는지, 중요 공시 놓침 없는지
8. 하이닉스 같은 분기보고서 실적 나올 때 rule-based 처리 (현재 분기보고서는 NORMAL → Haiku가 본문 보고 판단)

---

## 🔍 서버 운영 명령 (자주 쓰는 것)

```bash
# 서비스 상태
sudo systemctl status telegram-bot --no-pager

# 실시간 로그
sudo journalctl -u telegram-bot -f

# 최근 로그 (특정 키워드)
sudo journalctl -u telegram-bot --since "today 00:00" --no-pager | grep -E "ISSUE_BOT|card sent|below min|ERROR"

# 재시작
sudo systemctl restart telegram-bot

# 배포 (코드 변경 pull + restart)
cd /home/ubuntu/telegram-briefing-bot && git pull origin main && sudo systemctl restart telegram-bot

# 1회 수동 폴링 (테스트)
cd /home/ubuntu/telegram-briefing-bot && source venv/bin/activate
python -m telegram_bot.issue_bot.main once

# pending 카드 수
ls /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/pending/*.json 2>/dev/null | wc -l

# 긴급 중단
touch /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/KILL_SWITCH
```

---

## 💬 관리자 DM 명령 (텔레그램에서 직접)

- `/queue` — 대기 카드 요약 + 우선순위별 일괄 승인/스킵
- `/mute [분]` — N분 중지 (기본 60)
- `/stop` — 자정까지 중지
- `/resume` — 즉시 재개
- `/help` — 안내

---

## 🆕 새 세션 시작 프롬프트 예시

```
이 리포의 실시간 이슈봇 작업 이어서 진행할게.
SESSION_HANDOFF.md를 먼저 읽고 현재 상태 파악해줘.
그 다음 [구체 작업 지시].
```

또는 관찰 모드:
```
SESSION_HANDOFF.md 읽고 지금 이슈봇 운영 상태 점검해줘.
오늘 카드 발송 이력 + 남은 과제 정리해줘.
```

---

## 🛠 환경변수 기본값 (서버 .env)

```
TELEGRAM_BOT_TOKEN=<설정됨>
TELEGRAM_CHANNEL_ID=@noderesearch
TELEGRAM_ADMIN_CHAT_ID=5033358048
ANTHROPIC_API_KEY=sk-ant-api03-...
DART_API_KEY=<설정됨>

# 이슈봇 (대부분 코드 기본값 사용)
ISSUE_BOT_ENABLED=true
ISSUE_BOT_AUTO_APPROVE=false
ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_FILTER_VERIFIER_MODEL=claude-sonnet-4-5
ISSUE_BOT_FILTER_HYBRID=true
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-5
ISSUE_BOT_POLL_INTERVAL_MIN=3
ISSUE_BOT_ADMIN_MIN_PRIORITY=HIGH
ISSUE_BOT_AUTO_TIMEOUT=false
```

**완화하고 싶을 때**:
- 카드 더 많이 받기: `ISSUE_BOT_ADMIN_MIN_PRIORITY=NORMAL`
- 완전 중단: `ISSUE_BOT_ENABLED=false`
- 야간 자동 타임아웃 복구: `ISSUE_BOT_AUTO_TIMEOUT=true`

---

## 📚 관련 문서

1. **이 파일** — 최근 세션 상태
2. **`CLAUDE.md`** — 프로젝트 전체 개요 (날짜 구식이라 참고만)
3. **`ISSUE_BOT_SPEC.md`** — 이슈봇 전체 설계 1,121줄 (Phase 로드맵)
4. **`REVIEW_BRIEF.md`** (있으면) — 점검용 요약
5. **`telegram_bot/history/style_canon.md`** — 생성 스타일 경전

---

**모든 것 OK. 새 세션에서 이어가세요.** 🚀
