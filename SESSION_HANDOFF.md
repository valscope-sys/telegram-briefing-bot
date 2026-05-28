# 통합 세션 핸드오프 — 2026-05-28 (오후 update)

**모든 작업(브리핑봇 + 이슈봇)이 이 한 문서로 통합 운영됩니다.**

---

## 🔥 2026-05-28 최신 변경 — 시황 품질 대수술

### 오늘 commit (서버 배포 대기 중)

| commit | 내용 |
|---|---|
| `429d095` | 시황 본문 평문 흐름 + 데이터 카드 레이아웃 복원 + ETF 필터 |
| `136fd0f` | 첫 문장 메타 텍스트 + 마지막 문단 외국인 선물 고정 폐기 |
| `0543d54` | "강제 다양성" 톤 제거 — 시황의 자연스러움 우선 |
| `205266b` | **한지영 컨텍스트 자동 갱신 16일째 멈춤 fix** — 모델 fallback 체인 |

### 🚨 사용자 답답 누적 문제 (해결 진행 중)

5/12 ~ 5/27 사이 누적된 문제:
1. ✅ **시황 본문 섹션 헤더** (📈🔍🔄💰⚠️) 매번 들어옴 → 평문 5문단으로 폐기
2. ✅ **"검색이 필요한 항목을 먼저 확인합니다" 메타 텍스트** 첫 줄 노출 → 14가지 금지 명시
3. ✅ **마지막 문단 "외국인 선물 포지션" 1달째 고정** → 예시 문구 폐기 + 8가지 다양화
4. ✅ **리스크 매번 호르무즈 반복** → 같은 표현 반복 회피 (강제 X)
5. ✅ **데이터 카드 KOSPI/수급 라인 누락** (내가 5/12에 깨뜨림) → 5c25436 형식 복원
6. ✅ **IBK·HK·KCGI 같은 ETF 신고가 섞임** → exclude_kw 11개 추가
7. ✅ **한지영 컨텍스트 16일째 안 갱신** → 모델 fallback 체인 추가

### 🚧 남은 미해결 문제 (다음 세션 우선 처리)

#### Task #4 — sector_universe 시스템 검증 (가장 큰 누적 문제)
- **5/13부터 신고가 모두 "기타"로 분류** — 21~24/24 모두 기타
- sector_universe 06:00 cron이 실행되는지, KRX 지수 코드(1028 등 추정값)가 정확한지 검증 안 됨
- pykrx Windows 인코딩 영구 이슈 → Linux 서버 첫 cron 결과로만 검증 가능

**5/28 진단 (로컬)**: `sector_universe_latest.json` (5/26) 전 26개 섹터 모두 0건 / 모두 failures.
로컬은 pykrx Windows 이슈로 예상 결과이지만, **이전 정상 데이터마저 0건 결과로 덮어쓰여진 상태**.
→ `save_universe()`에 가드 추가 (commit 5e8a777 이후): 전 섹터 실패 시 latest_link 덮어쓰기 스킵.
서버에 배포되면 다음부터는 일시 장애도 이전 정상 데이터 보존.

**서버에서 실행할 검증 명령**:
```bash
# 1) 파일 상태 — 가장 최근 정상 생성일 확인
ls -la ~/telegram-briefing-bot/telegram_bot/history/sector_universe*.json | tail -10

# 2) latest 내용 (섹터별 종목 수, failures)
~/telegram-briefing-bot/venv/bin/python3 -c "
import json
with open('/home/ubuntu/telegram-briefing-bot/telegram_bot/history/sector_universe_latest.json') as f:
    u = json.load(f)
print('trd_dd:', u.get('trd_dd'))
print('generated_at:', u.get('generated_at'))
print('failures:', len(u.get('failures', [])), '/', len(u.get('sectors', {})))
for n, c in u.get('sectors', {}).items():
    print(f'  {n}: {len(c)}')
"

# 3) 06:00 cron 실행 로그 (어제+오늘)
sudo journalctl -u telegram-bot --since "yesterday 05:30" --no-pager | grep -E "FETCHER|sector_universe" | head -40

# 4) pykrx 직접 호출 — 반도체 지수 1028
cd ~/telegram-briefing-bot && venv/bin/python3 -c "
from pykrx import stock
import datetime
date_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y%m%d')
print('Date:', date_str)
tickers = stock.get_index_portfolio_deposit_file(date_str, '1028')
print('반도체(1028):', len(tickers) if tickers is not None else 'None')
print('샘플:', list(tickers)[:5] if tickers is not None else None)
"

# 5) 수동 1회 실행 — cron 디버깅 (출력 보면 어느 섹터에서 실패하는지 즉시 확인)
cd ~/telegram-briefing-bot && venv/bin/python3 -m telegram_bot.collectors.sector_universe_fetcher
```

