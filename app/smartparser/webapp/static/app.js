// UC-042 Smart Parser - browser application. Renders ONLY what the backend returns; every action is a POST to the API,
// which forwards to the existing PackageService / review workflow / reconciliation adapter. Untrusted text (file names,
// CSV headers and values, reasons, engine output) is always inserted with textContent, never as HTML.
"use strict";

// ================================================================================================ utilities
const $ = (s, r = document) => r.querySelector(s);
const SVGNS = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
}
const ICONS = {
  overview: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  upload: "M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3",
  process: "M4 6h16M4 12h10M4 18h6m10-6l-3 3m3-3l-3-3",
  files: "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6",
  review: "M4 5h16M4 10h10M4 15h7m6 1.5l2 2 4-4",
  validate: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3zm-3 9l2 2 4-4",
  history: "M12 8v4l3 2m6-2a9 9 0 11-3-6.7M21 4v4h-4",
  resubmit: "M4 4v6h6M20 20v-6h-6M5 15a7 7 0 0012 3l3-2M19 9A7 7 0 007 6L4 8",
  recon: "M4 7h11M4 7l3-3M4 7l3 3M20 17H9m11 0l-3-3m3 3l-3 3",
  results: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  design: "M12 3a9 9 0 100 18c1 0 1.5-.7 1.5-1.5 0-.9-.7-1.2-.7-2 0-.8.7-1.5 1.6-1.5H17a4 4 0 004-4c0-5-4-9-9-9zM7.5 11a1 1 0 110-2 1 1 0 010 2zm3-4a1 1 0 110-2 1 1 0 010 2zm5 0a1 1 0 110-2 1 1 0 010 2z",
  info: "M12 8h.01M11 12h1v5h1M12 21a9 9 0 110-18 9 9 0 010 18z",
  warn: "M12 9v4m0 4h.01M10.3 3.9L2 18a2 2 0 001.7 3h16.6a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12M18 6L6 18",
  inbox: "M4 13h4l2 3h4l2-3h4M5 5h14l1 8v6H4v-6l1-8z",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
};
function icon(name, cls = "ico") {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.8"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("class", cls); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", ICONS[name] || ICONS.info); s.append(p);
  return s;
}
const fmtBytes = n => n == null ? "–" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`;
const fmtNum = n => n == null ? "–" : Number(n).toLocaleString("en-GB");
function fmtTime(iso, withDate = true) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return withDate ? d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : d.toLocaleTimeString("en-GB");
}
const timeEl = (iso, withDate = true) => el("time", { datetime: iso || "", title: iso || "" }, fmtTime(iso, withDate));
const short = (s, n = 12) => s ? (s.length > n ? s.slice(0, n) + "…" : s) : "–";
const hash = s => el("span", { class: "hash", title: s || "" }, short(s, 12));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

// ================================================================================================ status vocabulary
const VERSION_STATUS = {
  VALIDATED: ["ok", "Validated"], ACTIVE: ["ok strong", "Active"], REVIEW_REQUIRED: ["warn", "Review required"],
  RESUBMISSION_REQUIRED: ["bad", "Resubmission required"], FAILED_VALIDATION: ["bad", "Failed validation"],
  REJECTED: ["bad outline", "Rejected"], SUPERSEDED: ["neutral", "Superseded"], RECEIVED: ["info", "Received"],
  MISSING: ["dashed", "Missing"],
};
const PACKAGE_STATUS = {
  RECEIVED: ["neutral", "No evidence yet"], RESUBMISSION_REQUIRED: ["bad", "Resubmission required"],
  REVIEW_REQUIRED: ["warn", "Review required"], INCOMPLETE: ["warn", "Incomplete"],
  READY_FOR_VALIDATION: ["info", "Ready for validation"], RECONCILIATION_READY: ["ok", "Active · reconciliation ready"],
};
const CASE_STATUS = { CLEAN: ["ok", "Clean"], EXCEPTIONS_OPEN: ["bad", "Exceptions open"], EVIDENCE_INCOMPLETE: ["warn", "Evidence incomplete"] };
const SEVERITY = { Critical: "bad", High: "warn", Medium: "info", Low: "neutral" };
const JOB_STATE = { queued: ["neutral", "Queued"], running: ["info", "Running"], completed: ["ok", "Completed"],
  failed: ["bad", "Failed"], interrupted: ["warn", "Interrupted"] };
const STAGE_STATE = { pending: "Pending", running: "Running", completed: "Completed", failed: "Failed",
  requires_review: "Requires review", requires_attention: "Requires attention", blocked: "Activation blocked", not_required: "Not required" };
// one vocabulary for analyst decisions (button "Map" and a recorded APPROVE are the same thing: "Mapped")
const DECISION = { MAP: "Mapped", APPROVE: "Mapped", CHANGE: "Mapped (changed field)", CHOOSE_DUPLICATE_SOURCE: "Chosen as source",
  IGNORE_COLUMN: "Ignored", LEAVE_UNRESOLVED: "Left unresolved", LEAVE_UNMAPPED: "Left unresolved", DETERMINISTIC: "Deterministic",
  REJECT: "Rejected" };
const badge = (cls, text, title) => el("span", { class: `badge ${cls}`, title: title || null }, text);
const vBadge = s => { const [c, t] = VERSION_STATUS[s] || ["neutral", s]; return badge(c, t, s); };
const pBadge = s => { const [c, t] = PACKAGE_STATUS[s] || ["neutral", s]; return badge(c, t, s); };
const cBadge = s => { const [c, t] = CASE_STATUS[s] || ["info", s || "–"]; return badge(c, t, s); };
const sevBadge = s => badge(SEVERITY[s] || "neutral", s);
const jBadge = s => { const [c, t] = JOB_STATE[s] || ["neutral", s]; return badge(c, t); };
const outcomeBadge = o => badge({ PASS: "ok", FAIL: "bad", INSUFFICIENT_EVIDENCE: "warn", NOT_APPLICABLE: "neutral" }[o] || "neutral", o);

// ================================================================================================ API
class ApiFail extends Error { constructor(status, code, message) { super(message); this.status = status; this.code = code; } }
async function api(method, path, body) {
  let res;
  try {
    res = await fetch(`/api/${path}`, { method, headers: { "Content-Type": "application/json", "X-Smartparser-Client": "webapp" },
      body: body ? JSON.stringify(body) : undefined });
  } catch (e) { throw new ApiFail(0, "NETWORK", "the application server is not reachable"); }
  const ct = res.headers.get("Content-Type") || "";
  if (!ct.startsWith("application/json")) {
    if (!res.ok) throw new ApiFail(res.status, "HTTP", res.statusText);
    return res.text();
  }
  const doc = await res.json();
  if (!res.ok) throw new ApiFail(res.status, doc.error, doc.message || res.statusText);
  return doc;
}

// ================================================================================================ toasts + dialogs
function toast(title, msg, kind = "") {
  const t = el("div", { class: `toast ${kind}`, role: kind === "bad" ? "alert" : "status" }, el("b", {}, title), msg ? el("div", { class: "small" }, msg) : null);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 9000 : 5000);
}
function confirmDialog({ title, body, confirmText = "Confirm", danger = false, reasonLabel = null, reasonRequired = false }) {
  return new Promise(resolve => {
    const d = $("#dlg"); d.replaceChildren();
    const reason = reasonLabel ? el("textarea", { id: "dlg-reason", "aria-label": reasonLabel }) : null;
    const ok = el("button", { class: `btn ${danger ? "danger solid" : "primary"}`, id: "dlg-ok" }, confirmText);
    const cancel = el("button", { class: "btn", id: "dlg-cancel" }, "Cancel");
    d.append(el("div", { class: "dlg-head" }, el("h2", {}, title)),
      el("div", { class: "dlg-body" }, body, reason ? el("div", { class: "field" }, el("label", { for: "dlg-reason" }, reasonLabel), reason) : null),
      el("div", { class: "dlg-foot" }, cancel, ok));
    const done = v => { d.close(); resolve(v); };
    cancel.onclick = () => done(null);
    ok.onclick = () => {
      if (reason && reasonRequired && !reason.value.trim()) { reason.focus(); reason.setAttribute("aria-invalid", "true"); return; }
      done({ reason: reason ? reason.value.trim() : null });
    };
    d.addEventListener("cancel", () => resolve(null), { once: true });
    d.showModal(); (reason || ok).focus();
  });
}
async function act(btn, fn, okTitle) {
  // run one backend action; the button shows a spinner until the server answers; success toast only on a real 2xx
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.replaceChildren(el("span", { class: "spin" }), " Working…"); }
  try { const r = await fn(); if (okTitle) toast(okTitle, null, "ok"); return r; }
  catch (e) { toast(e.code || "Error", e.message, "bad"); return undefined; }
  finally { if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = label; } }
}

// ================================================================================================ layout pieces
const S = { app: null, pkg: store.get("sp.pkg"), packages: [], reviews: [] };
let renderToken = 0;
function setPkg(pid) { S.pkg = pid || null; store.set("sp.pkg", pid || null); }

function pageHead({ eyebrow, title, lead, actions = [] }) {
  return el("div", { class: "page-head" }, el("div", { class: "titles" }, eyebrow ? el("div", { class: "eyebrow" }, eyebrow) : null,
    el("h1", {}, title), lead ? el("p", { class: "lead" }, lead) : null), actions.length ? el("div", { class: "actions" }, actions) : null);
}
function card(title, body, { sub, actions = [], flush = false, id } = {}) {
  return el("section", { class: "card", id: id || null },
    title ? el("div", { class: "card-head" }, el("h2", {}, title, sub ? el("span", { class: "sub" }, " · ", sub) : null), ...actions) : null,
    el("div", { class: `card-body ${flush ? "flush" : ""}` }, body));
}
function callout(kind, title, ...body) {
  return el("div", { class: `callout ${kind}` }, icon(kind === "ok" ? "check" : kind === "bad" || kind === "warn" || kind === "test" ? "warn" : "info", "ci"),
    el("div", { class: "body" }, title ? el("b", {}, title) : null, ...body));
}
function empty(title, text, actions = [], ill = "inbox") {
  return el("div", { class: "empty" }, icon(ill, "ill"), el("h3", {}, title), el("p", {}, text), actions.length ? el("div", { class: "row" }, actions) : null);
}
function loading() {
  return el("div", { "aria-busy": "true" }, el("div", { class: "skel h" }), el("div", { class: "skel w80" }), el("div", { class: "skel w60" }),
    el("div", { class: "skel block" }), el("div", { class: "skel w80" }), el("div", { class: "skel block" }));
}
function errorBox(e, retry) {
  return el("div", { class: "err-box", role: "alert" }, el("h3", {}, e.status === 404 ? "Not found" : "Something went wrong"),
    el("p", { class: "small" }, `${e.code || "ERROR"}: ${e.message}`),
    retry ? el("div", { class: "row section" }, el("button", { class: "btn", onclick: retry }, "Try again")) : null);
}
function table(cols, rows, { onRow, rowClass, emptyText = "No rows" } = {}) {
  const thead = el("thead", {}, el("tr", {}, cols.map(c => el("th", { class: c.cls || null }, c.h))));
  const tb = el("tbody");
  if (!rows.length) tb.append(el("tr", {}, el("td", { colspan: cols.length, class: "muted" }, emptyText)));
  for (const r of rows) {
    const tr = el("tr", { class: [onRow ? "click" : "", rowClass ? rowClass(r) : ""].join(" ").trim() || null },
      cols.map(c => el("td", { class: c.cls || null }, c.v(r))));
    if (onRow) { tr.tabIndex = 0; tr.onclick = () => onRow(r); tr.onkeydown = e => { if (e.key === "Enter") onRow(r); }; }
    tb.append(tr);
  }
  return el("div", { class: "table-wrap" }, el("table", { class: "t" }, thead, tb));
}
const facts = items => el("div", { class: "facts" }, items.map(([k, v, d, cls]) =>
  el("div", { class: `fact ${cls || ""}` }, el("div", { class: "k" }, k), el("div", { class: `v ${typeof v === "string" && v.length > 14 ? "small" : ""}` }, v), d ? el("div", { class: "d" }, d) : null)));
const kv = pairs => el("div", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v]) => [el("div", { class: "k" }, k), el("div", { class: "v" }, v ?? "–")]));

// ================================================================================================ navigation chrome
const NAV = [
  ["Workspace", [["overview", "Overview", "#/overview", "overview"], ["intake", "Evidence Intake", "#/intake", "upload"],
    ["processing", "Processing", "#/processing", "process"], ["files", "Evidence Files", p => `#/packages/${p}`, "files"]]],
  ["Review & control", [["review", "Mapping Review", "#/review", "review"], ["validation", "Package Validation", p => `#/validation/${p}`, "validate"],
    ["resubmit", "Resubmission", p => `#/resubmit/${p}`, "resubmit"], ["history", "Package History", p => `#/history/${p}`, "history"]]],
  ["Reconciliation", [["recon", "Reconciliation", p => `#/reconciliation/${p}`, "recon"], ["results", "Results & Exceptions", p => `#/results/${p}`, "results"]]],
  ["Governance", [["activity", "Activity & Audit", p => `#/activity/${p || ""}`, "activity"]]],
];
function renderNav(active) {
  const n = $("#nav"); n.replaceChildren();
  const pend = S.current ? Object.keys(S.current.pending_resubmissions || {}).length : 0;
  for (const [group, items] of NAV) {
    n.append(el("div", { class: "nav-group" }, group));
    for (const [key, label, href, ic] of items) {
      const needsPkg = typeof href === "function";
      const target = needsPkg ? (S.pkg ? href(S.pkg) : null) : href;
      const count = key === "review" && S.reviews.length ? S.reviews.length : key === "resubmit" && pend ? pend : null;
      n.append(el("a", { href: target || "#/overview", class: `${active === key ? "active" : ""} ${!target ? "disabled" : ""}`.trim(),
        "aria-current": active === key ? "page" : null, title: !target ? "Select or create a package first" : null },
        icon(ic), label, count ? el("span", { class: "count" }, String(count)) : null));
    }
  }
  $("#foot").replaceChildren(el("div", {}, el("a", { href: "/design.html", target: "_blank" }, "Design system reference")),
    el("div", { class: "subtle", title: S.app ? S.app.workspace : "" }, "Single-user POC · 127.0.0.1"));
}
function renderChrome(active, crumbs) {
  renderNav(active);
  const c = $("#crumbs"); c.replaceChildren();
  crumbs.forEach((x, i) => {
    if (i) c.append(el("span", { class: "sep" }, "/"));
    c.append(Array.isArray(x) ? el("a", { href: x[1] }, x[0]) : el("span", { class: "here" }, x));
  });
  const sel = $("#pkg-select"); sel.replaceChildren();
  if (S.packages.length) {
    const s = el("select", { "aria-label": "Current package", id: "pkg-switch" },
      S.packages.map(p => el("option", { value: p.package_id, selected: p.package_id === S.pkg }, `${p.package_id} · ${p.reporting_period}`)));
    if (!S.pkg) s.prepend(el("option", { value: "", selected: true }, "Select a package…"));
    s.onchange = () => { setPkg(s.value); location.hash = `#/packages/${s.value}`; };
    sel.append(el("span", { class: "muted" }, "Package"), s);
  }
  const env = $("#env"); env.replaceChildren();
  if (S.app) {
    env.append(el("span", { class: "pill test", title: S.app.authority_policy }, "TEST-ONLY authority"),
      el("span", { class: `pill ${S.app.llm.mode === "DISABLED" ? "off" : ""}`, title: S.app.llm.fixtures.join(", ") },
        S.app.llm.mode === "RECORDED" ? "LLM: recorded responses" : "LLM: disabled"),
      el("span", { class: "pill off", title: S.app.submission }, "Submission disabled"));
  }
}
async function refreshShared() {
  try {
    const [pk, rv] = await Promise.all([api("GET", "packages"), api("GET", "reviews")]);
    S.packages = pk; S.reviews = rv;
    if (S.pkg && !pk.some(p => p.package_id === S.pkg)) setPkg(null);
    if (!S.pkg && pk.length) setPkg(pk[0].package_id);
    S.current = S.pkg ? await api("GET", `packages/${S.pkg}`) : null;
  } catch (e) { /* the page itself shows errors */ }
}

