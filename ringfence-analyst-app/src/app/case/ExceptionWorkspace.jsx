/* Full-width exception workspace: cases/<ref>/recon/<run>/<exc> (replaces the 640px drawer).
   GET /api/cases/{ref}/closure/exceptions/{exc} (ExceptionWorkspace) in three sections:
   (A) deterministic facts, (B) the AI investigation (an interpretation, not a fact), (C) the analyst decision.
   No free-text input anywhere (O4): ACCEPT/REJECT carry fixed wording applied by the backend. A decision never
   changes the engine's exception status, which is shown separately. When closure is not available (no closure yet,
   mock service) section A falls back to the engine's read-only exception detail (GET /api/runs/{run}/exceptions/{id}). */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, Panel, KV, Notice, Table, Dialog, Pill, Enum, Ref, Hash, Money, Icon, Glyph, cx } from '../../ui/index.jsx';
import { fmtDateTime, catTitle, sevLevel } from '../format.js';
import { useClosure, useAiConfig, useJobWatch, ActBtn, AiState, ClosureError, scalarText, itemText } from './closure.jsx';

const ENGINE_KNOWN = ['exception_id', 'severity', 'root_cause', 'title', 'category', 'account', 'account_id', 'currency', 'amount', 'period', 'first_date', 'last_date', 'affected_results', 'status', 'engine_status', 'exception_status'];
const engineStatus = (e) => e.status || e.engine_status || e.exception_status || null;
/* ExceptionWorkspace.exception is {engine, pack, investigation_group}: the engine row wins (values exactly as written). */
const wsException = (ws) => { const x = (ws && ws.exception) || {}; return x.engine || x.pack ? Object.assign({}, x.pack || {}, x.engine || {}) : x; };
function Sev({ value }) { return <span className={'rf-sev rf-sev--' + sevLevel(value)} title={'Engine severity: ' + value}><span className="rf-sev__bars" aria-hidden="true"><i /><i /><i /></span>{value || '—'}</span>; }
function RowValues({ row }) {
  if (row == null) return null;
  if (typeof row !== 'object') return <span className="rfd-rowvals">{String(row)}</span>;
  const e = Object.entries(row);
  return e.length ? <span className="rfd-rowvals">{e.map(([k, v]) => <span key={k}><b>{k}</b>{scalarText(v)}</span>)}</span> : null;
}
const Sec = ({ tag, title, sub, tone, children, actions }) => <section className={cx('rfe-sec', tone && 'rfe-sec--' + tone)} aria-label={title}>
  <header className="rfe-sec__head"><span className="rfe-sec__tag">{tag}</span><div style={{ minWidth: 0, flex: 1 }}><h2 className="rfe-sec__title">{title}</h2>{sub && <div className="rfe-sec__sub">{sub}</div>}</div>{actions}</header>
  <div className="rfe-sec__body">{children}</div></section>;
const Sub = ({ title, children }) => <div className="rfe-sub"><h3 className="rfe-sub__title">{title}</h3>{children}</div>;

function ControlTable({ rows }) {
  if (!(rows || []).length) return <div className="rf-help">No control results reported for this exception.</div>;
  return <Table dense caption="Control results" columns={[{ key: 'check', label: 'Control', cls: 'is-tight' }, { key: 'control', label: 'Check' }, { key: 'acct', label: 'Account' }, { key: 'out', label: 'Outcome' }, { key: 'note', label: 'Note' }]}
    rows={rows.map((x, i) => { const cr = x.control_result || {}; return { key: i, cells: { check: <span className="rf-mono rf-strong">{x.check_id || cr.check_id || '—'}</span>, control: x.control || cr.control, acct: x.account || x.scope || cr.account, out: x.outcome || cr.outcome ? <Pill state={x.outcome || cr.outcome} /> : '—', note: x.note || cr.note || x.text } }; })} />;
}
function EvidenceList({ items, app, openFile }) {
  if (!(items || []).length) return <div className="rf-help">No supporting evidence rows reported.</div>;
  return <ul className="rfd-ev">{items.map((v, i) => <li key={i}>
    <div className="rf-row" style={{ justifyContent: 'space-between' }}><span className="rf-mono rf-strong">{v.reference || '—'}</span>{v.file_version_id && <Button size="sm" variant="link" iconRight="arrowRight" onClick={() => openFile(v.file_version_id)}>Open file</Button>}</div>
    <div className="rfd-ev__meta">{v.evidence_category && <span><Enum>{v.evidence_category}</Enum> {catTitle(app, v.evidence_category)}</span>}<span className="rf-strong">{v.original_filename || '—'}{v.version_number != null ? ' v' + v.version_number : ''}</span>{v.line != null && <span>line <b className="rf-mono">{v.line}</b></span>}</div>
    <div className="rfd-ev__meta">{v.file_version_id && <span className="rf-mono">{v.file_version_id}</span>}{v.source_sha256 && <Hash sha={v.source_sha256} />}</div>
    <RowValues row={v.row} />
  </li>)}</ul>;
}

