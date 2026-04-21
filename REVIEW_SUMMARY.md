# NODE Research 텔레그램 봇 — 개발자 리뷰 요약

**목적**: 외부 개발자가 10~15분 안에 전체 시스템을 파악하고 코드 품질/설계/리스크를 리뷰할 수 있도록 정리.

**작성일**: 2026-04-21

---

## 1. 프로젝트 한 줄

KIS(한국투자증권) Open API + Claude API + DART 공시 + RSS를 활용해 텔레그램 채널(`@noderesearch`)에 **자동 시황 브리핑(하루 2회, 8개 메시지) + 실시간 이슈 알림(승인제)**을 발송하는 봇.

---

## 2. 두 개의 독립 모듈

| 모듈 | 역할 | 상태 | 핵심 파일 |
|------|------|------|-----------|
| **기존 브리핑봇** (`telegram_bot/`) | 평일 07:00 모닝, 16:30 이브닝 자동 발송 (각 4메시지) | **프로덕션 운영 중** (AWS Lightsail) | `main.py`, `briefings.py`, `collectors/` |
| **신규 이슈봇** (`telegram_bot/issue_bot/`) | DART 공시 감지 → Claude 요약 → 관리자 승인 → 채널 발송 | **Phase 1 MVP 완료, 배포 직전** | `main.py`, `pipeline/`, `approval/` |

**두 모듈은 독립 모듈이지만** 같은 프로세스에서 APScheduler로 잡 등록. 동일 텔레그램 봇 토큰(`@noderesearch_bot`)을 공유, 동일 채널로 발송.

---

## 3. 전체 파이프라인 (이슈봇)

```
┌──────────────┐   ┌──────────┐   ┌────────────┐   ┌──────────────┐
│ DART API 폴링 │ → │ Haiku 필터│ → │ 관리자 DM   │ → │ 사용자 버튼 │
│ 15분 간격    │   │ priority │   │ (State 1)  │   │ 클릭        │
│ (보호구간제외) │   │ category │   │ 원문 발췌  │   │             │
└──────────────┘   └──────────┘   └────────────┘   └──────┬───────┘
                                                          │
               ┌─────────────┬───────────┬───────────────┬┘
               ▼             ▼           ▼               ▼
          [👁 미리보기]  [✅ 바로발송] [✏️ 수정]    [❌ 스킵]
               │             │           │               │
               ▼             ▼           ▼               ▼
        Sonnet 생성      Sonnet 생성   (생성+답장 대기)   pending 제거
            │               │                              → rejected/
            ▼               ▼
        State 2 카드    @noderesearch
        (재표시)         채널 발송
                            │
                            ▼
                        sent/ 이력 저장
```

**핵심 설계 원칙**:
1. **하이브리드 생성** — 승인 전에는 Sonnet 호출 X. 거절되면 비용 $0.
2. **메리츠 Tech 채널 70+ 샘플 학습** — R1~R8 하드 규칙으로 Claude가 일관된 포맷 생성.
3. **기존 브리핑과 독립** — 16:20~16:50 보호구간에 이슈봇은 자동 중단.

---

## 4. 이슈봇 코드 통계 (LOC)

### 신규 이슈봇 모듈 (총 2,542 LOC Python + 1,139 LOC 데이터/스펙)

| 파일 | 역할 | LOC |
|------|------|-----|
| `approval/bot.py` | 승인 카드 렌더링/발송/상태전환 | 468 |
| `utils/telegram.py` | Bot API 래퍼, 보호구간, KILL_SWITCH, 락 | 365 |
| `collectors/dart_collector.py` | DART 폴링 + KIND HTML 추출 + 룰 매칭 | 348 |
| `approval/poller.py` | 롱폴링 콜백 처리 + 수정 답장 + 중복 감지 | 330 |
| `pipeline/generator.py` | Claude Sonnet + 프롬프트 캐싱 + 린트 재시도 | 246 |
| `pipeline/filter.py` | Haiku 필터 + rule-based 하이브리드 | 230 |
| `pipeline/dedup.py` | 구조화 해시 키 중복 감지 | 216 |
| `pipeline/linter.py` | R1~R8 정규식 자동 검증 | 164 |
| `main.py` | 폴링 루프 + `telegram_bot/main.py` 통합 인터페이스 | 161 |
| **합계 (Python)** | | **2,528** |

