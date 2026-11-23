/* Reconciliation tab (S12) with the full-width exception workspace (S13, ExceptionWorkspace.jsx).
   Renders POST /reconcile, GET /api/runs/{run_id}, /controls, /report and /exceptions/{id} as returned
   (contract §3.4, §4). The run-level outcome (case_status CLEAN / EXCEPTIONS_OPEN / EVIDENCE_INCOMPLETE)
   is shown apart from the control-level outcomes (PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE).
   Exceptions are engine findings. The closure layer (impl_20261120 CONTRACT.md) adds the deterministic outcome
   summary, the audit pack status, the AI investigation state and the analyst decision per exception; RUN_FAILED is
   a technical failure and never a business outcome. */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, WithReason, Panel, KV, Notice, Table, Segmented, Tabs, Empty, Skeleton, Dialog, Pill, Enum, Ref, Hash, Money, Stats, SegBar, Outcome, Icon, Glyph, cx } from '../../ui/index.jsx';
import { fmtDateTime, sevLevel, reconRunId } from '../format.js';
import ExceptionWorkspace, { plainTitle } from './ExceptionWorkspace.jsx';
import StartReconButton, { reconAvailability } from './StartRecon.jsx';
import { useClosure, DeterministicSummary, PackStatusLine, AiState, DecisionCell, ClosureError } from './closure.jsx';

const OUTCOMES = [['PASS', 'pass', 'success', 'success'], ['FAIL', 'fail', 'danger', 'danger'], ['INSUFFICIENT_EVIDENCE', 'ie', 'warning', 'attention'], ['NOT_APPLICABLE', 'na', 'na', 'neutral']];
const CASE_STATUS = {
  CLEAN: ['Reconciliation clean', 'Every control result passed or did not apply. No exceptions were raised.'],
  EXCEPTIONS_OPEN: ['Exceptions open', 'At least one control failed. Each exception is a finding about the safeguarding position, not an evidence issue.'],
  EVIDENCE_INCOMPLETE: ['Evidence incomplete', 'At least one control could not be evaluated with the evidence in the snapshot.']
};
const JOB_PILL = { queued: 'RUN_QUEUED', running: 'RECON_RUNNING', completed: 'RUN_COMPLETED', failed: 'RUN_FAILED', interrupted: 'RUN_FAILED' };
/* Backend field names (smartparser/webapp/results.py: the engine's exceptions.csv / control_results.csv columns). */
const excTitle = (e) => e.title || e.category || e.root_cause;
const excAccount = (e) => e.account || e.account_id;
const excPeriod = (e) => e.period || (e.first_date ? (e.last_date && e.last_date !== e.first_date ? e.first_date + ' → ' + e.last_date : e.first_date) : null);

/* Overlays are anchored to the viewport so a scrolled page still shows them. */
const Layer = ({ drawer, children }) => <div className={cx('rfd-layer', drawer && 'rfd-layer--drawer')}>{children}</div>;
/* Engine severities are Critical / High (contract §7): the design's bars, with the engine's own word. */
function EngineSeverity({ value }) {
  return <span className={'rf-sev rf-sev--' + sevLevel(value)} title={'Engine severity: ' + value}><span className="rf-sev__bars" aria-hidden="true"><i /><i /><i /></span>{value || '—'}</span>;
}
function IntegrityList({ checks: raw }) {
  // The backend sends the run's integrity checks as { name: passed } (results.summary → reconciliation_run.json "checks").
  const checks = raw && !Array.isArray(raw) && typeof raw === 'object' ? Object.entries(raw).map(([check, passed]) => ({ check, passed: passed !== false })) : raw;
  if (!checks || !checks.length) return null;
  return <div className="rf-row rf-row--wrap" style={{ gap: '6px 16px' }}>{checks.map((k, i) => {
    const name = (k && (k.check || k.check_id || k.name)) || 'Integrity check ' + (i + 1);
    const passed = !k || k.passed !== false;
    return <span key={i} className={cx('rf-integrity', !passed && 'rfd-bad')}><Glyph name={passed ? 'success' : 'danger'} /><span className="rf-mono">{name}</span>{k && k.detail ? <span> · {k.detail}</span> : null}</span>;
  })}</div>;
}

