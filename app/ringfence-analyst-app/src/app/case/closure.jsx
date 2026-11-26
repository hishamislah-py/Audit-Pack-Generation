/* Closure helpers shared by the Reconciliation tab, the exception workspace and the Closing & Audit Pack tab.
   Everything renders the backend's ClosureView as returned (impl_20261120 CONTRACT.md): state, blockers and
   actions ({enabled, reason}) come from the server; nothing here derives a lifecycle rule. */
import React from 'react';
import { useQuery, useStoreApi } from '../hooks.js';
import { Button, WithReason, Pill, Notice, KV, Icon } from '../../ui/index.jsx';
import { fmtDateTime } from '../format.js';

const RUNNING_AI = ['QUEUED', 'RUNNING'];
const RUNNING_STATES = ['PACK_PENDING', 'INVESTIGATING', 'GENERATING'];
export const closureKey = (ref) => 'closure:' + ref;

/* True while a closure job is running server-side (poll every store.POLL.closure ms). */
export function closureBusy(cl) {
  if (!cl) return false;
  if (RUNNING_STATES.includes(cl.state)) return true;
  if (cl.pack && cl.pack.status === 'PENDING') return true;
  return (cl.exceptions || []).some((e) => RUNNING_AI.includes(e.ai_state));
}

/* GET /api/cases/{ref}/closure, polled while a job runs (or while it is about to appear after reconciliation). */
export function useClosure(c, extraPoll) {
  const store = useStoreApi();
  const ref = c.case_ref;
  const cur = store.getQuery(closureKey(ref));
  const waiting = c.status === 'COMPLETED' && cur.error && cur.error.error === 'NO_CLOSURE';
  const poll = closureBusy(cur.data) || waiting || extraPoll ? store.POLL.closure : null;
  return useQuery(closureKey(ref), (svc) => svc.getClosure(ref), { poll, enabled: c.status === 'COMPLETED' || !!c.completed });
}

export const useAiConfig = () => useQuery('ai-config', (svc) => svc.getAiConfiguration());

/* Watches closure jobs with GET /api/jobs/{id} until they finish, then refreshes the case's closure queries. */
export function useJobWatch(ref) {
  const store = useStoreApi();
  const [jobs, setJobs] = React.useState([]);
  const alive = React.useRef(true);
  React.useEffect(() => () => { alive.current = false; }, []);
  React.useEffect(() => {
    if (!jobs.length) return undefined;
    const t = setInterval(() => {
      jobs.forEach((j) => {
        store.svc.getJob(j.id).then((x) => {
          const st = x && x.state;
          if (st === 'completed' || st === 'failed' || st === 'interrupted') {
            if (!alive.current) return;
            setJobs((cur) => cur.filter((y) => y.id !== j.id));
            if (st === 'completed') store.toast('success', j.label + ' finished');
            else store.toast('danger', j.label + ' ' + st + (x.error ? ': ' + x.error : ''));
            store.invalidate(ref);
          }
        }, () => { /* the closure poll keeps the view current */ });
      });
    }, store.POLL.closure);
    return () => clearInterval(t);
  }, [jobs, ref, store]);
  const watch = React.useCallback((id, label) => { if (id) setJobs((cur) => cur.concat([{ id, label }])); }, []);
  return { watch, running: jobs };
}

/* A backend action {enabled, reason} rendered as a button; disabled buttons show the backend's reason. */
export function ActBtn({ a, label, onClick, variant = 'secondary', size, icon, loading, extraReason, ...rest }) {
  const why = extraReason || (!a ? 'Not available.' : !a.enabled ? a.reason || 'Not available.' : null);
  const btn = <Button variant={variant} size={size} icon={icon} loading={loading} disabled={!!why} onClick={why ? undefined : onClick} {...rest}>{label}</Button>;
  return why ? <WithReason reason={why}>{btn}</WithReason> : btn;
}

export const AiState = ({ state }) => (state ? <Pill state={state} /> : <span className="rf-muted">—</span>);
export function DecisionCell({ e }) {
  if (e && !e.analyst_decision && e.review_state === 'PENDING_REVIEW') return <Pill state="V_PENDING" label="PENDING REVIEW" />;
  if (!e || !e.analyst_decision) return <span className="rf-muted">No decision</span>;
  return <span className="rf-stack rf-stack--2" style={{ gap: 2, alignItems: 'flex-start' }}><Pill state={e.analyst_decision} label={e.analyst_decision === 'ACCEPT' ? 'AI finding accepted' : 'AI finding rejected'} />{e.decided_by && <span className="rf-cell-sub">{e.decided_by} · {fmtDateTime(e.decided_at)}</span>}</span>;
}

/* "System-generated, not AI": the backend's deterministic outcome summary. */
/* Reconciliation statement (owner, 24 Nov 2026): what the checks found, in plain sentences, generated from the engine's
   stored results (smartparser/webapp/statement.py, the same builder as the PDF). Never AI. */