### 설정/데이터/문서

| 파일 | 역할 | LOC |
|------|------|-----|
| `ISSUE_BOT_SPEC.md` | 전체 설계 명세 (R1~R8, Template A~E, Phase 로드맵) | 1,121 |
| `history/peer_map.json` | 해외기업→국내 종목 매핑 49개 시드 | 453 |
| `history/style_canon.md` | Claude에 주입할 "스타일 경전" (R1~R8 + 완벽 예시 11개) | 366 |
| `history/dart_category_map.json` | DART `report_nm` → Template/Priority 매핑 46건 | 320 |
| `scripts/test_dart_api.py` | DART API 검증 (Phase 0) | 135 |
| `scripts/get_admin_chat_id.py` | 관리자 chat_id 취득 | 108 |

### 기존 브리핑봇 (참고, 수정 X)

| 파일 | LOC |
|------|-----|
| `collectors/news_collector.py` | 968 |
| `collectors/domestic_market.py` | 667 |
| `collectors/schedule_collector.py` | 367 |
| `briefings.py` | 333 |
| 기타 30+ 파일 | ~3,000 |

---

## 5. 기술 스택

- **언어**: Python 3.12
- **스케줄러**: `apscheduler` (`BlockingScheduler` + `CronTrigger`)
- **외부 API**: 
  - Anthropic Claude (Haiku 4.5 필터 + Sonnet 4.5 생성, 프롬프트 캐싱)
  - Telegram Bot API (sendMessage, sendPhoto, getUpdates 롱폴링, callback_query)
  - DART OpenAPI (`opendart.fss.or.kr`)
  - KIS Open API (한국투자증권)
  - 키움 REST API (52주 신고가)
  - yfinance (해외 지수/원자재)
- **파싱**: `BeautifulSoup4` + `lxml`
- **상태 저장**: 파일 시스템 (JSON + JSONL) — DB 없음
- **배포**: AWS Lightsail Ubuntu 24.04, `systemd telegram-bot.service`, deploy.sh 크론
- **비용**: 기존 브리핑 $5/월 + 이슈봇 예상 $2~4/월 (하이브리드 + 프롬프트 캐싱)

---

## 6. 주요 데이터 모델

### 이슈 이벤트 (`pending/{id}.json`)

```json
{
  "id": "dart_20260421000123",
  "dedup_key": "005930:자사주:2026-04-21:a3f8e9d1",
  "source": "DART|RSS",
  "source_url": "https://dart.fss.or.kr/...",
  "priority": "URGENT|HIGH|NORMAL",
  "category": "A|B|C|D|E",       // Template 종류
  "sector": "반도체",
  "ticker": "005930",
  "company_name": "삼성전자",
  "title": "주요사항보고서(자기주식취득결정)",
  "original_content": "원문 전체",
  "original_excerpt": "원문 앞 500자 (State 1 카드용)",
  "generated_content": "Claude 생성본 (State 2 카드 = 최종 발송본)",
  "has_generated": false,
  "peer_map_used": ["삼성전기"],
  "peer_confidence": 0.95,
  "violations": [],
  "status": "pending_raw|pending_preview|pending_edit|sent|rejected|timeout|edited",
  "expires_at": "2026-04-21T18:51:51+09:00",
  "telegram_admin_msg_id": 123,
  "telegram_channel_msg_id": 456,
  "tokens_used": {"filter": 120, "gen": 580, "cache_read": 7078},
  "cost_krw": 45
}
```

### 이력 디렉토리

