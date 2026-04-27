# NODE Research 실시간 이슈 봇 — 설계 명세서 v1.1

**상태**: 설계 완료 (독립 검토 반영), Phase 0 착수 대기
**작성일**: 2026-04-21 (v1.0)
**개정일**: 2026-04-21 (v1.1 — Critical 6건 + Major 10건 반영)
**관계**: 기존 브리핑 봇(`SYSTEM_SPEC.md`)과 **독립 모듈**. 동일 텔레그램 봇 토큰 + 동일 채널 공유.

---

## 0. 목적

DART 공시 + RSS 뉴스 + (향후) 기업 IR/리서치 리포트에서 **실시간 이슈**를 자동 감지하여, 메리츠 증권 Tech 채널(`t.me/merITz_tech`)에서 학습한 스타일로 정제된 요약문 생성 → **관리자 수동 승인 후** `@noderesearch` 채널에 발송.

**학습 기반**: 메리츠 Tech 채널 70+ 샘플(타입 A + NONE, 2026-01 ~ 2026-04) 분석
**차별점**: 메리츠는 반도체/IT 전담. 본 봇은 **최종적으로 33개 섹터 커버**. 단, **MVP는 3개 섹터(반도체 + IT부품 + 2차전지)로 축소 시작** 후 2주 운영 검증 후 단계적 확장.

---

## 1. 전체 아키텍처

```
[소스 계층]
  DART 공시 (Phase 1 신규) + RSS 16개 (기존 재활용)
  → [Phase 2+]: 기업 IR, 리서치 기관(TrendForce/Digitimes/Prismark 등)
    ↓
[필터 계층 - Claude Haiku]
  4단계 중요도 분류 + Template 카테고리(A~E) 판정 + 섹터 태깅
  SKIP → 즉시 폐기 (비용 절감)
    ↓
[중복 감지]
  구조화 해시 키 기반 seen_ids 조회
  중복이면 "더 상세한 쪽 메인" 규칙 적용
    ↓
[Peer 매핑 계층 - Claude Sonnet + 웹검색]
  국내 관련 종목 자동 추론 + Peer 검증
  (예: Yageo 실적 → 삼성전기·코스모화학 매핑)
  confidence < 0.7이면 "Peer 미확정" 표시
    ↓
[생성 계층 - Claude Sonnet + 하이브리드 스타일 + 프롬프트 캐싱]
  카테고리별 완벽 예시 + R1~R8 규칙 하드 주입
  → 승인 카드에 표시될 최종 요약문 생성
    ↓
[자체 린트]
  R1~R8 위반 자동 검사 (정규식 + 구조 검증)
    ↓
[승인 계층 - 텔레그램 봇 DM (즉시)]
  우선순위별 타임아웃 차등 적용 (URGENT 15분 / HIGH 45분 / NORMAL 2h)
  [✅ 발송] [✏️ 수정] [❌ 스킵] 인라인 버튼
  대량 대기 시 [📦 묶음 승인] 버튼
    ↓
[발송 계층]
  이브닝 보호 구간(16:20~16:50) 회피
  승인 시 @noderesearch 발송
  수정 시 force_reply로 답장 매칭 → 수정본 린트 → 발송
  이력/로그 저장 (학습 루프용)
```

---

## 2. 데이터 소스

### 2.1 Phase 1 (초기, 3개 섹터 우선)

| 소스 | 커버 | 호출 방식 | 기존 모듈 재사용 |
|------|------|-----------|-------------------|
| **DART API** | 전 산업 공시 | `list.json` 폴링 + KIND HTML 본문 추출 | ❌ 신규 |
| **RSS 16개** | 국내/해외 뉴스 | 기존 `news_collector.py:fetch_rss_news()` | ✅ 재사용 |

**⚠️ DART API 실제 동작 (v1.1 추가)**:
- `list.json`은 `bgn_de`, `end_de`, `corp_cls`, `last_reprt_at` 등 파라미터 사용. `page_count=100` 단위 페이징.
- **반영 지연**: 공시 접수 후 5~15분 지연 후 API에 노출. "즉시 알림"의 기준은 사건 발생이 아닌 DART 노출 시점.
- `document.xml`은 ZIP 파일 반환(XBRL 원본). 텍스트 요약에 사용 곤란.
- **본문 추출**: KIND(`dart.fss.or.kr`) HTML 페이지 크롤링 (`rcept_no`로 URL 조립) → BeautifulSoup로 주요 내용 섹션 파싱.
- **Phase 0 검증 항목**: 실제 API 응답 구조 확인, `report_nm` 분포 조사, 본문 추출 안정성 테스트.

### 2.2 Phase 2+ (확장)

| 소스 | 커버 | 상태 |
|------|------|------|
| 기업 IR 페이지 크롤링 | 삼성전자/하이닉스 등 Top50 분기 실적 | 신규 |
| TrendForce, Digitimes, Prismark | 반도체/디스플레이/IT부품 | 기존 RSS 일부 연결됨 (TrendForce, Electrek, InsideEVs, FiercePharma, Defense News, World Nuclear News) |
| BloombergNEF, SNE Research | 2차전지·신재생 | 신규 |
| Clarksons, SCFI, BDI | 조선·해운 | 신규 |
| Henry Hub, JKM, Platts | LNG·원유·금속 | 신규 |
| FDA, EMA, ClinicalTrials.gov | 바이오 임상·승인 | 신규 |
| SIPRI, Defense News, Jane's | 방산 수주 | 일부 기존 |

### 2.3 폴링 스케줄 (v1.1 세분화)

| 구간 | 평일 | 주말 |
|------|------|------|
| 07:00~09:00 (미국 프리마켓 + 한국 장전) | **15분 간격** | 60분 |
| 09:00~16:00 (한국 장중) | 15분 간격 | 60분 |
| **16:20~16:50 (이브닝 브리핑 보호)** | **폴링 중단** | 폴링 중단 |
| 16:50~18:00 (KRX 장후) | 15분 간격 | 60분 |
| 18:00~22:00 (국내 DART 피크) | 30분 간격 | 120분 |
| 22:00~01:00 (미국 장 시작 전후) | 30분 간격 | 120분 |
| 01:00~07:00 (미국 장중·새벽) | 60분 간격 | 120분 |

- **이브닝 브리핑 보호 구간 (16:20~16:50)**: 이슈봇 폴링·발송 모두 중단. 16:30 이브닝 브리핑이 4개 연속 메시지 발송 후 간섭 방지.
- **모닝 브리핑 보호 구간 (06:50~07:10)**: 모닝 브리핑 준비/발송 시간 보호.

---

## 3. 섹터 매핑 — 최종 33개, Phase 1은 3개

### 3.0 Phase별 오픈 순서

