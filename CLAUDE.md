# NODE Research 텔레그램 브리핑 봇

## 프로젝트 개요
KIS Open API + Claude API + yfinance를 활용한 텔레그램 자동 시황 브리핑 봇.
하루 8개 메시지 발송 (모닝 4개, 이브닝 4개).

## 현재 상태 (2026-04-13)

### 메시지 구조
```
모닝 (07:00 KST)
  1. 📊 데이터 카드 (미국 증시/환율/금리/원자재/야간 프록시/전일 국내)
  2. 📋 미장 마감 리뷰 (시황 텍스트 — 별도 메시지)
  3. 📰 장전 주요 뉴스
  4. 📅 오늘 일정

이브닝 (16:00 KST)
  1. 📊 데이터 카드 (당일 증시/수급/환율/원자재/52주)
  2. 📋 오늘 시장 (시황 텍스트 — 별도 메시지)
  3. 📰 장중 주요 뉴스
  4. 📅 내일 일정
```

### 핵심 이슈 — 시황 품질 갭
- Sonnet(API 자동): 82점 (프롬프트 강화 후)
- Opus: 92점
- COMMENTARY_MODEL 환경변수로 Sonnet/Opus 전환 가능
- 원인: 모델 능력 차이 + 대화 맥락 유무
- 선택지: Sonnet 유지(월 $5) vs Opus 변경(월 $25)

---

## 프로젝트 구조
```
텔레그램 시황 브리핑/
├── .env                          # API 키 (git 제외)
├── .gitignore
├── CLAUDE.md                     # 이 파일
├── .github/workflows/
│   ├── morning.yml               # 모닝 자동 발송 (07:00 KST)
│   └── evening.yml               # 이브닝 자동 발송 (16:00 KST)
└── telegram_bot/
    ├── config.py                 # 환경변수, 종목코드, 섹터 ETF
    ├── kis_client.py             # KIS API 클라이언트 (토큰/rate limit)
    ├── main.py                   # 엔트리포인트 (morning/evening/test)
    ├── briefings.py              # 브리핑 실행 로직
    ├── sender.py                 # 텔레그램 발송
    ├── requirements.txt
    ├── collectors/
    │   ├── global_market.py      # 미국지수/VIX/DXY/환율/금리/원자재/미장섹터/종목/KORU
    │   ├── domestic_market.py    # KOSPI/KOSDAQ/수급/섹터ETF/52주/거래대금/상승률 순위
    │   ├── news_collector.py     # RSS 18개 + Claude 필터링 + 시황 생성 프롬프트
    │   ├── schedule_collector.py # 고정일정(FOMC/CPI) + FnGuide 실적 캘린더
    │   ├── consensus_collector.py # FnGuide 분기 컨센서스 크롤링
    │   ├── intraday_collector.py # 장중 흐름(시가→고가→저가→종가) + 외국인 지분율
    │   ├── investor_trend.py    # 외국인/기관 N일 연속 수급 트렌드
    │   ├── valuation_collector.py # FnGuide 12M PER/PBR
    │   └── market_context.py    # 시장 컨텍스트 관리 + 한지영 채널 크롤링
    ├── formatters/
    │   ├── morning.py            # 모닝 데이터 카드 포맷
    │   ├── evening.py            # 이브닝 데이터 카드 포맷
    │   ├── news.py               # 뉴스 포맷 (섹터 이모지 19개)
    │   └── schedule.py           # 일정 포맷
    └── history/
        ├── briefing_memory.py    # 이전 시황 저장/조회
        ├── market_context.txt    # 시장 컨텍스트 (자동 업데이트)
        └── analyst_raw.txt       # 한지영 원본 (초기 학습용)
```

---

## 데이터 소스

