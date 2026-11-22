/* ==========================================================================
   MOCK data service (temporary) · same methods and payload shapes as
   httpService.js / RINGFENCE_FRONTEND_API_CONTRACT.md, served from memory in
   the browser. It calls no backend: processing is simulated with timers and
   the demo data is synthetic (mockData.js). Lifecycle rules here only imitate
   the backend so the screens can be exercised; the backend owns them.
   ========================================================================== */
import M from './mockData.js';
import { assertDataService } from './dataService.js';

const clone = (o) => (o == null ? o : JSON.parse(JSON.stringify(o)));
const iso = (ms) => new Date(ms).toISOString().replace('.000Z', '+00:00').replace(/\.\d{3}Z$/, '+00:00');
const pad = (n, w) => String(n).padStart(w || 2, '0');
function hex(seed, len) { let out = '', h = 2166136261; for (let r = 0; out.length < len; r++) { for (let i = 0; i < seed.length; i++) { h ^= seed.charCodeAt(i) + r; h = Math.imul(h, 16777619) >>> 0; } out += h.toString(16).padStart(8, '0'); } return out.slice(0, len); }
const fail = (status, error, message) => { throw { status, error, message }; };
const CLOSURE_MOCK = 'Audit packs, AI investigations and final packs need the Ringfence backend. The mock data service does not simulate them.';
const at = (s) => Date.parse(s + (s.length === 16 ? ':00' : '') + 'Z');

// Categories IN-01…IN-19 with the design's titles (the backend's GET /api/app is the source in production)
const CATS = M.categories.map((c, i) => ({ category: 'IN-' + pad(i + 1), code: c.code, title: c.label, required: c.required, format: c.type }));
const catByCode = (code) => CATS.find((c) => c.code === code);
const catById = (id) => CATS.find((c) => c.category === id);
const STAGES = [['init', 'Initialise evidence package', 'Create the package from the original ZIP and verify its SHA-256 against the intake record.'], ['read', 'Read ZIP contents', 'Read the archive index and every entry.'], ['identify', 'Identify and classify evidence files', 'Separate evidence from unsupported entries and match each file to the 19 categories.'], ['structure', 'Check file structures', 'Encoding, delimiter, header row and column counts of classified CSVs.'], ['mapping', 'Map recognised CSV columns', 'Compare source headers with canonical schemas (exact names, approved aliases).'], ['proposals', 'Generate proposals for unresolved mappings', 'Recorded proposals where enabled. Never applied without an analyst decision.'], ['review', 'Prepare human review', 'List only the columns that need an analyst decision.'], ['previews', 'Generate canonical previews and provenance', 'Canonical previews with source row and column references.'], ['validation', 'Run package validation', 'Evaluate PV-01…PV-09 once processing and the required reviews are complete.']];
const REVIEW_SETS = { clean: { v1: ['MR-02', 'MR-06'] }, correction: { v1: ['MR-01', 'MR-02', 'MR-06', 'MR-08'], v2: ['MR-02', 'MR-06'] }, exceptions: { v1: ['MR-03', 'MR-04', 'MR-05', 'MR-09'] } };
const BANK_FIELDS = [['booking_date', 'date', true], ['value_date', 'date', false], ['amount', 'decimal', true], ['currency', 'code', true], ['credit_debit_indicator', 'enum', true], ['transaction_id', 'string', false], ['bank_reference', 'string', false], ['remittance_information', 'string', false], ['counterparty_name', 'string', false], ['transaction_type', 'enum', false], ['running_balance', 'decimal', false]];

