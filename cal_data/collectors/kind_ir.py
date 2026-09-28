"""KRX KIND IR일정 수집 — 한국 상장사 실적발표(컨퍼런스콜)·기업설명회 향후 일정

FnGuide 신버전은 향후 실적발표 일정(IR 16/17)을 더 이상 제공하지 않아 KIND를 주 소스로 사용.

소스: https://kind.krx.co.kr/corpgeneral/irschedule.do?method=searchIRScheduleMain&gubun=iRSchedule
  목록 AJAX: POST /corpgeneral/irschedule.do
    method=searchIRScheduleSub, forward=searchirschedule_sub,
    fromDate/toDate=YYYY-MM-DD, pageIndex, currentPageSize(15/30/50/100), orderMode=4, orderStat=D
  → HTML 조각: table.list tbody tr = 번호 | 회사명 | 제목 | 장소 | 일자 | 시작시간
     페이징 div.info "전체 N 건 : p /P", 결과 없음 = "조회된 결과값이 없습니다." 1칸 행
  상장사 '기업설명회(IR) 개최' 공시가 등록됨 → 대형주 분기 실적 컨퍼런스콜 포함 (통상 발표 1~2주 전 공시).
  같은 IR이 국문/영문 2행으로 올라오는 경우가 많아 (회사, 날짜) 단위로 병합.
"""
import datetime
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://kind.krx.co.kr/corpgeneral/irschedule.do"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://kind.krx.co.kr/corpgeneral/irschedule.do?method=searchIRScheduleMain&gubun=iRSchedule",
}
PAGE_SIZE = 100
PAGE_SLEEP = 0.5
MAX_PAGES = 80

# 같은 기업의 실적 IR이 이 기간 내 반복되면 첫 건만 실적발표, 이후는 실적 설명회(NDR성)로 강등
#   (예: iM금융지주 7/27 실적발표 → 7/29 "상반기 경영실적 등 주요 관심사항 설명")
SEASON_GAP_DAYS = 21
# 조회 시작일 이전 구간도 조회해 위 판정 문맥으로만 사용 (결과는 요청 구간만 반환)
LOOKBACK_DAYS = 21

# 실적 IR 제목 형식 — 기존 소비처 호환을 위해 " 실적발표" 로 끝나야 함
#   (telegram_bot/collectors/schedule_collector._extract_corp_name, update._dedupe_provisional_official_close 가
#    " 실적발표" 접미사만 떼어 기업명을 추출)
EARNINGS_TITLE_FMT = "{corp} 실적발표"

# 코넥스 IR은 거래소 주관 합동 IR(하루 20건+) 위주라 기본 제외
SKIP_MARKETS_DEFAULT = {"코넥스"}

# 직전 실행에서 조회 실패한 구간 [(from, to)] — 호출측 진단/보존 판단용
LAST_FAILED_RANGES: list[tuple[str, str]] = []

_KRX_LISTING = Path(__file__).resolve().parents[2] / "telegram_bot" / "history" / "krx_listing.json"
_NAME_BY_ISUR = None

# ───────────────────────── 분류 ─────────────────────────

_NDR_RE = re.compile(r"NDR|Non[\s-]*Deal|road\s*show|로드쇼|탐방", re.I)
_EARN_DIRECT_RE = re.compile(
    r"실적\s*(발표|설명)|earnings?\s+(release|call|conference|announcement|results?|review)"
    r"|results?\s+(release|announcement)", re.I)
_PERIOD_RE = re.compile(
    r"[1-4]\s*분기|\b[1-4]Q|\bQ[1-4]|\b[12]H(?=\b|\d)|상반기|하반기|반기|연간|결산|회계연도|사업연도"
    r"|\bFY\s?\d{2,4}|\bquarter|\bhalf\b|full[\s-]*year", re.I)
_EARN_WORD_RE = re.compile(r"실적|기업설명회|컨퍼런스\s*콜|earning|results?\b", re.I)

_IR_LABELS = [
    (re.compile(r"NDR|Non[\s-]*Deal|road\s*show|로드쇼", re.I), "NDR"),
    (re.compile(r"컨퍼런스\s*콜|conference\s*call", re.I), "컨퍼런스콜"),
    (re.compile(r"주주\s*간담회|주주\s*소통|shareholder", re.I), "주주간담회"),
    (re.compile(r"corporate\s*day|컨퍼런스|conference|포럼|forum|summit|서밋|premium\s*weeks|박람회", re.I),
     "컨퍼런스 참가"),
    (re.compile(r"탐방|투어|\btour\b|견학|site\s*visit", re.I), "기업탐방"),
    (re.compile(r"임상|파이프라인|pipeline|R&D|연구개발", re.I), "R&D 설명회"),
    (re.compile(r"전략|비전|investor\s*day|인베스터\s*데이|밸류업|value[\s-]*up", re.I), "전략 발표"),
]
_HANGUL_RE = re.compile(r"[가-힣]")