### KIS API (한국투자증권)
- 국내: KOSPI/KOSDAQ 지수, 업종 시세, 섹터 ETF 10종, 수급, 거래대금/상승률 30종목, 52주 신고저
- 해외: S&P500(SPX), NASDAQ(COMP), DOW(.DJI), 환율(FX@KRW), 금리 종합
- 기타: 장중 흐름(시가/고가/저가/종가), 외국인 지분율, 휴장일
- rate limit: 초당 3건 자동 대기 (0.35초 간격)

### yfinance
- VIX(^VIX), DXY(DX-Y.NYB)
- 원자재: WTI(CL=F), 금(GC=F), 구리(HG=F)
- 미장 섹터 ETF 11개 (XLK/SOXX/XLE 등)
- 미장 주요 종목 10개 (NVDA/AAPL/TSLA 등)
- 야간 프록시: KORU, EWY, 코스피200(^KS200)

### FnGuide
- 분기 컨센서스 (영업이익)
- 실적 캘린더 (잠정실적/실적발표 — ico_01 클래스)
- 12M PER, 업종 PER, PBR

### RSS 뉴스 (18개)
- 국내: 한경 마켓/경제, 연합 경제/산업, 매경 기업
- 해외: Reuters, CNBC, WSJ
- 섹터: TrendForce, Electrek, InsideEVs, FiercePharma, Defense News, World Nuclear News
- 커뮤니티: r/investing, r/wallstreetbets, r/stocks

### 한지영 텔레그램 (t.me/hedgecat0301)
- 매일 최신 1개 코멘트 크롤링 → 시장 컨텍스트로 활용
- 초기 학습: 21개 메시지에서 지정학/매크로/섹터/수급/밸류에이션 추출

---

## 시황 프롬프트 핵심 원칙

### 한지영 스타일에서 배운 것
1. **국면 프레이밍** — "3월 이후 조정 장세가 전환점" 같은 큰 그림
2. **장중 과정 서술** — 결론만 쓰지 않고 시간순 스토리
3. **구조적 고민 나열** — "시장이 뭘 고민하는지" 2~3가지
4. **컨센 경로** — "38조(컨센) → 50조(일부 전망) → 57.2조(실제)"
5. **수급 트렌드** — "연초 이후 57조 순매도, 8거래일 만에 전환"
6. **전략 시간축** — "4월 말 컨콜, 5월 초 M7까지 확인 후"
7. **투자자 심리 공감** — "이런 고민은 자연스러운 반응"

### Gemini 크로스체크에서 배운 것
1. 개인 매도는 "News Sell" — 과잉 해석 금지
2. PER이 낮다고 무조건 저평가 아님
3. "선별적 접근" 같은 모호한 결론 금지
4. 환율→외국인 환차손→추가 매도 경로 반드시 포함
5. 양면 시각 (긍정/부정 시나리오 모두)

### 우리 채널 원칙 (Gemini 피드백과 다른 점)
- 리딩/종목추천 금지 ("20% 덜어내라" 같은 구체적 비중 금지)
- "~적절하지 않을까 싶습니다" 수준의 방향성만
- 투자자가 스스로 판단할 여지를 남김

### 팩트 검증 규칙
1. 시스템 미제공 데이터 만들어내기 금지
2. "독점/유일/최초" 확인 안 되면 금지
3. 편향 금지 (특정 종목 하나가 시장 좌우한 것처럼 X)
4. 근거 없는 우려/낙관 금지
5. 데이터 용어 그대로 사용 (영업이익→매출 변환 금지)
6. 구체적 수치 예측 금지 ("4%대 급등 예상")

### 줄바꿈 규칙
- 내용이 달라지는 곳에서 빈 줄
- 전환어("다만", "반면", "한편") 앞에서 빈 줄
- 새로운 섹터/종목 시작 시 빈 줄
- 문장 중간 줄바꿈 절대 금지

---

## 수정 이력 (최근)

