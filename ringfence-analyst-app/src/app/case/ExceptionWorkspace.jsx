/* Full-width exception workspace: cases/<ref>/recon/<run>/<exc> (replaces the 640px drawer).
   GET /api/cases/{ref}/closure/exceptions/{exc} (ExceptionWorkspace) in three sections:
   (A) deterministic facts, (B) the AI investigation (an interpretation, not a fact), (C) the analyst decision.
   ACCEPT/REJECT take an OPTIONAL explanation in the analyst's own words (23 Nov 2026 owner requirement; it supersedes
   O4 for this decision only): stored verbatim as the REJECT reason (else the backend's fixed wording) or the ACCEPT
   comment, and reported in the final audit pack. A published AI finding without a decision is PENDING REVIEW. A decision never
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

/* Plain-English headline of an investigation: the summary's first sentence, large; the rest below; the evidence
   assessment as words. 23 Nov 2026 demo feedback ("say what it looks like first, then the evidence"). */
const SUFFICIENCY = {
  EVIDENCE_SUFFICIENT: ['good', 'The evidence is enough to show what happened'],
  PARTIALLY_SUFFICIENT: ['attention', 'The evidence shows part of the picture'],
  INSUFFICIENT_EVIDENCE: ['danger', 'Important evidence is missing'],
  CONFLICTING_EVIDENCE: ['danger', 'The records contradict each other'],
};
function Headline({ text, sufficiency, eyebrow = 'What this looks like (AI reading)', bare = false }) {
  const t = String(text || '').trim();
  const m = t.match(/^(.+?[.!?])(\s+|$)([\s\S]*)$/);
  const head = m ? m[1] : t, rest = m ? m[3].trim() : '';
  const [tone, words] = SUFFICIENCY[sufficiency] || [null, sufficiency];
  return <div className={cx('rfe-headline', bare && 'rfe-headline--bare')}>
    {eyebrow && <div className="rfe-headline__eyebrow">{eyebrow}</div>}
    <div className="rfe-headline__text">{head || '—'}</div>
    {rest && <div className="rfe-headline__rest">{rest}</div>}
    {words && <div className={'rfe-headline__suff' + (tone ? ' is-' + tone : '')}>{words}</div>}
  </div>;
}

/* (B) AI investigation: an interpretation, not a fact. */
function Investigation({ ws, row, cl, ai, openFile, onRetry, hideHeadline = false }) {
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
    {(state === 'QUEUED' || state === 'RUNNING') && <Notice tone="info" compact title={state === 'QUEUED' ? 'Queued' : 'Running'}>Every exception is investigated at the same time on the server. This page refreshes while it runs.</Notice>}
    {(state === 'NOT_PUBLISHED' || state === 'FAILED') && lastWhy && <Notice tone={state === 'FAILED' ? 'danger' : 'attention'} compact title={state === 'FAILED' ? 'Investigation failed' : 'Not published'}>{lastWhy}</Notice>}
    {inv && published && <>
      {!hideHeadline && <Headline text={inv.conclusion ? itemText(inv.conclusion) : ''} sufficiency={inv.sufficiency ? itemText(inv.sufficiency) : null} />}
      <Sub title={'What the evidence shows · ' + (inv.confirmed_findings || []).length}>
        {(inv.confirmed_findings || []).length ? <ul className="rfe-cards">{inv.confirmed_findings.map((x, i) => <li key={x.id || i}>
          <div className="rf-row" style={{ gap: 8 }}><span className="rfe-fnum">{i + 1}</span><span className="rf-strong rfe-find-title">{x.title || x.claim}</span></div>
          {x.title && x.claim && <div className="rfe-find-claim">{x.claim}</div>}
          {(x.evidence_ids || []).length > 0 && <div className="rf-row rf-row--wrap" style={{ gap: 6 }}><span className="rfe-small rf-muted">Evidence</span>{x.evidence_ids.map((id) => <Citation key={id} id={id} cit={cites[id]} openFile={openFile} />)}</div>}
          {(x.explanation || x.establishes || x.does_not_establish) && <details className="rfe-more"><summary>How the AI reached this, and what it does not prove</summary>
            {x.explanation && <div className="rfe-small rf-secondary">{itemText(x.explanation)}</div>}
            {x.establishes && <div className="rfe-small"><b>Proves:</b> {itemText(x.establishes)}</div>}
            {x.does_not_establish && <div className="rfe-small rf-secondary"><b>Does not prove:</b> {itemText(x.does_not_establish)}</div>}
            {x.id && <div className="rf-mono rf-muted rfe-small">{x.id}</div>}
          </details>}
        </li>)}</ul> : <div className="rf-help">No confirmed findings.</div>}
      </Sub>
      {(inv.hypotheses || []).length > 0 && <Sub title={'Possible explanations (not proven) · ' + inv.hypotheses.length}>
        <ul className="rfe-cards rfe-cards--hyp">{inv.hypotheses.map((h, i) => <Hypothesis key={(h && h.hypothesis_id) || i} h={h} cites={cites} openFile={openFile} />)}</ul></Sub>}
      {(inv.missing_evidence || []).length > 0 && <Sub title={'Missing evidence (AI view) · ' + inv.missing_evidence.length}><ul className="rfe-cards">{inv.missing_evidence.map((m, i) => <AiItem key={i} x={m} idKey="item_id" main="description"
        fields={[['expected_source', 'Expected source'], ['impact', 'Impact']]} refsKey="related_ids" cites={cites} openFile={openFile} />)}</ul></Sub>}
      {(inv.open_questions || []).length > 0 && <Sub title="Open questions (AI view)"><ul className="rfe-list">{inv.open_questions.map((m, i) => <li key={i}>{itemText(m)}</li>)}</ul></Sub>}
      {(inv.next_steps || []).length > 0 && <Sub title={'Suggested next steps (AI view) · ' + inv.next_steps.length}><ul className="rfe-cards">{inv.next_steps.map((m, i) => <AiItem key={i} x={m} idKey="step_id" main="action" badge="Suggested · not done"
        fields={[['evidence_needed', 'Evidence needed'], ['rationale', 'Rationale']]} cites={cites} openFile={openFile} />)}</ul></Sub>}
    </>}
    {inv && inv.validation && (inv.validation.problems || []).length > 0 && <Notice tone="attention" compact title="Deterministic validation problems"><ul className="rfe-list">{inv.validation.problems.map((p, i) => <li key={i}>{itemText(p)}</li>)}</ul></Notice>}
    <details className="rfe-more"><summary>{'Technical details · attempts · ' + attempts.length}</summary>
      {attempts.length ? <Table dense caption="Investigation attempts" columns={[{ key: 'id', label: 'Attempt' }, { key: 'st', label: 'State' }, { key: 'at', label: 'Started' }, { key: 'why', label: 'Reason' }]}
        rows={attempts.map((a, i) => ({ key: a.job_id || i, cells: { id: <span className="rf-mono rfe-small">{'#' + (a.attempt || i + 1)} {a.investigation_id || a.job_id}{a.retry_of ? <span className="rf-cell-sub">retry of {a.retry_of}</span> : null}</span>, st: <Pill state={a.outcome || String(a.state || '').toUpperCase()} />, at: fmtDateTime(a.created_at || a.started_at), why: a.reason || a.error || null } }))} />
        : <div className="rf-help">No attempt recorded.</div>}
    </details>
  </Sec>;
}

