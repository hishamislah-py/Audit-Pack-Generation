/* Demo scenarios: a separate section of the Work queue (enabled when the server runs with --demo-scenarios).
   GET  /api/demo/scenarios                              → the scenarios + the cases already loaded from each
   POST /api/demo/scenarios/{id}/load                    → registers a NEW case from the scenario's original ZIP through the
                                                            same registration API as a manual upload (one pipeline)
   GET  /api/demo/scenarios/{id}/verification?case_ref=  → actual backend results compared with the frozen answer key
   Nothing here computes or simulates an outcome: case status and results are the backend's. There is no separate
   Demo nav item; #/demo shows the queue with this section in view. */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, Notice, Table, Pill, Icon } from '../../ui/index.jsx';
import { fmtDateTime, fmtPeriod } from '../format.js';

/* The scenario's expected business outcome, as given by the scenario metadata (never computed here). */
function Expected({ e }) {
  e = e || {};
  if (e.case_status) {
    const bits = [['fail', 'FAIL'], ['insufficient_evidence', 'INSUFFICIENT_EVIDENCE'], ['exceptions', 'exception']]
      .filter(([k]) => typeof e[k] === 'number').map(([k, l]) => e[k] + ' ' + l + (k === 'exceptions' && e[k] !== 1 ? 's' : ''));
    return <span className="rf-stack rf-stack--2" style={{ gap: 2, alignItems: 'flex-start' }}><Pill state={e.case_status} />{bits.length > 0 && <span className="rf-cell-sub">{bits.join(' · ')}</span>}</span>;
  }
  if (e.smart_parser_run) return <span className="rf-stack rf-stack--2" style={{ gap: 2, alignItems: 'flex-start' }}><span className="rf-strong">Technical processing failure, then retry</span>
    <span className="rf-cell-sub">Smart Parser run {String(e.smart_parser_run).toLowerCase()}{e.retry_run ? ' · retry ' + String(e.retry_run).toLowerCase() : ''}{e.reconciliation ? ' · reconciliation ' + e.reconciliation : ''}</span></span>;
  const keys = Object.keys(e).filter((k) => e[k] != null && typeof e[k] !== 'object');
  return keys.length ? <span className="rf-cell-sub">{keys.map((k) => k.replace(/_/g, ' ') + ': ' + e[k]).join(' · ')}</span> : <span className="rf-muted">Not stated</span>;
}

function Verification({ sid, caseRef }) {
  const q = useQuery('demo-verify:' + sid + ':' + caseRef, (svc) => svc.getDemoVerification(sid, caseRef));
  const v = q.data;
  if (q.error) return <Notice tone="danger" compact title="Comparison could not be loaded">{q.error.message}</Notice>;
  if (!v) return <span className="rf-skel" style={{ width: '50%' }} />;
  if (v.status === 'PENDING') return <div className="rf-help">{v.detail}</div>;
  const tone = v.status === 'MATCH' ? 'success' : v.status === 'PARTIAL' ? 'attention' : 'danger';
  return <div className="rf-stack rf-stack--2" data-verification={v.status}>
    <Notice tone={tone} compact title={v.status === 'MATCH' ? 'Actual results match the frozen answer key' : v.status === 'PARTIAL' ? 'Partly verified · Retry from Beginning not run yet' : 'Actual results differ from the answer key'}>
      {v.checks.filter((c) => c.passed).length} of {v.checks.length} checks agree. The answer key is read only for this comparison; it never influences processing.</Notice>
    <Table dense caption="Comparison with the answer key" columns={[{ key: 'c', label: 'Check' }, { key: 'e', label: 'Expected' }, { key: 'a', label: 'Actual (backend)' }, { key: 'r', label: '', cls: 'is-tight' }]}
      rows={v.checks.map((c, i) => ({ key: i, cells: { c: c.check, e: <span className="rf-mono rf-small rf-wrap">{short(c.expected)}</span>, a: <span className="rf-mono rf-small rf-wrap">{short(c.actual)}</span>, r: <Pill state={c.passed ? 'PASS' : 'FAIL'} /> } }))} />
  </div>;
}
const short = (x) => { const s = typeof x === 'string' ? x : JSON.stringify(x); return s.length > 160 ? s.slice(0, 157) + '…' + (Array.isArray(x) ? ' (' + x.length + ' items)' : '') : s; };
const shortText = (t) => { const s = String(t || ''); const i = s.indexOf('. '); return i > 0 && i < 220 ? s.slice(0, i + 1) : s.length > 220 ? s.slice(0, 217) + '…' : s; };

function LoadButton({ s, nav }) {
  const m = useMutation();
  const load = async () => {
    const r = await m.run((svc) => svc.loadDemoScenario(s.scenario_id), { success: (c) => 'Scenario loaded · case ' + (c && c.case_ref) + ' registered · Waiting' });
    if (r && r.case_ref) nav('cases/' + r.case_ref + '/overview');
  };
  return <Button size="sm" variant="secondary" icon="play" loading={m.busy} disabled={!(s.zip && s.zip.present)} title={s.zip && s.zip.present ? undefined : 'The scenario ZIP is missing on the server'} aria-label={'Load scenario ' + s.scenario_id} data-scenario={s.scenario_id} onClick={(e) => { e.stopPropagation(); load(); }}>{m.busy ? 'Loading…' : 'Load scenario'}</Button>;
}