// ================================================================================================ router
const routes = [];
const on = (re, fn) => routes.push([re, fn]);
let pollTimer = null;
function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }
async function router() {
  stopPolling();
  const token = ++renderToken;
  const h = location.hash || "#/overview";
  const main = $("#main");
  main.replaceChildren(loading());
  if (!S.app) { try { S.app = await api("GET", "app"); } catch (e) { main.replaceChildren(errorBox(e, router)); return; } }
  await refreshShared();
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (!m) continue;
    try { await fn(main, token, ...m.slice(1).map(x => x === undefined ? undefined : decodeURIComponent(x))); }
    catch (e) { if (token === renderToken) { renderChrome(null, [["Home", "#/overview"], "Error"]); main.replaceChildren(errorBox(e, router)); } }
    if (token === renderToken) main.focus({ preventScroll: true });
    return;
  }
  location.hash = "#/overview";
}
window.addEventListener("hashchange", router);
const live = token => token === renderToken;
function poll(token, fn, ms = 900) { pollTimer = setTimeout(async () => { if (!live(token)) return; await fn(); }, ms); }

// ================================================================================================ Overview
on(/^#\/overview$/, async (main, token) => {
  renderChrome("overview", ["Overview"]);
  const p = S.current;
  const out = [pageHead({ eyebrow: "Overview", title: "Safeguarding evidence workspace",
    lead: "Upload a reporting period's evidence package, resolve mapping reviews, validate and activate the package, then reconcile it with the UC-042 engine.",
    actions: [el("a", { class: "btn primary", href: "#/intake" }, icon("upload"), "Start new evidence intake")] })];
  if (!p) {
    out.push(card(null, empty("No evidence package yet", "Create a package for a reporting period and upload its evidence files to begin.",
      [el("a", { class: "btn primary", href: "#/intake" }, "Start new evidence intake")])));
  } else {
    const c = p.counts, lv = p.latest_validation, lr = p.latest_run;
    out.push(el("div", { class: "stack" },
      card(`Current package · ${p.package_id}`, el("div", { class: "stack" },
        el("div", { class: "row" }, pBadge(p.package_status), el("span", { class: "muted" }, p.package_status_text)),
        facts([["Reporting period", p.reporting_period], ["Files received", fmtNum(c.files_received), `${c.versions} file version(s) · ${c.refused_uploads} refused`],
          ["Identified by content", fmtNum(c.identified_by_content), "category from headers / PDF labels"],
          ["Mapped & validated", `${c.validated_or_active}`, `of ${p.slots.length} evidence slot(s)`, c.validated_or_active ? "ok" : ""],
          ["Requiring review", fmtNum(c.review_required), null, c.review_required ? "warn" : ""],
          ["Missing / failed", `${c.missing_required} / ${c.needs_new_version}`, "missing required · awaiting correction", (c.missing_required + c.needs_new_version) ? "bad" : ""]]),
        facts([["Package validation", lv ? (lv.passed ? "Passed" : "Blocked") : "Not run", lv ? `${fmtTime(lv.at)}${lv.failed.length ? " · " + lv.failed.join(", ") : ""}` : "run from Package Validation", lv ? (lv.passed ? "ok" : "warn") : ""],
          ["Activation", p.active_snapshot_id || "Not activated", p.active_snapshot_id ? "immutable snapshot (not submitted)" : "", p.active_snapshot_id ? "ok" : ""],
          ["Latest reconciliation", lr ? (CASE_STATUS[lr.case_status] || [0, lr.case_status])[1] : "Not run", lr ? `${lr.exception_count} exception(s) · ${fmtTime(lr.executed_at)}` : "", lr ? (lr.case_status === "CLEAN" ? "ok" : "bad") : ""]]),
        nextStep(p)), { actions: [el("a", { class: "btn sm", href: `#/packages/${p.package_id}` }, "Open evidence files")] })));
  }
  out.push(el("div", { class: "section" }, card("Recent packages", S.packages.length ? table([
    { h: "Package", v: r => el("span", { class: "mono" }, r.package_id) }, { h: "Period", v: r => r.reporting_period },
    { h: "Status", v: r => pBadge(r.package_status) }, { h: "Files", cls: "num", v: r => fmtNum(r.counts.files_received) },
    { h: "Review", cls: "num", v: r => fmtNum(r.counts.review_required) }, { h: "Snapshot", v: r => r.active_snapshot_id || el("span", { class: "subtle" }, "–") },
    { h: "Latest reconciliation", v: r => r.latest_run ? cBadge(r.latest_run.case_status) : el("span", { class: "subtle" }, "Not run") },
    { h: "Updated", v: r => timeEl(r.updated_at) }], S.packages, { onRow: r => { setPkg(r.package_id); location.hash = `#/packages/${r.package_id}`; } })
    : empty("No packages", "Packages you create appear here."), { flush: true })));
  if (live(token)) main.replaceChildren(...out);
});
function nextStep(p) {
  const pend = Object.keys(p.pending_resubmissions || {});
  const pid = p.package_id;
  if (p.package_status === "RECEIVED") return callout("info", "Next step", el("p", {}, "Upload this package's evidence files."), el("a", { class: "btn sm primary", href: "#/intake" }, "Upload evidence"));
  if (pend.length) return callout("bad", "Corrected evidence required", el("p", {}, `${pend.join(", ")} need a corrected file before the package can be activated.`), el("a", { class: "btn sm", href: `#/resubmit/${pid}` }, "Open resubmission"));
  if (p.counts.review_required) return callout("warn", "Analyst review required", el("p", {}, `${p.counts.review_required} file(s) wait for a mapping decision.`), el("a", { class: "btn sm", href: "#/review" }, "Open review queue"));
  if (p.counts.missing_required) return callout("warn", "Required evidence missing", el("p", {}, `${p.counts.missing_required} required categor${p.counts.missing_required > 1 ? "ies have" : "y has"} no file.`), el("a", { class: "btn sm", href: `#/resubmit/${pid}` }, "Upload missing evidence"));
  if (p.package_status === "READY_FOR_VALIDATION") return callout("info", "Ready for validation and activation", el("p", {}, "Every required category has a validated file."), el("a", { class: "btn sm primary", href: `#/validation/${pid}` }, "Validate & activate"));
  if (p.package_status === "RECONCILIATION_READY") return callout("ok", "Active snapshot ready", el("p", {}, `${p.active_snapshot_id} can be reconciled with the UC-042 engine.`), el("a", { class: "btn sm primary", href: `#/reconciliation/${pid}` }, p.latest_run ? "View reconciliation" : "Run reconciliation"));
  return null;
}

// ================================================================================================ Evidence Intake
on(/^#\/intake$/, async (main, token) => {
  renderChrome("intake", [["Overview", "#/overview"], "Evidence intake"]);
  const staged = [];   // {meta, declared}
  const cats = S.app.categories;
  const period = el("input", { type: "month", id: "period", value: "", required: true, "aria-describedby": "period-hint" });
  const fileIn = el("input", { type: "file", id: "file-input", multiple: true, accept: ".csv,.pdf,.zip,.txt", class: "sr-only" });
  const listBox = el("div");
  const submitBtn = el("button", { class: "btn primary", id: "submit-intake", disabled: true }, "Submit package for processing");
  const drop = el("div", { class: "drop", id: "drop" }, icon("upload"), el("div", { class: "big" }, "Drop evidence files or a ZIP package here"),
    el("p", { class: "muted small" }, "CSV and PDF evidence files, or one ZIP containing them. Files are identified by their content, never by name."),
    el("div", { class: "row section", }, el("label", { class: "btn", for: "file-input" }, "Choose files…")), fileIn);
  const addFiles = async list => {
    for (const f of list) {
      const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(f); });
      const row = { meta: { name: f.name, size: f.size, kind: "…", staging_id: null }, declared: "", state: "uploading" };
      staged.push(row); draw();
      try {
        const r = await api("POST", "staging", { name: f.name, data_b64: b64 });
        staged.splice(staged.indexOf(row), 1, ...r.entries.map(m => ({ meta: m, declared: "", state: m.staging_id ? "staged" : "skipped" })));
      } catch (e) { row.state = "error"; row.error = e.message; }
      draw();
    }
  };
  fileIn.onchange = () => { addFiles([...fileIn.files]); fileIn.value = ""; };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); addFiles([...e.dataTransfer.files]); };
  function draw() {
    const ready = staged.filter(s => s.state === "staged");
    submitBtn.disabled = !ready.length || !period.value || staged.some(s => s.state === "uploading");
    listBox.replaceChildren(staged.length ? table([
      { h: "File", v: r => el("div", {}, el("div", { class: "mono" }, r.meta.name), r.meta.from_zip ? el("div", { class: "sub" }, `from ${r.meta.from_zip}`) : null) },
      { h: "Size", cls: "num", v: r => fmtBytes(r.meta.size) }, { h: "Type", v: r => r.meta.kind },
      { h: "Upload status", v: r => r.state === "staged" ? el("span", {}, badge("ok", "Ready"), " ", hash(r.meta.sha256))
          : r.state === "uploading" ? el("span", {}, el("span", { class: "spin" }), " Uploading…") : r.state === "skipped" ? badge("neutral", `Skipped: ${r.meta.skipped}`) : badge("bad", r.error || "Error") },
      { h: "Evidence category", v: r => r.state !== "staged" ? "–" : (() => {
          const s = el("select", { "aria-label": `Category for ${r.meta.name}`, class: "decl" }, el("option", { value: "" }, "Identify by content"),
            cats.map(c => el("option", { value: c.category, selected: r.declared === c.category }, `${c.category} · ${c.title}`)));
          s.onchange = () => { r.declared = s.value; }; return s; })() },
      { h: "", cls: "tight", v: r => el("button", { class: "btn sm ghost", "aria-label": `Remove ${r.meta.name}`, onclick: () => { staged.splice(staged.indexOf(r), 1); draw(); } }, "Remove") },
    ], staged) : el("p", { class: "muted small" }, "No files selected yet."));
  }
  period.oninput = draw;
  submitBtn.onclick = () => act(submitBtn, async () => {
    const pkg = await api("POST", "packages", { reporting_period: period.value });
    setPkg(pkg.package_id);
    const job = await api("POST", `packages/${pkg.package_id}/intake`, { items: staged.filter(s => s.state === "staged").map(s => ({ staging_id: s.meta.staging_id, declared_category: s.declared || null })) });
    location.hash = `#/processing/${job.job_id}`;
  }, "Package submitted for processing");
  draw();
  const out = [pageHead({ eyebrow: "Evidence intake", title: "Upload an evidence package",
      lead: "Create a package for one reporting period and submit its evidence. Every file is processed by the existing Smart Parser workflow from the beginning." }),
    el("div", { class: "split" }, el("div", { class: "stack" },
      card("1 · Reporting period", el("div", { class: "row" }, el("div", { class: "field" }, el("label", { for: "period" }, "Reporting period"), period,
        el("span", { class: "hint", id: "period-hint" }, "Month the evidence covers (YYYY-MM). A new package is created on submission.")))),
      card("2 · Evidence files", el("div", { class: "stack" }, drop, listBox)),
      el("div", { class: "row" }, submitBtn, el("span", { class: "muted small" }, "Declare a category only when the evidence calls for it - the content is always verified against the declaration."))),
      el("div", { class: "stack" }, card("What happens next", el("ol", { class: "small", style: null },
        el("li", {}, "Each file is stored with its SHA-256 and identified by its content."),
        el("li", {}, "CSV columns are compared with the category contract and mapped deterministically."),
        el("li", {}, "Unfamiliar or structurally different files are routed to an analyst - nothing is auto-approved."),
        el("li", {}, "Eligible files get a canonical preview with provenance."),
        el("li", {}, "The package is validated (PV-01 to PV-09); activation stays a separate, confirmed step."))),
        callout("info", "PDF evidence", el("p", { class: "small" }, "PDFs are classified by their key-detail labels only. Image-only (scanned) PDFs are not OCR'd and are reported as unsupported.")))) ];
  if (live(token)) main.replaceChildren(...out);
});

