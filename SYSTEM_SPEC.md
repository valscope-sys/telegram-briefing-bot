# NODE Research 텔레그램 브리핑 봇 — 완전 작동 명세서

이 문서는 텔레그램으로 발송되는 **8개 메시지**(모닝 4개 + 이브닝 4개)의 생성 과정을 0.1%도 빠짐없이 기술합니다.

---

## 실행 인프라

- **서버**: AWS Lightsail Ubuntu 24.04 (ap-northeast-2, 512MB RAM, 2vCPU)
- **프로세스**: systemd `telegram-bot.service` → `python -u -m telegram_bot.main`
- **스케줄러**: APScheduler `BlockingScheduler(timezone=KST)`
  - 모닝: `CronTrigger(hour=7, minute=0, day_of_week="mon-fri")` → `run_morning_briefing()`
  - 이브닝: `CronTrigger(hour=16, minute=0, day_of_week="mon-fri")` → `run_evening_briefing()`
  - `misfire_grace_time=900` (재시작 후 15분 내 보충 실행)
- **배포**: crontab으로 deploy.sh 실행 (06:30, 15:30, 17:00)
  - deploy.sh: `git add history/ → commit+push(뇌 백업) → git pull → 코드 변경 시 restart`
- **주말 체크**: `is_weekday()` → `datetime.date.today().weekday() < 5` (토/일 스킵)

---

## 모닝 브리핑 (07:00 KST) — 4개 메시지

### [메시지 1] 🌐 모닝 브리핑 (데이터 카드)

**파일**: `briefings.py:46-76` → `formatters/morning.py:format_morning_briefing()`

**실행 순서**:
1. `fetch_all_global()` 호출 → 글로벌 데이터 수집
2. `fetch_all_domestic()` 호출 → 국내 데이터 수집
3. `format_morning_briefing(global_data, domestic_data)` → 포맷팅
4. `send_message(msg1)` → 텔레그램 발송

**수집되는 데이터 전체 목록 (`global_market.py:fetch_all_global()`)**:

```python
{
    "indices": {
        "S&P 500": {현재가, 전일대비, 등락률, 부호},  # KIS API 일봉차트 (N시장, SPX)
        "NASDAQ": {...},   # KIS API (COMP)
        "DOW": {...},      # KIS API (.DJI)
        "VIX": {...},      # yfinance ^VIX, history(period="5d") 마지막 2일 비교
    },
    "fx": {
        "USD/KRW": {현재가, 전일대비, 등락률, 부호},  # KIS API 환율차트 (X시장, FX@KRW)
        "DXY": {...},      # yfinance DX-Y.NYB, history(5d)
    },
    "bonds": {
        "미국 2Y": {이름, 금리, 전일대비, 부호},  # KIS API 금리종합 (output1, Y0203)
        "미국 10Y": {...},   # KIS API (Y0202)
        "연방기금금리": {...}, # KIS API (Y0204)
        "국고채 3Y": {...},  # KIS API (output2, Y0101)
        "국고채 10Y": {...}, # KIS API (Y0106)
    },
    "commodities": {
        "WTI": {현재가, 전일대비, 등락률, 부호},  # yfinance CL=F, history(5d)
        "금": {...},    # yfinance GC=F
        "구리": {...},  # yfinance HG=F
    },
    "us_sectors": {  # yfinance, 각각 history(5d)
        "기술": {...},    # XLK
        "반도체": {...},  # SOXX
        "에너지": {...},  # XLE
        "헬스케어": {...}, # XLV
        "금융": {...},    # XLF
        "산업재": {...},  # XLI
        "소비재": {...},  # XLY
        "유틸리티": {...}, # XLU
        "소재": {...},    # XLB
        "통신": {...},    # XLC
        "부동산": {...},  # XLRE
    },
    "us_stocks": {  # yfinance, config.py US_MAJOR_STOCKS에서 정의
        "NVDA": {종목명, 현재가, 전일대비, 등락률},  # 엔비디아
        "AAPL": {...},  # 애플
        "MSFT": {...},  # 마이크로소프트
        "GOOGL": {...}, # 구글
        "AMZN": {...},  # 아마존
        "TSLA": {...},  # 테슬라
        "META": {...},  # 메타
        "AVGO": {...},  # 브로드컴
        "TSM": {...},   # TSMC
        "AMD": {...},   # AMD
        "SNDK": {...},  # 샌디스크
        "INTC": {...},  # 인텔
        "ORCL": {...},  # 오라클
    },
    "korea_proxies": {  # yfinance
        "KORU": {현재가, 등락률, 설명},  # 한국3x레버리지 ETF
    },
    "sentiment": {
        "Fear & Greed": {점수, 등급, 원문},  # CNN API (production.dataviz.cnn.io)
    },
}
```

