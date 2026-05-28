# stocknow.ai API 리버싱 핸드오프

**대상**: 이 프로젝트를 넘겨받는 다른 Claude 세션
**목적**: stocknow.ai (`app.stocknow.ai`) 내부 API를 파악해서 어닝콜 전문·SEC 공시·재무·뉴스를 직접 수집할 수 있도록 하는 레퍼런스
**검증일**: 2026-04-24 (모든 엔드포인트 curl 테스트 완료)
**원본 리버싱**: 네트워크 캡처 + JS 번들(`main-CHZZh6oA.js`, `ticker-worker-http-Yje7FLvl.js`, `stock-detail-panel-CL4r8WPB.js`) 분석

---

## 0. 30초 TL;DR

- stocknow.ai는 **어닝콜 전문(영/한 문장 매핑) + SEC 공시 AI 요약 + 재무제표 + 통합 이벤트 캘린더**를 제공하는 한국어 증권 서비스
- 대부분의 API는 **인증 없이 호출 가능** (`/api/earnings/*`, `/api/conference-call/*`, `/api/tickers/{T}/stats`, `/api/newsfeed/*`, `/api/breaking-news/*`, `/api/tickers/{T}/events`)
- 일부는 `sn-device-id` 헤더만 있으면 OK (`/api/tickers/{T}/fundamentals`, `/api/documents/*`) — 로그인 없이도 **아무 UUID나 넣어도 됨**
- 어닝콜 전문 JSONL은 S3+CloudFront로 **완전 공개** (`resources.stocknow.ai/transcripts/...`)
- **이슈 봇 / 브리핑 봇에서 핵심 활용처**: 어닝콜 전문·요약, SEC 공시 한국어 AI 요약, 구조화된 실적 보고서, 경제·이벤트 캘린더

---

## 1. 인증 패턴

### 1.1 세 가지 레벨

| 레벨 | 방법 | 접근 가능 엔드포인트 |
|------|------|---------------------|
| 🆓 무인증 | 헤더 불필요 | 시세·뉴스·어닝콜·이벤트·검색·속보 대부분 |
| 🔑 Device ID | `sn-device-id: <UUID>` | 재무제표·SEC 공시·AI 해설 |
| 🔒 JWT | `Authorization: Bearer <token>` | 관심종목·스크랩·유저정보 |

### 1.2 Device ID 얻는 법
브라우저 localStorage `SN-DEVICE-ID`에 저장됨. **형식만 UUID면 임의값도 작동**한다:
```python
DEVICE_ID = "269f70b8-535f-45ae-a469-f6d7106bf597"  # 실사용 예시, 아무 UUID나 OK
headers = {"sn-device-id": DEVICE_ID}
```

### 1.3 에러 패턴
- `HTTP 400 {"message":"Device ID is required"}` → `sn-device-id` 헤더 추가
- `HTTP 500 {"error":"No static resource ..."}` → 존재하지 않는 경로
- `HTTP 500 {"error":"Required request parameter 'from' ..."}` → 필수 쿼리 누락

---

## 2. 엔드포인트 전체 카탈로그

Base URL: `https://stocknow.ai/api`
CDN: `https://resources.stocknow.ai`

### 2.1 종목 기본
| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `GET /tickers/{T}` | 🆓 | id/name/sector/industry/marketCap |
| `GET /tickers/{T}?detailedInfo=true` | 🆓 | + description |
| `GET /search?query={q}` | 🆓 | 종목 검색 (최대 19개) |
| `GET /tickers/top20` | 🆓 | 시총 상위 20 |
| `GET /tickers/top100` | 🆓 | 시총 상위 100 |