def _is_earnings(title: str) -> bool:
    """IR 제목이 분기/반기/연간 실적발표인지 판별 (실적 NDR·로드쇼는 제외)"""
    if not title or _NDR_RE.search(title):
        return False
    if _EARN_DIRECT_RE.search(title):
        return True
    return bool(_PERIOD_RE.search(title) and _EARN_WORD_RE.search(title))


def _ir_label(titles: list[str]) -> str:
    text = " ".join(titles)
    for pat, label in _IR_LABELS:
        if pat.search(text):
            return label
    return "기업설명회"


def _norm_time(raw: str) -> str:
    """'9:00' → '09:00', '13시30분' → '13:30', '--:--'/'-' → ''"""
    m = re.match(r"^\s*(\d{1,2})\s*(?::|시)\s*(\d{1,2})?", raw or "")
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return ""
    return f"{h:02d}:{mi:02d}"


def _canonical_name(isur_cd: str, kind_name: str) -> str:
    """KIND 발행사코드(종목코드 앞 5자리) → KRX 약칭 (예: 현대자동차 → 현대차). 실패 시 KIND 이름."""
    global _NAME_BY_ISUR
    if _NAME_BY_ISUR is None:
        _NAME_BY_ISUR = {}
        try:
            data = json.loads(_KRX_LISTING.read_text(encoding="utf-8"))
            for s in data.get("stocks", []):
                code, name = str(s.get("code", "")), str(s.get("name", "")).strip()
                if len(code) == 6 and code.endswith("0") and name:  # 보통주만
                    _NAME_BY_ISUR.setdefault(code[:5], name)
        except Exception as e:
            print(f"[KIND] krx_listing.json 로드 실패 (KIND 표기 사용): {e}")
    krx = _NAME_BY_ISUR.get(isur_cd or "")
    if not krx or krx == kind_name:
        return kind_name
    # 한쪽이 다른 쪽을 포함하면 짧은 쪽 (롯데칠성음료→롯데칠성, 마스터가 옛 사명인 SPC삼립 vs 삼립→삼립)
    if kind_name in krx or krx in kind_name:
        return min(kind_name, krx, key=len)
    return krx


# ───────────────────────── HTTP ─────────────────────────

def _fetch_page(fr: str, to: str, page: int) -> tuple[list[dict], int] | None:
    """목록 1페이지 → (rows, total_pages). 실패 시 None."""
    data = {
        "method": "searchIRScheduleSub", "forward": "searchirschedule_sub",
        "currentPageSize": str(PAGE_SIZE), "pageIndex": str(page),
        "orderMode": "4", "orderStat": "D",
        "marketType": "", "searchCodeType": "", "repIsuSrtCd": "", "searchCorpName": "",
        "title": "", "fromDate": fr, "toDate": to,
    }
    last_err = ""
    for attempt in range(2):
        try:
            res = requests.post(URL, data=data, headers=HEADERS, timeout=20)
        except requests.RequestException as e:
            last_err = f"요청 실패 {type(e).__name__}: {e}"
            time.sleep(2)
            continue
        if res.status_code != 200:
            last_err = f"HTTP {res.status_code}"
            time.sleep(2)
            continue
        res.encoding = res.encoding or "utf-8"
        soup = BeautifulSoup(res.text, "lxml")
        table = soup.select_one("table.list")
        if table is None:
            snippet = " ".join(soup.get_text(" ", strip=True).split())[:120]
            print(f"[KIND] ERROR: {fr}~{to} p{page} — 목록 테이블 없음 (페이지 구조 변경/차단 의심): {snippet}")
            return None

        rows = []
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue  # "조회된 결과값이 없습니다."
            corp_a = tds[1].find("a")
            m = re.search(r"companysummary_open\('([^']*)'\)", corp_a.get("onclick", "") if corp_a else "")
            img = tds[1].find("img")
            rows.append({
                "market": (img.get("alt", "") if img else "").strip(),
                "isur_cd": m.group(1) if m else "",
                "corp": (corp_a.get("title") if corp_a and corp_a.get("title") else tds[1].get_text(" ", strip=True)).strip(),
                "title": " ".join(tds[2].get_text(" ", strip=True).split()),
                "loc": " ".join(tds[3].get_text(" ", strip=True).split()),
                "date": tds[4].get_text(strip=True),
                "time": _norm_time(tds[5].get_text(" ", strip=True)),
            })

        total_pages = 1
        info = soup.select_one("div.info")
        if info:
            pm = re.search(r":\s*\d+\s*/\s*(\d+)", info.get_text(" ", strip=True))
            if pm:
                total_pages = int(pm.group(1))
        return rows, total_pages
    print(f"[KIND] ERROR: {fr}~{to} p{page} — {last_err}")
    return None


# ───────────────────────── 공개 API ─────────────────────────

