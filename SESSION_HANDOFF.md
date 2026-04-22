# 세션 핸드오프 — 2026-04-22 (AWS 라이브 운영 시작)

**다음 세션에서 이 파일을 먼저 읽어주세요.**

---

## ⚠️ 작업 도메인 경고 — 이 작업방은 "이슈봇 전용"

- ✅ **이슈봇 영역**: `telegram_bot/issue_bot/**`, `telegram_bot/history/issue_bot/**`, `telegram_bot/history/dart_category_map.json`, SEC/DART/이슈봇 RSS 어댑터, 이슈봇 환경변수
- ❌ **건드리지 않음(시황 브리핑봇 영역)**: `telegram_bot/collectors/news_collector.py`, `telegram_bot/history/market_context.txt`, `telegram_bot/briefings.py`, `telegram_bot/collectors/*` (news_collector 제외한 것들은 원래 브리핑 데이터 수집용)

**이슈봇 RSS 추가**는 `telegram_bot/issue_bot/collectors/rss_adapter.py`의 `ISSUE_BOT_EXTRA_FEEDS`에만.
시황봇 `market_context.txt` (한지영·브리핑 메모리)는 이슈봇 필터에 주입 금지 — 이슈봇은 이벤트 **객관 평가** 전용.

---

## 🎯 현재 상태 요약

**실시간 이슈봇 Phase 1 — AWS Lightsail 라이브 운영 중** (2026-04-22 10:18 KST부터).

- 서비스: `telegram-bot.service` (systemd, Lightsail /home/ubuntu/telegram-briefing-bot)
- 브리핑봇 + 이슈봇 **한 프로세스에서 공존** (APScheduler 통합)
- 15분 간격 폴링 (DART 증분 + RSS 15개)
- 보호구간: 06:50~07:10 / 16:20~16:50 (브리핑 시간 자동 회피)

---

## ✅ 오늘 완료된 작업

### 코드
- Hybrid 필터 (Haiku 1차 → HIGH/NORMAL 경계는 Sonnet 재검증)
- 필터 프롬프트 전면 강화: "투자 시사점 4기준" + SKIP 목록 명시
- DART 증분 폴링 (rcept_no 커서), max_cards_per_poll=3
- RSS 어댑터 재도입 (기존 news_collector 15개 피드)
- dart_category_map 튜닝: 감사보고서 / 5%공시 → SKIP
- 런타임 상태 파일 .gitignore (cache_stats/seen_ids/sent/rejected/last_rcept_no)

### 배포
- 커밋 푸시 완료: `b789a00` (Hybrid 필터) + 이전 `5c7624c`, `6b42d51`, 이후 `776bc41`, `add51b3`
- 서버 .env에 `DART_API_KEY`, `TELEGRAM_ADMIN_CHAT_ID` 추가
- `sudo systemctl restart telegram-bot` → Active running 확인
- `ISSUE_BOT_POLL_INTERVAL_MIN=3`으로 단축 (3분 주기 실시간급)
- `a18b20a` 추가 커밋: 본문 생성 폴백 + RSS 19개로 확장

---

## 📡 현재 커버리지

### DART (국내 공시)
- rcept_no 증분 폴링. 첫 실행 시 최근 10건만.
- rule-based 분류: `dart_category_map.json` (감사/5% SKIP)

### RSS 15개 (기존 news_collector 재활용)
- **국내(6)**: 한국경제, 매일경제, 이데일리, 금융위, 한국은행, 산자부
- **해외종합(3)**: Reuters, CNBC, WSJ
- **섹터(6)**: TrendForce, Electrek, InsideEVs, FiercePharma, Defense News, World Nuclear News

### 필터 (Hybrid)
- 1차: Haiku — "투자 시사점 4기준" (밸류체인/사이클/구조변화/시급성)
- 2차: Sonnet (HIGH/NORMAL 경계만) — 더 엄격히 재판정
- SKIP/URGENT는 Haiku 결정 유지 (비용 절감)

---

## 🚦 다음 세션 우선순위

### 1. 라이브 운영 관찰 (당장)
- @noderesearch_bot DM으로 승인카드 수신 빈도 체크
- 하루 몇 건 오는지 → ADMIN_MIN_PRIORITY 조정 가늠
- SKIP 판정이 적절한지 spot check

**서버 로그 확인 명령** (브라우저 SSH):
```bash
sudo journalctl -u telegram-bot -n 100 --no-pager
sudo journalctl -u telegram-bot -f       # 실시간 tail
```

### 2. Phase 2 — 글로벌 커버리지 확대 (사용자 요청)
사용자 피드백: **빅테크 주요 이벤트, 부각 종목 AI 감지 필요**.

