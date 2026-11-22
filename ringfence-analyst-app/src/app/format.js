/* Formatting and backend-enum presentation. Times are ISO UTC from the backend, shown in UK time. */
import { STATES } from '../ui/design.js';

/* Backend enum values not already in the design registry (contract §2). Keys are the enum names. */
const add = (key, label, tone, glyph) => { if (!STATES[key]) STATES[key] = { key, label, tone, glyph, enumName: key }; };
add('RECEIVED', 'Received', 'neutral', 'pending');
add('REJECTED', 'Rejected', 'danger', 'danger');
add('INCOMPLETE', 'Incomplete', 'attention', 'warning');
add('READY_FOR_VALIDATION', 'Ready for validation', 'progress', 'pending');
add('RECONCILIATION_READY', 'Reconciliation ready', 'success', 'sealed');
add('PROCESSING', 'Running', 'progress', 'progress'); // run status PROCESSING is shown as Running (contract §7)
add('FAILED', 'Failed', 'danger', 'danger');
add('PASSED', 'Passed', 'success', 'success');
add('NOT_RUN', 'Not run', 'neutral', 'pending');
add('RUNNING', 'Running', 'progress', 'progress');
add('DEFERRAL_REQUESTED', 'Deferral requested', 'attention', 'paused');
add('ACTIVE_LOCKED', 'Active · locked', 'locked', 'sealed');
/* Closure (audit pack, AI investigation, analyst decision, closing review, final pack). */
add('NOT_STARTED', 'Not started', 'neutral', 'pending');
add('QUEUED', 'Queued', 'neutral', 'waiting');
add('PUBLISHED', 'Published', 'success', 'success');
add('NOT_PUBLISHED', 'Not published', 'attention', 'warning');
add('UNAVAILABLE', 'Unavailable', 'neutral', 'na');
add('ACCEPT', 'Accepted', 'success', 'success');
add('REJECT', 'Rejected', 'danger', 'danger');
add('GENERATED', 'Generated', 'success', 'sealed');
add('PACK_PENDING', 'Audit pack pending', 'progress', 'progress');
add('PACK_UNAVAILABLE', 'Audit pack unavailable', 'attention', 'warning');
add('INVESTIGATING', 'AI investigating', 'progress', 'progress');
add('DECIDING', 'Awaiting decisions', 'attention', 'review');
add('READY', 'Ready for preview', 'progress', 'pending');
add('PREVIEW_READY', 'Preview ready', 'success', 'success');
add('ON_HOLD', 'On hold', 'attention', 'paused');
add('GENERATING', 'Generating', 'progress', 'progress');
add('GENERATION_FAILED', 'Generation failed', 'danger', 'danger');
add('INCLUDED', 'Included', 'success', 'success');
add('NOT_INVESTIGATED', 'Not investigated', 'neutral', 'na');
add('EXCLUDED_BY_ANALYST', 'Excluded by analyst', 'attention', 'skipped');
add('VALID', 'Valid', 'success', 'success');
add('INVALID', 'Invalid', 'danger', 'danger');