/* ===================================================================================== single-page exception view
   23 Nov 2026 owner redesign: one page instead of three columns. (1) a plain title with the difference, (2) "What
   happened": the AI summary in 1-2 sentences, (3) a small supporting-evidence table built ONLY from engine data
   (control result reported/expected values, the engine's structured comparison values, the cited source rows), (4) one
   Accept / Reject bar, (5) everything else folded: engine details, the AI's reasoning, history. Nothing is removed. */
const CHECK_TITLE = {
  'C06-DIFFERENCE': 'The safeguarding reconciliation shows a difference',
  'C08-DIFFERENCE': 'The bank and the cash book do not agree',
  'BANK_LEDGER_DIFFERENCE': 'The bank and the cash book do not agree',
  'C07-BANK-EVIDENCE': 'Bank evidence is missing for the day',
  'C11-BATCH-ARITH': 'The settlement batch does not add up',
  'C11-BATCH-BANK': 'The settlement batch does not match the bank',
  'CBAL-ROLLFWD': 'A client balance does not roll forward',
  'RC4-DIRECT': 'A client transaction does not match the bank',
  'CASH-BANK-LINK': 'A cash-book entry has no matching bank entry',
  'BANK-CASH-LINK': 'A bank entry has no matching cash-book entry',
  'FUND-TOPUP': 'A safeguarding top-up cannot be confirmed',
  'DQ22-CONTINUITY': 'A bank statement does not continue from the previous day',
  'C14-COVER': 'Required evidence does not cover the day',
  'DUPLICATE_CASHBOOK_ENTRY': 'The same cash-book entry is recorded twice',
  'MISSING_BANK_EVIDENCE': 'Bank evidence is missing',
  'C04-REQUIREMENT': 'The safeguarding requirement does not agree',
  'C05-RESOURCE': 'The safeguarding resource does not agree',
  'RC2-LEDGER': "The firm's ledger balance does not agree with the cash book",
  'INTERNAL_DIFFERENCE': 'The safeguarding reconciliation shows a difference',
  'C11-TXN-LINE': 'A settlement line does not match its transaction',
  'C11-BANK-ENTRY': 'A settlement bank entry does not match',
  'CBAL-NONNEG': 'A client balance is negative',
  'BC-VS-EOD': 'The bank confirmation and statement differ',
  'DQ23-STATEMENT': 'A bank statement is incomplete',
  'C09-ALLOCATION': 'An unallocated receipt is outstanding',
  'C12-REFUND': 'A refund does not reconcile',
};
const plainTitle = (code) => CHECK_TITLE[code] || (code ? String(code).replace(/[_|-]+/g, ' ').toLowerCase().replace(/^./, (ch) => ch.toUpperCase()) : 'Exception');
const ID_KEYS = ['line_id', 'batch_id', 'txn_id', 'bank_entry_id', 'ledger_entry_id', 'entry_id', 'snapshot_id', 'recon_run_id', 'statement_id', 'confirmation_id', 'break_id', 'receipt_id'];
const DATE_KEYS = ['recon_date', 'cycle_date', 'posting_date', 'booking_date', 'value_date', 'clearing_date', 'settlement_date', 'entry_date', 'statement_date', 'as_at_ts', 'executed_ts', 'booking_ts'];
const AMT_KEYS = ['net_amount_reported', 'amount', 'balance', 'requirement_reported', 'closing_balance', 'gross_amount'];
const num = (v) => { if (v == null || v === '') return null; const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/,/g, '')); return Number.isFinite(n) ? n : null; };
function money(v, ccy) {
  const n = num(v);
  if (n == null) return null;
  try { if (ccy) return new Intl.NumberFormat('en-GB', { style: 'currency', currency: ccy }).format(n); } catch (e) { /* unknown code */ }
  return (ccy ? ccy + ' ' : '') + new Intl.NumberFormat('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}
function day(v) {
  const m = String(v || '').match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return v || '';
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
}
const parseJson = (s) => { if (s && typeof s === 'object') return s; try { return s ? JSON.parse(s) : null; } catch (e) { return null; } };
function walk(o, fn) { if (Array.isArray(o)) o.forEach((x) => walk(x, fn)); else if (o && typeof o === 'object') { fn(o); Object.values(o).forEach((x) => walk(x, fn)); } }

/* Deterministic evidence rows: never AI. */
function evidenceRows(ws, app) {
  const f = (ws && ws.facts) || {};
  const ctrl = f.control_results || [], sup = f.supporting_evidence || [];
  const fileOf = (citation) => { const base = String(citation || '').split('#')[0]; const s = sup.find((x) => String(x.reference || '').split('#')[0] === base); return s ? s.file_version_id : null; };
  let ccy = null;
  sup.forEach((s) => { if (!ccy && s.row && s.row.currency) ccy = s.row.currency; });
  ctrl.forEach((x) => { const m = String((x.control_result || {}).scope || x.scope || '').match(/\b(GBP|EUR|USD|CHF)\b/); if (!ccy && m) ccy = m[1]; });
  const rows = [], seen = new Set();
  let diff = null;
  ctrl.forEach((x, i) => {
    const cr = x.control_result || {};
    const rep = num(cr.reported), comp = num(cr.computed);
    const d = (String(cr.scope || x.scope || '').match(/\d{4}-\d{2}-\d{2}/) || [])[0];
    const delta = rep != null && comp != null && rep !== comp ? Math.round((rep - comp) * 100) / 100 : null;
    if (diff == null && delta != null) diff = delta;
    rows.push({ key: 'c' + i, kind: 'check', date: d, what: plainTitle(cr.check_id || x.check_id), ref: cr.scope || x.scope,
      amount: delta != null ? money(delta, ccy) : rep != null && rep === comp ? money(rep, ccy) : null,
      note: rep != null && comp != null && rep !== comp ? 'Reported ' + money(rep, ccy) + ' · engine expected ' + money(comp, ccy)
        : rep != null && rep === comp ? 'difference reported by the engine' : (cr.note || x.note || x.text || '') });
  });
  ctrl.forEach((x) => {
    const st = parseJson((x.control_result || {}).structured);
    const outliers = new Set();
    walk(st, (o) => { if (o.outlier && o.outlier.record) outliers.add(o.outlier.record); });
    walk(st, (o) => {
      if (!o.record || o.amount == null || seen.has(o.record) || o.outlier || !(o.source || o.citation)) return;
      seen.add(o.record);
      const cat = o.source || String(o.citation || '').split(':')[0];
      const plainRec = { 'roll-forward': 'Balance the engine expects', snapshot: 'Balance the firm recorded' }[o.record];
      rows.push({ key: 'v' + o.record, date: null, what: plainRec || catTitle(app, cat) || cat, ref: plainRec ? null : o.record, amount: money(o.amount, ccy),
        note: outliers.has(o.record) ? 'differs from the other records' : outliers.size ? 'agrees with the other records' : '', fv: fileOf(o.citation), odd: outliers.has(o.record) });
    });
  });
  sup.forEach((s, i) => {
    const r = s.row;
    if (!r || typeof r !== 'object') return;
    const idk = ID_KEYS.find((k) => r[k]);
    const id = idk ? r[idk] : s.reference;
    if (seen.has(id)) return;
    seen.add(id);
    const dk = DATE_KEYS.find((k) => r[k]), ak = AMT_KEYS.find((k) => r[k] != null && r[k] !== '');
    rows.push({ key: 's' + i, date: dk ? r[dk] : null, what: catTitle(app, s.evidence_category) || s.evidence_category, ref: id,
      amount: ak ? money(r[ak], r.currency || ccy) : null,
      note: [r.client_id && 'client ' + r.client_id, r.txn_type && txnWord(r.txn_type).toLowerCase(),
        r.dc_indicator ? ({ D: 'debit', C: 'credit' }[String(r.dc_indicator).toUpperCase()] || r.dc_indicator)
          : r.direction ? ({ CR: 'credit', DR: 'debit' }[String(r.direction).toUpperCase()] || String(r.direction).toLowerCase().replace(/_/g, ' ')) : null].filter(Boolean).join(' · '),
      fv: s.file_version_id });
  });
  return { rows: rows.slice(0, 6), more: Math.max(0, rows.length - 6), diff: diff != null ? money(Math.abs(diff), ccy) : null };
}

const TXN_WORDS = { LOAD_BANK: 'Bank load', LOAD_CARD: 'Card load', SPEND: 'Card spend', REFUND: 'Refund', REDEEM: 'Redemption',
  REDEMPTION: 'Redemption', TRANSFER_IN: 'Transfer in', TRANSFER_OUT: 'Transfer out', FEE: 'Fee' };
const txnWord = (t) => TXN_WORDS[String(t || '').toUpperCase()] || (t ? String(t).replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase()) : 'Transaction');

/* Client balance roll-forward, step by step: previous recorded balance, each transaction of the day (+ credit / - debit),
   the balance the ENGINE expects (its own computed value), the recorded balance, the difference. Values are the engine's
   and the cited source rows; nothing is invented. Returns null when the payload does not hold every piece. */
function rollForwardSteps(ws) {
  const f = (ws && ws.facts) || {};
  const cr = ((f.control_results || [])[0] || {}).control_result || {};
  if ((cr.check_id || '') !== 'CBAL-ROLLFWD') return null;
  const m = String(cr.scope || '').match(/^([A-Z]{3})\/(\S+) (\d{4}-\d{2}-\d{2})$/);
  if (!m) return null;
  const [, ccy, client, date] = m;
  const sup = f.supporting_evidence || [];
  const snaps = sup.filter((s) => s.row && s.row.snapshot_id && s.row.client_id === client);
  const prev = snaps.find((s) => s.row.recon_date < date), cur = snaps.find((s) => s.row.recon_date === date);
  const txns = sup.filter((s) => s.row && s.row.txn_id);
  const comp = num(cr.computed), rep = num(cr.reported);
  if (!prev || comp == null || rep == null) return null;
  const sign = (d) => ['DR', 'D'].includes(String(d || '').toUpperCase()) ? -1 : 1;
  const rows = [{ key: 'p', date: prev.row.recon_date, what: 'Recorded balance at 17:00', ref: prev.row.snapshot_id, amount: money(prev.row.balance, ccy), fv: prev.file_version_id }];
  txns.forEach((t) => {
    const sg = sign(t.row.direction || t.row.dc_indicator);
    rows.push({ key: t.row.txn_id, date: String(t.row.executed_ts || t.row.clearing_date || '').slice(0, 10), op: sg > 0 ? '+' : '−',
      what: txnWord(t.row.txn_type), ref: t.row.txn_id, amount: money(String(t.row.amount).replace(/^-/, ''), ccy), fv: t.file_version_id });
  });
  rows.push({ key: 'e', op: '=', what: 'Balance the engine expects', amount: money(comp, ccy), strong: true });
  rows.push({ key: 'r', date: cur ? cur.row.recon_date : date, what: 'Balance the firm recorded at 17:00', ref: cur ? cur.row.snapshot_id : null,
    amount: money(rep, ccy), fv: cur ? cur.file_version_id : null, strong: true });
  const diff = Math.round((comp - rep) * 100) / 100;
  rows.push({ key: 'd', what: diff > 0 ? 'The recorded balance is lower than expected by' : 'The recorded balance is higher than expected by', amount: money(Math.abs(diff), ccy), diff: true });
  return { client, ccy, date, rows };
}

/* The engine's own links between this exception and others (investigation group links), as written by the engine. */
function engineLinks(ws, excId) {
  const g = ws && ws.exception && ws.exception.investigation_group;
  if (!g || typeof g !== 'object' || !g.links) return [];
  return String(g.links).split(/(?=EXC-[A-Z]+-\d+—EXC-)/).map((t) => t.trim()).filter(Boolean).map((t) => {
    const mm = t.match(/^(EXC-[A-Z]+-\d+)—(EXC-[A-Z]+-\d+)\s+([A-Z0-9 ]+?):\s*([\s\S]*)$/);
    if (!mm) return { other: null, kind: '', text: t.replace(/\s*\[[^\]]*\]\s*;?\s*$/, '') };
    if (mm[1] !== excId && mm[2] !== excId) return null;
    const other = mm[1] === excId ? mm[2] : mm[1];
    return { other, kind: mm[3].replace(/^L\d+\s+/, '').toLowerCase(), text: mm[4].replace(/\s*\[[^\]]*\]\s*;?\s*$/, '').trim() };
  }).filter(Boolean);
}