// ================================================================================================ Processing
on(/^#\/processing$/, async (main, token) => {
  renderChrome("processing", [["Overview", "#/overview"], "Processing"]);
  const jobs = S.current ? S.current.jobs : [];
  const out = [pageHead({ eyebrow: "Processing centre", title: "Processing runs", lead: S.current ? `Intake, resubmission and reconciliation jobs of ${S.current.package_id}.` : "" })];
  out.push(card(null, jobs.length ? table([{ h: "Job", v: r => el("span", { class: "mono" }, r.job_id) }, { h: "Kind", v: r => r.kind },
    { h: "State", v: r => jBadge(r.state) }, { h: "Files", cls: "num", v: r => r.kind === "reconciliation" ? "–" : fmtNum(r.files) },
    { h: "Started", v: r => timeEl(r.started_at) }, { h: "Finished", v: r => timeEl(r.finished_at) }], jobs,
    { onRow: r => { location.hash = `#/processing/${r.job_id}`; } }) : empty("No processing runs yet", "Submit evidence from Evidence Intake to start processing.", [el("a", { class: "btn primary", href: "#/intake" }, "Evidence intake")]), { flush: true }));
  if (live(token)) main.replaceChildren(...out);
});
on(/^#\/processing\/(JOB-[a-f0-9]+)$/, async (main, token, jid) => {
  const draw = async () => {
    const j = await api("GET", `jobs/${jid}`);
    if (!live(token)) return;
    if (j.package_id !== S.pkg) { setPkg(j.package_id); }
    renderChrome("processing", [["Overview", "#/overview"], ["Processing", "#/processing"], j.job_id]);
    if (j.kind === "reconciliation") { location.hash = `#/reconciliation/${j.package_id}?job=${j.job_id}`; return; }
    const running = j.state === "running" || j.state === "queued";
    const pct = j.progress.files_total ? Math.round(100 * j.progress.files_processed / j.progress.files_total) : 0;
    const bar = el("div", { class: `bar ${j.state === "completed" ? "ok" : ""}`, role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(j.progress.files_total), "aria-valuenow": String(j.progress.files_processed) }, el("span"));
    bar.firstChild.style.width = `${pct}%`;
    const head = pageHead({ eyebrow: j.kind === "resubmission" ? "Processing · resubmission" : "Processing · evidence intake",
      title: running ? "Processing your evidence package…" : j.state === "completed" ? "Processing complete" : "Processing stopped",
      lead: `${j.package_id} · job ${j.job_id}${j.resubmission ? ` · corrected ${j.resubmission.category}` : ""}`,
      actions: [jBadge(j.state)] });
    const stages = el("ol", { class: "steps", id: "stages" }, j.stages.map((s, i) => el("li", { class: `step ${s.status}`, dataset: { stage: s.key, status: s.status } },
      el("div", { class: "dot" }, s.status === "completed" ? "✓" : s.status === "failed" ? "!" : String(i + 1)),
      el("div", {}, el("div", { class: "t" }, s.title), el("div", { class: "x" }, s.explanation), s.detail ? el("div", { class: "d" }, s.detail) : null,
        s.evidence && s.evidence.length ? el("div", { class: "ev" }, s.evidence.join(" · ")) : null),
      el("div", { class: "when" }, el("div", {}, STAGE_STATE[s.status] || s.status), s.started_at ? el("div", {}, fmtTime(s.started_at, false)) : null,
        s.finished_at && s.finished_at !== s.started_at ? el("div", {}, "→ ", fmtTime(s.finished_at, false)) : null))));
    const files = table([{ h: "File", v: f => el("div", {}, el("div", { class: "mono" }, f.name), f.declared_category ? el("div", { class: "sub" }, `declared ${f.declared_category}`) : null) },
      { h: "Size", cls: "num", v: f => fmtBytes(f.size) },
      { h: "State", v: f => f.state === "running" ? el("span", {}, el("span", { class: "spin" }), " Processing") : f.state === "queued" ? badge("neutral", "Queued") : f.state === "error" ? badge("bad", "Error") : badge("ok", "Processed") },
      { h: "Category", v: f => f.outcome && f.outcome.evidence_category ? el("span", {}, el("b", {}, f.outcome.evidence_category), f.outcome.content_category && f.outcome.content_category === f.outcome.evidence_category ? el("div", { class: "sub" }, "identified by content") : f.outcome.content_category ? el("div", { class: "sub" }, `content: ${f.outcome.content_category}`) : el("div", { class: "sub" }, "declared")) : "–" },
      { h: "Route", v: f => f.outcome && f.outcome.processing_status ? el("span", { class: "mono small", title: f.outcome.processing_status }, f.outcome.processing_status.split(":")[0]) : "–" },
      { h: "Result", v: f => !f.outcome ? "–" : f.outcome.error ? el("span", { class: "small" }, f.outcome.error) : f.outcome.version_status ? el("div", {}, vBadge(f.outcome.version_status), el("div", { class: "sub" }, short(f.outcome.reasons && f.outcome.reasons[0], 140))) : el("div", {}, badge("bad", "Not accepted"), el("div", { class: "sub" }, f.outcome.refused_reason)) },
      { h: "", cls: "tight", v: f => f.outcome && f.outcome.review ? el("a", { class: "btn sm", href: `#/review/${j.package_id}/${f.outcome.file_version_id}` }, "Review") : f.outcome && f.outcome.file_version_id ? el("a", { class: "btn sm ghost", href: `#/history/${j.package_id}/${f.outcome.file_version_id}` }, "Details") : null }],
      j.files);
    const nRev = j.files.filter(f => f.outcome && f.outcome.version_status === "REVIEW_REQUIRED").length;
    const nBad = j.files.filter(f => f.outcome && (["FAILED_VALIDATION", "RESUBMISSION_REQUIRED", "REJECTED"].includes(f.outcome.version_status) || f.outcome.refused_reason || f.outcome.error)).length;
    const cta = !running ? el("div", { class: "row" },
      nRev ? el("a", { class: "btn primary", href: "#/review" }, `Review ${nRev} file${nRev > 1 ? "s" : ""}`) : null,
      nBad ? el("a", { class: "btn", href: `#/resubmit/${j.package_id}` }, `Resolve ${nBad} file${nBad > 1 ? "s" : ""}`) : null,
      el("a", { class: `btn ${nRev ? "" : "primary"}`, href: `#/validation/${j.package_id}` }, "Package validation"),
      el("a", { class: "btn ghost", href: `#/packages/${j.package_id}` }, "Evidence files")) : null;
    const feed = el("ul", { class: "timeline small", id: "feed" }, j.events.slice().reverse().slice(0, 25).map(e => el("li", { class: "tl" },
      el("div", { class: "tm" }, fmtTime(e.at, false)), el("div", { class: "mk" }), el("div", {}, el("span", { class: "mono" }, e.event_type), e.category ? el("span", { class: "muted" }, ` · ${e.category}`) : null, e.file ? el("span", { class: "muted" }, ` · ${e.file}`) : null))));
    const view = [head,
      j.error ? callout("bad", "The job failed", el("p", {}, j.error)) : null,
      el("div", { class: "split" }, el("div", { class: "stack" },
        card("Progress", el("div", { class: "stack" }, el("div", { class: "row" }, el("b", {}, `${j.progress.files_processed} of ${j.progress.files_total} files processed`),
          el("span", { class: "muted small" }, running ? "updating from the server…" : `finished ${fmtTime(j.finished_at)}`)), bar)),
        card("Pipeline stages", stages, { flush: true, sub: "status from service results and recorded audit events" })),
        el("div", { class: "stack" }, card("Recorded events", j.events.length ? feed : el("p", { class: "muted small" }, "No events yet."), { flush: true, sub: "audit log" }),
          callout("info", "How progress is reported", el("p", { class: "small" }, "Each file is a real call to the package service. A stage is shown as completed only when the service returned its result or the matching event was written to the audit log; nothing is timed or simulated."), el("p", { class: "small" }, j.llm_mode.label)))),
      el("div", { class: "section" }, card("Files", files, { flush: true, sub: `${j.files.length} file(s), processed in the service's order (CSV before PDF)` })),
      cta ? el("div", { class: "section" }, cta) : null];
    main.replaceChildren(...view.filter(Boolean));
    if (running) poll(token, draw, 800);
    else refreshShared().then(() => live(token) && renderNav("processing"));
  };
  await draw();
});

// ================================================================================================ Evidence files (classification + status)
on(/^#\/packages\/(PKG-[\w-]+)$/, async (main, token, pid) => {
  setPkg(pid); await refreshShared();
  const p = await api("GET", `packages/${pid}`);
  renderChrome("files", [["Overview", "#/overview"], pid, "Evidence files"]);
  const slots = table([
    { h: "Category", v: s => el("div", {}, el("b", {}, s.evidence_category), el("div", { class: "sub" }, s.category_title)) },
    { h: "Req.", v: s => s.required ? badge("neutral plain", "Required") : badge("dashed plain", "Optional") },
    { h: "File", v: s => s.latest ? el("div", {}, el("div", { class: "mono small" }, s.latest.original_filename), el("div", { class: "sub" }, `v${s.latest.version_number} · ${s.latest.identified_by_content ? "identified by content" : s.latest.content_category ? `content: ${s.latest.content_category}` : "declared category"}`)) : el("span", { class: "subtle" }, "No file received") },
    { h: "Classification / route", v: s => s.latest ? el("span", { class: "mono small", title: s.latest.processing_status }, s.latest.processing_status.split(":")[0]) : "–" },
    { h: "Status", v: s => vBadge(s.state) },
    { h: "Reason", v: s => s.latest ? el("span", { class: "small" }, short(s.latest.reason, 160)) : s.required ? el("span", { class: "small muted" }, "Required for activation (PV-01)") : "–" },
    { h: "", cls: "tight", v: s => s.latest ? (s.latest.version_status === "REVIEW_REQUIRED" ? el("a", { class: "btn sm", href: `#/review/${pid}/${s.latest.file_version_id}` }, "Review")
        : ["RESUBMISSION_REQUIRED", "FAILED_VALIDATION", "REJECTED"].includes(s.latest.version_status) ? el("a", { class: "btn sm", href: `#/resubmit/${pid}/${s.evidence_category}` }, "Correct")
        : el("a", { class: "btn sm ghost", href: `#/history/${pid}/${s.latest.file_version_id}` }, "Details")) : el("a", { class: "btn sm ghost", href: `#/resubmit/${pid}/${s.evidence_category}` }, "Upload") }], p.slots);
  const view = [pageHead({ eyebrow: `Evidence files · ${p.reporting_period}`, title: pid, lead: p.package_status_text,
      actions: [pBadge(p.package_status), el("a", { class: "btn", href: `#/validation/${pid}` }, "Package validation")] }),
    facts([["Files received", fmtNum(p.counts.files_received)], ["Identified by content", fmtNum(p.counts.identified_by_content)],
      ["Validated / active", fmtNum(p.counts.validated_or_active), null, "ok"], ["Review required", fmtNum(p.counts.review_required), null, p.counts.review_required ? "warn" : ""],
      ["Awaiting correction", fmtNum(p.counts.needs_new_version), null, p.counts.needs_new_version ? "bad" : ""], ["Missing required", fmtNum(p.counts.missing_required), null, p.counts.missing_required ? "bad" : ""]]),
    el("div", { class: "section" }, card("Evidence classification and file status", slots, { flush: true, sub: `${p.slots.length} slot(s)` })),
    p.unassigned_uploads.length ? el("div", { class: "section" }, card("Uploads not accepted", table([{ h: "File", v: u => el("span", { class: "mono small" }, u.filename) },
      { h: "Category", v: u => u.evidence_category || el("span", { class: "subtle" }, "not identified") }, { h: "Reason", v: u => el("span", { class: "small" }, u.reason) },
      { h: "SHA-256", v: u => hash(u.source_sha256) }, { h: "When", v: u => timeEl(u.at) }], p.unassigned_uploads), { flush: true, sub: "kept for traceability; no version was created" })) : null];
  if (live(token)) main.replaceChildren(...view.filter(Boolean));
});

