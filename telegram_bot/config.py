"""환경변수 및 설정 관리"""
import os
from dotenv import load_dotenv

# .env 파일 탐색: 패키지 상위 → 현재 디렉토리 → 절대경로
_env_candidates = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    os.path.join(os.getcwd(), ".env"),
]
for _p in _env_candidates:
    if os.path.exists(_p):
        load_dotenv(_p, override=True)
        break

# KIS API
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "").replace("-", "")
KIS_IS_PAPER = os.getenv("KIS_IS_PAPER", "false").lower() == "true"
KIS_BASE_URL = (
    "https://openapivts.koreainvestment.com:29443"
    if KIS_IS_PAPER
    else "https://openapi.koreainvestment.com:9443"
)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

# DART
DART_API_KEY = os.getenv("DART_API_KEY", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 섹터 ETF 코드
SECTOR_ETFS = {
    "반도체": "091160",
    "2차전지": "305720",
    "바이오": "244580",
    "방산": "457480",
    "에너지": "117460",
    "자동차": "091180",
    "금융": "091170",
    "건설": "117010",
    "철강": "117000",
    "게임": "214980",
}

# 해외지수 코드 (KIS 차트 API용 - 점(.) 없이 사용)
GLOBAL_INDICES = {
    "S&P 500": "SPX",
    "NASDAQ": "COMP",
    "DOW": ".DJI",
}

# VIX, DXY, 원자재는 yfinance로 조회 (KIS 미지원)

# 환율 코드 (KIS 차트 API용)
FX_CODES = {
    "USD/KRW": "FX@KRW",
}
# DXY는 yfinance "DX-Y.NYB" 사용 (global_market.py에서 처리)

# 원자재 yfinance 코드 (global_market.py에서 직접 사용)
# WTI: "CL=F", 금: "GC=F", 구리: "HG=F"

# 섹터별 대표 종목 (이브닝 브리핑에 함께 표시)
SECTOR_STOCKS = {
    "반도체": [("삼성전자", "005930"), ("SK하이닉스", "000660")],
    "2차전지": [("LG에너지솔루션", "373220"), ("에코프로비엠", "247540")],
    "바이오": [("삼성바이오", "207940"), ("셀트리온", "068270")],
    "방산": [("한화에어로", "012450"), ("LIG넥스원", "079550")],
    "에너지": [("두산에너빌리티", "034020"), ("한국전력", "015760")],
    "자동차": [("현대차", "005380"), ("기아", "000270")],
    "금융": [("KB금융", "105560"), ("신한지주", "055550")],
    "게임": [("크래프톤", "259960"), ("엔씨소프트", "036570")],
}