/* "What went wrong": a plain-English story of the exception, built ONLY from the engine's results and the cited source
   rows (never AI). Each kind of exception has its own short story; when the engine has not established why, the story
   says so. Returns { title, lines: [...], flow: [{label, ref, amount}], gap: {amount, note}, linked } or null. */
function crOf(w) { return (((w && w.facts) || {}).control_results || [])[0] || {}; }
function structured(cr) { return parseJson((cr.control_result || {}).structured) || {}; }
function rowsOf(w) { return (((w && w.facts) || {}).supporting_evidence || []).filter((x) => x.row && typeof x.row === 'object'); }
function ccyOf(w) {
  const r = rowsOf(w).find((x) => x.row.currency);
  if (r) return r.row.currency;
  const m = String((crOf(w).control_result || {}).scope || '').match(/\b(GBP|EUR|USD|CHF)\b/);
  return m ? m[1] : null;
}
function moneyVals(st) {
  const out = [];
  walk(st, (o) => { if (o.amount != null && (o.source || o.citation) && o.record) out.push(o); });
  return out;
}
function txnVsBank(w) {
  /* A transaction-against-bank result (RC4-DIRECT): the firm's transaction amount and the bank's amount. */
  const cr = crOf(w).control_result || {};
  if (cr.check_id !== 'RC4-DIRECT') return null;
  const rows = rowsOf(w), ccy = ccyOf(w);
  const txn = rows.find((x) => x.row.txn_id), bank = rows.find((x) => x.row.bank_entry_id);
  const vals = moneyVals(structured(crOf(w)));
  const vt = vals.find((v) => String(v.source || v.citation).startsWith('IN-11')), vb = vals.find((v) => String(v.source || v.citation).startsWith('IN-09'));
  const firm = num(vt ? vt.amount : (txn ? txn.row.amount : cr.computed)), bankAmt = num(vb ? vb.amount : (bank ? bank.row.amount : cr.reported));
  if (firm == null || bankAmt == null) return null;
  const t = (txn || {}).row || {};
  return { ccy, firm, bank: bankAmt, gap: Math.round((firm - bankAmt) * 100) / 100, client: t.client_id, type: txnWord(t.txn_type).toLowerCase(),
           date: String(t.executed_ts || t.clearing_date || (bank && bank.row.booking_date) || '').slice(0, 10), txnId: t.txn_id || cr.scope,
           bankId: bank ? bank.row.bank_entry_id : (vb && vb.record), out: ['DR', 'D'].includes(String(t.direction || '').toUpperCase()) };
}
function story(ws, linkedWs, links, excId) {
  const c = crOf(ws), cr = c.control_result || {};
  const check = cr.check_id || '';
  const ccy = ccyOf(ws);
  const rows = rowsOf(ws);
  const labelled = (v) => { const n = num(v); if (n != null) return n; const t = String(v || '');
    const named = t.match(/resource (-?[\d.]+)/) || t.match(/requirement (-?[\d.]+)/); if (named) return num(named[1]);
    const all = t.match(/-?\d+\.\d{2}/g); return all ? num(all[all.length - 1]) : null; };
  const comp = labelled(cr.computed), rep = labelled(cr.reported);
  const link = links.find((l) => l.other);
  const linked = link ? { id: link.other, why: /transaction/.test(link.kind) ? 'the same transaction' : /balance|snapshot/.test(link.kind) ? 'the same client balance' : 'linked by the engine' } : null;
  const M = (v) => money(Math.abs(v), ccy);
  // 1. transaction recorded differently from the bank
  const tb = txnVsBank(ws);
  if (tb) {
    const hl = tb.gap > 0 ? 'higher' : 'lower';
    return { title: `A ${tb.type} was recorded ${M(tb.gap)} ${hl} than the bank shows`,
      lines: [`${tb.client ? 'Client ' + tb.client + ' made a ' : 'A '}${tb.type}${tb.date ? ' on ' + day(tb.date) : ''}.`,
              `The firm's records say ${M(tb.firm)}. The bank says ${M(tb.bank)}.`,
              `So the firm's figure is ${M(tb.gap)} ${hl} than what the bank actually ${tb.out ? 'paid out' : 'received'}.`],
      flow: [{ label: "Firm's record", ref: tb.txnId, amount: M(tb.firm) }, { label: 'Bank', ref: tb.bankId, amount: M(tb.bank) }],
      gap: { amount: M(tb.gap), note: 'difference' }, linked };
  }
  // 2. client balance does not roll forward
  if (check === 'CBAL-ROLLFWD' && comp != null && rep != null) {
    const m = String(cr.scope || '').match(/^([A-Z]{3})\/(\S+) (\d{4}-\d{2}-\d{2})$/);
    const client = m ? m[2] : '', date = m ? m[3] : '';
    const diff = Math.round((comp - rep) * 100) / 100;
    const lowhigh = diff > 0 ? 'lower' : 'higher';
    const title = `Client ${client}'s balance is ${M(diff)} ${lowhigh} than it should be`;
    const ltb = txnVsBank(linkedWs);
    if (ltb && Math.abs(Math.abs(ltb.gap) - Math.abs(diff)) < 0.005) {
      return { title,
        lines: [`Client ${client} made a ${ltb.type}${ltb.date ? ' on ' + day(ltb.date) : ''}.`,
                `The firm's records say ${M(ltb.firm)} ${ltb.out ? 'went out' : 'arrived'}. The bank says ${M(ltb.bank)}.`,
                `Because the firm counted ${M(ltb.gap)} ${ltb.gap > 0 ? 'more' : 'less'} than the bank actually ${ltb.out ? 'paid out' : 'paid in'}, ${client}'s balance for ${day(date)} comes out ${M(diff)} different.`],
        flow: [{ label: "Firm's record", ref: ltb.txnId, amount: M(ltb.firm) }, { label: 'Bank', ref: ltb.bankId, amount: M(ltb.bank) }],
        gap: { amount: M(ltb.gap), note: `shows up in ${client}'s balance` }, linked };
    }
    const prev = rows.find((x) => x.row.snapshot_id && x.row.client_id === client && x.row.recon_date < date);
    const n = rows.filter((x) => x.row.txn_id).length;
    return { title,
      lines: [`The engine took ${client}'s balance from ${prev ? day(prev.row.recon_date) + ' (' + M(num(prev.row.balance)) + ')' : 'the day before'} and added that day's ${n} transaction${n === 1 ? '' : 's'}.`,
              `That should give ${M(comp)}, but the firm recorded ${M(rep)} at 17:00.`,
              linked ? `The engine links this to ${linked.id}${linkedWs ? ': ' + (story(linkedWs, null, [], null) || { title: '' }).title.replace(/^./, (ch) => ch.toLowerCase()) : ''}.` : `The records do not show which figure is wrong.`],
      flow: [{ label: 'Engine expects', amount: M(comp) }, { label: 'Firm recorded', ref: client, amount: M(rep) }],
      gap: { amount: M(diff), note: 'difference' }, linked };
  }
  // 3. settlement batch does not add up
  if (check.startsWith('C11-')) {
    const b = rows.find((x) => x.row.batch_id);
    const br = b ? b.row : {};
    const batch = br.batch_id || cr.scope;
    let line = null;
    walk(structured(c), (o) => { if (!line && o.outlier && o.outlier.record && o.outlier.outlier_value != null) line = o.outlier; });
    const head = `Settlement batch ${batch}${br.settlement_date ? ' (' + day(br.settlement_date) + ')' : ''} is meant to add up to its net amount${br.net_amount_reported ? ' of ' + M(num(br.net_amount_reported)) : ''}.`;
    if (line) {
      const g = num(line.outlier_value) - num(line.agreed_value);
      return { title: `A settlement line is ${M(g)} ${g < 0 ? 'lower' : 'higher'} than its transaction`,
        lines: [head, `One line, ${line.record}, shows ${M(num(line.outlier_value))}. The transaction and the batch agree on ${M(num(line.agreed_value))}.`,
                `That ${M(g)} gap is why the batch does not add up. The records do not show which figure is right.`],
        flow: [{ label: 'Settlement line', ref: line.record, amount: M(num(line.outlier_value)) }, { label: 'Transaction', amount: M(num(line.agreed_value)) }],
        gap: { amount: M(g), note: 'difference' }, linked };
    }
    const missing = [...String(cr.note || '').matchAll(/(SL-[\w-]+) does not match transaction (TX-[\w-]+)/g)].map((x) => [x[1], x[2]]);
    if (missing.length) {
      return { title: `Settlement batch ${batch} does not add up`,
        lines: [head, `${missing.length === 1 ? 'One line refers' : missing.length + ' lines refer'} to ${missing.length === 1 ? 'a transaction that is' : 'transactions that are'} not in the firm's transaction export: ${missing.map((x) => x[0] + ' → ' + x[1]).join(', ')}.`,
                'So the batch cannot be matched line by line. The records do not show why the transaction' + (missing.length === 1 ? ' is' : 's are') + ' missing.'],
        flow: [], gap: null, linked };
    }
  }
  // 4a. timing difference stated by the engine's note
  const tm = String(cr.note || '').match(/explained by timing: (LE-[\w-]+) \/ (BE-[\w-]+) \(ref ([\w-]+), (-?[\d.]+), cleared (\d{4}-\d{2}-\d{2})\)/);
  if (tm) {
    const d0 = (String(cr.scope || '').match(/\d{4}-\d{2}-\d{2}/) || [])[0];
    const amt = M(num(tm[4]));
    const days = /one business day/.test(cr.note) ? ' one business day later' : ' later';
    return { kind: 'timing', title: `A ${amt} payment reached the bank${days} than the cash book`,
      lines: [`The firm's cash book recorded ${amt} (reference ${tm[3]})${d0 ? ' on ' + day(d0) : ''}.`,
              `The bank booked the same ${amt} on ${day(tm[5])}${days}.`,
              `So${d0 ? ' on ' + day(d0) : ''} the bank and the cash book differ by ${amt}. The engine treats this as a timing difference that still needs your confirmation.`],
      flow: [{ label: 'Cash book', ref: tm[1] + (d0 ? ' · ' + day(d0) : ''), amount: amt }, { label: 'Bank', ref: tm[2] + ' · ' + day(tm[5]), amount: amt }],
      gap: { amount: amt, note: d0 ? 'open on ' + day(d0) : 'timing' }, linked };
  }
  // 4. bank and cash book differ: timing (same amount, later bank date) or a plain difference
  const cash = rows.find((x) => /^LE-/.test(x.row.entry_id || x.row.ledger_entry_id || '')), bankE = rows.find((x) => x.row.bank_entry_id);
  if (cash && bankE && num(cash.row.amount) === num(bankE.row.amount)) {
    const cd = String(cash.row.posting_date || cash.row.entry_date || cash.row.posting_ts || '').slice(0, 10), bd = String(bankE.row.booking_date || bankE.row.value_date || '').slice(0, 10);
    if (cd && bd && cd !== bd) {
      const amt = M(num(cash.row.amount));
      return { kind: 'timing', title: `The bank and cash book differ by ${amt} on ${day(cd)}`,
        lines: [`The firm's cash book recorded ${amt} on ${day(cd)}.`, `The bank booked the same ${amt} on ${day(bd)}.`,
                `So on ${day(cd)} the bank and the cash book differ by ${amt} until the bank entry arrives.`],
        flow: [{ label: 'Cash book', ref: (cash.row.entry_id || cash.row.ledger_entry_id) + ' · ' + day(cd), amount: amt }, { label: 'Bank', ref: bankE.row.bank_entry_id + ' · ' + day(bd), amount: amt }],
        gap: { amount: amt, note: `open on ${day(cd)}` }, linked };
    }
  }
  // 5. the same cash-book entry twice
  const les = rows.filter((x) => /^LE-/.test(x.row.entry_id || x.row.ledger_entry_id || ''));
  if (/DUPLICATE/.test(String((ws.summary || {}).root_cause || '')) || les.length >= 2) {
    const byAmt = {};
    les.forEach((x) => { (byAmt[x.row.amount] = byAmt[x.row.amount] || []).push(x); });
    const dup = Object.values(byAmt).find((g) => g.length >= 2);
    if (dup) {
      const amt = M(num(dup[0].row.amount)), ids = dup.map((x) => x.row.entry_id || x.row.ledger_entry_id);
      return { kind: 'duplicate', amount: num(dup[0].row.amount), ids, title: `The same ${amt} is recorded twice in the cash book`,
        lines: [`The firm's cash book has the same ${amt} entry twice: ${ids.join(' and ')}.`,
                bankE ? `The bank shows it only once (${bankE.row.bank_entry_id}).` : 'Only one of them is matched to the bank.',
                `So the cash book is ${amt} higher than it should be.`],
        flow: [{ label: 'Cash book entry', ref: ids[0], amount: amt }, { label: 'Same entry again', ref: ids[1], amount: amt }],
        gap: { amount: amt, note: 'counted twice' }, linked };
    }
  }
  // 6. anything else: what the engine expected against what the firm reported
  const where = (() => { const d0 = (String(cr.scope || '').match(/\d{4}-\d{2}-\d{2}/) || [])[0]; const acct = (String(cr.scope || '').match(/(SGA-[\w-]+|[A-Z]{3})$/) || [])[0];
    return [d0 ? 'on ' + day(d0) : '', acct ? 'for ' + acct : ''].filter(Boolean).join(' '); })();
  const lst = linkedWs ? story(linkedWs, null, [], null) : null;
  if (comp != null && rep != null && comp !== rep) {
    const d = Math.round((comp - rep) * 100) / 100;
    const S = (v) => money(v, ccy);
    const cause = lst && lst.kind === 'duplicate' && Math.abs(Math.abs(d) - lst.amount) < 0.005
      ? `Because the same ${M(lst.amount)} was recorded twice in the cash book (${lst.ids.join(' and ')}), the figures ${where} are ${M(d)} apart.`
      : linked ? `The engine links this to ${linked.id}${lst ? ': ' + lst.title.charAt(0).toLowerCase() + lst.title.slice(1) : ''}.` : 'The records do not show why.';
    return { kind: 'generic', title: `${plainTitle(check).replace(/\.$/, '')} — ${M(d)} apart`,
      lines: [`${where ? where.charAt(0).toUpperCase() + where.slice(1) + ', the' : 'The'} engine's figure is ${S(comp)} and the firm's figure is ${S(rep)}.`, cause],
      flow: [{ label: "Engine's figure", amount: S(comp) }, { label: "Firm's figure", amount: S(rep) }], gap: { amount: M(d), note: 'apart' }, linked };
  }
  if (rep != null) {
    return { kind: 'generic', title: `${plainTitle(check)} (${M(rep)})`,
      lines: [`${where ? where.charAt(0).toUpperCase() + where.slice(1) + ', the' : 'The'} engine found a difference of ${M(rep)}.`,
              /same-day resolution/.test(cr.note || '') ? 'A difference like this must be resolved the same day (CASS 15.8.50R).' : cr.note ? `Engine note: ${cr.note}.` : '',
              linked ? `The engine links this to ${linked.id}${lst ? ': ' + lst.title.charAt(0).toLowerCase() + lst.title.slice(1) : ''}.` : 'The records do not show why.'].filter(Boolean),
      flow: [], gap: { amount: M(rep), note: 'difference' }, linked };
  }
  return null;
}

