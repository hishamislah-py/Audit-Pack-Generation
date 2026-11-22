// Phase 3B-11 POC mapping review screen. Renders ONLY what the backend returns; every action is a POST to the API,
// which forwards to PackageService / the existing review functions. Untrusted text (CSV headers, reasons) is always
// inserted with textContent, never as HTML.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
const badge = (text, kind) => el("span", { class: `badge b-${kind}` }, text);
const VALIDATION_KIND = { CLEAR: "ok", DETERMINISTIC: "ok", PLAUSIBLE: "warn", AMBIGUOUS: "warn",
  NO_MATCH: "bad", CONFLICT_INCOMPLETE: "bad", NO_SUGGESTION: "mute" };
const STATUS_KIND = { VALIDATED: "ok", ACTIVE: "ok", REVIEW_REQUIRED: "warn", RESUBMISSION_REQUIRED: "bad",
  FAILED_VALIDATION: "bad", REJECTED: "bad", SUPERSEDED: "mute" };

async function api(method, path, body) {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined });
  const doc = await res.json();
  if (!res.ok) throw Object.assign(new Error(doc.message || res.statusText), { code: doc.error, status: res.status });
  return doc;
}

function showError(err) {
  const box = $("#error");
  if (!err) { box.hidden = true; box.textContent = ""; return; }
  box.hidden = false;
  box.textContent = `${err.code || "ERROR"}: ${err.message}`;
}

// ------------------------------------------------------------------------------------------------ queue
async function renderQueue() {
  $("#queue-view").hidden = false; $("#review-view").hidden = true;
  const rows = await api("GET", "/api/reviews");
  const body = $("#queue tbody"); body.replaceChildren();
  $("#queue-empty").hidden = rows.length > 0;
  for (const r of rows) {
    body.append(el("tr", { class: "clickable", "data-vid": r.file_version_id,
      onclick: () => { location.hash = `#/review/${r.package_id}/${r.file_version_id}`; } },
      el("td", { class: "mono" }, r.package_id), el("td", {}, r.reporting_period),
      el("td", {}, r.evidence_category), el("td", {}, r.original_filename), el("td", {}, `v${r.version_number}`),
      el("td", {}, `${r.incoming_header_count ?? "–"} / ${r.expected_field_count}`),
      el("td", {}, badge(r.review_kind, "info")), el("td", { class: "note" }, r.review_reason)));
  }
}

// ------------------------------------------------------------------------------------------------ review
let current = null;

async function renderReview(pid, vid) {
  $("#queue-view").hidden = true; $("#review-view").hidden = false;
  current = { pid, vid };
  draw(await api("GET", `/api/review/${encodeURIComponent(pid)}/${encodeURIComponent(vid)}`));
}