```
history/issue_bot/
├── pending/        # 승인 대기 (우선순위별 TTL 15/45/120분)
├── sent/           # 승인+발송 완료 (일별 JSONL)
├── rejected/       # 거절 (학습용)
├── edited/         # 관리자 수정 후 발송 (diff 포함)
├── seen_ids.jsonl  # 중복 방지 키 누적
├── cache_stats.jsonl  # Claude 캐시 히트율 일별 로깅
├── poller.lock     # 단일 인스턴스 락 (PID:timestamp)
└── KILL_SWITCH     # 긴급 중단 파일 (존재하면 모든 폴링 중단)
```

---

## 7. 핵심 Flow 3가지

### Flow A. DART 공시 → 카드 발송 (읽기 전용, 비용 낮음)

```python
# telegram_bot/issue_bot/main.py:issue_bot_poll_once()
events = collect_disclosures(days_back=1)          # DART API
for event in events:
    if is_duplicate(generate_dedup_key(event)): continue
    classification = filter_event(event)            # Rule or Haiku
    if classification['priority'] == 'SKIP': continue
    send_raw_approval_card({...event, ...classification})
```

**비용**: DART 폴링 무료. Haiku 필터 $0.0013/건 (룰 매칭되면 스킵).

### Flow B. 관리자 [✅ 바로 발송] 클릭 → 채널 발송

```python
# poller.py:_handle_callback
if action == "approve_direct":
    answer_callback_query(cb_id, "생성 + 발송 중...")
    result = approve_and_send(issue_id)
    # approve_and_send: 생성 안됐으면 generator.generate_with_retry → send_channel_message
```

**비용**: Sonnet 생성 $0.007/건 (캐시 히트 시). 이 단계에서만 과금.

### Flow C. [✏️ 수정] → 답장 대기 → 수정본 발송

```python
# poller.py:_start_edit_flow → _handle_edit_reply
1. 원본 생성 (아직 안됐으면) → force_reply DM 발송
2. 사용자가 force_reply에 답장 → reply_to_message_id로 매칭
3. 수정본 R1~R8 린트 → 위반 시 경고
4. 통과 시 send_to_channel + mark_decision("edited")
5. edited/YYYY-MM-DD.jsonl에 diff 저장 (학습용)
```

---

## 8. Claude API 사용 패턴

### 필터 (Haiku 4.5)
- **System prompt**: R1~R8 섹터 분류 기준 (~2KB, 캐시 불필요)
- **User**: 이벤트 원문 요약
- **Output**: `{"priority", "sector", "category", "reason"}` JSON
- **비용**: $0.0013/호출

### 생성 (Sonnet 4.5 + 프롬프트 캐싱)
- **System prompt**: `style_canon.md` 전체 (~8KB, R1~R8 + Template 완벽 예시 11개)
  - `cache_control: {"type": "ephemeral"}` 적용 → 5분 TTL
  - 실측 캐시 hit: 7,078 tokens (style_canon 전체)
- **User**: 이벤트 메타 + 원문 + Peer 매핑
- **Output**: 메리츠 Tech 스타일 본문 (Template A~E)
- **Retry**: R1~R8 린트 실패 시 1회 재시도 (위반 항목을 프롬프트에 제약 주입)
- **비용**: $0.007/호출 (캐시 적용)

---

## 9. 설계 결정 5가지

### D1. 왜 "하이브리드 승인 카드" (State 1/2 분리)?
**문제**: 승인카드에 Claude 생성본을 미리 포함하면, 거절 시 생성 비용이 낭비됨 (월 100건 거절 시 $7 낭비).
**해결**: State 1은 원문 발췌만 (비용 $0), 관리자가 [미리보기] 클릭하거나 [바로 발송] 클릭 시에만 생성.
**절감**: 월 비용 $5 → $2~3 (40%)

### D2. 왜 R1~R8 하드 규칙 + 완벽 예시 조합?
**문제**: Claude가 메리츠 스타일을 "대강 흉내 내면" 품질 편차 큼 (급등/폭등 같은 금지 표현 재등장).
**해결**: 
- R1~R8을 정규식 린트로 자동 검증
- `style_canon.md`에 **완벽 예시 11개 명시** (few-shot)
- 위반 시 재생성 자동 시도
**근거**: 메리츠 Tech 채널 70+ 샘플을 패턴 분석해 도출