// ================================================================================================ Mapping review - queue
on(/^#\/review$/, async (main, token) => {
  renderChrome("review", [["Overview", "#/overview"], "Mapping review"]);
  const rows = S.reviews;
  const view = [pageHead({ eyebrow: "Mapping review", title: "Review queue", lead: "File versions waiting for an analyst decision. Open a file to see its source columns, sample values and the proposed canonical fields." }),
    callout("test", "TEST-ONLY analyst authority", el("p", { class: "small" }, `Decisions are recorded as ${S.app.reviewer.reviewer_id} (${S.app.reviewer.role}, ${S.app.reviewer.kind}) under "${S.app.authority_policy}". This is not a production approval.`)),
    el("div", { class: "section" }, card(null, rows.length ? table([
      { h: "Package", v: r => el("span", { class: "mono small" }, r.package_id) },
      { h: "Category", v: r => el("div", {}, el("b", {}, r.evidence_category), el("div", { class: "sub" }, r.category_title)) },
      { h: "File", v: r => el("div", {}, el("div", { class: "mono small" }, r.original_filename), el("div", { class: "sub" }, `v${r.version_number} · uploaded ${fmtTime(r.uploaded_at)}`)) },
      { h: "Columns", cls: "num", v: r => `${r.incoming_header_count ?? "–"} / ${r.expected_field_count}` },
      { h: "Review", v: r => badge("info plain", r.review_kind || "–") },
      { h: "Diagnosis", v: r => el("div", { class: "small" },
          Object.entries(r.duplicate_headers || {}).map(([h, ps]) => el("div", {}, badge("warn plain", "Duplicate"), " ", el("span", { class: "mono" }, h), ` at #${ps.join(", #")}`)),
          (r.extra_headers || []).length ? el("div", {}, badge("neutral plain", "Extra"), " ", r.extra_headers.join(", ")) : null,
          (r.missing_fields || []).length ? el("div", {}, badge("bad plain", "Missing"), " ", r.missing_fields.join(", ")) : null,
          !Object.keys(r.duplicate_headers || {}).length && !(r.extra_headers || []).length && !(r.missing_fields || []).length ? el("span", { class: "muted" }, short(r.review_reason, 120)) : null) },
    ], rows, { onRow: r => { setPkg(r.package_id); location.hash = `#/review/${r.package_id}/${r.file_version_id}`; } })
      : empty("No file is waiting for review", "Files that need an analyst decision appear here after processing.", [], "check"), { flush: true }))];
  if (live(token)) main.replaceChildren(...view);
});

// ================================================================================================ Mapping review - detail
on(/^#\/review\/(PKG-[\w-]+)\/(FV-[\w]+)$/, async (main, token, pid, vid) => {
  setPkg(pid);
  const open = new Set();
  let d = await api("GET", `review/${pid}/${vid}`);
  const post = async (btn, path, body, okTitle) => {
    const r = await act(btn, () => api("POST", `review/${pid}/${vid}/${path}`, body), okTitle);
    if (r) { d = r; await refreshShared(); draw(); }
    return r;
  };
  function decisionCell(r) {
    const dec = r.decision;
    if (!dec) return badge("warn", "Undecided");
    const cls = dec.action === "DETERMINISTIC" ? "ok" : ["IGNORE_COLUMN"].includes(dec.action) ? "neutral" : ["LEAVE_UNRESOLVED", "LEAVE_UNMAPPED"].includes(dec.action) ? "warn" : "ok";
    return el("div", { class: "dec" }, el("div", {}, badge(cls, DECISION[dec.action] || dec.action), dec.canonical_field ? el("span", { class: "mono small" }, " → ", dec.canonical_field) : null),
      dec.reason ? el("div", { class: "r" }, dec.reason) : null, dec.reviewer ? el("div", { class: "r" }, `${dec.reviewer} · ${fmtTime(dec.at)}`) : null);
  }
  function detailRow(r, ncol) {
    const fields = d.canonical_fields;
    const prof = r.profile || {};
    const sel = el("select", { class: "field-sel", "aria-label": `Canonical field for column ${r.source_position}` }, el("option", { value: "" }, "— choose a field —"),
      fields.map(f => el("option", { value: f.name, selected: f.name === r.suggested_field }, `${f.name} (${f.type}${f.required ? ", required" : ""})`)));
    const why = el("input", { type: "text", class: "reason", placeholder: "Reason for this decision (required)", "aria-label": `Reason for column ${r.source_position}` });
    const editable = d.editable && !r.read_only;
    const doDecide = (action, btn) => {
      const body = { action, source_index: r.source_index, reason: why.value.trim() };
      if (action === "CHANGE" || action === "CHOOSE_DUPLICATE_SOURCE") body.canonical_field = sel.value || r.suggested_field;
      if (action === "CHOOSE_DUPLICATE_SOURCE") body.others_reason = why.value.trim();
      return post(btn, "decision", body, `Column #${r.source_position}: ${DECISION[action] || action}`);
    };
    const btns = editable ? el("div", { class: "row" },
      el("button", { class: "btn sm primary", dataset: { action: "MAP" }, disabled: !r.suggested_field, onclick: e => doDecide("MAP", e.currentTarget) }, "Map to proposed field"),
      el("button", { class: "btn sm", dataset: { action: "CHANGE" }, onclick: e => doDecide("CHANGE", e.currentTarget) }, "Map to selected field"),
      d.actions.includes("CHOOSE_DUPLICATE_SOURCE") && (r.duplicate_claim || (r.same_header_positions || []).length) ? el("button", { class: "btn sm", dataset: { action: "CHOOSE_DUPLICATE_SOURCE" }, onclick: e => doDecide("CHOOSE_DUPLICATE_SOURCE", e.currentTarget) }, "Use this column as the source") : null,
      d.actions.includes("IGNORE_COLUMN") ? el("button", { class: "btn sm", dataset: { action: "IGNORE_COLUMN" }, onclick: e => doDecide("IGNORE_COLUMN", e.currentTarget) }, "Ignore column") : null,
      el("button", { class: "btn sm", dataset: { action: "LEAVE_UNRESOLVED" }, onclick: e => doDecide("LEAVE_UNRESOLVED", e.currentTarget) }, "Leave unresolved")) : null;
    const f = fields.find(x => x.name === (r.decision && r.decision.canonical_field || r.suggested_field));
    return el("tr", { class: "expand", dataset: { detailFor: String(r.source_index) } }, el("td", { colspan: ncol },
      el("div", { class: "col-detail" },
        el("div", { class: "stack" },
          el("div", {}, el("h4", {}, `Source values · ${prof.rows ?? "–"} rows`), el("div", { class: "vals" }, (prof.samples || []).map(v => el("span", { class: `chip ${v === "" ? "empty" : ""}` }, v === "" ? "empty" : v)))),
          kv([["Source column", el("span", {}, el("span", { class: "mono" }, r.source_header), ` · position #${r.source_position}`)],
            ["Statistics", prof.rows != null ? `${fmtNum(prof.distinct)} distinct · ${fmtNum(prof.empty)} empty · ${fmtNum(prof.negative_values)} negative${prof.missing_cells ? ` · ${prof.missing_cells} short rows` : ""}` : "–"],
            ["Suggestion basis", r.suggestion_basis], r.proposal_assessment ? ["LLM assessment", el("span", {}, badge("info plain", r.proposal_assessment), " ", el("span", { class: "small muted" }, S.app.llm.mode === "RECORDED" ? "recorded response" : ""))] : null,
            r.note ? ["Explanation", el("span", { class: "small" }, r.note)] : null,
            ["Provenance", el("span", { class: "small" }, "stored original ", hash(d.source_sha256), ` · intake ${short(d.intake_id, 14)} · data from line 2`)]])),
        el("div", { class: "stack" },
          f ? el("div", {}, el("h4", {}, "Canonical field"), kv([["Field", el("span", { class: "mono" }, f.name)], ["Type", f.type], ["Required", f.required ? "Yes - must be covered" : "No"]])) : null,
          editable ? el("div", { class: "decide" }, el("div", { class: "row" }, sel), why, btns,
            el("p", { class: "xs muted" }, "Every decision needs a reason and is validated by the backend (duplicate targets, value rules and deterministic matches are enforced there).")) :
            el("p", { class: "small muted" }, r.read_only ? "Matched deterministically - not part of this review." : "This review is closed; decisions are read-only.")))));
  }
  function draw() {
    if (!live(token)) return;
    renderChrome("review", [["Overview", "#/overview"], ["Mapping review", "#/review"], `${d.evidence_category} · v${d.version_number}`]);
    const s = d.summary || {};
    const o = d.outcome;
    const closed = !d.editable;
    const ncol = 8;
    const tb = el("tbody");
    for (const r of d.rows) {
      const isOpen = open.has(r.source_index);
      const tw = el("button", { class: "twisty", "aria-expanded": String(isOpen), "aria-label": `Details for column ${r.source_position}`, onclick: () => { isOpen ? open.delete(r.source_index) : open.add(r.source_index); draw(); } }, isOpen ? "▾" : "▸");
      const samples = r.profile ? r.profile.samples.slice(0, 3).map(v => el("span", { class: `chip ${v === "" ? "empty" : ""}` }, v === "" ? "empty" : v)) : el("span", { class: "subtle" }, "–");
      tb.append(el("tr", { dataset: { idx: String(r.source_index) }, class: r.decision ? null : "sel" },
        el("td", { class: "tight" }, tw), el("td", { class: "num tight" }, String(r.source_position)),
        el("td", {}, el("div", { class: "mono" }, r.source_header)),
        el("td", { class: "samples" }, samples),
        el("td", {}, r.suggested_field ? el("div", {}, el("span", { class: "mono" }, r.suggested_field),
          el("div", { class: "sub" }, r.field_type ? `${r.field_type}${r.field_required ? " · required" : ""}` : "", r.proposal_assessment ? ` · LLM: ${r.proposal_assessment}` : "")) : el("em", { class: "muted" }, "No proposal"),
          r.alternatives_note && r.alternatives_note.length ? el("div", { class: "sub" }, r.alternatives_note[0]) : null),
        el("td", {}, badge({ CLEAR: "ok", DETERMINISTIC: "ok", PLAUSIBLE: "warn", AMBIGUOUS: "warn", NO_MATCH: "bad", CONFLICT_INCOMPLETE: "bad", NO_SUGGESTION: "neutral" }[r.validation] || "neutral", r.validation)),
        el("td", {}, r.financial ? el("span", { class: "tag fin" }, "Financial") : null, r.sign_sensitive ? el("span", { class: "tag sign" }, "Sign-sensitive") : null, r.field_required ? el("span", { class: "tag req" }, "Required") : null),
        el("td", {}, decisionCell(r))));
      if (isOpen) tb.append(detailRow(r, ncol));
    }
    const grid = el("div", { class: "table-wrap" }, el("table", { class: "t colgrid", id: "mapping" },
      el("thead", {}, el("tr", {}, ["", "#", "Source column", "Sample values", "Proposed canonical field", "Validation", "Flags", "Decision"].map(h => el("th", {}, h)))), tb));
    const outstanding = (s.outstanding || []).length, notCovered = (s.required_not_covered || []).length, unresolved = (s.unresolved || []).length;
    const fin = closed ? null : outstanding ? "Decide every column before completing." : (notCovered || unresolved)
      ? "Completing now will HOLD the file: a required field is not covered or a column is left unresolved."
      : "Ready: completing writes the file-specific mapping (bound to this upload only), reprocesses the original and runs the 14 handoff checks.";
    const basis = el("input", { type: "text", id: "basis", placeholder: "Completion basis (required)", "aria-label": "Completion basis" });
    const completeBtn = el("button", { class: "btn primary", id: "complete", disabled: !!outstanding }, "Complete review");
    completeBtn.onclick = () => { if (!basis.value.trim()) { basis.focus(); toast("REASON_REQUIRED", "Give the basis for completing this review.", "warn"); return; } post(completeBtn, "complete", { basis: basis.value.trim() }, "Review completed"); };
    const rejectBtn = el("button", { class: "btn danger", id: "reject" }, "Reject file…");
    rejectBtn.onclick = async () => {
      const c = await confirmDialog({ title: "Reject this file?", danger: true, confirmText: "Reject file", reasonLabel: "Rejection reason (recorded in the audit trail)", reasonRequired: true,
        body: el("div", { class: "stack small" }, el("p", {}, `${d.evidence_category} v${d.version_number} (${d.original_filename}) becomes REJECTED. The package then needs a corrected file for this category; no decision made here is carried forward to the new version.`)) });
      if (c) post(rejectBtn, "reject", { reason: c.reason }, "File rejected");
    };
    const outcomeCard = card("Outcome", el("div", { class: "stack" },
      kv([["Version status", vBadge(o.version_status)], ["Processing", el("span", { class: "mono small" }, o.processing_status)],
        ["Deterministic reprocess", o.reprocessed ? badge("ok", "Completed") : badge("neutral", "Not run")],
        ["Handoff eligible", o.handoff ? (o.handoff.eligible ? badge("ok", "Yes") : badge("bad", "No")) : "–"],
        ["Canonical preview", o.preview_generated ? el("a", { href: `/api/packages/${pid}/versions/${vid}/preview`, target: "_blank" }, "Open canonical CSV") : badge("neutral", "None")],
        o.handoff && o.handoff.provenance ? ["Provenance sidecar", el("span", { class: "mono xs" }, o.handoff.provenance)] : null,
        (o.missing_fields || []).length ? ["Missing fields", el("span", { class: "mono" }, o.missing_fields.join(", "))] : null,
        ["Package status", pBadge(o.package_status)], closed && d.current_outcome_reason ? ["Latest outcome", el("span", { class: "small" }, d.current_outcome_reason)] : null]),
      o.handoff && o.handoff.checks && o.handoff.checks.length ? table([{ h: "#", cls: "tight", v: c => String(c.id) }, { h: "Handoff check", v: c => c.name },
        { h: "Result", v: c => badge(c.passed ? "ok" : "bad", c.passed ? "PASS" : "FAIL") }, { h: "Detail", v: c => el("span", { class: "small muted" }, c.detail) }], o.handoff.checks) : null), { id: "outcome" });
    const hist = el("details", {}, el("summary", { class: "small muted" }, `Status and reason history (${d.status_history.length})`),
      el("ul", { class: "list-plain small" }, d.status_history.map(h => el("li", {}, vBadge(h.status), " ", timeEl(h.at), h.note ? el("div", { class: "muted" }, h.note) : null))));
    const view = [pageHead({ eyebrow: `Mapping review · ${d.review_kind || ""}`, title: `${d.evidence_category} · ${d.category_title}`,
        lead: `${d.original_filename} · version ${d.version_number} · ${d.package_id}`, actions: [vBadge(d.version_status), badge("info plain", d.review_state || "")] }),
      callout("test", "TEST-ONLY analyst authority", el("p", { class: "small" }, `You act as ${d.reviewer.reviewer_id} (${d.reviewer.role}, ${d.reviewer.kind}) under "${d.reviewer.authority_policy}". Nothing here is auto-approved; ambiguous proposals stay undecided until you decide them.`)),
      el("div", { class: "section grid2" },
        closed ? callout(o.version_status === "VALIDATED" ? "ok" : "warn", `Review closed · ${VERSION_STATUS[o.version_status] ? VERSION_STATUS[o.version_status][1] : o.version_status}`, el("p", { class: "small" }, d.current_outcome_reason || "This file is no longer under review."))
          : callout("warn", "Why this file needs a review", el("p", { class: "small" }, d.why_review || "–")),
        callout("info", "If a column is left unresolved", el("p", { class: "small" }, "The file stays under review (it never becomes Validated), the package cannot be activated (PV-04), and you can return to decide it or reject the file."))),
      el("div", { class: "section" }, facts([["Columns (incoming / canonical)", `${d.incoming_header_count ?? "–"} / ${d.expected_field_count}`], ["Rows in source", fmtNum(d.profile.rows)],
        ["Decisions made", `${s.decided ?? 0} of ${d.rows.length}`], ["Outstanding", outstanding ? `#${s.outstanding.map(i => i + 1).join(", #")}` : "None", null, outstanding ? "warn" : "ok"],
        ["Required not covered", notCovered ? s.required_not_covered.join(", ") : "None", null, notCovered ? "bad" : "ok"], ["Source SHA-256", short(d.source_sha256, 14), d.profile.encoding || null]])),
      Object.keys(d.duplicate_incoming_headers || {}).length ? el("div", { class: "section" }, callout("warn", "Duplicate source columns", ...Object.entries(d.duplicate_incoming_headers).map(([h, ps]) => el("p", { class: "small" }, el("span", { class: "mono" }, h), ` appears at columns #${ps.map(p => p + 1).join(", #")}. Choose the authoritative column with "Use this column as the source"; the others are ignored with your reason.`)))) : null,
      el("div", { class: "section" }, card("Column mapping", el("div", {}, grid, closed ? null : el("div", { class: "sticky-foot" }, el("span", { class: `small ${outstanding || notCovered || unresolved ? "muted" : ""}`, id: "finalisation" }, fin),
          el("div", { class: "spacer grow" }), basis, completeBtn, rejectBtn)), { flush: true, sub: "one row per incoming column, by position · expand a row for its values and actions" })),
      el("div", { class: "section" }, outcomeCard), el("div", { class: "section" }, hist)];
    main.replaceChildren(...view.filter(Boolean));
  }
  draw();
});