**수집되는 데이터 전체 목록 (`domestic_market.py:fetch_all_domestic()`)**:

```python
{
    "indices": {
        "KOSPI": {현재가, 전일대비, 등락률, 부호, 거래대금, 상승, 하락, 보합},
        "KOSDAQ": {...},
        # KIS API inquire-index-price (U시장, 0001/1001)
        # 장전(거래대금 0)이면 일별차트에서 전일 데이터로 폴백
    },
    "investors": {
        외국인, 기관, 개인, 외국인금액, 기관금액, 개인금액, 날짜
        # KIS API inquire-investor-daily-by-market
        # 당일 먼저 시도, 없으면 최근 5영업일 순회
    },
    "program": {차익순매수, 비차익순매수, 합계순매수},
        # KIS API comp-program-trade-today
    "sectors": {  # KIS API inquire-price, 각 ETF 종목코드로
        "반도체": {현재가, 등락률, 부호},  # 091160
        "2차전지": {...},  # 305720
        "바이오": {...},   # 244580
        "방산": {...},     # 457480
        "에너지": {...},   # 117460
        "자동차": {...},   # 091180
        "금융": {...},     # 091170
        "건설": {...},     # 117010
        "철강": {...},     # 117000
        "게임": {...},     # 214980
    },
    "sector_stocks": {  # KIS API inquire-price, 각 종목코드로
        "반도체": [삼성전자(005930), SK하이닉스(000660)],
        "2차전지": [LG에너지솔루션(373220), 에코프로비엠(247540)],
        ... (8개 섹터, 각 2종목)
    },
    "highlow": {  # 이브닝에서만 사용 (모닝에서는 수집은 하지만 포맷에 미포함)
        "신고가": [{종목명, 종목코드, 현재가, 등락률, 부호, 섹터}, ...]
    },
    "trade_value_rank": [{종목명, 종목코드, 현재가, 등락률, 거래량, 거래대금}, ...],
        # KIS API volume-rank (거래금액순, 최대 30종목)
    "top_gainers": [{종목명, 종목코드, 현재가, 등락률, 거래대금}, ...],
        # KIS API fluctuation (상승률순, 최대 30종목, 1000원+, 1만주+)
    "top_losers": [{...}, ...],
        # KIS API fluctuation (하락률순)
    "sector_investor_flow": [  # 키움 REST API ka10051
        {업종, 외국인(억원), 기관(억원)}, ...  # 28개 업종
    ],
}
```

**데이터 카드 포맷 (`formatters/morning.py`)**:
```
📊 *미국 증시*
  S&P500, NASDAQ, DOW: 현재가 + 등락률(소수점2)
  VIX: 현재가(소수점2) + 등락률

🏷 *미국 섹터*
  us_sectors 11개에서 등락률순 정렬 → 상위3 "▲" 줄 + 하위3 "▼" 줄

💱 *환율 · 금리*
  USD/KRW: 현재가(소수점1) + 전일대비(소수점2)
  DXY: 현재가(소수점2) + 등락률
  미국채 2Y/10Y: 금리(소수점2%) + 스프레드(10Y-2Y, bp단위, int)
  국고채 3Y/10Y: 금리(소수점2%) — bonds에 데이터 있을 때만

🛢 *원자재*
  WTI/금/구리: $현재가(소수점2) + 등락률

😱 *심리지표*
  Fear & Greed: 점수(정수) + 등급(한국어)

🌙 *야간 프록시*
  KORU: 현재가(소수점2) + 등락률

🇰🇷 *전일 국내 증시*
  KOSPI/KOSDAQ: 현재가(소수점2) + 등락률 + 거래대금(조, 백만원÷1,000,000)
  상승/하락/보합: KOSPI 기준
  외국인/기관/개인: 금액(백만원÷100=억원)
```

**단위 변환 규칙**:
- 거래대금: KIS API 백만원 단위 → ÷1,000,000 = 조원
- 수급 금액: KIS API 백만원 단위 → ÷100 = 억원
- 프로그램매매: KIS API 백만원 단위 → ÷100 = 억원
- 환율 전일대비: KIS API 원본 그대로 (전 거래일 종가 대비)
- 채권 스프레드: (10Y금리 - 2Y금리) × 100 = bp (양수=정상, 음수=역전)

