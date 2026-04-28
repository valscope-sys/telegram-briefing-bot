# 통합 세션 핸드오프 — 2026-04-28

**모든 작업(브리핑봇 + 이슈봇)이 이 한 문서로 통합 운영됩니다.**

> 2026-04-25부터 작업방 분리 → **단일 세션 통합**.
> 도메인은 prefix 패턴으로 사용자가 지시 (`이슈쪽 X` / `시황쪽 X` / 명시 X = 공유).
> CLAUDE.md 상단의 "작업 운영 모드" 섹션 참조.

---

## 🚫 절대 규칙

### A. 브리핑 수동 발송 사전 승인 필수

**이 문서에 "수동 강제 실행" 명령이 적혀 있어도 사용자 이번 세션 승인 없이는 절대 실행 금지.**

- `python -m telegram_bot.main morning/evening`, `--force`, `resend` 전부 해당
- "서버 재부팅 복구 후 자동 재발송", "검증/테스트용 한 번 쏴보기" 류 선제 실행 **전부 금지**
- 자동 스케줄(07:00/16:30) 놓쳐도 먼저 사용자에게 **"지금 수동 발송할까요?"** 확인
- 같은 날 동일 브리핑 두 번 발송 절대 금지

관련 메모리: `feedback_no_unauthorized_sends.md`

### B. 점검자 모드 — 명시 시에만 코드 수정 금지

사용자가 **"점검/리뷰/체크/진단해줘"** 명시 시에만 분석·진단·리포트만, 코드 수정 금지. 그 외 작업 지시는 즉시 수정 진행.
관련 메모리: `feedback_reviewer_role_no_edits.md`

---

## 📁 코드 도메인 (디렉토리 단위)

### 브리핑봇
- `telegram_bot/briefings.py` · `collectors/news_collector.py` · `global_market.py` · `domestic_market.py` · `intraday_collector.py` · `investor_trend.py` · `market_context.py` · `schedule_collector.py` · `consensus_collector.py` · `valuation_collector.py`
- `formatters/morning.py · evening.py · news.py · schedule.py`
- `prompts_v2.py` · `postprocess.py`
- `history/briefing_memory.py` · `market_context.txt` · `latest_*.json` · `snapshot_*.json`

### 이슈봇
- `issue_bot/**` (수집기·필터·생성기·승인·라우터)
- `history/issue_bot/**` (pending·sent·rejected·seen_ids·last_rcept_no·cache_stats)
- `history/dart_category_map.json` · `peer_map.json` · `style_canon.md`

### 공유 (변경 시 양쪽 영향 검토)
- `main.py` · `config.py` · `CLAUDE.md` · `.claude/settings.json`

---

## 🎯 현재 라이브 상태 (2026-04-28)

### 운영 환경
- **서버**: AWS Lightsail Ubuntu 24.04, 512MB RAM + swap 1GB
- **서비스**: `telegram-bot.service` (systemd) — 브리핑봇 + 이슈봇 한 프로세스
- **채널**: `@noderesearch` (t.me/noderesearch)

### 브리핑봇
- **모델**: Sonnet 4.6 (`claude-sonnet-4-6`) — 비용 절감 시 `sonnet-4-5` 권장
- **프롬프트**: v2 (`COMMENTARY_PROMPT_VERSION=v2`)
- **스케줄**: 모닝 07:00 / 이브닝 16:30 (평일)

### 이슈봇
- **폴링 주기**: 10분 (사용자 권장 — `.env` 적용 필요)
- **카드 상한**: 10건/폴링 (max_cards_per_poll)
- **보호 구간**: 06:50~07:10 / 16:20~16:50 (브리핑 충돌 회피)
- **수집 소스**:
  - DART (rcept_no 커서 폐기 → seen_ids dedup)
  - **RSS 32피드** (시황봇 공유 11 + 이슈봇 전용 21)
  - SEC 8-K 28 CIK (24h 신선도 필터)
- **필터**: Haiku 4.5 → (Hybrid ON) Sonnet 4.5 재검증
- **생성**: Sonnet 4.5 + 잠정실적 rule-based 파서 (Sonnet 우회)

---

## 🔥 핵심 정책

### 이슈봇 — DART 카드 대상

