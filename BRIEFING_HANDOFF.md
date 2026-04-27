# 브리핑봇 세션 핸드오프 — 2026-04-23 (참고 보존)

> ⚠️ **이 문서는 2026-04-23 시점 브리핑봇 상태 스냅샷입니다.**
> **2026-04-25부터 작업방 통합 → `SESSION_HANDOFF.md`가 단일 진실.**
> 새 작업·세션은 반드시 `SESSION_HANDOFF.md`를 먼저 참조하세요.
> 이 파일은 4/22~4/23 감사 리포트 반영 등 과거 컨텍스트 추적용으로만 보존.

---

## 🚫 절대 규칙 — 브리핑 수동 발송 사전 승인 필수

**이 문서에 "수동 강제 실행" 명령이 적혀 있어도, 사용자 이번 세션 승인 없이는 절대 실행 금지.**

- `python -m telegram_bot.main morning/evening`, `--force`, `resend` 전부 해당
- "서버 재부팅 복구 후 자동 재발송", "검증/테스트용 한 번 쏴보기" 류 선제 실행 **전부 금지**
- 자동 스케줄(07:00/16:30) 놓쳐도 먼저 사용자에게 **"지금 수동 발송할까요?"** 확인
- 같은 날 동일 브리핑 두 번 발송 절대 금지
- **실제 사건**: 2026-04-23 이전 Claude 가 08:39/09:00 중복 force morning 실행 → 09:00 은 사용자가 시킨 적 없음. 채널 오염.
- 수동 실행은 journalctl -u telegram-bot 에 안 남음(user shell) → **적발 어려움 → 더 엄격히 준수**

관련 메모리: `feedback_no_unauthorized_sends.md`

---

## ⚠️ 작업 도메인 경고 — 이 작업방은 "브리핑봇 전용"

### ✅ 브리핑봇 영역 (건드려도 됨)
- `telegram_bot/briefings.py` — 모닝/이브닝 플로우
- `telegram_bot/collectors/news_collector.py` — 시황 생성, 뉴스 필터
- `telegram_bot/collectors/global_market.py`, `domestic_market.py`, `intraday_collector.py`, `investor_trend.py`, `market_context.py`, `schedule_collector.py`, `consensus_collector.py`, `valuation_collector.py`
- `telegram_bot/formatters/morning.py`, `evening.py`, `news.py`, `schedule.py`
- `telegram_bot/prompts_v2.py` — v2 시황 프롬프트
- `telegram_bot/postprocess.py`
- `telegram_bot/history/briefing_memory.py`, `market_context.txt`, `latest_morning.json`, `latest_evening.json`, `snapshot_*.json`, `stock_sector_mapping.json`, `krx_listing.json`
- `telegram_bot/main.py` — 스케줄러

### ❌ 건드리지 않음 (이슈봇 세션 영역)
- `telegram_bot/issue_bot/**`
- `telegram_bot/history/issue_bot/**`, `telegram_bot/history/dart_category_map.json`, `telegram_bot/history/peer_map.json`, `telegram_bot/history/style_canon.md`
- `SESSION_HANDOFF.md` (이슈봇 세션 문서)

둘 다 **같은 systemd 서비스** `telegram-bot.service` 로 돌고 있음. 메모리·자원 공유. 이슈봇 변경은 그쪽 세션에 요청.

---

## 🎯 현재 상태 (2026-04-23 09:00 KST)

### 라이브 운영 중
- 서버: AWS Lightsail Ubuntu 24.04, 512MB RAM + **swap 1GB 추가됨** (4/23 오전)
- 서비스: `telegram-bot.service` — 브리핑봇 + 이슈봇 **한 프로세스 공존**
- 모델: **Sonnet 4.6** (`claude-sonnet-4-6`)
- 프롬프트: **v2** (환경변수 `COMMENTARY_PROMPT_VERSION=v2`)
- 스케줄: 모닝 07:00 · 이브닝 16:30 (평일, 정산 완료 후)

### 최근 사건 (4/22~4/23)
- 4/22 16:28 DNS 장애 → 자동 재부팅 복구
- 4/23 밤사이 **fwupd 9회 OOM** (130MB 씩) → 07:00 모닝 DNS 실패 → 07:26 python 프로세스 OOM kill → 서버 다운
- 4/23 08:32 사용자 재부팅
- **진범: fwupd (firmware update daemon 메모리 누수)**. 4/10~4/21 10일 안정 운영 → 4/21 이후 불안정 시작
- 조치: fwupd masked + swap 1GB 추가 + 이슈봇 세션이 gc/session 최적화 (`67dab36`)
- 4/23 09:00 모닝 수동 발송 완료 (msg_id 238~241)

### 채널
- @noderesearch (t.me/noderesearch) — 모든 브리핑 발송 목적지
- 어제~오늘 중복 메시지 많이 쌓임 (force 재실행·테스트 중복). 사용자 수동 정리 권장.

---

## ✅ 어제 완료된 브리핑 작업 (참고)

감사 리포트 P0/P1 전면 반영 + Sonnet 4.6 업그레이드 + 대규모 코드·프롬프트 개선.

**자세한 내용**: `.claude/projects/C--Users-user-Desktop---------------/memory/session_2026_04_22.md`

