"""고정 경제/증시 일정 (수동 관리, 연 1~2회 업데이트)"""
import datetime


FIXED_EVENTS_2026 = [
    # ========== 통화정책 ==========
    # FOMC — 공식 일정: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    # 2026 회의: 1/27-28, 3/17-18, 4/28-29, 6/16-17, 7/28-29, 9/15-16, 10/27-28, 12/8-9
    # 표기 원칙(2026-07-21 교정): KST 발표일 기준 — 2일차 회의 미국 동부 14:00 발표
    #   → KST 다음날 새벽. 미국 DST 기간(3~11월) 03:00, 그 외 04:00
    #   ※ 7/21 이전 항목은 과거 기록 보존을 위해 기존 표기 유지
    {"date": "2026-01-28", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-03-18", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-05-06", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-06-17", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},
    {"date": "2026-07-30", "time": "03:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},  # 7/28-29 회의 (EDT)
    {"date": "2026-09-17", "time": "03:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},  # 9/15-16 회의 (EDT)
    {"date": "2026-10-29", "time": "03:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},  # 10/27-28 회의 (EDT, DST 종료 11/1 이전)
    {"date": "2026-12-10", "time": "04:00", "category": "통화정책", "title": "FOMC 금리 결정", "country": "🇺🇸"},  # 12/8-9 회의 (EST)
    # 한국은행 금통위 — 공식 일정(2026년 정기회의 개최 예정):
    # https://www.bok.or.kr/portal/bbs/B0000502/view.do?menuNo=201265&nttId=10094300
    # 통화정책방향 결정회의: 1/15, 2/26, 4/16, 5/28, 7/16, 8/27, 10/22, 11/26 (발표 당일 KST 오전)
    # 2026-07-21 교정: 10월 회의 10/15 → 10/22. 7/21 이전 항목은 과거 기록 보존
    {"date": "2026-01-16", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-02-27", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-04-16", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-05-28", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-07-16", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-08-27", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-10-22", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    {"date": "2026-11-26", "time": "10:00", "category": "통화정책", "title": "한국은행 금통위 금리 결정", "country": "🇰🇷"},
    # ECB — 공식 일정: https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
    # 하반기 결정일: 9/10, 10/29, 12/17 (기존 날짜 정확 — 날짜 수정 없음)
    # 2026-07-21 교정: 발표 14:15 중부유럽시간 → KST 여름(CEST) 21:15 / 겨울(CET) 22:15
    #   EU DST 종료(10/25) 이후 회의는 22:15. 7/21 이전 항목은 과거 기록 보존
    {"date": "2026-01-22", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},
    {"date": "2026-03-05", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},
    {"date": "2026-04-16", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},
    {"date": "2026-06-04", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},
    {"date": "2026-07-16", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},
    {"date": "2026-09-10", "time": "21:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},  # CEST
    {"date": "2026-10-29", "time": "22:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},  # CET (DST 종료 후)
    {"date": "2026-12-17", "time": "22:15", "category": "통화정책", "title": "ECB 금리 결정", "country": "🇪🇺"},  # CET
    # BOJ — 공식 일정: https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
    # 2026 하반기 회의: 7/30-31, 9/17-18, 10/29-30, 12/17-18
    # 2026-07-21 교정: 결정 발표는 2일차 회의일 정오 무렵(JST=KST 동일) — 2일차 날짜로 통일
    #   7/21 이전 항목은 과거 기록 보존
    {"date": "2026-01-24", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},
    {"date": "2026-03-19", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},
    {"date": "2026-05-01", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},
    {"date": "2026-06-18", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},
    {"date": "2026-07-31", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},  # 7/30-31 회의
    {"date": "2026-09-18", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},  # 9/17-18 회의
    {"date": "2026-10-30", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},  # 10/29-30 회의
    {"date": "2026-12-18", "time": "", "category": "통화정책", "title": "BOJ 금리 결정", "country": "🇯🇵"},  # 12/17-18 회의

    # ========== 경제지표 ==========
    # 미국 CPI (매월 둘째주 화/수)
    {"date": "2026-01-14", "time": "22:30", "category": "경제지표", "title": "미국 CPI (12월)", "country": "🇺🇸"},
    {"date": "2026-02-11", "time": "22:30", "category": "경제지표", "title": "미국 CPI (1월)", "country": "🇺🇸"},
    {"date": "2026-03-11", "time": "21:30", "category": "경제지표", "title": "미국 CPI (2월)", "country": "🇺🇸"},
    {"date": "2026-04-14", "time": "21:30", "category": "경제지표", "title": "미국 CPI (3월)", "country": "🇺🇸"},
    {"date": "2026-05-13", "time": "21:30", "category": "경제지표", "title": "미국 CPI (4월)", "country": "🇺🇸"},
    {"date": "2026-06-10", "time": "21:30", "category": "경제지표", "title": "미국 CPI (5월)", "country": "🇺🇸"},
    {"date": "2026-07-15", "time": "21:30", "category": "경제지표", "title": "미국 CPI (6월)", "country": "🇺🇸"},
    {"date": "2026-08-12", "time": "21:30", "category": "경제지표", "title": "미국 CPI (7월)", "country": "🇺🇸"},
    {"date": "2026-09-15", "time": "21:30", "category": "경제지표", "title": "미국 CPI (8월)", "country": "🇺🇸"},
    {"date": "2026-10-13", "time": "21:30", "category": "경제지표", "title": "미국 CPI (9월)", "country": "🇺🇸"},
    {"date": "2026-11-12", "time": "22:30", "category": "경제지표", "title": "미국 CPI (10월)", "country": "🇺🇸"},
    {"date": "2026-12-10", "time": "22:30", "category": "경제지표", "title": "미국 CPI (11월)", "country": "🇺🇸"},
    # 미국 고용 (매월 첫째 금요일)
    {"date": "2026-01-09", "time": "22:30", "category": "경제지표", "title": "미국 비농업 고용 (12월)", "country": "🇺🇸"},
    {"date": "2026-02-06", "time": "22:30", "category": "경제지표", "title": "미국 비농업 고용 (1월)", "country": "🇺🇸"},
    {"date": "2026-03-06", "time": "22:30", "category": "경제지표", "title": "미국 비농업 고용 (2월)", "country": "🇺🇸"},
    {"date": "2026-04-10", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (3월)", "country": "🇺🇸"},
    {"date": "2026-05-08", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (4월)", "country": "🇺🇸"},
    {"date": "2026-06-05", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (5월)", "country": "🇺🇸"},
    {"date": "2026-07-02", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (6월)", "country": "🇺🇸"},
    {"date": "2026-08-07", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (7월)", "country": "🇺🇸"},
    {"date": "2026-09-04", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (8월)", "country": "🇺🇸"},
    {"date": "2026-10-02", "time": "21:30", "category": "경제지표", "title": "미국 비농업 고용 (9월)", "country": "🇺🇸"},
    {"date": "2026-11-06", "time": "22:30", "category": "경제지표", "title": "미국 비농업 고용 (10월)", "country": "🇺🇸"},
    {"date": "2026-12-04", "time": "22:30", "category": "경제지표", "title": "미국 비농업 고용 (11월)", "country": "🇺🇸"},
    # 한국 수출입 (매월 1일)
    {"date": "2026-01-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (12월)", "country": "🇰🇷"},
    {"date": "2026-02-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (1월)", "country": "🇰🇷"},
    {"date": "2026-03-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (2월)", "country": "🇰🇷"},
    {"date": "2026-04-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (3월)", "country": "🇰🇷"},
    {"date": "2026-05-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (4월)", "country": "🇰🇷"},
    {"date": "2026-06-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (5월)", "country": "🇰🇷"},
    {"date": "2026-07-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (6월)", "country": "🇰🇷"},
    {"date": "2026-08-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (7월)", "country": "🇰🇷"},
    {"date": "2026-09-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (8월)", "country": "🇰🇷"},
    {"date": "2026-10-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (9월)", "country": "🇰🇷"},
    {"date": "2026-11-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (10월)", "country": "🇰🇷"},
    {"date": "2026-12-01", "time": "09:00", "category": "경제지표", "title": "한국 수출입 통계 (11월)", "country": "🇰🇷"},
    # 중국 PMI (매월 말일)
    {"date": "2026-01-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (1월)", "country": "🇨🇳"},
    {"date": "2026-02-28", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (2월)", "country": "🇨🇳"},
    {"date": "2026-03-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (3월)", "country": "🇨🇳"},
    {"date": "2026-04-30", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (4월)", "country": "🇨🇳"},
    {"date": "2026-05-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (5월)", "country": "🇨🇳"},
    {"date": "2026-06-30", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (6월)", "country": "🇨🇳"},
    {"date": "2026-07-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (7월)", "country": "🇨🇳"},
    {"date": "2026-08-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (8월)", "country": "🇨🇳"},
    {"date": "2026-09-30", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (9월)", "country": "🇨🇳"},
    {"date": "2026-10-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (10월)", "country": "🇨🇳"},
    {"date": "2026-11-30", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (11월)", "country": "🇨🇳"},
    {"date": "2026-12-31", "time": "10:30", "category": "경제지표", "title": "중국 제조업 PMI (12월)", "country": "🇨🇳"},
    # 현대차/기아 월간 판매량 (매월 1일)
    {"date": "2026-01-02", "time": "", "category": "자동차/배터리", "title": "현대차/기아 12월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-02-02", "time": "", "category": "자동차/배터리", "title": "현대차/기아 1월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-03-02", "time": "", "category": "자동차/배터리", "title": "현대차/기아 2월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-04-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 3월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-05-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 4월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-06-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 5월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-07-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 6월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-08-03", "time": "", "category": "자동차/배터리", "title": "현대차/기아 7월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-09-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 8월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-10-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 9월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-11-02", "time": "", "category": "자동차/배터리", "title": "현대차/기아 10월 판매량 발표", "country": "🇰🇷"},
    {"date": "2026-12-01", "time": "", "category": "자동차/배터리", "title": "현대차/기아 11월 판매량 발표", "country": "🇰🇷"},

    # ========== 지수 리밸런싱 ==========
    # MSCI 리밸런싱 (2/5/8/11월 마지막 거래일 종가 기준)
    {"date": "2026-02-27", "time": "", "category": "만기일", "title": "MSCI 리밸런싱 (2월)", "summary": "MSCI 분기 리밸런싱. 편입/제외 종목 대규모 외국인 수급 발생"},
    {"date": "2026-05-29", "time": "", "category": "만기일", "title": "MSCI 리밸런싱 (5월)", "summary": "MSCI 반기 리밸런싱. 대규모 편출입 가능"},
    # 2026-07-21 교정: 8월 마지막 거래일 = 8/31(월), 11월 마지막 거래일 = 11/30(월)
    {"date": "2026-08-31", "time": "", "category": "만기일", "title": "MSCI 리밸런싱 (8월)", "summary": "MSCI 분기 리밸런싱"},
    {"date": "2026-11-30", "time": "", "category": "만기일", "title": "MSCI 리밸런싱 (11월)", "summary": "MSCI 반기 리밸런싱. 대규모 편출입 가능"},
    # KOSPI200 정기변경 (6/12월 둘째주 목요일)
    {"date": "2026-06-11", "time": "", "category": "만기일", "title": "KOSPI200 정기변경", "summary": "KOSPI200 종목 편입/제외 반영일. 패시브 자금 리밸런싱"},
    {"date": "2026-12-10", "time": "", "category": "만기일", "title": "KOSPI200 정기변경", "summary": "KOSPI200 종목 편입/제외 반영일"},
    # FTSE 리밸런싱 (3/6/9/12월 셋째주 금요일)
    {"date": "2026-03-20", "time": "", "category": "만기일", "title": "FTSE 리밸런싱 (3월)", "summary": "FTSE 분기 리밸런싱. 외국인 수급 변동"},
    {"date": "2026-06-19", "time": "", "category": "만기일", "title": "FTSE 리밸런싱 (6월)", "summary": "FTSE 반기 리밸런싱"},
    {"date": "2026-09-18", "time": "", "category": "만기일", "title": "FTSE 리밸런싱 (9월)", "summary": "FTSE 분기 리밸런싱"},
    {"date": "2026-12-18", "time": "", "category": "만기일", "title": "FTSE 리밸런싱 (12월)", "summary": "FTSE 반기 리밸런싱"},

    # ========== 한국 휴장일 ==========
    {"date": "2026-01-01", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (신정)"},
    {"date": "2026-01-28", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (설날 연휴)"},
    {"date": "2026-01-29", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (설날)"},
    {"date": "2026-01-30", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (설날 연휴)"},
    {"date": "2026-03-01", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (삼일절)"},
    {"date": "2026-05-05", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (어린이날)"},
    {"date": "2026-05-24", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (석가탄신일)"},
    {"date": "2026-06-06", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (현충일)"},
    {"date": "2026-08-15", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (광복절)"},
    {"date": "2026-09-24", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (추석 연휴)"},
    {"date": "2026-09-25", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (추석)"},
    {"date": "2026-09-26", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (추석 연휴)"},
    {"date": "2026-10-03", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (개천절)"},
    {"date": "2026-10-09", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (한글날)"},
    {"date": "2026-12-25", "time": "", "category": "만기일", "title": "🇰🇷 한국 휴장 (크리스마스)"},
    # 미국 휴장일
    {"date": "2026-01-01", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (New Year)"},
    {"date": "2026-01-19", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (MLK Day)"},
    {"date": "2026-02-16", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Presidents Day)"},
    {"date": "2026-04-03", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Good Friday)"},
    {"date": "2026-05-25", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Memorial Day)"},
    {"date": "2026-06-19", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Juneteenth)"},
    {"date": "2026-07-03", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Independence Day)"},
    {"date": "2026-09-07", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Labor Day)"},
    {"date": "2026-11-26", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Thanksgiving)"},
    {"date": "2026-12-25", "time": "", "category": "만기일", "title": "🇺🇸 미국 휴장 (Christmas)"},

    # ========== 반도체 가격 발표 (TrendForce/DRAMeXchange) ==========
    # 매월 초 DRAMeXchange 계약가 발표 (대략 1~5일)
    {"date": "2026-01-05", "time": "", "category": "반도체", "title": "DRAMeXchange 1월 메모리 계약가 발표", "summary": "DRAM/NAND 월간 계약가격. SK하이닉스/삼성전자 직접 영향"},
    {"date": "2026-02-05", "time": "", "category": "반도체", "title": "DRAMeXchange 2월 메모리 계약가 발표"},
    {"date": "2026-03-05", "time": "", "category": "반도체", "title": "DRAMeXchange 3월 메모리 계약가 발표"},
    {"date": "2026-04-03", "time": "", "category": "반도체", "title": "DRAMeXchange 4월 메모리 계약가 발표"},
    {"date": "2026-05-05", "time": "", "category": "반도체", "title": "DRAMeXchange 5월 메모리 계약가 발표"},
    {"date": "2026-06-04", "time": "", "category": "반도체", "title": "DRAMeXchange 6월 메모리 계약가 발표"},
    {"date": "2026-07-03", "time": "", "category": "반도체", "title": "DRAMeXchange 7월 메모리 계약가 발표"},
    {"date": "2026-08-05", "time": "", "category": "반도체", "title": "DRAMeXchange 8월 메모리 계약가 발표"},
    {"date": "2026-09-04", "time": "", "category": "반도체", "title": "DRAMeXchange 9월 메모리 계약가 발표"},
    {"date": "2026-10-05", "time": "", "category": "반도체", "title": "DRAMeXchange 10월 메모리 계약가 발표"},
    {"date": "2026-11-05", "time": "", "category": "반도체", "title": "DRAMeXchange 11월 메모리 계약가 발표"},
    {"date": "2026-12-04", "time": "", "category": "반도체", "title": "DRAMeXchange 12월 메모리 계약가 발표"},

    # ========== 배당 기준일 (대형주) ==========
    # 연말 배당 기준일 (12월 말)
    {"date": "2026-12-28", "time": "", "category": "기업이벤트", "title": "연말 배당 기준일 (대형주)", "summary": "삼성전자/SK하이닉스/POSCO 등 12월 결산 배당주 기준일. 배당락 전 매수세 유입"},
    {"date": "2026-12-29", "time": "", "category": "기업이벤트", "title": "연말 배당락일", "summary": "배당 기준일 다음 영업일. 배당금만큼 주가 하락 가능"},
    # 중간배당 (6월 말)
    {"date": "2026-06-29", "time": "", "category": "기업이벤트", "title": "중간배당 기준일 (대형주)", "summary": "삼성전자 등 중간배당 기준일"},
    {"date": "2026-06-30", "time": "", "category": "기업이벤트", "title": "중간배당락일"},
]


def get_fixed_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """고정 일정에서 날짜 범위 내 이벤트 반환"""
    results = []
    for ev in FIXED_EVENTS_2026:
        ev_date = datetime.date.fromisoformat(ev["date"])
        if from_date <= ev_date <= to_date:
            entry = {
                "date": ev["date"],
                "time": ev.get("time", ""),
                "category": ev["category"],
                "title": ev["title"],
                "source": "fixed",
                "auto": False,
                "country": ev.get("country", ""),
            }
            if ev.get("summary"):
                entry["summary"] = ev["summary"]
            results.append(entry)
    return results
