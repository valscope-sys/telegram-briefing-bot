"""산업 이벤트 (학회·전시회·신제품 발표) — 한국 공급망 관련주가 반응하는 굵직한 일정

news_events.py 의 KNOWN_INDUSTRY_EVENTS_2026/2027 보완용 하드코딩 스냅샷 (2026-09-28 작성).
- 공식 사이트(또는 주최측 발표를 인용한 신뢰 매체)로 날짜가 확인된 일정만 수록. 추정 날짜 금지.
- news_events.py 에 이미 있는 일정(Apple 9/9 발표, SEMICON West/Japan/Korea/Taiwan 2027,
  OCP, GTC, CES, MWC, IFA 2026, KES, G-STAR 등)은 중복 수록하지 않음.
- 반환 스키마는 news_events.fetch_known_events 와 동일 (source "known", auto True).
- 날짜는 현지 개최일 기준. 다일 행사는 endDate 포함.

미공표(공표 시 추가, 그 전엔 넣지 말 것):
  Meta Connect 2027 · WWDC 2027 · Apple 2027 봄 이벤트 · 갤럭시 언팩(차기) · Amazon 디바이스 이벤트 ·
  Made by Google 2027 · K-Display 2027 · Hot Chips 2027 · 삼성 파운드리 포럼/SAFE 2027 ·
  TSMC 테크 심포지엄 2027 · 테슬라 2026 주총 · 더배터리쇼 북미 2027(비공식 10/5-7 설만 있음) ·
  인터배터리 유럽 2027 · iREX 2027(12월 초로만 공지) · AUSA 2027(출처별 상이) ·
  엔비디아/AMD/인텔 인베스터데이
"""
import datetime

# 한국 관련주 요약 문구 (테마별 공통)
_OPTICAL = "광통신·광트랜시버 관련주 (대한광통신, 오이솔루션, 쏠리드, 우리로 등)"
_XR = "XR·AI 글래스 부품 관련주 (LG이노텍, LG디스플레이, 라온텍 등)"
_DISPLAY = "디스플레이 패널·OLED 소재·장비주 (LG디스플레이, 덕산네오룩스, 선익시스템 등)"
_BATTERY = "2차전지 셀·소재주 (LG에너지솔루션, 삼성SDI, SK이노베이션, 에코프로비엠, 포스코퓨처엠 등)"
_ESS = "ESS·태양광 관련주 (LG에너지솔루션, 삼성SDI, 한화솔루션, HD현대에너지솔루션 등)"
_ROBOT = "로봇·휴머노이드 관련주 (레인보우로보틱스, 두산로보틱스, 로보티즈, 에스피지 등)"
_SEMI_EQUIP = "반도체 장비·소재주 (한미반도체, 원익IPS, 주성엔지니어링, 이오테크닉스 등)"
_SEMI_PAPER = "삼성전자·SK하이닉스 차세대 메모리·공정 논문 발표 — HBM·파운드리 기술 이슈"
_SHIP = "조선·조선기자재주 (HD한국조선해양, 한화오션, 삼성중공업, HD현대마린솔루션 등)"
_LNG = "LNG선·보냉재 관련주 (한화오션, 삼성중공업, HD한국조선해양, 한국카본, 동성화인텍 등)"
_DEFENSE = "K-방산주 (한화에어로스페이스, 현대로템, LIG넥스원, 한국항공우주 등)"
_NUCLEAR = "원전주 (두산에너빌리티, 한전기술, 한전KPS, 현대건설 등)"