---

### [메시지 2] 📋 미장 마감 리뷰 (시황)

**파일**: `briefings.py:67-86` → `news_collector.py:generate_morning_commentary()`

**시황 생성에 전달되는 데이터 (프롬프트에 포함되는 모든 것)**:

1. **미국 지수** — S&P500/NASDAQ/DOW 현재가+등락률
2. **미국 섹터 ETF 11개** — 각 등락률
3. **미국 주요 종목 13개** — 각 현재가+등락률+종목명
4. **원자재** — WTI/금/구리 현재가+등락률
5. **환율** — USD/KRW 현재가+전일대비
6. **채권금리** — 미국 2Y/10Y 금리+전일대비, 10Y-2Y 스프레드
7. **심리지표** — Fear & Greed 점수+등급, Put/Call Ratio(있으면)
8. **뉴스 8건** — 제목 + detail(Claude 요약) + 본문(스크래핑 300자)
9. **수급 트렌드** — 외국인/기관 N거래일 연속 매수/매도 + 누적금액 + 최근 5일 일별
10. **전일 이브닝 시황** — latest_evening.json에서 500자 (briefing_memory.py)
11. **시장 컨텍스트** — market_context.txt (2000자) + 한지영 최신 1건 (2000자)

**Claude API 호출**:
```python
model = COMMENTARY_MODEL  # 기본 "claude-sonnet-4-20250514", 환경변수로 opus 전환 가능
max_tokens = 2000
system = PROMPT_SYSTEM  # 절대 규칙 9개
messages = [{"role": "user", "content": prompt}]  # 위 데이터 + 프롬프트 지시사항
```

**시황 프롬프트 구조 지시**:
```
1: 미장 핵심 동인 (2~3문장) — "왜" 중심, 이벤트(원인)→파생변수(결과) 순서
2: 섹터 로테이션 + 금리/통화/원자재 (3~4문장) — DXY, 채권금리, 로테이션 흐름
3: 오늘 한국 체크포인트 (3~4문장) — 매크로부터, 방향성 단정 금지, 야간프록시 활용
4: 수급 + 리스크 체크 (2~3문장) — 시나리오형, 양비론 금지
```

**시스템 프롬프트 절대 규칙** (9개):
1. 데이터/뉴스에 있는 내용만 사용
2. 뉴스 목록에 없는 뉴스 인용 금지
3. 수급 연속일수는 트렌드 데이터 숫자만
4. 방향성 단정 금지
5. 과거 이벤트 현재형 금지
6. 실적 추정치 출처 명시 의무
7. 경제지표 비교기준 + 서프라이즈 방향 의무
8. VIX 절대 레벨 표기 의무
9. 목표가 구체적 수치 없으면 금지

**후처리** (`postprocess.py`):
1. 화살표(→) → 콤마로 변환
2. 하이픈 복원 (미이란→미-이란, 미중→미-중)
3. 전환어("다만","반면","한편") 앞 빈 줄
4. 주제 전환 앞 빈 줄
5. 국면 정의 첫 문장 뒤 빈 줄 (한국어 서술형 마침표 패턴)
6. 중복 빈 줄 정리 (3줄→2줄)
7. 어색한 표현 교체 (3개)
8. 한영 혼용 오타 수정 ("아마zon"→"아마존")

**발송**: `send_message(commentary_msg)` — Markdown 파싱, 실패 시 일반텍스트 재시도

---

### [메시지 3] 📰 장전 주요 뉴스

**파일**: `briefings.py:93-104` → `formatters/news.py:format_premarket_news()`

**뉴스 수집 흐름**:
1. `fetch_rss_news()` — 16개 RSS 피드에서 48시간 이내 기사 수집 (각 피드 최대 50건)
   - 국내: 한국경제, 매일경제, 이데일리 (각 전체 뉴스 RSS)
   - 국내정책: 금융위, 한국은행, 산업부
   - 해외: Reuters, CNBC, WSJ
   - 섹터: TrendForce, Electrek, InsideEVs, FiercePharma, Defense News, World Nuclear News
   - 각 기사: source, group(국내/해외), title, link, published, summary(200자)