// ================================================================================================ Package validation + activation
on(/^#\/validation\/(PKG-[\w-]+)$/, async (main, token, pid) => {
  setPkg(pid);
  let v = await api("GET", `packages/${pid}/validation`);
  let activation = null;
  async function draw() {
    if (!live(token)) return;
    renderChrome("validation", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], "Package validation"]);
    const r = v.result, sm = v.summary;
    const runBtn = el("button", { class: "btn", id: "run-validation" }, "Run validation now");
    runBtn.onclick = async () => { const x = await act(runBtn, () => api("POST", `packages/${pid}/validate`), "Package validation completed"); if (x) { v = x; await refreshShared(); draw(); } };
    const actBtn = el("button", { class: "btn primary", id: "activate", disabled: !v.activation_permitted }, "Activate package…");
    actBtn.onclick = async () => {
      const sel = v.candidate.filter(c => c.file_version_id);
      const c = await confirmDialog({ title: "Activate this package?", confirmText: "Activate package",
        body: el("div", { class: "stack small" }, kv([["Package", pid], ["Reporting period", S.current ? S.current.reporting_period : "–"], ["File versions selected", String(sel.length)],
          ["Validation", r ? `${r.validation_id} · ${r.passed ? "passed" : "failed"}` : "–"], ["Snapshot", v.active_snapshot_id ? `replaces the active ${v.active_snapshot_id} only if the selection changed` : "a new immutable snapshot (sequence 1)"]]),
          callout("info", null, el("p", {}, "Activation re-runs PV-01 to PV-09 now and, only if every check passes, creates an immutable snapshot and manifest marked NOT submitted. It does not submit anything to UC-042 and does not generate or publish an audit pack."))) });
      if (!c) return;
      const x = await act(actBtn, () => api("POST", `packages/${pid}/activate`, { confirm: true }));
      if (x) { activation = x; v = x.validation; toast(x.activated ? "Package activated" : "Activation not performed", x.reason, x.activated ? "ok" : "warn"); await refreshShared(); draw(); }
    };
    const pvTable = r ? table([{ h: "Check", cls: "tight", v: c => el("b", { class: "mono" }, c.check_id) }, { h: "Description", v: c => c.name },
      { h: "Result", v: c => badge(c.passed ? "ok" : "bad", c.passed ? "PASS" : "FAIL") }, { h: "Evidence / reason", v: c => el("span", { class: "small mono" }, c.detail || "–") },
      { h: "Blocks activation", v: c => c.blocks_activation ? el("div", {}, badge("bad plain", "Blocks"), el("div", { class: "sub" }, c.action)) : el("span", { class: "subtle" }, "No") }], r.checks)
      : empty("Validation has not been run", "Run the package checks to see whether the package can be activated.", [], "validate");
    const listOf = (title, items, cls) => el("div", { class: "fact " + (items.length ? cls : "") }, el("div", { class: "k" }, title), el("div", { class: "v small" }, items.length ? items.join(", ") : "None"));
    const statusLegend = el("div", { class: "legend section" }, ["FAILED_VALIDATION", "REVIEW_REQUIRED", "RESUBMISSION_REQUIRED", "VALIDATED", "ACTIVE"].map(s => el("span", {}, vBadge(s), " ",
      { FAILED_VALIDATION: "processed, cannot become eligible - needs a new version", REVIEW_REQUIRED: "waiting for an analyst", RESUBMISSION_REQUIRED: "required columns missing - corrected file needed", VALIDATED: "passed every file-level check", ACTIVE: "selected by the active snapshot" }[s])));
    const cand = table([{ h: "Category", v: c => el("b", {}, c.evidence_category) }, { h: "Selected version", v: c => c.file_version_id ? el("span", {}, el("span", { class: "mono small" }, c.file_version_id), ` · v${c.version_number}`) : badge("bad plain", "None selectable") },
      { h: "File", v: c => c.original_filename ? el("span", { class: "mono small" }, c.original_filename) : "–" }, { h: "SHA-256", v: c => c.source_sha256 ? hash(c.source_sha256) : "–" },
      { h: "Status", v: c => c.version_status ? vBadge(c.version_status) : "–" }], v.candidate);
    const blocked = r && !r.passed ? callout("bad", "Activation is blocked", el("ul", { class: "small" }, r.checks.filter(c => !c.passed).map(c => el("li", {}, el("b", {}, c.check_id), ` ${c.name}: `, el("span", { class: "mono" }, c.detail), c.action ? ` - ${c.action}` : ""))))
      : r && r.passed ? callout("ok", "All package checks pass", el("p", { class: "small" }, v.active_snapshot_id && S.current && S.current.package_status === "RECONCILIATION_READY" ? `The active snapshot ${v.active_snapshot_id} already holds this selection.` : "The package can be activated.")) : null;
    const act0 = activation && activation.activated ? card("Activation result", el("div", { class: "stack" }, kv([["Snapshot", el("b", { class: "mono" }, activation.snapshot_id)], ["Result", activation.reason], ["Package status", pBadge(activation.package.package_status)]]),
      el("div", { class: "row" }, el("a", { class: "btn primary", href: `#/snapshot/${pid}/${activation.snapshot_id}` }, "View snapshot & manifest"), el("a", { class: "btn", href: `#/reconciliation/${pid}` }, "Go to reconciliation"))), { id: "activation-result" }) : null;
    const view = [pageHead({ eyebrow: "Package validation", title: `Validate & activate ${pid}`, lead: "PV-01 to PV-09 run over the current selection. Activation is only possible when the package service reports every check as passed.",
        actions: [pBadge(v.package_status), runBtn, actBtn] }),
      blocked, act0, el("div", { class: "section facts" }, listOf("Required present", sm.required_present.map(x => x), "ok"), listOf("Missing", sm.missing, "bad"), listOf("Under review", sm.review_required, "warn"),
        listOf("Resubmission required", sm.resubmission_required, "bad"), listOf("Failed validation", sm.failed_validation, "bad"), listOf("Rejected", sm.rejected, "bad"),
        listOf("Optional present", sm.optional, ""), el("div", { class: "fact" }, el("div", { class: "k" }, "Refused uploads"), el("div", { class: "v small" }, String(sm.refused_uploads)))),
      statusLegend,
      el("div", { class: "section" }, card("Package checks", pvTable, { flush: true, sub: r ? `${r.validation_id} · ${fmtTime(r.at)}` : "not run yet" })),
      el("div", { class: "section" }, card("Selection that activation would snapshot", cand, { flush: true, sub: "latest VALIDATED / ACTIVE version per category - never an older version" })),
      el("div", { class: "section" }, callout("info", "Activation does not submit", el("p", { class: "small" }, v.activation_note)))];
    main.replaceChildren(...view.filter(Boolean));
  }
  draw();
});

// ================================================================================================ Snapshot
on(/^#\/snapshot\/(PKG-[\w-]+)\/(SNAP-[\w-]+)$/, async (main, token, pid, sid) => {
  setPkg(pid);
  const s = await api("GET", `packages/${pid}/snapshots/${sid}`);
  renderChrome("history", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], ["History", `#/history/${pid}`], sid]);
  const m = s.manifest || {};
  const view = [pageHead({ eyebrow: "Activated snapshot", title: sid, lead: `${pid} · created ${fmtTime(s.snapshot.created_at)}`,
      actions: [s.is_active ? badge("ok strong", "Active") : badge("neutral", "Historical"), s.reconciliation_eligible ? el("a", { class: "btn primary", href: `#/reconciliation/${pid}` }, "Reconcile this snapshot") : null] }),
    facts([["Activation timestamp", fmtTime(s.snapshot.created_at)], ["File versions", String(s.snapshot.entries.length)], ["Manifest status", m.status || "–"],
      ["Submission authorised", m.submission_authorised === false ? "No" : "–"], ["Reconciliation eligible", s.reconciliation_eligible ? "Yes" : "No", s.is_active ? "active snapshot" : "only the active snapshot can be reconciled", s.reconciliation_eligible ? "ok" : ""]]),
    el("div", { class: "section grid2" }, card("Snapshot verification", table([{ h: "Check", v: c => el("b", { class: "mono" }, c.check_id) }, { h: "Description", v: c => c.name }, { h: "Result", v: c => badge(c.passed ? "ok" : "bad", c.passed ? "PASS" : "FAIL") }], s.verification), { flush: true }),
      card("Identity", kv([["Selection SHA-256", hash(s.snapshot.selection_sha256)], ["Validation", s.snapshot.validation_id], ["Previous snapshot", s.snapshot.previous_snapshot_id || "–"], ["Superseded versions", (m.superseded_versions || []).join(", ") || "None"]]))),
    el("div", { class: "section" }, card("Active file versions", table([{ h: "Category", v: e => el("b", {}, e.evidence_category) }, { h: "Version", v: e => el("span", {}, el("span", { class: "mono small" }, e.file_version_id), ` · v${e.version_number}`) },
      { h: "File", v: e => el("span", { class: "mono small" }, e.original_filename) }, { h: "Source SHA-256", v: e => hash(e.source_sha256) },
      { h: "Basis", v: e => e.handoff ? e.handoff.basis : "–" }, { h: "Canonical preview", v: e => e.handoff && e.handoff.output_sha256 ? hash(e.handoff.output_sha256) : el("span", { class: "subtle" }, "original PDF") }], s.snapshot.entries,
      { onRow: e => { location.hash = `#/history/${pid}/${e.file_version_id}`; } }), { flush: true })),
    s.runs.length ? el("div", { class: "section" }, card("Reconciliation runs of this snapshot", runsTable(s.runs), { flush: true })) : null];
  if (live(token)) main.replaceChildren(...view.filter(Boolean));
});