export default function ReconTab({ c, app, route, nav, store }) {
  const ref = c.case_ref;
  const rec = (c.progress && c.progress.reconciliation) || { state: 'NOT_RUN' };
  const runs = ((c.package && c.package.jobs) || []).filter((j) => j.kind === 'reconciliation');
  const latest = rec.run_id || reconRunId(c) || (runs.length ? runs[runs.length - 1].run_id : null);
  const runId = route.sub || latest || null;
  const act = reconAvailability(c);
  const completed = c.status === 'COMPLETED';
  const go = (rid, exc) => nav('cases/' + ref + '/recon' + (rid ? '/' + rid + (exc ? '/' + exc : '') : ''));
  // One click, no confirmation: activates the package when needed, then starts the run (StartRecon.jsx).
  const runButton = completed ? null : <StartReconButton c={c} nav={nav} label={runs.length ? 'Run reconciliation again' : 'Start reconciliation'} />;
  const last = (c.status_history || []).slice(-1)[0];

  return <div className="rf-workspace">
    {completed && <Notice tone="locked" title="Case Completed · read-only">{'Completed ' + fmtDateTime(c.completed && c.completed.at) + (last && last.note ? ' · ' + last.note : '') + '. Results stay linked to their snapshot and run; nothing can be re-run or corrected.'}</Notice>}
    {c.deferring && <Notice tone="attention" title="Deferral requested">{'Requested ' + fmtDateTime(c.deferral && c.deferral.requested_at) + '. A deferral never interrupts a run: the running operation continues to the end.'}</Notice>}
    {app && app.engine_configured === false && <Notice tone="attention" title="Reconciliation engine not configured">The server reports no UC-042 engine, so reconciliation cannot run here.</Notice>}
    {runId && runId !== latest && latest && <Notice tone="info" compact actions={<Button size="sm" onClick={() => go(latest)}>Show latest run</Button>}>{'You are viewing an earlier run, ' + runId + '. The latest run is ' + latest + '.'}</Notice>}
    {!runId && !completed && (rec.state === 'RUNNING' || rec.state === 'QUEUED')
      ? <Panel title="Reconciliation running" sub="The evidence is sealed and the engine is evaluating the controls. Results appear here automatically." actions={<Pill state="RECON_RUNNING" />}>
          <div className="rf-row" style={{ gap: 8 }}><span className="rf-tone-progress"><Glyph name="progress" /></span><span className="rf-secondary">Starting the run…</span></div>
        </Panel>
      : runId
      ? <RunView key={runId} c={c} app={app} runId={runId} isLatest={runId === latest} rec={rec} runs={runs} store={store} go={go} route={route} runButton={runButton} nav={nav} />
      : <NotRun c={c} app={app} act={act} runButton={runButton} nav={nav} />}
  </div>;
}

function SnapshotPanel({ c, app }) {
  const a = c.activation;
  return <Panel title="Snapshot" sub="The sealed evidence the engine reconciles">
    {a ? <KV pairs={[['Snapshot', <Ref id={a.snapshot_id} copy />], ['Activated', fmtDateTime(a.activated_at) + (a.activated_by ? ' by ' + a.activated_by : '')], ['Manifest', a.manifest_sha256 ? <Hash sha={a.manifest_sha256} /> : '—'], ['Package', c.package ? <span className="rf-mono">{c.package.package_id}</span> : '—'], ['Engine', app && app.engine_configured ? 'UC-042 reconciliation · configured' : 'Not configured']]} />
      : <div className="rf-help">No snapshot yet. The evidence is sealed as a snapshot automatically when reconciliation starts.</div>}
  </Panel>;
}
function RunsList({ runs, runId, onSelect }) {
  if (!runs.length) return <div className="rf-help" style={{ padding: '12px 16px' }}>No reconciliation runs yet.</div>;
  return <ul className="rfd-runs">{runs.slice().reverse().map((j) => <li key={j.job_id} className={cx('rfd-run', j.run_id === runId && 'is-selected')} role="button" tabIndex={0} aria-current={j.run_id === runId || undefined} onClick={() => onSelect(j.run_id)} onKeyDown={(e) => { if (e.key === 'Enter') onSelect(j.run_id); }}>
    <div className="rf-row" style={{ justifyContent: 'space-between' }}><span className="rf-mono rf-strong">{j.run_id || j.job_id}</span><Pill state={JOB_PILL[j.state] || 'RUN_QUEUED'} label={j.state === 'interrupted' ? 'Interrupted' : undefined} /></div>
    <div className="rf-help">Job <span className="rf-mono">{j.job_id}</span> · started {fmtDateTime(j.created_at)}{j.finished_at ? ' · ended ' + fmtDateTime(j.finished_at) : ''}</div>
    {j.error && <div className="rfd-run__err">{j.error}</div>}
  </li>)}</ul>;
}