export const TZ = 'Europe/London';
const f = (o) => new Intl.DateTimeFormat('en-GB', Object.assign({ timeZone: TZ }, o));
const F = { dt: f({ day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }), d: f({ day: 'numeric', month: 'short', year: 'numeric' }), t: f({ hour: '2-digit', minute: '2-digit' }), ts: f({ hour: '2-digit', minute: '2-digit', second: '2-digit' }), day: f({ weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) };
const ok = (iso) => iso && !isNaN(Date.parse(iso));
export const fmtDateTime = (iso) => (ok(iso) ? F.dt.format(new Date(iso)) : '—');
export const fmtDate = (iso) => (ok(iso) ? F.d.format(new Date(iso)) : '—');
export const fmtTime = (iso) => (ok(iso) ? F.t.format(new Date(iso)) : '—');
export const fmtTimeSec = (iso) => (ok(iso) ? F.ts.format(new Date(iso)) : '—');
export const fmtDay = (iso) => (ok(iso) ? F.day.format(new Date(iso)) : '—');
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const fmtPeriod = (p) => { const m = /^(\d{4})-(\d{2})$/.exec(p || ''); return m ? MONTHS[+m[2] - 1] + ' ' + m[1] : p || '—'; };
export const periodRange = (p) => { const m = /^(\d{4})-(\d{2})$/.exec(p || ''); if (!m) return p || '—'; const last = new Date(Date.UTC(+m[1], +m[2], 0)).getUTCDate(); return '1–' + last + ' ' + MONTHS[+m[2] - 1].slice(0, 3) + ' ' + m[1]; };
export const fmtBytes = (n) => (n == null ? '—' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
export function fmtAgo(iso, nowMs) {
  if (!ok(iso)) return '—';
  const s = Math.max(0, Math.round(((nowMs || Date.now()) - Date.parse(iso)) / 1000));
  if (s < 60) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' min ago'; if (s < 86400) return Math.round(s / 3600) + ' h ago';
  return Math.round(s / 86400) + ' d ago';
}
export const catTitle = (app, id) => { const c = app && app.categories && app.categories.find((x) => x.category === id); return c ? c.title : id; };
export const catInfo = (app, id) => (app && app.categories && app.categories.find((x) => x.category === id)) || { category: id, title: id, required: false, format: '' };
export const analystOf = (app) => {
  const r = (app && app.reviewer) || {};
  const name = r.name || (r.reviewer_id || 'Analyst').split(/[._-]/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  return { name, initials: name.split(' ').map((w) => w.charAt(0)).join('').slice(0, 2).toUpperCase(), role: (r.role ? r.role.charAt(0).toUpperCase() + r.role.slice(1) : 'Analyst') + (r.kind ? ' · ' + r.kind : ''), email: r.reviewer_id || '' };
};
/* Contract step keys → labels, and step state → CaseProgress state. */
export const STEP_KEYS = ['smart_parser', 'review', 'validation', 'activation', 'reconciliation'];
export const stepStates = (c) => STEP_KEYS.map((k) => ((c && c.steps) || []).find((s) => s.key === k) || { key: k, state: 'todo' }).map((s) => s.state);
/* Run stage status (contract §3.5) → Stages component state. */
export const STAGE_STATE = { pending: 'pending', running: 'running', completed: 'done', requires_review: 'attention', requires_attention: 'attention', not_required: 'skipped', blocked: 'pending', failed: 'failed' };
export const STAGE_LABEL = { pending: 'Pending', running: 'Running', completed: 'Completed', requires_review: 'Requires review', requires_attention: 'Requires attention', not_required: 'Not required', blocked: 'Blocked', failed: 'Failed' };
/* Severity from the engine: Critical / High (contract §7) → the design's severity bars. */
export const sevLevel = (s) => ({ Critical: 'high', High: 'medium' }[s] || 'low');
export const reconRunId = (c) => (c && ((c.progress && c.progress.reconciliation && c.progress.reconciliation.run_id) || (c.completed && c.completed.reconciliation_run_id))) || null;
/* outstanding.unreadable_members (cases.py: {name, size, error_kind, error, original_zip_sha256, open, hint}) and the
   run's unreadable_entries: ZIP members that could not be read and were isolated. `open` = a corrected file is still
   needed. While one is open the missing required categories are shown as the backend's hint on that item, not as a
   separate "N categories missing" list (which reads as if the whole submission were missing). */
export const unreadableOf = (list) => (list || []).map((x) => (typeof x === 'string' ? { name: x, error: null, open: true }
  : { name: x.name || x.member || x.filename || '—', error: x.error || null, errorKind: x.error_kind || null, size: x.size, open: x.open !== false, hint: x.hint || null, zipSha: x.original_zip_sha256 || null }));
export const missingNotUnreadable = (o) => (unreadableOf(o && o.unreadable_members).some((u) => u.open) ? [] : ((o && o.missing_categories) || []));
