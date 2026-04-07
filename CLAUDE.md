# NODE Research 텔레그램 브리핑 봇

## 프로젝트 개요
KIS Open API + Claude API + yfinance를 활용한 텔레그램 자동 시황 브리핑 봇.
하루 6개 메시지 발송 (장전 3개, 장후 3개).

## 현재 상태: 시황 품질 고도화 단계 (2026-04-07)

### 완료된 것
- [x] KIS API 스킬 8개 (~/.claude/commands/kis-*.md)
- [x] 프로젝트 구조 + 모든 모듈 코드 완성
- [x] 글로벌 데이터: S&P500/NASDAQ/DOW + VIX + USD/KRW + DXY + 금리 + WTI/금/구리
- [x] 국내 데이터: KOSPI/KOSDAQ + 수급 + 섹터ETF + 52주 + 거래대금/상승률 30종목
- [x] 미장 섹터 ETF 11개 + 주요 종목 10개 + KORU/EWY 야간 프록시
- [x] 뉴스: RSS 18개 소스 → Claude 필터링 → 섹터 이모지 + 상세 요약
- [x] 시황: 키움증권 스타일 프롬프트 + Gemini 크로스체크 반영
- [x] 장중 흐름 (시가→고가→저가→종가)
- [x] 외국인 N일 연속 수급 트렌드
- [x] 외국인 지분율 (삼성전자/SK하이닉스)
- [x] FnGuide 컨센서스 + 밸류에이션(12M PER) 크롤링
- [x] FnGuide 실적 캘린더 (잠정실적/실적발표)
- [x] 이전 브리핑 기억 (briefing_memory)
- [x] KIS API rate limit 대응 (초당 3건, 0.35초 간격)
- [x] GitHub push 완료 (valscope-sys/telegram-briefing-bot)
- [x] 텔레그램 발송 테스트 완료

### 남은 작업
1. **GitHub Actions 배포** — PC 안 켜놔도 자동 발송
2. **실제 장중 16:00 라이브 테스트** — 진짜 종가 기준 출력 확인
3. **DART API 키** — 실적 공시 자동 수집 (없어도 FnGuide로 동작)
4. **Gemini API 자동 크로스체크** (선택) — 월 $2.5 추가
5. **코스피 선행 PER** — FnGuide에서 시장 전체 PER 크롤링 (개별종목은 완료)

### 시황 프롬프트 핵심 원칙 (Gemini 피드백 반영)
1. 결론부터 — 첫 문장에 방향
2. 인과관계 체인 — A→B→C 구체적 경로
3. House View 명확 — "위인지 아래인지"가 아니라 방향을 찍어라
4. One Voice — 선택지 3개가 아니라 액션 1개
5. News Sell 구분 — 개인 매도를 과잉 해석하지 마라
6. 환율-외국인 연결 — 환차손 임계점 구체적으로
7. 도망 표현 금지 — "~보입니다" "~필요합니다" 금지

### 비용
- Anthropic API: 월 ~$5.5 (하루 4회 호출)
- KIS API: 무료
- yfinance: 무료
- 텔레그램: 무료

### 실행 방법
```bash
cd "텔레그램 시황 브리핑"
pip install -r telegram_bot/requirements.txt
python -m telegram_bot.main test      # 데이터 수집 테스트
python -m telegram_bot.main morning   # 모닝 브리핑 수동 실행
python -m telegram_bot.main evening   # 이브닝 브리핑 수동 실행
python -m telegram_bot.main           # 스케줄러 모드
```