function NotRun({ c, app, act, runButton, nav }) {
  const ref = c.case_ref;
  if (!c.activation && !act.enabled) {
    return <div className="rf-split"><Panel><Empty icon="lock" title="Not ready for reconciliation yet" action={c.status === 'COMPLETED' ? null : <Button icon="arrowRight" onClick={() => nav('cases/' + ref + '/parser')}>Go to Smart Parser</Button>}>{(act.reason ? act.reason + '. ' : '') + 'Finish the Smart Parser step (mapping and checks) first.'}</Empty></Panel><SnapshotPanel c={c} app={app} /></div>;
  }
  return <div className="rf-split">
    <Panel title="Start reconciliation" sub="Runs the UC-042 reconciliation engine on this case's evidence">
      <div className="rf-stack rf-stack--3">
        <p style={{ margin: 0, fontSize: 13, lineHeight: '20px', color: 'var(--ink-secondary)' }}>All evidence checks have passed. Starting seals the evidence as a snapshot and runs the engine on it. When the run completes the case is Completed.</p>
        <div><div className="rf-label" style={{ marginBottom: 6 }}>Possible outcomes</div>
          <div className="rf-row rf-row--wrap"><Pill state="CLEAN" /><Pill state="EXCEPTIONS_OPEN" /><Pill state="EVIDENCE_INCOMPLETE" /></div></div>
        <div className="rf-help"><Icon name="info" size={12} /> Technical failures (the engine cannot complete a run) are not an outcome. They are shown separately with their error, the case stays In Progress and the run can be started again.</div>
        <div>{runButton}</div>
      </div>
    </Panel>
    <SnapshotPanel c={c} app={app} />
  </div>;
}

