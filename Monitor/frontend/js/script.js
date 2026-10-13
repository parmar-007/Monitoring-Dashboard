// ============================================
// Extract Monitor - dashboard script
// Served by the same FastAPI app, so API calls are same-origin.
// State lives in the URL hash (#date=...&job=...) so views can be shared.
// ============================================

const REFRESH_MS = 60_000;

const STATUS = {
    FAILED:  { label: "Failed",      icon: "x",     rank: 0 },
    STUCK:   { label: "Stuck",       icon: "clock", rank: 1 },
    MISSING: { label: "Missing",     icon: "alert", rank: 2 },
    UNKNOWN: { label: "Unknown",     icon: "question", rank: 3 },
    RUNNING: { label: "Running",     icon: "play",  rank: 4 },
    PENDING: { label: "Pending",     icon: "dots",  rank: 5 },
    SUCCESS: { label: "Succeeded",   icon: "check", rank: 6 },
    NO_RUN:  { label: "Not scheduled", icon: "dash", rank: 7 },
};

const PROBLEMS = ["FAILED", "STUCK", "MISSING", "UNKNOWN"];

const ICON_PATHS = {
    check: '<path d="M3.5 8.5l3 3 6-7"/>',
    x:     '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
    alert: '<path d="M8 3.5v5.5M8 12v.5"/>',
    question: '<path d="M5.8 6a2.3 2.3 0 1 1 3.2 2.1c-.6.3-1 .8-1 1.4v.3M8 12.5v.01"/>',
    clock: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2 1.3"/>',
    play:  '<path d="M5.5 4l6 4-6 4z" fill="currentColor"/>',
    dots:  '<path d="M4 8h.01M8 8h.01M12 8h.01" stroke-width="2.6"/>',
    dash:  '<path d="M4.5 8h7"/>',
};

const state = {
    overview: null,
    date: null,         // selected day (YYYY-MM-DD)
    job: null,          // job open in the drawer
    detail: null,
    attempt: null,      // index into detail.runs
    search: "",
    problemsOnly: false,
};

const $ = (id) => document.getElementById(id);


// ============================================
// Small DOM helpers (no innerHTML with data - file contents are untrusted)
// ============================================

function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") node.className = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : String(child));
    }
    return node;
}

function icon(name) {
    const wrap = document.createElement("span");
    wrap.innerHTML =
        `<svg class="sicon" viewBox="0 0 16 16" fill="none" stroke="currentColor" ` +
        `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
        `${ICON_PATHS[name]}</svg>`;
    return wrap.firstChild;
}

function statusPill(status) {
    const meta = STATUS[status] || STATUS.UNKNOWN;
    return el("span", { class: `pill status-${status}` }, icon(meta.icon), meta.label);
}


// ============================================
// Formatting
// ============================================

// Times are shown as written in the status file (the jobs' STATUS_TZ),
// not converted to the browser's timezone.
function clockTime(iso) {
    return iso ? iso.slice(11, 16) : "–";
}

function dateTime(iso) {
    return iso ? `${iso.slice(0, 10)} ${iso.slice(11, 19)}` : "–";
}

function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return "–";
    seconds = Math.round(seconds);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
}

function formatNumber(n) {
    return n === null || n === undefined || n === "" ? "–" : Number(n).toLocaleString();
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return "–";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function elapsedSince(iso) {
    return iso ? (Date.now() - new Date(iso).getTime()) / 1000 : null;
}

function durationText(cell) {
    if (cell.status === "STUCK") return "never finished";
    if (cell.status === "RUNNING") {
        return `${formatDuration(elapsedSince(cell.started_at))} so far`;
    }
    return formatDuration(cell.duration_seconds);
}

function dayLabel(iso, today) {
    const d = new Date(`${iso}T12:00:00`);
    const diff = Math.round((new Date(`${today}T12:00:00`) - d) / 86_400_000);
    const name = diff === 0 ? "Today" : diff === 1 ? "Yesterday" :
        d.toLocaleDateString(undefined, { weekday: "long" });
    const short = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    return { name, short };
}


// ============================================
// URL hash state
// ============================================

function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    return { date: params.get("date"), job: params.get("job") };
}

function writeHash() {
    const params = new URLSearchParams();
    if (state.date && state.overview && state.date !== state.overview.today) params.set("date", state.date);
    if (state.job) params.set("job", state.job);
    const hash = params.toString();
    history.replaceState(null, "", hash ? `#${hash}` : location.pathname);
}


// ============================================
// Data
// ============================================