function Story({ st, go, runId }) {
  return <section className="rfx-card rfx-story" aria-label="What went wrong">
    <div className="rfx-label">What went wrong<span className="rfe-badge rfe-badge--det">From the engine and the uploaded files · not AI</span></div>
    <div className="rfx-story__text">{st.lines.map((l, i) => <p key={i}>{l}</p>)}</div>
    {st.flow.length > 0 && <div className="rfx-flow">
      {st.flow.map((f, i) => <React.Fragment key={i}>{i > 0 && <span className="rfx-flow__arrow" aria-hidden="true">→</span>}
        <div className="rfx-flow__box"><div className="rfx-flow__label">{f.label}</div><div className="rfx-flow__amt">{f.amount}</div>{f.ref && <div className="rf-mono rfx-flow__ref">{f.ref}</div>}</div></React.Fragment>)}
      {st.gap && <><span className="rfx-flow__arrow" aria-hidden="true">→</span>
        <div className="rfx-flow__box is-gap"><div className="rfx-flow__label">Gap</div><div className="rfx-flow__amt">{st.gap.amount}</div><div className="rfx-flow__ref">{st.gap.note}</div></div></>}
    </div>}
    {st.linked && <div className="rfx-linked">This is linked to <Button size="sm" variant="link" iconRight="arrowRight" onClick={() => go(runId, st.linked.id)}>{st.linked.id}</Button> ({st.linked.why}).</div>}
  </section>;
}