/* (A) Deterministic facts. */
function Facts({ ws, eng, app, openFile, run, runId }) {
  const f = (ws && ws.facts) || {};
  const e = ws ? wsException(ws) : (eng && eng.exception) || {};
  const status = (ws && ws.summary && ws.summary.status) || engineStatus(e);
  const extra = Object.keys(e).filter((k) => !ENGINE_KNOWN.includes(k) && e[k] != null && typeof e[k] !== 'object');
  const ctrl = ws ? f.control_results : eng && eng.affected_control_results;
  const ev = ws ? f.supporting_evidence : eng && eng.evidence;
  return <Sec tag="A" title="Deterministic facts" sub="From the UC-042 engine and the uploaded evidence. Not AI." tone="det">
    <KV pairs={[['Engine status', status ? <span className="rf-row" style={{ gap: 6 }}><Enum>{status}</Enum><span className="rf-help">set by the engine; analyst decisions never change it</span></span> : <span className="rf-muted">Not reported</span>],
      ['Account', scalarText(e.account || e.account_id)], ['Currency', scalarText(e.currency)],
      ['Date or period', scalarText(e.period || (e.first_date ? (e.last_date && e.last_date !== e.first_date ? e.first_date + ' → ' + e.last_date : e.first_date) : null))],
      ['Amount', typeof e.amount === 'number' ? <Money amount={e.amount} ccy={e.currency} /> : scalarText(e.amount)],
      ['Affected results', scalarText(e.affected_results)], ['Reconciliation run', <span className="rf-mono">{runId}</span>], ['Snapshot', run && run.snapshot_id ? <Ref id={run.snapshot_id} /> : '—']]
      .concat(extra.map((k) => [k.replace(/_/g, ' '), scalarText(e[k])]))} />
    <Sub title={'Control results · ' + (ctrl || []).length}><ControlTable rows={ctrl} /></Sub>
    <Sub title={'Supporting evidence · ' + (ev || []).length}><EvidenceList items={ev} app={app} openFile={openFile} /></Sub>
    {ws && <Sub title={'Missing evidence · ' + (f.missing_evidence || []).length}>
      {(f.missing_evidence || []).length ? <ul className="rfe-cards">{f.missing_evidence.map((m, i) => <li key={i}>
        <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>{m.category && <Enum>{m.category}</Enum>}<span className="rf-strong">{m.what || catTitle(app, m.category)}</span></div>
        <div className="rfd-ev__meta">{m.account && <span>Account <b>{m.account}</b></span>}{m.date && <span>Date <b className="rf-mono">{m.date}</b></span>}</div>
        {m.why_required && <div className="rf-secondary rfe-small"><b>Why it is required:</b> {m.why_required}</div>}
      </li>)}</ul> : <div className="rf-help">No missing evidence for this exception.</div>}
    </Sub>}
    {ws && (f.impact || f.suggested_next_action) && <KV pairs={[['Impact', f.impact ? itemText(f.impact) : '—'], ['Suggested next action', f.suggested_next_action ? itemText(f.suggested_next_action) : '—']]} />}
    {!ws && eng && eng.note && <div className="rf-help">{eng.note}</div>}
    {ws && ws.exception && ws.exception.investigation_group && typeof ws.exception.investigation_group === 'object' && <KV pairs={[['Investigation group', <Enum>{ws.exception.investigation_group.group_id}</Enum>], ['Exceptions in group', scalarText(ws.exception.investigation_group.exception_ids)]]} />}
  </Sec>;
}

