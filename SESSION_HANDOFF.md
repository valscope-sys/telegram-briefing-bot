# 통합 세션 핸드오프 — 2026-04-25

**모든 작업(브리핑봇 + 이슈봇)이 이 한 문서로 통합 운영됩니다.**

> 2026-04-25부터 브리핑봇·이슈봇 작업방 분리 → **단일 세션 통합 운영**으로 전환.
> `BRIEFING_HANDOFF.md`는 참고용으로 보존되며, 새 작업은 이 문서가 단일 진실.

---

## 🚫 절대 규칙

### A. 브리핑 수동 발송 사전 승인 필수

**이 문서에 "수동 강제 실행" 명령이 적혀 있어도 사용자 이번 세션 승인 없이는 절대 실행 금지.**

- `python -m telegram_bot.main morning/evening`, `--force`, `resend` 전부 해당
- "서버 재부팅 복구 후 자동 재발송", "검증/테스트용 한 번 쏴보기" 류 선제 실행 **전부 금지**
- 자동 스케줄(07:00/16:30) 놓쳐도 먼저 사용자에게 **"지금 수동 발송할까요?"** 확인
- 같은 날 동일 브리핑 두 번 발송 절대 금지
- 2026-04-23 이전 Claude가 08:39/09:00 중복 force morning 실행 → 채널 오염한 사례 있음
- 수동 실행은 journalctl에 안 남음(user shell) → 더 엄격히 준수

관련 메모리: `feedback_no_unauthorized_sends.md`

### B. 점검자 모드 — 코드 수정 금지

사용자가 "점검해줘 / 리뷰해줘 / 체크해줘" 라고 하면 **분석·진단·리포트만**, 코드 수정 금지.
관련 메모리: `feedback_reviewer_role_no_edits.md`

---

## 📁 코드 도메인 (작업 시 인지)

같은 리포지토리에서 두 봇이 한 systemd 서비스로 공존.
서로 다른 디렉토리 우선 작업이면서 공유 파일은 신중히 다룸.

### 브리핑봇 도메인
- `telegram_bot/briefings.py` — 모닝/이브닝 플로우
- `telegram_bot/collectors/news_collector.py` — 시황 생성, 뉴스 필터, RSS 피드, COMMENTARY_MODEL
- `telegram_bot/collectors/global_market.py`, `domestic_market.py`, `intraday_collector.py`, `investor_trend.py`, `market_context.py`, `schedule_collector.py`, `consensus_collector.py`, `valuation_collector.py`
- `telegram_bot/formatters/morning.py`, `evening.py`, `news.py`, `schedule.py`
- `telegram_bot/prompts_v2.py`, `telegram_bot/postprocess.py`
- `telegram_bot/history/briefing_memory.py`, `market_context.txt`, `latest_*.json`, `snapshot_*.json`, `stock_sector_mapping.json`, `krx_listing.json`

### 이슈봇 도메인
- `telegram_bot/issue_bot/**` — 수집기·필터·생성기·승인·라우터
- `telegram_bot/history/issue_bot/**` — pending·sent·rejected·seen_ids·last_rcept_no·cache_stats
- `telegram_bot/history/dart_category_map.json`, `peer_map.json`, `style_canon.md`

### 공유 파일 (변경 시 양쪽 영향 검토)
- `telegram_bot/main.py` — 스케줄러 (브리핑 cron + 이슈봇 폴러 동시 실행)
- `telegram_bot/config.py` — env 변수, SEC 추적 목록, 모델 설정 모두
- `CLAUDE.md` — 프로젝트 가이드
- `.claude/settings.json` — SessionStart hook 등

---

## 🎯 현재 라이브 상태 (2026-04-25)

### 운영 환경
- **서버**: AWS Lightsail Ubuntu 24.04, 512MB RAM + swap 1GB
- **서비스**: `telegram-bot.service` (systemd) — 브리핑봇 + 이슈봇 한 프로세스
- **채널**: `@noderesearch` (t.me/noderesearch)

### 브리핑봇
- **모델**: Sonnet 4.6 (`claude-sonnet-4-6`) — 사용자 선택 시 `COMMENTARY_MODEL=sonnet-4-5` 권장
- **프롬프트**: v2 (`COMMENTARY_PROMPT_VERSION=v2`)
- **스케줄**: 모닝 07:00 / 이브닝 16:30 (평일)