| Phase | 기간 | 오픈 섹터 | 근거 |
|-------|------|-----------|------|
| **MVP (Phase 1)** | 2주 운영 | 반도체, IT부품/PCB, 2차전지 | 메리츠 학습 샘플 풍부, Peer 매핑 시드 확보, 승인 폭주 리스크 낮음 |
| **Phase 1.5** | +2주 | 디스플레이, 스마트폰, 자동차, 바이오/제약 | 국내 대형주 집중 섹터 |
| **Phase 2** | +4주 | 나머지 26개 섹터 점진 오픈 | 학습 루프 데이터 축적 후 |

### 3.1 IT/테크

| 섹터 | 해외 Peer | 국내 타겟 | 전용 소스 |
|------|-----------|-----------|-----------|
| 반도체 ⭐P1 | TSMC, 마이크론, 키옥시아, Nanya, Phison | 삼성전자, SK하이닉스 | TrendForce, DRAMeXchange, Omdia, SEMI, SIA |
| 디스플레이 | BOE, CSOT, JDI | 삼성디스플레이, LG디스플레이 | Witsview, Omdia, DSCC |
| 반도체 장비 | ASML, AMAT, TEL, LAM, KLAC | 원익IPS, 세메스, 유진테크 | SEMI WFE |
| IT부품/PCB ⭐P1 | Unimicron, Kinsus, Yageo, Topoint, GCE | 대덕전자, 심텍, LG이노텍, 네오티스, 이수페타시스 | Prismark, Digitimes |
| 스마트폰 | Apple, Xiaomi, 화웨이, 오포 | 삼성전자 MX | Counterpoint, Canalys |
| PC/서버 | Dell, HPE, Supermicro, Wistron, Foxconn | - | IDC, Gartner |

### 3.2 에너지/소재

| 섹터 | 해외 Peer | 국내 타겟 | 전용 소스 |
|------|-----------|-----------|-----------|
| 2차전지 ⭐P1 | CATL, BYD, Panasonic, Northvolt | LG에너지솔루션, 삼성SDI, SK온, 에코프로비엠 | BloombergNEF, SNE Research, Benchmark Mineral |
| 전기차 | Tesla, BYD, Rivian, Lucid | 현대차, 기아 (E-GMP) | EV-Volumes, Kelley Blue Book |
| 석유/가스 | ExxonMobil, Shell, Chevron | S-Oil, GS칼텍스, SK이노베이션 | NYMEX(WTI), ICE(Brent), EIA |
| LNG/천연가스 | Cheniere, Venture Global, Woodside | SK E&S, 한국가스공사 | Henry Hub, JKM, Platts LNG |
| 원전/원자력 | Westinghouse, EDF, Rosatom | 두산에너빌리티, 한전KPS, 우진엔텍 | World Nuclear News, UxC |
| 신재생 | First Solar, Vestas, Orsted | 한화솔루션, 씨에스윈드, 씨에스베어링 | BloombergNEF, IEA |
| 수소 | Plug Power, Ballard, Nel | 효성중공업, 두산퓨얼셀, 일진하이솔루스 | Hydrogen Insights |
| 철강/금속 | Nippon Steel, Baosteel, Nucor | POSCO홀딩스, 현대제철, 동국제강 | Mysteel, LME, Platts Metals |
| 화학 | BASF, Dow, SABIC | LG화학, 롯데케미칼, 한화솔루션 | ICIS, Platts Olefins |

### 3.3 산업/운송

| 섹터 | 해외 Peer | 국내 타겟 | 전용 소스 |
|------|-----------|-----------|-----------|
| 조선 | Fincantieri, MHI, Hyundai Mipo | HD현대중공업, 한화오션, 삼성중공업 | Clarksons, LNG 선가지수 |
| 해운/물류 | Maersk, COSCO, Hapag-Lloyd | HMM, 팬오션, 대한해운 | BDI, SCFI, Freightos |
| 자동차 | Toyota, VW, Ford, Stellantis | 현대차, 기아, 현대모비스, 한온시스템 | IHS Markit, ACEA, SIAM |
| 방산 | Lockheed Martin, RTX, BAE Systems | 한화에어로스페이스, LIG넥스원, 한국항공우주, 현대로템 | SIPRI, Defense News, Jane's |
| 우주항공 | SpaceX, Rocket Lab, Blue Origin | 한화시스템, 쎄트렉아이 | SpaceNews |
| 건설 | Vinci, Bechtel, China Comm | 현대건설, 삼성물산, GS건설, 대우건설 | 국토부 실거래가, ENR |

### 3.4 헬스케어/소비

| 섹터 | 해외 Peer | 국내 타겟 | 전용 소스 |
|------|-----------|-----------|-----------|
| 바이오/제약 | Pfizer, J&J, Novartis, Eli Lilly | 삼성바이오로직스, 셀트리온, 유한양행, 알테오젠, 리가켐바이오 | FDA, EMA, ClinicalTrials.gov, FiercePharma |
| 의료기기 | Medtronic, Abbott, Siemens Healthineers | 루닛, 뷰노, 클래시스, 레이저옵텍 | FDA 510(k), PMA |
| 식품/농업 | Nestle, CJ International, Tyson | CJ제일제당, 하림, 오뚜기, 롯데칠성 | USDA, CBOT |
| 유통/커머스 | Amazon, Walmart, Costco | 쿠팡, 이마트, GS리테일, 현대백화점 | Counterpoint Retail |
| 엔터/미디어 | Netflix, Disney, UMG, Warner | 하이브, 에스엠, YG, JYP, CJ ENM | Spotify Charts, Billboard |
| 게임 | Tencent, Nintendo, Take-Two | 크래프톤, 엔씨소프트, 넷마블, 펄어비스 | Sensor Tower, Newzoo |
| 호텔/레저/항공 | Marriott, Delta, Hilton | 대한항공, 아시아나항공, 호텔신라 | STR Global, IATA |

### 3.5 금융/매크로

| 섹터 | 해외 Peer | 국내 타겟 | 전용 소스 |
|------|-----------|-----------|-----------|
| 금융/은행 | JPM, GS, Citi, BofA | KB금융, 신한지주, 하나금융, 우리금융 | Fed FOMC, BOK |
| 보험 | Allianz, AIG, Prudential | 삼성생명, 한화생명, 현대해상 | 금융감독원 |
| 증권/자산운용 | BlackRock, Morgan Stanley | 미래에셋증권, NH투자증권, 삼성증권, 키움증권 | KRX, KOFIA |
| 부동산 | Prologis, Zillow | SK디앤디, 신세계프라퍼티 | KB부동산, 국토부 |
| 가상자산 | Coinbase, Binance | 두나무, 빗썸 | CoinGecko, Chainalysis |

