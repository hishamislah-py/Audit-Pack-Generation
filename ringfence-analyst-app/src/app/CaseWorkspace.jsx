/* Case workspace (S05–S14): case header, lifecycle actions, banner and tabs.
   Loads the case detail (GET /api/cases/{ref}) and polls it per contract §5. Status, steps,
   actions and reasons are rendered exactly as the backend returns them. */
import React from 'react';
import { useQuery, useMutation } from './hooks.js';
import { STATES } from '../ui/design.js';
import { CaseHeader, CaseBanner, Pill, Button, WithReason, Dialog, Notice, Skeleton, Empty, KV, Hash, Bullets } from '../ui/index.jsx';
import { fmtDateTime, fmtPeriod, periodRange, fmtBytes, missingNotUnreadable } from './format.js';
import OverviewTab from './case/Overview.jsx';
import EvidenceTab from './case/Evidence.jsx';
import ParserTab from './case/Parser.jsx';
import ReviewTab from './case/Review.jsx';
import PackageTab from './case/Package.jsx';
import ReconTab from './case/Recon.jsx';
import ActivityTab from './case/Activity.jsx';
import ClosingTab from './case/Closing.jsx';

const TABS = { overview: OverviewTab, evidence: EvidenceTab, parser: ParserTab, review: ReviewTab, package: PackageTab, recon: ReconTab, closing: ClosingTab, activity: ActivityTab };

// Contract step states (done/current/attention/failed/paused/todo) → lifecycle tab glyphs.
[['done', 'Done', 'success', 'success'], ['current', 'In progress', 'progress', 'progress'], ['attention', 'Needs attention', 'attention', 'review'], ['failed', 'Failed', 'danger', 'danger'], ['paused', 'Paused · case Pending', 'neutral', 'paused'], ['todo', 'Not started', 'neutral', 'pending']]
  .forEach(([k, l, t, g]) => { if (!STATES['STEP_' + k]) STATES['STEP_' + k] = { key: 'STEP_' + k, label: l, tone: t, glyph: g, enumName: k }; });
const stepOf = (c, key) => { const s = (c.steps || []).find((x) => x.key === key); return s ? s.state : 'todo'; };

function tabSteps(c) {
  const p = c.progress || {}, o = c.outstanding || {};
  const val = stepOf(c, 'validation'), act = stepOf(c, 'activation');
  const fixes = missingNotUnreadable(o).length + (o.files_requiring_replacement || []).length + (o.unreadable_members || []).filter((u) => u.open !== false).length;
  const exc = p.reconciliation && p.reconciliation.state === 'COMPLETED' ? p.reconciliation.exceptions : 0;
  return {
    evidence: fixes ? { count: fixes, countTone: 'attention', title: fixes + ' evidence item(s) need action' } : {},
    parser: { state: 'STEP_' + stepOf(c, 'smart_parser'), title: 'Smart Parser · ' + stepOf(c, 'smart_parser') },
    review: { state: 'STEP_' + stepOf(c, 'review'), count: p.decisions_outstanding || null, countTone: 'attention', title: 'Review · ' + stepOf(c, 'review') },
    package: { state: 'STEP_' + (act === 'done' ? 'done' : val === 'done' ? 'current' : val), locked: !!c.activation, title: c.activation ? 'ACTIVE and locked as ' + c.activation.snapshot_id : 'Validation · ' + val + ', activation · ' + act },
    recon: { state: 'STEP_' + stepOf(c, 'reconciliation'), count: exc || null, countTone: 'danger', title: 'Reconciliation · ' + stepOf(c, 'reconciliation') },
    closing: c.status === 'COMPLETED' ? { title: 'Closing & Audit Pack · available after reconciliation' } : { title: 'Closing & Audit Pack · after reconciliation completes' }
  };
}