function LoadedCases({ s, nav }) {
  const [open, setOpen] = React.useState(null);
  if (!(s.cases || []).length) return <div className="rf-help">No case has been loaded from this scenario yet.</div>;
  return <div className="rf-stack rf-stack--2">
    <Table dense caption={'Cases from ' + s.scenario_id} columns={[{ key: 'ref', label: 'Case' }, { key: 'st', label: 'Status' }, { key: 'out', label: 'Backend outcome' }, { key: 'at', label: 'Registered' }, { key: 'go', label: '', cls: 'is-tight' }]}
      rows={s.cases.map((c) => ({ key: c.case_ref, selected: open === c.case_ref, cells: {
        ref: <span className="rf-mono rf-strong">{c.case_ref}</span>, st: <Pill state={c.status} />,
        out: c.case_status ? <Pill state={c.case_status} /> : (c.runs || []).length ? <span className="rf-small">{c.runs.map((r) => 'Run ' + r.run_no + ' ' + r.status).join(' · ')}</span> : <span className="rf-muted">Not started</span>,
        at: fmtDateTime(c.created_at),
        go: <span className="rf-row" style={{ gap: 4 }}><Button size="sm" onClick={() => setOpen(open === c.case_ref ? null : c.case_ref)}>{open === c.case_ref ? 'Hide comparison' : 'Compare with answer key'}</Button><Button size="sm" variant="quiet" iconRight="arrowRight" onClick={() => nav('cases/' + c.case_ref + '/overview')}>Open</Button></span> } }))} />
    {open && <Verification sid={s.scenario_id} caseRef={open} />}
  </div>;
}

/* "Waiting to start": submissions already on the server (server --demo-scenarios) that the analyst can start with one
   click. Start registers a case from the submission through the same registration as an upload, then starts it. */
function StartButton({ s, nav }) {
  const m = useMutation();
  const start = async () => {
    const r = await m.run((svc) => svc.loadDemoScenario(s.scenario_id), { success: (c) => 'Case ' + (c && c.case_ref) + ' created' });
    if (r && r.case_ref) nav('cases/' + r.case_ref + '/overview?action=start');
  };
  return <Button size="sm" variant="primary" icon="play" loading={m.busy} disabled={!(s.zip && s.zip.present)} title={s.zip && s.zip.present ? undefined : 'The submission file is missing on the server'}
    aria-label={'Start ' + s.customer_name} data-scenario={s.scenario_id} onClick={(e) => { e.stopPropagation(); start(); }}>{m.busy ? 'Starting…' : 'Start'}</Button>;
}

export function DemoScenariosSection({ nav, focus }) {
  const q = useQuery('demo-scenarios', (svc) => svc.listDemoScenarios(), { focus: true });
  const ref = React.useRef(null);
  React.useEffect(() => { if (focus && ref.current && ref.current.scrollIntoView) ref.current.scrollIntoView({ block: 'start' }); }, [focus, !!q.data]);
  const d = q.data;
  const list = (d && d.scenarios) || [];
  if (q.error && q.error.error === 'DEMO_DISABLED') return null;
  return <section ref={ref} className="rf-panel dash-panel" id="waiting-to-start" aria-label="Waiting to start">
    <header className="rf-panel__head"><div><h3 className="rf-panel__title">Waiting to start</h3>
      <div className="rf-panel__sub">Submissions received and ready for processing. Start runs Smart Parsing, reconciliation and the AI review.</div></div>
      <span className="rf-spacer" /><span className="dash-count">{list.length}</span></header>
    <div className="rf-panel__body rf-panel__body--flush">
      {q.error && <div style={{ padding: 16 }}><Notice tone="danger" compact title="Submissions could not be loaded">{q.error.message}</Notice></div>}
      {!d && !q.error && <div style={{ padding: 16 }}><span className="rf-skel" style={{ width: '60%' }} /></div>}
      {d && (list.length ? <Table caption="Waiting to start" columns={[{ key: 'cust', label: 'Customer', width: '260px' }, { key: 'per', label: 'Period', width: '140px' }, { key: 'desc', label: 'Submission' }, { key: 'last', label: 'Previous cases', width: '170px' }, { key: 'go', label: <span className="rf-sr">Start</span>, cls: 'is-tight' }]}
        rows={list.map((s) => { const prev = (s.cases || [])[0]; return { key: s.scenario_id, cells: {
          cust: <span className="rf-cell-main">{s.customer_name}</span>,
          per: <span className="rf-nowrap">{fmtPeriod(s.reporting_period)}</span>,
          desc: <><span className="rf-cell-main">{s.title}</span>{s.zip && s.zip.filename && <span className="rf-cell-sub rf-mono">{s.zip.filename}</span>}</>,
          last: prev ? <Button size="sm" variant="link" iconRight="arrowRight" onClick={(e) => { e.stopPropagation(); nav('cases/' + prev.case_ref + '/overview'); }}>{prev.case_ref}</Button> : <span className="rf-muted">None</span>,
          go: <StartButton s={s} nav={nav} /> } }; })} />
        : <div style={{ padding: 16 }} className="rf-help">No submission is waiting.</div>)}
    </div>
  </section>;
}

export default DemoScenariosSection;