**⭐P1** = Phase 1 MVP 대상 섹터 (3개).

---

## 4. 우선순위 분류 (4단계) + 타임아웃

필터 단계에서 Claude Haiku가 `priority`, `sector`, `category`(A~E), `reason`을 JSON으로 출력.

### 4.1 우선순위별 승인 타임아웃 (v1.1 차등 적용)

| Priority | 타임아웃 | 리마인더 | 의미 |
|----------|----------|----------|------|
| **URGENT** | **15분** | 10분 경과 시 DM | 시의성 극도로 중요 (서프라이즈, 돌발, 대형 공시) |
| **HIGH** | **45분** | 30분 경과 시 DM | 중요하되 즉시성 덜함 (실적, 가격 변동, Capex) |
| **NORMAL** | **2시간** | 1시간 경과 시 DM | 통계·리포트, 지연 허용 |

### 4.2 각 우선순위 판정 기준

**URGENT**:
- 국내 Top30 종목의 대형 공시 (M&A, 실적 서프라이즈, 대규모 증자·자사주 소각, 경영권 변동)
- 해외 Big5(삼성/하이닉스/TSMC/애플/엔비디아) 관련 실적 서프라이즈
- 돌발 이슈 (지진·정전·파업·긴급 규제 발표)
- 원자재·환율 급변동 (±3% 이상)
- FDA 승인/반려 (주요 바이오)

**HIGH**:
- Top100 종목 분기 실적 발표
- 해외 Peer 월매출 발표 (AI 서버 관련 대만 업체 등)
- 주요 원자재 가격 인상/인하 발표
- 증설·Capex 발표 (1,000억원+)
- 대만 경쟁사 IR 컨센 대비 ±10%

**NORMAL**:
- 월별 수출통계 (TRASS, 관세청)
- 산업 리서치 리포트 (TrendForce, IDC 등)
- 정기 IR 자료
- 중소형주 잠정실적

**SKIP (자동 폐기)**:
- 인사·채용·CSR 공고
- 보험·카드 광고
- 범죄·연예·스포츠
- 기 발송 이슈와 동일 주제 (중복 감지 후)
- 클릭베이트·가십

---

## 5. 톤/스타일 고정 규칙 (R1~R8)

Claude 프롬프트에 **MUST/MUST NOT 하드 제약**으로 주입. 생성 후 **자동 린트**로 위반 검증.

### R1. 헤더
- **MUST (Template A, C, D, E)**: 첫 줄은 `[NODE Research {섹터}]`
- **MUST NOT**: 작성자명, 날짜, 인사말, 이모지 삽입 금지
- **예외**: Template B(국내 공시형)는 헤더 생략 허용, `[{기업명} {공시 유형}]` 형식 직접 시작

### R2. 제목
- **MUST (A, C, D, E)**: `▶` + 공백 + 제목
- **MUST (B)**: `[{제목}]` 대괄호만 (▶ 없음)
- **MUST (E 속보)**: 제목 생략 허용, 본문 바로 시작
- **MUST NOT**: 🔥📈💹 등 어떤 이모지도 금지

### R3. 본문 bullet
- **MUST (A, B, C)**: `-` + 공백1 + 내용. 각 bullet 사이 **빈 줄 1개**
- **MUST (D 수출통계 과거 추이)**: bullet 연속 허용 (빈 줄 생략). 가독성 위해
- **MUST NOT**: `•`, `*`, `·`, 번호(1. 2. 3.) 금지

### R4. 숫자 표기
- **MUST**: 모든 금액에 단위 명시 (`3,597.9백만대만달러`, `7.17조원`, `$415,191M`)
- **MUST**: 증감률은 `(+30.7% MoM, +45.2% YoY)` 쌍으로, 부호 필수
- **MUST NOT**: "약", "대략", "거의" 등 모호 수치 금지
- **허용**: "사상최고", "역대", "최대", "월 최대" 등 정성 서술 (숫자 동반 시)

### R5. 인칭/어조
- **MUST**: 3인칭 — "동사는", "회사는", "{기업명}은"
- **MUST NOT**: "당사는", "저희는", "우리는"
- **MUST**: 전망 표현 — "예상/전망/기대/예측" 허용
- **MUST NOT**: "확실/분명/틀림없이/반드시" 금지

### R6. 출처
- **MUST**: 본문 끝 직전 `(자료: {출처})` 또는 `(출처: {URL} - {언론사})`
- **MUST**: 원문 링크가 있으면 반드시 첨부
- **MUST NOT**: "~한다는 얘기", "~로 알려진" 등 추정 인용 금지

### R7. 면책 문구
- **MUST (A, B, C, D)**: 본문 맨 끝
- **MUST NOT (E 속보)**: 면책 생략 허용

**텔레그램 Markdown 이슈 대응**: 면책 문구 앞 `*`는 Markdown italic으로 파싱됨. 이슈봇은 **`parse_mode=HTML`** 사용 고정 또는 `*`를 `\*`로 escape. 구현 시 `parse_mode="HTML"` 권장.

HTML 모드 면책 문구:
```html
<i>* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.</i>
```

### R8. 금지 표현 (정규식 자동 린트)

| 금지 | 대체 | 린트 정규식 |
|------|------|-------------|
| 급등/폭등/수직상승 | 수치 직접 (`+15.0%`) | `/급등\|폭등\|수직상승\|급락\|폭락/` |
| 매수 추천/매도 권고 | 객관 서술만 | `/매수\s*추천\|매도\s*권고\|투자\s*의견/` |
| 호재/악재 | "수요 확대/둔화" 등 | `/호재\|악재/` |
| 시장은 ~라고 본다 | 특정 출처 인용 시만 | `/시장은\s.*?\s보/` |
| 당사는/저희는 | 3인칭 교체 | `/당사는\|저희는\|우리는/` |
| 확실/분명/반드시 | 전망 표현 교체 | `/확실히\|분명히\|반드시\|틀림없이/` |

**린트 실행**: 생성 직후 자동 검사. 위반 발견 시:
1. 재생성 1회 자동 시도 (위반 항목을 프롬프트에 추가 하드 제약으로 주입)
2. 재생성 후에도 위반 남으면 관리자 DM에 "⚠️ R8 위반: {표현}" 경고와 함께 승인 카드 전송

---

## 6. 카테고리별 템플릿 (A~E)

### Template A — 해외 Peer 월매출/실적

```
[NODE Research {섹터}]

▶ {월} {지역} {분류} 업체 {회사명} 매출액 {금액}({단위})({+MoM%}, {+YoY%}) 발표

- {사상최고/비수기/이벤트 영향 등 맥락 한 줄}

- {분기 누계 또는 12개월 추이}

- {Capex 계획 / 증설 계획 / 가동률}

- {제품 비중 또는 신제품 일정}

(자료: {회사명} ir)

* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
```