function Banner({ c, nav }) {
  const b = c.blocked_by;
  const open = b ? <Button size="sm" iconRight="arrowRight" onClick={() => nav('cases/' + b.case_ref + '/overview')}>Open {b.case_ref}</Button> : null;
  if (c.status === 'WAITING') return b
    ? <CaseBanner kind="blocked" title="Waiting · cannot start yet." actions={open}>{b.case_ref} ({b.customer_name}, {fmtPeriod(b.reporting_period)}) is In Progress. Only one case can be In Progress at a time.</CaseBanner>
    : <CaseBanner kind="waiting" title="Waiting.">The original ZIP is attached; nothing has been processed. Opening a case never starts it.</CaseBanner>;
  if (c.status === 'PENDING') return <CaseBanner kind={b ? 'pending-blocked' : 'pending'} title="Pending · read-only." actions={open}>{b ? b.case_ref + ' is In Progress. It must be deferred before this case can resume.' : 'Resume Processing to continue. Kept work is listed in Overview.'}</CaseBanner>;
  if (c.status === 'COMPLETED') { const d = c.completed || {}; return <CaseBanner kind="completed" title="Completed · read-only.">Reconciliation finished {fmtDateTime(d.at)} on snapshot <span className="rf-mono">{d.snapshot_id}</span> · {d.case_status}.</CaseBanner>; }
  if (c.deferring) { const w = (c.deferral && c.deferral.waiting_for) || []; return <CaseBanner kind="deferring" title="Deferral requested.">The running operation continues and is not interrupted. The case becomes Pending when it finishes{w.length ? ' (waiting for ' + w.map((x) => x.kind + (x.job_id ? ' ' + x.job_id : '')).join(', ') + ')' : ''}.</CaseBanner>; }
  return <CaseBanner kind="in-progress" title="In Progress.">{((c.progress && c.progress.summary) || []).slice(0, 2).join(' · ')}</CaseBanner>;
}

function LifecycleActions({ c, open }) {
  const a = c.actions || {};
  const btn = (kind, label, variant, icon) => {
    const x = a[kind === 'retry' ? 'retry_from_beginning' : kind] || {};
    const b = <Button variant={variant} icon={icon} disabled={!x.enabled} onClick={() => open(kind)}>{label}</Button>;
    return x.enabled ? <React.Fragment key={kind}>{b}</React.Fragment> : <WithReason key={kind} reason={x.reason}>{b}</WithReason>;
  };
  const out = [];
  if (c.status === 'WAITING') out.push(btn('start', 'Start Smart Parsing', 'primary', 'play'));
  if (c.status === 'PENDING') out.push(btn('resume', 'Resume Processing', 'primary', 'play'));
  if (c.status === 'IN_PROGRESS') {
    if (c.current_run && c.current_run.status === 'FAILED') out.push(btn('retry', 'Retry from Beginning', 'primary', 'refresh'));
    out.push(btn('defer', c.deferring ? 'Deferral requested' : 'Defer Case', 'secondary', 'pause'));
  }
  return <div className="rf-row rf-row--top" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>{out}</div>;
}

/* Start / Defer / Resume / Retry confirmation dialogs (S05, S06). */
const ACTIONS = {
  start: { eyebrow: 'Start Smart Parsing', title: 'Start Smart Parsing for this case?', confirm: 'Start Smart Parsing', icon: 'play', after: 'parser', success: 'Smart Parsing started',
    call: (svc, c) => svc.startCase(c.case_ref, { expected_revision: c.revision }) },
  defer: { eyebrow: 'Defer Case', title: 'Defer this case?', confirm: 'Defer Case', icon: 'pause', variant: 'secondary',
    success: (r) => (r && r.status === 'PENDING' ? 'Case deferred · Pending' : 'Deferral requested · the running operation continues'),
    call: (svc, c) => svc.deferCase(c.case_ref, { expected_revision: c.revision }) },
  resume: { eyebrow: 'Resume Processing', title: 'Resume processing this case?', confirm: 'Resume Processing', icon: 'play', success: 'Processing resumed · In Progress',
    call: (svc, c) => svc.resumeCase(c.case_ref, { expected_revision: c.revision }) },
  retry: { eyebrow: 'Retry from Beginning', title: 'Start a new run from the original ZIP?', confirm: 'Retry from Beginning', icon: 'refresh', ack: 'I understand that files uploaded to the failed run are not carried forward and must be uploaded again.', after: 'parser', success: 'New run started from the original ZIP',
    call: (svc, c) => svc.retryCase(c.case_ref, { confirm: true, expected_revision: c.revision }) }
};