### D3. 왜 파일 시스템 기반 상태 (DB 없음)?
**이유**: 
- 하루 ~30건 처리 → DB 오버엔지니어링
- JSON 읽기/쓰기로 충분, `git push`로 상태 백업 (기존 브리핑봇 패턴 재사용)
- 단점: 파일 개수 늘면 느려질 수 있음 (sent/ scan O(N))

### D4. 왜 롱폴링 (webhook 대신)?
**이유**: 
- AWS Lightsail 서버에 공개 HTTPS endpoint 설정 안 됨
- 롱폴링은 outbound only → 방화벽 복잡도 0
- `timeout=25s` 최적화 → 폴링 오버헤드 무시할 만함

### D5. 왜 APScheduler 단일 프로세스?
**이유**: 
- 기존 브리핑봇과 같은 프로세스 → state 공유 쉬움 (보호구간 감지)
- 백그라운드 스레드(`daemon=True`)로 poller 돌림
- 단점: 프로세스 크래시 시 둘 다 멈춤 (`systemd` auto-restart로 완화)

---

## 10. Race Condition + 수정 (v1.1)

### 발견된 문제
Test B(실제 채널 발송)에서 콜백이 두 번 처리되어 "발송 실패: pending not found" 스퓨리어스 에러 발생. 실제 발송은 1회만 성공.

### 가설
- Telegram 콜백 이중 배달 (네트워크 재전송)
- 더블클릭
- 두 개의 poller 프로세스가 동시에 getUpdates (아마도 테스트 중 stale 프로세스)

### 적용한 수정 (모두 완료)
1. **단일 인스턴스 락** (`poller.lock` 파일 + 2분 stale 자동 해제)
2. **콜백 ID 메모리 dedup** (`_processed_callbacks`, 5분 윈도우)
3. **approve_and_send 멱등성** (`_is_already_sent` 체크 → 이미 sent면 OK 반환)

### 검증
- 락: 두 번째 획득 시도 즉시 False 반환 ✓
- 콜백 dedup: 같은 ID 두 번째 호출 시 True 반환 ✓
- 멱등성: 이미 sent된 ID로 approve 호출 시 `already_sent: True` 반환 ✓

---

## 11. 알려진 제약 + TODO

### Phase 1 MVP 완료
- DART 공시 수집 + 룰/Haiku 분류
- Sonnet 생성 + R1~R8 린트
- 관리자 DM 승인 카드 (하이브리드)
- Poller 콜백 + 수정 답장
- 채널 발송 + 이력 저장

### Phase 1.5 (2주 내)
- [ ] Peer 매핑 자동 추론 (Claude + web_search tool)
- [ ] RSS 연계 (기존 `news_collector.py` 재활용)
- [ ] `/mute`, `/stop`, `/confirm_send` 명령 처리
- [ ] 묶음 승인 버튼 (NORMAL 카드 다수 쌓였을 때)
- [ ] KPI 추적 (월별 approved / rejected / edited 비율)

### Phase 2 (추후)
- [ ] 33개 섹터 전체 오픈 (현재 MVP는 반도체/IT부품/2차전지 3개)
- [ ] DART 외 추가 소스 (TrendForce, Prismark, Digitimes 크롤링)
- [ ] DART 공시 스크린샷 첨부 (Playwright 필요)
- [ ] 학습 루프 (rejected/edited 이력 분석 → 필터/스타일 개선)

### 미해결/의문점
1. **프롬프트 캐싱 TTL 5분 vs 폴링 15분** — 대부분 cache miss 가능. 실측 로깅 중 (`cache_stats.jsonl`). 히트율 낮으면 폴링 주기 축소 검토.
2. **DART API 응답 지연 5~15분** — "실시간" 기준은 DART 노출 시점, 사건 발생 시점이 아님. SPEC에 명기.
3. **KIND HTML iframe 파싱** — 현재 `viewDoc` 정규식 매칭 사용. Dart 페이지 구조 변경 시 깨질 수 있음.

---

## 12. 리뷰하실 분께 특히 봐주시면 좋을 것