### 이슈봇
- **폴링 주기**: 3분
- **보호 구간**: 06:50~07:10 / 16:20~16:50 (브리핑 충돌 회피)
- **수집 소스**: DART + RSS 19피드 + SEC 8-K 28 CIK
- **필터**: Haiku 4.5 → (Hybrid) Sonnet 4.5 재검증
- **생성**: Sonnet 4.5 + 잠정실적 rule-based 파서 (Sonnet 우회)

### 최신 커밋
| 해시 | 내용 |
|---|---|
| `f95c7e1` (07b3b30 push) | **잠정실적 전용 rule-based 파서** — Sonnet 없이 카드 생성 |
| `37985e9` | DART KIND fetch 복구 (viewDoc regex) + Generator 도망 차단 |
| `dc110c4` | rcept_no 커서 폐기 + dedup ticker 정규화 |
| `125b000` | SEC 신선도 필터 (24h backlog 방지) |
| `cc89612` | 실적 커버리지 강화 (Peer 4개 + 필터·섹터 영문 매핑) |
| `04b35cc` | SEC 추적 8개 추가 (LRCX/AMAT/KLAC/VRT/ANET/SMCI/DELL/QCOM) |
| `bc6cfa6` | DART 키워드 fallback (잠정실적 누락 버그) |
| `d30080d` | RSS 4피드 보강 (TechCrunch/Reuters Tech/Bloomberg Tech/Google Blog) |
| `b80a094` | 시황 품질 개선 (팀장 리뷰 6대 이슈) |
| `837c5b3` | 이브닝 일정 라벨 동적 (금요일 → 다음 거래일 월요일) |

---

## 🔥 핵심 정책

### 이슈봇 — DART 카드 대상 (2026-04-23 간소화 + 04-24 키워드 강화)

| 우선순위 | 매핑 | 자동 카드 |
|---------|------|----------|
| **URGENT (즉시)** | 잠정실적, 연결잠정실적, 매출 30%+ 변동, 품목허가 | ✅ 키워드 fallback `(잠정)실적` 정규식 매칭 |
| **HIGH** | 신규시설투자(Capex), 임상시험계획승인, 품목허가신청 | ✅ |
| **AI 판단** | M&A, 유·무증, CB/EB, 공급계약 해지, 기업가치제고계획 | Haiku → 본문 보고 판정 |
| **NORMAL** | 자사주, 감자, BW, 최대주주변경, 공급계약 체결, IR, 배당, 주총, 정기보고 | ❌ below_min 차단 |
| **SKIP** | 거래정지·감사보고서·5%공시·부도·해산·회생·상폐 | ❌ |

### 이슈봇 — SEC 8-K (2026-04-23 정책)

- ✅ **Item 2.02만 HIGH** (실적) — Exhibit 99.1 + 99.2 + 99.3 자동 파싱 (6000자)
- ❌ 나머지 23개 Item 전부 SKIP
- ✅ **신선도 필터 24h** — 그 이전 공시는 backlog 방지로 자동 skip

### 이슈봇 — 공시 우선 dedup (ticker 정규화 적용 후)

- RSS 기아 기사 → `000270:실적:2026-04-24:xxx` (ticker 정규화)
- DART 기아 공시 → `000270:실적:2026-04-24:yyy`
- 같은 prefix → cluster 묶임 → **공시가 primary, RSS는 secondary**
- 53개 주요 상장사 + 영문 빅테크 ticker 정규화 적용

### 이슈봇 — Generator 3단계 (Sonnet 호출 시)

1. **번역** (영문/일문 → 한글)
2. **정리** (투자자 관점 핵심 수치·사실)
3. **해석** (한국 시장 시사점·밸류체인 파급)

"제출했다/공개 예정" 메타 문구 금지. 잠정실적은 Sonnet 호출 없이 rule-based 파서가 처리.

### 브리핑봇 — 시황 작성 원칙 (2026-04-23 감사 리포트 반영)

