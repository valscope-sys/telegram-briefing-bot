// === CONFIG ===
const CAT_COLORS = {
    "한국실적":"var(--cat-kr)","한국실적(잠정)":"var(--cat-kr-prov)",
    "미국실적":"var(--cat-us)","경제지표":"var(--cat-econ)",
    "통화정책":"var(--cat-monetary)",
    "IPO/공모":"var(--cat-ipo)","기업이벤트":"var(--cat-corp)","IR":"var(--cat-ir)",
    "정치/외교":"var(--cat-politics)","산업컨퍼런스":"var(--cat-conf)",
    "게임":"var(--cat-game)","반도체":"var(--cat-semi)",
    "자동차/배터리":"var(--cat-auto)","제약/바이오":"var(--cat-pharma)",
    "에너지":"var(--cat-energy)","방산":"var(--cat-defense)",
    "전시/박람회":"var(--cat-expo)","K-콘텐츠":"var(--cat-kcontent)",
    "부동산":"var(--cat-realestate)","만기일":"var(--cat-expiry)",
    "수동":"var(--cat-manual)",
};
const CAT_LABELS = {
    "한국실적":"실적(정식)","한국실적(잠정)":"실적(잠정)",
    "미국실적":"미국 실적","경제지표":"경제지표","통화정책":"통화정책",
    "IPO/공모":"IPO/공모","기업이벤트":"기업이벤트","IR":"IR",
    "정치/외교":"정치/외교","산업컨퍼런스":"산업컨퍼런스",
    "게임":"게임","반도체":"반도체","자동차/배터리":"자동차/배터리",
    "제약/바이오":"제약/바이오","에너지":"에너지","방산":"방산",
    "전시/박람회":"전시/박람회","K-콘텐츠":"K-콘텐츠",
    "부동산":"부동산","만기일":"만기일","수동":"기타",
};
const DAYS_KR = ["일","월","화","수","목","금","토"];
// SHA-256 hash of admin password (change this)
const ADMIN_HASH = "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3"; // "123"

// === THEME ===
const THEMES = ["dark","light","blue","green"];
const THEME_NAMES = {"dark":"다크","light":"라이트","blue":"블루","green":"그린"};
function initTheme() {
    const saved = localStorage.getItem("calendar_theme") || "dark";
    setTheme(saved);
}
function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("calendar_theme", theme);
    const btn = document.getElementById("theme-btn");
    if (btn) btn.textContent = THEME_NAMES[theme] || theme;
}
function cycleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const idx = THEMES.indexOf(current);
    const next = THEMES[(idx + 1) % THEMES.length];
    setTheme(next);
}

// === STATE ===
let events = [];
let currentView = "month"; // month | week | day
let viewDate = new Date(); // current focused date
let selectedDate = null;
let enabledCats = new Set(Object.keys(CAT_COLORS));
let isAdmin = false;
let editingEvent = null;

// === INIT ===
async function init() {
    initTheme();
    try {
        const res = await fetch("calendar.json?" + Date.now());
        events = await res.json();
    } catch { events = []; }
    renderMiniCal();
    renderCatFilter();
    renderView();
    bindEvents();
}

// === UTILS ===
function fmt(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; }
function toDate(s) { const p=s.split("-"); return new Date(+p[0],+p[1]-1,+p[2]); }
function sameDay(a,b) { return a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate(); }
function isToday(d) { return sameDay(d, new Date()); }
function eventsOn(dateStr) {
    return events.filter(e => {
        if (!enabledCats.has(e.category)) return false;
        if (e.undated) return false; // undated events shown in banner
        if (e.endDate) {
            return dateStr >= e.date && dateStr <= e.endDate;
        }
        return e.date === dateStr;
    });
}
function catColor(cat) { return CAT_COLORS[cat] || "var(--dim)"; }