**완벽 예시 (R1~R8 전체 통과)**:
```
[NODE Research IT부품]

▶ 3월 대만 ABF+HDI 기판 업체 Unimicron 매출액 13,079.1백만대만달러(+12.7% MoM, +23.3% YoY) 발표

- 2월에 이어 동일 월 기준 사상 최고 매출액을 달성

- AI 서버와 고성능 컴퓨팅(HPC) 수요 강세로 기판 및 PCB 생산 라인 가동률 높은 수준 유지

- 공급자 우위 시장 활용해 유리섬유, 동박 기판, 귀금속 등 원자재 가격 상승이 제품 가격에 반영

- 2026년 AI 관련 매출 비중은 60%를 상회할 전망

(자료: Unimicron ir)

* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
```

### Template B — 국내 공시 (자사주/증자/M&A)

**R1 예외**: `[NODE Research {섹터}]` 헤더 생략.

```
[{기업명} {공시 유형}]

- {전일/당일} {기업명}의 {공시 내용} 체결내역입니다.
  {항목}: {수량/금액}
* {누적 진행률} / {총 한도} ({%})

- {당일 신청내역}:
  {항목}: {수량}

(자료: KIND / DART)
```

**완벽 예시**:
```
[삼성전자 자사주 매매 현황]

- 전일 삼성전자의 자사주 매매 체결내역입니다.
  보통주: 1,371,401주 (신청수량: 1,380,999주)
* 자사주 매입(임직원 주식보상) 공시 금액인 7.17조원 중 전일까지 매수 진행률은 99.7% (7.15조원) 입니다.

- 금일 삼성전자의 자사주 매매 신청내역입니다.
  보통주: 1,800,000주

(자료: KIND)
```

### Template C — 영문 기사/리서치 인용

```
[NODE Research {섹터}]

▶ {영문 원제 또는 한글 번역}

- {bullet 요약 1}

- {bullet 요약 2}

- {bullet 요약 3}

(출처: {URL} - {언론사/기관})

* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
```

### Template D — 월별 수출통계

**R3 예외**: 과거 추이 bullet은 빈 줄 없이 연속.

```
[NODE Research {섹터}]

▶ '{YY}년 {월} 1~{일자} {품목} 수출금액 잠정치 발표

- 1~{일자}일 수출금액: {금액} ({+MoM%}, {+YoY%})
- 중량 기준 수출단가: {단가}/kg ({+MoM%}, {+YoY%})

* 과거 12개월 {품목} 수출금액 추이
- {연월} {금액} ({+MoM%}, {+YoY%})
- {연월} {금액} ({+MoM%}, {+YoY%})
... (12줄 연속)

(출처: TRASS / 관세청)

* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
```

### Template E — 돌발 이슈/속보 (NONE형)

**R7 예외**: 면책 문구 생략.
**R2 예외**: 제목 생략 가능.

```
{종목명 또는 키워드} {상황 한 줄}

{핵심 팩트 1~3줄}

(출처: {URL})
```

**완벽 예시**:
```
일본 이와테현 동쪽 해역 진도 7.4 지진 발생

키옥시아는 이와테현 키타카미에 NAND 팹 보유 중.
174km 떨어진 해역, 내륙에도 진도 2-5 관측.

(출처: NHK)
```

---

## 7. Peer 매핑 (자동 추론 + 검증)

### 7.1 알고리즘

```
1. 이벤트 원문 추출 (회사명, 제품, 이벤트 유형)
2. peer_map.json 먼저 조회 (캐시 역할)
   - 있으면 즉시 반환 (last_verified < 90일)
   - 없거나 오래되면 3~4 단계 진행
3. Claude Sonnet에 질의:
   - "이 이벤트의 국내 Peer 종목은?"
   - 메리츠 학습 샘플 기반 힌트 주입
4. 웹 검색 (Anthropic tool_use: web_search_20250305)
   - "{해외기업명} 국내 경쟁사" 검색
   - 검색 결과로 Claude 추론 검증
5. peer_map.json 업데이트 (confidence + last_verified + evidence)
6. confidence < 0.7이면 승인 카드에 "Peer 미확정" 표시 (관리자 판정)
```

### 7.2 peer_map.json 스키마

```json
{
  "Yageo": {
    "category": "MLCC/수동부품",
    "korean_peers": ["삼성전기", "코스모화학"],
    "confidence": 0.92,
    "last_verified": "2026-04-21",
    "evidence_urls": ["https://..."],
    "verification_count": 3
  }
}
```

**재검증 정책**: `last_verified` 90일 초과 시 재검증 큐로 이동. `verification_count >= 3`이면 `confidence: 1.0` 고정. 합병/폐업 감지 시 수동 삭제 후 재추론.

### 7.3 초기 시드 (Phase 0 수작업, 3개 섹터 기준)

**반도체**:
- TSMC → 삼성전자, SK하이닉스
- 마이크론 → SK하이닉스
- 키옥시아 → SK하이닉스 (지분 보유)
- Phison → 에이디테크놀로지
- Nanya → SK하이닉스, 삼성전자

**IT부품/PCB**:
- Yageo, Walsin, TDK → 삼성전기
- Unimicron, Kinsus → 대덕전자, 이수페타시스, 코리아써키트
- Topoint, Dynamic Holdings → 네오티스, 이수페타시스
- CWTC → 해성디에스
- Taimide → PI첨단소재
- EMC, ITEQ, TUC → 두산 전자BG
- Fulltech, Nittobo → SKC, 효성첨단소재
- Co-Tech → 일진머티리얼즈, KCFT

**2차전지**:
- CATL → LG에너지솔루션, 삼성SDI
- BYD → LG에너지솔루션
- Panasonic 2차전지 사업 → 삼성SDI
- Northvolt → SK온
- Albemarle, SQM → 포스코퓨처엠, 엘앤에프

---

## 8. 메시지 생성 파이프라인 상세

### 8.1 필터 (Claude Haiku)

**출력 JSON 스키마 (v1.1, category 추가)**:
```json
{
  "priority": "URGENT | HIGH | NORMAL | SKIP",
  "sector": "반도체|IT부품|2차전지|...",
  "category": "A | B | C | D | E",
  "reason": "왜 이 우선순위로 판정했는가",
  "should_dedup_check": true
}
```

**카테고리(A~E) 판정 규칙**:
- `B (국내 공시)`: `source == "DART"` + report_nm에 "자사주"/"증자"/"감자"/"합병"/"분할"/"실적발표" 포함
- `C (영문 기사)`: `source == "RSS"` + 원문 영문(`language=en`) 또는 해외 언론사 소스
- `D (수출통계)`: 제목에 "수출통계"/"수출금액"/"수출단가" 키워드 + TRASS/관세청 출처
- `A (해외 Peer 월매출)`: 해외 기업 IR 발표 + 매출/실적 키워드
- `E (속보)`: priority=URGENT + 짧은 본문(500자 미만) + 면책 생략 가능

