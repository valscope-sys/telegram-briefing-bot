"""FnGuide 기업 캘린더 수집 (wcomp.fnguide.com 신버전)

구 사이트(comp.fnguide.com/SVO2/json/data/05_01/YYYYMM.json, svd_comp_calendarData.asp)는
폐쇄되어 "페이지가 없습니다" HTML만 반환 → 신버전 AJAX 엔드포인트로 교체.

엔드포인트 (GET, 파라미터 dt=YYYYMM, capchg_typ=쉼표구분 코드, grp_cd=쉼표구분 그룹):
  /Calendar/getCalendar_Newtonsoft  → {"dataset":[...]} 달력 그리드 (날짜×기업 1행, CMP_KOR null = 빈 날짜)
  /Calendar/getListPreliminary      → 잠정실적 수치 (영업이익 실적 vs 컨센)

이벤트 코드 (capchg_typ / grp_cd):
  0 잠정실적발표 (grp 1)             → 한국실적(잠정)   ※ 이미 공시된 과거분만 제공 (향후 예정 X)
  14 신규상장 / 15 재상장 (grp 3)    → IPO/공모
  16 IR|실적발표 / 17 IR|경영현황 (grp 4) → 한국실적 / IR  ※ 2026-09 현재 전 기간 0건 (FnGuide 미제공)
  수집 제외 (사용자 요청): 1 유상증자 · 2 무상증자 · 3 합병/분할 · 4 감자 · 5 액면변경 · 11 배당 · 12 상호변경

향후 실적발표(컨퍼런스콜) 일정은 cal_data/collectors/kind_ir.py (KRX KIND IR일정) 에서 수집.
"""
import datetime
import re
import time

import requests

BASE_URL = "https://wcomp.fnguide.com/Calendar/"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://wcomp.fnguide.com/Calendar/CompCalendar",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

TYPE_PRELIM = 0          # 잠정실적발표
TYPE_NEW_LISTING = 14    # 신규상장
TYPE_RELISTING = 15      # 재상장
TYPE_IR_EARNINGS = 16    # IR | 실적발표
TYPE_IR_MGMT = 17        # IR | 경영현황

# 수집 대상 capchg_typ → grp_cd
COLLECT_TYPES = {
    TYPE_PRELIM: 1,
    TYPE_NEW_LISTING: 3,
    TYPE_RELISTING: 3,
    TYPE_IR_EARNINGS: 4,
    TYPE_IR_MGMT: 4,
}

# 스팩/우선주 필터
SKIP_KEYWORDS = ["스팩", "SPAC", "우B", "우C"]

# 직전 실행에서 조회 실패한 월 (YYYYMM) — 호출측 진단용
LAST_FAILED_MONTHS: list[str] = []

_BASIS_RE = re.compile(r"\((연결|개별|별도)\)\s*$")


# ───────────────────────── HTTP ─────────────────────────

def _get_dataset(endpoint: str, yyyymm: str, types: list[int]) -> list[dict] | None:
    """FnGuide AJAX 호출 → dataset 리스트. 실패 시 None (에러 로그 출력)."""
    params = {
        "dt": yyyymm,
        "capchg_typ": ",".join(str(t) for t in types),
        "grp_cd": ",".join(str(g) for g in sorted({COLLECT_TYPES.get(t, 1) for t in types})),
    }
    last_err = ""
    for attempt in range(2):
        try:
            res = requests.get(BASE_URL + endpoint, params=params, headers=HEADERS, timeout=20)
        except requests.RequestException as e:
            last_err = f"요청 실패 {type(e).__name__}: {e}"
            time.sleep(1.5)
            continue
        if res.status_code != 200:
            last_err = f"HTTP {res.status_code}"
            time.sleep(1.5)
            continue
        text = res.text.lstrip("﻿").strip()
        ctype = res.headers.get("Content-Type", "")
        if text.startswith("<") or "html" in ctype.lower():
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:120]
            print(f"[FnGuide] ERROR: {endpoint} {yyyymm} — JSON 대신 HTML 응답 "
                  f"(엔드포인트 폐쇄/변경 의심): {snippet}")
            return None
        try:
            data = res.json()
        except ValueError:
            print(f"[FnGuide] ERROR: {endpoint} {yyyymm} — JSON 파싱 실패 "
                  f"(Content-Type={ctype}): {text[:120]!r}")
            return None
        rows = data.get("dataset") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"[FnGuide] ERROR: {endpoint} {yyyymm} — 예상과 다른 응답 구조 (dataset 없음): {keys}")
            return None
        return rows
    print(f"[FnGuide] ERROR: {endpoint} {yyyymm} — {last_err}")
    return None


# ───────────────────────── 파싱 헬퍼 ─────────────────────────