function Citation({ id, cit, openFile }) {
  if (!cit) return <span className="rfe-cite is-unresolved" title="This citation does not resolve to a source row">{id} · unresolved</span>;
  const label = (cit.original_filename || cit.reference || id) + (cit.line != null ? ' · line ' + cit.line : '');
  return cit.file_version_id
    ? <button type="button" className="rfe-cite" title={(cit.reference || id) + ' · ' + cit.file_version_id} onClick={() => openFile(cit.file_version_id)}><Icon name="file" size={12} />{label}</button>
    : <span className="rfe-cite" title={cit.reference || id}><Icon name="hash" size={12} />{label}</span>;
}

/* A list of evidence references (strings → citation chips that resolve like the findings; other items as text). */
function Cites({ ids, cites, openFile }) {
  const list = Array.isArray(ids) ? ids : ids != null && ids !== '' ? [ids] : [];
  if (!list.length) return <span className="rf-muted">None</span>;
  return <span className="rf-row rf-row--wrap" style={{ gap: 6 }}>{list.map((x, i) => typeof x === 'string'
    ? <Citation key={x + i} id={x} cit={cites[x]} openFile={openFile} /> : <span key={i} className="rfe-small">{itemText(x)}</span>)}</span>;
}

/* An AI hypothesis, field by field (never raw JSON). It is never established. */
function Hypothesis({ h, cites, openFile }) {
  if (!h || typeof h !== 'object') return <li><span className="rfe-hyp">Hypothesis – not established</span><div>{scalarText(h)}</div></li>;
  const main = h.possible_explanation || h.hypothesis || h.statement || h.text || h.description;
  const ev = h.supporting_evidence || h.evidence_ids;
  return <li>
    <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>{h.hypothesis_id && <span className="rf-mono rf-muted rfe-small">{h.hypothesis_id}</span>}<span className="rfe-hyp">HYPOTHESIS – NOT ESTABLISHED</span></div>
    {main && <div className="rf-strong">{main}</div>}
    {h.rationale && <div className="rfe-small"><b>Rationale:</b> {itemText(h.rationale)}</div>}
    {h.limitations && <div className="rfe-small rf-secondary"><b>Limitations:</b> {itemText(h.limitations)}</div>}
    <div className="rfe-small"><b>Supporting evidence:</b> <Cites ids={ev} cites={cites} openFile={openFile} /></div>
    <div className="rfe-small"><b>Contradictory evidence:</b> <Cites ids={h.contradictory_evidence} cites={cites} openFile={openFile} /></div>
  </li>;
}

/* A structured AI item (missing evidence, next step): its id, main text, labelled fields and references. */
function AiItem({ x, idKey, main, fields, refsKey, badge, cites, openFile }) {
  if (!x || typeof x !== 'object') return <li><div>{scalarText(x)}</div></li>;
  return <li>
    <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>{x[idKey] && <span className="rf-mono rf-muted rfe-small">{x[idKey]}</span>}{badge && <span className="rfe-hyp">{badge}</span>}<span className="rf-strong">{x[main] != null ? itemText(x[main]) : itemText(x)}</span></div>
    {fields.filter(([k]) => x[k] != null && x[k] !== '').map(([k, label]) => <div key={k} className="rfe-small"><b>{label}:</b> {itemText(x[k])}</div>)}
    {refsKey && (x[refsKey] || []).length > 0 && <div className="rfe-small"><b>Related:</b> <span className="rf-row rf-row--wrap" style={{ gap: 6 }}>{x[refsKey].map((id, i) => typeof id === 'string' && cites[id]
      ? <Citation key={id + i} id={id} cit={cites[id]} openFile={openFile} /> : <span key={i} className="rf-mono rfe-small">{scalarText(id)}</span>)}</span></div>}
  </li>;
}