function RunView({ c, app, runId, isLatest, rec, runs, store, go, route, runButton, nav }) {
  const ref = c.case_ref;
  const key = 'recon:' + ref + ':' + runId;
  const live = isLatest && rec.state !== 'COMPLETED';  // running or failed: no stored results yet (contract §3.4)
  const q = useQuery(live ? null : key, (svc) => svc.getReconRun(runId));
  const [report, setReport] = React.useState(false);
  const job = runs.find((j) => j.run_id === runId) || {};
  if (live) q.data = { state: rec.state, run_id: runId, error: rec.error, snapshot_id: c.activation && c.activation.snapshot_id, started_at: job.started_at || job.created_at, finished_at: job.finished_at };
  if (!live && q.error) return <Notice tone="danger" title={'Run ' + runId + ' could not be loaded'} actions={<Button size="sm" icon="refresh" onClick={q.reload}>Try again</Button>}>{q.error.message}</Notice>;
  if (!q.data) return <Skeleton rows={5} />;
  const r = q.data;
  const runsPanel = <Panel title={'Reconciliation runs · ' + runs.length} sub="Every run is kept, including failed runs and their errors" flush><RunsList runs={runs} runId={runId} onSelect={(rid) => go(rid)} /></Panel>;

  if (r.state !== 'COMPLETED') {
    const failed = r.state === 'FAILED';
    const at = store.getQuery(key).at;
    return <div className="rf-split">
      <div className="rf-stack">
        <Panel title={'Reconciliation ' + r.run_id + (failed ? ' · failed' : ' · running')} sub={failed ? 'No results were stored for this run. The snapshot is unchanged.' : 'Status as reported by the adapter. No partial results are shown.'}
          actions={failed ? <Pill state="RUN_FAILED" /> : <><Pill state="RECON_RUNNING" />{at ? <span className="rf-stale"><span className="rf-live" />Updated {Math.max(0, Math.round((Date.now() - at) / 1000))} s ago</span> : null}</>}>
          <div className="rf-stack rf-stack--3">
            {failed && <Notice tone="danger" title="Run failed">{r.error || 'The backend reported the run as failed without an error message.'}</Notice>}
            <div>
              <div className="rfd-rstat"><span className="rf-tone-success"><Glyph name="success" /></span><b>Submitted</b><span>{fmtDateTime(r.started_at)}</span></div>
              <div className="rfd-rstat"><span className={r.accepted_at ? 'rf-tone-success' : 'rf-tone-neutral'}><Glyph name={r.accepted_at ? 'success' : 'pending'} /></span><b>Accepted by engine</b><span>{r.accepted_at ? fmtDateTime(r.accepted_at) : failed ? 'Not accepted' : 'Waiting for the adapter'}</span></div>
              <div className="rfd-rstat"><span className={failed ? 'rf-tone-danger' : 'rf-tone-progress'}><Glyph name={failed ? 'danger' : 'progress'} /></span><b>{failed ? 'Failed' : 'Running'}</b><span>{failed ? fmtDateTime(r.finished_at) : 'The engine is evaluating the controls'}</span></div>
            </div>
            <KV pairs={[['Run', <Ref id={r.run_id} copy />], ['Job', (runs.find((j) => j.run_id === r.run_id) || {}).job_id || (isLatest && rec.job_id) ? <span className="rf-mono">{(runs.find((j) => j.run_id === r.run_id) || {}).job_id || rec.job_id}</span> : '—'], ['Snapshot', r.snapshot_id ? <Ref id={r.snapshot_id} /> : '—']]} />
            {!failed && <Notice tone="info" compact>Defer Case does not interrupt this run. The page refreshes while the run is in progress.</Notice>}
            {failed && isLatest && runButton && <div>{runButton}</div>}
          </div>
        </Panel>
      </div>
      <aside className="rf-stack rf-stack--3"><SnapshotPanel c={c} app={app} />{runsPanel}</aside>
    </div>;
  }

  if (route.id) return <ExceptionWorkspace c={c} app={app} run={r} runId={runId} excId={route.id} go={go} nav={nav} />;
  const out = r.outcomes || {};
  const total = r.total_results != null ? r.total_results : OUTCOMES.reduce((a, o) => a + (out[o[0]] || 0), 0);
  const cs = CASE_STATUS[r.case_status];
  const earlierFailed = runs.filter((j) => j.run_id !== r.run_id && j.state === 'failed');
  return <>
    {cs ? <Outcome status={r.case_status} title={cs[0]} actions={<Button size="sm" icon="file" onClick={() => setReport(true)}>View engine report</Button>}>{cs[1]} Run-level outcome of {r.run_id}.</Outcome>
      : <Notice tone="info" title={'Run outcome: ' + (r.case_status || 'not reported')} actions={<Button size="sm" icon="file" onClick={() => setReport(true)}>View engine report</Button>} />}
    <div className="rfd-runline">
      <span>Run <b className="rf-mono">{r.run_id}</b></span><span>Snapshot <b className="rf-mono">{r.snapshot_id || '—'}</b></span>
      <span>Engine <b>UC-042 reconciliation via Smart Parser adapter</b></span><span>Started <b>{fmtDateTime(r.started_at)}</b></span><span>Completed <b>{fmtDateTime(r.finished_at)}</b></span>
      {earlierFailed.length > 0 && <span>Earlier failed run{earlierFailed.length > 1 ? 's' : ''} <b className="rf-mono">{earlierFailed.map((j) => j.run_id).join(', ')}</b></span>}
    </div>
    <IntegrityList checks={r.integrity_checks} />
    <ClosurePanel c={c} runId={runId} nav={nav} />
    <div className="rfd-section"><span className="rfd-section__title">Control results</span><span className="rfd-section__note">Control-level outcomes, one per control and account. Separate from the run-level outcome above.</span></div>
    <Stats items={[{ label: 'Control results', value: total }].concat(OUTCOMES.map((o) => ({ label: o[0], value: out[o[0]] || 0, glyph: o[2], tone: o[3] })), [{ label: 'Exceptions', value: r.exception_count != null ? r.exception_count : (r.exceptions || []).length }])} />
    <SegBar parts={OUTCOMES.map((o) => ({ key: o[1], label: o[0], value: out[o[0]] || 0 }))} />
    <ResultTabs c={c} r={r} runs={runs} runId={runId} route={route} go={go} />
    {report && <ReportDialog refKey={c.case_ref} runId={runId} onClose={() => setReport(false)} />}
  </>;
}