**결과 해석 가이드**:
- 모든 섹터 200건 이상 → 정상. 신고가 분류도 정상화될 것
- KRX_index만 실패, ETF만 성공 → 지수 코드 잘못. `sector_config.json`의 code 검증 필요
- 전 섹터 0건 → pykrx Linux도 실패. KRX API 자체 변경 의심, raw HTTP 호출 검토
- pykrx 직접 호출은 OK인데 cron만 실패 → 환경변수·작업 디렉토리·권한 문제

#### Task #9·#10·#11 — 시황 품질 ↑ (한지영 수준)
한지영 5/28 모닝과 비교 시 우리 봇이 잡지 못한 것:
- **시장 폭 데이터** (상승 75 / 하락 823 / 차이 -748개) + 역사적 비교
- **거래대금 집중도** ("전일 거래대금 90%가 삼성·SK하이닉스 집중")
- **차주 일정 자연 녹임** (PCE·FOMC 일정을 본문에 자연스럽게)

→ 데이터는 이미 collector에 있음. prompts_v2.py 가이드만 추가하면 됨.

### 🚀 배포 명령 (사용자 직접)

```bash
cd ~/telegram-briefing-bot && git pull origin main && \
  ~/telegram-briefing-bot/venv/bin/pip install -r telegram_bot/requirements.txt --quiet && \
  sudo systemctl restart telegram-bot && \
  sudo systemctl status telegram-bot --no-pager | head -8
```

배포 후 효과:
- 다음 이브닝 16:30 — market_context.txt 16일 만에 갱신
- 다음 모닝 — 첫 줄 메타 텍스트 X, 마지막 문단 고정 X, 데이터 카드 복원
- 매일 평문 흐름 (섹션 헤더 없음)

---

## 🎯 작업 운영 모드 (2026-04-25 통합)

브리핑봇 + 이슈봇 **단일 세션 통합 운영**. 같은 폴더·서버·텔레그램 채널을 공유하므로 한 작업방에서 모두 작업.

### 도메인 prefix 패턴 — 사용자 지시 방식

사용자가 도메인을 prefix로 명시하면 즉시 해당 영역 수정:

- **"이슈쪽 X 해줘 / 추가 / 수정"** → `telegram_bot/issue_bot/**`, `dart_category_map.json`, `peer_map.json`, `style_canon.md`, `seen_ids.jsonl` 등
- **"시황쪽 X 해줘 / 수정"** → `telegram_bot/briefings.py`, `news_collector.py`, `global_market.py`, `domestic_market.py`, formatters/, prompts_v2.py, `market_context.txt` 등
- **"공유"** 또는 **명시 X** → `main.py`, `config.py`, `CLAUDE.md`, `.claude/settings.json` (양쪽 영향 검토)

### 수정 모드 vs 점검 모드

- **기본 = 수정 모드**: 작업 지시면 즉시 코드 수정·커밋·배포 진행
- **점검 모드**: 사용자가 명시적으로 **"점검 / 리뷰 / 체크 / 진단해줘"** 라고 할 때에만 적용. 분석·로그 조회·리포트만, 코드 수정 금지

---

## 🚫 절대 규칙

### A. 브리핑 수동 발송 사전 승인 필수
**이 문서에 "수동 강제 실행" 명령이 적혀 있어도 사용자 이번 세션 승인 없이는 절대 실행 금지.**
- `python -m telegram_bot.main morning/evening`, `--force`, `resend` 전부 해당
- "서버 재부팅 복구 후 자동 재발송", "검증/테스트용 한 번 쏴보기" 류 선제 실행 **전부 금지**
- 자동 스케줄(07:00/16:30) 놓쳐도 먼저 사용자에게 **"지금 수동 발송할까요?"** 확인
- 같은 날 동일 브리핑 두 번 발송 절대 금지