// === MINI CALENDAR ===
function renderMiniCal() {
    const el = document.getElementById("mini-cal");
    const y = viewDate.getFullYear(), m = viewDate.getMonth();
    const first = new Date(y, m, 1), last = new Date(y, m+1, 0);
    const startDow = first.getDay(), days = last.getDate();
    const prevLast = new Date(y, m, 0).getDate();

    let html = `<div class="mini-cal-header">
        <button class="mini-cal-nav" onclick="miniNav(-1)">&lt;</button>
        <span class="mini-cal-title">${y}년 ${m+1}월</span>
        <button class="mini-cal-nav" onclick="miniNav(1)">&gt;</button>
    </div><div class="mini-cal-grid">`;
    for (const d of DAYS_KR) html += `<div class="mini-cal-hdr">${d}</div>`;

    for (let i=startDow-1; i>=0; i--) {
        html += `<div class="mini-cal-day">${prevLast-i}</div>`;
    }
    for (let d=1; d<=days; d++) {
        const dt = new Date(y, m, d);
        const ds = fmt(dt);
        const cls = ["mini-cal-day","current-month"];
        if (isToday(dt)) cls.push("today");
        if (selectedDate && sameDay(dt, selectedDate)) cls.push("selected");
        if (eventsOn(ds).length > 0) cls.push("has-event");
        html += `<div class="${cls.join(" ")}" onclick="miniClick(${y},${m},${d})">${d}</div>`;
    }
    const total = startDow + days;
    for (let i=1; i<=(42-total); i++) {
        html += `<div class="mini-cal-day">${i}</div>`;
    }
    html += `</div>`;
    el.innerHTML = html;
}
function miniNav(delta) {
    viewDate.setMonth(viewDate.getMonth() + delta);
    renderMiniCal();
    if (currentView === "month") renderView();
}
function miniClick(y,m,d) {
    selectedDate = new Date(y,m,d);
    viewDate = new Date(y,m,d);
    if (currentView === "month") {
        renderMiniCal();
        showDetailPanel(fmt(selectedDate));
    } else {
        currentView = "day";
        updateViewTabs();
        renderView();
    }
}

// === CATEGORY FILTER ===
function renderCatFilter() {
    const el = document.getElementById("cat-filter");
    const usedCats = new Set(events.map(e => e.category));
    const allOn = [...usedCats].every(c => enabledCats.has(c));
    let html = `<div class="cat-header"><h3>카테고리</h3>
        <button class="cat-toggle-btn" onclick="toggleAllCats()">${allOn ? "전체 해제" : "전체 선택"}</button></div>`;
    for (const [cat, label] of Object.entries(CAT_LABELS)) {
        if (!usedCats.has(cat)) continue;
        const on = enabledCats.has(cat);
        html += `<div class="cat-item${on?"":" disabled"}" onclick="toggleCat('${cat}')">
            <span class="cat-dot" style="background:${catColor(cat)}"></span>
            <span class="cat-label">${label}</span>
        </div>`;
    }
    el.innerHTML = html;
}
function toggleCat(cat) {
    if (enabledCats.has(cat)) enabledCats.delete(cat);
    else enabledCats.add(cat);
    renderCatFilter();
    renderView();
    renderMiniCal();
}
function toggleAllCats() {
    const usedCats = new Set(events.map(e => e.category));
    const allOn = [...usedCats].every(c => enabledCats.has(c));
    if (allOn) enabledCats.clear();
    else for (const c of usedCats) enabledCats.add(c);
    renderCatFilter();
    renderView();
    renderMiniCal();
}

// === VIEW RENDERING ===
function renderView() {
    document.getElementById("month-view").classList.toggle("hidden", currentView!=="month");
    document.getElementById("week-view").classList.toggle("hidden", currentView!=="week");
    document.getElementById("day-view").classList.toggle("hidden", currentView!=="day");

    if (currentView === "month") renderMonth();
    else if (currentView === "week") renderWeek();
    else renderDay();
    updateTitle();
}

function updateTitle() {
    const y = viewDate.getFullYear(), m = viewDate.getMonth(), d = viewDate.getDate();
    const el = document.getElementById("title-text");
    if (currentView === "month") el.textContent = `${y}년 ${m+1}월`;
    else if (currentView === "week") {
        const start = getWeekStart(viewDate);
        const end = new Date(start); end.setDate(end.getDate()+6);
        el.textContent = `${start.getMonth()+1}/${start.getDate()} ~ ${end.getMonth()+1}/${end.getDate()}`;
    } else {
        el.textContent = `${y}년 ${m+1}월 ${d}일 (${DAYS_KR[viewDate.getDay()]})`;
    }
}