**이번 세션 완료분:**
- RSS 4개 피드 추가 (Nikkei Asia, Seeking Alpha, 전자신문, 디지털타임스)
- 총 RSS 19개 (기존 15 + 신규 4)

**완료분 (Phase 2 이번 세션):**
- SEC EDGAR 8-K 수집기 (16개 CIK — M7 + 반도체 Peer)
- 필터 프롬프트에 "해외 Peer 8-K 판정 기준" 조항 추가 (Item 2.02/1.01 → HIGH 후보)
- 이슈봇 전용 RSS 4개 (Nikkei Asia / Seeking Alpha / 전자신문 / 디지털타임스)
  → `rss_adapter.ISSUE_BOT_EXTRA_FEEDS`에만 저장, 시황봇 `news_collector` 불변

**남은 백로그 (다음 세션 — 이슈봇 도메인):**
- SEC 8-K Item 파싱 (Item 2.02 실적 / 1.01 M&A 등을 자동 태깅)
- TrendForce 개별 리서치 본문 파싱
- Digitimes 대안 탐색 (공식 RSS 없음)
- `/mute` `/stop` 실구현
- 승인 카드 UX: DM 카드 일괄승인/스킵 버튼

**❌ 명시적 분리:**
- `market_context.txt` (한지영·브리핑 메모리) → **시황봇 전용** (이슈봇 미사용)
- 52주 신고가/거래량 급증 데이터 → 별도 데이터 소스 필요. 지금은 이벤트 본문에 있는 수치만 필터가 활용.

### 3. Phase 1.5 잔여
- `approval/edit_handler.py` 분리 (현재 poller에 포함)
- `/mute` `/stop` 실구현
- Peer 매핑 자동화 (`peer_mapper.py`)

---

## 🎛 운영 설정 (서버 .env)

```bash
# 기본 (자동, 수정 불필요)
ISSUE_BOT_ENABLED=true
ISSUE_BOT_AUTO_APPROVE=false
ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_FILTER_VERIFIER_MODEL=claude-sonnet-4-5
ISSUE_BOT_FILTER_HYBRID=true
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-5
ISSUE_BOT_POLL_INTERVAL_MIN=15
ISSUE_BOT_ADMIN_MIN_PRIORITY=HIGH  # NORMAL은 로그만, 카드 안 옴
```

스팸 심하면 → `ADMIN_MIN_PRIORITY=URGENT` 로 상향
누락 느끼면 → `ADMIN_MIN_PRIORITY=NORMAL` 로 하향

---

## ⚠️ 운영 주의사항

### 텔레그램 봇 토큰
- 2026-04-22 대화창에 한 번 노출된 적 있음 (재발급 안 하기로 결정)
- **향후 절대 채팅창에 `.env` 값 붙여넣지 말 것**

### 커밋 습관
- 서버 deploy.sh가 `telegram_bot/history/` 변경을 자동으로 커밋+푸시함
- 로컬 작업 시 pull 먼저!

### 로컬 poller
- 이 세션 이전 로컬에서 돌리던 poller는 죽음 (AWS 올라가면서 불필요)
- 로컬 재시작 불요 — AWS가 주 운영 환경

---

## 🔧 트러블슈팅 명령

```bash
# 서비스 상태
sudo systemctl status telegram-bot --no-pager

# 재시작
sudo systemctl restart telegram-bot

# 실시간 로그
sudo journalctl -u telegram-bot -f

# 1회 수동 폴링 (테스트)
cd /home/ubuntu/telegram-briefing-bot
source venv/bin/activate
python -m telegram_bot.issue_bot.main once

# 긴급 중단
touch telegram_bot/history/issue_bot/KILL_SWITCH
sudo systemctl stop telegram-bot
```

---

## 📚 주요 문서

1. **`SESSION_HANDOFF.md`** (이 파일)
2. **`CLAUDE.md`** — 프로젝트 전체 개요
3. **`ISSUE_BOT_SPEC.md`** — 이슈봇 전체 설계 1,121줄
4. **`telegram_bot/history/style_canon.md`** — 스타일 경전

---

## 💬 새 세션 프롬프트 예시

```
SESSION_HANDOFF.md 먼저 읽고 현재 상태 파악해줘.
이슈봇 24시간 라이브 시작했으니 이제 Phase 2(빅테크/글로벌) 작업 시작.
```

또는:

```
어제부터 이슈봇 돌고 있어. 관리자 DM 받은 카드 품질 분석해줘.
sudo journalctl -u telegram-bot --since "yesterday" 로 로그 확인하고 주요 지표 정리.
```