function draw(d) {
  document.body.dataset.renders = String((+document.body.dataset.renders || 0) + 1);  // render counter (tests)
  const info = $("#info"); info.replaceChildren();
  const item = (k, v, cls) => el("div", { class: cls }, el("div", { class: "k" }, k), el("div", { class: "v" }, v));
  info.append(
    item("Package", d.package_id), item("Reporting period", d.reporting_period),
    item("Evidence category", `${d.evidence_category} · ${d.category_title}`),
    item("File / version", `${d.original_filename} · v${d.version_number}`),
    item("Columns (incoming / canonical)", `${d.incoming_header_count ?? "–"} / ${d.expected_field_count}`),
    item("Source SHA-256", el("span", { class: "mono", title: d.source_sha256 }, `${d.source_sha256_short}…`)),
    item("Review", el("span", {}, badge(d.review_kind || "–", "info"), " ", badge(d.review_state || "–", "mute"))),
    item("Version status", badge(d.version_status, STATUS_KIND[d.version_status] || "mute")),
    item("Review reason", d.review_reason, "wide"));

  const fields = d.canonical_fields.map(f => f.name);
  const body = $("#mapping tbody"); body.replaceChildren();
  for (const r of d.rows) {
    const dec = r.decision;
    const decCell = dec
      ? el("div", { class: "decision" }, badge(dec.action, dec.action === "LEAVE_UNRESOLVED" || dec.action === "LEAVE_UNMAPPED" ? "warn" : dec.action === "IGNORE_COLUMN" ? "mute" : "ok"),
          " ", dec.canonical_field ? el("span", { class: "mono" }, dec.canonical_field) : "",
          dec.reason ? el("div", { class: "r" }, dec.reason) : null)
      : badge("undecided", "warn");
    const proposed = el("div", {}, r.suggested_field ? el("span", { class: "mono" }, r.suggested_field) : el("em", {}, "Unmapped"),
      el("div", { class: "note" }, `basis: ${r.suggestion_basis}` + (r.proposal_assessment ? ` · LLM said ${r.proposal_assessment}` : "")),
      r.note ? el("div", { class: "note" }, r.note) : null,
      r.duplicate_claim ? el("div", { class: "note" }, `claims ${r.duplicate_claim} together with another column`) : null,
      r.same_header_positions.length ? el("div", { class: "note" }, `same header text at #${r.same_header_positions.map(p => p + 1).join(", #")}`) : null);
    let actions = el("span", { class: "note" }, "read-only");
    if (d.editable && !r.read_only) {
      const sel = el("select", { class: "field", "aria-label": `canonical field for column ${r.source_position}` },
        el("option", { value: "" }, "— field —"), ...fields.map(f => el("option", { value: f, selected: f === r.suggested_field }, f)));
      const why = el("input", { class: "reason", placeholder: "reason (ignore / leave)" });
      const act = (action) => () => decide(r, action, sel.value, why.value);
      const btns = [el("button", { "data-action": "MAP", disabled: !r.suggested_field, onclick: act("MAP") }, "Map"),
        el("button", { "data-action": "CHANGE", onclick: act("CHANGE") }, "Change")];
      if (d.actions.includes("CHOOSE_DUPLICATE_SOURCE") && (r.duplicate_claim || r.same_header_positions.length))
        btns.push(el("button", { "data-action": "CHOOSE_DUPLICATE_SOURCE", onclick: act("CHOOSE_DUPLICATE_SOURCE") }, "Use this source"));
      if (d.actions.includes("IGNORE_COLUMN"))
        btns.push(el("button", { "data-action": "IGNORE_COLUMN", onclick: act("IGNORE_COLUMN") }, "Ignore"));
      btns.push(el("button", { "data-action": "LEAVE_UNRESOLVED", onclick: act("LEAVE_UNRESOLVED") }, "Leave unresolved"));
      actions = el("div", { class: "actions" }, sel, why, ...btns);
    }
    body.append(el("tr", { "data-idx": r.source_index },
      el("td", {}, r.source_position), el("td", { class: "mono" }, r.source_header), el("td", {}, proposed),
      el("td", {}, badge(r.validation, VALIDATION_KIND[r.validation] || "mute")), el("td", {}, decCell), el("td", {}, actions)));
  }

  const s = d.summary || {};
  const sm = $("#summary"); sm.replaceChildren();
  const kv = el("div", { class: "kv" });
  const add = (k, v) => kv.append(el("div", { class: "k" }, k), el("div", {}, v));
  add("Decisions made", `${s.decided ?? 0} of ${d.rows.length}`);
  add("Outstanding columns", (s.outstanding || []).length ? s.outstanding.map(i => `#${i + 1}`).join(", ") : "none");
  add("Required fields not covered", (s.required_not_covered || []).length ? s.required_not_covered.join(", ") : "none");
  add("Ignored columns", (s.ignored || []).length ? s.ignored.map(x => `#${x.source_index + 1} (${x.reason})`).join("; ") : "none");
  add("Left unresolved", (s.unresolved || []).length ? s.unresolved.map(i => `#${i + 1}`).join(", ") : "none");
  if (d.duplicate_incoming_headers && Object.keys(d.duplicate_incoming_headers).length)
    add("Duplicate headers", JSON.stringify(d.duplicate_incoming_headers));
  if (s.content_classification) add("Category conflict", `content identifies as ${s.content_classification.category}`);
  const willHold = (s.outstanding || []).length === 0 && ((s.required_not_covered || []).length || (s.unresolved || []).length);
  add("Finalisation", (s.outstanding || []).length ? "not possible yet: decide every column"
    : willHold ? "completing now will HOLD the file (required field not covered or column left unresolved)"
    : "ready: completing will write the file-specific mapping and reprocess the original");
  sm.append(kv);

  $("#finalise").hidden = !d.editable; $("#toolbar").hidden = !d.editable;
  drawOutcome(d.outcome);
}