// === UNDATED BANNER ===
function renderUndatedBanner() {
    let banner = document.getElementById("undated-banner");
    if (!banner) {
        banner = document.createElement("div");
        banner.id = "undated-banner";
        banner.className = "undated-banner";
        const monthView = document.getElementById("month-view");
        monthView.insertBefore(banner, monthView.firstChild);
    }
    const y = viewDate.getFullYear(), m = viewDate.getMonth();
    const monthStr = `${y}-${String(m+1).padStart(2,"0")}`;

    // 월간 미확정
    const monthUndated = events.filter(e => e.undated && e.month === monthStr && enabledCats.has(e.category));
    // 주간 미확정 (해당 월에 속하는 것)
    const weekUndated = events.filter(e => e.undated && e.week && e.week.startsWith(monthStr) && enabledCats.has(e.category));

    if (monthUndated.length === 0 && weekUndated.length === 0) { banner.style.display = "none"; return; }
    banner.style.display = "flex";
    let html = "";

    if (monthUndated.length > 0) {
        html += `<span class="undated-banner-label">${m+1}월 중</span>`;
        for (const ev of monthUndated) {
            html += `<span class="undated-chip" style="border-color:${catColor(ev.category)};color:${catColor(ev.category)}">${ev.title}</span>`;
        }
    }
    if (weekUndated.length > 0) {
        for (const ev of weekUndated) {
            const wn = ev.week.split("W")[1];
            html += `<span class="undated-banner-label">${m+1}월 ${wn}주차</span>`;
            html += `<span class="undated-chip" style="border-color:${catColor(ev.category)};color:${catColor(ev.category)}">${ev.title}</span>`;
        }
    }
    banner.innerHTML = html;
}

// === MONTH VIEW ===
function renderMonth() {
    renderUndatedBanner();
    const grid = document.getElementById("month-grid");
    const y = viewDate.getFullYear(), m = viewDate.getMonth();
    const first = new Date(y, m, 1), last = new Date(y, m+1, 0);
    const startDow = first.getDay(), daysInMonth = last.getDate();
    const prevLast = new Date(y, m, 0).getDate();

    // Calculate rows needed
    const totalCells = startDow + daysInMonth;
    const rows = Math.ceil(totalCells / 7);
    grid.style.gridTemplateRows = `repeat(${rows}, 1fr)`;

    let html = "";
    const MAX_EVENTS = rows <= 5 ? 3 : 2;

    // Previous month
    for (let i = startDow-1; i>=0; i--) {
        html += `<div class="month-cell other"><div class="day-num">${prevLast-i}</div></div>`;
    }
    // Current month
    for (let d=1; d<=daysInMonth; d++) {
        const dt = new Date(y,m,d);
        const ds = fmt(dt);
        const cls = ["month-cell"];
        if (isToday(dt)) cls.push("today");
        const dayEvents = eventsOn(ds);

        html += `<div class="${cls.join(" ")}" onclick="cellClick('${ds}')">`;
        html += `<div class="day-num">${d}</div>`;

        for (let i=0; i<Math.min(dayEvents.length, MAX_EVENTS); i++) {
            const ev = dayEvents[i];
            let barCls = "event-bar";
            if (ev.endDate && ev.date !== ev.endDate) {
                if (ds === ev.date) barCls += " range-start";
                else if (ds === ev.endDate) barCls += " range-end";
                else barCls += " range-mid";
            }
            html += `<div class="${barCls}" style="background:${catColor(ev.category)}" title="${ev.title}">${ev.title}</div>`;
        }
        if (dayEvents.length > MAX_EVENTS) {
            html += `<div class="more-events">+${dayEvents.length - MAX_EVENTS}건 더</div>`;
        }
        html += `</div>`;
    }
    // Next month padding
    const remaining = (7 - ((startDow + daysInMonth) % 7)) % 7;
    for (let i=1; i<=remaining; i++) {
        html += `<div class="month-cell other"><div class="day-num">${i}</div></div>`;
    }
    grid.innerHTML = html;
}

function cellClick(dateStr) {
    selectedDate = toDate(dateStr);
    renderMiniCal();
    showDetailPanel(dateStr);
}