2. `filter_news_with_claude(raw_news, context="장전 브리핑")` — Claude Sonnet 1회 호출
   - 최대 150건 기사 목록을 프롬프트에 전달
   - 13개 섹터 트리거 기준으로 중요도(상/중) 평가
   - 출력: JSON 배열 [{index, importance, sector, title, detail, direction}]
   - 중복 기사 합치기 규칙
   - 절대 제외: 인사/채용/CSR, 보험/카드 광고, 범죄/연예, 과거뉴스, 클릭베이트

3. `enrich_news_bodies(filtered_news)` — 선택된 뉴스의 원문 본문 스크래핑
   - `concurrent.futures.ThreadPoolExecutor(max_workers=5)`
   - 각 기사 URL → BeautifulSoup → article/p 태그에서 500자 추출
   - timeout 15초

**뉴스 포맷** (`formatters/news.py`):
```
{섹터이모지} [{섹터}] {방향이모지} [{제목}](링크)
   {detail 요약}
```
- 섹터 이모지: 48개 매핑 (반도체📟, 2차전지🔋, 바이오💊, 방산🪖, ...)
- 방향: 긍정🟢, 부정🔴, 중립⚪
- 최대 10건

---

### [메시지 4] 📅 오늘 일정

**파일**: `briefings.py:108-116` → `schedule_collector.py:fetch_today_schedule()` → `formatters/schedule.py`

**일정 데이터 소스**:
1. `calendar.json` (cal_data/calendar.json) — 통합 일정 파일
   - FnGuide JSON API → 한국 실적/IR/배당/유증/주총 (자동, GitHub Actions)
   - Finnhub API → 미국 실적 + 경제지표 (자동)
   - 38.co.kr → 신규상장/공모청약 (자동)
   - 고정 이벤트 → FOMC/금통위/CPI 등 (수동, 연 1~2회)
   - AI 뉴스 스캔 → 뉴스에서 일정 추출 (반자동)

2. DART API → 당일 공시 실시간 보완

**텔레그램 일정 필터 기준** (`schedule_collector.py`):
- **무조건 포함**: 경제지표, 통화정책, 만기일
- **실적 섹션**: 한국실적, 한국실적(잠정), 미국실적
- **IR**: 시총 상위 50 기업만 (TOP50_CORPS 딕셔너리)
- **이벤트**: IPO/공모, 산업컨퍼런스, 게임, 전시/박람회 등
- **제외**: 기업이벤트(액면분할/병합/유증/무증/합병/소각), 소형주 IR
- **제외**: unconfirmed=true (AI 추출 미확인), undated=true (날짜 미확정)

**경제지표 자동 필터** (`_filter_economic_events()`):
- 파생 지표 제거: YTD, QoQ, Press Conference, Core CPI/PPI, CPI MoM, 감독위원 발언, 의사록, Continuing Jobless 등
- 영문→한글 번역: 40개+ 지표 매핑 (GDP→GDP, CPI→소비자물가, Retail Sales→소매판매 등)
- 같은 시간+같은 국가 중복 병합

**포맷** (`formatters/schedule.py`):
```
📅 *오늘 일정*
04월 15일

{시간}  {국가이모지} {이벤트명}
실적  {기업명1}, {기업명2}, ...

[전체 일정 보기](GitHub Pages URL)
```

---

## 이브닝 브리핑 (16:00 KST) — 4개 메시지

### [메시지 1] 📋 이브닝 브리핑 (데이터 카드)

**파일**: `briefings.py:134-228` → `formatters/evening.py:format_evening_briefing()`

**모닝과 다른 점 — 이브닝 전용 데이터**:
- `fetch_intraday_summary()` — KOSPI/KOSDAQ 장중 시가/고가/저가/종가 + 주요종목 5개 장중흐름 + 외국인 지분율
- `fetch_investor_trend_ndays()` — N일 연속 순매수/순매도 + 누적금액
- `fetch_market_valuation()` — FnGuide 12M PER/PBR (try/except, 실패 무시)
- `fetch_consensus()` — FnGuide 분기 컨센서스 (오늘 실적발표 종목만, 주요 대형주 9개 코드 매핑)
- `fetch_sector_investor_flow()` — 키움 ka10051, 28개 업종별 외국인/기관 순매수(억원)

**이브닝 데이터 카드 포맷**:
```
📊 *당일 증시* — KOSPI/KOSDAQ + 상승/하락/보합
💰 *수급* — 외국인/기관/개인/프로그램
💱 *환율 · 원자재* — USD/KRW, WTI, 금, 구리
🏷 *섹터* — ETF 등락률 상위3+하위3
🔺 *52주 신고가* — 테마별 그룹핑
```