### 2026-04-13
- 시스템 프롬프트 할루시네이션 방지 5규칙 추가
- 방향성 단정 금지 ("강세 출발" → 긍정/부정 병렬)
- 장전 프리마켓 묘사 금지, 잘못된 인과관계 방지
- 중소형주 세일즈 인상 방지 (섹터 트렌드로 묶어서 서술)
- APScheduler misfire_grace_time=900 추가
- crontab 10분 → 하루 3회(06:30, 15:30, 17:00) 변경
- 테스트 스케줄(17:10) 제거, _wait_until 제거
- 뇌 업데이트 실패 로그 + 날짜 기록 의무화
- 채권 스프레드 방향 수정 (2Y-10Y → 10Y-2Y)
- 52주 신고가 ETF/스팩/우선주 필터
- Sonnet/Opus 모델 선택 기능 (COMMENTARY_MODEL 환경변수)
- 한지영 전건 저장 (중간 누락 방지)
- 시황 품질 65점 → 82점 개선
- deploy.sh git config 반복 제거
- KIS API → 키움 REST API 전면 교체 예정
- 모닝/이브닝 데이터 카드 레이아웃 전면 개편

### 2026-04-08
- 수급 날짜 버그 수정 (전일→당일 우선 조회)
- GitHub Actions 모닝/이브닝 분리 (briefing.yml → morning.yml + evening.yml)
- 시황을 별도 메시지로 분리 (데이터 카드와 분리)
- 모닝 프롬프트 전면 교체 (팩트검증 + 줄바꿈 + 국면정의 + 레퍼런스 예시)
- 이브닝 프롬프트 전면 교체 (동일)
- 한지영 채널 매일 크롤링 추가
- 뉴스 할루시네이션 방지 ("기사 원문만 요약")
- 뉴스 중복 "절대 금지" 강화
- 섹터 이모지 누락 수정 (반도체/AI, 매크로/에너지, 정책 등)

### 2026-04-07
- KIS API 스킬 8개 제작
- 프로젝트 전체 코드 작성 (18개 파일)
- 뉴스 필터링 10회 반복 테스트
- 섹터별 이모지 19개 매핑
- FnGuide 실적 캘린더 + 컨센서스 크롤링
- 장중 흐름 + 외국인 N일 연속 + 밸류에이션 수집
- 이전 브리핑 기억 기능
- KIS rate limit 대응 (초당 3건)
- GitHub Actions 배포 + Secrets 설정
- Gemini 크로스체크 → 프롬프트 반영
- 한지영 채널 초기 학습 (21개 메시지)

---

## 비용

| 항목 | 월 비용 |
|------|---------|
| Anthropic API (Sonnet) | ~$5 |
| KIS API | 무료 |
| yfinance | 무료 |
| 텔레그램 | 무료 |
| GitHub Actions | 무료 |
| **합계** | **~$5 (약 7,500원)** |

Opus 모델로 변경 시: ~$25/월

---

## 실행 방법
```bash
cd "텔레그램 시황 브리핑"
pip install -r telegram_bot/requirements.txt

python -m telegram_bot.main test      # 데이터 수집 테스트
python -m telegram_bot.main morning   # 모닝 브리핑 수동 실행
python -m telegram_bot.main evening   # 이브닝 브리핑 수동 실행
python -m telegram_bot.main           # 스케줄러 모드 (07:00/16:00)
```

---

## 남은 작업
1. **시황 품질 안정화** — 프롬프트 튜닝 + 데이터 의미 주석(annotate_data) 구현
2. **Opus vs Sonnet 결정** — 비용 대비 품질 판단
3. **캘린더 페이지** — GitHub Pages 웹 캘린더 + 텔레그램 일정 연동
4. **구조 리팩토링** — data/ 폴더 분리, 스킬 자동화
5. **GitHub Actions 안정화** — cron 지연 모니터링
6. **DART API** — 실적 공시 자동 수집 (선택)

---

## GitHub
- 리포: valscope-sys/telegram-briefing-bot (Private)
- 텔레그램: t.me/noderesearch
- 봇: @noderesearch_bot