function ActionDialog({ kind, c, onClose, nav }) {
  const d = ACTIONS[kind];
  const m = useMutation();
  const [ack, setAck] = React.useState(false);
  const op = c.progress && c.progress.current_operation;
  const run = c.current_run;
  const go = async () => {
    const r = await m.run((svc) => d.call(svc, c), { inline: true, success: d.success });
    if (r) { onClose(); if (d.after) nav('cases/' + c.case_ref + '/' + d.after); }
  };
  let body;
  if (kind === 'start') body = <>
    <KV pairs={[['Original ZIP', <span key="z">{c.zip.filename} <span className="rf-muted">· {fmtBytes(c.zip.size)}</span></span>], ['SHA-256', <Hash key="h" sha={c.zip.sha256} />]]} />
    <Bullets items={[['layers', 'The case takes the In Progress slot. Only one case can be In Progress at a time.'], ['parser', 'Smart Parser reads the original ZIP and runs its stages. Progress is reported by the backend.'], ['mapping', 'Nothing is accepted automatically: columns that need a decision wait for your review.'], ['pause', 'You can defer at any time. A running operation always finishes first.']]} /></>;
  if (kind === 'defer') body = <>
    {op ? <Notice tone="attention" title="An operation is running" compact>{op.kind}{op.job_id ? ' · ' + op.job_id : ''} continues and is not interrupted. The deferral is requested now and takes effect when it finishes.</Notice> : null}
    <Bullets items={[['pause', 'The case becomes Pending and frees the In Progress slot.'], ['lock', 'A Pending case is read-only until you resume it.'], ['check', 'All completed work and recorded decisions are kept.']]} /></>;
  if (kind === 'resume') body = <>
    <Bullets items={[['play', 'The case takes the In Progress slot again.'], ['check', 'Work continues from what was kept; nothing is re-run.']]} />
    {(c.kept || []).length > 0 && <div className="rf-tasks__kept" style={{ marginTop: 12 }}><div className="rf-tasks__keptlabel">Kept</div><ul>{c.kept.map((k, i) => <li key={i}><span>{k}</span></li>)}</ul></div>}</>;
  if (kind === 'retry') body = <>
    {run && run.failure && <Notice tone="danger" title={'Run ' + run.run_no + ' failed · ' + run.failure.code} compact>{run.failure.message}</Notice>}
    <Bullets items={[['archive', 'A new Smart Parser run starts from the original ZIP (' + c.zip.filename + ').'], ['clock', 'The failed run stays in the history for audit.'], ['upload', 'Files uploaded to the failed run are not carried forward. Upload them again after the new run.']]} />
    <label className="rf-check-ack" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 12, fontSize: 13 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{d.ack}</span></label></>;
  const blocked = d.ack && !ack;
  const confirmBtn = <Button variant={d.variant || 'primary'} icon={d.icon} loading={m.busy} disabled={blocked} onClick={go}>{d.confirm}</Button>;
  return <div className="rf-layer"><Dialog eyebrow={d.eyebrow + ' · ' + c.case_ref} title={d.title} error={m.error} onClose={m.busy ? undefined : onClose}
    foot={<><Button onClick={onClose} disabled={m.busy}>Cancel</Button>{blocked ? <WithReason reason="Tick the acknowledgement first">{confirmBtn}</WithReason> : confirmBtn}</>}>{body}</Dialog></div>;
}

/* Case owner and the viewer's access (Fix8 D7). The backend decides (c.access, and every c.actions.* already carries
   the NOT_CASE_OWNER reason); this only shows it and offers the audited claim of an unassigned case. */