async function getJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText} - ${url}`);
    return response.json();
}

async function loadOverview() {
    try {
        state.overview = await getJSON("api/overview");
        $("errorBanner").hidden = true;
    }
    catch (error) {
        console.error("Error fetching overview:", error);
        $("errorBanner").textContent = `Couldn't load job status: ${error.message}`;
        $("errorBanner").hidden = false;
        return;
    }
    if (!state.date || !state.overview.dates.includes(state.date)) {
        state.date = state.overview.today;
    }
    $("updatedAt").textContent =
        `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` +
        ` · refreshes every minute · times in job timezone`;
    $("historyDays").textContent = state.overview.dates.length;
    render();
}

async function loadDetail() {
    if (!state.job) return;
    const job = state.job, date = state.date;
    try {
        const detail = await getJSON(`api/jobs/${encodeURIComponent(job)}/${date}`);
        if (state.job !== job || state.date !== date) return; // user moved on
        const sameView = state.detail && state.detail.name === job && state.detail.date === date;
        state.detail = detail;
        if (!sameView || state.attempt === null || state.attempt >= detail.runs.length) {
            state.attempt = detail.runs.length - 1;
        }
        renderDrawer();
    }
    catch (error) {
        console.error("Error fetching job detail:", error);
        $("drawerBody").replaceChildren(el("div", { class: "error-box" }, `Couldn't load details: ${error.message}`));
    }
}


// ============================================
// Render: day picker, tiles, legend, table
// ============================================

function render() {
    renderDayPicker();
    renderTiles();
    renderTable();
}

function renderDayPicker() {
    const { dates, today, summary } = state.overview;
    const chips = dates.map((iso) => {
        const label = dayLabel(iso, today);
        const counts = summary[iso];
        const scheduled = Object.entries(counts)
            .filter(([k]) => k !== "problems" && k !== "NO_RUN")
            .reduce((n, [, v]) => n + v, 0);
        const badge = counts.problems
            ? el("span", { class: "day-badge status-FAILED" }, icon("x"), `${counts.problems} issue${counts.problems > 1 ? "s" : ""}`)
            : scheduled === 0
                ? el("span", { class: "day-badge status-NO_RUN" }, icon("dash"), "Nothing scheduled")
                : el("span", { class: "day-badge status-SUCCESS" }, icon("check"), "No issues");
        return el("button", {
            type: "button",
            class: "day-chip",
            "aria-pressed": String(iso === state.date),
            onclick: () => selectDate(iso),
        },
            el("span", { class: "day-name" }, label.name),
            el("span", { class: "day-date" }, label.short),
            badge,
        );
    });
    $("dayPicker").replaceChildren(...chips);
}

function renderTiles() {
    const c = state.overview.summary[state.date];
    const problems = c.problems || 0;
    const scheduled = state.overview.jobs.length - (c.NO_RUN || 0);
    const breakdown = PROBLEMS.filter((s) => c[s]).map((s) => `${c[s]} ${STATUS[s].label.toLowerCase()}`).join(" · ");

    const tile = (cls, status, label, value, sub) => el("div", { class: `tile ${cls}` },
        el("div", { class: `tile-label status-${status}` }, icon(STATUS[status].icon), label),
        el("div", { class: "tile-value" }, value),
        el("div", { class: "tile-sub" }, sub),
    );

    $("tiles").replaceChildren(
        tile(`attention${problems ? " has-problems" : ""}`, problems ? "FAILED" : "SUCCESS",
            "Needs attention", problems, problems ? breakdown : "Nothing failed or missing"),
        tile("", "SUCCESS", "Succeeded", c.SUCCESS || 0, `of ${scheduled} scheduled`),
        tile("", "RUNNING", "Running", c.RUNNING || 0, "in progress now"),
        tile("", "PENDING", "Pending", c.PENDING || 0, "not due yet"),
    );
}

function renderLegend() {
    $("legend").replaceChildren(...Object.entries(STATUS).map(([status, meta]) =>
        el("span", { class: `status-${status}` }, icon(meta.icon), meta.label)));
}

function visibleJobs() {
    const q = state.search.trim().toLowerCase();
    return state.overview.jobs
        .filter((job) => !q || job.name.toLowerCase().includes(q) || (job.description || "").toLowerCase().includes(q))
        .filter((job) => !state.problemsOnly || PROBLEMS.includes(job.days[state.date].status))
        .sort((a, b) =>
            STATUS[a.days[state.date].status].rank - STATUS[b.days[state.date].status].rank ||
            a.name.localeCompare(b.name));
}