function CalcTable({ calc, openFile }) {
  return <div className="rfx-ev"><table className="rfx-ev__t rfx-calc"><tbody>{calc.rows.map((r) => <tr key={r.key} className={cx(r.strong && 'is-strong', r.diff && 'is-diff')}>
    <td className="rfx-ev__date">{r.date ? day(r.date) : ''}</td>
    <td className="rfx-calc__op">{r.op || ''}</td>
    <td className="rfx-ev__what"><div>{r.what}</div>{r.ref && <div className="rf-mono rfx-ev__ref">{r.ref}</div>}</td>
    <td className="rfx-ev__amt">{r.amount}</td>
    <td className="rfx-ev__open">{r.fv && <button type="button" className="rfx-ev__btn" title="Open the source file" onClick={() => openFile(r.fv)}><Icon name="file" size={12} />Open</button>}</td>
  </tr>)}</tbody></table></div>;
}

function EvidenceTable({ rows, more, openFile }) {
  if (!rows.length) return <div className="rf-help">The engine reported no figures for this exception. See Engine details.</div>;
  return <div className="rfx-ev">
    <table className="rfx-ev__t"><tbody>{rows.map((r) => <tr key={r.key} className={cx(r.kind === 'check' && 'is-check', r.odd && 'is-odd')}>
      <td className="rfx-ev__date">{r.date ? day(r.date) : ''}</td>
      <td className="rfx-ev__what"><div>{r.what}</div>{r.ref && <div className="rf-mono rfx-ev__ref">{r.ref}</div>}</td>
      <td className="rfx-ev__amt">{r.amount || ''}</td>
      <td className="rfx-ev__note">{r.note}</td>
      <td className="rfx-ev__open">{r.fv && <button type="button" className="rfx-ev__btn" title="Open the source file" onClick={() => openFile(r.fv)}><Icon name="file" size={12} />Open</button>}</td>
    </tr>)}</tbody></table>
    {more > 0 && <div className="rf-help">{more} more in Engine details.</div>}
  </div>;
}