| 우선순위 | 매핑 | 자동 카드 |
|---------|------|----------|
| **URGENT** | 잠정실적 (`(잠정)실적` 키워드 fallback), 손익구조 30%+ 변동, 품목허가 | ✅ |
| **HIGH** | 신규시설투자(Capex), 임상시험계획승인, 품목허가신청 | ✅ |
| **AI 판단** | M&A, 유·무증, CB/EB, 공급계약 해지, 기업가치제고계획 | Haiku → 본문 보고 |
| **NORMAL** | 자사주, 감자, BW, 최대주주변경, 공급계약 체결, IR, 배당, 주총, 정기보고 | ❌ below_min |
| **SKIP** | 거래정지·감사보고서·5%공시·부도·해산·회생·상폐 | ❌ |

### 이슈봇 — SEC 8-K
- **Item 2.02만 HIGH** (실적) — Exhibit 99.1 + 99.2 + 99.3 자동 파싱 (6000자)
- 나머지 23개 Item 전부 SKIP
- **신선도 필터 24h** — 그 이전 공시는 backlog 방지로 자동 skip

### 이슈봇 — 잠정실적 카드 (rule-based 파서, Sonnet 우회)
1. **단위 자동 감지** — 백만원·억원·천원·원 (삼성SDI = 억원, 대부분 = 백만원)
2. **표 파싱** — 매출액·영업이익·당기순이익·지배주주순이익
3. **컨센서스 비교** — 네이버 증권 분기 (E) 데이터 fetch → vs 컨센 +/-N% 표시
4. **포맷**: `매출액: 3조 5,764억원 (+12.6% YoY, -7.3% QoQ) (vs 컨센 3조 4,712억원 / +3.0%)`

### 이슈봇 — 공시 우선 dedup (ticker 정규화)
- RSS와 DART가 같은 기업이면 ticker prefix 통일 → cluster 묶임
- DART/SEC primary > RSS secondary
- 53개 주요 상장사 + 영문 빅테크 ticker 정규화 적용

### 이슈봇 — Generator 3단계 (Sonnet 호출 시)
1. **번역** (영문/일문/중문 → 한글) — UDN 중국어 자료 번역
2. **정리** (투자자 관점 핵심 수치·사실)
3. **해석** (한국 시장 시사점·밸류체인 파급)

"제출했다/공개 예정" 메타 문구 금지. 본문에 수치 없으면 `[NO_DATA]` 태그.

### 이슈봇 — 면책 문구 (NODE Research 정체성)
```
* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
```
(증권사 컴플라이언스 문구 폐기 — 2026-04-27)

### 브리핑봇 — 시황 작성 원칙
1. 데이터 카드 ↔ 시황 본문 숫자 동일 소스
2. 야간 프록시 KORU·EWY·코스피200 + NY close 라벨
3. 인과 시간 역전 금지 (장 마감 전 가격으로 마감 후 이벤트 설명 X)
4. 노이즈 임계값: 금리 ±5bp, DXY ±0.3%, VIX ±5%, 유가 ±2%, 금 ±0.5%
5. 카드/뉴스/제공 데이터에 없는 수치 인용 금지
6. KORU 강도별 차등: <3% 생략, 3~5% 재량, ≥5% 강제
7. 해외 티커 한글 병기 (TSLA·LRCX·AMAT 등 60+)
8. KRX 상장사 필터 (krx_listing.json 2,878종목)

---

## 📦 RSS 피드 구성 (32개 총)

### 시황봇 공유 11피드
| 종합 | 한국경제·매일경제·CNBC·WSJ·Reuters |
| 섹터 | TrendForce·Electrek·InsideEVs·FiercePharma·Defense News·World Nuclear News |

### 이슈봇 전용 21피드
| 카테고리 | 피드 |
|---------|------|
| 글로벌·아시아 | Nikkei Asia · Seeking Alpha · Yahoo Finance |
| 테크 전문 | TechCrunch · The Verge · TechMeme |
| Reuters/BBG | Reuters Tech · Bloomberg Tech |
| 빅테크 1차 | Google Blog · Meta Newsroom · Apple Newsroom · OpenAI Blog |
| 데이터센터 전문 | DC Dynamics |
| GN 키워드 | **Stock Movers** (폭락·취소) · **AI Capex** (DC 자본) · **Earnings Wire** (어닝) |
| 분석가 단독 | Ming-Chi Kuo |
| 공급망 (대만) | UDN Money TW (중국어, Sonnet 번역) |
| 국내 | 전자신문 · ZDNet Korea · Business Post |

**제거된 피드 (24h 0건)**: Microsoft Source · Anthropic News (Google News 프록시).