function renderTable() {
    const jobs = visibleJobs();
    const oldestFirst = [...state.overview.dates].reverse();

    const rows = jobs.map((job) => {
        const cell = job.days[state.date];
        const note = cell.error_message || cell.note;

        const history = el("div", { class: "history" }, oldestFirst.map((iso) => {
            const day = job.days[iso];
            const meta = STATUS[day.status] || STATUS.UNKNOWN;
            const tip = `${dayLabel(iso, state.overview.today).short}: ${meta.label}` +
                (day.attempts > 1 ? ` (${day.attempts} attempts)` : "");
            return el("button", {
                type: "button",
                class: `cell status-${day.status}${iso === state.date ? " selected" : ""}`,
                title: tip,
                "aria-label": `${job.name}, ${tip}`,
                onclick: (event) => { event.stopPropagation(); selectDate(iso); openJob(job.name); },
            }, icon(meta.icon));
        }));

        return el("tr", {
            class: job.name === state.job ? "active" : null,
            tabindex: "0",
            onclick: () => openJob(job.name),
            onkeydown: (event) => { if (event.key === "Enter") openJob(job.name); },
        },
            el("td", {},
                el("div", { class: "job-name" }, job.name,
                    job.registered ? null : el("span", { class: "tag", title: "Not listed in jobs.yaml - missed runs can't be detected" }, "unregistered")),
                job.description ? el("div", { class: "job-desc" }, job.description) : null,
            ),
            el("td", {},
                statusPill(cell.status),
                note ? el("div", { class: "row-note", title: note }, note) : null,
            ),
            el("td", { class: "col-history" }, history),
            el("td", {}, cell.started_at ? clockTime(cell.started_at) :
                el("span", { class: "muted" }, cell.expected_by && cell.status !== "NO_RUN" ? `due ${cell.expected_by}` : "–")),
            el("td", { class: "col-optional" }, durationText(cell)),
            el("td", { class: "num" }, formatNumber(cell.records)),
            el("td", { class: "col-optional" }, cell.output_files && cell.output_files.length
                ? el("div", { class: "output-file", title: cell.output_files.join(", ") }, cell.output_files.join(", "))
                : el("span", { class: "muted" }, "–")),
        );
    });

    $("jobRows").replaceChildren(...rows);
    $("emptyState").hidden = rows.length > 0;
    $("emptyState").textContent = state.problemsOnly && !state.search
        ? "No problems on this day."
        : "No jobs match.";
}


// ============================================
// Drawer: one job, one day, every attempt
// ============================================

function openJob(name) {
    state.job = name;
    state.detail = null;
    state.attempt = null;
    writeHash();
    $("drawerTitle").textContent = name;
    $("drawerSubtitle").textContent = "Loading…";
    $("drawerBody").replaceChildren();
    $("drawer").hidden = false;
    $("scrim").hidden = false;
    renderTable();
    loadDetail();
}

function closeJob() {
    state.job = null;
    state.detail = null;
    writeHash();
    $("drawer").hidden = true;
    $("scrim").hidden = true;
    renderTable();
}