function drawOutcome(o) {
  const box = $("#outcome"); box.replaceChildren();
  const kv = el("div", { class: "kv" });
  const add = (k, v) => kv.append(el("div", { class: "k" }, k), el("div", {}, v));
  add("Version status", el("span", { id: "outcome-status" }, badge(o.version_status, STATUS_KIND[o.version_status] || "mute")));
  add("Processing", o.processing_status);
  add("Deterministic reprocessing", o.reprocessed ? badge("completed", "ok") : badge("not run", "mute"));
  add("Handoff eligible", o.handoff ? (o.handoff.eligible ? badge("yes", "ok") : badge("no", "bad")) : "–");
  add("Canonical preview", o.preview_generated
    ? el("a", { href: `/api/review/${encodeURIComponent(current.pid)}/${encodeURIComponent(current.vid)}/preview`, target: "_blank" }, "generated (open CSV)")
    : badge("none", "mute"));
  if (o.handoff && o.handoff.provenance) add("Provenance sidecar", el("span", { class: "mono" }, o.handoff.provenance));
  add("Eligible for package activation", o.eligible_for_package_activation ? badge("yes", "ok") : badge("no", "warn"));
  add("Package status", o.package_status);
  if ((o.missing_fields || []).length) add("Missing fields", o.missing_fields.join(", "));
  add("Latest reasons", (o.reasons || []).join(" | "));
  box.append(kv);
  if (o.handoff && o.handoff.checks && o.handoff.checks.length) {
    const t = el("table", { class: "grid checks", id: "checks" },
      el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Handoff check"), el("th", {}, "Result"), el("th", {}, "Detail"))));
    const tb = el("tbody");
    for (const c of o.handoff.checks)
      tb.append(el("tr", {}, el("td", {}, c.id), el("td", {}, c.name), el("td", {}, badge(c.passed ? "PASS" : "FAIL", c.passed ? "ok" : "bad")), el("td", { class: "note" }, c.detail)));
    t.append(tb); box.append(t);
  }
}

async function post(path, body) {
  showError(null);
  try { draw(await api("POST", `/api/review/${encodeURIComponent(current.pid)}/${encodeURIComponent(current.vid)}/${path}`, body)); }
  catch (e) { showError(e); }
}

function decide(r, action, field, reason) {
  const why = (reason || "").trim() || $("#default-reason").value.trim();
  const body = { action, source_index: r.source_index, reason: why };
  if (action === "CHANGE" || action === "CHOOSE_DUPLICATE_SOURCE") body.canonical_field = field || r.suggested_field;
  if (action === "CHOOSE_DUPLICATE_SOURCE") body.others_reason = why;
  if ((action === "IGNORE_COLUMN") && !(reason || "").trim()) { showError({ code: "REASON_REQUIRED", message: "type a reason in the row to ignore a column" }); return; }
  return post("decision", body);
}

$("#map-all").addEventListener("click", async () => {
  const d = await api("GET", `/api/review/${encodeURIComponent(current.pid)}/${encodeURIComponent(current.vid)}`);
  for (const r of d.rows) if (!r.decision && !r.read_only && r.suggested_field && r.validation !== "NO_MATCH")
    await decide(r, "MAP", r.suggested_field, "");
});
$("#complete").addEventListener("click", () => post("complete", { basis: $("#basis").value }));
$("#reject").addEventListener("click", () => post("reject", { reason: $("#reject-reason").value }));

async function route() {
  showError(null);
  const m = location.hash.match(/^#\/review\/([^/]+)\/([^/]+)$/);
  try { if (m) await renderReview(decodeURIComponent(m[1]), decodeURIComponent(m[2])); else await renderQueue(); }
  catch (e) { $("#queue-view").hidden = true; $("#review-view").hidden = false; showError(e); }
}
window.addEventListener("hashchange", route);
api("GET", "/api/identity").then(i => { $("#identity").textContent = `Reviewer ${i.reviewer_id} (${i.role}, ${i.kind}) · policy ${i.authority_policy} · no authentication (POC)`; });
route();