필터 프롬프트가 우선순위 + 섹터 + 카테고리 동시 판정.

### 8.2 중복 감지 (v1.1 구조화)

**중복 키 생성**:
```python
import hashlib

def dedup_key(event):
    ticker = event.get("ticker") or event.get("company_id") or "NONE"
    event_type = event.get("event_type", "misc")  # 실적/자사주/M&A/가격/통계
    date = event["date"]  # YYYY-MM-DD
    title_norm = re.sub(r"\s+", "", event["title"])[:100]
    title_hash = hashlib.sha1(title_norm.encode()).hexdigest()[:8]
    return f"{ticker}:{event_type}:{date}:{title_hash}"
```

**seen_ids.jsonl 레코드**:
```json
{"id": "005930:자사주:2026-04-21:a3f8e9d1", "timestamp": "...", "source_url": "...", "role": "primary"}
{"id": "005930:자사주:2026-04-21:b7c2d4e6", "timestamp": "...", "source_url": "...", "role": "secondary"}
```

**중복 시 우선순위**:
```python
primary = max(candidates, key=lambda x: (len(x.text), x.source_trust_score))
# source_trust_score: DART=10, 주요 언론(CNBC/WSJ/Reuters)=7, 그 외=5
secondary_candidates = [c for c in candidates if c != primary]
# secondary는 primary 메시지의 related_sources에 링크만 첨부
```

### 8.3 Peer 매핑 (Claude Sonnet + 웹검색)

**Anthropic web_search tool 사용**:
```python
response = client.messages.create(
    model=PEER_MODEL,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[...]
)
```

**비용 추적**: 이슈 JSON의 `tokens_used.web_search_count` 필드에 누적.

**검색 실패 시**: `confidence=0`으로 저장, 승인 카드에 "Peer 미확정" 표시. 관리자가 수동 판정.

### 8.4 생성 (Claude Sonnet + 하이브리드 스타일 + 캐싱)

**프롬프트 구조**:
```
[SYSTEM - cache_control: ephemeral]
{R1~R8 규칙 전문}
{Template A~E 완벽 예시 각 1~2개}

[USER - 매번]
카테고리: {A~E}
섹터: {섹터}
원문:
{원문 전체}

Peer 매핑: {국내 관련 종목 리스트} (confidence: {점수})

위 원문을 Template {A~E} 형식으로 변환하세요.
R1~R8 규칙을 절대 위반하지 마세요.
```

**⚠️ 프롬프트 캐싱 현실 (v1.1 추가)**:
- Anthropic 프롬프트 캐시는 **기본 5분 TTL**. 1시간 TTL은 베타.
- 폴링 30분 간격이면 대부분 cache miss → 캐싱 효과 미미
- **대응책**: Phase 1에서 **실측 히트율 로깅** (`usage.cache_read_input_tokens` 비율) → 30% 미만이면 폴링 간격 축소 or Prompt 분할 검토
- **현실적 비용 재추정 (캐시 미스 시나리오)**: 생성 단계 $0.45/일 → **$1.20/일** 상승 가능. 월 $66~75로 늘어날 수 있음 (시나리오 D 기준 +$30~40)

---

## 9. 승인 플로우

### 9.1 승인 카드 (관리자 DM)

**렌더링 규칙**:
- 본문 + 메타 합쳐 **3,500자 초과 시 분할**: 본문 먼저, 메타(만료시각/peer/버튼) 별도 메시지
- `parse_mode="HTML"` 사용 (Markdown `*` 파싱 문제 회피)

**예시**:
```
🔴 <b>URGENT</b> | 반도체 | Template A
━━━━━━━━━━━━━━━━━━━━━
📰 <a href="https://dart.fss.or.kr/...">원본</a>

[NODE Research 반도체]

▶ 3월 대만 TSMC 매출액 415,191백만대만달러(+30.7% MoM, +45.2% YoY) 발표

- 1Q26 매출액 1,134,103.1백만대만달러(+8.4% QoQ, +35.1% YoY) 기록

* 1Q26 매출액 컨센서스: 1,121,604.2백만대만달러 (+1.1% 상회)

(자료: TSMC ir)

<i>* 본 내용은 국내외 언론·공시 자료를 인용·정리한 것으로, 투자 판단과 그 결과의 책임은 본인에게 있습니다.</i>

━━━━━━━━━━━━━━━━━━━━━
Peer: 삼성전자, SK하이닉스, 동진쎄미켐 (confidence: 0.92)
⏰ 만료: 15:08 (15분 — URGENT)

[✅ 발송]  [✏️ 수정]  [❌ 스킵]
```

### 9.2 인라인 버튼 동작

| 버튼 | 동작 |
|------|------|
| ✅ 발송 | 이브닝 보호 구간(16:20~16:50)이면 대기. 아니면 즉시 `@noderesearch` 채널로 본문 전송 → `sent/` 저장 |
| ✏️ 수정 | 아래 9.3 "수정 플로우" 참조 |
| ❌ 스킵 | `rejected/`에 저장 (학습용) |

### 9.3 수정 플로우 (v1.1 강화)

1. "✏️ 수정" 클릭 → 봇이 안내 메시지 전송:
   ```
   수정본을 이 메시지에 답장으로 보내주세요.
   제한 시간: 15분
   ```
   안내 메시지에 `force_reply=True, selective=True` 지정.
2. 관리자가 **안내 메시지에 답장**으로 수정본 전송.
3. 봇은 `reply_to_message.message_id == 안내_msg_id`로 매칭.
4. 수정본에 **R8 린트 자동 실행**. 위반 발견 시 경고 후 재확인 요구:
   ```
   ⚠️ R8 위반 의심: "급등" 발견.
   그대로 발송하려면 /confirm, 재수정하려면 답장 다시.
   ```
5. 수정 대기 15분 타임아웃 → 자동 취소, 원본 카드로 복귀 안내.
6. 수정본 확정 시 `edited/YYYY-MM-DD.jsonl`에 `{original, final, unified_diff}` 저장.

### 9.4 묶음 승인 (v1.1 신규)

**대기 3개 이상** 쌓이면 관리자 DM에 자동 추가 버튼:
```
📦 현재 대기 중인 NORMAL 3건
[일괄 승인] [일괄 스킵]
```
- 개별 버튼도 유지. 묶음 승인은 NORMAL만 허용 (URGENT/HIGH는 개별 확인 필수).