// ================================================================================================ History
on(/^#\/history\/(PKG-[\w-]+)$/, async (main, token, pid) => {
  setPkg(pid);
  const h = await api("GET", `packages/${pid}/history`);
  renderChrome("history", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], "Package history"]);
  const cats = h.categories.filter(c => c.versions.length);
  const view = [pageHead({ eyebrow: "Package history", title: `${pid} · versions and snapshots`, lead: "Every upload is a new version with its own intake ID and SHA-256; earlier versions and their bytes are never changed." }),
    el("div", { class: "grid2" }, card("Snapshots", h.snapshots.length ? table([{ h: "Snapshot", v: s => el("b", { class: "mono" }, s.snapshot_id) }, { h: "Created", v: s => timeEl(s.created_at) },
      { h: "Files", cls: "num", v: s => String(s.entries.length) }, { h: "", v: s => s.snapshot_id === h.active_snapshot_id ? badge("ok strong", "Active") : badge("neutral", "Historical") }], h.snapshots,
      { onRow: s => { location.hash = `#/snapshot/${pid}/${s.snapshot_id}`; } }) : empty("Not activated", "Snapshots appear after package activation."), { flush: true }),
      card("Validation runs", h.validations.length ? table([{ h: "Validation", v: x => el("span", { class: "mono small" }, x.validation_id) }, { h: "At", v: x => timeEl(x.at) },
        { h: "Result", v: x => x.passed ? badge("ok", "Passed") : el("span", {}, badge("bad", "Failed"), " ", el("span", { class: "small mono" }, x.failed.join(", "))) }], h.validations.slice().reverse())
        : empty("No validation yet", "Validation runs appear here."), { flush: true })),
    el("div", { class: "section" }, card("File versions by category", el("div", {}, cats.map(c => el("div", { class: "section" },
      el("div", { class: "toolbar" }, el("b", {}, c.evidence_category), el("span", { class: "muted" }, c.category_title), el("span", { class: "grow" }), c.versions.length > 1 ? badge("info plain", `${c.versions.length} versions`) : null),
      table([{ h: "Version", cls: "tight", v: x => el("b", {}, `v${x.version_number}`) }, { h: "File", v: x => el("div", {}, el("div", { class: "mono small" }, x.original_filename), x.replacement_reason ? el("div", { class: "sub" }, `replacement: ${x.replacement_reason}`) : null) },
        { h: "Intake", v: x => el("div", {}, timeEl(x.uploaded_at), el("div", { class: "sub mono" }, short(x.intake_id, 14))) }, { h: "SHA-256", v: x => hash(x.source_sha256) },
        { h: "Status", v: x => vBadge(x.version_status) }, { h: "Previous", v: x => x.previous_version_id ? el("span", { class: "mono small" }, x.previous_version_id) : "–" },
        { h: "Status history", v: x => el("div", { class: "small" }, x.status_history.map(s => el("div", {}, el("span", { class: "mono" }, s.status), " ", el("span", { class: "muted" }, fmtTime(s.at))))) }],
        c.versions, { onRow: x => { location.hash = `#/history/${pid}/${x.file_version_id}`; } })))), { flush: true }))];
  if (live(token)) main.replaceChildren(...view);
});
on(/^#\/history\/(PKG-[\w-]+)\/(FV-[\w]+)$/, async (main, token, pid, vid) => {
  setPkg(pid);
  const d = await api("GET", `packages/${pid}/versions/${vid}`);
  const v = d.version, b = d.brief;
  renderChrome("history", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], ["History", `#/history/${pid}`], `${v.evidence_category} v${v.version_number}`]);
  const view = [pageHead({ eyebrow: "File version", title: `${v.evidence_category} · version ${v.version_number}`, lead: v.original_filename,
      actions: [vBadge(v.version_status), v.version_status === "REVIEW_REQUIRED" ? el("a", { class: "btn primary", href: `#/review/${pid}/${vid}` }, "Open review") : null,
        b.preview ? el("a", { class: "btn", href: `/api/packages/${pid}/versions/${vid}/preview`, target: "_blank" }, "Canonical preview") : null] }),
    el("div", { class: "grid2" }, card("Identity & provenance", kv([["File version", el("span", { class: "mono" }, v.file_version_id)], ["Intake ID", el("span", { class: "mono" }, v.intake_id)], ["Source SHA-256", el("span", { class: "mono xs" }, v.source_sha256)],
      ["Uploaded", fmtTime(v.uploaded_at)], ["Category", `${v.evidence_category} · ${b.category_title}`], ["Identified by content", b.identified_by_content ? "Yes" : v.content_category ? `No - content is ${v.content_category}` : "No (declared)"],
      ["Processing route", el("span", { class: "mono small" }, v.processing_status)], ["Previous version", v.previous_version_id || "–"], ["Replacement reason", v.replacement_reason || "–"],
      ["Mapping rules", v.mapping_rule_refs.length ? v.mapping_rule_refs.map(r => `${r.rule_id || r.file_mapping_id || ""} v${r.rule_version || ""}`).join(", ") : "–"]])),
      card("Status history", el("ul", { class: "list-plain small" }, v.status_history.map(s => el("li", {}, vBadge(s.status), " ", timeEl(s.at), s.note ? el("div", { class: "muted" }, s.note) : null))))),
    v.reasons.length ? el("div", { class: "section" }, card("Reasons recorded", el("ul", { class: "small" }, v.reasons.map(r => el("li", {}, r))))) : null,
    d.decisions.length ? el("div", { class: "section" }, card(`Review decisions · ${d.review_kind}`, table([{ h: "#", cls: "tight", v: r => String(r.source_position) }, { h: "Source column", v: r => el("span", { class: "mono" }, r.source_header) },
      { h: "Decision", v: r => badge(r.decision.action === "IGNORE_COLUMN" ? "neutral" : "ok", DECISION[r.decision.action] || r.decision.action) }, { h: "Field", v: r => r.decision.canonical_field ? el("span", { class: "mono" }, r.decision.canonical_field) : "–" },
      { h: "Reason", v: r => el("span", { class: "small" }, r.decision.reason || "–") }, { h: "Reviewer", v: r => r.decision.reviewer ? el("div", { class: "small" }, r.decision.reviewer, el("div", { class: "sub" }, fmtTime(r.decision.at))) : el("span", { class: "subtle" }, "system") }], d.decisions), { flush: true })) : null,
    v.handoff && v.handoff.checks.length ? el("div", { class: "section" }, card("Handoff checks", table([{ h: "#", cls: "tight", v: c => String(c.id) }, { h: "Check", v: c => c.name }, { h: "Result", v: c => badge(c.passed ? "ok" : "bad", c.passed ? "PASS" : "FAIL") }, { h: "Detail", v: c => el("span", { class: "small muted" }, c.detail) }], v.handoff.checks), { flush: true })) : null,
    el("div", { class: "section" }, card("Version history of this category", table([{ h: "Version", v: x => el("b", {}, `v${x.version_number}`) }, { h: "File", v: x => el("span", { class: "mono small" }, x.original_filename) }, { h: "Uploaded", v: x => timeEl(x.uploaded_at) }, { h: "SHA-256", v: x => hash(x.source_sha256) }, { h: "Status", v: x => vBadge(x.version_status) }], d.history,
      { onRow: x => { location.hash = `#/history/${pid}/${x.file_version_id}`; }, rowClass: x => x.file_version_id === vid ? "sel" : "" }), { flush: true })),
    el("div", { class: "section" }, card("Recorded events for this version", eventList(d.events.slice().reverse()), { flush: true }))];
  if (live(token)) main.replaceChildren(...view.filter(Boolean));
});

// ================================================================================================ Resubmission
on(/^#\/resubmit\/(PKG-[\w-]+)(?:\/(IN-\d\d))?$/, async (main, token, pid, focusCat) => {
  setPkg(pid);
  const p = await api("GET", `packages/${pid}`);
  renderChrome("resubmit", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], "Correction & resubmission"]);
  const pend = Object.keys(p.pending_resubmissions);
  const missing = p.slots.filter(s => s.state === "MISSING");
  const blocks = [];
  function uploader(slot, mode) {
    const l = slot.latest;
    const box = el("div", { class: "stack" });
    const fileIn = el("input", { type: "file", accept: ".csv,.pdf,.txt", id: `file-${slot.evidence_category}`, class: "sr-only" });
    const status = el("div", { class: "small muted" }, "No file selected.");
    const reason = el("input", { type: "text", placeholder: mode === "resubmit" ? "Replacement reason (required)" : "Note (optional)", "aria-label": `Reason for ${slot.evidence_category}`, id: `reason-${slot.evidence_category}` });
    let staged = null;
    const go = el("button", { class: "btn primary", disabled: true, id: `send-${slot.evidence_category}` }, mode === "resubmit" ? "Upload corrected version" : "Upload evidence");
    fileIn.onchange = async () => {
      const f = fileIn.files[0]; if (!f) return;
      status.replaceChildren(el("span", { class: "spin" }), ` Uploading ${f.name}…`);
      try {
        const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(f); });
        const r = await api("POST", "staging", { name: f.name, data_b64: b64 });
        staged = r.entries[0];
        status.replaceChildren(badge("ok", "Ready"), " ", el("span", { class: "mono" }, staged.name), ` · ${fmtBytes(staged.size)} · `, hash(staged.sha256));
        go.disabled = false;
      } catch (e) { status.replaceChildren(badge("bad", e.code || "Error"), " ", e.message); }
    };
    go.onclick = () => act(go, async () => {
      if (mode === "resubmit" && !reason.value.trim()) throw Object.assign(new Error("Give the reason for the corrected version."), { code: "REASON_REQUIRED" });
      const job = mode === "resubmit" ? await api("POST", `packages/${pid}/resubmit`, { category: slot.evidence_category, staging_id: staged.staging_id, reason: reason.value.trim() })
        : await api("POST", `packages/${pid}/intake`, { items: [{ staging_id: staged.staging_id, declared_category: slot.evidence_category }] });
      location.hash = `#/processing/${job.job_id}`;
    }, mode === "resubmit" ? "Corrected version submitted" : "Evidence submitted");
    box.append(el("div", { class: "row" }, el("label", { class: "btn", for: fileIn.id }, "Choose file…"), fileIn, status), el("div", { class: "row" }, reason, go));
    return card(`${slot.evidence_category} · ${slot.category_title}`, el("div", { class: "stack" },
      l ? kv([["Current version", el("span", {}, vBadge(l.version_status), ` v${l.version_number} · `, el("span", { class: "mono small" }, l.original_filename))],
        ["Reason", el("span", { class: "small" }, l.reason || "–")], l.missing_fields.length ? ["Missing fields", el("span", { class: "mono" }, l.missing_fields.join(", "))] : null,
        ["What to correct", el("span", { class: "small" }, l.version_status === "RESUBMISSION_REQUIRED" ? "Supply a file that contains every required column - missing columns are never filled or inferred."
          : l.version_status === "REJECTED" ? "Supply the corrected export; the rejected version stays on record as REJECTED." : "Supply a corrected file that passes the file-level checks (see the reason).")]])
        : kv([["State", badge("dashed", "Missing")], ["Requirement", slot.required ? "Required for activation (PV-01)" : "Optional"]]),
      box, mode === "resubmit" ? el("p", { class: "xs muted" }, "The correction is a new intake and a new version, processed from the beginning. Earlier review decisions are not carried forward: a new review starts with no decisions. Identical bytes are refused.") : null),
      { id: `slot-${slot.evidence_category}`, actions: l ? [el("a", { class: "btn sm ghost", href: `#/history/${pid}/${l.file_version_id}` }, "Version history")] : [] });
  }
  for (const c of pend) blocks.push(uploader(p.slots.find(s => s.evidence_category === c), "resubmit"));
  for (const s of missing) blocks.push(uploader(s, "first"));
  const view = [pageHead({ eyebrow: "Correction & resubmission", title: "Evidence awaiting correction", lead: "Only files that are RESUBMISSION_REQUIRED, FAILED_VALIDATION or REJECTED accept a corrected version. A validated or active file is never voluntarily replaced, and a file under open review must be completed or rejected first." }),
    blocks.length ? el("div", { class: "stack" }, blocks) : card(null, empty("Nothing awaits correction", "Every evidence slot has a file that is validated, active or under review.", [el("a", { class: "btn", href: `#/validation/${pid}` }, "Package validation")], "check"))];
  if (live(token)) { main.replaceChildren(...view); if (focusCat) { const t = document.getElementById(`slot-${focusCat}`); if (t) t.scrollIntoView({ block: "start" }); } }
});