// === WEEK VIEW ===
function getWeekStart(d) {
    const dt = new Date(d);
    dt.setDate(dt.getDate() - dt.getDay());
    return dt;
}
function renderWeek() {
    const start = getWeekStart(viewDate);
    const el = document.getElementById("week-content");
    let html = "";

    // Collect all events for the week
    const weekEvents = [];
    for (let i=0; i<7; i++) {
        const dt = new Date(start);
        dt.setDate(dt.getDate()+i);
        const ds = fmt(dt);
        const dayEvs = eventsOn(ds);
        for (const ev of dayEvs) {
            weekEvents.push({...ev, _day: i, _date: ds, _dt: dt});
        }
    }

    // Header
    html += `<div class="week-header"><div class="week-header-cell"></div>`;
    for (let i=0; i<7; i++) {
        const dt = new Date(start); dt.setDate(dt.getDate()+i);
        const todayCls = isToday(dt) ? " today" : "";
        html += `<div class="week-header-cell${todayCls}">
            <div class="wk-day">${DAYS_KR[dt.getDay()]}</div>
            <div class="wk-num">${dt.getDate()}</div>
        </div>`;
    }
    html += `</div>`;

    // Events list by day
    html += `<div class="week-events-list">`;
    for (let i=0; i<7; i++) {
        const dt = new Date(start); dt.setDate(dt.getDate()+i);
        const ds = fmt(dt);
        const dayEvs = eventsOn(ds);
        if (dayEvs.length === 0) continue;

        html += `<div style="font-size:0.75rem;font-weight:600;padding:8px 8px 4px;color:var(--dim);margin-top:8px;">${dt.getMonth()+1}/${dt.getDate()} ${DAYS_KR[dt.getDay()]}</div>`;
        for (const ev of dayEvs) {
            html += `<div class="week-event-row" onclick="dayClick('${ds}')">
                <div class="week-event-time">${ev.time || "종일"}</div>
                <div class="week-event-dot" style="background:${catColor(ev.category)}"></div>
                <div class="week-event-info">
                    <div class="week-event-title">${ev.title}</div>
                    <div class="week-event-meta">${CAT_LABELS[ev.category]||ev.category}${ev.endDate ? " ("+ev.date+" ~ "+ev.endDate+")" : ""}</div>
                </div>
            </div>`;
        }
    }
    if (weekEvents.length === 0) {
        html += `<div style="text-align:center;color:var(--dim);padding:40px;">이 주에 일정이 없습니다</div>`;
    }
    html += `</div>`;
    el.innerHTML = html;
}

// === DAY VIEW ===
function renderDay() {
    const el = document.getElementById("day-content");
    const ds = fmt(viewDate);
    const dayEvs = eventsOn(ds);

    let html = `<div class="day-date-header">${viewDate.getMonth()+1}월 ${viewDate.getDate()}일</div>`;
    html += `<div class="day-date-sub">${viewDate.getFullYear()}년 ${DAYS_KR[viewDate.getDay()]}요일</div>`;

    if (dayEvs.length === 0) {
        html += `<div class="day-no-events">일정이 없습니다</div>`;
    } else {
        dayEvs.sort((a,b) => (a.time||"99").localeCompare(b.time||"99"));
        for (const ev of dayEvs) {
            html += `<div class="day-event-card" style="border-left-color:${catColor(ev.category)}" onclick="showEventDetail(${JSON.stringify(ev).replace(/"/g,'&quot;')})">
                <div class="day-event-card-body">
                    <div class="day-event-card-title">${ev.title}</div>
                    <div class="day-event-card-meta">${ev.time || "종일"} · ${CAT_LABELS[ev.category]||ev.category}${ev.endDate ? " · "+ev.date+" ~ "+ev.endDate : ""}</div>
                    ${ev.summary ? `<div class="day-event-card-summary">${ev.summary}</div>` : ""}
                    ${ev.link ? `<a class="day-event-card-link" href="${ev.link}" target="_blank" onclick="event.stopPropagation()">상세 보기 &rarr;</a>` : ""}
                </div>
            </div>`;
        }
    }

    if (isAdmin) {
        html += `<button class="btn-primary" style="margin-top:16px" onclick="openAddEvent('${ds}')">+ 일정 추가</button>`;
    }
    el.innerHTML = html;
}

function dayClick(ds) {
    viewDate = toDate(ds);
    selectedDate = toDate(ds);
    currentView = "day";
    updateViewTabs();
    renderView();
    renderMiniCal();
}