### 9.5 자동 승인 모드 (v1.1 옵션)

**조건 모두 만족 시 자동 발송** (관리자 DM에는 "발송됨" 알림만):
- `priority == "NORMAL"`
- `peer_confidence >= 0.9`
- `source == "DART"` (고신뢰 소스)
- 해당 기업의 과거 30일 승인율 ≥ 80%
- 린트 위반 없음

기본값 **OFF**. `.env`의 `ISSUE_BOT_AUTO_APPROVE=true`로 활성화.

### 9.6 섹터 Mute (v1.1 신규)

관리자 DM 명령:
- `/mute 반도체` → 24시간 반도체 섹터 폴링·승인카드 발송 중단
- `/mute 반도체 6h` → 6시간만
- `/unmute 반도체` → 즉시 해제
- `/mute_list` → 현재 mute된 섹터 목록
- 상태는 `history/issue_bot/mute.json`에 저장

### 9.7 KILL_SWITCH (v1.1 신규)

긴급 상황 (오작동/허위 발송 발생) 즉시 차단:
- `history/issue_bot/KILL_SWITCH` 파일 생성 → 모든 폴링·승인·발송 즉시 중단
- 관리자 DM 명령: `/stop_issue_bot`, `/start_issue_bot`
- `.env`의 `ISSUE_BOT_ENABLED=false` → 스케줄러 시작 시 잡 등록 생략 (재시작 필요)

---

## 10. 자체 린트 (v1.1 신규)

**R1~R8 자동 검증** (생성 직후):

```python
def lint_r1_r8(text, template):
    violations = []
    
    # R1 헤더 (Template B 예외)
    if template != "B" and not text.startswith("[NODE Research "):
        violations.append("R1: 헤더 누락")
    
    # R2 제목 이모지
    if re.search(r"[🔥📈💹🚀💥⚡]", text):
        violations.append("R2: 금지 이모지")
    
    # R3 bullet
    if re.search(r"^[•*·]", text, re.MULTILINE):
        violations.append("R3: 금지 bullet 기호")
    
    # R4 모호 수치
    if re.search(r"약\s*\d|대략\s*\d|거의\s*\d", text):
        violations.append("R4: 모호 수치")
    
    # R5 1인칭
    if re.search(r"당사는|저희는|우리는", text):
        violations.append("R5: 1인칭 사용")
    
    # R6 추정 인용
    if re.search(r"~한다는 얘기|~로 알려진", text):
        violations.append("R6: 추정 인용")
    
    # R8 금지 표현
    r8_patterns = [
        ("급등/폭등", r"급등|폭등|수직상승|급락|폭락"),
        ("추천", r"매수\s*추천|매도\s*권고|투자\s*의견"),
        ("호재/악재", r"호재|악재"),
        ("확정 표현", r"확실히|분명히|반드시|틀림없이"),
    ]
    for name, pat in r8_patterns:
        if re.search(pat, text):
            violations.append(f"R8: {name}")
    
    return violations
```

**위반 시 흐름**:
1. 1차 재생성 시도 (위반 항목을 프롬프트 추가 제약으로)
2. 재생성 후에도 위반 → 승인 카드에 ⚠️ 경고 표시 (관리자가 수정 or 스킵 결정)

---

## 11. 저장 구조 (이력 + 학습)

### 11.1 디렉토리

```
telegram_bot/
├── issue_bot/                    # 신규 모듈
│   ├── __init__.py
│   ├── main.py                   # 폴링 스케줄러
│   ├── collectors/
│   │   ├── dart_collector.py     # DART API + KIND HTML (신규)
│   │   └── rss_adapter.py        # 기존 news_collector 연동
│   ├── pipeline/
│   │   ├── filter.py             # Haiku 필터 (priority + category + sector)
│   │   ├── peer_mapper.py        # Sonnet + web_search
│   │   ├── generator.py          # Sonnet + 하이브리드 스타일
│   │   ├── linter.py             # R1~R8 자동 린트
│   │   └── dedup.py              # 구조화 중복 감지
│   ├── approval/
│   │   ├── bot.py                # 승인 카드 발송 + 콜백 처리
│   │   ├── poller.py             # getUpdates 롱폴링
│   │   ├── commands.py           # /mute, /stop, /start, /confirm
│   │   └── edit_handler.py       # force_reply 답장 매칭
│   └── utils/
│       └── telegram.py           # DM/채널 발송 래퍼
│
├── history/
│   ├── style_canon.md            # R1~R8 + Template 완벽 예시
│   ├── peer_map.json             # Peer 매핑 DB
│   ├── dart_category_map.json    # report_nm → Template/priority 매핑
│   └── issue_bot/
│       ├── pending/              # 승인 대기 (타임아웃 기반 자동 정리)
│       │   └── {dedup_key}.json
│       ├── sent/                 # 승인 + 발송
│       │   └── YYYY-MM-DD.jsonl
│       ├── rejected/             # 거절 (학습용)
│       │   └── YYYY-MM-DD.jsonl
│       ├── edited/               # 수정 후 발송
│       │   └── YYYY-MM-DD.jsonl
│       ├── seen_ids.jsonl        # 중복 방지 (구조화 키)
│       ├── mute.json             # 섹터 Mute 상태
│       ├── feedback.log          # 점검 로그
│       ├── cache_stats.jsonl     # 프롬프트 캐싱 히트율 (일별)
│       └── KILL_SWITCH           # 긴급 중단 파일 (있으면 차단)
```

### 11.2 이슈 JSON 스키마 (v1.1 확장)

```json
{
  "id": "dart_20260421_001",
  "dedup_key": "005930:자사주:2026-04-21:a3f8e9d1",
  "source": "DART|RSS|PRICE_API",
  "source_url": "https://...",
  "source_id": "DART_20260421000123",
  "fetched_at": "2026-04-21T14:23:00+09:00",
  "category": "A|B|C|D|E",
  "sector": "반도체",
  "priority": "URGENT|HIGH|NORMAL",
  "original_content": "원문 전체",
  "generated_content": "Claude 생성 최종 요약본",
  "lint_violations": [],
  "lint_retry_count": 0,
  "peer_map_used": ["삼성전자", "SK하이닉스"],
  "peer_confidence": 0.95,
  "related_sources": [],
  "status": "pending|approved|rejected|edited|sent|timeout|auto_approved",
  "decided_at": "2026-04-21T14:53:00+09:00",
  "edit_diff": {
    "original": "...",
    "final": "...",
    "unified_diff": "--- original\n+++ final\n..."
  },
  "sent_to_channel_at": null,
  "telegram_admin_msg_id": 12345,
  "telegram_channel_msg_id": 67890,
  "tokens_used": {
    "filter": 120,
    "peer": 340,
    "gen": 580,
    "web_search_count": 1,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0
  },
  "cost_krw": 45
}
```