INDUSTRY_EVENTS_2026 = [
    # ===== 광통신·포토닉스 =====
    # ECOC 2026 (말라가 FYCMA) — 학회 9/20-24, 전시 9/21-23
    #   https://www.ecocexhibition.com/future-dates/
    {"date": "2026-09-20", "endDate": "2026-09-24", "title": "ECOC 2026 (유럽광통신학회)", "category": "산업컨퍼런스",
     "link": "https://www.ecocexhibition.com/", "summary": f"스페인 말라가, 전시 9/21-23 · {_OPTICAL}"},
    # CIOE 2026 (선전 국제컨벤션센터) — https://www.sourcephotonics.com/events/cioe-2026/ (출전사 공지), https://www.cioe.cn/en/
    {"date": "2026-09-09", "endDate": "2026-09-11", "title": "CIOE 2026 (중국 선전 광전자전)", "category": "산업컨퍼런스",
     "link": "https://www.cioe.cn/en/", "summary": _OPTICAL},

    # ===== XR·AI 글래스·모바일 신제품 =====
    # Meta Connect 2026 (멘로파크 본사) — 키노트 9/23 16:00 PT (KST 9/24 08:00)
    #   https://www.meta.com/blog/connect-2026-save-the-date/
    {"date": "2026-09-23", "endDate": "2026-09-24", "title": "Meta Connect 2026 (AI 글래스·XR)", "category": "산업컨퍼런스",
     "link": "https://www.meta.com/connect/", "summary": f"키노트 KST 9/24 08:00 · {_XR}"},
    # Snapdragon Summit 2026 (마우이) — https://www.gsmarena.com/qualcomm_snapdragon_summit_2026_date-news-73500.php
    {"date": "2026-09-22", "endDate": "2026-09-24", "title": "퀄컴 스냅드래곤 서밋 2026", "category": "산업컨퍼런스",
     "link": "https://www.qualcomm.com/company/events/snapdragon-summit",
     "summary": "차기 플래그십 AP 공개 — 스마트폰 부품주 (삼성전자, 삼성전기, LG이노텍 등)"},

    # ===== 2차전지·ESS =====
    # The Battery Show North America 2026 (디트로이트 Huntington Place) — 워크숍 10/12, 전시 10/13-15
    #   https://www.thebatteryshow.com/
    {"date": "2026-10-12", "endDate": "2026-10-15", "title": "더배터리쇼 북미 2026 (디트로이트)", "category": "자동차/배터리",
     "link": "https://www.thebatteryshow.com/", "summary": _BATTERY},
    # RE+ 2026 (라스베이거스 컨벤션센터, 9월→11월 이동) — https://www.re-plus.com/about/future-dates/
    {"date": "2026-11-16", "endDate": "2026-11-19", "title": "RE+ 2026 (미국 태양광·ESS 전시회)", "category": "에너지",
     "link": "https://www.re-plus.com/", "summary": _ESS},

    # ===== 로봇·AI 하드웨어 =====
    # 2026 로보월드 (킨텍스) — https://robotworld.or.kr/visitors/information.php
    {"date": "2026-11-04", "endDate": "2026-11-07", "title": "로보월드 2026 (킨텍스)", "category": "산업컨퍼런스",
     "link": "https://www.robotworld.or.kr/", "summary": _ROBOT},
    # Humanoids Summit Silicon Valley 2026 (산마테오) — https://humanoidssummit.com/silicon-valley-2026
    {"date": "2026-12-01", "endDate": "2026-12-02", "title": "휴머노이드 서밋 2026 (실리콘밸리)", "category": "산업컨퍼런스",
     "link": "https://humanoidssummit.com/silicon-valley-2026", "summary": _ROBOT},

    # ===== 반도체 =====
    # SEMICON Taiwan 2026 (TaiNEX 1·2) — https://expo.semi.org/taiwan2026/public/Enter.aspx
    {"date": "2026-09-02", "endDate": "2026-09-04", "title": "SEMICON Taiwan 2026", "category": "반도체",
     "link": "https://www.semicontaiwan.org/en", "summary": f"첨단패키징·HBM 공급망 · {_SEMI_EQUIP}"},
    # SEDEX 2026 제28회 반도체대전 (코엑스 C·D1홀) — https://sedex.org/public_html_eng/summary/summary_info.asp
    {"date": "2026-10-14", "endDate": "2026-10-16", "title": "반도체대전 SEDEX 2026", "category": "반도체",
     "link": "https://www.sedex.org/", "summary": f"삼성전자·SK하이닉스 참가 · {_SEMI_EQUIP}"},
    # SEMICON Europa 2026 (메세 뮌헨, productronica 동시개최) — https://messe-muenchen.de/en/events/semicon-europa-2026.html
    {"date": "2026-11-10", "endDate": "2026-11-13", "title": "SEMICON Europa 2026 (뮌헨)", "category": "반도체",
     "link": "https://www.semiconeuropa.org/", "summary": _SEMI_EQUIP},
    # IEDM 2026 (샌프란시스코 Hilton Union Square) — https://ieee-iedm.org/
    {"date": "2026-12-12", "endDate": "2026-12-16", "title": "IEDM 2026 (국제전자소자학회)", "category": "반도체",
     "link": "https://ieee-iedm.org/", "summary": _SEMI_PAPER},

    # ===== 조선·LNG =====
    # SMM 2026 (함부르크) — https://www.smm-hamburg.com/
    {"date": "2026-09-01", "endDate": "2026-09-04", "title": "SMM 함부르크 2026 (조선해양 박람회)", "category": "전시/박람회",
     "link": "https://www.smm-hamburg.com/", "summary": _SHIP},
    # Gastech 2026 (방콕 BITEC) — https://www.dnv.com/events/gastech-2026/
    {"date": "2026-09-14", "endDate": "2026-09-17", "title": "가스텍 2026 (방콕, LNG·가스)", "category": "에너지",
     "link": "https://www.gastechevent.com/", "summary": _LNG},

    # ===== 방산 =====
    # MSPO 2026 (폴란드 키엘체) — https://www.targikielce.pl/en/mspo
    {"date": "2026-09-08", "endDate": "2026-09-11", "title": "MSPO 2026 (폴란드 방산전)", "category": "방산",
     "link": "https://www.targikielce.pl/en/mspo", "summary": f"K2·K9·천무 폴란드 수출 · {_DEFENSE}"},
    # DX KOREA 2026 (킨텍스) — https://v.daum.net/v/20260526103107456 (조직위 발표 보도)
    {"date": "2026-09-16", "endDate": "2026-09-19", "title": "DX KOREA 2026 (대한민국방위산업전)", "category": "방산",
     "link": "https://dxkorea.org/", "summary": _DEFENSE},
    # Land Forces 2026 (퍼스 컨벤션센터) — https://www.australiandefence.com.au/yafevent/the-land-forces-international-land-defence-exposition-2026
    {"date": "2026-10-06", "endDate": "2026-10-08", "title": "랜드포스 2026 (호주 지상방산전)", "category": "방산",
     "link": "https://landforces.com.au/", "summary": "레드백·AS9 호주 사업 — 한화에어로스페이스 등 K-방산주"},
    # AUSA 2026 (워싱턴DC WEWCC) — https://meetings.ausa.org/annual/2026/index.cfm
    {"date": "2026-10-12", "endDate": "2026-10-14", "title": "AUSA 2026 (미 육군협회 방산전)", "category": "방산",
     "link": "https://meetings.ausa.org/annual/2026/index.cfm", "summary": _DEFENSE},
    # Euronaval 2026 (파리 노르 빌팽트) — https://www.euronaval.com/
    {"date": "2026-11-03", "endDate": "2026-11-06", "title": "유로나발 2026 (파리 해군방산전)", "category": "방산",
     "link": "https://www.euronaval.com/", "summary": "함정·잠수함 수출 — 한화오션, HD현대중공업, LIG넥스원 등"},
    # Indo Defence 2026 (자카르타 JIExpo) — https://indodefence.com/indo-defence-2026-opens-opportunities-amidst-indonesias-defence-market/
    {"date": "2026-11-18", "endDate": "2026-11-21", "title": "인도디펜스 2026 (자카르타 방산전)", "category": "방산",
     "link": "https://indodefence.com/", "summary": f"KF-21 공동개발국 · {_DEFENSE}"},

    # ===== 원전·에너지 정책 =====
    # 제70차 IAEA 총회 (빈 VIC) — https://www.iaea.org/newscenter/news/the-week-ahead-iaea-hosts-70th-general-conference
    {"date": "2026-09-14", "endDate": "2026-09-18", "title": "IAEA 총회 2026 (제70차, 빈)", "category": "에너지",
     "link": "https://www.iaea.org/about/governance/general-conference", "summary": _NUCLEAR},
    # COP31 (튀르키예 안탈리아 EXPO) — https://unfccc.int/cop31/the-road-to-antalya
    {"date": "2026-11-09", "endDate": "2026-11-20", "title": "COP31 기후총회 (튀르키예 안탈리아)", "category": "에너지",
     "link": "https://unfccc.int/cop31", "summary": "신재생·원전·수소 정책 (한화솔루션, 씨에스윈드, 두산에너빌리티 등)"},
]