export function createMockService(opts) {
  const o = Object.assign({ latency: 220 }, opts || {});
  const BASE = Date.UTC(2026, 10, 19, 10, 41, 0), T0 = Date.now();
  const now = () => BASE + (Date.now() - T0);
  let st, seq;
  const controls = { failNextRun: false, failNextRecon: false, speed: 1 };
  const analyst = { reviewer_id: 'elena.marsh', name: M.analyst.name, role: 'analyst', kind: 'TEST' };

  function reset() {
    st = { cases: {}, order: [], customers: [], staging: {}, jobs: {}, recons: {}, snapCount: 0 };
    seq = { case: {}, job: 1000, fv: 5000, recon: 300, stg: 1 };
    M.customers.forEach((c) => st.customers.push({ customer_id: c.id, customer_name: c.name, code: c.code }));
    seed();
  }

  /* ---------- helpers ---------- */
  const C = (ref) => st.cases[ref] || fail(404, 'NOT_FOUND', 'Case ' + ref + ' not found.');
  const slotCase = () => Object.values(st.cases).find((c) => c.status === 'IN_PROGRESS') || null;
  const audit = (c, t, type, details, actor) => { c.events.push({ seq: c.events.length + 1, event_id: 'EV-' + hex(c.case_ref + type + t + c.events.length, 10), event_type: type, at: iso(t), actor_id: actor === 'system' ? 'system' : analyst.reviewer_id, actor_role: actor === 'system' ? 'system' : 'analyst', intake_id: null, source_sha256: null, details: details || {} }); c.last_activity_at = t; c.revision++; };
  const setStatus = (c, status, t, note) => { c.status = status; c.status_since = t; c.status_history.push({ status, at: iso(t), note }); };
  const latestRun = (c) => c.runs[c.runs.length - 1] || null;
  const versions = (c) => (c.pkg ? Object.values(c.pkg.slots).map((s) => s.versions[s.versions.length - 1]).filter(Boolean) : []);
  const allJobsRunning = (c) => c.jobs.filter((j) => j.state === 'running' || j.state === 'queued');
  const rowRemaining = (v) => (v.review ? v.review.rows.filter((r) => r.needs_attention && !r.decided).length : 0);
  const ms = (base) => base / (controls.speed || 1);

  /* ---------- registration ---------- */
  function register(q, t, extra) {
    if (!q.customer_name || !/^\d{4}-\d{2}$/.test(q.reporting_period || '')) fail(400, 'INVALID', 'Customer name and a reporting period in YYYY-MM are required.');
    if (!/\.zip$/i.test(q.zip_name || '')) fail(400, 'NOT_A_ZIP', 'The file name must end in .zip.');
    let cu = q.customer_id ? st.customers.find((x) => x.customer_id === q.customer_id) : st.customers.find((x) => x.customer_name === q.customer_name);
    if (!cu) { cu = { customer_id: 'CUS-' + (1013 + st.customers.length), customer_name: q.customer_name, code: q.customer_name.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase() }; st.customers.push(cu); }
    const ym = q.reporting_period.split('-'); const key = ym[0] + '-' + ym[1]; seq.case[key] = (seq.case[key] || 0) + 1;
    const ref = (extra && extra.ref) || 'RF-' + key + '-' + pad(seq.case[key], 3);
    const size = q.zip_size || Math.round((q.zip_b64 || '').length * 0.75) || 1048576;
    const c = { case_ref: ref, customer_id: cu.customer_id, customer_name: cu.customer_name, code: cu.code, reporting_period: q.reporting_period, created_at: t, status: 'WAITING', status_since: t, revision: 1, last_activity_at: t,
      zip: { filename: q.zip_name, size, sha256: hex(ref + q.zip_name + size, 64) }, scenario: (extra && extra.scenario) || q.mock_scenario || { evidence: 'clean', recon: 'clean' },
      deferring: false, deferral: null, deferred_at: null, started: null, completed: null, runs: [], pkg: null, activation: null, status_history: [], events: [], jobs: [], recons: [], refused: [], uploadsByRun: {} };
    st.cases[ref] = c; st.order.push(ref);
    setStatus(c, 'WAITING', t, 'Case registered with the original ZIP');
    audit(c, t, 'CASE_CREATED', { zip_name: q.zip_name, zip_sha256: c.zip.sha256, size });
    return c;
  }

  /* ---------- evidence produced by the simulated Smart Parser ---------- */
  function zipFiles(c) {
    const ev = c.scenario.evidence, period = c.reporting_period.replace('-', '').slice(2, 6);
    const tok = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'][+c.reporting_period.slice(5) - 1] + c.reporting_period.slice(2, 4);
    const list = M.files.filter((f) => f.category).map((f) => ({ code: f.category, name: f.name.replace(/^HBL_/, c.code + '_').replace(/oct26/g, tok), type: f.type, structure_error: null, review: null, period }));
    const bank = list.find((f) => f.code === 'BANK_STATEMENT_TRANSACTIONS'); bank.review = ((c.scenario.items || REVIEW_SETS[ev]) || {}).v1 || [];
    const fx = list.find((f) => f.code === 'FX_CONVERSIONS'); if (ev === 'correction') fx.structure_error = 'Row 1,204 has 9 fields; the header has 11.';
    if (ev !== 'correction') list.push({ code: 'FUNDS_IN_TRANSIT', name: c.code + '_funds_in_transit_' + tok + '.csv', type: 'CSV', review: null });
    return { files: list, skipped: [{ name: c.code + '_ops_notes_' + tok + '.csv', reason: 'No category signature matched' }, { name: 'Cover_note.docx', reason: 'Unsupported file type' }] };
  }
  function makeRows(ids) {
    return ids.map((id, i) => {
      const it = M.items.find((x) => x.id === id);
      const basis = it.source === 'LLM' ? 'proposal' : it.source === 'NONE' ? 'none' : it.source === 'ALIAS' || it.source === 'EXACT' ? 'deterministic' : 'diagnostic_name_match';
      const failing = it.checks.filter((k) => k[0] === 'danger');
      return { source_index: parseInt(it.pos.slice(1), 10) - 1, source_position: it.pos, source_header: it.header, suggested_field: it.proposal, suggestion_basis: basis, proposal_assessment: it.llm || null,
        validation: failing.length ? failing.map((k) => k[3] + ': ' + k[2]).join(' ') : it.checks.length ? 'Proposal checks passed.' : null, note: it.reason, needs_attention: true, duplicate: !!it.conflict, decided: false, decision: null,
        field_type: (BANK_FIELDS.find((f) => f[0] === it.proposal) || [0, 'string'])[1], field_required: it.required, financial: it.financial, samples: it.samples.map((s) => s[1]), available_actions: it.proposal ? ['MAP', 'CHANGE', 'IGNORE'] : ['CHANGE', 'IGNORE'],
        _conflict: it.conflict ? it.conflict.pos : null, _failsFormat: failing.some((k) => k[3] !== 'SINGLE_SOURCE') && it.required, _order: i };
    });
  }
  function newVersion(c, code, t, o2) {
    const cat = catByCode(code), slot = c.pkg.slots[cat.category];
    const prev = slot.versions[slot.versions.length - 1];
    if (prev) { prev.version_status = 'SUPERSEDED'; prev.status_history.push({ status: 'SUPERSEDED', at: iso(t) }); }
    const v = { file_version_id: 'FV-' + (seq.fv++), version_number: slot.versions.length + 1, version_status: 'RECEIVED', original_filename: o2.name, processing_status: 'PROCESSING', source_sha256: hex(c.case_ref + o2.name + t, 64), intake_id: 'INT-' + hex(c.case_ref + code + t, 8).toUpperCase(), received_at: iso(t), evidence_category: cat.category, status_history: [{ status: 'RECEIVED', at: iso(t) }], review: null, structure_error: null, plan: o2.plan, job_id: o2.job_id, source: o2.source };
    slot.versions.push(v);
    return v;
  }
  function settleVersion(c, v, t) {
    const p = v.plan; v.processing_status = 'PROCESSED';
    if (p.structure_error) { v.structure_error = p.structure_error; v.version_status = 'RESUBMISSION_REQUIRED'; }
    else if (p.review && p.review.length) { v.version_status = 'REVIEW_REQUIRED'; v.review = { kind: 'PROPOSAL_REVIEW', reason: p.review.length + ' columns could not be mapped deterministically.', rows: makeRows(p.review), state: 'open' }; }
    else v.version_status = 'VALIDATED';
    v.status_history.push({ status: v.version_status, at: iso(t) });
  }

  /* ---------- jobs: intake (a run), resubmission (an upload), reconciliation ---------- */
  function newJob(c, kind, t, extra) {
    const j = Object.assign({ job_id: 'JOB-' + (seq.job++), kind, state: 'running', created_at: iso(t), finished_at: null, error: null, run_id: null, stage: 0, nextAt: t + ms(kind === 'intake' ? 800 : kind === 'resubmission' ? 450 : 1100), files: [] }, extra || {});
    c.jobs.push(j); st.jobs[j.job_id] = { ref: c.case_ref, job: j };
    return j;
  }
  function startRun(c, t, retryOf) {
    const n = c.runs.length + 1, pkgId = 'PKG-' + c.reporting_period + '-' + hex(c.case_ref + n + t, 6);
    const run = { run_id: 'RUN-' + c.case_ref.slice(3) + '-' + pad(n) + '-' + hex(c.case_ref + 'run' + n, 6), run_no: n, package_id: pkgId, started_at: iso(t), started_by: analyst.reviewer_id, status: 'PROCESSING', finished_at: null, failure: null, retry_of: retryOf || null, evidence_source: 'ORIGINAL_ZIP', staged_entries: null, skipped_entries: null, not_carried_forward: retryOf ? (c.uploadsByRun[retryOf] || []) : undefined, stages: STAGES.map((s) => ({ key: s[0], title: s[1], explanation: s[2], status: 'pending', started_at: null, finished_at: null, evidence: null })), events: [] };
    run.stages[0].status = 'running'; run.stages[0].started_at = iso(t);
    c.runs.push(run);
    c.pkg = { package_id: pkgId, package_status: 'RECEIVED', active_snapshot_id: null, slots: {}, validations: [], snapshots: [], validationRunning: null };
    CATS.forEach((k) => { c.pkg.slots[k.category] = { evidence_category: k.category, required: k.required, versions: [] }; });
    const j = newJob(c, 'intake', t, { run_id: run.run_id, fail: controls.failNextRun || (retryOf ? false : !!c.scenario.failFirstRun && c.runs.length === 1) });
    controls.failNextRun = false;
    run.intake_job_id = j.job_id; run.events.push({ seq: 1, event_type: 'INTAKE_STARTED', at: iso(t), actor_id: 'system' });
    audit(c, t, n > 1 ? 'CASE_RETRY_REQUESTED' : 'CASE_RUN_STARTED', { run_id: run.run_id, retry_of: retryOf || null }, n > 1 ? 'analyst' : 'system');
    return run;
  }
  function stepIntake(c, j, t) {
    const run = c.runs.find((r) => r.run_id === j.run_id), s = run.stages[j.stage];
    if (j.fail && j.stage === 1) {
      s.status = 'failed'; s.finished_at = iso(t); run.status = 'FAILED'; run.finished_at = iso(t);
      run.failure = { code: 'EVIDENCE_STORE_TIMEOUT', message: 'The evidence store did not respond while reading entry 9 of 23. Nothing was registered.', at: iso(t), job_id: j.job_id, stage: 'read' };
      j.state = 'failed'; j.finished_at = iso(t); j.error = run.failure.message;
      audit(c, t, 'CASE_RUN_FAILED', { run_id: run.run_id, code: run.failure.code }, 'system');
      return finishOp(c, t);
    }
    const plan = j.plan || (j.plan = zipFiles(c));
    if (s.key === 'identify') { run.staged_entries = plan.files.length; run.skipped_entries = plan.skipped.length; plan.files.forEach((f) => { const v = newVersion(c, f.code, t, { name: f.name, plan: f, job_id: j.job_id, source: 'ORIGINAL_ZIP' }); j.files.push({ name: f.name, state: 'processing', outcome: null, vid: v.file_version_id }); }); }
    if (s.key === 'mapping') versions(c).forEach((v) => { if (v.processing_status === 'PROCESSING' && v.job_id === j.job_id) settleVersion(c, v, t); });
    const summaries = { init: 'Package created · ZIP SHA-256 verified', read: '17 entries read', identify: plan.files.length + ' files classified · ' + plan.skipped.length + ' skipped', structure: plan.files.some((f) => f.structure_error) ? '1 structure failure' : 'All structures valid', mapping: (() => { const n = versions(c).reduce((a, v) => a + rowRemaining(v), 0); return n ? n + ' columns need a decision' : 'All columns resolved'; })(), proposals: 'Recorded proposals only · LLM mode RECORDED', review: (() => { const n = versions(c).filter((v) => v.review && v.review.state === 'open').length; return n ? n + ' file awaiting mapping review' : 'Nothing to review'; })(), previews: 'Canonical previews generated', validation: 'Runs once the required reviews are complete' };
    const needsReview = versions(c).some((v) => v.review && v.review.state === 'open');
    s.status = s.key === 'structure' && plan.files.some((f) => f.structure_error) ? 'requires_attention' : s.key === 'review' && needsReview ? 'requires_review' : s.key === 'validation' && needsReview ? 'not_required' : 'completed';
    s.finished_at = iso(t); s.evidence = summaries[s.key];
    run.events.push({ seq: run.events.length + 1, event_type: 'STAGE_' + s.key.toUpperCase() + '_COMPLETED', at: iso(t), actor_id: 'system' });
    j.stage++;
    if (j.stage >= run.stages.length) {
      run.status = 'COMPLETED'; run.finished_at = iso(t); j.state = 'completed'; j.finished_at = iso(t);
      j.files.forEach((f) => { f.state = 'completed'; const v = findVersion(c, f.vid); f.outcome = v ? v.version_status : null; });
      audit(c, t, 'INTAKE_COMPLETED', { run_id: run.run_id, files: plan.files.length }, 'system');
      updatePackageStatus(c);
      maybeValidate(c, t);
      return finishOp(c, t);
    }
    run.stages[j.stage].status = 'running'; run.stages[j.stage].started_at = iso(t); j.nextAt = t + ms(800);
  }
  function stepResubmission(c, j, t) {
    j.stage++;
    if (j.stage < 4) { j.nextAt = t + ms(450); return; }
    const v = findVersion(c, j.vid); settleVersion(c, v, t);
    j.state = 'completed'; j.finished_at = iso(t); j.files = [{ name: v.original_filename, state: 'completed', outcome: v.version_status }];
    audit(c, t, 'FILE_VERSION_PROCESSED', { file_version_id: v.file_version_id, version_status: v.version_status }, 'system');
    updatePackageStatus(c); maybeValidate(c, t); finishOp(c, t);
  }
  function findVersion(c, vid) { for (const v of c.pkg ? Object.values(c.pkg.slots).flatMap((s) => s.versions) : []) if (v.file_version_id === vid) return v; return null; }
  function updatePackageStatus(c) {
    const p = c.pkg; if (!p || p.package_status === 'RECONCILIATION_READY') return;
    const cur = versions(c);
    const missing = CATS.filter((k) => k.required && !cur.some((v) => v.evidence_category === k.category && v.version_status !== 'REJECTED' && v.version_status !== 'SUPERSEDED'));
    if (cur.some((v) => v.version_status === 'REVIEW_REQUIRED')) p.package_status = 'REVIEW_REQUIRED';
    else if (cur.some((v) => ['RESUBMISSION_REQUIRED', 'REJECTED', 'FAILED_VALIDATION'].includes(v.version_status))) p.package_status = 'RESUBMISSION_REQUIRED';
    else if (missing.length) p.package_status = 'INCOMPLETE';
    else p.package_status = 'READY_FOR_VALIDATION';
  }
  /* ---------- validation: automatic once nothing runs and no review is open ---------- */
  function maybeValidate(c, t) {
    if (!c.pkg || c.activation || allJobsRunning(c).length) return;
    if (versions(c).some((v) => v.version_status === 'REVIEW_REQUIRED')) return;
    c.pkg.validationRunning = { started_at: iso(t), endAt: t + ms(1200) };
  }
  function finishValidation(c, t) {
    const cur = versions(c), checks = [];
    const missing = CATS.filter((k) => k.required && !cur.some((v) => v.evidence_category === k.category && !['REJECTED', 'SUPERSEDED'].includes(v.version_status)));
    const rejected = cur.filter((v) => v.version_status === 'REJECTED');
    const struct = cur.filter((v) => v.structure_error && v.version_status !== 'SUPERSEDED');
    const badMap = cur.filter((v) => v.review && v.review.state === 'confirmed' && v.review.rows.some((r) => r._failsFormat && r.decision && r.decision.action === 'MAP'));
    const add = (id, name, passed, detail) => checks.push({ check_id: id, name, passed, detail });
    add('PV-01', 'Package manifest complete', true, cur.length + ' file versions registered with SHA-256.');
    add('PV-02', 'Required evidence categories present', !missing.length, missing.length ? missing.map((k) => k.category + ' ' + k.title).join(', ') + ': required, no file.' : 'All required categories have a file.');
    add('PV-03', 'All files classified or excluded', true, '2 entries skipped (not recognised or unsupported); preserved, not used.');
    add('PV-04', 'Required canonical fields mapped', !rejected.length && !badMap.length, rejected.length ? rejected.map((v) => v.original_filename + ' v' + v.version_number + ' was rejected: its required fields have no usable source.').join(' ') : badMap.length ? 'booking_date is mapped from a column that failed FORMAT_CONSISTENT.' : 'Every required canonical field has an accepted mapping.');
    add('PV-05', 'Mapping review complete', true, 'No mapping review is open.');
    add('PV-06', 'One source per canonical field', true, 'Each canonical field has one source column.');
    add('PV-07', 'Records within reporting period', true, 'Dated records fall within ' + c.reporting_period + '.');
    add('PV-08', 'File structures valid', !struct.length, struct.length ? struct.map((v) => v.original_filename + ': ' + v.structure_error).join(' ') : 'All classified CSVs have consistent structures.');
    add('PV-09', 'One active version per evidence item', true, 'No superseded version is active.');
    badMap.forEach((v) => { v.version_status = 'FAILED_VALIDATION'; v.status_history.push({ status: 'FAILED_VALIDATION', at: iso(t) }); });
    const passed = checks.every((k) => k.passed);
    c.pkg.validations.forEach((v) => { v.current = false; });
    c.pkg.validations.push({ at: iso(t), passed, checks, current: true });
    c.pkg.validationRunning = null;
    updatePackageStatus(c);
    audit(c, t, passed ? 'PACKAGE_VALIDATION_PASSED' : 'PACKAGE_VALIDATION_FAILED', { failed_checks: checks.filter((k) => !k.passed).map((k) => k.check_id) }, 'system');
    finishOp(c, t);
  }
  /* ---------- reconciliation ---------- */
  function finishRecon(c, j, t) {
    const r = st.recons[j.run_id];
    if (j.fail) {
      r.state = 'FAILED'; r.error = 'The Smart Parser adapter did not accept the request: the reconciliation engine returned HTTP 503.'; r.finished_at = iso(t);
      j.state = 'failed'; j.error = r.error; j.finished_at = iso(t);
      audit(c, t, 'RECONCILIATION_FAILED', { run_id: r.run_id }, 'system');
      return finishOp(c, t);
    }
    const kind = c.scenario.recon, acc = [['GBP', '••4821'], ['EUR', '••0937']];
    r.controls = [];
    M.recon.controls.forEach((ctl) => acc.forEach((a, ai) => {
      let out = ai ? ctl[3] : ctl[2];
      if (kind !== 'exceptions') { out = ctl[0] === 'CTL-08' && !ai ? 'NOT_APPLICABLE' : 'PASS'; if (kind === 'incomplete' && ai && (ctl[0] === 'CTL-04' || ctl[0] === 'CTL-11')) out = 'INSUFFICIENT_EVIDENCE'; }
      r.controls.push({ check_id: ctl[0], control: ctl[1], account: a[0] + ' ' + a[1], outcome: out, note: out === 'FAIL' ? 'See linked exception.' : out === 'INSUFFICIENT_EVIDENCE' ? 'Evidence for this control is missing from the snapshot.' : out === 'NOT_APPLICABLE' ? 'No activity of this kind on the account.' : null });
    }));
    const causeCtl = { SHORTFALL: ['CTL-01', 'CTL-10'], BALANCE_MISMATCH: ['CTL-02'], TRANSIT_AGEING: ['CTL-04'], UNMATCHED_RECEIPT: ['CTL-05'], TIMING_DIFFERENCE: ['CTL-05'], FX_RATE_VARIANCE: ['CTL-08'] };
    r.exceptions = kind !== 'exceptions' ? [] : M.recon.exceptions.map((e, i) => ({ exception_id: 'EXC-CASE-' + pad(i + 1), severity: e.sev === 'HIGH' ? 'Critical' : 'High', root_cause: e.cause, title: e.causeLabel, account: e.bank + ' ' + e.account, currency: e.ccy, period: e.date, amount: e.amount, affected_results: e.results, checks: causeCtl[e.cause] || [], refs: e.refs }));
    const out = { PASS: 0, FAIL: 0, INSUFFICIENT_EVIDENCE: 0, NOT_APPLICABLE: 0 }; r.controls.forEach((x) => { out[x.outcome]++; });
    r.outcomes = out; r.total_results = r.controls.length; r.exception_count = r.exceptions.length;
    r.case_status = out.FAIL ? 'EXCEPTIONS_OPEN' : out.INSUFFICIENT_EVIDENCE ? 'EVIDENCE_INCOMPLETE' : 'CLEAN';
    r.state = 'COMPLETED'; r.finished_at = iso(t); j.state = 'completed'; j.finished_at = iso(t);
    const superseded = c.deferring;
    c.deferring = false; c.deferral = null;
    c.completed = { at: iso(t), reconciliation_run_id: r.run_id, snapshot_id: c.activation.snapshot_id, case_status: r.case_status };
    audit(c, t, 'RECONCILIATION_COMPLETED', { run_id: r.run_id, case_status: r.case_status }, 'system');
    setStatus(c, 'COMPLETED', t, 'Reconciliation completed' + (superseded ? '; the deferral request was superseded' : ''));
    audit(c, t, 'CASE_COMPLETED', { reconciliation_run_id: r.run_id, deferral_superseded: superseded }, 'system');
  }
  // When the last running operation finishes, a requested deferral takes effect.
  function finishOp(c, t) {
    if (!c.deferring || allJobsRunning(c).length || (c.pkg && c.pkg.validationRunning)) return;
    c.deferring = false; c.deferral = null; c.deferred_at = iso(t);
    setStatus(c, 'PENDING', t, 'Deferred: the running operation finished first');
    audit(c, t, 'CASE_DEFERRED', {}, 'system');
  }
  function tick(t) {
    Object.values(st.cases).forEach((c) => {
      let guard = 0;
      for (const j of c.jobs.slice()) {
        while (j.state === 'running' && t >= j.nextAt && guard++ < 50) {
          const tt = j.nextAt;
          if (j.kind === 'intake') { stepIntake(c, j, tt); if (j.state === 'running') continue; }
          else if (j.kind === 'resubmission') { stepResubmission(c, j, tt); if (j.state === 'running') continue; }
          else if (j.kind === 'reconciliation') { if (tt >= j.endAt) finishRecon(c, j, tt); else { st.recons[j.run_id].accepted_at = st.recons[j.run_id].accepted_at || iso(tt); j.nextAt = j.endAt; continue; } }
        }
      }
      if (c.pkg && c.pkg.validationRunning && t >= c.pkg.validationRunning.endAt) finishValidation(c, c.pkg.validationRunning.endAt);
    });
  }
  const drain = (c, until) => { for (let i = 0; i < 300; i++) { const j = c.jobs.find((x) => x.state === 'running'); const vr = c.pkg && c.pkg.validationRunning; const next = Math.min(j ? j.nextAt : Infinity, vr ? vr.endAt : Infinity); if (next === Infinity || (until && next > until)) return; tick(next); } };

  /* ---------- lifecycle operations (the backend's rules, imitated) ---------- */
  const expect = (c, q) => { if (q && q.expected_revision != null && q.expected_revision !== c.revision) fail(409, 'CASE_CHANGED', 'This case changed. Reload to see the latest state.'); };
  const mustWork = (c) => { if (c.status === 'COMPLETED') fail(409, 'CASE_COMPLETED', 'The case is Completed and read-only.'); if (c.status !== 'IN_PROGRESS') fail(409, 'CASE_NOT_ACTIVE', 'The case is not In Progress. Resume Processing first.'); if (c.deferring) fail(409, 'CASE_DEFERRING', 'A deferral is requested; nothing new can start.'); };
  const ops = {
    start(c, t) {
      if (c.status !== 'WAITING') fail(409, 'CASE_STATE', 'Only a Waiting case can be started.');
      const other = slotCase(); if (other) fail(409, 'ACTIVE_CASE_EXISTS', other.case_ref + ' is In Progress. Defer it before starting another case.');
      setStatus(c, 'IN_PROGRESS', t, 'Start Smart Parsing'); c.started = { by: analyst.reviewer_id, at: iso(t) };
      audit(c, t, 'CASE_STARTED', {});
      startRun(c, t);
    },
    defer(c, t) {
      if (c.status !== 'IN_PROGRESS' || c.deferring) fail(409, 'CASE_STATE', 'Only an In Progress case without a pending deferral can be deferred.');
      const running = allJobsRunning(c);
      if (running.length || (c.pkg && c.pkg.validationRunning)) { c.deferring = true; c.deferral = { requested_at: iso(t), waiting_for: running.map((j) => ({ job_id: j.job_id, kind: j.kind, state: j.state })).concat(c.pkg && c.pkg.validationRunning ? [{ job_id: null, kind: 'validation', state: 'running' }] : []) }; audit(c, t, 'CASE_DEFERRAL_REQUESTED', { waiting_for: c.deferral.waiting_for }); }
      else { c.deferred_at = iso(t); setStatus(c, 'PENDING', t, 'Defer Case'); audit(c, t, 'CASE_DEFERRED', {}); }
    },
    resume(c, t) {
      if (c.status !== 'PENDING') fail(409, 'CASE_STATE', 'Only a Pending case can be resumed.');
      const other = slotCase(); if (other) fail(409, 'ACTIVE_CASE_EXISTS', other.case_ref + ' is In Progress. Defer it before resuming another case.');
      setStatus(c, 'IN_PROGRESS', t, 'Resume Processing'); c.deferred_at = null; audit(c, t, 'CASE_RESUMED', {});
    },
    retry(c, t, q) {
      if (!q || q.confirm !== true) fail(400, 'CONFIRMATION_REQUIRED', 'Retry from Beginning needs confirmation.');
      if (c.status === 'PENDING') fail(409, 'CASE_NOT_ACTIVE', 'Resume Processing before retrying.');
      const run = latestRun(c); if (!run || run.status !== 'FAILED') fail(409, 'RUN_NOT_FAILED', 'Only a failed run can be retried.');
      mustWork(c); startRun(c, t, run.run_id);
    },
    decision(c, t, vid, q) {
      mustWork(c); expect(c, q);
      const v = findVersion(c, vid) || fail(404, 'NOT_FOUND', 'File version not found.');
      if (!v.review || v.review.state !== 'open') fail(409, 'REVIEW_STATE', 'This file is not open for review.');
      const action = q.action === 'IGNORE_COLUMN' ? 'IGNORE' : q.action;
      if (action === 'REJECT') return ops.reject(c, t, vid);
      const row = v.review.rows.find((r) => r.source_index === q.source_index) || fail(404, 'NOT_FOUND', 'Column not found.');
      if (!row.available_actions.includes(action)) fail(400, 'UNSUPPORTED_ACTION', action + ' is not available for this column.');
      const field = action === 'MAP' ? row.suggested_field : action === 'CHANGE' ? q.canonical_field : null;
      if (action === 'CHANGE' && !BANK_FIELDS.some((f) => f[0] === field)) fail(400, 'INVALID', 'Choose a canonical field for Change.');
      if (field && v.review.rows.some((r) => r !== row && r.decision && r.decision.canonical_field === field)) fail(400, 'DUPLICATE_TARGET', field + ' is already supplied by another column. Ignore or Change this column.');
      row.decision = { action, backend_action: action === 'IGNORE' ? 'IGNORE_COLUMN' : action, canonical_field: field, at: iso(t), reviewer: analyst.reviewer_id }; row.decided = true;
      audit(c, t, 'REVIEW_DECISION_RECORDED', { file_version_id: vid, source_index: row.source_index, action, canonical_field: field });
    },
    confirm(c, t, vid) {
      mustWork(c);
      const v = findVersion(c, vid) || fail(404, 'NOT_FOUND', 'File version not found.');
      if (!v.review || v.review.state !== 'open') fail(409, 'REVIEW_STATE', 'This file is not open for review.');
      const rem = rowRemaining(v); if (rem) fail(409, 'DECISIONS_OUTSTANDING', rem + ' decision(s) outstanding.');
      v.review.state = 'confirmed'; v.version_status = 'VALIDATED'; v.status_history.push({ status: 'VALIDATED', at: iso(t) });
      audit(c, t, 'ANALYST_REVIEW_CONFIRMED', { file_version_id: vid });
      updatePackageStatus(c); maybeValidate(c, t);
    },
    reject(c, t, vid) {
      mustWork(c);
      const v = findVersion(c, vid) || fail(404, 'NOT_FOUND', 'File version not found.');
      if (!v.review || v.review.state !== 'open') fail(409, 'REVIEW_STATE', 'This file is not open for review.');
      v.review.state = 'rejected'; v.version_status = 'REJECTED'; v.status_history.push({ status: 'REJECTED', at: iso(t) });
      audit(c, t, 'ANALYST_CORRECTION_REQUESTED', { file_version_id: vid });
      updatePackageStatus(c); maybeValidate(c, t);
    },
    evidence(c, t, q) {
      mustWork(c);
      if (c.activation) fail(409, 'PACKAGE_LOCKED', 'The package is ACTIVE and locked.');
      const run = latestRun(c); if (run && run.status === 'FAILED') fail(409, 'RUN_FAILED', 'The latest run failed. Retry from Beginning first.');
      if (allJobsRunning(c).length) fail(409, 'OPERATION_RUNNING', 'Wait for the running operation to finish.');
      const stg = st.staging[q.staging_id] || fail(404, 'NOT_FOUND', 'Staged file not found.');
      const cat = catById(q.category) || fail(400, 'INVALID', 'Unknown category.');
      const cur = versions(c).find((v) => v.evidence_category === cat.category);
      const correction = cur && ['RESUBMISSION_REQUIRED', 'REJECTED', 'FAILED_VALIDATION'].includes(cur.version_status);
      if (cur && !correction) fail(409, 'EVIDENCE_NOT_ACCEPTED', cat.category + ' already has a current file that does not require replacement.');
      if (cur && cur.source_sha256 === stg.sha) fail(409, 'EVIDENCE_NOT_ACCEPTED', 'Identical bytes are refused.');
      if (stg.name.split('.').pop().toUpperCase() !== cat.format) { c.refused.push({ filename: stg.name, source_sha256: stg.sha, evidence_category: cat.category, reason: 'Expected a ' + cat.format + ' file.', at: iso(t) }); fail(409, 'EVIDENCE_NOT_ACCEPTED', 'Expected a ' + cat.format + ' file for ' + cat.category + '.'); }
      const j = newJob(c, 'resubmission', t, { run_id: run.run_id });
      const plan = cat.code === 'BANK_STATEMENT_TRANSACTIONS' ? { review: ((c.scenario.items || REVIEW_SETS[c.scenario.evidence]) || {}).v2 || [] } : {};
      const v = newVersion(c, cat.code, t, { name: stg.name, plan, job_id: j.job_id, source: 'ANALYST_UPLOAD' }); v.source_sha256 = stg.sha;
      j.vid = v.file_version_id; j.files = [{ name: stg.name, state: 'processing', outcome: null }];
      (c.uploadsByRun[run.run_id] = c.uploadsByRun[run.run_id] || []).push({ job_id: j.job_id, kind: 'resubmission', files: [{ name: stg.name, category: cat.category }] });
      audit(c, t, 'ANALYST_EVIDENCE_UPLOADED', { file_version_id: v.file_version_id, category: cat.category, filename: stg.name, job_id: j.job_id });
      updatePackageStatus(c);
      return j;
    },
    activate(c, t, q) {
      if (!q || q.confirm !== true) fail(400, 'CONFIRMATION_REQUIRED', 'Activation needs confirmation.');
      if (c.activation) fail(409, 'ALREADY_ACTIVATED', 'The package is already activated.');
      mustWork(c);
      const val = c.pkg && c.pkg.validations[c.pkg.validations.length - 1];
      if (!val || !val.passed || !val.current) return { activated: false, reason: 'Validation has not passed for the current evidence.' };
      st.snapCount++;
      const sid = 'SNAP-' + pad(st.snapCount, 3) + '-' + hex(c.case_ref + t, 8);
      c.activation = { snapshot_id: sid, activated_by: analyst.reviewer_id, activated_at: iso(t), manifest_sha256: hex(sid + 'manifest', 64) };
      c.pkg.active_snapshot_id = sid; c.pkg.package_status = 'RECONCILIATION_READY';
      c.pkg.snapshots.push({ snapshot_id: sid, at: iso(t), entries: versions(c).length });
      audit(c, t, 'ANALYST_ACTIVATION_REQUESTED', { snapshot_id: sid });
      return { activated: true, reason: null, snapshot_id: sid };
    },
    reconcile(c, t, q) {
      mustWork(c); expect(c, q);
      if (!c.activation) fail(409, 'NOT_ACTIVATED', 'Activate the package first.');
      if (allJobsRunning(c).length) fail(409, 'OPERATION_RUNNING', 'A reconciliation run is already running.');
      const runId = 'RECON-' + (seq.recon++) + '-' + hex(c.case_ref + t, 6);
      const j = newJob(c, 'reconciliation', t, { run_id: runId, fail: controls.failNextRecon, endAt: t + ms(controls.failNextRecon ? 2000 : 5000) });
      controls.failNextRecon = false;
      st.recons[runId] = { run_id: runId, ref: c.case_ref, job_id: j.job_id, snapshot_id: c.activation.snapshot_id, state: 'RUNNING', started_at: iso(t), accepted_at: null, finished_at: null, error: null, controls: [], exceptions: [], outcomes: null, case_status: null };
      c.recons.push(runId);
      audit(c, t, 'ANALYST_RECONCILIATION_REQUESTED', { run_id: runId, snapshot_id: c.activation.snapshot_id });
      return j;
    }
  };

  /* ---------- payloads (contract §3) ---------- */
  function steps(c) {
    const run = latestRun(c), cur = versions(c), val = c.pkg && c.pkg.validations[c.pkg.validations.length - 1];
    const lastRecon = c.recons.length ? st.recons[c.recons[c.recons.length - 1]] : null;
    const reviewOpen = cur.some((v) => v.version_status === 'REVIEW_REQUIRED'), needsFix = cur.some((v) => ['RESUBMISSION_REQUIRED', 'REJECTED', 'FAILED_VALIDATION'].includes(v.version_status));
    let s = [
      !run ? 'todo' : run.status === 'FAILED' ? 'failed' : run.status === 'PROCESSING' ? 'current' : 'done',
      !run || run.status !== 'COMPLETED' ? 'todo' : reviewOpen || needsFix ? 'attention' : 'done',
      c.pkg && c.pkg.validationRunning ? 'current' : !val ? 'todo' : val.passed && val.current ? 'done' : val.current ? 'attention' : 'todo',
      c.activation ? 'done' : 'todo',
      !lastRecon ? 'todo' : lastRecon.state === 'COMPLETED' ? 'done' : lastRecon.state === 'RUNNING' ? 'current' : 'failed'];
    if (c.status === 'PENDING') { const i = s.findIndex((x) => x !== 'done'); if (i > -1 && s[i] !== 'failed') s[i] = 'paused'; }
    return ['smart_parser', 'review', 'validation', 'activation', 'reconciliation'].map((key, i) => ({ key, state: s[i] }));
  }
  function progress(c) {
    const cur = versions(c), val = c.pkg && c.pkg.validations[c.pkg.validations.length - 1];
    const lastRecon = c.recons.length ? st.recons[c.recons[c.recons.length - 1]] : null;
    const awaiting = cur.filter((v) => v.version_status === 'REVIEW_REQUIRED').map((v) => ({ category: v.evidence_category, title: catById(v.evidence_category).title, file_version_id: v.file_version_id, remaining: rowRemaining(v), total: v.review.rows.length, remaining_columns: v.review.rows.filter((r) => !r.decided).map((r) => r.source_header), version_number: v.version_number, original_filename: v.original_filename }));
    const missing = c.pkg && latestRun(c) && latestRun(c).status === 'COMPLETED' ? CATS.filter((k) => k.required && !cur.some((v) => v.evidence_category === k.category && !['REJECTED', 'SUPERSEDED'].includes(v.version_status))).map((k) => ({ category: k.category, title: k.title })) : [];
    const corr = cur.filter((v) => ['RESUBMISSION_REQUIRED', 'REJECTED', 'FAILED_VALIDATION'].includes(v.version_status)).map((v) => ({ category: v.evidence_category, title: catById(v.evidence_category).title, file_version_id: v.file_version_id, version_status: v.version_status, version_number: v.version_number, reason: v.structure_error || (v.version_status === 'REJECTED' ? 'Rejected: correction requested.' : 'Failed validation.'), required: catById(v.evidence_category).required }));
    const running = allJobsRunning(c)[0];
    const processed = new Set(cur.filter((v) => v.processing_status === 'PROCESSED' && !['REJECTED'].includes(v.version_status)).map((v) => v.evidence_category)).size;
    const validated = new Set(cur.filter((v) => v.version_status === 'VALIDATED').map((v) => v.evidence_category)).size;
    const made = cur.reduce((a, v) => a + (v.review ? v.review.rows.filter((r) => r.decided).length : 0), 0), outstanding = awaiting.reduce((a, x) => a + x.remaining, 0);
    const summary = [];
    const run = latestRun(c);
    if (c.status === 'COMPLETED') summary.push('Reconciliation ' + lastRecon.case_status + ' · ' + lastRecon.exception_count + ' exception(s)');
    if (run && run.status === 'FAILED') summary.push('Smart Parser run failed at stage ' + (run.failure.stage || '') + ' · Retry from Beginning needed');
    if (running) summary.push(running.kind === 'intake' ? 'Smart Parser · stage ' + (running.stage + 1) + ' of 9, ' + STAGES[Math.min(running.stage, 8)][1].toLowerCase() : running.kind === 'resubmission' ? 'Processing an uploaded file' : 'Reconciliation running');
    if (c.pkg && c.pkg.validationRunning) summary.push('Validation running');
    if (c.pkg && run && run.status !== 'FAILED' && c.status !== 'COMPLETED') summary.push(processed + ' of 19 evidence categories processed');
    if (awaiting.length) summary.push(awaiting.length + ' file(s) awaiting mapping review, ' + outstanding + ' decision(s) outstanding');
    if (missing.length) summary.push(missing.length + ' missing required categor' + (missing.length > 1 ? 'ies' : 'y'));
    if (corr.length) summary.push(corr.length + ' file(s) require correction');
    if (val && val.current && val.passed && !c.activation) summary.push('Validated · activation not started');
    if (c.activation && c.status !== 'COMPLETED') summary.push('Active · locked as ' + c.activation.snapshot_id);
    if (!c.pkg) summary.push('Original ZIP attached · not processed');
    return { categories_total: 19, required_total: CATS.filter((k) => k.required).length, categories_processed: processed, categories_validated: validated, files_awaiting_review: awaiting.length, decisions_outstanding: outstanding, decisions_made: made, missing_required: missing, correction_required: corr, awaiting_review: awaiting, refused_uploads: c.refused,
      validation: { state: c.pkg && c.pkg.validationRunning ? 'RUNNING' : !val ? 'NOT_RUN' : val.passed ? 'PASSED' : 'FAILED', at: val ? val.at : null, failed_checks: val ? val.checks.filter((k) => !k.passed).map((k) => k.check_id) : [], current: val ? val.current : false },
      activation: c.activation ? { snapshot_id: c.activation.snapshot_id } : null,
      reconciliation: lastRecon ? { state: lastRecon.state, job_id: lastRecon.job_id, run_id: lastRecon.run_id, case_status: lastRecon.case_status, exceptions: lastRecon.exceptions.length, error: lastRecon.error } : { state: 'NOT_RUN', job_id: null, run_id: null, case_status: null, exceptions: 0, error: null },
      current_operation: running ? { kind: running.kind, job_id: running.job_id, state: running.state, files_total: running.kind === 'intake' ? (running.plan ? running.plan.files.length : null) : 1, files_processed: running.files.filter((f) => f.state === 'completed').length, validation_running: !!(c.pkg && c.pkg.validationRunning) } : c.pkg && c.pkg.validationRunning ? { kind: 'validation', job_id: null, state: 'running', files_total: null, files_processed: null, validation_running: true } : null,
      last_activity_at: iso(c.last_activity_at), summary };
  }
  const runPayload = (c, r) => { const x = clone(r); delete x.stages; delete x.events; delete x.intake_job_id; const j = c.jobs.find((k) => k.job_id === r.intake_job_id); x.intake_job = j ? { job_id: j.job_id, state: j.state, error: j.error, trace: null, files: j.files.map((f) => ({ name: f.name, state: f.state, outcome: f.outcome })), created_at: j.created_at, finished_at: j.finished_at } : null; if (!x.retry_of) delete x.not_carried_forward; return x; };
  function summaryPayload(c) {
    const run = latestRun(c), others = Object.values(st.cases).filter((x) => x !== c && x.customer_id === c.customer_id && x.reporting_period === c.reporting_period).length;
    return { case_ref: c.case_ref, customer_id: c.customer_id, customer_name: c.customer_name, reporting_period: c.reporting_period, created_at: iso(c.created_at), status: c.status, last_activity_at: iso(c.last_activity_at), zip: clone(c.zip),
      deferring: c.deferring, deferral: clone(c.deferral), deferred_at: c.deferred_at, started: clone(c.started), completed: clone(c.completed),
      current_run: run ? { run_id: run.run_id, run_no: run.run_no, status: run.status, package_id: run.package_id, started_at: run.started_at, finished_at: run.finished_at, failure: clone(run.failure) } : null,
      runs_total: c.runs.length, failed_runs: c.runs.filter((r) => r.status === 'FAILED').length, revision: c.revision, status_since: iso(c.status_since), other_cases_for_period: others, steps: steps(c), progress: progress(c) };
  }
  function actions(c) {
    const run = latestRun(c), other = slotCase(), cur = versions(c), val = c.pkg && c.pkg.validations[c.pkg.validations.length - 1];
    const running = allJobsRunning(c).length || (c.pkg && c.pkg.validationRunning);
    const A = (enabled, reason) => ({ enabled: !!enabled, reason: enabled ? null : reason });
    const ip = c.status === 'IN_PROGRESS', idle = ip && !running && !c.deferring, failed = run && run.status === 'FAILED';
    const notIp = c.status === 'PENDING' ? 'The case is Pending: read-only. Resume Processing first.' : c.status === 'COMPLETED' ? 'The case is Completed: read-only.' : c.status === 'WAITING' ? 'Start Smart Parsing first.' : c.deferring ? 'A deferral is requested.' : running ? 'An operation is running.' : null;
    return {
      start: A(c.status === 'WAITING' && !other, c.status !== 'WAITING' ? 'Only a Waiting case can be started.' : other ? other.case_ref + ' is In Progress. Defer it first.' : null),
      defer: A(ip && !c.deferring, c.deferring ? 'Deferral requested. The running operation continues.' : 'Only the case In Progress can be deferred.'),
      resume: A(c.status === 'PENDING' && !other, c.status !== 'PENDING' ? 'Only a Pending case can be resumed.' : other ? other.case_ref + ' is In Progress. Defer it first.' : null),
      retry_from_beginning: A(idle && failed, c.status === 'PENDING' ? 'Resume Processing first.' : !failed ? 'Only a failed run can be retried.' : notIp),
      upload_evidence: A(idle && !failed && run && run.status === 'COMPLETED' && !c.activation, c.activation ? 'The package is ACTIVE and locked.' : failed ? 'Retry from Beginning first.' : notIp || 'Available after the Smart Parser run.'),
      review: A(idle && cur.some((v) => v.version_status === 'REVIEW_REQUIRED'), notIp || 'No file awaits review.'),
      validate: A(idle && run && run.status === 'COMPLETED' && !c.activation, notIp || 'Validation runs automatically.'),
      activate: A(idle && val && val.passed && val.current && !c.activation, c.activation ? 'Already activated.' : notIp || 'Available when validation has PASSED for the current evidence.'),
      reconcile: A(idle && c.activation, notIp || 'Activate the package first.')
    };
  }
  function detail(c) {
    const s = summaryPayload(c), cur = versions(c), run = latestRun(c), other = slotCase();
    const p = s.progress;
    const outstanding = {
      mapping_decisions: p.awaiting_review.map((a) => ({ file_version_id: a.file_version_id, category: a.category, file_name: a.original_filename, version: a.version_number, outstanding: a.remaining, total: a.total, columns: a.remaining_columns })),
      missing_categories: p.missing_required.map((m) => ({ category: m.category, title: m.title, format: catById(m.category).format })),
      files_requiring_replacement: p.correction_required.map((x) => ({ category: x.category, file_version_id: x.file_version_id, version: x.version_number, version_status: x.version_status, cause: x.version_status === 'RESUBMISSION_REQUIRED' ? 'STRUCTURE_FAILED' : 'COLUMN_REJECTED', detail: x.reason })),
      refused_uploads: c.refused,
      other: [].concat(run && run.status === 'FAILED' ? [{ kind: 'RETRY_FROM_BEGINNING', detail: 'Run ' + run.run_id + ' failed: ' + run.failure.code }] : [], p.validation.state === 'PASSED' && p.validation.current && !c.activation ? [{ kind: 'ACTIVATE', detail: 'Validation passed for the current evidence.' }] : [], c.activation && c.status !== 'COMPLETED' ? [{ kind: 'RUN_RECONCILIATION', detail: 'Snapshot ' + c.activation.snapshot_id + ' is ready.' }] : [])
    };
    const kept = c.pkg ? [p.categories_processed + ' of 19 evidence categories processed and kept'].concat(p.decisions_made ? [p.decisions_made + ' mapping decision(s) saved'] : [], ['Original ZIP with SHA-256 ' + c.zip.sha256.slice(0, 12) + '…']) : [];
    const pkg = c.pkg ? { package_id: c.pkg.package_id, package_status: c.pkg.package_status, active_snapshot_id: c.pkg.active_snapshot_id,
      slots: Object.values(c.pkg.slots).map((sl) => { const l = sl.versions[sl.versions.length - 1]; return { evidence_category: sl.evidence_category, required: sl.required, versions: sl.versions.length, latest: l ? { file_version_id: l.file_version_id, version_number: l.version_number, version_status: l.version_status, original_filename: l.original_filename, processing_status: l.processing_status } : null }; }),
      latest_validation: c.pkg.validations.length ? clone(c.pkg.validations[c.pkg.validations.length - 1]) : null,
      jobs: c.jobs.map((j) => ({ job_id: j.job_id, kind: j.kind, state: j.state, created_at: j.created_at, finished_at: j.finished_at, error: j.error, run_id: j.run_id })) } : null;
    return Object.assign(s, { status_history: clone(c.status_history), runs: c.runs.map((r) => runPayload(c, r)), actions: actions(c), outstanding, kept, blocked_by: other && other !== c && (c.status === 'WAITING' || c.status === 'PENDING') ? { case_ref: other.case_ref, customer_name: other.customer_name, reporting_period: other.reporting_period } : null, activation: clone(c.activation), package: pkg });
  }
  function reviewPayload(c, v) {
    const rows = v.review.rows.map((r) => { const x = clone(r); delete x._conflict; delete x._failsFormat; delete x._order; return x; });
    const rem = rowRemaining(v);
    return { case_ref: c.case_ref, package_id: c.pkg.package_id, file_version_id: v.file_version_id, evidence_category: v.evidence_category, category_title: catById(v.evidence_category).title, original_filename: v.original_filename, version_number: v.version_number, version_status: v.version_status, review_kind: v.review.kind, review_reason: v.review.reason,
      editable: v.review.state === 'open' && c.status === 'IN_PROGRESS' && !c.deferring, canonical_fields: BANK_FIELDS.map((f) => ({ name: f[0], requiredness: f[2] ? 'REQUIRED' : 'OPTIONAL', required: f[2], type: f[1] })),
      rows, counts: { attention: rows.length, decided: rows.filter((r) => r.decided).length, remaining: rem, recognised: 13 - rows.length }, required_not_covered: [], can_confirm: v.review.state === 'open' && rem === 0, file_actions: v.review.state === 'open' ? ['CONFIRM', 'REJECT'] : [], review_state: v.review.state };
  }

  /* ---------- seed (MOCK data) ---------- */
  function seed() {
    const reg = (name, cid, period, zip, when, scenario, ref) => register({ customer_name: name, customer_id: cid, reporting_period: period, zip_name: zip, zip_size: 3000000 + zip.length * 9137 }, at(when), { scenario, ref });
    const run = (fn) => fn();
    // Completed with exceptions (the storyline case, replayed)
    run(() => {
      const c = reg('Harbourline Payments Ltd', 'CUS-1001', '2026-10', 'Harbourline_Safeguarding_Oct2026.zip', '2026-11-03T09:14', { evidence: 'correction', recon: 'exceptions' }, 'RF-2026-10-001');
      ops.start(c, at('2026-11-04T10:02')); drain(c);
      const bank = () => versions(c).find((v) => v.evidence_category === catByCode('BANK_STATEMENT_TRANSACTIONS').category);
      ops.defer(c, at('2026-11-05T09:44')); ops.resume(c, at('2026-11-10T11:20'));
      [[2, 'MAP'], [7, 'MAP'], [11, 'IGNORE']].forEach((d, i) => ops.decision(c, at('2026-11-10T11:2' + i), bank().file_version_id, { action: d[1], source_index: d[0] }));
      ops.reject(c, at('2026-11-10T11:31'), bank().file_version_id); drain(c);
      const stage = (name, when) => { const id = 'STG-' + (seq.stg++); st.staging[id] = { name, sha: hex(name + when, 64) }; return id; };
      [['BANK_STATEMENT_TRANSACTIONS', 'HBL_bank_txns_oct26.csv', '11:41'], ['FX_CONVERSIONS', 'HBL_fx_conversions_oct26.csv', '11:43'], ['FUNDS_IN_TRANSIT', 'HBL_funds_in_transit_oct26.csv', '11:46']].forEach((u) => { ops.evidence(c, at('2026-11-10T' + u[2]), { staging_id: stage(u[1], u[2]), category: catByCode(u[0]).category }); drain(c); });
      [[2, 'MAP'], [7, 'MAP']].forEach((d, i) => ops.decision(c, at('2026-11-10T14:1' + i), bank().file_version_id, { action: d[1], source_index: d[0] }));
      ops.confirm(c, at('2026-11-10T14:40'), bank().file_version_id); drain(c);
      ops.defer(c, at('2026-11-10T14:52')); ops.resume(c, at('2026-11-12T09:18'));
      ops.activate(c, at('2026-11-12T09:20'), { confirm: true });
      controls.failNextRecon = true; ops.reconcile(c, at('2026-11-12T09:22')); drain(c);
      ops.reconcile(c, at('2026-11-12T09:23')); ops.defer(c, at('2026-11-12T09:25')); drain(c);
    });
    // Completed, clean
    run(() => { const c = reg('Ashgrove Card Ltd', 'CUS-1012', '2026-09', 'ASHGROVE_SG_SEP2026.zip', '2026-10-02T14:47', { evidence: 'clean', recon: 'clean' }, 'RF-2026-09-001'); ops.start(c, at('2026-11-03T10:00')); drain(c); const b = versions(c).find((v) => v.version_status === 'REVIEW_REQUIRED'); b.review.rows.forEach((r, i) => ops.decision(c, at('2026-11-03T10:1' + i), b.file_version_id, { action: 'MAP', source_index: r.source_index })); ops.confirm(c, at('2026-11-03T10:15'), b.file_version_id); drain(c); ops.activate(c, at('2026-11-03T15:52'), { confirm: true }); ops.reconcile(c, at('2026-11-03T15:55')); drain(c); });
    // Pending: failed run (Retry from Beginning after Resume)
    run(() => { const c = reg('Quayside FX Ltd', 'CUS-1007', '2026-10', 'QuaysideFX_Safeguarding_10-2026.zip', '2026-11-17T14:30', { evidence: 'clean', recon: 'clean', failFirstRun: true }, 'RF-2026-10-002'); ops.start(c, at('2026-11-18T12:40')); drain(c); ops.defer(c, at('2026-11-18T12:47')); });
    // Pending: partial review with retained decisions
    run(() => { const c = reg('Ashgrove Card Ltd', 'CUS-1012', '2026-10', 'ASHGROVE_SG_OCT2026.zip', '2026-11-16T13:05', { evidence: 'exceptions', recon: 'clean' }, 'RF-2026-10-003'); ops.start(c, at('2026-11-17T09:30')); drain(c); const b = versions(c).find((v) => v.version_status === 'REVIEW_REQUIRED'); ops.decision(c, at('2026-11-17T09:41'), b.file_version_id, { action: 'MAP', source_index: 5 }); ops.defer(c, at('2026-11-17T17:12')); });
    // Waiting: the three demo journeys and a second case for one customer and period
    reg('Kestrel Card Services Ltd', 'CUS-1002', '2026-10', 'KCS_SG_evidence_2026-10.zip', '2026-11-17T16:41', { evidence: 'clean', recon: 'clean' }, 'RF-2026-10-004');
    reg('Northgate E-Money Ltd', 'CUS-1003', '2026-10', 'northgate_oct26_safeguarding.zip', '2026-11-18T11:05', { evidence: 'exceptions', recon: 'exceptions' }, 'RF-2026-10-005');
    reg('Fernhill Pay Ltd', 'CUS-1005', '2026-10', 'Fernhill-Oct-2026.zip', '2026-11-18T14:22', { evidence: 'correction', recon: 'clean' }, 'RF-2026-10-006');
    reg('Harbourline Payments Ltd', 'CUS-1001', '2026-10', 'Harbourline_Safeguarding_Oct2026_supplement.zip', '2026-11-18T16:05', { evidence: 'clean', recon: 'incomplete' }, 'RF-2026-10-007');
    seq.case['2026-10'] = 7; seq.case['2026-09'] = 1;
  }

  /* ---------- the service ---------- */
  const later = (fn) => new Promise((resolve, reject) => setTimeout(() => { try { tick(now()); const out = fn(now()); tick(now()); resolve(clone(out)); } catch (e) { reject(e && e.error ? e : { status: 500, error: 'INTERNAL', message: String(e && e.message || e) }); } }, o.latency));
  const timer = setInterval(() => tick(now()), 200);
  const sorted = () => {
    const all = Object.values(st.cases), by = (s) => all.filter((c) => c.status === s);
    return by('IN_PROGRESS').concat(by('WAITING').concat(by('PENDING')).sort((a, b) => a.created_at - b.created_at), by('COMPLETED').sort((a, b) => b.last_activity_at - a.last_activity_at));
  };
  reset();
  const svc = {
    kind: 'mock', label: 'Mock data service · in-browser, no backend connected', now, controls,
    getApp: () => later(() => ({ reviewer: analyst, llm: { mode: 'RECORDED', label: 'Recorded proposals (mock). No live LLM.' }, engine_configured: true, categories: CATS.map((k) => ({ category: k.category, title: k.title, required: k.required, format: k.format })) })),
    listCases: (q) => later(() => { const all = sorted(), a = slotCase(); const counts = {}; ['WAITING', 'IN_PROGRESS', 'PENDING', 'COMPLETED'].forEach((k) => { counts[k] = all.filter((c) => c.status === k).length; }); return { items: all.filter((c) => !q || !q.status || c.status === q.status).map(summaryPayload), counts, active_case_ref: a ? a.case_ref : null, active_case: a ? { case_ref: a.case_ref, customer_name: a.customer_name, reporting_period: a.reporting_period, deferring: a.deferring } : null, ordering: 'in progress first; then WAITING and PENDING oldest first; then COMPLETED newest first' }; }),
    registerCase: (q) => later((t) => detail(register(q, t))),
    getCase: (ref) => later(() => detail(C(ref))),
    claimCase: (ref) => later(() => { const c = C(ref); if (!c.assigned_to) c.assigned_to = analyst.reviewer_id; return detail(c); }),
    startCase: (ref, q) => later((t) => { const c = C(ref); expect(c, q); ops.start(c, t); return detail(c); }),
    deferCase: (ref, q) => later((t) => { const c = C(ref); expect(c, q); ops.defer(c, t); return detail(c); }),
    resumeCase: (ref, q) => later((t) => { const c = C(ref); expect(c, q); ops.resume(c, t); return detail(c); }),
    retryCase: (ref, q) => later((t) => { const c = C(ref); expect(c, q); ops.retry(c, t, q); return detail(c); }),
    validateCase: (ref) => later((t) => { const c = C(ref); if (c.activation) fail(409, 'PACKAGE_LOCKED', 'The package is ACTIVE and locked.'); mustWork(c); maybeValidate(c, t); return detail(c); }),
    stageFile: (q) => later(() => { const id = 'STG-' + (seq.stg++); st.staging[id] = { name: q.name, sha: hex(q.name + (q.data_b64 || '').length + Date.now(), 64) }; return { entries: [{ staging_id: id, name: q.name }] }; }),
    submitEvidence: (ref, q) => later((t) => { const c = C(ref); const j = ops.evidence(c, t, q); return { job_id: j.job_id, case: detail(c) }; }),
    activateCase: (ref, q) => later((t) => { const c = C(ref); const r = ops.activate(c, t, q); return Object.assign(r, { case: detail(c) }); }),
    reconcileCase: (ref, q) => later((t) => { const c = C(ref); const j = ops.reconcile(c, t, q); return { job_id: j.job_id, case: detail(c) }; }),
    getRun: (ref, runId) => later(() => { const c = C(ref), r = c.runs.find((x) => x.run_id === runId) || fail(404, 'NOT_FOUND', 'Run not found.'); return Object.assign(runPayload(c, r), { stages: clone(r.stages), events: clone(r.events), llm_mode: { mode: 'RECORDED', label: 'Recorded proposals (mock). No live LLM.' } }); }),
    getReview: (ref, vid) => later(() => { const c = C(ref), v = findVersion(c, vid) || fail(404, 'NOT_FOUND', 'File version not found.'); if (!v.review) fail(404, 'NOT_FOUND', 'No review for this file version.'); return reviewPayload(c, v); }),
    postDecision: (ref, vid, q) => later((t) => { const c = C(ref); const action = q.action === 'IGNORE_COLUMN' ? 'IGNORE' : q.action; ops.decision(c, t, vid, q); return action === 'REJECT' ? detail(c) : reviewPayload(c, findVersion(c, vid)); }),
    confirmReview: (ref, vid, q) => later((t) => { const c = C(ref); expect(c, q); ops.confirm(c, t, vid); return detail(c); }),
    rejectReview: (ref, vid, q) => later((t) => { const c = C(ref); expect(c, q); ops.reject(c, t, vid); return detail(c); }),
    getActivity: (ref) => later(() => { const c = C(ref); return { case_ref: c.case_ref, chain: { verified: true, events: c.events.length }, status_history: clone(c.status_history), events: clone(c.events).reverse() }; }),
    listCustomers: () => later(() => st.customers.map((cu) => { const cs = Object.values(st.cases).filter((c) => c.customer_id === cu.customer_id); const by = { WAITING: 0, IN_PROGRESS: 0, PENDING: 0, COMPLETED: 0 }; cs.forEach((c) => { by[c.status]++; }); return { customer_id: cu.customer_id, customer_name: cu.customer_name, cases: cs.length, by_status: by }; })),
    getCustomer: (id) => later(() => { const cu = st.customers.find((x) => x.customer_id === id) || fail(404, 'NOT_FOUND', 'Customer not found.'); const cs = sorted().filter((c) => c.customer_id === id); return { customer_id: cu.customer_id, customer_name: cu.customer_name, cases: cs.map(summaryPayload), reconciliation_history: cs.filter((c) => c.completed).map((c) => ({ case_ref: c.case_ref, reporting_period: c.reporting_period, at: c.completed.at, reconciliation_run_id: c.completed.reconciliation_run_id, snapshot_id: c.completed.snapshot_id, case_status: c.completed.case_status })) }; }),
    getFileVersion: (pid, vid) => later(() => { const c = Object.values(st.cases).find((x) => x.pkg && findVersion(x, vid)) || fail(404, 'NOT_FOUND', 'File version not found.'); const v = findVersion(c, vid), slot = c.pkg.slots[v.evidence_category]; const strip = (x) => { const y = clone(x); delete y.plan; delete y.review; delete y.job_id; return Object.assign(y, { review_state: x.review ? x.review.state : null }); }; return { version: strip(v), history: slot.versions.map(strip), decisions: v.review ? v.review.rows.filter((r) => r.decision).map((r) => Object.assign({ source_header: r.source_header, source_index: r.source_index }, r.decision)) : [], events: c.events.filter((e) => e.details && e.details.file_version_id === vid) }; }),
    getVersionColumns: (pid, vid) => later(() => { const c = Object.values(st.cases).find((x) => x.pkg && findVersion(x, vid)) || fail(404, 'NOT_FOUND', 'File version not found.'); const v = findVersion(c, vid); return { columns: v.review ? v.review.rows.map((r) => ({ source_header: r.source_header, samples: r.samples, rows: 2418, empty: 0, distinct: new Set(r.samples).size })) : [] }; }),
    getVersionPreview: (pid, vid) => later(() => { const c = Object.values(st.cases).find((x) => x.pkg && findVersion(x, vid)) || fail(404, 'NOT_FOUND', 'File version not found.'); const v = findVersion(c, vid); const rows = v.review ? v.review.rows : []; const head = rows.filter((r) => r.decision && r.decision.canonical_field).map((r) => r.decision.canonical_field); return head.length ? head.join(',') + '\n' + [0, 1, 2].map((i) => rows.filter((r) => r.decision && r.decision.canonical_field).map((r) => r.samples[i] || '').join(',')).join('\n') + '\n' : 'source_file,rows\n' + v.original_filename + ',synthetic preview (mock)\n'; }),
    getPackageHistory: (pid) => later(() => { const c = Object.values(st.cases).find((x) => x.pkg && x.pkg.package_id === pid) || fail(404, 'NOT_FOUND', 'Package not found.'); return { categories: Object.values(c.pkg.slots).filter((s) => s.versions.length).map((s) => ({ evidence_category: s.evidence_category, versions: s.versions.map((v) => ({ file_version_id: v.file_version_id, version_number: v.version_number, version_status: v.version_status, original_filename: v.original_filename, received_at: v.received_at, source_sha256: v.source_sha256, intake_id: v.intake_id })) })), snapshots: clone(c.pkg.snapshots), validations: clone(c.pkg.validations) }; }),
    getSnapshot: (pid, sid) => later(() => { const c = Object.values(st.cases).find((x) => x.activation && x.activation.snapshot_id === sid) || fail(404, 'NOT_FOUND', 'Snapshot not found.'); return { snapshot: { snapshot_id: sid, created_at: c.activation.activated_at, entries: versions(c).map((v) => ({ evidence_category: v.evidence_category, file_version_id: v.file_version_id, version_number: v.version_number, original_filename: v.original_filename, source_sha256: v.source_sha256 })) }, manifest: { sha256: c.activation.manifest_sha256 }, is_active: true, verification: ['SV-1', 'SV-2', 'SV-3', 'SV-4', 'SV-5'].map((id) => ({ check_id: id, passed: true })), reconciliation_eligible: c.status === 'IN_PROGRESS', runs: c.recons.map((id) => ({ run_id: id, state: st.recons[id].state })) }; }),
    getJob: (jobId) => later(() => { const x = st.jobs[jobId] || fail(404, 'NOT_FOUND', 'Job not found.'); const j = x.job; return { job_id: j.job_id, kind: j.kind, state: j.state, stages: [], files: clone(j.files), progress: { stage: j.stage }, run_id: j.run_id }; }),
    getReconRun: (runId) => later(() => { const r = st.recons[runId] || fail(404, 'NOT_FOUND', 'Run not found.'); return { run_id: r.run_id, state: r.state, snapshot_id: r.snapshot_id, started_at: r.started_at, accepted_at: r.accepted_at, finished_at: r.finished_at, error: r.error, case_status: r.case_status, exception_count: r.exceptions.length, total_results: r.controls.length, outcomes: clone(r.outcomes), integrity_checks: r.state === 'COMPLETED' ? [{ check: 'SNAPSHOT_MANIFEST', passed: true }] : [], exceptions: r.exceptions.map((e) => { const y = clone(e); delete y.refs; delete y.checks; return y; }) }; }),
    getControls: (runId, q) => later(() => { const r = st.recons[runId] || fail(404, 'NOT_FOUND', 'Run not found.'); const rows = r.controls.filter((x) => (!q || !q.outcome || x.outcome === q.outcome) && (!q || !q.check || x.check_id === q.check)); return { total: rows.length, rows: clone(rows), truncated: false }; }),
    getReport: (runId) => later(() => { const r = st.recons[runId] || fail(404, 'NOT_FOUND', 'Run not found.'); return '# Reconciliation report (MOCK)\n\nRun ' + r.run_id + ' · snapshot ' + r.snapshot_id + '\n\nCase status: ' + (r.case_status || r.state) + '\n\n' + (r.outcomes ? Object.keys(r.outcomes).map((k) => '- ' + k + ': ' + r.outcomes[k]).join('\n') : '') + '\n'; }),
    getException: (runId, excId) => later(() => {
      const r = st.recons[runId] || fail(404, 'NOT_FOUND', 'Run not found.'), c = st.cases[r.ref], e = r.exceptions.find((x) => x.exception_id === excId) || fail(404, 'NOT_FOUND', 'Exception not found.');
      const fileFor = { balances: 'SAFEGUARDING_ACCOUNT_BALANCES', 'bank txns': 'BANK_STATEMENT_TRANSACTIONS', ledger: 'EMONEY_LIABILITY_LEDGER', 'daily recon': 'DAILY_SAFEGUARDING_RECON', 'scheme settlements': 'SCHEME_SETTLEMENTS', receipts: 'RELEVANT_FUNDS_RECEIPTS', 'fx conversions': 'FX_CONVERSIONS', 'funds in transit': 'FUNDS_IN_TRANSIT' };
      const evidence = e.refs.map((ref, i) => { const m = ref.match(/^(.*) v\d · (r[\d,–r]+)$/) || [ref, ref, '']; const cat = catByCode(fileFor[m[1]] || 'SAFEGUARDING_ACCOUNT_BALANCES'); const v = versions(c).find((x) => x.evidence_category === cat.category); return { reference: ref, evidence_category: cat.category, file_version_id: v ? v.file_version_id : null, intake_id: v ? v.intake_id : null, source_sha256: v ? v.source_sha256 : null, original_filename: v ? v.original_filename : m[1], version_number: v ? v.version_number : 1, line: parseInt((m[2] || '').replace(/\D.*/, '').replace('r', ''), 10) || i + 2, row: i === 0 ? { amount: String(e.amount), currency: e.currency, date: e.period } : { reference: ref } }; });
      return { exception: clone(Object.assign({}, e, { refs: undefined, checks: undefined })), affected_control_results: r.controls.filter((x) => e.checks.includes(x.check_id) && x.account === e.account.replace(/^.* (GBP|EUR) /, '$1 ')).concat(r.controls.filter((x) => e.checks.includes(x.check_id) && x.outcome === 'FAIL')).filter((x, i, arr) => arr.indexOf(x) === i), evidence, investigation_group: e.root_cause, note: 'Read-only finding. Investigation happens outside Ringfence in this POC.' };
    }),
    // Demo scenarios exist only on a real backend started with --demo-scenarios; the mock has none.
    listDemoScenarios: () => later(() => fail(404, 'DEMO_DISABLED', 'Demo scenarios need the Ringfence backend (--demo-scenarios); the mock has none.')),
    loadDemoScenario: () => later(() => fail(404, 'DEMO_DISABLED', 'Demo scenarios need the Ringfence backend.')),
    getDemoVerification: () => later(() => fail(404, 'DEMO_DISABLED', 'Demo scenarios need the Ringfence backend.')),
    // Closure (audit pack, AI investigations, final pack) exists only on the Ringfence backend. The mock never fakes it.
    getAiConfiguration: () => later(() => fail(404, 'NOT_AVAILABLE', 'AI configuration is reported by the Ringfence backend only; the mock has no AI.')),
    getClosure: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getClosurePack: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getClosureException: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    startInvestigation: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getInvestigation: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    decideInvestigation: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getExceptionHistory: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    openClosingReview: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    setClosingSelections: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    requestClosingPreview: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    decideClosingReview: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getFinalPack: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    getClosureHistory: () => later(() => fail(404, 'NOT_AVAILABLE', CLOSURE_MOCK)),
    /* MOCK ONLY · not part of the contract */
    mock: { setFailNextRun: (v) => { controls.failNextRun = !!v; }, setFailNextRecon: (v) => { controls.failNextRecon = !!v; }, setSpeed: (v) => { controls.speed = v; }, reset, dispose: () => clearInterval(timer) }
  };
  return assertDataService(svc);
}