function renderDrawer() {
    const d = state.detail;
    const label = dayLabel(d.date, state.overview.today);
    $("drawerTitle").textContent = d.name;
    const when = ["Today", "Yesterday"].includes(label.name) ? `${label.name}, ${label.short}` : label.short;
    $("drawerSubtitle").textContent = [d.description, when].filter(Boolean).join(" · ");

    const sections = [];
    const run = d.runs[state.attempt];

    // Overall status for the day
    sections.push(el("section", {},
        el("div", {}, statusPill(d.day.status)),
        d.day.note ? el("div", { class: "subtle" }, d.day.note) : null,
    ));

    // Attempt picker when the job ran more than once
    if (d.runs.length > 1) {
        sections.push(el("section", {},
            el("h3", {}, `Attempts (${d.runs.length})`),
            el("div", { class: "attempts" }, d.runs.map((r, i) => {
                const meta = STATUS[r.status] || STATUS.UNKNOWN;
                return el("button", {
                    type: "button",
                    class: `attempt-btn status-${r.status}`,
                    "aria-pressed": String(i === state.attempt),
                    onclick: () => { state.attempt = i; renderDrawer(); },
                }, icon(meta.icon), `#${i + 1} · ${clockTime(r.started_at)} · ${meta.label}`);
            })),
        ));
    }

    if (!run) {
        sections.push(el("section", {},
            el("div", { class: "callout" },
                d.day.status === "NO_RUN"
                    ? `This job isn't scheduled on this day (schedule: ${d.schedule}).`
                    : d.day.status === "PENDING"
                        ? `No run yet. ${d.day.note || ""}`
                        : "No status file was written for this day. Either the CronJob didn't fire, " +
                          "the pod failed before the job started, or the job doesn't use job_status.py yet. " +
                          "Check the CronJob's last schedule time and events in OpenShift."),
        ));
        sections.push(scheduleSection(d));
        $("drawerBody").replaceChildren(...sections);
        return;
    }

    // Error first - it's why you opened this
    if (run.error) {
        sections.push(el("section", {},
            el("h3", {}, "Error"),
            el("div", { class: "error-box" },
                el("strong", {}, run.error.type || "Error"),
                run.error.message || "",
                run.error.traceback
                    ? el("details", {}, el("summary", {}, "Traceback"), el("pre", { class: "log" }, run.error.traceback))
                    : null,
            ),
        ));
    }

    const status = run.status === "RUNNING" && d.day.status === "STUCK" ? "STUCK" : run.status;
    const facts = [
        ["Started", dateTime(run.started_at)],
        ["Finished", dateTime(run.finished_at)],
        ["Duration", durationText({ ...run, status })],
        ["Records", formatNumber(run.records)],
        ["Execution ID", run.execution_id || "–"],
        ["Pod", run.host || "–"],
    ];
    sections.push(el("section", {},
        el("h3", {}, "Run"),
        el("dl", { class: "facts" }, facts.map(([k, v]) => el("div", {}, el("dt", {}, k), el("dd", {}, v)))),
    ));

    // Output files
    if (run.output_files.length) {
        sections.push(el("section", {},
            el("h3", {}, "Output files"),
            el("table", { class: "kv" }, el("tbody", {}, run.output_files.map((f) => {
                const ok = f.exists !== false && f.size_bytes !== 0;
                return el("tr", {},
                    el("td", {}, el("span", { class: `file-row status-${ok ? "SUCCESS" : "FAILED"}` },
                        el("span", { class: "pill status-" + (ok ? "SUCCESS" : "FAILED") }, icon(ok ? "check" : "x"), ok ? "Written" : "Missing"),
                    )),
                    el("td", { title: f.path || "" }, f.name || f.path, el("div", { class: "subtle" }, formatBytes(f.size_bytes))),
                );
            }))),
        ));
    }

    // Free-form metrics (DW table, records sent, ...)
    const metrics = Object.entries(run.metrics || {});
    if (metrics.length) {
        sections.push(el("section", {},
            el("h3", {}, "Details"),
            el("table", { class: "kv" }, el("tbody", {}, metrics.map(([k, v]) =>
                el("tr", {}, el("td", {}, k.replace(/_/g, " ")),
                    el("td", {}, typeof v === "number" ? formatNumber(v) : typeof v === "object" ? JSON.stringify(v) : String(v)))))),
        ));
    }

    // Log tail
    sections.push(el("section", {},
        el("h3", {}, "Log (last lines)"),
        run.log_tail.length
            ? el("pre", { class: "log" }, run.log_tail.map((line) => {
                const level = (line.match(/\b(ERROR|CRITICAL|WARNING)\b/) || [])[1];
                return el("span", { class: level ? `lvl-${level === "CRITICAL" ? "ERROR" : level}` : null }, line + "\n");
            }))
            : el("div", { class: "callout" }, "No log lines captured. Jobs using job_status.py include the last 200 lines here."),
    ));

    sections.push(scheduleSection(d, run.source_file));
    $("drawerBody").replaceChildren(...sections);
}

function scheduleSection(d, sourceFile) {
    const rows = [
        ["Schedule", d.registered ? d.schedule : "not in jobs.yaml"],
        ["Expected by", d.day.expected_by || "end of day"],
        ["Max runtime", `${d.max_runtime_minutes} min`],
    ];
    if (sourceFile) rows.push(["Status file", `${d.name}/${sourceFile}`]);
    return el("section", {},
        el("h3", {}, "Configuration"),
        el("table", { class: "kv" }, el("tbody", {}, rows.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))))),
    );
}


// ============================================
// Events
// ============================================

function selectDate(iso) {
    state.date = iso;
    writeHash();
    render();
    if (state.job) loadDetail();
}

$("refreshBtn").addEventListener("click", () => { loadOverview(); loadDetail(); });
$("searchInput").addEventListener("input", (e) => { state.search = e.target.value; renderTable(); });
$("problemsOnly").addEventListener("change", (e) => { state.problemsOnly = e.target.checked; renderTable(); });
$("drawerClose").addEventListener("click", closeJob);
$("scrim").addEventListener("click", closeJob);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.job) closeJob(); });

window.addEventListener("load", async () => {
    renderLegend();
    const fromHash = readHash();
    state.date = fromHash.date;
    await loadOverview();
    if (fromHash.job && state.overview) openJob(fromHash.job);
    setInterval(() => { loadOverview(); loadDetail(); }, REFRESH_MS);
});