INDUSTRY_EVENTS_2027 = [
    # ===== 광통신·포토닉스 =====
    # SPIE Photonics West 2027 (샌프란시스코 Moscone) — 학회 1/30-2/4, 전시 2/2-4
    #   https://spie.org/conferences-and-exhibitions/photonics-west
    {"date": "2027-01-30", "endDate": "2027-02-04", "title": "SPIE 포토닉스 웨스트 2027", "category": "산업컨퍼런스",
     "link": "https://spie.org/conferences-and-exhibitions/photonics-west",
     "summary": "전시 2/2-4 · 광학·레이저·실리콘포토닉스 관련주 (이오테크닉스, 오이솔루션 등)"},
    # OFC 2027 (LA 컨벤션센터) — 학회 3/7-11, 전시 3/9-11  https://www.ofcconference.org/about/
    {"date": "2027-03-07", "endDate": "2027-03-11", "title": "OFC 2027 (광통신 학회·전시)", "category": "산업컨퍼런스",
     "link": "https://www.ofcconference.org/", "summary": f"전시 3/9-11 · {_OPTICAL}"},
    # CIOE 2027 (선전 국제컨벤션센터) — https://www.cioe.cn/en/Brief.html
    {"date": "2027-09-08", "endDate": "2027-09-10", "title": "CIOE 2027 (중국 선전 광전자전)", "category": "산업컨퍼런스",
     "link": "https://www.cioe.cn/en/", "summary": _OPTICAL},
    # ECOC 2027 (밀라노 MiCo) — 학회 10/10-14, 전시 10/11-13  https://www.ecocexhibition.com/future-dates/
    {"date": "2027-10-10", "endDate": "2027-10-14", "title": "ECOC 2027 (유럽광통신학회)", "category": "산업컨퍼런스",
     "link": "https://www.ecocexhibition.com/", "summary": f"이탈리아 밀라노, 전시 10/11-13 · {_OPTICAL}"},

    # ===== XR·디스플레이 =====
    # SID Display Week 2027 (새너제이) — 심포지엄 6/6-11, 전시 6/8-10  https://www.displayweek.org/attendees/why-attend/
    {"date": "2027-06-06", "endDate": "2027-06-11", "title": "SID 디스플레이위크 2027", "category": "산업컨퍼런스",
     "link": "https://www.displayweek.org/", "summary": f"전시 6/8-10 · {_DISPLAY}"},
    # AWE USA 2027 (롱비치) — https://www.awexr.com/usa-2027/
    {"date": "2027-06-14", "endDate": "2027-06-17", "title": "AWE USA 2027 (XR·AI 글래스 엑스포)", "category": "산업컨퍼런스",
     "link": "https://www.awexr.com/usa-2027/", "summary": _XR},

    # ===== 2차전지·EV·ESS =====
    # 인터배터리 2027 (코엑스 A·B·C·D홀) — https://interbattery.or.kr/
    {"date": "2027-03-10", "endDate": "2027-03-12", "title": "인터배터리 2027", "category": "자동차/배터리",
     "link": "https://interbattery.or.kr/", "summary": _BATTERY},
    # The smarter E Europe 2027 (Intersolar·ees Europe, 메세 뮌헨) — 전시 6/8-10  https://www.intersolar.de/home
    {"date": "2027-06-08", "endDate": "2027-06-10", "title": "더 스마터 E 유럽 2027 (ESS·태양광, 뮌헨)", "category": "에너지",
     "link": "https://www.intersolar.de/", "summary": _ESS},
    # The Battery Show Europe 2027 (메세 슈투트가르트) — https://www.thebatteryshow.eu/
    {"date": "2027-06-22", "endDate": "2027-06-24", "title": "더배터리쇼 유럽 2027 (슈투트가르트)", "category": "자동차/배터리",
     "link": "https://www.thebatteryshow.eu/", "summary": _BATTERY},
    # IAA MOBILITY 2027 (뮌헨) — 프레스데이 9/6  https://www.iaa-mobility.com/en
    {"date": "2027-09-07", "endDate": "2027-09-12", "title": "IAA 모빌리티 2027 (뮌헨 모터쇼)", "category": "자동차/배터리",
     "link": "https://www.iaa-mobility.com/en",
     "summary": "프레스데이 9/6 · 완성차·부품·2차전지 (현대차, 기아, 현대모비스, LG에너지솔루션 등)"},
    # RE+ 2027 (라스베이거스 컨벤션센터) — https://www.re-plus.com/about/future-dates/
    {"date": "2027-11-15", "endDate": "2027-11-18", "title": "RE+ 2027 (미국 태양광·ESS 전시회)", "category": "에너지",
     "link": "https://www.re-plus.com/", "summary": _ESS},

    # ===== 로봇 =====
    # 2027 세계로봇대회 WRC (베이징) — 2026 폐막식에서 개막일(8/18)만 공식 발표, 폐막일 미공표
    #   https://www.worldrobotconference.com/news/3616.html
    {"date": "2027-08-18", "title": "세계로봇대회 WRC 2027 개막 (베이징)", "category": "산업컨퍼런스",
     "link": "https://www.worldrobotconference.com/", "summary": f"중국 휴머노이드 신제품 공개 · {_ROBOT}"},

    # ===== 반도체 =====
    # ISSCC 2027 (샌프란시스코 Marriott Marquis) — https://www.isscc.org/
    {"date": "2027-02-14", "endDate": "2027-02-18", "title": "ISSCC 2027 (국제고체회로학회)", "category": "반도체",
     "link": "https://www.isscc.org/", "summary": _SEMI_PAPER},
    # SEMICON China 2027 (상하이 SNIEC) — https://www.semiconchina.org/en/1
    {"date": "2027-03-24", "endDate": "2027-03-26", "title": "SEMICON China 2027 (상하이)", "category": "반도체",
     "link": "https://www.semiconchina.org/en/", "summary": f"중국 장비 투자 동향 · {_SEMI_EQUIP}"},
    # 2027 VLSI 심포지엄 (교토 RIHGA Royal) — https://www.vlsisymposium.org/info.html
    {"date": "2027-06-20", "endDate": "2027-06-24", "title": "VLSI 심포지엄 2027 (교토)", "category": "반도체",
     "link": "https://www.vlsisymposium.org/", "summary": _SEMI_PAPER},
    # FMS 2027 (산타클라라 컨벤션센터) — 본문 7/27-29 (푸터 7/28-30 표기 혼재, 본문 기준)
    #   https://www.terrapinn.com/conference/future-memory-storage/index.stm
    {"date": "2027-07-27", "endDate": "2027-07-29", "title": "FMS 2027 (메모리·스토리지 서밋)", "category": "반도체",
     "link": "https://www.terrapinn.com/conference/future-memory-storage/index.stm",
     "summary": "HBM·eSSD·CXL 로드맵 — 삼성전자, SK하이닉스 등 메모리주"},
    # IEDM 2027 (샌프란시스코 Hilton Union Square) — http://ieee-iedm.org/future-conferences
    {"date": "2027-12-04", "endDate": "2027-12-08", "title": "IEDM 2027 (국제전자소자학회)", "category": "반도체",
     "link": "https://ieee-iedm.org/", "summary": _SEMI_PAPER},

    # ===== 조선·LNG =====
    # Nor-Shipping 2027 (릴레스트룀 NOVA Spektrum) — 전시 6/8-11  https://nor-shipping.com/
    {"date": "2027-06-07", "endDate": "2027-06-11", "title": "노르쉬핑 2027 (오슬로 조선해운전)", "category": "전시/박람회",
     "link": "https://nor-shipping.com/", "summary": f"전시 6/8-11 · {_SHIP}"},
    # Gastech 2027 (휴스턴 George R. Brown) — https://www.gastechevent.com/networking/
    {"date": "2027-09-14", "endDate": "2027-09-17", "title": "가스텍 2027 (휴스턴, LNG·가스)", "category": "에너지",
     "link": "https://www.gastechevent.com/", "summary": _LNG},
    # KORMARINE 2027 (부산 BEXCO 1·2전시장) — https://www.kormarine.com/ko-kr/about/show-info.html
    {"date": "2027-10-19", "endDate": "2027-10-22", "title": "코마린 2027 (부산 조선해양전)", "category": "전시/박람회",
     "link": "https://www.kormarine.com/", "summary": _SHIP},

    # ===== 방산·항공우주 =====
    # IDEX 2027 (아부다비 ADNEC) — 공식 사이트 1/25-29 (ADNEC 2025년 보도자료의 1/21-25는 구 일정)
    #   https://www.idexuae.ae/en
    {"date": "2027-01-25", "endDate": "2027-01-29", "title": "IDEX 2027 (아부다비 방산전)", "category": "방산",
     "link": "https://www.idexuae.ae/en", "summary": f"중동 수출 · {_DEFENSE}"},
    # 파리 에어쇼 2027 (르부르제, 제56회) — https://www.siae.fr/le-salon/
    {"date": "2027-06-14", "endDate": "2027-06-20", "title": "파리 에어쇼 2027", "category": "방산",
     "link": "https://www.siae.fr/", "summary": "항공우주·항공엔진 부품 (한국항공우주, 한화에어로스페이스 등)"},
    # DSEI 2027 (런던 ExCeL) — https://www.dsei.co.uk/
    {"date": "2027-09-07", "endDate": "2027-09-10", "title": "DSEI 2027 (런던 방산전)", "category": "방산",
     "link": "https://www.dsei.co.uk/", "summary": _DEFENSE},
    # 서울 ADEX 2027 (서울공항) — https://seouladex.com/en/public/seoul-adex/overview.php
    {"date": "2027-10-19", "endDate": "2027-10-24", "title": "서울 ADEX 2027 (항공우주·방산전)", "category": "방산",
     "link": "https://seouladex.com/", "summary": _DEFENSE},

    # ===== 원전 =====
    # 제71차 IAEA 총회 (빈) — https://www.iaea.org/events/evt2505290
    {"date": "2027-09-13", "endDate": "2027-09-17", "title": "IAEA 총회 2027 (제71차, 빈)", "category": "에너지",
     "link": "https://www.iaea.org/events/evt2505290", "summary": _NUCLEAR},
    # WNE 2027 세계원자력전시회 (파리 노르 빌팽트, 격년) — https://www.world-nuclear-exhibition.com/en-gb/the-show.html
    {"date": "2027-12-07", "endDate": "2027-12-09", "title": "세계원자력전시회 WNE 2027 (파리)", "category": "에너지",
     "link": "https://www.world-nuclear-exhibition.com/", "summary": _NUCLEAR},
]


def fetch_industry_events(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """조회 구간과 겹치는 산업 이벤트 반환 (news_events.fetch_known_events 와 동일 스키마)"""
    results = []
    for ev in INDUSTRY_EVENTS_2026 + INDUSTRY_EVENTS_2027:
        try:
            ev_start = datetime.date.fromisoformat(ev["date"])
            ev_end = datetime.date.fromisoformat(ev.get("endDate", ev["date"]))
        except (ValueError, KeyError):
            continue
        if ev_start > to_date or ev_end < from_date:
            continue

        result = {
            "date": ev["date"],
            "time": "",
            "category": ev["category"],
            "title": ev["title"],
            "source": "known",  # 하드코딩 스냅샷 (update.py SNAPSHOT_SOURCES)
            "auto": True,
        }
        if ev.get("endDate"):
            result["endDate"] = ev["endDate"]
        if ev.get("link"):
            result["link"] = ev["link"]
        if ev.get("summary"):
            result["summary"] = ev["summary"]
        results.append(result)

    results.sort(key=lambda e: e["date"])
    return results
