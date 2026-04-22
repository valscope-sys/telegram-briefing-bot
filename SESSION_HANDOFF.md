# 세션 핸드오프 — 2026-04-22

**다음 세션에서 이 파일을 먼저 읽어주세요.** (이전 대화 요약 + 현재 상태)

---

## 🎯 현재 상황 요약

실시간 이슈봇 **Phase 1 MVP 구현 완료 + 로컬 테스트 진행 중**, 배포 직전 단계.

---

## ✅ 완료된 작업 (이번 세션)

### Phase 0 — 인프라 (완료)
- DART API 키 발급 + `.env`에 저장
- 관리자 chat_id 취득 (`TELEGRAM_ADMIN_CHAT_ID=5033358048`)
- 메리츠 Tech 채널 샘플 70+개 학습

### Phase 1 — MVP (완료)
10개 모듈 구현:
- `telegram_bot/issue_bot/collectors/dart_collector.py` — DART 폴링 + 증분 커서
- `telegram_bot/issue_bot/collectors/rss_adapter.py` — 기존 RSS 16개 재활용
- `telegram_bot/issue_bot/pipeline/filter.py` — **Hybrid 필터 (Haiku→Sonnet 재검증)**
- `telegram_bot/issue_bot/pipeline/dedup.py` — 구조화 해시 중복 감지
- `telegram_bot/issue_bot/pipeline/generator.py` — Sonnet + style_canon + 캐싱
- `telegram_bot/issue_bot/pipeline/linter.py` — R1~R8 자동 린트
- `telegram_bot/issue_bot/approval/bot.py` — 하이브리드 승인 카드 State 1/2
- `telegram_bot/issue_bot/approval/poller.py` — 콜백 + 수정 답장 + 타임아웃
- `telegram_bot/issue_bot/utils/telegram.py` — DM/채널/보호구간/락/og:image
- `telegram_bot/issue_bot/main.py` — 폴링 루프

### 테스트 결과
- **Test A (스킵)**: ✅ 통과
- **Test B (채널 발송)**: ✅ 통과 (channel_msg_id 193, race 수정 완료)
- **Test C (AWS 배포)**: ⏸ 일시 중단 — 로컬 커밋은 완료 (`5744c8b`), **push 아직 안 함**

### Claude.ai 데스크탑 앱 A/B 비교 완료
- Haiku vs Sonnet 4.5 30건 테스트 → **일치율 83%**
- Sonnet이 5건 모두 더 정확 (HIGH↔NORMAL 경계에서)
- **결론: Hybrid 채택** (Haiku 1차 → HIGH/NORMAL이면 Sonnet 재검증)

### 최종 튜닝 (이 세션에서 반영)
- `주식등의대량보유상황보고서` (5% 공시): HIGH → **SKIP**
- `감사보고서` / `연결감사보고서`: NORMAL → **SKIP**
- `단일판매ㆍ공급계약체결`: HIGH → **NORMAL** (body 보고 Sonnet 판단)
- 환경변수 `ISSUE_BOT_ADMIN_MIN_PRIORITY=HIGH` (기본값) — NORMAL은 카드 X, 로그만

### 3대 안정성 개선 (최종)
- `rcept_no 증분 폴링` — 신규만 처리, 중복 방지
- `max_cards_per_poll=3` — 카드 몰빵 방지
- `first_run_limit=10` — 첫 실행 조용히 시작

---

## 📦 커밋 + 배포 상태

### 로컬 Git
- 로컬 커밋 완료: `5744c8b feat: 실시간 이슈봇 Phase 1 MVP 추가` (30 files, 5,514 insertions)
- **Push 거부됨** (main 직접 push 권한 이슈) — 사용자가 다음 중 선택 필요:
  1. 명시적 "main push 허가" → 저 재시도
  2. 수동 push: `git push origin main`
  3. 피처 브랜치 PR

### 이후 추가 수정 (Hybrid + 튜닝 + 증분 폴링 + RSS 재통합) — **커밋 안 됨**
다음 커밋에 들어갈 파일:
- `telegram_bot/config.py` (HYBRID 플래그 추가)
- `telegram_bot/issue_bot/pipeline/filter.py` (Sonnet 재검증 로직)
- `telegram_bot/issue_bot/collectors/dart_collector.py` (증분 커서)
- `telegram_bot/issue_bot/collectors/rss_adapter.py` (NEW — 한 번 사라졌다가 복원됨)
- `telegram_bot/issue_bot/main.py` (RSS 통합, max_cards, 증분)
- `telegram_bot/history/dart_category_map.json` (감사보고서/5% 공시 SKIP)
- `scripts/dryrun_filter.py`, `scripts/benchmark_filter_models.py`, `scripts/export_claude_testpack.py` (테스트용)

---

## 🗂 상태 파일