/* Closure for the run on screen: deterministic outcome summary (not AI) and the audit pack status. */
function ClosurePanel({ c, runId, nav }) {
  const q = useClosure(c);
  const cl = q.data;
  if (!cl) return q.error ? <ClosureError err={q.error} reload={q.reload} /> : null;
  if (cl.recon_run_id !== runId) return null;
  return <div className="rf-stack rf-stack--3">
    <DeterministicSummary s={cl.deterministic_summary} />
    <div className="rf-row rf-row--wrap" style={{ gap: 12 }}><PackStatusLine pack={cl.pack} /><span className="rf-spacer" />
      <Button size="sm" iconRight="arrowRight" onClick={() => nav('cases/' + c.case_ref + '/closing')}>Closing & Audit Pack</Button></div>
  </div>;
}

/* Exceptions grouped under their cause (owner, 24 Nov 2026): each engine investigation group becomes one block, the
   causing exception (duplicate entry / transaction against bank) first, then its linked exceptions; ungrouped
   exceptions stay as they are, in the engine's order. */
const CAUSE_RE = /^(DUPLICATE_|RC4-DIRECT)/;
function groupedRows(exc) {
  const out = [], done = new Set();
  exc.forEach((e) => {
    const gid = e.investigation_group_id;
    if (!gid) { out.push({ e }); return; }
    if (done.has(gid)) return;
    done.add(gid);
    const members = exc.filter((x) => x.investigation_group_id === gid);
    if (members.length < 2) { out.push({ e }); return; }
    const cause = members.find((x) => CAUSE_RE.test(String(x.root_cause || '')));
    const order = cause ? [cause].concat(members.filter((x) => x !== cause)) : members;
    out.push({ group: <span className="rf-row" style={{ gap: 6 }}><Icon name="layers" size={14} />{cause
      ? <>{plainTitle(String(cause.root_cause).split('|')[0])} ({cause.exception_id}) · causes {members.length - 1} linked exception{members.length - 1 === 1 ? '' : 's'}</>
      : <>{members.length} linked exceptions</>}</span> });
    order.forEach((x) => out.push({ e: x, inGroup: true, isCause: x === cause }));
  });
  return out;
}

function ResultTabs({ c, r, runs, runId, route, go }) {
  const exc = r.exceptions || [];
  const clq = useClosure(c);
  const cl = clq.data && clq.data.recon_run_id === runId ? clq.data : null;
  const byId = new Map(((cl && cl.exceptions) || []).map((x) => [x.exception_id, x]));
  const [tab, setTab] = React.useState(exc.length ? 'exceptions' : 'controls');
  return <div className="rf-stack rf-stack--3">
    <Tabs items={[['exceptions', 'Exceptions · ' + exc.length], ['controls', 'Control results · ' + (r.total_results != null ? r.total_results : '')], ['runs', 'Runs · ' + runs.length]]} active={tab} onChange={setTab} />
    {tab === 'exceptions' && <Panel flush>{exc.length ? <Table dense caption="Exceptions" columns={[{ key: 'id', label: 'Exception' }, { key: 'sev', label: 'Severity' }, { key: 'finding', label: 'Finding' }, { key: 'acct', label: 'Account' }, { key: 'period', label: 'Date or period' }, { key: 'amt', label: 'Amount', cls: 'is-num' }, { key: 'aff', label: 'Affected results', cls: 'is-num' }, { key: 'ai', label: 'AI investigation' }, { key: 'dec', label: 'Decision' }]}
      rows={groupedRows(exc).map((g) => g.group != null ? g : (({ e, inGroup, isCause }) => ({ key: e.exception_id, selected: route.id === e.exception_id, onClick: () => go(runId, e.exception_id), className: inGroup ? 'is-grouped' : undefined, cells: {
        id: <span className="rf-mono rf-strong">{inGroup ? <span className="rfx-indent" aria-hidden="true">{isCause ? '●' : '└'}</span> : null}{e.exception_id}</span>, sev: <EngineSeverity value={e.severity} />,
        finding: <><span className="rf-cell-main">{(/^[A-Z0-9_-]+$/.test(String(excTitle(e))) ? plainTitle(String(excTitle(e))) : excTitle(e))}</span>{e.root_cause && <span className="rf-cell-sub"><Enum>{e.root_cause}</Enum></span>}</>,
        acct: excAccount(e), period: excPeriod(e), amt: typeof e.amount === 'number' ? <Money amount={e.amount} ccy={e.currency} /> : e.amount, aff: e.affected_results,
        ai: cl ? <AiState state={(byId.get(e.exception_id) || {}).ai_state} /> : <span className="rf-muted" title={clq.error ? clq.error.message : 'Closure not loaded'}>—</span>,
        dec: cl ? <DecisionCell e={byId.get(e.exception_id)} /> : <span className="rf-muted">—</span> } }))(g))} />
      : <Empty icon="check" title="No exceptions">This run raised no exceptions.</Empty>}</Panel>}
    {tab === 'controls' && <ControlsPanel refKey={c.case_ref} runId={runId} outcomes={r.outcomes || {}} total={r.total_results} />}
    {tab === 'runs' && <Panel title={'Reconciliation runs · ' + runs.length} sub="Every run is kept, including failed runs and their errors" flush><RunsList runs={runs} runId={runId} onSelect={(rid) => go(rid)} /></Panel>}
  </div>;
}