function WhatHappened({ ws, row, cl, ai, onRetry }) {
  const inv = ws && ws.investigation;
  const state = (inv && inv.state) || (row && row.ai_state) || 'NOT_STARTED';
  const published = !!(inv && inv.investigation_id && inv.conclusion !== undefined) || state === 'PUBLISHED';
  const attempts = (inv && inv.attempts) || [];
  const last = attempts[attempts.length - 1];
  const retry = <ActBtn a={cl && cl.actions && cl.actions.retry_investigation} label={attempts.length ? 'Try the AI again' : 'Start AI investigation'} icon="refresh" size="sm" onClick={onRetry} />;
  if (published) return <Headline text={inv.conclusion ? itemText(inv.conclusion) : ''} sufficiency={inv.sufficiency ? itemText(inv.sufficiency) : null} eyebrow={null} bare />;
  if (state === 'QUEUED' || state === 'RUNNING') return <div className="rfx-wait"><span className="rf-skel" style={{ width: '70%' }} /><span className="rf-help">The AI is investigating this exception (usually under a minute). The evidence below is already final.</span></div>;
  if (state === 'UNAVAILABLE') return <Notice tone="attention" compact title="AI is not available on this server">{(cl && cl.ai && cl.ai.problem) || (ai && ai.problem) || 'No AI provider is configured.'} The evidence below is complete without it.</Notice>;
  if (state === 'NOT_PUBLISHED' || state === 'FAILED') return <Notice tone="attention" compact title="The AI explanation is not available for this exception" actions={retry}>{(last && (last.reason || last.error)) ? 'It did not pass the automatic checks, so it is not shown. ' : ''}The evidence below is the engine's own and is complete.</Notice>;
  return <div className="rf-row" style={{ gap: 8 }}><span className="rf-help">No AI explanation yet.</span>{retry}</div>;
}