def _clean_name(raw: str) -> tuple[str, bool, str]:
    """'[정정]DL(연결)' → ('DL', True, '연결')"""
    name = (raw or "").strip()
    corrected = False
    if name.startswith("[정정]"):
        corrected = True
        name = name[len("[정정]"):].strip()
    basis = ""
    m = _BASIS_RE.search(name)
    if m:
        basis = m.group(1)
        name = name[:m.start()].strip()
    return name, corrected, basis


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _fmt_eok(v: float) -> str:
    """억원 단위 수치 → '2,565억' / '2.85조' / '89.4조'"""
    if abs(v) >= 10000:
        digits = 1 if abs(v) >= 100000 else 2
        s = f"{v / 10000:.{digits}f}".rstrip("0").rstrip(".")
        return f"{s}조"
    return f"{v:,.0f}억"


def _period_label(yymm: str, freq: str | None) -> str:
    """('2026/06', '2Q') → '2Q' / FREQ 없으면 월로 추정"""
    if freq:
        return str(freq).strip()
    digits = re.sub(r"\D", "", yymm or "")
    if len(digits) >= 6:
        q = {"03": "1Q", "06": "2Q", "09": "3Q", "12": "4Q"}.get(digits[4:6])
        if q:
            return q
    return ""


def _prelim_summary(period: str, basis: str, actual: float | None, cons: float | None,
                    corrected: bool) -> str:
    """'2Q 영업이익 2,565억 (컨센 2,044억, +25.5%)'

    FnGuide 필드 검증 (2026-07/08 삼성전자·SK하이닉스·DL·셀트리온 대조):
      *_P  = 발표 실적(Preliminary), *_E = 컨센서스(Estimate)
      달력 DET_DATA3 = 실적, DET_DATA2 = 컨센, DET_DATA4 괴리율 = (실적-컨센)/컨센
      *_G 는 괴리율이 아니라 성장률(QoQ)이므로 사용하지 않음.
    """
    if actual is None:
        return ""
    label = "영업이익" + ("(별도)" if basis in ("개별", "별도") else "")
    s = f"{period} {label} {_fmt_eok(actual)}".strip()
    if cons is not None:
        if cons > 0 and actual > 0:  # 적자·흑전 구간은 괴리율 % 가 무의미 → 컨센 수치만
            gap = (actual - cons) / cons * 100
            s += f" (컨센 {_fmt_eok(cons)}, {gap:+.1f}%)"
        else:
            s += f" (컨센 {_fmt_eok(cons)})"
    if corrected:
        s = "정정공시 · " + s
    return s


_DET_OP_RE = re.compile(r"(\d{6})\([^)]*\)\s*영업이익\((연결|개별|별도)\)\s*:\s*(-?[\d,\.]+)")


def _prelim_from_det(row: dict) -> dict | None:
    """getListPreliminary 실패 시 폴백: 달력 DET_DATA2(컨센)/DET_DATA3(실적) 문자열 파싱"""
    act = _DET_OP_RE.search(row.get("DET_DATA3") or "")
    if not act:
        return None
    cons = _DET_OP_RE.search(row.get("DET_DATA2") or "")
    return {
        "yymm": act.group(1),
        "freq": None,
        "basis": act.group(2),
        "actual": _num(act.group(3)),
        "cons": _num(cons.group(3)) if cons else None,
    }


def _det_value(row: dict, label: str) -> str:
    for i in range(1, 16):
        v = row.get(f"DET_DATA{i}") or ""
        if v.startswith(label):
            return v.split(":", 1)[-1].strip()
    return ""


# ───────────────────────── 월 단위 수집 ─────────────────────────