### 코드 품질
- **에러 처리**: 예외 클래스 사용 최소화, 대부분 `try/except + 로그 + 빈값 반환` 패턴 (정상?)
- **타입 힌트**: 일부 함수만 있음 (일관성 부족)
- **테스트**: 단위 테스트 없음 (`__main__` 블록의 스모크 테스트만)

### 아키텍처
- **파일 I/O 빈도**: 콜백마다 JSON read/write. 하루 50건 규모엔 문제 없지만, 스케일 아웃 가능성?
- **단일 프로세스 리스크**: 크래시 시 모든 기능 중단
- **상태 동기화**: AWS 서버 상태 ↔ Git 저장소 (deploy.sh의 `git add history/ → commit → push` 패턴). 충돌 처리?

### 보안
- **.env 비밀 관리**: 단순 파일. 로테이션 프로세스 없음 (이번 세션에 실수로 키 노출 발생)
- **관리자 인증**: `TELEGRAM_ADMIN_CHAT_ID` 단일 ID로 신뢰. Admin chat ID 탈취 시 악용 가능

### 비용
- 현재 추정 월 $7~10 (브리핑 $5 + 이슈봇 $2~4)
- 트래픽 2배 증가 시 비용 선형 증가

---

## 13. 핵심 파일 링크 (Git 기준)

- [CLAUDE.md](CLAUDE.md) — 프로젝트 전체 개요
- [SYSTEM_SPEC.md](SYSTEM_SPEC.md) — 기존 브리핑봇 명세
- [ISSUE_BOT_SPEC.md](ISSUE_BOT_SPEC.md) — 이슈봇 전체 설계 (1,121 LOC 상세)
- [telegram_bot/issue_bot/main.py](telegram_bot/issue_bot/main.py) — 진입점
- [telegram_bot/issue_bot/pipeline/generator.py](telegram_bot/issue_bot/pipeline/generator.py) — Claude 생성 로직 핵심
- [telegram_bot/issue_bot/approval/poller.py](telegram_bot/issue_bot/approval/poller.py) — 인터랙션 핵심
- [telegram_bot/history/style_canon.md](telegram_bot/history/style_canon.md) — Claude에 주입되는 스타일 규칙

---

## 14. 질문받을 만한 것 5가지 (미리 답변)

**Q1. 왜 Claude? GPT-4는 안 썼나요?**
A. Anthropic API가 Claude 4.5/4.6 기준으로 Sonnet 가성비 최고 + 프롬프트 캐싱 적용 시 비용 1/10. 기존 브리핑봇이 Claude 기반이라 모델 통일.

**Q2. 봇이 잘못된 요약 보내면 어떻게 되나요?**
A. 모든 발송은 관리자 수동 승인 필수 (auto_approve=False 기본). 승인 전에 [👁 미리보기]로 전체 확인 가능. 추가로 R1~R8 자동 린트가 극단 표현/추천/호재악재 등 자동 차단.

**Q3. 스케일이 가능한가요? 하루 공시 1,000건 되면?**
A. 현재 룰 매칭이 SKIP 판정해서 실제 필터/생성 대상은 하루 50건 수준. 1,000건이 전부 타겟이면 Haiku 필터 비용 $1/일로 증가. 승인 폭주 시 묶음 승인 버튼(Phase 1.5)으로 완화.

**Q4. 기존 브리핑봇과 충돌 우려는?**
A. 16:20~16:50 / 06:50~07:10 보호구간에 이슈봇 폴링 자동 스킵. 동일 봇 토큰 공유하지만 채널 발송은 분당 20개 제한 내 여유 큼. 같은 파일 시스템은 `history/issue_bot/` 하위로 격리.

**Q5. 이 모델 결정이 최선인가?**
A. 시나리오 D (Haiku 필터 + Sonnet 생성 + 캐싱)가 품질/비용 균형상 최적. 품질 부족 시 `.env`로 Opus 업그레이드 가능 (월 $25 → $275로 급증하므로 MVP 2주 운영 검증 후 결정).
