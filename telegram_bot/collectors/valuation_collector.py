"""밸류에이션 데이터 수집 (선행 PER, PBR 등)"""
import requests
from bs4 import BeautifulSoup
import re


def fetch_stock_valuation(stock_code):
    """
    FnGuide에서 개별 종목 밸류에이션 조회
    - 반환: {"PER": 29.42, "12M_PER": 6.53, "업종PER": 24.01, "PBR": 3.02}
    """
    gicode = f"A{stock_code}"
    url = "https://comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp"
    params = {"pGB": "1", "gicode": gicode, "cID": "AA", "MenuYn": "Y", "ReportGB": "", "NewMenuID": "108", "stkGb": "701"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "lxml")
        text = soup.get_text()

        result = {}
        # 정규식으로 PER/PBR 값 추출
        # "PER\n\t\t29.42" 패턴
        per_match = re.search(r'PER\s*\n[\s]*(\d+\.?\d*)', text)
        if per_match:
            result["PER"] = float(per_match.group(1))

        per12m_match = re.search(r'12M PER[^\d]*?(\d+\.?\d*)', text)
        if per12m_match:
            result["12M_PER"] = float(per12m_match.group(1))

        sector_per_match = re.search(r'업종 PER[^\d]*?(\d+\.?\d*)', text)
        if sector_per_match:
            result["업종PER"] = float(sector_per_match.group(1))

        pbr_match = re.search(r'PBR[^\d]*?(\d+\.?\d*)', text)
        if pbr_match:
            result["PBR"] = float(pbr_match.group(1))

        return result if result else None
    except Exception:
        return None


def fetch_market_valuation():
    """
    주요 종목 밸류에이션 + 코스피 수준 판단용 데이터
    """
    import time
    results = {}
    targets = [
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
    ]
    for name, code in targets:
        val = fetch_stock_valuation(code)
        if val:
            results[name] = val
        time.sleep(0.3)
    return results


def format_valuation_for_prompt(val_data):
    """밸류에이션 데이터를 프롬프트용 텍스트로 변환"""
    if not val_data:
        return ""

    lines = ["=== 밸류에이션 ==="]
    for name, data in val_data.items():
        per = data.get("PER", 0)
        per12m = data.get("12M_PER", 0)
        sector_per = data.get("업종PER", 0)
        pbr = data.get("PBR", 0)
        lines.append(f"{name}: PER {per}배 / 12M선행PER {per12m}배 / 업종PER {sector_per}배 / PBR {pbr}배")

    lines.append("\n참고: 코스피 역사상 선행PER 8배 이하는 08년 금융위기(6.3배), 11년 유럽재정위기(7.6배), 18년 미중무역분쟁(7.7배) 단 3차례. 장기평균 약 10배.")

    return "\n".join(lines)