/* (B) AI investigation: an interpretation, not a fact. */
function Investigation({ ws, row, cl, ai, openFile, onRetry }) {
  const inv = ws && ws.investigation;
  const state = (inv && inv.state) || (row && row.ai_state) || 'NOT_STARTED';
  const prov = (inv && inv.provider) || (cl && cl.ai && cl.ai.provider);
  const model = (inv && inv.model) || (cl && cl.ai && cl.ai.model);
  const cites = (inv && inv.citations) || {};
  const attempts = (inv && inv.attempts) || [];
  const retry = <ActBtn a={cl && cl.actions && cl.actions.retry_investigation} label={attempts.length || (row && row.attempts) ? 'Retry AI investigation' : 'Start AI investigation'} icon="refresh" size="sm" onClick={onRetry} />;
  const sub = <span className="rfe-badge rfe-badge--ai"><Icon name="sparkNone" size={12} />{[(inv && inv.label) || 'AI-generated', [prov, model].filter(Boolean).join(' ') || null, inv && inv.created_at ? fmtDateTime(inv.created_at) : null, 'an interpretation, not a fact'].filter(Boolean).join(' · ')}</span>;
  const published = !!(inv && inv.investigation_id && inv.conclusion !== undefined) || state === 'PUBLISHED';
  const last = attempts[attempts.length - 1];
  const lastWhy = last ? last.reason || last.error || null : null;
  return <Sec tag="B" title="AI investigation" sub={sub} tone="ai" actions={retry}>
    <div className="rf-row rf-row--wrap" style={{ gap: 8 }}><AiState state={state} />{inv && inv.investigation_id && <span className="rf-mono rf-muted rfe-small">{inv.investigation_id}</span>}
      {inv && inv.validation && <span className="rf-row" style={{ gap: 4 }}><span className="rfe-small rf-muted">Validation</span><Pill state={inv.validation.status} /></span>}</div>
    {state === 'UNAVAILABLE' && <Notice tone="attention" compact title="AI is not available on this server">{(cl && cl.ai && cl.ai.problem) || (ai && ai.problem) || 'No AI provider is configured.'} Nothing is simulated.</Notice>}
    {(state === 'QUEUED' || state === 'RUNNING') && <Notice tone="info" compact title={state === 'QUEUED' ? 'Queued' : 'Running'}>The investigation runs on the server, one at a time. This page refreshes while it runs.</Notice>}
    {(state === 'NOT_PUBLISHED' || state === 'FAILED') && lastWhy && <Notice tone={state === 'FAILED' ? 'danger' : 'attention'} compact title={state === 'FAILED' ? 'Investigation failed' : 'Not published'}>{lastWhy}</Notice>}
    {inv && published && <>
      <KV pairs={[['Conclusion', inv.conclusion ? itemText(inv.conclusion) : '—'], ['Sufficiency', inv.sufficiency ? <Enum>{itemText(inv.sufficiency)}</Enum> : '—']]} />
      <Sub title={'Confirmed findings · ' + (inv.confirmed_findings || []).length}>
        {(inv.confirmed_findings || []).length ? <ul className="rfe-cards">{inv.confirmed_findings.map((x, i) => <li key={x.id || i}>
          <div className="rf-row" style={{ gap: 8 }}>{x.id && <span className="rf-mono rf-muted rfe-small">{x.id}</span>}<span className="rf-strong">{x.title || x.claim}</span></div>
          {x.title && x.claim && <div>{x.claim}</div>}
          {x.explanation && <div className="rfe-small rf-secondary">{itemText(x.explanation)}</div>}
          {x.establishes && <div className="rfe-small"><b>Establishes:</b> {itemText(x.establishes)}</div>}
          {x.does_not_establish && <div className="rfe-small rf-secondary"><b>Does not establish:</b> {itemText(x.does_not_establish)}</div>}
          {(x.evidence_ids || []).length > 0 && <div className="rf-row rf-row--wrap" style={{ gap: 6 }}>{x.evidence_ids.map((id) => <Citation key={id} id={id} cit={cites[id]} openFile={openFile} />)}</div>}
        </li>)}</ul> : <div className="rf-help">No confirmed findings.</div>}
      </Sub>
      {(inv.hypotheses || []).length > 0 && <Sub title={'Hypotheses · ' + inv.hypotheses.length}>
        <ul className="rfe-cards rfe-cards--hyp">{inv.hypotheses.map((h, i) => <Hypothesis key={(h && h.hypothesis_id) || i} h={h} cites={cites} openFile={openFile} />)}</ul></Sub>}
      {(inv.missing_evidence || []).length > 0 && <Sub title={'Missing evidence (AI view) · ' + inv.missing_evidence.length}><ul className="rfe-cards">{inv.missing_evidence.map((m, i) => <AiItem key={i} x={m} idKey="item_id" main="description"
        fields={[['expected_source', 'Expected source'], ['impact', 'Impact']]} refsKey="related_ids" cites={cites} openFile={openFile} />)}</ul></Sub>}
      {(inv.open_questions || []).length > 0 && <Sub title="Open questions (AI view)"><ul className="rfe-list">{inv.open_questions.map((m, i) => <li key={i}>{itemText(m)}</li>)}</ul></Sub>}
      {(inv.next_steps || []).length > 0 && <Sub title={'Suggested next steps (AI view) · ' + inv.next_steps.length}><ul className="rfe-cards">{inv.next_steps.map((m, i) => <AiItem key={i} x={m} idKey="step_id" main="action" badge="Suggested · not done"
        fields={[['evidence_needed', 'Evidence needed'], ['rationale', 'Rationale']]} cites={cites} openFile={openFile} />)}</ul></Sub>}
    </>}
    {inv && inv.validation && (inv.validation.problems || []).length > 0 && <Notice tone="attention" compact title="Deterministic validation problems"><ul className="rfe-list">{inv.validation.problems.map((p, i) => <li key={i}>{itemText(p)}</li>)}</ul></Notice>}
    <Sub title={'Attempts · ' + attempts.length}>
      {attempts.length ? <Table dense caption="Investigation attempts" columns={[{ key: 'id', label: 'Attempt' }, { key: 'st', label: 'State' }, { key: 'at', label: 'Started' }, { key: 'why', label: 'Reason' }]}
        rows={attempts.map((a, i) => ({ key: a.job_id || i, cells: { id: <span className="rf-mono rfe-small">{'#' + (a.attempt || i + 1)} {a.investigation_id || a.job_id}{a.retry_of ? <span className="rf-cell-sub">retry of {a.retry_of}</span> : null}</span>, st: <Pill state={a.outcome || String(a.state || '').toUpperCase()} />, at: fmtDateTime(a.created_at || a.started_at), why: a.reason || a.error || null } }))} />
        : <div className="rf-help">No attempt recorded.</div>}
    </Sub>
  </Sec>;
}