// ================================================================================================ Reconciliation
function runsTable(runs) {
  return table([{ h: "Run", v: r => el("span", { class: "mono small" }, r.run_id) }, { h: "Snapshot", v: r => el("span", { class: "mono small" }, r.snapshot_id) },
    { h: "Status", v: r => cBadge(r.case_status) }, { h: "Results", cls: "num", v: r => fmtNum(Object.values(r.outcomes).reduce((a, b) => a + b, 0)) },
    { h: "Exceptions", cls: "num", v: r => fmtNum(r.exception_count) }, { h: "Executed", v: r => timeEl(r.executed_at) }], runs, { onRow: r => { location.hash = `#/runs/${r.run_id}`; } });
}
on(/^#\/reconciliation\/(PKG-[\w-]+)(?:\?job=(JOB-[a-f0-9]+))?$/, async (main, token, pid, jobId) => {
  setPkg(pid);
  let jid = jobId || null;
  const draw = async () => {
    const p = await api("GET", `packages/${pid}`);
    if (!live(token)) return;
    renderChrome("recon", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], "Reconciliation"]);
    const j = jid ? await api("GET", `jobs/${jid}`) : null;
    const snapCount = p.active_snapshot_id ? p.slots.filter(s => s.active_version_id).length : 0;
    const eligible = !!p.active_snapshot_id && p.package_status === "RECONCILIATION_READY" && S.app.engine_configured;
    const why = !p.active_snapshot_id ? "The package has no active snapshot - validate and activate it first." : p.package_status !== "RECONCILIATION_READY" ? "The active snapshot is not the current selection (a newer version exists) - re-activate first."
      : !S.app.engine_configured ? "No UC-042 engine is configured for this server." : null;
    const runBtn = el("button", { class: "btn primary", id: "run-recon", disabled: !eligible || (j && j.state === "running") }, "Run reconciliation");
    runBtn.onclick = async () => { const x = await act(runBtn, () => api("POST", `packages/${pid}/reconcile`, { snapshot_id: p.active_snapshot_id }), "Reconciliation started"); if (x) { jid = x.job_id; history.replaceState(null, "", `#/reconciliation/${pid}?job=${jid}`); draw(); } };
    const jobCard = j ? card("Reconciliation run", el("div", { class: "stack" },
      el("div", { class: "row" }, jBadge(j.state), j.state === "running" ? el("span", { class: "muted small" }, "the UC-042 engine is running in a separate process…") : null, j.run_id ? el("span", { class: "mono small" }, j.run_id) : null),
      j.state === "running" ? el("div", { class: "bar indet" }, el("span")) : null,
      el("ol", { class: "steps", id: "recon-stages" }, j.stages.map((s, i) => el("li", { class: `step ${s.status}`, dataset: { stage: s.key, status: s.status } }, el("div", { class: "dot" }, s.status === "completed" ? "✓" : s.status === "failed" ? "!" : String(i + 1)),
        el("div", {}, el("div", { class: "t" }, s.title), el("div", { class: "x" }, s.explanation), s.detail ? el("div", { class: "d small" }, s.detail) : null), el("div", { class: "when" }, STAGE_STATE[s.status] || s.status, s.finished_at ? el("div", {}, fmtTime(s.finished_at, false)) : null)))),
      j.error ? callout("bad", "Reconciliation failed", el("p", { class: "small" }, j.error)) : null,
      j.state === "completed" ? el("div", { class: "stack" }, facts([["Status", (CASE_STATUS[j.result.case_status] || [0, j.result.case_status])[1], null, j.result.case_status === "CLEAN" ? "ok" : "bad"],
        ["Total results", fmtNum(Object.values(j.result.outcomes).reduce((a, b) => a + b, 0))], ...Object.entries(j.result.outcomes).map(([k, v]) => [k, fmtNum(v), null, k === "PASS" ? "ok" : k === "FAIL" ? "bad" : ""]),
        ["Exceptions", fmtNum(j.result.exceptions), null, j.result.exceptions ? "bad" : "ok"]]), el("div", { class: "row" }, el("a", { class: "btn primary", id: "open-results", href: `#/runs/${j.run_id}` }, "Open results & exceptions"))) : null), { id: "recon-job" }) : null;
    const view = [pageHead({ eyebrow: "Reconciliation", title: `Reconcile ${pid}`, lead: "Runs the existing UC-042 reconciliation engine on exactly the versions in the active snapshot. Nothing is submitted and no audit pack is generated.", actions: [runBtn] }),
      facts([["Package", pid], ["Active snapshot", p.active_snapshot_id || "None"], ["Active evidence versions", String(snapCount)], ["Eligibility", eligible ? "Eligible" : "Not eligible", why || "active snapshot = current selection", eligible ? "ok" : "warn"]]),
      why ? el("div", { class: "section" }, callout("warn", "Reconciliation is not available", el("p", { class: "small" }, why), !p.active_snapshot_id ? el("a", { class: "btn sm", href: `#/validation/${pid}` }, "Package validation") : null)) : null,
      jobCard ? el("div", { class: "section" }, jobCard) : null,
      el("div", { class: "section" }, card("Previous runs", p.runs.length ? runsTable(p.runs) : empty("No reconciliation yet", "Runs of this package appear here."), { flush: true }))];
    main.replaceChildren(...view.filter(Boolean));
    if (j && (j.state === "running" || j.state === "queued")) poll(token, draw, 1200);
    else if (j) refreshShared();
  };
  await draw();
});
on(/^#\/results\/(PKG-[\w-]+)$/, async (main, token, pid) => {
  setPkg(pid);
  const p = await api("GET", `packages/${pid}`);
  if (p.runs.length) { location.replace(`#/runs/${p.runs[0].run_id}`); return; }
  renderChrome("results", [["Overview", "#/overview"], [pid, `#/packages/${pid}`], "Results"]);
  main.replaceChildren(pageHead({ eyebrow: "Reconciliation results", title: "No results yet" }), card(null, empty("This package has not been reconciled", "Activate the package and run the reconciliation to see its results and exceptions.", [el("a", { class: "btn primary", href: `#/reconciliation/${pid}` }, "Reconciliation")], "results")));
});

