"""환경변수 및 설정 관리"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

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

# VIX는 차트 API에서 미지원 → 해외주식 현재가 API로 별도 조회
VIX_CODE = {"exchange": "NAS", "symbol": "VIXY"}  # VIX ETF 대안

# 환율 코드 (KIS 차트 API용)
FX_CODES = {
    "USD/KRW": "FX@KRW",
}

# DXY는 차트 API에서 미지원 → 해외선물로 대체 가능
# 원자재도 차트 API 'S' 구분에서 코드 미확인 → 해외선물 API 사용

# 해외선물로 조회할 원자재/DXY 코드 (해외선물종목현재가 API)
OVERSEAS_FUTURES_CODES = {
    "WTI": "CLK25",   # WTI 원유 2025년 5월물 (근월물 변경 필요)
    "금": "GCM25",     # 금 2025년 6월물
    "구리": "HGK25",   # 구리 2025년 5월물
}

# 국채 금리 코드 (금리종합 API output1에서 조회)
BOND_CODES = {
    "미국 2Y": "Y0203",   # 미국 1년T-BILL (2Y 직접 미제공)
    "미국 10Y": "Y0202",  # 미국 10년T-NOTE
    "미국 30Y": "Y0201",  # 미국 30년T-BOND
}
