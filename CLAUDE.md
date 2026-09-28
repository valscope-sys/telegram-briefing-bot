# NODE Research 증시 캘린더

한국 투자자용 증시 일정 캘린더. 매일 자동 수집 → GitHub Pages 웹 캘린더로 공개.

- 웹: https://valscope-sys.github.io/telegram-briefing-bot/
- 리포: valscope-sys/telegram-briefing-bot (이름은 옛 브리핑봇 시절 그대로 — 바꾸면 웹 주소가 바뀜)
- 시황 브리핑봇·이슈봇은 2026-09-28 폐기·삭제 (필요 시 git 기록에서 복원 가능)

## 구조
```
cal_data/
  update.py              # 수집 오케스트레이터 (병합·중복제거·스냅샷 교체)
  llm_client.py          # Claude 호출 — API 크레딧 없으면 Claude Code CLI(구독)로 자동 전환
  requirements.txt
  krx_listing.json       # KIND IR 회사명 약칭 매핑
  calendar.json          # 수집 결과 (docs/calendar.json으로 복사됨)
  collectors/            # 소스별 수집기 (아래 표)
docs/                    # GitHub Pages 웹 캘린더 (index.html, calendar.js, style.css, calendar.json)
.github/workflows/calendar.yml   # 매일 06:00 KST 자동 수집·커밋
.claude/launch.json      # 로컬 미리보기 (python -m http.server 8080 -d docs)
```

## 수집 소스
| 수집기 | 소스 | 내용 |
|---|---|---|
| us_earnings.py | Nasdaq(주, 키 불필요) → TradingView → Finnhub(원거리 보강) | 해외 실적. 워치리스트(finnhub.WATCHLIST, 한국 연관) + 시총 2,000억달러↑ 자동 |
| fnguide.py | wcomp.fnguide.com (신버전) | 국내 잠정실적(발표 후, 컨센 대비 괴리율)·신규상장 |
| kind_ir.py | KRX KIND IR 일정 | 국내 향후 실적발표(컨콜)·IR |
| tradingview_economic.py | TradingView 경제 캘린더 | 경제지표 (핵심 지표 화이트리스트, KST, 중요도 ★) |
| investing_economic.py | Investing.com | 경제지표 fallback (데이터센터 IP 429 차단 잦음) |
| fixed_events.py | 공식 일정 하드코딩 | FOMC·금통위·ECB·BOJ·옵션만기·MSCI·배당락 등 (2026·2027) |
| news_events.py / industry_events.py | 공식 일정 하드코딩 | 바이오 학회·테크 컨퍼런스·광통신·XR·배터리·조선·방산·원전 전시 |
| holidays_kr.py | holidays 라이브러리 | 한국 증시 휴장일 |
| ipo_listing.py | 38.co.kr | 공모청약·신규상장 |
| ai_news_scanner.py | RSS + Claude(haiku) | 돌발 일정(신제품 공개·학회·정책 시행일) |

## 원칙
- 하드코딩 일정은 **공식 출처로 확인된 날짜만**, 출처 URL을 주석으로 남긴다. 추정 날짜 금지
- 증시 영향이 미미한 일정은 넣지 않는다 (유증·무증·액면·합병·감자는 수집 중단)
- 스냅샷 소스(fixed·known·holidays·nasdaq·tv_earnings·finnhub·tradingview·kind)는 정상 수집된 구간의
  기존 항목을 신규분으로 교체 → 연기·취소 일정이 남지 않음. 수동(source=manual) 일정은 보존
- 수집 실패는 반드시 `[모듈] ERROR:` 로그로 드러나게 한다 (조용한 0건 금지 — 과거 FnGuide 폐쇄·Finnhub 절단이 수개월 무음 소실)
- 웹 기본 필터: IR(경영현황)만 숨김

## 실행
```bash
pip install -r cal_data/requirements.txt
python -m cal_data.update --full            # 오늘~180일 (매일 자동 실행과 동일)
python -m cal_data.update --month 202610    # 특정 월 재수집
python -m cal_data.update --full --skip-ai  # AI 스캐너 생략
```

## Claude 인증 (AI 스캐너만 사용)
- 로컬 PC: Claude Code 로그인만 되어 있으면 API 크레딧 없이 동작
- GitHub Actions: 시크릿 `CLAUDE_CODE_OAUTH_TOKEN`(`claude setup-token`으로 발급)이 있으면 CLI 설치 후 사용
- 토큰·크레딧 둘 다 없으면 AI 스캔만 건너뛰고 나머지는 정상 수집

## 알려진 공백
- 한은 금통위 2027 일정 미공표 (보통 10월 말 공표 → fixed_events.py에 추가)
- Nasdaq 실적은 약 2.5개월 앞까지만 게시 → 그 이후는 Finnhub 추정 일정
- 경제지표는 TradingView 게시 범위(약 1개월)까지만, 그 이후는 fixed 대표 지표만