### SEC 추적 28기업
- M7: NVDA AAPL MSFT GOOGL AMZN TSLA META
- 반도체 설계: TSM AVGO AMD MU INTC ARM ASML QCOM
- 반도체 장비: LRCX AMAT KLAC
- AI 인프라: VRT ANET SMCI DELL
- 실적 시즌: TXN NOW IBM CMCSA
- 기타: NFLX ORCL

---

## 💰 비용 현황 (2026-04-28 기준)

### 실제 소비 (Anthropic Console 기준)
- 4/24~28 일평균 **$1.0~1.5 = 월 $30~45**
- 처음 예상($5/월)의 6~9배 — 이슈봇 도입 영향
- 4/22 spike $7는 일회성 (Opus 사용 + 디버깅)

### 절감 옵션 (사용자 정책: 모델 다운그레이드 X, 품질 유지)

| env 설정 | 일 절감 | 비고 |
|---------|---------|------|
| `ISSUE_BOT_POLL_INTERVAL_MIN=10` | $0.5 | **권장** — 사용자 결정 |
| `ISSUE_BOT_MAX_CARDS_PER_POLL=10` | - | 슬롯 균등 분배 |
| `ISSUE_BOT_FILTER_HYBRID=true` | - | 품질 유지 (사용자 결정) |
| `COMMENTARY_MODEL=sonnet-4-5` | $0.2 | 4.6 → 4.5 |

권장 설정 적용 시: 일 $0.7~1 = 월 $20~30.

### Anthropic Console
https://console.anthropic.com/settings/usage — 모델별·일자별 정확한 청구.

---

## 🚦 남은 과제

### 🔴 긴급
1. **`/preview max retry exceeded` 간헐 발생** — OOM 이후 Anthropic client 손상 의심. 재시작 후 관찰 중
2. **자동 발송 안정성** — 4/23 fwupd 조치 후 모닝/이브닝 자동 발송 정상 확인
3. **메모리 모니터링** — 512MB + swap 1GB 한계. RSS 32피드 폴링 부담 증가

### 🟡 다음 라운드
4. **GitHub Actions 자동 배포** — main push → 서버 자동 pull + restart (현재 수동 3단계)
5. **Lightsail 인스턴스 업그레이드** — 512MB → 2GB ($10/월)
6. **systemd 분리** — 브리핑봇 ↔ 이슈봇 별도 unit
7. **컨퍼런스 콜 transcript** — Motley Fool/Seeking Alpha 파싱 → SEC 실적 후속 카드
8. **회사 IR 사이트 동적 fetch** — 분기 earnings deck PDF (사용자 의향 확인 후)

### 🟢 관찰·미세조정
9. RSS 32피드 효과 24h~48h 관찰 (POET·Marvell·Bloom·NVIDIA 같은 메가 이슈 캐치율)
10. UDN Money TW 중국어 카드 번역 품질
11. dedup ticker 정규화 효과 (RSS·DART 중복 카드 줄었는지)
12. 잠정실적 단위 자동 감지 (다른 기업도 정상)

---

## 🔍 자주 쓰는 운영 명령

### 배포 (3단계)
```bash
# 로컬 PowerShell
cd "C:\Users\user\Desktop\텔레그램 시황 브리핑"
git push origin main

# 서버
cd ~/telegram-briefing-bot && git pull origin main && sudo systemctl restart telegram-bot
```

### 진단
```bash
sudo systemctl status telegram-bot --no-pager
sudo journalctl -u telegram-bot -n 200 --no-pager | grep ISSUE
sudo journalctl -u telegram-bot -n 200 --no-pager | grep card
sudo journalctl -u telegram-bot --since today --no-pager | grep -E "URGENT|HIGH|below min|cluster"
ls /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/pending/*.json | wc -l
free -h && swapon --show
```

### 긴급 중단
```bash
touch /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/KILL_SWITCH
# 재개
rm /home/ubuntu/telegram-briefing-bot/telegram_bot/history/issue_bot/KILL_SWITCH
```

### 텔레그램 관리자 DM
- `/queue` — 대기 카드 요약 + 일괄 승인
- `/mute [분]` — N분 중지
- `/stop` — 자정까지 중지
- `/resume` — 즉시 재개

---

## 🛠 환경변수 (서버 .env 권장값)