**52주 신고가 전체 흐름**:
```
키움 REST API ka10016 POST https://api.kiwoom.com/api/dostk/stkinfo
  → mrkt_tp:"000", ntl_tp:"1", high_low_close_tp:"2", stk_cnd:"3",
    trde_qty_tp:"00010", updown_incls:"0", dt:"250", stex_tp:"1"
  → 응답: ntl_pric[] (stk_cd, stk_nm, cur_prc, flu_rt, trde_qty)
  → ETF 필터 (TIGER/KODEX/KBSTAR/HANARO/SOL/ARIRANG/ACE/KOSEF/RISE/KIWOOM/ITF/PLUS/KoAct/TIMEFOLIO/레버리지/인버스/ETN/스팩/리츠/머니마켓/인프라/액티브)
  → 거래량 0 제외
  → 5종목 미만이면 60초 대기 후 재시도
  → Claude Sonnet 테마 분류 (1회 호출, 종목명 전체 전달)
     프롬프트: 오분류 사례 명시 (레이=치과, 에이치케이=부동산 등)
     "모르면 기타" 원칙
  → 폴백: 키움 실패 시 KIS near-new-highlow API
  → 포맷: (테마명) 종목1, 종목2, ... (종목수 내림차순)
```

---

### [메시지 2] 📋 오늘 시장 (시황)

**파일**: `news_collector.py:generate_market_commentary()`

**시황 프롬프트에 전달되는 데이터 전체 목록**:

```
=== 오늘 시장 데이터 ===
KOSPI: 현재가 (등락률%)
KOSDAQ: 현재가 (등락률%)

수급: 외국인 ±N억 / 기관 ±N억 / 개인 ±N억

업종별 외국인 순매수 (억원):  ← 키움 ka10051
  상위5개 업종: 외국인 ±N억 / 기관 ±N억
  ...
  하위3개 업종: 외국인 ±N억 / 기관 ±N억

섹터 ETF 등락:
  반도체: ±N.NN%  삼성전자(±N.N%), SK하이닉스(±N.N%)
  2차전지: ±N.NN%  LG에너지솔루션(±N.N%), 에코프로비엠(±N.N%)
  ... (10개 섹터)

거래대금 상위 30종목:
  1. 종목명 ±N.NN%
  ...

상승률 상위 15종목 / 하락률 상위 15종목

채권금리:
  미국 2Y: N.NNN% (±N.NNN%p)
  미국 10Y: N.NNN% (±N.NNN%p)
  10Y-2Y 스프레드: ±N.NNN%p
  국고채 3Y/10Y: (있으면)

심리지표:
  Fear & Greed Index: N점 (등급)
  Put/Call Ratio: N.NN (해석)

뉴스 (제목 + 요약 + 본문):
  - [섹터] 제목 (방향)
    요약: ...
    본문: ...

섹터-뉴스 매칭:
  [섹터 ±N.N%] 관련 뉴스: ...

장중 흐름:
  KOSPI: 시가 N, 고가 N(시가대비 ±N%), 저가 N(시가대비 ±N%), 종가 N
  주요종목: 삼성전자 시가 N(±N%), 종가 N(±N%) | 고가 N / 저가 N
  외국인 지분율: 삼성전자 N.N%, SK하이닉스 N.N%

수급 트렌드:
  외국인: N거래일 연속 순매수/매도 (누적 ±N억원)
  기관: N거래일 연속 순매수/매도 (누적 ±N억원)
  최근 5일 일별: 날짜별 외국인/기관

이전 모닝 시황 (500자)

시장 컨텍스트 (2000자) + 한지영 최신 코멘트 (2000자)

밸류에이션 (있으면): KOSPI 12M PER, 업종 PER, PBR

실적 컨센서스 (있으면): 종목 분기별 영업이익 컨센서스
```

**이브닝 시황 프롬프트 구조**:
```
1: 국면 정의 (1~2문장)
2: 핵심 동인 (2~3문장) — 이벤트→파생변수 순서, 채권금리 포함
3: 섹터 로테이션 (3~4문장) — 로테이션 흐름, "왜" 중심, 유가↔섹터 방향성 가이드
4: 수급 (2~3문장) — 외국인/기관/개인 + 업종별 집중도
5: 리스크 체크 시나리오형 (2~3문장) — 양비론 금지, 구체적 시나리오
```

