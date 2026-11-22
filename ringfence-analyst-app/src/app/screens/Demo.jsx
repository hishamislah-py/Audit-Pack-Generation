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

export function DemoScenariosSection({ nav, focus }) {
  const q = useQuery('demo-scenarios', (svc) => svc.listDemoScenarios(), { focus: true });
  const [sel, setSel] = React.useState(null);
  const ref = React.useRef(null);
  React.useEffect(() => { if (focus && ref.current && ref.current.scrollIntoView) ref.current.scrollIntoView({ block: 'start' }); }, [focus, !!q.data]);
  const d = q.data;
  const list = (d && d.scenarios) || [];
  const chosen = list.find((s) => s.scenario_id === sel);
  return <section ref={ref} className="rf-panel as-demo" id="demo-scenarios" aria-label="Demo scenarios">
    <header className="rf-panel__head"><div><h3 className="rf-panel__title"><Icon name="flag" size={14} /> Demo scenarios</h3>
      <div className="rf-panel__sub">Synthetic evidence ZIPs. Load scenario registers a new Waiting case through the same registration as a manual upload; every result comes from the real Smart Parser and engine.</div></div>
      <span className="rf-spacer" /><Button size="sm" icon="refresh" onClick={() => q.reload()}>Refresh</Button></header>
    <div className="rf-panel__body rf-panel__body--flush">
      {q.error && <div style={{ padding: 16 }}><Notice tone={q.error.error === 'DEMO_DISABLED' ? 'attention' : 'danger'} compact title={q.error.error === 'DEMO_DISABLED' ? 'Demo scenarios are not enabled on this server' : 'Demo scenarios could not be loaded'}>{q.error.message}</Notice></div>}
      {!d && !q.error && <div style={{ padding: 16 }}><span className="rf-skel" style={{ width: '60%' }} /></div>}
      {d && (list.length ? <Table dense caption="Demo scenarios" columns={[{ key: 'cust', label: 'Customer', width: '200px' }, { key: 'per', label: 'Period', width: '120px' }, { key: 'desc', label: 'Scenario' }, { key: 'exp', label: 'Expected business outcome', width: '240px' }, { key: 'n', label: 'Loaded', cls: 'is-num' }, { key: 'go', label: <span className="rf-sr">Load</span>, cls: 'is-tight' }]}
        rows={list.map((s) => ({ key: s.scenario_id, selected: sel === s.scenario_id, onClick: () => setSel(sel === s.scenario_id ? null : s.scenario_id), cells: {
          cust: <span className="rf-cell-main">{s.customer_name}</span>,
          per: <span className="rf-nowrap">{fmtPeriod(s.reporting_period)}</span>,
          desc: <><span className="rf-cell-main">{s.title}</span><span className="rf-cell-sub" title={s.description}>{shortText(s.description)}</span></>,
          exp: <Expected e={s.expected} />,
          n: (s.cases || []).length || null,
          go: <LoadButton s={s} nav={nav} /> } }))} />
        : <div style={{ padding: 16 }} className="rf-help">The scenario folder contains no scenario.</div>)}
      {chosen && <div className="as-demo__detail"><div className="rf-label" style={{ marginBottom: 6 }}>{chosen.title} · cases loaded from this scenario</div>
        {chosen.demonstrates && <div className="rf-help" style={{ marginBottom: 8 }}>{chosen.demonstrates}</div>}
        <LoadedCases s={chosen} nav={nav} /></div>}
      {d && d.scenarios && d.scenarios[0] && d.scenarios[0].synthetic_notice && <div className="rf-help as-demo__note">{d.scenarios[0].synthetic_notice}</div>}
    </div>
  </section>;
}

export default DemoScenariosSection;