function Ownership({ c }) {
  const m = useMutation();
  const acc = c.access || {};
  const owner = c.assigned_to;
  const claim = () => m.run((svc) => svc.claimCase(c.case_ref, { expected_revision: c.revision }), { success: 'Case claimed · you are now the owner' });
  return <span className="rf-row" data-testid="case-owner" style={{ gap: 8, fontSize: 12, flexWrap: 'wrap' }}>
    <span className="rf-muted">Owner</span>
    <span className={owner ? 'rf-strong' : 'rf-muted'} data-testid="case-owner-name">{owner || 'Unassigned'}{acc.is_owner ? ' (you)' : ''}</span>
    {acc.enforced && acc.override && <span className="rf-tone-attention" data-testid="case-override-note" title="Every action you take on this case is recorded as SUPERVISOR_OVERRIDE">Supervisor · actions audited as override</span>}
    {acc.enforced && !acc.can_act && <span className="rf-tone-attention" data-testid="case-access-reason">{acc.reason}</span>}
    {acc.enforced && acc.can_claim && !owner && <Button size="sm" icon="check" loading={m.busy} onClick={claim} data-testid="case-claim">Claim case</Button>}
    {m.error && <span className="rf-tone-danger">{m.error}</span>}
  </span>;
}

export default function CaseWorkspace({ route, app, nav, store }) {
  const ref = route.ref, key = 'case:' + ref;
  const poll = store.casePoll(store.getQuery(key).data);
  const q = useQuery(key, (svc) => svc.getCase(ref), { poll });
  const [dlg, setDlg] = React.useState(null);
  React.useEffect(() => { setDlg(null); }, [ref]);
  const c = q.data;
  // Work queue "Start" (…/overview?action=start): open the normal Start confirmation once the case has loaded. Nothing
  // starts without that confirmation, and the backend's action availability (one In Progress case, state) still applies.
  const autoStart = React.useRef(!!(route.query && route.query.action === 'start'));
  React.useEffect(() => {
    if (!autoStart.current || !c) return;
    autoStart.current = false;
    const a = c.actions && c.actions.start;
    if (c.status === 'WAITING' && a && a.enabled) setDlg('start');
    else store.toast('attention', 'Start is not available for ' + c.case_ref + (a && a.reason ? ': ' + a.reason : ' (' + c.status + ')'));
    nav('cases/' + c.case_ref + '/overview');
  }, [c]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!c) {
    if (q.error) return <div className="rf-page"><Empty icon="alert" danger title={q.error.error === 'NOT_FOUND' ? 'Case not found' : 'The case could not be loaded'} action={<div className="rf-row"><Button onClick={q.reload}>Try again</Button><Button onClick={() => nav('queue')}>Work queue</Button></div>}>{q.error.message}</Empty></div>;
    return <div className="rf-page"><Skeleton rows={6} /></div>;
  }
  const Tab = TABS[route.tab] || OverviewTab;
  const tabNav = (id) => nav('cases/' + c.case_ref + '/' + id);
  const state = <div className="rf-row" style={{ flexWrap: 'wrap', gap: 8 }}>
    <Pill state={c.status} size="lg" />
    {c.deferring && <Pill state="DEFERRAL_REQUESTED" />}
    {c.completed && <Pill state={c.completed.case_status} />}
    <span className="rf-muted" style={{ fontSize: 12 }}>since {fmtDateTime(c.status_since)}</span>
    {q.error && <span className="rf-tone-danger" style={{ fontSize: 12 }} title={q.error.message}>Refresh failed: {q.error.message}</span>}
    <Ownership c={c} />
  </div>;
  return <>
    <CaseHeader c={{ customerId: c.customer_id, customer: c.customer_name, ref: c.case_ref, period: fmtPeriod(c.reporting_period), periodRange: periodRange(c.reporting_period), submission: c.zip.filename, receivedLabel: fmtDateTime(c.created_at) }}
      onNav={nav} tab={route.tab} onTab={tabNav} state={state} actions={<LifecycleActions c={c} open={setDlg} />} steps={tabSteps(c)} banner={<Banner c={c} nav={nav} />} />
    <Tab key={c.case_ref + ':' + route.tab} c={c} app={app} route={route} nav={nav} openAction={setDlg} store={store} />
    {dlg && ACTIONS[dlg] && <ActionDialog kind={dlg} c={c} nav={nav} onClose={() => setDlg(null)} />}
  </>;
}