---

## 12. 학습 루프 (v1.1 구체화)

### 12.1 월 1회 배치 분석

**입력**: 최근 30일 `rejected/` + `edited/`
**배치**: 30건씩 청크로 Sonnet 호출 (한 번에 전부 넣으면 토큰 초과)

**프롬프트**:
```
[배치 N/M] 지난 30일 이슈봇 승인 이력입니다.

{이벤트 30개 × (원본/생성본/edit_diff 포함)}

공통 패턴 분석:
1. SKIP 판정되어야 했는데 HIGH/NORMAL로 올라온 케이스
2. 생성 스타일이 수정된 경향
3. 추가해야 할 R1~R8 규칙

JSON 출력:
{
  "filter_improvements": ["..."],
  "style_improvements": ["..."],
  "new_rules_proposed": ["..."]
}
```

### 12.2 결과 반영 프로세스

- 자동 반영 ❌
- `history/style_canon_candidates.md` 생성 → 관리자 수동 검토 → 필요 시 `style_canon.md`에 merge
- 관리자 검토 UI: 별도 없음 (텍스트 diff로 충분)

### 12.3 KPI 추적

| 지표 | 측정 | 목표 |
|------|------|------|
| `approved / total` | 월별 | ≥ 60% |
| `rejected / total` | 월별 | < 25% |
| `edited / approved` | 월별 | < 30% |
| `timeout / total` | 월별 | < 10% |
| `lint_violation / total` | 일별 | < 5% |
| `cache_hit_rate` | 일별 | 측정만 (목표 없음, 0% 가능) |

`history/issue_bot/kpi_YYYY-MM.json`에 월말 자동 계산.

---

## 13. 비용 모델

### 13.1 시나리오 D (기본) — 낙관적 vs 보수적 계산

| 단계 | 모델 | 낙관적 (캐싱 성공) | 보수적 (캐시 미스) |
|------|------|--------------------|---------------------|
| 필터 | Haiku 4.5 | $0.30/일 | $0.30/일 |
| 생성 | Sonnet + 캐싱 | $0.45/일 | $1.20/일 |
| Peer | Sonnet + 웹검색 | $0.15 + 웹검색 $0.10 | $0.15 + 웹검색 $0.10 |
| **합계/일** | | **$1.00** | **$1.75** |
| **월** | | **~$30** | **~$53** |

**전제**:
- 하루 필터 대상 200건, 생성 대상 25건, Peer 검증 12건
- 웹검색 $10/1000회 = $0.01/회
- 보수적 시나리오에서 생성 단계는 캐싱 효과 없이 매 호출 50k tokens input

### 13.2 전 모델 비교

| 시나리오 | 일 비용 | 월 비용 | 비고 |
|----------|---------|---------|------|
| A. 전부 Opus | $10.66 | ~$320 | 최고 품질, 과투자 |
| B. 전부 Sonnet (캐싱 X) | $2.14 | ~$64 | 무난 |
| C. 전부 Haiku | $0.71 | ~$22 | 품질 리스크 |
| **D. 최적 조합 (낙관적)** ⭐ | $1.00 | ~$30 | **권장** |
| **D. 최적 조합 (보수적)** | $1.75 | ~$53 | 캐시 미스 전제 |
| E. 초저비용 Haiku + 캐싱 | $0.57 | ~$17 | 검증 필요 |

**실제 월 비용 예상 범위: $30~$55.** 캐싱 효과에 따라 가변.

### 13.3 환경변수 (모델 교체 가능)

```bash
# .env
ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-6
ISSUE_BOT_PEER_MODEL=claude-sonnet-4-6
ISSUE_BOT_ENABLE_CACHING=true
```

**기존 브리핑 봇(`COMMENTARY_MODEL=claude-sonnet-4-20250514`)과 별도 제어**. 이슈봇만 모델 버전 올려도 됨.

### 13.4 거절 시 낭비 비용

- 승인 카드 생성까지 이미 전체 파이프라인 실행됨
- 건당 낭비: ~$0.07 (Sonnet 생성 + Peer)
- 월 거절 50건 가정 시 $3.5 (수용 가능)
- **SKIP 판정되면 생성 단계 스킵** (이미 설계 반영)

---

## 14. 스타일 저장 (하이브리드 + 완벽 예시)

### 14.1 `history/style_canon.md` 구조

```markdown
# NODE Research 이슈 봇 스타일 경전

## 하드 규칙
(R1~R8 전문)

## 금지 표현 리스트
(R8 상세 정규식 포함)

## 카테고리별 완벽 예시

### Template A — 해외 Peer 월매출
[규칙 요약]
완벽 예시 1:
...
완벽 예시 2:
...

### Template B — 국내 공시
[R1 예외: 헤더 생략]
완벽 예시 1:
...

### Template C, D, E
(동일 구조)
```

### 14.2 프롬프트 주입

- `style_canon.md` 전체를 Claude system prompt에 삽입
- `cache_control: ephemeral` 적용 → 캐시 히트 시 1/10 비용
- **캐시 히트율 실측 로깅** (`cache_stats.jsonl`)

---

## 15. 기존 브리핑과의 충돌 방지

### 15.1 시간 보호 구간 (v1.1 확장)

- **모닝 보호**: **06:50~07:10** 이슈봇 폴링·발송 전면 중단
- **이브닝 보호**: **16:20~16:50** 이슈봇 폴링·발송 전면 중단

### 15.2 APScheduler 통합

```python
scheduler.add_job(
    issue_bot_poll,
    CronTrigger(minute="*/15", timezone=KST),  # 15분마다
    id="issue_bot_poll",
    name="이슈봇 폴링",
    misfire_grace_time=900,
)

# 함수 내부에서 시간 보호 구간 체크
def issue_bot_poll():
    now = datetime.datetime.now(KST)
    if is_protected_time(now):
        return
    if os.path.exists(KILL_SWITCH_PATH):
        return
    ...
```

### 15.3 Rate Limit 공유

- 봇 1개 + 채널 2곳(메인 채널 + 관리자 DM)
- 텔레그램 Bot API: 채널당 분당 20개, 초당 1개
- `send_message` 간 2초 대기 (기존 `sender.py` 패턴 재사용)

### 15.4 state 파일 분리

- 이슈봇은 `history/issue_bot/` 하위에서만 read/write
- 기존 `history/market_context.txt`, `history/analyst_raw.txt` 건드리지 않음

---

## 16. 환경변수 추가