const ST_MARK = { PASS: ['check', 'is-pass'], FAIL: ['x', 'is-fail'], INCOMPLETE: ['alert', 'is-warn'] };
export function ReconStatement({ st, status }) {
  if (!st || !(st.lines || []).length) return null;
  return <section className={'rf-panel rfst rfst--' + String(st.state || '').toLowerCase()} aria-label="Reconciliation statement">
    <div className="rfst__head">
      <div className="rfst__kicker">Reconciliation statement <span className="rfe-badge rfe-badge--det"><Icon name="shield" size={12} />System-generated, not AI</span></div>
      {status && <Pill state={status} />}
    </div>
    <div className="rfst__headline"><Icon name={st.state === 'ALL_PASSED' ? 'check' : 'alert'} size={20} />{st.headline}</div>
    <p className="rfst__summary">{st.summary}</p>
    <ul className="rfst__lines">{st.lines.map((l) => { const m = ST_MARK[l.state] || ST_MARK.INCOMPLETE; return <li key={l.key} className={m[1]}>
      <span className="rfst__mark"><Icon name={m[0]} size={14} /></span><span className="rfst__area">{l.area}</span><span className="rfst__text">{l.text}</span></li>; })}</ul>
    <p className="rfst__note">{st.note}</p>
  </section>;
}

export function DeterministicSummary({ s }) {
  if (!s) return null;
  if (s.statement && (s.statement.lines || []).length) return <ReconStatement st={s.statement} status={s.case_status} />;
  const obj = (o) => (o && typeof o === 'object' ? Object.entries(o) : []);
  return <section className="rf-panel rfe-det" aria-label="Deterministic outcome summary">
    <header className="rf-panel__head"><div><h3 className="rf-panel__title">Outcome summary</h3><div className="rf-panel__sub"><span className="rfe-badge rfe-badge--det"><Icon name="shield" size={12} />{s.label || 'System-generated, not AI'}</span></div></div><span className="rf-spacer" />{s.case_status && <Pill state={s.case_status} />}</header>
    <div className="rf-panel__body rf-stack rf-stack--3">
      {(s.text || []).length > 0 && <ul className="rfe-list">{s.text.map((t, i) => <li key={i}>{t}</li>)}</ul>}
      {(obj(s.totals).length > 0 || obj(s.exceptions_by_severity).length > 0) && <div className="rfe-kvrow">
        {obj(s.totals).length > 0 && <div><div className="rf-label">Totals</div><KV pairs={obj(s.totals).map(([k, v]) => [k.replace(/_/g, ' '), scalarText(v)])} /></div>}
        {obj(s.exceptions_by_severity).length > 0 && <div><div className="rf-label">Exceptions by severity</div><KV pairs={obj(s.exceptions_by_severity).map(([k, v]) => [k, scalarText(v)])} /></div>}
      </div>}
    </div>
  </section>;
}

export function PackStatusLine({ pack }) {
  if (!pack) return null;
  if (pack.status === 'GENERATED') return <div className="rfe-packline is-ok"><Icon name="check" size={14} /><span>Audit pack: generated</span>{pack.pack_id && <span className="rf-mono rf-muted">{pack.pack_id}</span>}</div>;
  if (pack.status === 'UNAVAILABLE') return <div className="rfe-packline is-bad"><Icon name="alert" size={14} /><span>Audit pack unavailable: {pack.reason || 'no reason reported'}</span></div>;
  return <div className="rfe-packline"><Icon name="clock" size={14} /><span>Audit pack: {String(pack.status || 'pending').toLowerCase()}{pack.reason ? ' · ' + pack.reason : ''}</span></div>;
}

/* Closure errors: NO_CLOSURE (reconciliation not complete), NOT_AVAILABLE (mock), anything else. */
export function ClosureError({ err, reload }) {
  if (!err) return null;
  if (err.error === 'NO_CLOSURE') return <Notice tone="info" title="Closure not started yet">{err.message}</Notice>;
  if (err.error === 'NOT_AVAILABLE' || err.error === 'CLOSURE_DISABLED') return <Notice tone="attention" title="Closure is not available here">{err.message}</Notice>;
  return <Notice tone="danger" title="Closure could not be loaded" actions={reload ? <Button size="sm" icon="refresh" onClick={reload}>Try again</Button> : null}>{err.message}</Notice>;
}

export function scalarText(v) {
  if (v == null || v === '') return '—';
  if (typeof v !== 'object') return String(v);
  return JSON.stringify(v);
}
/* Free-form backend items (string or object) → readable text, without inventing fields. */
export function itemText(x) {
  if (x == null) return '';
  if (typeof x !== 'object') return String(x);
  return x.text || x.statement || x.hypothesis || x.claim || x.description || x.recommendation || x.what || x.step || x.action || x.question || x.message || x.title || JSON.stringify(x);
}