### 2.2 시세·차트
| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `GET /tickers/{T}/last-trade` | 🆓 | `{price, ticker, timestamp}` |
| `POST /tickers/current-prices` | 🆓 | body `{"tickers":[...]}` → market status + 가격 |
| `GET /tickers/{T}/today-stats` | 🆓 | 오늘 5분봉 intraday (~78개, Pre+Reg+After) |
| `GET /tickers/{T}/recent-daily-stats` | 🆓 | 최근 2일 일봉 |
| `GET /tickers/{T}/stats?timespan={TS}` | 🆓 | **TS ∈ {1d,1w,1m,3m,1y,5y}** — 바 자동 샘플링 |
| `GET /tickers/{T}/stats?from={ms}&to={ms}` | 🆓 | 커스텀 구간 (UNIX ms) |
| `POST /tickers/watchlist` | 🆓 | body `{"tickers":[...]}` → 복수 종목 메타+당일+최근일봉 일괄 |

**timespan 실측 바 개수 (GOOGL):**
```
1d=192, 1w=136, 1m=245, 3m=62, 1y=251, 5y=61
```
(짧은 범위 → 분봉/일봉, 긴 범위 → 주봉/월봉 자동 샘플링)

### 2.3 재무제표 — `sn-device-id` 필요
| 엔드포인트 | 설명 |
|-----------|------|
| `GET /tickers/{T}/fundamentals` | 전체 (ticker/cik/tickerMeta/ratios/incomeStatements/balanceSheets/cashFlowStatements/keyMetrics) |
| `GET /tickers/{T}/fundamentals/incomeStatements` | 손익계산서 10분기 |
| `GET /tickers/{T}/fundamentals/balanceSheets` | 재무상태표 10분기 |
| `GET /tickers/{T}/fundamentals/cashFlowStatements` | 현금흐름표 10분기 |

### 2.4 SEC 공시 — `sn-device-id` 필요
| 엔드포인트 | 설명 |
|-----------|------|
| `GET /document-types?sourceType=sec&ticker={T}` | 공시 타입 목록 (10-K/10-Q/8-K/4 등 23종) |
| `GET /documents/ticker/{T}?pageSize=20` | 공시 목록 (cursor 페이지네이션) |
| `GET /documents/ticker/{T}?types=10-K,8-K&pageSize=20` | 타입 필터 |
| `GET /documents/{id}` | 공시 상세 + **AI 한국어 요약** + `documentPath`(SEC 원본 URL) |

### 2.5 실적 & 어닝콜 🔥 (이 프로젝트의 핵심)
| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `GET /earnings/{T}` | 🆓 | 종목의 실적 이벤트 10분기 (`earningsConferenceCalls` 배열 포함) |
| `GET /earnings?from={ms}&to={ms}&pageSize=N` | 🆓 | 기간 내 전체 실적 (시장 전체 스캔) |
| `GET /conference-call/{id}` | 🆓 | 어닝콜 상세 — summary/outlook/guidance/qna + **liveTranscriptUrl** |
| `GET {liveTranscriptUrl}` | 🆓 | S3 JSONL — 문장 단위 영/한 매핑 |
| `GET /earnings-by-id/{earning_id}/earnings-report` | 🆓 | 구조화 실적 보고서 (부문별 매출/마진/가이던스 트리) |
| `GET /agent/earnings-report/{id}` | 🔑 | AI 실적 해설 |

**어닝콜 JSONL 스키마:**
```json
{"s":0.1, "e":4.76, "p":"0", "S":"11", "t":"English text", "tr":"한국어 번역"}
```
- `s/e` 시작/끝 초, `p` 문단 ID, `S` 발화자 ID, `t` 영문, `tr` 국문

### 2.6 이벤트 일정
| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `GET /tickers/{T}/events?page=0&pageSize=50` | 🆓 | **EarningsCall/ConferenceCall/Earnings 통합** (개발자 키노트·증권사 컨퍼런스도 포함) |
| `GET /economic-events?from={ms}&to={ms}` | 🆓 | FOMC/CPI/ISM 등 거시 이벤트 |

이벤트 내 `eventUrl: "/ConferenceCall/{id}"` 에서 call_id 추출 → `/api/conference-call/{id}` 로 상세 조회.