def _to_iso(d) -> str:
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def fetch_kind_ir(from_date, to_date, include_konex: bool = False) -> list[dict]:
    """KIND IR일정 → 캘린더 이벤트
    실적 IR  : {"category": "한국실적", "title": "{회사} 실적발표"}
    기타 IR  : {"category": "IR", "title": "{회사} IR ({요지})"}
    공통     : date, time(HH:MM 또는 ""), source "kind", auto True, summary(원제목 · 장소)
    """
    fr, to = _to_iso(from_date), _to_iso(to_date)
    q_fr = (datetime.date.fromisoformat(fr) - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    LAST_FAILED_RANGES.clear()
    skip_markets = set() if include_konex else SKIP_MARKETS_DEFAULT

    raw = []
    page, total_pages = 1, 1
    while page <= min(total_pages, MAX_PAGES):
        got = _fetch_page(q_fr, to, page)
        if got is None:
            LAST_FAILED_RANGES.append((fr, to))
            break
        rows, total_pages = got
        raw.extend(rows)
        if not rows:
            break
        page += 1
        if page <= total_pages:
            time.sleep(PAGE_SLEEP)
    if total_pages > MAX_PAGES:
        print(f"[KIND] 경고: {total_pages}페이지 중 {MAX_PAGES}페이지까지만 수집")

    # 1단계: (회사, 날짜, 시각) 단위 병합 — 국문/영문 중복 행을 하나로, 한 행이라도 실적이면 실적 IR
    groups: dict[tuple, dict] = {}
    for r in raw:
        if r["market"] in skip_markets:
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]) or not (q_fr <= r["date"] <= to):
            continue
        corp = _canonical_name(r["isur_cd"], r["corp"])
        if not corp or "스팩" in corp:
            continue
        key = (r["isur_cd"] or corp, r["date"], r["time"])
        g = groups.setdefault(key, {"corp": corp, "date": r["date"], "time": r["time"],
                                    "titles": [], "locs": [], "earn": False})
        if r["title"] and r["title"] not in g["titles"]:
            g["titles"].append(r["title"])
        if r["loc"] and r["loc"] not in ("-", "--") and r["loc"] not in g["locs"]:
            g["locs"].append(r["loc"])
        g["earn"] = g["earn"] or _is_earnings(r["title"])

    # 2단계: (회사, 날짜, 유형) 단위 병합 — 같은 날 동일 IR 중복 등록 제거 (가장 이른 시각 유지)
    merged: dict[tuple, dict] = {}
    for key in sorted(groups, key=lambda k: (k[1], k[2] or "99:99")):
        g = groups[key]
        k2 = (key[0], g["date"], g["earn"])
        if k2 in merged:
            m = merged[k2]
            m["titles"] += [t for t in g["titles"] if t not in m["titles"]]
            m["locs"] += [l for l in g["locs"] if l not in m["locs"]]
            m["time"] = m["time"] or g["time"]
        else:
            merged[k2] = g

    events = []
    for g in merged.values():
        ko = [t for t in g["titles"] if _HANGUL_RE.search(t)]
        main_title = (ko or g["titles"] or [""])[0]
        loc_ko = [l for l in g["locs"] if _HANGUL_RE.search(l)]
        loc = (loc_ko or g["locs"] or [""])[0]
        summary = " · ".join(x for x in (main_title, loc) if x)[:150]

        if g["earn"]:
            category = "한국실적"
            title = EARNINGS_TITLE_FMT.format(corp=g["corp"])
        else:
            category = "IR"
            title = f"{g['corp']} IR ({_ir_label(ko or g['titles'])})"

        ev = {
            "date": g["date"],
            "time": g["time"],
            "category": category,
            "title": title,
            "source": "kind",
            "auto": True,
            "_corp": g["corp"],
        }
        if summary:
            ev["summary"] = summary
        events.append(ev)

    events.sort(key=lambda e: (e["date"], e["time"] or "99:99", e["category"], e["title"]))

    # 실적 시즌 내 후속 실적 IR 강등 (첫 건만 실적발표)
    anchor: dict[str, datetime.date] = {}
    for ev in events:
        if ev["category"] != "한국실적":
            continue
        d = datetime.date.fromisoformat(ev["date"])
        a = anchor.get(ev["_corp"])
        if a is not None and (d - a).days <= SEASON_GAP_DAYS:
            ev["category"] = "IR"
            ev["title"] = f"{ev['_corp']} IR (실적 설명회)"
        else:
            anchor[ev["_corp"]] = d

    events = [{k: v for k, v in ev.items() if not k.startswith("_")}
              for ev in events if ev["date"] >= fr]  # lookback 구간은 판정 문맥용 → 제외
    n_earn = sum(1 for e in events if e["category"] == "한국실적")
    status = " (일부 실패)" if LAST_FAILED_RANGES else ""
    print(f"[KIND] IR일정 {fr}~{to}: 원본 {len(raw)}행 → {len(events)}건 (실적 {n_earn}){status}")
    return events