/* (C) Analyst decision on the AI finding. ACCEPT/REJECT only; fixed wording; no free text. */
function Decision({ ws, row, cl, onDecide, history }) {
  const d = (ws && ws.decision) || {};
  const a = d.actions || {};
  const cur = d.current;
  const inv = ws && ws.investigation;
  const missing = row && row.missing_evidence;
  const status = ws ? (ws.summary && ws.summary.status) || engineStatus(wsException(ws)) : null;
  const hist = d.history || [];
  return <Sec tag="C" title="Analyst decision" sub="On the AI finding only. Fixed wording; no free-text reason is captured (O4)." tone="dec">
    {cur ? <div className="rfe-current"><Pill state={cur.decision} size="lg" label={cur.decision === 'ACCEPT' ? 'AI finding accepted' : 'AI finding rejected'} />
      <span className="rfe-small rf-secondary">{cur.decided_by} · {fmtDateTime(cur.decided_at)} · revision {cur.revision}</span>{cur.analyst_review_id && <span className="rf-mono rf-muted rfe-small">{cur.analyst_review_id}</span>}</div>
      : <div className="rf-help">No decision recorded{inv && inv.state === 'PUBLISHED' ? ' yet. A decision is required before closing.' : '. A decision is possible once an AI finding is published.'}</div>}
    <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>
      <ActBtn a={a.accept} label="Accept AI finding" variant="primary" icon="check" onClick={() => onDecide('ACCEPT', inv && inv.investigation_id)} extraReason={inv && inv.investigation_id ? null : a.accept && a.accept.enabled ? 'No published AI finding.' : null} />
      <ActBtn a={a.reject} label="Reject AI finding" variant="danger" icon="x" onClick={() => onDecide('REJECT', inv && inv.investigation_id)} extraReason={inv && inv.investigation_id ? null : a.reject && a.reject.enabled ? 'No published AI finding.' : null} />
    </div>
    {missing && <Notice tone="info" compact title="Missing-evidence exception">There is no “accept evidence” action. Missing evidence is resolved only by the evidence itself; a decision here applies to the AI finding, not to the evidence.</Notice>}
    <div className="rf-help"><Icon name="lock" size={12} /> Decisions never change the engine exception status{status ? <> (still <Enum>{status}</Enum>)</> : null}.</div>
    <Sub title={'Decision history · ' + hist.length}>
      {hist.length ? <Table dense caption="Decision history" columns={[{ key: 'd', label: 'Decision' }, { key: 'by', label: 'Actor' }, { key: 'at', label: 'Time' }, { key: 'rev', label: 'Revision', cls: 'is-num' }]}
        rows={hist.map((h, i) => ({ key: i, cells: { d: <Pill state={h.decision} />, by: h.decided_by || h.actor, at: fmtDateTime(h.decided_at || h.at), rev: h.revision } }))} />
        : <div className="rf-help">No decisions yet.</div>}
    </Sub>
    {history && <Sub title="Exception history">
      {history.error ? <div className="rf-help">{history.error.message}</div> : !history.data ? <span className="rf-skel" style={{ width: '60%' }} />
        : (history.data.events || []).length ? <ol className="rfe-events">{history.data.events.map((ev, i) => <li key={i}><span className="rf-mono rf-muted rfe-small">{fmtDateTime(ev.at || ev.created_at)}</span><Enum>{ev.event_type || ev.kind || ev.type}</Enum><span className="rfe-small">{ev.actor || ev.actor_id || ''}</span>{ev.details && (ev.details.reason || ev.details.rejection_reason || ev.details.decision) && <span className="rfe-small rf-secondary">{itemText(ev.details.decision || ev.details.reason || ev.details.rejection_reason)}</span>}</li>)}</ol>
          : <div className="rf-help">No events yet.</div>}
    </Sub>}
  </Sec>;
}

