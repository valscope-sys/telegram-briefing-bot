# NODE Research 텔레그램 브리핑 봇

## 프로젝트 개요
한국투자증권(KIS) Open API + Claude API를 활용한 텔레그램 자동 시황 브리핑 봇.
하루 6개 메시지 발송 (장전 3개, 장후 3개).

## 브리핑 구조

| 시간 | 메시지 1 | 메시지 2 | 메시지 3 |
|------|----------|----------|----------|
| 장전 07:00 | 모닝 브리핑 (글로벌 시황) | 장전 뉴스 (5건) | 오늘 일정 |
| 장후 16:00 | 이브닝 브리핑 (당일 증시+시황해석) | 장중 주요 뉴스 (5건) | 내일 일정 |

## 프로젝트 구조
```
텔레그램 시황 브리핑/
├── .env                       # API 키 (git 미포함)
├── .gitignore
├── CLAUDE.md                  # 이 파일
└── telegram_bot/
    ├── config.py              # 환경변수, 종목코드 설정
    ├── kis_client.py          # KIS API 클라이언트 (OAuth 토큰, GET/POST)
    ├── main.py                # 엔트리포인트 (스케줄러 + 수동실행)
    ├── briefings.py           # 브리핑 실행 로직 (수집→포맷→발송)
    ├── sender.py              # 텔레그램 메시지 발송
    ├── requirements.txt
    ├── collectors/
    │   ├── global_market.py   # 해외지수, 환율, 금리, 원자재
    │   ├── domestic_market.py # KOSPI/KOSDAQ, 수급, 섹터ETF, 52주
    │   ├── news_collector.py  # RSS 뉴스 + Claude 필터링/시황생성
    │   └── schedule_collector.py  # 경제일정(investing.com) + DART실적
    └── formatters/
        ├── morning.py         # 모닝 브리핑 메시지 포맷
        ├── evening.py         # 이브닝 브리핑 메시지 포맷
        ├── news.py            # 뉴스 메시지 포맷
        └── schedule.py        # 일정 메시지 포맷
```

## .env 파일 형식
```
KIS_APP_KEY=발급완료
KIS_APP_SECRET=발급완료
KIS_ACCOUNT_NO=미입력 (8자리-2자리)
KIS_IS_PAPER=false

TELEGRAM_BOT_TOKEN=미입력
TELEGRAM_CHANNEL_ID=미입력

DART_API_KEY=미입력

ANTHROPIC_API_KEY=미입력
```

## 실행 방법
```bash
pip install -r telegram_bot/requirements.txt

# 데이터 수집 테스트
python -m telegram_bot.main test

# 모닝 브리핑 수동 실행
python -m telegram_bot.main morning

# 이브닝 브리핑 수동 실행
python -m telegram_bot.main evening

# 스케줄러 모드 (평일 07:00, 16:00 자동 발송)
python -m telegram_bot.main
```

## 현재 진행 상황

### 완료된 것
- [x] KIS API 스킬 8개 제작 (~/.claude/commands/kis-*.md)
- [x] 프로젝트 구조 + 모든 모듈 코드 작성 완료
- [x] KIS API 인증 + 토큰 캐싱 동작 확인
- [x] 국내 데이터 수집 동작 확인: KOSPI/KOSDAQ 지수, 섹터 ETF, 금리
- [x] 해외 데이터 수집 동작 확인: S&P500(SPX), NASDAQ(COMP), DOW(.DJI), USD/KRW(FX@KRW)
- [x] 투자자매매동향 파라미터 수정 완료 (FID_COND_MRKT_DIV_CODE="U" + 추가 필수 파라미터)
- [x] 프로그램매매 파라미터 수정 완료
- [x] GitHub 리포 생성: valscope-sys/telegram-briefing-bot (Private)
- [x] 초기 커밋 완료 (push는 인증 설정 후 필요)

### 남은 이슈 (우선순위 순)
1. **Git push**: GitHub 인증(credential) 설정 후 push 필요
   ```bash
   cd "C:\Users\user\Desktop\텔레그램 시황 브리핑"
   git push -u origin main
   ```

2. **원자재 데이터 (WTI/금/구리)**: 해외선물 API가 500 에러 반환
   - 해외선물옵션 서비스가 별도 신청 필요할 수 있음
   - 대안: yfinance 라이브러리로 원자재 조회 (pip install yfinance)
   - 또는 KIS API 포털에서 해외선물옵션 서비스 신청

3. **52주 신고가/신저가**: 빈 배열 반환
   - near-new-highlow API 파라미터 확인 필요
   - 대안: fluctuation(등락률순위) API에서 상위/하위 추출

4. **VIX/DXY**: KIS 차트 API에서 코드 미확인
   - 대안: yfinance로 VIX(^VIX), DXY(DX-Y.NYB) 조회

5. **나머지 API 키 입력**: 텔레그램 봇 토큰, DART, Anthropic

## 테스트 결과 (2026-04-03)

### 정상 동작
| 데이터 | API | 코드 | 결과 |
|--------|-----|------|------|
| S&P 500 | 차트API(N) | SPX | 6582.69 |
| NASDAQ | 차트API(N) | COMP | 21879.18 |
| DOW | 차트API(N) | .DJI | 46504.67 |
| USD/KRW | 차트API(X) | FX@KRW | 1506.50 |
| 미국 10Y | 금리종합 | Y0202 | 4.31% |
| 미국 1Y T-BILL | 금리종합 | Y0203 | 3.68% |
| 국고채 3Y | 금리종합 | Y0101 | 3.443% |
| 국고채 10Y | 금리종합 | Y0106 | 3.744% |
| KOSPI | 업종현재지수 | 0001 | 5377.30 (+2.74%) |
| KOSDAQ | 업종현재지수 | 1001 | 1063.75 (+0.70%) |
| 투자자매매동향 | 일별 | - | 외국인 +808억, 기관 +723억 |
| 섹터 ETF | 현재가 | 10종목 | 반도체 +3.39%, 에너지 +2.72% 등 |

### 미해결
| 데이터 | 문제 | 대안 |
|--------|------|------|
| WTI/금/구리 | 해외선물API 500에러 | yfinance 또는 서비스 신청 |
| VIX | 차트API 코드 미확인 | yfinance ^VIX |
| DXY | 차트API 코드 미확인 | yfinance DX-Y.NYB |
| 52주 신고/저 | 빈 배열 | 파라미터 재확인 |

## KIS API 스킬 (다른 대화방에서도 사용 가능)
`~/.claude/commands/` 에 저장된 8개 스킬:
- `/kis-auth` - 인증, 토큰, 공통함수
- `/kis-domestic-stock` - 국내주식 시세
- `/kis-overseas-stock` - 해외주식/지수/환율
- `/kis-market-index` - 업종/지수/금리/시장분석
- `/kis-ranking` - 순위분석 (거래량/등락률/시총 등)
- `/kis-portfolio` - 잔고/주문/손익
- `/kis-futures` - 선물/옵션/원자재
- `/kis-stock-info` - 종목정보/재무/공시/뉴스

## 기술 스택
- Python 3.11+
- requests, python-dotenv, APScheduler
- python-telegram-bot, feedparser, beautifulsoup4, lxml
- anthropic (Claude API - 뉴스 필터링 + 시황 해석)