**이브닝 후 자동 실행**:
- `save_briefing("evening", commentary, key_data)` → latest_evening.json 저장
- `update_market_context(commentary)` → Claude Sonnet 1회 추가 호출 → market_context.txt 갱신
  - 기존 컨텍스트 + 오늘 시황 → 업데이트된 컨텍스트 생성
  - 첫 줄에 날짜 기록 의무
  - 3일 이상 지난 이벤트 제거
  - 실패 시 에러 로그 출력 (무음 실패 방지)

---

### [메시지 3] 📰 장중 주요 뉴스

**모닝과 동일 로직**, 차이점:
- `filter_news_with_claude(raw_news, count=5, context="장후 브리핑, 장중 시장 영향 뉴스 위주")`
- Claude API **별도 1회 호출** (모닝 뉴스와 다른 결과)

---

### [메시지 4] 📅 내일 일정

**모닝과 동일 로직**, 차이점:
- `fetch_tomorrow_schedule()` — 내일 날짜. 금요일이면 월요일로 점프.

---

## 파일별 역할 전체 목록

| 파일 | 줄수 | 역할 |
|---|---|---|
| `main.py` | 126 | 엔트리포인트, APScheduler, CLI (morning/evening/test) |
| `briefings.py` | 270 | 모닝/이브닝 실행 오케스트라 (수집→포맷→발송) |
| `config.py` | 104 | 환경변수, API키, 섹터ETF코드, 종목리스트 |
| `kis_client.py` | 90 | KIS API 클라이언트 (토큰캐싱, rate limit 0.35초, 재시도) |
| `kiwoom_client.py` | 58 | 키움 REST API 클라이언트 (토큰캐싱, POST) |
| `sender.py` | 61 | 텔레그램 Bot API 발송 (Markdown, 실패시 재시도) |
| `postprocess.py` | 69 | 시황 후처리 (화살표/줄바꿈/오타) |
| `collectors/global_market.py` | 322 | 해외 데이터 (KIS+yfinance+CNN) |
| `collectors/domestic_market.py` | 565 | 국내 데이터 (KIS+키움) + 52주 신고가 |
| `collectors/news_collector.py` | 711 | RSS수집 + Claude필터 + 시황생성 프롬프트 |
| `collectors/market_context.py` | 138 | 뇌 관리 + 한지영 스크래핑 |
| `collectors/investor_trend.py` | 128 | N일 연속 수급 트렌드 |
| `collectors/intraday_collector.py` | 182 | 장중 시가/고가/저가/종가 |
| `collectors/schedule_collector.py` | 312 | 일정 (calendar.json + DART + 필터) |
| `collectors/consensus_collector.py` | 114 | FnGuide 분기 컨센서스 |
| `collectors/valuation_collector.py` | 79 | FnGuide PER/PBR |
| `formatters/morning.py` | 153 | 모닝 데이터카드 포맷 |
| `formatters/evening.py` | 121 | 이브닝 데이터카드 포맷 |
| `formatters/news.py` | 98 | 뉴스 포맷 (섹터이모지 48개) |
| `formatters/schedule.py` | 59 | 일정 포맷 (캘린더 링크 포함) |
| `history/briefing_memory.py` | 70 | 이전 시황 저장/로드 |
| `history/market_context.txt` | ~2000자 | 시장 국면 기억 (이브닝 후 갱신) |
| `history/analyst_raw.txt` | 누적 | 한지영 코멘트 전건 저장 |

---

## API 호출 총량 (하루)

| API | 호출 | 용도 | 비용 |
|---|---|---|---|
| Claude Sonnet | 6회 | 뉴스필터×2 + 시황×2 + 뇌갱신×1 + 신고가테마×1 | ~$0.15 |
| KIS API | ~60건 | 지수/수급/섹터/종목/환율/금리 | 무료 |
| 키움 API | 2건 | 52주 신고가 + 업종별 수급 | 무료 |
| yfinance | ~30건 | VIX/DXY/원자재/섹터/종목/KORU | 무료 |
| CNN API | 1건 | Fear & Greed | 무료 |
| RSS | 16건 | 뉴스 수집 | 무료 |
| DART API | 2건 | 오늘/내일 공시 | 무료 |
| 텔레그램 Bot API | 8건 | 메시지 발송 | 무료 |

---

## 환경변수 (.env)

```
KIS_APP_KEY=...
KIS_APP_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=...
ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
FMP_API_KEY=...
KIWOOM_APP_KEY=...
KIWOOM_APP_SECRET=...
COMMENTARY_MODEL=sonnet  # 또는 opus
```