export default function ExceptionWorkspace({ c, app, run, runId, excId, go, nav }) {
  const ref = c.case_ref;
  const clq = useClosure(c);
  const cl = clq.data;
  const forRun = cl && cl.recon_run_id === runId;
  const row = forRun ? (cl.exceptions || []).find((x) => x.exception_id === excId) : null;
  const busy = row && (row.ai_state === 'QUEUED' || row.ai_state === 'RUNNING');
  const wsq = useQuery(forRun ? 'cexc:' + ref + ':' + excId : null, (svc) => svc.getClosureException(ref, excId), { poll: busy ? 4000 : null });
  const histq = useQuery(forRun ? 'cexch:' + ref + ':' + excId : null, (svc) => svc.getExceptionHistory(ref, excId));
  const useEngine = !forRun || !!wsq.error;
  const engq = useQuery(useEngine ? 'exc:' + ref + ':' + runId + ':' + excId : null, (svc) => svc.getException(runId, excId));
  const ai = useAiConfig();
  const jobs = useJobWatch(ref);
  const m = useMutation();
  const [dlg, setDlg] = React.useState(null);
  const ws = forRun && !wsq.error ? wsq.data : null;

  const list = (run.exceptions || []).map((e) => e.exception_id);
  const idx = list.indexOf(excId);
  const openFile = (fv) => nav('cases/' + ref + '/evidence/' + encodeURIComponent(fv));
  React.useEffect(() => { const f = (e) => { if (e.key === 'Escape' && !dlg) go(runId); }; window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f); });

  const confirm = async () => {
    const rev = cl ? cl.revision : ws && ws.revision;
    if (dlg.kind === 'retry') {
      const r = await m.run((svc) => svc.startInvestigation(ref, excId, { expected_revision: rev }), { inline: true, success: 'AI investigation queued' });
      if (r) { jobs.watch(r.job_id, 'AI investigation for ' + excId); setDlg(null); }
    } else {
      const r = await m.run((svc) => svc.decideInvestigation(ref, dlg.inv, { decision: dlg.kind, expected_revision: rev }), { inline: true, success: dlg.kind === 'ACCEPT' ? 'AI finding accepted' : 'AI finding rejected' });
      if (r) setDlg(null);
    }
  };
  const e = (ws && wsException(ws)) || (engq.data && engq.data.exception) || (run.exceptions || []).find((x) => x.exception_id === excId) || {};

  return <div className="rfe-ws">
    <div className="rfe-ws__nav">
      <Button size="sm" variant="quiet" icon="arrowLeft" onClick={() => go(runId)}>Back to exceptions</Button>
      <span className="rf-spacer" />
      <span className="rfd-dhead__pos">Finding {idx > -1 ? idx + 1 : '?'} of {list.length}</span>
      <Button size="sm" variant="quiet" icon="chevronLeft" disabled={idx < 1} aria-label="Previous finding" onClick={() => go(runId, list[idx - 1])} />
      <Button size="sm" variant="quiet" icon="chevronRight" disabled={idx < 0 || idx >= list.length - 1} aria-label="Next finding" onClick={() => go(runId, list[idx + 1])} />
    </div>
    <header className="rfe-ws__head">
      <h2 className="rfd-dtitle">{e.title || e.category || e.root_cause || excId}</h2>
      <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>{e.severity && <Sev value={e.severity} />}{e.root_cause && <Enum>{e.root_cause}</Enum>}<Ref id={excId} copy />{row && <AiState state={row.ai_state} />}{row && row.analyst_decision && <Pill state={row.analyst_decision} label={row.analyst_decision === 'ACCEPT' ? 'AI finding accepted' : 'AI finding rejected'} />}</div>
    </header>
    {cl && !forRun && <Notice tone="info" compact>Closure belongs to run <span className="rf-mono">{cl.recon_run_id}</span>. This earlier run shows the engine facts only.</Notice>}
    {!cl && clq.error && <ClosureError err={clq.error} reload={clq.reload} />}
    {forRun && wsq.error && <Notice tone="danger" compact title="Exception workspace could not be loaded" actions={<Button size="sm" onClick={wsq.reload}>Try again</Button>}>{wsq.error.message} The engine facts are shown instead.</Notice>}
    {cl && cl.frozen && <Notice tone="locked" compact title="Closure frozen">The final pack has been generated. Decisions and investigations are read-only.</Notice>}
    {(forRun && !ws && !wsq.error) || (useEngine && !engq.data && !engq.error) ? <div className="rf-panel" style={{ padding: 16 }}><span className="rf-skel" style={{ width: '80%' }} /><span className="rf-skel" style={{ width: '60%', marginTop: 10 }} /></div>
      : <div className={cx('rfe-cols', ws ? 'rfe-cols--3' : 'rfe-cols--1')}>
        <Facts ws={ws} eng={useEngine ? engq.data : null} app={app} openFile={openFile} run={run} runId={runId} />
        {useEngine && engq.error && <Notice tone="danger" title="Exception could not be loaded">{engq.error.message}</Notice>}
        {ws && <Investigation ws={ws} row={row} cl={cl} ai={ai.data} openFile={openFile} onRetry={() => { m.reset(); setDlg({ kind: 'retry' }); }} />}
        {ws && <Decision ws={ws} row={row} cl={cl} history={histq} onDecide={(kind, inv) => { m.reset(); setDlg({ kind, inv }); }} />}
      </div>}
    {ws && ws.note && <div className="rf-help">{ws.note}</div>}
    {dlg && <div className="rfd-layer"><Dialog eyebrow={excId + ' · ' + ref} error={m.error} onClose={m.busy ? undefined : () => setDlg(null)}
      title={dlg.kind === 'retry' ? 'Run the AI investigation again?' : dlg.kind === 'ACCEPT' ? 'Accept the AI finding?' : 'Reject the AI finding?'}
      foot={<><Button onClick={() => setDlg(null)} disabled={m.busy}>Cancel</Button><Button variant={dlg.kind === 'REJECT' ? 'danger' : 'primary'} loading={m.busy} onClick={confirm}>{dlg.kind === 'retry' ? 'Start investigation' : dlg.kind === 'ACCEPT' ? 'Accept AI finding' : 'Reject AI finding'}</Button></>}>
      {dlg.kind === 'retry' ? <div className="rf-stack rf-stack--3">
        <KV pairs={[['Provider', (ai.data && ai.data.provider) || (cl && cl.ai && cl.ai.provider) || '—'], ['Model', (ai.data && ai.data.model) || (cl && cl.ai && cl.ai.model) || '—']]} />
        {ai.data && ai.data.data_notice && <Notice tone="info" compact title="Data notice">{ai.data.data_notice}</Notice>}
        <div className="rf-help">A new attempt never overwrites an earlier one; earlier attempts stay in the list.</div></div>
        : <div className="rf-stack rf-stack--3">
          <div className="rf-help">{dlg.kind === 'ACCEPT' ? 'Records that you accept the published AI finding. No comment is captured.' : 'Records that you reject the published AI finding with fixed wording. No free-text reason is captured (O4).'}</div>
          {dlg.kind === 'REJECT' && ws && ws.decision && ws.decision.rejection_wording && <Notice tone="info" compact title="Recorded wording">{ws.decision.rejection_wording}</Notice>}
          <div className="rf-help"><Icon name="lock" size={12} /> The engine exception status does not change.</div></div>}
    </Dialog></div>}
  </div>;
}