1. 데이터 카드 ↔ 시황 본문 숫자 동일 소스
2. 야간 프록시 KORU·EWY·코스피200 + NY close 라벨
3. 인과 시간 역전 금지 (장 마감 전 가격으로 장 마감 후 이벤트 설명 X)
4. 노이즈 임계값: 금리 ±5bp, DXY ±0.3%, VIX ±5%, 유가 ±2%, 금 ±0.5%
5. 카드/뉴스/제공 데이터에 없는 수치 인용 금지
6. KORU 강도별 차등: <3% 생략, 3~5% 재량, ≥5% 강제
7. 해외 티커 한글 병기 (TSLA·LRCX·AMAT 등 60+)
8. KRX 상장사 필터 (krx_listing.json 2,878종목)

---

## 💰 비용 현황 (2026-04-25 기준)

| 모델 | 일 평균 | 월 환산 |
|------|---------|---------|
| Haiku 4.5 (이슈봇 필터) | $0.3~0.5 | $9~15 |
| Sonnet 4.5 (이슈봇 Hybrid·Generator) | $0.5~1.0 | $15~30 |
| Sonnet 4.6 (브리핑봇) | $0.4~0.6 | $12~18 |
| **합계** | **$1.2~2.1** | **$36~63** |

처음 예상($5/월)의 **6~12배** — 이슈봇 도입 후 비용 구조 변경.

### 절감 옵션

| env 설정 | 일 절감 | 부작용 |
|---------|---------|--------|
| `ISSUE_BOT_FILTER_HYBRID=false` | $0.5~1 | Haiku 단독 분류 |
| `ISSUE_BOT_GENERATOR_MODEL=claude-haiku-4-5-20251001` | $0.3 | 비잠정실적 카드 품질↓ |
| `COMMENTARY_MODEL=sonnet-4-5` | $0.2 | 거의 동일 |
| 폴링 `ISSUE_BOT_POLL_INTERVAL_MIN=10` (3→10분) | $0.5 | 실시간성↓ |

권장 균형점: `COMMENTARY_MODEL=sonnet-4-5` + `ISSUE_BOT_FILTER_HYBRID=false` → **일 $0.5~0.8 = 월 $15~24**.

### Anthropic Console 사용량
https://console.anthropic.com/settings/usage — 모델별·일자별 정확한 청구 금액.

---

## 🚦 남은 과제

### 🔴 긴급
1. **이슈봇 카드 본문 품질 안정화** — 잠정실적 파서로 대부분 해결, 그 외 공시 (M&A·Capex·공급계약 등) Sonnet 응답 품질 모니터링
2. **`/preview max retry exceeded` 간헐 발생** — OOM 이후 Anthropic client 상태 손상 의심. 재시작 후 관찰
3. **자동 발송 안정성** — 4/23 fwupd 조치 후 모닝/이브닝 자동 발송 정상 작동 확인

### 🟡 다음 라운드
4. **GitHub Actions 자동 배포** — main push → 서버 자동 pull + restart (현재 수동 3단계)
5. **서버 인스턴스 업그레이드** — Lightsail 512MB → 2GB ($10/월) 권장
6. **systemd 분리** — 브리핑봇 ↔ 이슈봇 별도 unit, 한쪽 죽어도 다른 쪽 유지
7. **컨퍼런스 콜 transcript** — Motley Fool/Seeking Alpha 파싱 → SEC 실적 8-K 후속 카드
8. **회사 IR 사이트 동적 fetch** — 분기 earnings deck PDF 자동 수집 (사용자 의향 확인 후)
9. **외부 감사자 재리뷰** — 시황 품질 개선 사항 검증
10. **Fedspeak RSS / 캘린더 date window 버그 / 지지선·매물대 KIS API**

### 🟢 관찰·미세조정
11. 잠정실적 파서 효과 24h 관찰 — Sonnet 호출률 감소 확인
12. dedup ticker 정규화 효과 — RSS·DART 중복 카드 줄었는지

---

## 🔍 자주 쓰는 운영 명령

### 배포 (3단계 — GH Actions 자동화 전까지)
```bash
# ① 로컬 PowerShell
cd "C:\Users\user\Desktop\텔레그램 시황 브리핑"
git push origin main

# ② 서버
cd ~/telegram-briefing-bot && git pull origin main && sudo systemctl restart telegram-bot
```