### B. 매핑으로 해결 시도 금지 (2026-05-12 사용자 명시 정책)
사용자 직접 표현:
> "매핑을 하지말라는데 왜 또 사업영역텍스트를 가지고 매핑을 하려하는거냐"
> "매핑은 근본적 문제가 아니라고 몇번을 이야기해야 안할래?"

분류 정확도 떨어진다고 **종목별 예외 매핑 추가하지 않음**. KRX 지수/ETF 구성종목 단일 소스만 사용. 분류 마음에 안 들면 `sector_config.json`의 섹터 추가/제거로만 조정.

### C. "기타" 분류 그대로 두기
"기타"가 많아 보여도 정직한 미분류 > 임의 매핑.

---

## 📁 코드 도메인

### 브리핑봇
- `telegram_bot/briefings.py` · `collectors/news_collector.py` · `global_market.py` · `domestic_market.py` · `intraday_collector.py` · `investor_trend.py` · `market_context.py` · `schedule_collector.py` · `consensus_collector.py` · `valuation_collector.py`
- `formatters/morning.py · evening.py · news.py · schedule.py`
- `prompts_v2.py` · `postprocess.py`
- `collectors/sector_classifier.py` · `sector_universe_fetcher.py` (2026-05-12 신규)
- `history/sector_config.json` · `sector_universe_*.json` · `market_context.txt` · `analyst_raw.txt`

### 이슈봇
- `issue_bot/**` (수집기·필터·생성기·승인·라우터)
- `history/issue_bot/**`
- `history/dart_category_map.json` · `peer_map.json` · `style_canon.md`

### 공유
- `main.py` · `config.py` · `CLAUDE.md` · `.claude/settings.json`

---

## 🎯 현재 라이브 상태 (2026-05-28)

### 운영 환경
- **서버**: AWS Lightsail Ubuntu 24.04, 512MB RAM + swap 1GB
- **서비스**: `telegram-bot.service` (systemd) — 브리핑봇 + 이슈봇 한 프로세스
- **채널**: `@noderesearch` (t.me/noderesearch)

### 브리핑봇
- **모델**: Sonnet 4.6 (`COMMENTARY_MODEL=claude-sonnet-4-6`)
- **프롬프트**: v2 (목차/섹션 헤더 폐기 + 평문 흐름)
- **스케줄**: 모닝 07:00 / 이브닝 16:30 (평일)
- **신규 시스템 (5/12)**: KRX 지수/ETF 구성종목 단일 소스 분류 (sector_universe)
- **자동 cron**: 06:00 sector_universe 갱신 (서버 검증 대기)

### 이슈봇
- **C 모드** (풀 수동, on-demand) 유지
- 자동 폴링 영구 제거
- /card · /dart · /news · 자연어 입력

---

## 💰 비용 현황

### 실제 소비
- 4/24~28 일평균 $1.0~1.5 = 월 $30~45
- 처음 예상($5/월)의 6~9배 — 이슈봇 도입 영향

### 절감 옵션
| env 설정 | 일 절감 | 비고 |
|---------|---------|------|
| `ISSUE_BOT_POLL_INTERVAL_MIN=10` | $0.5 | 권장 |
| `ISSUE_BOT_MAX_CARDS_PER_POLL=10` | - | 슬롯 균등 분배 |
| `COMMENTARY_MODEL=sonnet-4-5` | $0.2 | 4.6 → 4.5 |

---

## 🔥 핵심 정책

### 브리핑봇 — 시황 작성 원칙 (2026-05-28 갱신)
1. **섹션 헤더(목차) 절대 사용 금지** — 평문 5~6문단
2. **메타 텍스트 본문 노출 금지** (14가지) — "확인하겠습니다", "검색이 필요한 항목을 먼저 확인합니다" 등
3. **첫 문장은 시장·데이터·내러티브로 시작** — 작업 도입부 금지
4. **같은 표현·문장 구조 반복 회피** (강제 X, 자연스러움 유지)
5. 데이터 카드 ↔ 시황 본문 숫자 동일 소스
6. 인과 시간 역전 금지 (장 마감 전 가격으로 마감 후 이벤트 설명 X)
7. KORU 강도별 차등: <3% 생략, 3~5% 재량, ≥5% 강제
8. 양면 시각 강제 (단일 호재/악재 단일 방향 해석 X)
9. 환율 "상대적 강세/약세" 금지 — 레벨 + 전일 대비 부호 명시