function DecisionBar({ ws, onDecide }) {
  const d = (ws && ws.decision) || {};
  const a = d.actions || {};
  const cur = d.current;
  const inv = ws && ws.investigation;
  const invId = inv && inv.investigation_id;
  const status = (ws && ws.summary && ws.summary.status) || engineStatus(wsException(ws));
  const accepted = cur && cur.decision === 'ACCEPT';
  return <section className={cx('rfx-decide', cur && (accepted ? 'is-accepted' : 'is-rejected'))} aria-label="Analyst decision">
    <div className="rfx-decide__main">
      {cur ? <div><div className="rfx-decide__q"><Icon name={accepted ? 'check' : 'x'} size={14} /> {accepted ? 'You accepted this finding' : 'You rejected this finding'}</div>
        <div className="rfe-small rf-secondary">{cur.decided_by} · {fmtDateTime(cur.decided_at)}</div>
        {cur.explanation && <div className="rfx-decide__note">“{cur.explanation}”</div>}</div>
        : <div className="rfx-decide__q">{invId ? 'Do you agree with this finding?' : 'You can decide once the AI explanation is available.'}</div>}
      <div className="rf-row" style={{ gap: 8 }}>
        {(!cur || !accepted) && <ActBtn a={a.accept} label={cur ? 'Change to accept' : 'Accept'} variant="primary" icon="check" onClick={() => onDecide('ACCEPT', invId)} extraReason={invId ? null : 'No AI explanation to decide on.'} />}
        {(!cur || accepted) && <ActBtn a={a.reject} label={cur ? 'Change to reject' : 'Reject'} variant="danger" icon="x" onClick={() => onDecide('REJECT', invId)} extraReason={invId ? null : 'No AI explanation to decide on.'} />}
      </div>
    </div>
    <div className="rf-help"><Icon name="lock" size={12} /> Accept puts the AI explanation in the audit pack; Reject leaves it out. Your note is kept either way. The engine status stays {status ? <Enum>{status}</Enum> : 'unchanged'}.</div>
  </section>;
}