// === DETAIL PANEL ===
function showDetailPanel(dateStr) {
    const panel = document.getElementById("detail-panel");
    const dayEvs = eventsOn(dateStr);
    const dt = toDate(dateStr);

    document.getElementById("detail-title").textContent = `${dt.getMonth()+1}월 ${dt.getDate()}일 ${DAYS_KR[dt.getDay()]}`;
    let html = "";
    if (dayEvs.length === 0) {
        html = `<div style="color:var(--dim);padding:20px 16px;text-align:center;font-size:0.85rem;">일정 없음</div>`;
    } else {
        dayEvs.sort((a,b)=>(a.time||"99").localeCompare(b.time||"99"));
        for (const ev of dayEvs) {
            html += `<div class="detail-event" onclick="dayClick('${dateStr}')">
                <div class="detail-event-title">
                    <span class="detail-event-dot" style="background:${catColor(ev.category)}"></span>
                    ${ev.title}
                </div>
                <div class="detail-event-meta">${ev.time || "종일"} · ${CAT_LABELS[ev.category]||ev.category}</div>
                ${ev.summary ? `<div class="detail-event-summary">${ev.summary}</div>` : ""}
                ${ev.link ? `<a class="detail-event-link" href="${ev.link}" target="_blank" onclick="event.stopPropagation()">링크 &rarr;</a>` : ""}
            </div>`;
        }
    }
    if (isAdmin) {
        html += `<div style="padding:12px 16px"><button class="btn-primary" style="width:100%" onclick="openAddEvent('${dateStr}')">+ 일정 추가</button></div>`;
    }
    document.getElementById("detail-body").innerHTML = html;
    panel.classList.remove("hidden");
}

function closeDetail() { document.getElementById("detail-panel").classList.add("hidden"); }

// === NAVIGATION ===
function navigate(delta) {
    if (currentView === "month") viewDate.setMonth(viewDate.getMonth()+delta);
    else if (currentView === "week") viewDate.setDate(viewDate.getDate()+delta*7);
    else viewDate.setDate(viewDate.getDate()+delta);
    renderMiniCal();
    renderView();
}
function goToday() {
    viewDate = new Date();
    selectedDate = new Date();
    renderMiniCal();
    renderView();
}
function switchView(v) {
    currentView = v;
    updateViewTabs();
    closeDetail();
    renderView();
}
function updateViewTabs() {
    document.querySelectorAll(".view-tab").forEach(t => {
        t.classList.toggle("active", t.dataset.view === currentView);
    });
}