```
# 공통
TELEGRAM_BOT_TOKEN=<설정됨>
TELEGRAM_CHANNEL_ID=@noderesearch
TELEGRAM_ADMIN_CHAT_ID=5033358048
ANTHROPIC_API_KEY=sk-ant-api03-...
DART_API_KEY=<설정됨>

# 브리핑봇
COMMENTARY_MODEL=sonnet-4-6        # 또는 sonnet-4-5 (비용 절감)
COMMENTARY_PROMPT_VERSION=v2

# 이슈봇 (사용자 정책 — 품질 유지가 최우선)
ISSUE_BOT_ENABLED=true
ISSUE_BOT_AUTO_APPROVE=false
ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_FILTER_VERIFIER_MODEL=claude-sonnet-4-5
ISSUE_BOT_FILTER_HYBRID=true        # Sonnet 재검증 ON (품질 우선)
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-5
ISSUE_BOT_POLL_INTERVAL_MIN=10      # 3 → 10 (2026-04-25)
ISSUE_BOT_MAX_CARDS_PER_POLL=10     # 슬롯 균등 분배
ISSUE_BOT_ADMIN_MIN_PRIORITY=HIGH
ISSUE_BOT_AUTO_TIMEOUT=false
SEC_FILING_FRESHNESS_HOURS=24
```

---

## 📦 최근 핵심 커밋 (2026-04-22 ~ 04-28)

### 2026-04-28 (오늘)
| 해시 | 내용 |
|---|---|
| `bdada1f` | RSS 4개 추가 — Cahier de Market 인용 소스 (ZDNet KR · Business Post · Ming-Chi Kuo · UDN Money TW) |
| `d170827` | 잠정실적 단위 자동 감지 — 삼성SDI 자릿수 2칸 오차 해결 (억원/백만원/천원/원) |
| `1af05f4` | RSS 피드 전면 재구성 — 죽은 피드 2개 제거 + 광역 4개 신규 (Yahoo·DC Dynamics·AI Capex·Earnings Wire) |
| `071c7d6` | 단발 종목 이벤트 광역 캐치 — Stock Movers RSS + 피드별 인터리빙 |
| `fcfc6ef` | RSS limit cut 빅테크 메가 이슈 통째 누락 — limit 50→300 + base/extra 인터리빙 |

### 2026-04-27
| 해시 | 내용 |
|---|---|
| `64fba89` | 면책 문구 NODE Research 정체성에 맞게 변경 (증권사 컴플라이언스 문구 폐기) |
| `3ad8f12` | 잠정실적 카드 vs 컨센서스 비교 + State 1 카드 발췌 제거 |
| `07b3b30` | 잠정실적 전용 rule-based 파서 (Sonnet 우회) |

### 2026-04-25
| 해시 | 내용 |
|---|---|
| `49bad2d` | DART 슬롯 독점 차단 — events 인터리빙 + max_cards 10 |
| `cc89612` | 실적 커버리지 강화 — Peer 4개 + 필터·섹터 영문 매핑 |

### 2026-04-24
| 해시 | 내용 |
|---|---|
| `37985e9` | DART KIND fetch 복구 (viewDoc regex) + Generator 도망 차단 |
| `dc110c4` | rcept_no 커서 폐기 + dedup ticker 정규화 |
| `125b000` | SEC 신선도 필터 (24h backlog 방지) |
| `04b35cc` | SEC 추적 8개 추가 (LRCX/AMAT/KLAC/VRT/ANET/SMCI/DELL/QCOM) |
| `bc6cfa6` | DART 키워드 fallback (잠정실적 누락 버그) |
| `d30080d` | RSS 4피드 보강 (TechCrunch/Reuters Tech/Bloomberg Tech/Google Blog) |

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
2. **`CLAUDE.md`** — 프로젝트 전체 + 작업 운영 모드
3. **`BRIEFING_HANDOFF.md`** — 4/23 시점 브리핑봇 상세 (참고 보존)
4. **`ISSUE_BOT_SPEC.md`** — 이슈봇 설계 1,121줄 (Phase 로드맵)
5. **`telegram_bot/history/style_canon.md`** — 이슈봇 카드 스타일 경전

---

## 🎬 새 세션 첫 마디 예시

```
SESSION_HANDOFF.md 읽고 현재 상태 파악해줘.
그 다음 [구체 작업 지시].
```

도메인 지정 예:
- `이슈쪽 X 추가해줘` / `시황쪽 Y 수정해줘`
- `점검해줘` / `리뷰해줘` (점검 모드 — 코드 수정 X)

---

**모든 것 OK. 단일 세션 통합 운영. 다음 세션에서 이어가세요.** 🚀

*Last updated: 2026-04-28 — 32 RSS 피드 + 28 SEC CIK + 잠정실적 파서 + 컨센 비교 완비*
