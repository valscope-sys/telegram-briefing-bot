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
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

# DART
DART_API_KEY = os.getenv("DART_API_KEY", "")

# === 이슈 봇 설정 ===
ISSUE_BOT_ENABLED = os.getenv("ISSUE_BOT_ENABLED", "true").lower() == "true"
ISSUE_BOT_AUTO_APPROVE = os.getenv("ISSUE_BOT_AUTO_APPROVE", "false").lower() == "true"
ISSUE_BOT_FILTER_MODEL = os.getenv("ISSUE_BOT_FILTER_MODEL", "claude-haiku-4-5-20251001")
ISSUE_BOT_FILTER_VERIFIER_MODEL = os.getenv("ISSUE_BOT_FILTER_VERIFIER_MODEL", "claude-sonnet-4-5")
ISSUE_BOT_FILTER_HYBRID = os.getenv("ISSUE_BOT_FILTER_HYBRID", "true").lower() == "true"
ISSUE_BOT_GENERATOR_MODEL = os.getenv("ISSUE_BOT_GENERATOR_MODEL", "claude-sonnet-4-5")
ISSUE_BOT_PEER_MODEL = os.getenv("ISSUE_BOT_PEER_MODEL", "claude-sonnet-4-5")
ISSUE_BOT_ENABLE_CACHING = os.getenv("ISSUE_BOT_ENABLE_CACHING", "true").lower() == "true"
ISSUE_BOT_POLL_INTERVAL_MIN = int(os.getenv("ISSUE_BOT_POLL_INTERVAL_MIN", "15"))
ISSUE_BOT_URGENT_TIMEOUT_MIN = int(os.getenv("ISSUE_BOT_URGENT_TIMEOUT_MIN", "15"))
ISSUE_BOT_HIGH_TIMEOUT_MIN = int(os.getenv("ISSUE_BOT_HIGH_TIMEOUT_MIN", "45"))
ISSUE_BOT_NORMAL_TIMEOUT_MIN = int(os.getenv("ISSUE_BOT_NORMAL_TIMEOUT_MIN", "120"))
ISSUE_BOT_EDIT_TIMEOUT_MIN = int(os.getenv("ISSUE_BOT_EDIT_TIMEOUT_MIN", "15"))

# 자동 타임아웃 스킵 활성 여부 (기본 OFF — 자는 동안 중요 이슈 유실 방지)
# True로 켜면 priority별 timeout_min 초과 시 자동 rejected 처리
ISSUE_BOT_AUTO_TIMEOUT = os.getenv("ISSUE_BOT_AUTO_TIMEOUT", "false").lower() == "true"

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Finnhub
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# Kiwoom (52주 신고가 전용)
KIWOOM_APP_KEY = os.getenv("KIWOOM_APP_KEY", "")
KIWOOM_APP_SECRET = os.getenv("KIWOOM_APP_SECRET", "")

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

# 미국 주요 종목 (모닝 시황 프롬프트에 사용, 시장 상황에 따라 수시 업데이트)
US_MAJOR_STOCKS = {
    # 빅테크/반도체
    "NVDA": "엔비디아",
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
    "GOOGL": "구글",
    "AMZN": "아마존",
    "TSLA": "테슬라",
    "META": "메타",
    "AVGO": "브로드컴",
    "TSM": "TSMC",
    "AMD": "AMD",
    # 시장 주목 종목 (수시 교체 가능)
    "SNDK": "샌디스크",
    "INTC": "인텔",
    "ORCL": "오라클",
}

# === SEC EDGAR 8-K 추적 기업 (이슈봇 Phase 2) ===
# 빅테크 + 한국 반도체 밸류체인 직결 Peer
# CIK 10자리 zero-pad. ticker: [cik, company_name]
SEC_TRACKED_COMPANIES = {
    # M7 빅테크
    "NVDA":  ["0001045810", "NVIDIA"],
    "AAPL":  ["0000320193", "Apple"],
    "MSFT":  ["0000789019", "Microsoft"],
    "GOOGL": ["0001652044", "Alphabet"],
    "AMZN":  ["0001018724", "Amazon"],
    "TSLA":  ["0001318605", "Tesla"],
    "META":  ["0001326801", "Meta"],
    # 반도체 밸류체인 Peer (삼성·하이닉스 관련)
    "TSM":   ["0001046179", "TSMC"],
    "AVGO":  ["0001730168", "Broadcom"],
    "AMD":   ["0000002488", "AMD"],
    "MU":    ["0000723125", "Micron"],
    "INTC":  ["0000050863", "Intel"],
    "ARM":   ["0001973239", "Arm Holdings"],
    "ASML":  ["0000937966", "ASML"],
    # 기타 빅테크 관련
    "NFLX":  ["0001065280", "Netflix"],
    "ORCL":  ["0001341439", "Oracle"],
}

# SEC API User-Agent (SEC 규정 — 이메일 포함 필수)
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "NODE Research Bot valscope@noderesearch.co.kr",
)

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