// === ADMIN ===
async function sha256(text) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,"0")).join("");
}
function openAdminModal() {
    document.getElementById("admin-overlay").classList.remove("hidden");
    if (isAdmin) {
        document.getElementById("modal-title").textContent = "일정 추가";
        document.getElementById("login-form").classList.add("hidden");
        document.getElementById("event-form").classList.remove("hidden");
        resetEventForm();
    } else {
        document.getElementById("modal-title").textContent = "관리자 로그인";
        document.getElementById("login-form").classList.remove("hidden");
        document.getElementById("event-form").classList.add("hidden");
        document.getElementById("admin-pw").value = "";
        setTimeout(() => document.getElementById("admin-pw").focus(), 100);
    }
}
function closeModal() {
    document.getElementById("admin-overlay").classList.add("hidden");
    editingEvent = null;
}
async function doLogin() {
    const pw = document.getElementById("admin-pw").value;
    const hash = await sha256(pw);
    if (hash === ADMIN_HASH) {
        isAdmin = true;
        document.getElementById("admin-btn").textContent = "+";
        document.getElementById("admin-btn").title = "일정 추가";
        closeModal();
        renderView();
    } else {
        document.getElementById("admin-pw").style.borderColor = "var(--cat-us)";
        document.getElementById("admin-pw").value = "";
        document.getElementById("admin-pw").placeholder = "비밀번호가 틀렸습니다";
    }
}
function openAddEvent(dateStr) {
    if (!isAdmin) { openAdminModal(); return; }
    editingEvent = null;
    document.getElementById("admin-overlay").classList.remove("hidden");
    document.getElementById("modal-title").textContent = "일정 추가";
    document.getElementById("login-form").classList.add("hidden");
    document.getElementById("event-form").classList.remove("hidden");
    document.getElementById("ev-delete").classList.add("hidden");
    resetEventForm();
    if (dateStr) document.getElementById("ev-date").value = dateStr;
}
function openEditEvent(ev) {
    if (!isAdmin) return;
    editingEvent = ev;
    document.getElementById("admin-overlay").classList.remove("hidden");
    document.getElementById("modal-title").textContent = "일정 수정";
    document.getElementById("login-form").classList.add("hidden");
    document.getElementById("event-form").classList.remove("hidden");
    document.getElementById("ev-delete").classList.remove("hidden");
    document.getElementById("ev-title").value = ev.title || "";
    document.getElementById("ev-category").value = ev.category || "수동";
    document.getElementById("ev-date").value = ev.date || "";
    document.getElementById("ev-end-date").value = ev.endDate || "";
    document.getElementById("ev-time").value = ev.time || "";
    document.getElementById("ev-link").value = ev.link || "";
    document.getElementById("ev-summary").value = ev.summary || "";
}
function resetEventForm() {
    ["ev-title","ev-date","ev-end-date","ev-time","ev-link","ev-summary"].forEach(id => {
        document.getElementById(id).value = "";
    });
    document.getElementById("ev-category").value = "수동";
}
function saveEvent() {
    const title = document.getElementById("ev-title").value.trim();
    const date = document.getElementById("ev-date").value;
    if (!title || !date) { alert("제목과 날짜는 필수입니다"); return; }

    const ev = {
        date,
        time: document.getElementById("ev-time").value || "",
        category: document.getElementById("ev-category").value,
        title,
        source: "manual",
        auto: false,
    };
    const endDate = document.getElementById("ev-end-date").value;
    if (endDate) ev.endDate = endDate;
    const link = document.getElementById("ev-link").value.trim();
    if (link) ev.link = link;
    const summary = document.getElementById("ev-summary").value.trim();
    if (summary) ev.summary = summary;

    if (editingEvent) {
        const idx = events.findIndex(e => e.date===editingEvent.date && e.title===editingEvent.title && e.category===editingEvent.category);
        if (idx >= 0) events[idx] = ev;
    } else {
        events.push(ev);
    }

    events.sort((a,b) => (a.date+a.time).localeCompare(b.date+b.time));
    saveToStorage();
    closeModal();
    renderView();
    renderMiniCal();
    renderCatFilter();
}
function deleteEvent() {
    if (!editingEvent || !confirm("이 일정을 삭제하시겠습니까?")) return;
    events = events.filter(e => !(e.date===editingEvent.date && e.title===editingEvent.title && e.category===editingEvent.category));
    saveToStorage();
    closeModal();
    renderView();
    renderMiniCal();
    renderCatFilter();
}
function saveToStorage() {
    localStorage.setItem("calendar_events_manual", JSON.stringify(events.filter(e=>e.source==="manual")));
}
function loadManualEvents() {
    try {
        const manual = JSON.parse(localStorage.getItem("calendar_events_manual") || "[]");
        for (const m of manual) {
            if (!events.find(e => e.date===m.date && e.title===m.title)) {
                events.push(m);
            }
        }
        events.sort((a,b) => (a.date+(a.time||"")).localeCompare(b.date+(b.time||"")));
    } catch {}
}
function showEventDetail(ev) {
    if (isAdmin) openEditEvent(ev);
}

// === BIND EVENTS ===
function bindEvents() {
    document.getElementById("prev-btn").onclick = () => navigate(-1);
    document.getElementById("next-btn").onclick = () => navigate(1);
    document.getElementById("today-btn").onclick = goToday;
    document.getElementById("theme-btn").onclick = cycleTheme;
    document.querySelectorAll(".view-tab").forEach(t => {
        t.onclick = () => switchView(t.dataset.view);
    });
    document.getElementById("detail-close").onclick = closeDetail;
    document.getElementById("admin-btn").onclick = () => {
        if (isAdmin) openAddEvent(selectedDate ? fmt(selectedDate) : fmt(new Date()));
        else openAdminModal();
    };
    document.getElementById("modal-close").onclick = closeModal;
    document.getElementById("admin-overlay").onclick = (e) => { if(e.target===e.currentTarget) closeModal(); };
    document.getElementById("login-btn").onclick = doLogin;
    document.getElementById("admin-pw").onkeydown = (e) => { if(e.key==="Enter") doLogin(); };
    document.getElementById("ev-save").onclick = saveEvent;
    document.getElementById("ev-delete").onclick = deleteEvent;
    document.getElementById("ev-cancel").onclick = closeModal;

    document.onkeydown = (e) => {
        if (e.key==="Escape") { closeModal(); closeDetail(); }
        if (e.target.tagName==="INPUT"||e.target.tagName==="TEXTAREA"||e.target.tagName==="SELECT") return;
        if (e.key==="ArrowLeft") navigate(-1);
        if (e.key==="ArrowRight") navigate(1);
    };
}

// === START ===
init().then(() => {
    loadManualEvents();
    renderView();
    renderMiniCal();
    renderCatFilter();
});