```bash
# .env
TELEGRAM_ADMIN_CHAT_ID=           # 관리자 개인 user_id (Phase 0에 취득)

ISSUE_BOT_ENABLED=true            # 전체 on/off (false면 스케줄 등록 생략)
ISSUE_BOT_AUTO_APPROVE=false      # 자동 승인 모드 (기본 OFF)

ISSUE_BOT_FILTER_MODEL=claude-haiku-4-5-20251001
ISSUE_BOT_GENERATOR_MODEL=claude-sonnet-4-6
ISSUE_BOT_PEER_MODEL=claude-sonnet-4-6
ISSUE_BOT_ENABLE_CACHING=true

ISSUE_BOT_POLL_INTERVAL_MIN=15    # 폴링 주기 (분, 기본 15)
ISSUE_BOT_URGENT_TIMEOUT_MIN=15
ISSUE_BOT_HIGH_TIMEOUT_MIN=45
ISSUE_BOT_NORMAL_TIMEOUT_MIN=120
ISSUE_BOT_EDIT_TIMEOUT_MIN=15

DART_API_KEY=                     # Phase 0에 발급 필요 (현재 빈 값)
```

---

## 17. Phase 0/1/2 구현 순서 (v1.1 수정)

### Phase 0 — 인프라 (3~5일, 상향)

1. **DART API 키 발급** (opendart.fss.or.kr 회원가입 + 신청) — 영업일 1~2일
2. **DART API 실동작 검증**: `list.json` 응답, `report_nm` 분포, KIND HTML 본문 추출 테스트
3. **관리자 chat_id 취득**: `scripts/get_admin_chat_id.py` 작성 + 사용자 `/start` 후 실행
4. **`.env.example` 작성**: 새 환경변수 전체 포함
5. **초기 Peer 시드 작성**: Phase 1 3개 섹터 대상 메리츠 샘플에서 30개 매핑 추출
6. **`history/style_canon.md` 작성**: R1~R8 + Template A~E 완벽 예시 (각 1~2개씩)
7. **v1.1 스펙 최종 확정**

### Phase 1 — MVP (5~7일)

**범위: 반도체 + IT부품 + 2차전지 3개 섹터만**

1. `collectors/dart_collector.py` — DART API 폴링 + KIND HTML 본문 추출 + seen_ids.jsonl
2. `pipeline/filter.py` — Haiku 필터 (priority + category + sector)
3. `pipeline/dedup.py` — 구조화 중복 감지
4. `pipeline/generator.py` — Sonnet + 하이브리드 스타일 + 프롬프트 캐싱 + 히트율 로깅
5. `pipeline/linter.py` — R1~R8 자동 린트
6. `approval/bot.py` — 승인 카드 발송 (HTML 모드, 분할 대응)
7. `approval/poller.py` — getUpdates 롱폴링
8. `approval/commands.py` — `/mute`, `/stop`, `/start`, `/confirm`
9. `approval/edit_handler.py` — force_reply 답장 매칭 + 수정본 린트
10. `issue_bot/main.py` — 메인 루프 + 보호 구간 체크 + KILL_SWITCH
11. 기존 `telegram_bot/main.py`에 issue_bot 잡 통합
12. **End-to-end 테스트**: DART 공시 → 필터 → 생성 → 승인 → 채널 발송

### Phase 1.5 — Peer 매핑 고도화 + 2주 운영 (2주)

- Phase 1 실제 운영 + 승인율/거절율 추적
- 승인율 60% 이상 유지되면 Phase 2 진입

### Phase 2 — 섹터 확장 + Peer 자동 추론 (2~3주)

1. `pipeline/peer_mapper.py` — Sonnet + web_search tool
2. Phase 1.5 섹터 (디스플레이, 스마트폰, 자동차, 바이오/제약) 오픈
3. 나머지 26개 섹터 점진 추가
4. 학습 루프 첫 구현

### Phase 3 — 운영 고도화 (추후)

1. 기존 RSS 16개 연동 (`rss_adapter.py`)
2. 기업 IR/리서치 기관 크롤링 확장
3. 월 자동 학습 루프 운영
4. KPI 대시보드 (Google Sheets 동기화 or 간이 웹)

---

## 18. TODO / 확인 필요 체크리스트 (Phase 0 블로커)

- [ ] DART API 키 발급 (opendart.fss.or.kr)
- [ ] DART API 실응답 구조 조사 (`list.json` + `report_nm` 샘플 100건)
- [ ] KIND HTML 본문 추출 안정성 테스트
- [ ] `TELEGRAM_ADMIN_CHAT_ID` 취득
- [ ] Peer 시드 30개 (3개 섹터) 작성
- [ ] `style_canon.md` 작성 (Template A~E 각 1~2개)
- [ ] web_search tool API 실테스트
- [ ] 모델 식별자 실가용 확인 (`claude-sonnet-4-6` vs `claude-sonnet-4-5-20250929`)
- [ ] 프롬프트 캐싱 TTL 실측 (5분 vs 1시간 베타)

---

## 19. 의존성

```
# requirements.txt 추가 (예정)
anthropic>=0.40.0    # web_search tool + cache_control 지원
# (기존 재사용: requests, BeautifulSoup4, pytz, apscheduler)
```

DART API는 별도 라이브러리 불필요 (requests로 호출).

---

## 20. 관련 문서

- `CLAUDE.md` — 프로젝트 전체 개요
- `SYSTEM_SPEC.md` — 기존 브리핑 봇 명세
- `history/style_canon.md` — 스타일 경전 (Phase 0에 작성 예정)
- `history/peer_map.json` — Peer 매핑 DB (Phase 0에 초기 시드, 이후 자동 확장)
- `history/dart_category_map.json` — DART `report_nm` → Template/priority 매핑 (Phase 0 작성)

---

## 개정 이력

### v1.1 (2026-04-21) — 독립 검토 반영
- Critical 6건 수정: C1(모델 식별자 명시) / C2(DART 키 상태) / C3(필터 출력 category) / C4(DART API 현실) / C5(시간 보호 확대) / C6(수정 플로우 강화)
- Major 10건 반영: M1(타임아웃 차등) / M2(묶음 승인, 섹터 Mute, 자동 승인) / M3(Peer 재검증) / M4(dedup 구조화) / M5(diff 포맷) / M6(R1~R8 예외 명문화) / M7(캐싱 현실성) / M8(폴링 스케줄 세분화) / M9(KILL_SWITCH) / M10(학습 루프 구체화)
- Minor 반영: m1(RSS 16개) / m4(HTML 모드) / m10(기업명 통일)
- 제안 반영: d6(MVP 3개 섹터 축소 시작) / d5(발송 실패 처리)
- 자체 린트(R1~R8) 신규 추가

### v1.0 (2026-04-21) — 초안
- 33개 섹터 동시 오픈 가정 (v1.1에서 MVP 3개로 축소)
- 1시간 단일 타임아웃 (v1.1에서 차등)