### 2.7 뉴스·속보
| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `GET /newsfeed?pageSize=18` | 🆓 | 글로벌 통합 뉴스피드 |
| `GET /newsfeed/ticker/{T}?pageSize=50&cursor={c}` | 🆓 | 종목 뉴스피드 (breaking + news 혼합) |
| `GET /news-article/{id}` | 🆓 | 일반 뉴스 상세 (title/content/summary/**url/source/publisher**) |
| `GET /breaking-news?order=desc&pageSize=20` | 🆓 | 속보 목록 |
| `GET /breaking-news/{id}` | 🆓 | **originalTitle/Content(영문 원문) + 번역 + link(원본 URL) + reference(제공처)** |
| `GET /agent/breaking-news/{id}` | 🔑 | AI 속보 분석 |
| `GET /breaking-news/category` | 🆓 | 카테고리 13개 |
| `GET /breaking-news/keywords` | 🆓 | 키워드 목록 |
| `GET /market-news-articles?pageSize=10` | 🆓 | 시장 뉴스 |

**뉴스 태깅 로직 (서버 측)**:
- 각 기사에 `tickers: ["AAPL","GOOGL","META"]` 다중 태그가 미리 매핑됨
- `/newsfeed/ticker/{T}`는 `T in article.tickers` 필터일 뿐
- 실측: GOOGL 피드 50건 중 90%가 복수 태그, 5종목 교집합 18건

### 2.8 기타
| 엔드포인트 | 인증 |
|-----------|------|
| `GET /now-cast-info` | 🆓 |
| `GET /agent/search/unified?query={q}` | 🔑 |
| `GET /agent/presets` | 🆓 |
| `GET /user/me` | 🔒 (JWT) |
| `GET /user/favorite-tickers` | 🔒 |
| `GET /scraps` | 🔒 |

---

## 3. 바로 쓸 수 있는 Python 스니펫

### 3.1 기본 클라이언트
```python
import urllib.request, json, time

BASE = "https://stocknow.ai/api"
CDN = "https://resources.stocknow.ai"
DEVICE_ID = "00000000-0000-0000-0000-000000000000"  # 임의 UUID OK

def sn_get(path, device=False, timeout=10):
    req = urllib.request.Request(f"{BASE}{path}")
    if device:
        req.add_header("sn-device-id", DEVICE_ID)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def sn_post(path, body, timeout=10):
    req = urllib.request.Request(
        f"{BASE}{path}",
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
```

### 3.2 종목 차트 (1년치 일봉)
```python
d = sn_get("/tickers/NVDA/stats?timespan=1y")
for bar in d["stats"]:
    # bar: {startTimestamp, et, volume, openPrice, closePrice, highPrice, lowPrice, market}
    ...
```

### 3.3 어닝콜 전문 다운로드
```python
import pathlib

def download_call(ticker, save_dir):
    earnings = sn_get(f"/earnings/{ticker}")
    save_dir = pathlib.Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    for e in earnings:
        for call in (e.get("earningsConferenceCalls") or []):
            url = call.get("liveTranscriptUrl")
            if not url:
                continue
            fy = f"{call['fiscalYear']}{call['fiscalPeriod']}"
            t_path = save_dir / f"{ticker}_{fy}_transcript.jsonl"
            m_path = save_dir / f"{ticker}_{fy}_meta.json"
            urllib.request.urlretrieve(url, t_path)
            urllib.request.urlretrieve(f"{BASE}/conference-call/{call['id']}", m_path)
            print(f"{ticker} {fy}: {t_path.stat().st_size}B")

download_call("NVDA", "./data/earnings_calls/NVDA")
```

### 3.4 SEC 공시 목록 + 원본 URL
```python
docs = sn_get("/documents/ticker/GOOGL?pageSize=10&types=10-K,10-Q,8-K", device=True)
for item in docs["items"]:
    detail = sn_get(f"/documents/{item['id']}", device=True)
    print(detail["documentPath"])  # SEC EDGAR 원본 URL
    print(detail["summary"])       # stocknow의 한국어 AI 요약
```

### 3.5 이번 주 실적 발표 예정 종목
```python
now_ms = int(time.time() * 1000)
week_ms = now_ms + 7*24*3600*1000
upcoming = sn_get(f"/earnings?from={now_ms}&to={week_ms}&pageSize=100")
for e in upcoming:
    print(f"{e['eventAt']} {e['ticker']} {e['fiscalPeriod']}{e['fiscalYear']} est EPS={e['epsEst']}")
```

### 3.6 속보 + 원본 링크
```python
news = sn_get("/breaking-news?order=desc&pageSize=20")
# news[*]: {id, title(한), originalTitle(영), link, reference, categoryName, tickers}
for n in news:
    print(f"[{n.get('categoryName')}] {n['title']}")
    print(f"  원본: {n.get('link')} (from {n.get('reference')})")
```

### 3.7 재무제표
```python
fund = sn_get("/tickers/NVDA/fundamentals", device=True)
# fund: {ticker, cik, tickerMeta, ratios, incomeStatements[10], balanceSheets[10], cashFlowStatements[10], keyMetrics[10]}
print(f"CIK: {fund['cik']}")  # SEC EDGAR 공시 추적용 CIK
print(f"최근 분기 EPS: {fund['ratios']['earningsPerShare']}")
```

---

## 4. 원본 소스 추적 가능 여부

### 4.1 원본이 있고 **직접 수집이 더 안정적**인 것
| stocknow 데이터 | 원본 | 직접 수집 API |
|-----------------|------|--------------|
| SEC 공시 (10-K/Q/8-K/4) | SEC EDGAR | `https://data.sec.gov/submissions/CIK{10자리}.json` |
| 재무제표 (XBRL) | SEC XBRL | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` |
| 시세 | 다수 벤더 | Polygon / yfinance / IEX (이미 봇에서 사용) |
| 마켓 캘린더 | NYSE/NASDAQ | `pandas_market_calendars` |
| 경제 이벤트 | Fed / BLS / BEA | FRED / BLS API |
| YahooFinance 뉴스 | Yahoo | `https://finance.yahoo.com/rss/headline?s={T}` |

### 4.2 stocknow **고유 가치가 있어** 직접 쓰는 게 낫은 것
| 데이터 | 이유 |
|--------|------|
| 어닝콜 영/한 전문 JSONL | 문장 타임스탬프 매핑 + 번역 품질, 직접 ASR+번역보다 싸고 정확 |
| SEC 공시 AI 한국어 요약 | 10-K 400페이지 → 한국어 요약, 직접 구현 시 LLM 비용 부담 |
| 속보 번역 + 원본 쌍 | Newsquawk 등 유료 소스 대체 (`originalTitle` + `title` 동시) |
| 통합 이벤트 타임라인 | EarningsCall + ConferenceCall + 개발자 키노트 한 번에 |
| 구조화 실적 보고서 | 부문별 매출·마진·가이던스를 트리로 파싱해둠 |

### 4.3 원본 없음 (stocknow 가공물)
- AI 요약·해설 (`summary`, `aiContent`, `/agent/*`)
- 실적 보고서 구조화 파싱
- 한국어 번역 전반

---

## 5. Gotchas ⚠️

1. **SPA 라우팅 이슈**: `https://app.stocknow.ai/stock/{T}/schedule` 직접 URL로 열면 홈으로 리다이렉트. 브라우저 자동화 시 watchlist에서 종목 클릭 후 탭 클릭 필요 (API 직접 호출은 영향 없음).

2. **차트 데이터는 Web Worker**: `window.fetch` hook으로 안 잡힘. 실제 URL은 `ticker-worker-http-*.js` 안에 있고 API 본체는 동일 (`/api/tickers/{T}/stats?timespan=...`).

3. **timespan 값 소문자**: `1D` 아닌 `1d`, `1Y` 아닌 `1y` (대문자 넣으면 HTTP 500).

4. **economic-events·earnings는 UNIX ms 필수**:
   - ❌ `?from=2026-04-24` → 500
   - ✅ `?from=1777011959858&to=1777616759858`

5. **한국 종목 미지원**: `/earnings/005930` (삼성전자) → `[]`. stocknow는 **미국 종목 전용**.

6. **어닝콜 ID는 ticker에 종속 안 됨**: `/conference-call/61722` 에서 call_id는 글로벌 유일. events 목록의 `eventUrl: "/ConferenceCall/{id}"` 에서 추출.

7. **transcript URL 예측 불가**: `{T}-{id}-{ISO8601-timestamp}-finished.jsonl` 에서 timestamp 부분은 녹음 처리 완료 시각이라 미리 알 수 없음 → **반드시 `/conference-call/{id}` 선조회 후 `liveTranscriptUrl` 추출**.

8. **CloudFront cache 없음**: transcript 파일에 `Cache-Control: no-cache` → 매번 S3 조회. 다운로드 속도 일정.

9. **개발자 키노트도 ConferenceCall**: Google Cloud Next 2026 Developer Keynote (call_id=171365) 같은 건 `eventType: "Conference"` 로 구분되고 `period/fiscalPeriod`가 빈 문자열.

10. **ToS 미확인**: 상업용 재배포 전 약관 검토 필요. 현재는 리서치·내부 자동화 용도로 해석.

---

## 6. 이미 확보한 샘플 데이터

```
data/earnings_calls/
├── CDNS/
│   ├── CDNS_2025Q4_transcript.jsonl   (509 lines, 69분)
│   ├── CDNS_2025Q4_meta.json
│   ├── CDNS_2025Q3_transcript.jsonl   (632 lines)
│   ├── CDNS_2025Q3_meta.json
│   ├── CDNS_2025Q2_transcript.jsonl   (643 lines)
│   └── CDNS_2025Q2_meta.json
└── GOOG/
    ├── GOOG_CloudNext2026_DeveloperKeynote_transcript.jsonl  (637 lines, 64분)
    └── GOOG_CloudNext2026_DeveloperKeynote_meta.json
```

각 `meta.json`에 포함된 요약 섹션 (한국어):
- `summary` — 핵심 3~5줄
- `outlook` — 향후 전망
- `guidance` — 구체 가이던스
- `executiveComment` — 경영진 코멘트
- `qna` — Q&A 페어 배열
- `liveSummary` — 타임스탬프 기반 요약 (오디오 구간 매핑)

---

## 7. 이슈 봇 통합 우선순위 제안

1. **Earnings transcript collector** (`telegram_bot/collectors/earnings_transcript.py` 신규)
   - 대형주 리스트 매일 스캔 → 새 call_id 감지 → 전문 + 요약 저장
   - `ISSUE_BOT_SPEC.md`의 "실적 커버리지" 요건 보강
2. **SEC disclosure monitor** — 10-K/10-Q/8-K 자동 감지 → AI 요약 카드화
3. **구조화 실적 보고서** — `/earnings-by-id/{id}/earnings-report` 파싱 → 부문별 매출 비교 카드
4. **속보 번역 파이프라인** — `/breaking-news` + `reference` 필드로 출처 명시 + 한국어 번역 활용

---

## 8. 참고

- 리버싱 대상 JS 번들 (변경될 수 있음):
  - `https://app.stocknow.ai/assets/main-CHZZh6oA.js` (4.7MB, API 클라이언트 정의)
  - `https://app.stocknow.ai/assets/ticker-worker-http-Yje7FLvl.js` (1.6KB, 차트 URL 패턴)
  - `https://app.stocknow.ai/assets/stock-detail-panel-CL4r8WPB.js` (재무·공시 탭 로직)
- 사이트: <https://app.stocknow.ai>
- 리소스 CDN: <https://resources.stocknow.ai>