// ================================================================================================ Results + exceptions
on(/^#\/runs\/([\w.-]+?)(?:\/(exceptions|controls|report|inputs))?$/, async (main, token, rid, tab) => {
  const r = await api("GET", `runs/${rid}`);
  setPkg(r.package_id);
  tab = tab || "exceptions";
  renderChrome("results", [["Overview", "#/overview"], [r.package_id, `#/packages/${r.package_id}`], ["Reconciliation", `#/reconciliation/${r.package_id}`], rid]);
  const o = r.outcomes;
  const head = pageHead({ eyebrow: `Reconciliation results · ${r.snapshot_id}`, title: "Reconciliation results", lead: `${r.package_id} · run ${r.run_id} · executed ${fmtTime(r.executed_at)}`, actions: [cBadge(r.case_status)] });
  const cards = facts([["Reconciliation status", (CASE_STATUS[r.case_status] || [0, r.case_status])[1], null, r.case_status === "CLEAN" ? "ok" : r.case_status === "EXCEPTIONS_OPEN" ? "bad" : "warn"],
    ["Total controls", fmtNum(r.total_results)], ["Passed", fmtNum(o.PASS || 0), null, "ok"], ["Failed", fmtNum(o.FAIL || 0), null, o.FAIL ? "bad" : ""],
    ["Insufficient evidence", fmtNum(o.INSUFFICIENT_EVIDENCE || 0), null, o.INSUFFICIENT_EVIDENCE ? "warn" : ""], ["Not applicable", fmtNum(o.NOT_APPLICABLE || 0)],
    ["Exceptions", fmtNum(r.exception_count), Object.entries(r.by_severity).map(([k, v]) => `${v} ${k}`).join(" · "), r.exception_count ? "bad" : "ok"]]);
  const tabs = el("nav", { class: "tabs", "aria-label": "Result views" }, [["exceptions", "Exceptions", r.exception_count], ["controls", "Control results", r.total_results], ["report", "Validation report"], ["inputs", "Inputs & integrity", r.staged.length]].map(([k, l, n]) =>
    el("a", { href: `#/runs/${rid}${k === "exceptions" ? "" : "/" + k}`, class: tab === k ? "on" : null, "aria-current": tab === k ? "page" : null }, l, n != null ? el("span", { class: "n" }, fmtNum(n)) : null)));
  let body;
  if (tab === "exceptions") {
    const f = { severity: "", account_id: "", currency: "", status: "", q: "" };
    const tableBox = el("div");
    const sel = (key, label, opts) => { const s = el("select", { "aria-label": label, id: `f-${key}` }, el("option", { value: "" }, `All ${label.toLowerCase()}`), opts.map(x => el("option", { value: x }, x))); s.onchange = () => { f[key] = s.value; drawT(); }; return s; };
    const search = el("input", { type: "search", placeholder: "Search root cause / ID", "aria-label": "Search exceptions" }); search.oninput = () => { f.q = search.value.toLowerCase(); drawT(); };
    function drawT() {
      const rows = r.exceptions.filter(e => (!f.severity || e.severity === f.severity) && (!f.account_id || e.account_id === f.account_id) && (!f.currency || e.currency === f.currency) && (!f.status || e.status === f.status)
        && (!f.q || (e.root_cause + e.exception_id + e.category).toLowerCase().includes(f.q)));
      tableBox.replaceChildren(table([{ h: "Exception", v: e => el("b", { class: "mono" }, e.exception_id) }, { h: "Severity", v: e => sevBadge(e.severity) },
        { h: "Category / root cause", v: e => el("div", {}, el("div", {}, e.category), el("div", { class: "sub mono" }, e.root_cause)) },
        { h: "Account", v: e => e.account_id ? el("span", { class: "mono id" }, e.account_id) : "–" }, { h: "Ccy", v: e => e.currency || "–" },
        { h: "Period", v: e => e.first_date ? (e.last_date && e.last_date !== e.first_date ? `${e.first_date} → ${e.last_date}` : e.first_date) : "–" },
        { h: "Amount", cls: "num", v: e => e.amount ? el("span", { class: `amount ${e.amount.startsWith("-") ? "neg" : ""}` }, e.amount) : "–" },
        { h: "Results", cls: "num", v: e => e.affected_results }, { h: "Evidence", v: e => el("span", { class: "small muted" }, `${(e.evidence || "").split(";").filter(x => x.trim()).length} reference(s)`) },
        { h: "Status", v: e => el("div", {}, badge("neutral plain", e.status || "–"), e.review_status ? el("div", { class: "sub" }, e.review_status) : null) }],
        rows, { onRow: e => { location.hash = `#/runs/${rid}/exceptions/${e.exception_id}`; }, emptyText: r.exception_count ? "No exception matches the filters." : "The engine reported no exceptions." }));
    }
    drawT();
    body = card(null, el("div", {}, r.exception_count ? el("div", { class: "toolbar" }, sel("severity", "Severities", r.filters.severity), sel("account_id", "Accounts", r.filters.account_id), sel("currency", "Currencies", r.filters.currency), sel("status", "Statuses", r.filters.status), el("span", { class: "grow" }), search) : null,
      r.exception_count ? tableBox : empty("No exceptions", "The UC-042 engine reported no exceptions for this snapshot.", [], "check")), { flush: true });
  } else if (tab === "controls") {
    const box = el("div"); const st = { outcome: "", check: "" };
    const outSel = el("select", { "aria-label": "Outcome" }, el("option", { value: "" }, "All outcomes"), Object.keys(o).map(k => el("option", { value: k }, `${k} (${o[k]})`)));
    const chk = el("input", { type: "search", placeholder: "Filter check ID (e.g. C08)", "aria-label": "Filter check" });
    const load = async () => { const q = new URLSearchParams({ outcome: st.outcome, check: st.check }); const c = await api("GET", `runs/${rid}/controls?${q}`); if (!live(token)) return;
      box.replaceChildren(el("div", { class: "toolbar" }, outSel, chk, el("span", { class: "grow" }), el("span", { class: "muted small" }, `${fmtNum(c.total)} result(s)${c.truncated ? " · first 2,000 shown" : ""}`)),
        table([{ h: "Check", v: x => el("b", { class: "mono" }, x.check_id) }, { h: "Control", v: x => x.control }, { h: "Scope", v: x => el("span", { class: "mono small" }, x.scope) }, { h: "Outcome", v: x => outcomeBadge(x.outcome) },
          { h: "Computed", v: x => el("span", { class: "small" }, x.computed) }, { h: "Reported", v: x => el("span", { class: "small" }, x.reported) }, { h: "Note", v: x => el("span", { class: "small muted" }, short(x.note, 140)) }], c.rows)); };
    outSel.onchange = () => { st.outcome = outSel.value; load(); }; chk.onchange = () => { st.check = chk.value.trim(); load(); };
    await load();
    body = card(null, box, { flush: true });
  } else if (tab === "report") {
    const md = await api("GET", `runs/${rid}/report`);
    body = card("VALIDATION_REPORT.md", renderMarkdown(md), { sub: "written by the UC-042 engine" });
  } else {
    body = el("div", { class: "stack" }, card("Adapter integrity checks", table([{ h: "Check", v: x => x[0] }, { h: "Result", v: x => badge(x[1] ? "ok" : "bad", x[1] ? "PASS" : "FAIL") }], Object.entries(r.integrity_checks)), { flush: true }),
      card("Staged evidence (exactly the snapshot's versions)", table([{ h: "Category", v: s => el("b", {}, s.evidence_category) }, { h: "Version", v: s => el("span", {}, el("span", { class: "mono small" }, s.file_version_id), ` · v${s.version_number}`) },
        { h: "Original file", v: s => el("span", { class: "mono small" }, s.original_filename) }, { h: "Staged as", v: s => s.staged_kind }, { h: "Engine intake", v: s => el("span", {}, badge(s.engine_decision === "ACCEPTED" ? "ok" : "bad", s.engine_decision || "–"), " ", el("span", { class: "mono xs" }, s.engine_canonical_name || "")) },
        { h: "Exact bytes", v: s => badge(s.engine_received_exact_bytes ? "ok" : "bad", s.engine_received_exact_bytes ? "Yes" : "No") }], r.staged), { flush: true }),
      card("Engine", kv([["Implementation", r.engine.implementation], ["Period", r.engine.period], ["Return code", String(r.engine.returncode)], ["Submission", r.submission]])));
  }
  if (live(token)) main.replaceChildren(head, cards, el("div", { class: "section" }, tabs, body));
});
on(/^#\/runs\/([\w.-]+?)\/exceptions\/([\w-]+)$/, async (main, token, rid, xid) => {
  const [r, d] = await Promise.all([api("GET", `runs/${rid}`), api("GET", `runs/${rid}/exceptions/${xid}`)]);
  setPkg(r.package_id);
  renderChrome("results", [["Overview", "#/overview"], [r.package_id, `#/packages/${r.package_id}`], [rid, `#/runs/${rid}`], xid]);
  const e = d.exception;
  const ev = d.evidence;
  const view = [pageHead({ eyebrow: `Exception · ${r.run_id}`, title: `${e.exception_id} · ${e.category}`, lead: e.root_cause, actions: [sevBadge(e.severity), badge("neutral plain", e.status)] }),
    facts([["Financial impact", e.amount ? `${e.amount} ${e.currency || ""}` : "–", e.amount ? "as computed by the engine" : "no amount for this root cause", e.amount && e.amount.startsWith("-") ? "bad" : ""],
      ["Affected account", e.account_id || "–"], ["Relevant dates", e.first_date ? (e.last_date && e.last_date !== e.first_date ? `${e.first_date} → ${e.last_date}` : e.first_date) : "–"],
      ["Affected results", e.affected_results], ["Evidence references", String(ev.length)]]),
    el("div", { class: "section grid2" },
      card("Exception description", kv([["Category", e.category], ["Root cause", el("span", { class: "mono small" }, e.root_cause)], ["Cause category", e.cause_category || "–"], ["Flags", e.flags || "–"],
        ["Related records", e.related_records || "–"], ["Evidence status", e.evidence_status ? `${e.evidence_status}${e.evidence_status_detail ? " - " + e.evidence_status_detail : ""}` : "–"],
        ["Review status (engine)", e.review_status || "–"], ["Investigation group", e.investigation_group_id || "–"]])),
      callout("info", "Engine output, not a decision", el("p", { class: "small" }, d.note), el("p", { class: "small" }, "Investigation decisions, resolutions and audit packs are outside this application."))),
    el("div", { class: "section" }, card("Supporting evidence", ev.length ? table([{ h: "Reference", v: x => el("span", { class: "mono small" }, x.reference) },
      { h: "Category", v: x => x.evidence_category || "–" }, { h: "Source file (version)", v: x => x.original_filename ? el("div", {}, el("div", { class: "mono small" }, x.original_filename), el("div", { class: "sub" }, `v${x.version_number} · ${x.file_version_id}`)) : "–" },
      { h: "Line", cls: "num", v: x => x.line ? String(x.line) : "file" }, { h: "Row as reconciled", v: x => x.row ? rowPeek(x.row) : el("span", { class: "subtle small" }, x.line ? "–" : "whole document") },
      { h: "Source SHA-256", v: x => hash(x.source_sha256) }], ev) : el("p", { class: "muted small" }, "No evidence reference recorded."), { flush: true, sub: "resolved to the snapshot's file versions; rows read from the canonical input the engine received" })),
    el("div", { class: "section" }, card("Associated control results", table([{ h: "Check", v: a => el("b", { class: "mono" }, a.check_id || "–") }, { h: "Scope", v: a => el("span", { class: "mono small" }, a.scope || a.text) },
      { h: "Outcome", v: a => a.outcome ? outcomeBadge(a.outcome) : "–" }, { h: "Computed", v: a => a.control_result ? el("span", { class: "small" }, a.control_result.computed) : "–" },
      { h: "Reported", v: a => a.control_result ? el("span", { class: "small" }, a.control_result.reported) : "–" }, { h: "Note", v: a => a.control_result ? el("span", { class: "small muted" }, short(a.control_result.note, 160)) : "–" }], d.affected_control_results), { flush: true })),
    d.investigation_group ? el("div", { class: "section" }, card("Investigation group (engine)", kv(Object.entries(d.investigation_group).map(([k, v]) => [k, el("span", { class: "small" }, v)])))) : null,
    el("div", { class: "section" }, el("a", { class: "btn", href: `#/runs/${rid}` }, "← All exceptions"))];
  if (live(token)) main.replaceChildren(...view.filter(Boolean));
});
function rowPeek(row) {
  // the referenced canonical row: three identifying / financial fields inline, every field on demand
  const keys = Object.keys(row);
  const pick = keys.filter(k => /(_id|amount|balance|date|_ts|currency|difference)/.test(k)).slice(0, 3);
  return el("details", { class: "rowpeek" }, el("summary", {}, pick.map(k => el("span", { class: "chip", title: `${k}: ${row[k]}` }, `${k}=${row[k]}`))),
    kv(keys.map(k => [k, el("span", { class: "mono" }, row[k] === "" ? "(empty)" : row[k])])));
}
function renderMarkdown(md) {
  // minimal, safe renderer: every text node via textContent (headings, tables, lists, bold, code)
  const root = el("div", { class: "md" });
  const inline = s => { const out = []; const re = /(\*\*[^*]+\*\*|`[^`]+`)/g; let i = 0, m; while ((m = re.exec(s))) { out.push(s.slice(i, m.index)); out.push(m[0].startsWith("**") ? el("b", {}, m[0].slice(2, -2)) : el("code", {}, m[0].slice(1, -1))); i = m.index + m[0].length; } out.push(s.slice(i)); return out; };
  const lines = md.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^#{1,4} /.test(l)) { const n = l.match(/^#+/)[0].length; root.append(el(`h${Math.min(n + 0, 3)}`, {}, inline(l.slice(n + 1)))); continue; }
    if (l.startsWith("|")) {
      const rows = []; while (i < lines.length && lines[i].startsWith("|")) { rows.push(lines[i]); i++; } i--;
      const cells = r => r.replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const body = rows.filter((r, k) => k !== 1 || !/^\|[\s:|-]+\|$/.test(r));
      const t = el("table", {}, el("thead", {}, el("tr", {}, cells(body[0]).map(c => el("th", {}, inline(c))))), el("tbody", {}, body.slice(1).map(r => el("tr", {}, cells(r).map(c => el("td", {}, inline(c)))))));
      root.append(el("div", { class: "table-wrap" }, t)); continue;
    }
    if (/^[-*] /.test(l)) { const ul = el("ul"); while (i < lines.length && /^[-*] /.test(lines[i])) { ul.append(el("li", {}, inline(lines[i].slice(2)))); i++; } i--; root.append(ul); continue; }
    if (l.trim()) root.append(el("p", {}, inline(l)));
  }
  return root;
}

// ================================================================================================ Activity
const EVENT_LABEL = { PACKAGE_CREATED: "Package created", PACKAGE_FILE_RECEIVED: "File received", FILE_VERSION_CREATED: "File version created", FILE_VERSION_VALIDATED: "File validated",
  FILE_VERSION_REVIEW_REQUIRED: "Routed to analyst review", RESUBMISSION_REQUESTED: "Corrected file requested", RESUBMISSION_RECEIVED: "Corrected file received", FILE_VERSION_REJECTED: "File rejected",
  FILE_VERSION_ACTIVATED: "File version activated", FILE_VERSION_SUPERSEDED: "File version superseded", REPROCESSED: "Deterministic (re)processing", HANDOFF_EVALUATED: "Handoff checks evaluated",
  HANDOFF_PREVIEW_WRITTEN: "Canonical preview written", INTAKE_CASE_OPENED: "Column review case opened", INTAKE_DECISION: "Analyst column decision", INTAKE_CASE_RESOLVED: "Column review resolved",
  INTAKE_CASE_HELD: "Column review held", INTAKE_CASE_REJECTED: "Column review rejected", PROVIDER_CALL: "Mapping proposal requested", PROPOSAL_REVIEW_OPENED: "Proposal review opened",
  COLUMN_DECIDED: "Analyst column decision", PROPOSAL_APPROVED: "Proposal approved by analyst", PROPOSAL_REJECTED: "Proposal rejected", CATEGORY_CONFIRMED: "Category confirmed",
  RULE_CREATED: "File mapping rule created", RULE_ACTIVATED: "File mapping rule activated", PACKAGE_VALIDATION_STARTED: "Package validation started", PACKAGE_VALIDATED: "Package validation passed",
  PACKAGE_VALIDATION_FAILED: "Package validation failed", PACKAGE_SNAPSHOT_CREATED: "Snapshot created", PACKAGE_SNAPSHOT_ACTIVATED: "Package activated", RECONCILIATION_INPUT_STAGED: "Reconciliation initiated (inputs staged)",
  RECONCILIATION_EXECUTED: "Reconciliation completed", RECONCILIATION_FAILED: "Reconciliation failed" };
const eventKind = t => /RECONCILIATION/.test(t) ? "k-recon" : /FAILED|REJECTED|RESUBMISSION_REQUESTED/.test(t) ? "k-bad" : /VALIDATED$|ACTIVATED|APPROVED|RESOLVED/.test(t) ? "k-ok" : /DECISION|DECIDED|REVIEW|CASE/.test(t) ? "k-review" : /PACKAGE/.test(t) ? "k-package" : "";
function eventList(events) {
  if (!events.length) return el("p", { class: "muted small", style: null }, "No recorded events.");
  const ul = el("ul", { class: "timeline" });
  let day = null;
  for (const e of events) {
    const dd = (e.at || "").slice(0, 10);
    if (dd !== day) { day = dd; ul.append(el("li", { class: "day" }, new Date(e.at).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "long", year: "numeric" }))); }
    const det = e.details || {};
    const ids = [det.evidence_category || det.category, det.file_version_id, det.snapshot_id, det.run_id, det.validation_id].filter(Boolean);
    ul.append(el("li", { class: `tl ${eventKind(e.event_type)}`, dataset: { type: e.event_type } }, el("div", { class: "tm" }, fmtTime(e.at, false)), el("div", { class: "mk" }),
      el("div", {}, el("div", {}, el("span", { class: "what" }, EVENT_LABEL[e.event_type] || e.event_type), el("span", { class: "mono xs muted" }, `  #${e.seq} ${e.event_type}`)),
        el("div", { class: "who" }, `${e.actor_id || "system"}${e.actor_role ? ` (${e.actor_role})` : ""}`, ids.length ? ` · ${ids.join(" · ")}` : "", det.filename ? ` · ${det.filename}` : "", det.reason ? ` · ${short(det.reason, 120)}` : ""),
        el("details", {}, el("summary", {}, "Recorded details"), el("pre", {}, JSON.stringify({ seq: e.seq, event_id: e.event_id, intake_id: e.intake_id, source_sha256: e.source_sha256, hash: e.hash, details: det }, null, 1))))));
  }
  return ul;
}
on(/^#\/activity\/?(PKG-[\w-]+)?$/, async (main, token, pid) => {
  if (pid) setPkg(pid);
  const a = await api("GET", `activity${pid ? `?package_id=${encodeURIComponent(pid)}` : ""}`);
  renderChrome("activity", [["Overview", "#/overview"], "Activity & audit trail"]);
  const types = [...new Set(a.events.map(e => e.event_type))].sort();
  const box = el("div");
  const typeSel = el("select", { "aria-label": "Event type" }, el("option", { value: "" }, "All event types"), types.map(t => el("option", { value: t }, EVENT_LABEL[t] || t)));
  const draw = () => box.replaceChildren(eventList(a.events.filter(e => !typeSel.value || e.event_type === typeSel.value)));
  typeSel.onchange = draw; draw();
  const scope = el("select", { "aria-label": "Scope" }, el("option", { value: "", selected: !pid }, "All packages"), S.packages.map(p => el("option", { value: p.package_id, selected: p.package_id === pid }, p.package_id)));
  scope.onchange = () => { location.hash = `#/activity/${scope.value}`; };
  const view = [pageHead({ eyebrow: "Governance", title: "Activity & audit trail", lead: "Every entry below is a recorded event from the hash-chained audit log. Nothing on this page is generated by the browser.",
      actions: [a.chain.verified ? badge("ok", `Hash chain verified · ${fmtNum(a.chain.events)} events`) : badge("bad", "Hash chain NOT verified")] }),
    !a.chain.verified ? callout("bad", "Audit chain verification failed", el("p", { class: "small" }, a.chain.error)) : null,
    card(null, el("div", {}, el("div", { class: "toolbar" }, scope, typeSel, el("span", { class: "grow" }), el("span", { class: "muted small" }, `${fmtNum(a.events.length)} event(s) shown`)),
      el("div", { class: "legend", style: null }, ""), box), { flush: true })];
  if (live(token)) main.replaceChildren(...view.filter(Boolean));
});

router();