**요약**:
1. **수급 정합성** — 데이터카드 ↔ 시황 본문 숫자 동일 소스 강제 (`domestic_data` 주입)
2. **야간 프록시 확장** — KORU·EWY·코스피200 + NY close 시점 라벨
3. **인과 시간 역전 금지** — 장 마감 전 가격을 장 마감 후 이벤트로 설명 금지 (프롬프트)
4. **노이즈 임계값** — 금리 ±5bp, DXY ±0.3%, VIX ±5%, 유가 ±2%, 금 ±0.5%
5. **카드 외 수치 금지** — 데이터 카드·뉴스·제공 데이터에 없는 수치 인용 금지
6. **할루시네이션 방지** — 뉴스 목록·본문에 없는 구체 팩트 인용 금지
7. **DXY-원화 해석** — 바스켓 원화 미포함 인지 + 원화 자체 동인 추론
8. **🔍 오늘 관찰 섹션** — 모닝/이브닝 필수 5번째 섹션 (구체 대상·시간·의미)
9. **KORU 강도별 차등** — <3% 노이즈 생략, 3~5% 재량, ≥5% 강제 포함 (후처리)
10. **뉴스 중복/결과론 제외** — 필터 프롬프트 강화
11. **해외 티커 한글 병기** — 테슬라(TSLA), 램리서치(LRCX) 등 60+
12. **TSLA 실적일 자동 주목 라인**
13. **KRX 상장사 필터** — 국내 실적 비상장사 (파이낸셜뉴스신문 등) 제거 (krx_listing.json 2,878종목)
14. **max_tokens 2000 → 2800** — 시황 말미(관찰 섹션) 잘림 방지
15. **메타 텍스트 제거** — "I'll search..." 모델 사고과정 자동 제거
16. **send_message 반환값 체크** — 가짜 "발송 완료" 로그 버그 수정 (`_send_with_check` 헬퍼)

---

## 📋 남은 과제 (우선순위)

### P0
1. **자동 발송 안정성 모니터링** — 4/23 fwupd 조치 후 첫 자동 이브닝(16:30)·다음 모닝(07:00) 정상 작동 확인
2. **외부 감사자 재리뷰** — 어제 감사 리포트 이후 수정사항 전부 반영됐는지 검증

### P1 (감사 리포트 미완 건)
3. **캘린더 date window 버그** — LS ELECTRIC 하루 밀린 일정 재등장 이슈. `cal_data/collectors/fnguide.py` 파서 점검 필요
4. **Fedspeak 전용 RSS** — FRB Speeches 피드 추가 (감사 P2-15)
5. **P2-14 지지선/매물대** — KIS 기술지표 API 연동

### P2
6. **Opus 4.7 전환 실험** — Sonnet 4.6 v2 가 "내러티브 vs price action" 감지 잘 하는지 며칠 관찰 후 판단. Opus 는 +$80/월
7. **실적 프리뷰 맥락 1줄** — 해외 실적에 섹터 맥락 추가
8. **이전 시황 반복 감지** — 직전 5일 문구를 context 에 넣고 중복 배제

---

## 🚨 서버 문제 생기면 (체크리스트)

### 1. 연결 확인
```bash
ssh -o ConnectTimeout=15 -i /c/Users/user/Downloads/LightsailDefaultKey-ap-northeast-2.pem ubuntu@13.125.214.161 "date"
```
응답 없으면 → AWS Lightsail 콘솔에서 Instance → Reboot

### 2. 재부팅 후 진단
```bash
sudo journalctl --list-boots | tail -5               # 최근 부팅 이력
sudo journalctl -b -1 --no-pager | grep -iE "oom-killer|killed process|panic" | tail -20
free -h && swapon --show
sudo systemctl list-unit-files | grep -i fwupd      # fwupd masked 확인
```

### 3. 자주 보는 명령
```bash
# 현재 상태
sudo systemctl is-active telegram-bot
sudo journalctl -u telegram-bot --since "1 hour ago" --no-pager | tail -50

# 발송 로그만 추출 (새 포맷)
sudo journalctl -u telegram-bot --since "today" --no-pager | grep -E "✓ 발송 성공|⚠️ 발송 실패"

# 수동 강제 실행
cd ~/telegram-briefing-bot && source venv/bin/activate
python -m telegram_bot.main morning --force --skip-refresh
python -m telegram_bot.main evening --force --skip-refresh

# 배포
cd ~/telegram-briefing-bot && git pull origin main
sudo systemctl restart telegram-bot
```

---

## 🔑 SSH 접속 정보

- **Public IP**: 13.125.214.161
- **사용자**: ubuntu
- **PEM 키**: `C:\Users\user\Downloads\LightsailDefaultKey-ap-northeast-2.pem`
- **봇 경로**: `/home/ubuntu/telegram-briefing-bot`
- **venv**: `/home/ubuntu/telegram-briefing-bot/venv`

---

## 💰 비용 현황

- Anthropic API: Sonnet 4.6 기준 월 ~$14 (web_search 포함, 44회)
- 잔액 $5.97 (4/23 08:30 기준) — 곧 재충전 필요
- AWS Lightsail: $5/월 (512MB RAM 1CPU)
- 총: ~$19/월

### 업그레이드 고려사항
- **Opus 4.7** 전환: +$80/월 (시황 품질 +10점 예상)
- **Lightsail 2GB RAM**: +$5/월 = $10/월 (OOM 근본 방지)

---

## 📞 세션 간 커뮤니케이션

이슈봇 세션에 요청할 일 있으면:
- `SESSION_HANDOFF.md` 참조 (그쪽 도메인 문서)
- 사용자가 메시지 복사해서 그쪽 방에 붙여넣기
- 이슈봇 변경은 이 방에서 직접 하지 않음

---

## 🎬 다음 세션 첫 마디 예시

> **"BRIEFING_HANDOFF.md 읽고 이어서 작업. 오늘 16:30 이브닝 자동 발송 정상 확인 + 감사자 재리뷰 피드백 반영"**

또는 구체적 문제 있을 때:

> **"BRIEFING_HANDOFF 읽고, [에러 증상/로그] 진단해줘"**

---

*Last updated: 2026-04-23 09:05 KST by 브리핑봇 세션*