function History({ ws, history }) {
  const hist = ((ws && ws.decision) || {}).history || [];
  return <div className="rf-stack rf-stack--3">
    <Sub title={'Decisions · ' + hist.length}>
      {hist.length ? <Table dense caption="Decision history" columns={[{ key: 'd', label: 'Decision' }, { key: 'by', label: 'By' }, { key: 'at', label: 'Time' }, { key: 'ex', label: 'Note' }]}
        rows={hist.map((h, i) => ({ key: i, cells: { d: <Pill state={h.decision} />, by: h.decided_by || h.actor, at: fmtDateTime(h.decided_at || h.at), ex: h.explanation || <span className="rf-muted">—</span> } }))} />
        : <div className="rf-help">No decisions yet.</div>}
    </Sub>
    {history && <Sub title="Events">
      {history.error ? <div className="rf-help">{history.error.message}</div> : !history.data ? <span className="rf-skel" style={{ width: '60%' }} />
        : (history.data.events || []).length ? <ol className="rfe-events">{history.data.events.map((ev, i) => <li key={i}><span className="rf-mono rf-muted rfe-small">{fmtDateTime(ev.at || ev.created_at)}</span><Enum>{ev.event_type || ev.kind || ev.type}</Enum><span className="rfe-small">{ev.actor || ev.actor_id || ''}</span></li>)}</ol>
          : <div className="rf-help">No events yet.</div>}
    </Sub>}
  </div>;
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
  const [why, setWhy] = React.useState('');
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
      const body = { decision: dlg.kind, expected_revision: rev };
      if (why.trim()) body.explanation = why.trim();
      const r = await m.run((svc) => svc.decideInvestigation(ref, dlg.inv, body), { inline: true, success: dlg.kind === 'ACCEPT' ? 'AI finding accepted' : 'AI finding rejected' });
      if (r) { setDlg(null); setWhy(''); }
    }
  };
  const e = (ws && wsException(ws)) || (engq.data && engq.data.exception) || (run.exceptions || []).find((x) => x.exception_id === excId) || {};
  const ev = ws ? evidenceRows(ws, app) : null;
  const calc = ws ? rollForwardSteps(ws) : null;
  const links = ws ? engineLinks(ws, excId) : [];
  const linkedId = (links.find((l) => l.other) || {}).other || null;
  const lq = useQuery(forRun && linkedId ? 'cexc:' + ref + ':' + linkedId : null, (svc) => svc.getClosureException(ref, linkedId));
  const st = ws ? story(ws, lq.data || null, links, excId) : null;

  return <div className="rfe-ws">
    <div className="rfe-ws__nav">
      <Button size="sm" variant="quiet" icon="arrowLeft" onClick={() => go(runId)}>Back to exceptions</Button>
      <span className="rf-spacer" />
      <span className="rfd-dhead__pos">Finding {idx > -1 ? idx + 1 : '?'} of {list.length}</span>
      <Button size="sm" variant="quiet" icon="chevronLeft" disabled={idx < 1} aria-label="Previous finding" onClick={() => go(runId, list[idx - 1])} />
      <Button size="sm" variant="quiet" icon="chevronRight" disabled={idx < 0 || idx >= list.length - 1} aria-label="Next finding" onClick={() => go(runId, list[idx + 1])} />
    </div>
    <header className="rfe-ws__head rfx-head">
      <div style={{ minWidth: 0 }}>
        <h2 className="rfd-dtitle rfx-title">{st ? st.title : ws ? plainTitle(e.category || String(e.root_cause || '').split('|')[0]) : (e.title || e.category || e.root_cause || excId)}</h2>
        <div className="rf-row rf-row--wrap rfx-sub" style={{ gap: 8 }}>{ws && String(e.root_cause || '').includes('|') && <span className="rf-mono">{String(e.root_cause).split('|').slice(1).join(' · ')}</span>}<Ref id={excId} copy /></div>
      </div>
      <div className="rf-row rf-row--wrap rfx-head__right" style={{ gap: 8 }}>{st && st.gap ? <span className="rfx-amount">{st.gap.amount}</span> : ev && ev.diff && <span className="rfx-amount">{ev.diff}</span>}{e.severity && <Sev value={e.severity} />}{row && row.analyst_decision && <Pill state={row.analyst_decision} label={row.analyst_decision === 'ACCEPT' ? 'Accepted' : 'Rejected'} />}{row && row.review_state === 'PENDING_REVIEW' && <Pill state="V_PENDING" label="Awaiting your decision" />}</div>
    </header>
    {cl && !forRun && <Notice tone="info" compact>Closure belongs to run <span className="rf-mono">{cl.recon_run_id}</span>. This earlier run shows the engine facts only.</Notice>}
    {!cl && clq.error && <ClosureError err={clq.error} reload={clq.reload} />}
    {forRun && wsq.error && <Notice tone="danger" compact title="Exception workspace could not be loaded" actions={<Button size="sm" onClick={wsq.reload}>Try again</Button>}>{wsq.error.message} The engine facts are shown instead.</Notice>}
    {cl && cl.frozen && <Notice tone="locked" compact title="Closure frozen">The final pack has been generated. Decisions and investigations are read-only.</Notice>}
    {(forRun && !ws && !wsq.error) || (useEngine && !engq.data && !engq.error) ? <div className="rf-panel" style={{ padding: 16 }}><span className="rf-skel" style={{ width: '80%' }} /><span className="rf-skel" style={{ width: '60%', marginTop: 10 }} /></div>
      : ws ? <div className="rfx rfx--wide">
        <div className="rfx-col">
          {st && <Story st={st} go={go} runId={runId} />}
          <section className="rfx-card" aria-label="What the AI thinks">
            <div className="rfx-label">What the AI thinks<span className="rfe-badge rfe-badge--ai"><Icon name="sparkNone" size={12} />{['AI reading', ws.investigation && ws.investigation.model, 'an interpretation, not a fact'].filter(Boolean).join(' · ')}</span></div>
            <WhatHappened ws={ws} row={row} cl={cl} ai={ai.data} onRetry={() => { m.reset(); setDlg({ kind: 'retry' }); }} />
          </section>
          <DecisionBar ws={ws} onDecide={(kind, inv) => { m.reset(); setWhy(''); setDlg({ kind, inv }); }} />
        </div>
        <div className="rfx-col">
          <section className="rfx-card" aria-label="The records">
            <div className="rfx-label">The records<span className="rfe-badge rfe-badge--det">Engine and uploaded files · not AI</span></div>
            {calc ? <><div className="rfx-calc__title">How the engine checked client {calc.client}'s balance on {day(calc.date)}</div><CalcTable calc={calc} openFile={openFile} /></>
              : <EvidenceTable rows={ev.rows} more={ev.more} openFile={openFile} />}
            {links.length > 0 && <div className="rfx-links"><div className="rfx-calc__title">Linked by the engine</div>
              {links.map((l, i) => <div key={i} className="rfx-link">{l.other && <Button size="sm" variant="link" iconRight="arrowRight" onClick={() => go(runId, l.other)}>{l.other}</Button>}
                <span>{l.kind ? <span className="rf-muted">({l.kind}) </span> : null}{l.text}</span></div>)}</div>}
          </section>
          <details className="rfx-more"><summary>Engine details</summary>
            <Facts ws={ws} eng={null} app={app} openFile={openFile} run={run} runId={runId} /></details>
          <details className="rfx-more"><summary>How the AI reached this</summary>
            <Investigation ws={ws} row={row} cl={cl} ai={ai.data} openFile={openFile} hideHeadline onRetry={() => { m.reset(); setDlg({ kind: 'retry' }); }} /></details>
          <details className="rfx-more"><summary>History</summary><History ws={ws} history={histq} /></details>
        </div>
      </div>
      : <div className="rfe-cols rfe-cols--1">
        <Facts ws={null} eng={useEngine ? engq.data : null} app={app} openFile={openFile} run={run} runId={runId} />
        {useEngine && engq.error && <Notice tone="danger" title="Exception could not be loaded">{engq.error.message}</Notice>}
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
          <div className="rf-help">{dlg.kind === 'ACCEPT' ? 'Records that you accept the published AI finding. It is reported as accepted in the final audit pack.' : 'Records that you reject the published AI finding. Its AI content is excluded from the final audit pack; the original investigation is kept unchanged.'}</div>
          <label className="rfe-explain"><span>Explanation (optional{dlg.kind === 'REJECT' ? ', recommended when rejecting' : ''})</span>
            <textarea value={why} maxLength={2000} rows={4} onChange={(ev) => setWhy(ev.target.value)} placeholder={dlg.kind === 'REJECT' ? 'Why is the AI finding rejected?' : 'Any comment on the AI finding'} /></label>
          {dlg.kind === 'REJECT' && !why.trim() && ws && ws.decision && ws.decision.rejection_wording && <Notice tone="info" compact title="Recorded wording if no explanation is given">{ws.decision.rejection_wording}</Notice>}
          <div className="rf-help"><Icon name="lock" size={12} /> The engine exception status does not change.</div></div>}
    </Dialog></div>}
  </div>;
}