### 살아있는 상태
- `telegram_bot/history/issue_bot/last_rcept_no.txt` = `20260422900085` (커서)
- `telegram_bot/history/issue_bot/seen_ids.jsonl` — 중복 방지
- `telegram_bot/history/issue_bot/sent/2026-04-21.jsonl` — Test B 발송 이력
- `telegram_bot/history/issue_bot/rejected/2026-04-21.jsonl` — Test A 스킵 이력
- `telegram_bot/history/issue_bot/poller.lock` — (만약 남아있으면) stale 자동 해제됨

### gitignored
- `pending/`, `poller.lock`, `poller_offset.txt`, `KILL_SWITCH`, `.claude/settings.local.json`

---

## 🎛 현재 운영 설정

```bash
# .env
TELEGRAM_ADMIN_CHAT_ID=5033358048
DART_API_KEY=<발급됨>
# ISSUE_BOT_* 는 코드 기본값 사용:
#   ENABLED=true
#   AUTO_APPROVE=false
#   FILTER_MODEL=claude-haiku-4-5-20251001
#   FILTER_VERIFIER_MODEL=claude-sonnet-4-5
#   FILTER_HYBRID=true
#   GENERATOR_MODEL=claude-sonnet-4-5
#   ENABLE_CACHING=true
#   POLL_INTERVAL_MIN=15
#   URGENT_TIMEOUT_MIN=15
#   HIGH_TIMEOUT_MIN=45
#   NORMAL_TIMEOUT_MIN=120
#   EDIT_TIMEOUT_MIN=15
# ADMIN_MIN_PRIORITY=HIGH (기본, 사용자 선택)
```

**사용자 방금 확정**: `ADMIN_MIN_PRIORITY=HIGH` 유지 (NORMAL은 카드 안 옴)

---

## 🚦 다음 세션에서 할 일 (우선순위 순)

### 1. 추가 변경사항 커밋 + 배포
```bash
cd "C:\Users\user\Desktop\텔레그램 시황 브리핑"
git add telegram_bot/config.py telegram_bot/issue_bot/ \
        telegram_bot/history/dart_category_map.json \
        scripts/*.py SESSION_HANDOFF.md
git commit -m "feat: Hybrid 필터 + 증분 폴링 + 튜닝"
git push origin main   # 권한 이슈 시 사용자 직접 실행 필요
```

### 2. AWS Lightsail 배포 확인
- deploy.sh 크론이 pull & systemd restart 수행
- 다음 크론: **06:30, 15:30, 17:00 KST**
- 서버에서 `systemctl status telegram-bot` + 로그 확인

### 3. 라이브 운영 관찰
- 관리자 DM에 카드 오는지 확인
- 필요 시 `ADMIN_MIN_PRIORITY` 조정 (HIGH→NORMAL이면 더 많이)

### 4. Phase 1.5 백로그
- `approval/edit_handler.py` 분리 (현재 poller에 포함)
- `approval/commands.py` `/mute` `/stop` 실구현
- Peer 매핑 웹검색 자동화 (`peer_mapper.py`)
- TrendForce/Digitimes RSS 직접 연동 (해외 IR 뉴스 커버리지 확장)

### 5. 알려진 미해결
- Windows cp949 콘솔 인코딩 — 스크립트에 utf-8 reconfigure 추가했으나 bash 일부 잔존
- DART `report_nm` "[기재정정]주요사항보고서(타법인주식및출자증권양수결정)" 같이 key 완전일치 실패 건 → Haiku fallback이 처리 (현재 큰 문제 없음)

---

## 📚 주요 문서 (읽을 순서)

1. **`SESSION_HANDOFF.md`** (이 파일) — 최근 세션 전체 상태
2. **`CLAUDE.md`** — 프로젝트 전체 개요 + 브리핑봇 + 이슈봇 포인터
3. **`REVIEW_SUMMARY.md`** — 외부 개발자용 14섹션 리뷰 (아키텍처/LOC/비용/리스크)
4. **`ISSUE_BOT_SPEC.md`** — 이슈봇 전체 설계 1,121줄 (R1~R8, Template A~E, 33 섹터, Phase 로드맵)
5. **`telegram_bot/history/style_canon.md`** — Claude에 주입되는 스타일 경전

---

## 🔧 빠른 동작 확인 명령

```bash
cd "C:\Users\user\Desktop\텔레그램 시황 브리핑"

# 1회 폴링 (실제 카드 발송)
python -m telegram_bot.issue_bot.main once

# dry-run (카드 안 보내고 분류만)
python scripts/dryrun_filter.py --days 1

# 배포 전 DART 테스트
python scripts/test_dart_api.py

# Claude.ai 테스트팩 재생성
python scripts/export_claude_testpack.py --max 30

# 멈추기: history/issue_bot/KILL_SWITCH 파일 생성
```

---

## 💬 새 세션 시작 시 쓸 프롬프트 예시

```
이 프로젝트 이어서 작업할게. SESSION_HANDOFF.md 읽어서 현재 상태 파악해줘.
그 다음 [구체적 작업 지시]
```

또는:

```
실시간 이슈봇 Phase 1 배포 작업 이어서 진행. SESSION_HANDOFF.md + CLAUDE.md 참조.
지금 상태에서 git push부터 진행해줘.
```