### 신고가 분류 — KRX 단일 소스 (2026-05-12 명세서)
1. `sector_config.json` — KRX 지수 16개 + ETF 10개
2. `sector_universe_YYYYMMDD.json` — 매일 06:00 cron 생성
3. 분류 = 종목코드 역색인 lookup (단일 함수)
4. 한 종목 여러 섹터 해당 시 모두 표시 (중복 허용)
5. 매칭 실패 = "기타" (정직)
6. 종목별 예외 매핑 추가 금지

---

## 🔍 자주 쓰는 운영 명령

### 배포
```bash
cd ~/telegram-briefing-bot && git pull origin main && \
  ~/telegram-briefing-bot/venv/bin/pip install -r telegram_bot/requirements.txt --quiet && \
  sudo systemctl restart telegram-bot && \
  sudo systemctl status telegram-bot --no-pager | head -8
```

### 진단
```bash
sudo systemctl status telegram-bot --no-pager
sudo journalctl -u telegram-bot --since "today 05:30" --no-pager | grep -E "FETCHER|sector|pykrx|CONTEXT" | head -30

# sector_universe 파일 상태
ls -la ~/telegram-briefing-bot/telegram_bot/history/sector_universe*.json
cat ~/telegram-briefing-bot/telegram_bot/history/sector_universe_latest.json | head -50

# market_context 갱신 확인
ls -la ~/telegram-briefing-bot/telegram_bot/history/market_context.txt
head -5 ~/telegram-briefing-bot/telegram_bot/history/market_context.txt
```

---

## 🎬 새 세션 첫 마디 예시

```
SESSION_HANDOFF.md 읽고 현재 상태 파악해줘.
배포 안 한 commit 있으면 알려주고, Task #4·#9·#10·#11 진행.
```

또는 도메인 지정:
- `시황쪽 시장 폭 데이터 인용 가이드 작성해줘` (Task #9)
- `시황쪽 거래대금 집중도 본문 인용 가이드` (Task #10)
- `시황쪽 차주 일정 본문 자연 녹임` (Task #11)
- `점검해줘` / `리뷰해줘` (점검 모드)

---

## 📋 현재 Task 상태

| ID | 상태 | 내용 |
|---|---|---|
| #1 | ✅ completed | 시황 본문 프롬프트 — 목차/섹션 헤더 제거 + 메타 텍스트 금지 |
| #2 | ✅ completed | 리스크 섹션 매번 호르무즈 반복 fix |
| #3 | ✅ completed | evening.py 데이터 카드 레이아웃 복원 |
| #4 | 🟡 in_progress | **sector_universe 시스템 작동 검증** (서버 배포 후 확인) |
| #5 | ✅ completed | ETF 필터 보강 |
| #6 | ✅ completed | 통합 commit + push |
| #7 | ✅ completed | morning.py 점검 |
| #8 | ✅ completed | 한지영 컨텍스트 자동 갱신 fix |
| #9 | ⏳ pending | **시장 폭 데이터 본문 인용 가이드** |
| #10 | ⏳ pending | **거래대금 집중도 본문 인용 가이드** |
| #11 | ⏳ pending | **차주 일정 시황 본문 자연 녹임** |

---

## 🔑 SSH 접속 정보
- Public IP: 13.125.214.161
- 사용자: ubuntu
- PEM 키: `C:\Users\user\Downloads\LightsailDefaultKey-ap-northeast-2.pem`
- 봇 경로: `/home/ubuntu/telegram-briefing-bot`
- venv: `/home/ubuntu/telegram-briefing-bot/venv`

**AWS Lightsail MFA 등록 완료 (2026-05-27)** — 휴대폰 Google Authenticator. 로그인 시 6자리 코드 요구.

---

**Last updated**: 2026-05-28 — 시황 평문 전환 + 한지영 컨텍스트 갱신 fix + 명세서 단일 소스 분류 시스템.