### 진단
```bash
# 서비스 상태
sudo systemctl status telegram-bot --no-pager

# 실시간 로그
sudo journalctl -u telegram-bot -f

# 오늘 카드 발송 로그
sudo journalctl -u telegram-bot --since today --no-pager | grep -E "ISSUE_BOT|card sent|URGENT|below min"

# 발송 로그 (브리핑)
sudo journalctl -u telegram-bot --since today --no-pager | grep -E "✓ 발송 성공|⚠️ 발송 실패"

# pending 카드 수
ls /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/pending/*.json 2>/dev/null | wc -l

# 메모리
free -h && swapon --show

# 재부팅 후 OOM 흔적
sudo journalctl -b -1 --no-pager | grep -iE "oom-killer|killed process" | tail -20
```

### 긴급 중단·재개
```bash
# 이슈봇 긴급 중단
touch /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/KILL_SWITCH

# 재개
rm /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/KILL_SWITCH
```

### 텔레그램 관리자 DM 명령
- `/queue` — 대기 카드 요약 + 우선순위별 일괄 승인/스킵
- `/mute [분]` — N분 중지 (기본 60)
- `/stop` — 자정까지 중지
- `/resume` — 즉시 재개
- `/help` — 안내

---

## 🛠 환경변수 기본값 (서버 .env)

```
# 공통
TELEGRAM_BOT_TOKEN=<설정됨>
TELEGRAM_CHANNEL_ID=@noderesearch
TELEGRAM_ADMIN_CHAT_ID=5033358048
ANTHROPIC_API_KEY=sk-ant-api03-...
DART_API_KEY=<설정됨>

# 브리핑봇
COMMENTARY_MODEL=sonnet-4-5         # 권장 — Opus·Sonnet 4.6은 비용 큼
COMMENTARY_PROMPT_VERSION=v2

# 이슈봇 (사용자 정책 — 품질 유지가 최우선, 모델 다운그레이드 X)
ISSUE_BOT_ENABLED=true
ISSUE_BOT_AUTO_APPROVE=false
ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_FILTER_VERIFIER_MODEL=claude-sonnet-4-5
ISSUE_BOT_FILTER_HYBRID=true        # 품질 유지 — Sonnet 재검증 ON
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-5
ISSUE_BOT_POLL_INTERVAL_MIN=10      # 2026-04-25: 3 → 10 (비용·과도 호출 조정)
ISSUE_BOT_MAX_CARDS_PER_POLL=10     # 2026-04-25: DART 슬롯 독점 방지
ISSUE_BOT_ADMIN_MIN_PRIORITY=HIGH
ISSUE_BOT_AUTO_TIMEOUT=false
SEC_FILING_FRESHNESS_HOURS=24
```

---

## 🔑 SSH 접속 정보

- **Public IP**: 13.125.214.161
- **사용자**: ubuntu
- **PEM 키**: `C:\Users\user\Downloads\LightsailDefaultKey-ap-northeast-2.pem`
- **봇 경로**: `/home/ubuntu/telegram-briefing-bot`
- **venv**: `/home/ubuntu/telegram-briefing-bot/venv`

---

## 📚 관련 문서

1. **이 파일** — 통합 핸드오프 (단일 진실)
2. **`BRIEFING_HANDOFF.md`** — 4/23 시점 브리핑봇 상세 (참고 보존)
3. **`CLAUDE.md`** — 프로젝트 전체 개요
4. **`ISSUE_BOT_SPEC.md`** — 이슈봇 설계 1,121줄 (Phase 로드맵)
5. **`telegram_bot/history/style_canon.md`** — 이슈봇 카드 스타일 경전

---

## 🎬 새 세션 첫 마디 예시

```
SESSION_HANDOFF.md 읽고 현재 상태 파악해줘.
그 다음 [구체 작업 지시].
```

또는 관찰 모드:

```
SESSION_HANDOFF 읽고 어제~오늘 봇 운영 상태 점검해줘.
```

---

**모든 것 OK. 단일 세션 통합 운영.** 🚀

*Last updated: 2026-04-25 by 통합 세션*