function ControlsPanel({ refKey, runId, outcomes, total }) {
  const [outcome, setOutcome] = React.useState('');
  const [check, setCheck] = React.useState('');
  const all = useQuery('controls:' + refKey + ':' + runId + '::', (svc) => svc.getControls(runId, {}));
  const q = useQuery('controls:' + refKey + ':' + runId + ':' + outcome + ':' + check, (svc) => svc.getControls(runId, { outcome: outcome || undefined, check: check || undefined }));
  const checks = all.data && all.data.rows ? [...new Set(all.data.rows.map((x) => x.check_id))] : [];
  const sum = total != null ? total : OUTCOMES.reduce((a, o) => a + (outcomes[o[0]] || 0), 0);
  const d = q.data;
  return <Panel flush title="Control results" sub="check_id and note as returned by the engine "
    actions={<div className="rfd-filters">
      <Segmented items={[['', 'All ' + sum]].concat(OUTCOMES.map((o) => [o[0], o[0] + ' ' + (outcomes[o[0]] || 0)]))} active={outcome} onChange={setOutcome} />
      <select className="rfd-select" aria-label="Filter by control" value={check} onChange={(e) => setCheck(e.target.value)}><option value="">All controls</option>{checks.map((k) => <option key={k} value={k}>{k}</option>)}</select>
    </div>}>
    {q.error ? <div style={{ padding: 16 }}><Notice tone="danger" title="Control results could not be loaded" actions={<Button size="sm" onClick={q.reload}>Try again</Button>}>{q.error.message}</Notice></div>
      : !d ? <div style={{ padding: 16 }}><span className="rf-skel" style={{ width: '60%' }} /></div>
      : <>
        {d.truncated && <div style={{ padding: '12px 16px 0' }}><Notice tone="attention" compact>{'Showing the first ' + d.rows.length + ' of ' + d.total + ' results. Narrow the filter to see the rest.'}</Notice></div>}
        {d.rows.length ? <Table dense caption="Control results" maxHeight={520} columns={[{ key: 'check', label: 'Control', cls: 'is-tight' }, { key: 'control', label: 'Check' }, { key: 'acct', label: 'Account' }, { key: 'out', label: 'Outcome' }, { key: 'note', label: 'Note' }]}
          rows={d.rows.map((x, i) => ({ key: x.check_id + ':' + x.account + ':' + i, className: x.outcome === 'FAIL' ? 'is-flagged' : undefined, cells: { check: <span className="rf-mono rf-strong">{x.check_id}</span>, control: x.control, acct: x.account || x.scope, out: <Pill state={x.outcome} />, note: x.note } }))} />
          : <Empty icon="filter" title="No control results match">{'No results for ' + [outcome, check].filter(Boolean).join(' · ') + '.'}</Empty>}
      </>}
  </Panel>;
}

function ReportDialog({ refKey, runId, onClose }) {
  const q = useQuery('report:' + refKey + ':' + runId, (svc) => svc.getReport(runId));
  return <Layer><Dialog eyebrow="Engine report" title={'Reconciliation report · ' + runId} width={760} onClose={onClose} foot={<><span className="rf-spacer" /><Button onClick={onClose}>Close</Button></>}>
    {q.error ? <Notice tone="danger" title="The report could not be loaded" actions={<Button size="sm" onClick={q.reload}>Try again</Button>}>{q.error.message}</Notice>
      : q.data == null ? <span className="rf-skel" style={{ width: '70%' }} /> : <pre className="rfd-pre">{String(q.data)}</pre>}
  </Dialog></Layer>;
}