def _fetch_month_raw(year: int, month: int) -> list[dict] | None:
    """한 달치 이벤트 (내부 키 포함). 달력 조회 실패 시 None."""
    yyyymm = f"{year}{month:02d}"
    cal = _get_dataset("getCalendar_Newtonsoft", yyyymm, list(COLLECT_TYPES))
    if cal is None:
        return None

    rows = [r for r in cal if r.get("CMP_KOR")]  # CMP_KOR null = 이벤트 없는 달력 칸

    # 잠정실적 수치 (연결 우선)
    prelim = {}
    if any(r.get("CAPCHG_TYP") == TYPE_PRELIM for r in rows):
        lst = _get_dataset("getListPreliminary", yyyymm, [TYPE_PRELIM])
        for x in lst or []:
            name, corrected, basis = _clean_name(x.get("CMP_NM", ""))
            dt = re.sub(r"\D", "", x.get("DT") or "")[:8]
            key = (dt, x.get("CMP_CD"))
            info = {
                "yymm": re.sub(r"\D", "", x.get("YYMM") or ""),
                "freq": x.get("FREQ"),
                "basis": basis,
                "actual": _num(x.get("OPERATION_PROFIT_P")),
                "cons": _num(x.get("OPERATION_PROFIT_E")),
            }
            old = prelim.get(key)
            if old is None or (old["basis"] != "연결" and basis == "연결"):
                prelim[key] = info
        if lst is None:
            print(f"[FnGuide] {yyyymm} 잠정실적 수치 목록 실패 → 달력 상세 문자열로 대체")

    events = []
    for r in rows:
        try:
            typ = int(r.get("CAPCHG_TYP"))
        except (TypeError, ValueError):
            continue
        if typ not in COLLECT_TYPES:
            continue

        company, corrected, basis = _clean_name(r.get("CMP_KOR", ""))
        if not company or any(kw in company for kw in SKIP_KEYWORDS):
            continue

        ymd = re.sub(r"\D", "", r.get("YMD") or "")[:8]
        if len(ymd) != 8:
            continue
        ev_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        cmp_cd = r.get("CMP_CD") or company
        summary = ""
        period_key = ""

        if typ == TYPE_PRELIM:
            category = "한국실적(잠정)"
            title = f"{company} 잠정실적발표"
            info = prelim.get((ymd, r.get("CMP_CD"))) or _prelim_from_det(r)
            if info:
                basis = info["basis"] or basis
                period_key = info["yymm"]
                summary = _prelim_summary(_period_label(info["yymm"], info["freq"]), basis,
                                          info["actual"], info["cons"], corrected)
        elif typ == TYPE_NEW_LISTING:
            category = "IPO/공모"
            title = f"{company} 신규상장"
            price = _det_value(r, "공모가")
            summary = f"공모가 {price}원" if price else ""
        elif typ == TYPE_RELISTING:
            category = "IPO/공모"
            title = f"{company} 재상장"
            shares = _det_value(r, "최초상장주식수")
            summary = f"상장주식수 {shares}주" if shares else ""
        elif typ == TYPE_IR_EARNINGS:
            category = "한국실적"
            title = f"{company} 실적발표"
        else:  # TYPE_IR_MGMT
            category = "IR"
            title = f"{company} IR (경영현황)"

        if not summary and typ in (TYPE_IR_EARNINGS, TYPE_IR_MGMT):
            # IR 상세 필드 구조 미확인(현재 0건) → 값 있는 DET 항목만 이어붙임
            det = []
            for i in range(1, 16):
                v = str(r.get(f"DET_DATA{i}") or "").strip()
                if v and not v.endswith(":"):
                    det.append(v)
            summary = " · ".join(det)[:150]

        ev = {
            "date": ev_date,
            "time": "",
            "category": category,
            "title": title,
            "source": "fnguide",
            "auto": True,
            "_type": typ,
            "_cmp": cmp_cd,
            "_period": period_key,
            "_corrected": corrected,
        }
        if summary:
            ev["summary"] = summary
        events.append(ev)
    return events


def _dedupe_prelim(events: list[dict]) -> list[dict]:
    """같은 기업·같은 분기 잠정실적 중복 제거.
    최초 발표만 유지 (예: DL 8/3 연결 → 8/14 개별 재공시 제거). [정정] 공시는 별도 이벤트로 유지
    (삼성전자 7/7 잠정 → 7/30 [정정]=실적 확정/컨콜일).
    """
    events = sorted(events, key=lambda e: e["date"])
    seen = set()
    out = []
    for ev in events:
        if ev["_type"] == TYPE_PRELIM and ev["_period"] and not ev["_corrected"]:
            key = (ev["_cmp"], ev["_period"])
            if key in seen:
                continue
            seen.add(key)
        out.append(ev)
    return out


def _strip_internal(events: list[dict]) -> list[dict]:
    return [{k: v for k, v in ev.items() if not k.startswith("_")} for ev in events]


# ───────────────────────── 공개 API ─────────────────────────

def fetch_fnguide_month(year: int, month: int) -> list[dict]:
    """FnGuide 한 달 캘린더 수집 → [{"date","time","category","title","source","auto"[,"summary"]}]"""
    raw = _fetch_month_raw(year, month)
    if raw is None:
        LAST_FAILED_MONTHS.append(f"{year}{month:02d}")
        return []
    return _strip_internal(_dedupe_prelim(raw))


def fetch_fnguide_range(from_date: datetime.date, to_date: datetime.date) -> list[dict]:
    """날짜 범위의 FnGuide 데이터 수집 (월 경계 자동 처리).
    잠정실적 중복 판정을 위해 시작월의 전월도 조회하되 결과는 범위 내만 반환."""
    LAST_FAILED_MONTHS.clear()
    first = from_date.replace(day=1)
    current = (first - datetime.timedelta(days=1)).replace(day=1)  # 중복 판정용 전월

    raw_all = []
    while current <= to_date:
        raw = _fetch_month_raw(current.year, current.month)
        if raw is None:
            LAST_FAILED_MONTHS.append(f"{current.year}{current.month:02d}")
        else:
            raw_all.extend(raw)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if LAST_FAILED_MONTHS:
        print(f"[FnGuide] ERROR: 조회 실패 월 {LAST_FAILED_MONTHS}")

    fr, to = from_date.isoformat(), to_date.isoformat()
    deduped = _dedupe_prelim(raw_all)
    return _strip_internal([ev for ev in deduped if fr <= ev["date"] <= to])
