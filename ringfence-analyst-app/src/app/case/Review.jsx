/* S08 · Mapping review. Renders GET /api/cases/{ref}/review/{vid} as returned; every decision is
   explicit (AI proposals are never applied without one) and the backend decides what is allowed
   (available_actions, editable, can_confirm, file_actions). */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, WithReason, Panel, Notice, Table, Segmented, Empty, Skeleton, Dialog, Pill, Enum, Tag, Ref, Icon, KV, DECISIONS, stateOf, cx } from '../../ui/index.jsx';
import { fmtDateTime } from '../format.js';

const BASIS = { deterministic: ['EXACT', 'EXACT / ALIAS'], diagnostic_name_match: ['NAME_MATCH', 'NAME MATCH'], proposal: ['LLM', 'PROPOSAL'], none: ['NONE', 'NONE'] };
export function BasisTag({ basis }) { const b = BASIS[basis] || ['NONE', String(basis || 'NONE').toUpperCase()]; return <Tag kind={b[0]} text={b[1]} />; }
// Fix8 D4: a financial AI proposal that is ambiguous / interchangeable is never a one-click Map; the analyst names the field.
const CLARIFY = ['CLARIFY', 'Clarify', 'Name the financial field explicitly. Required for this column (no one-click Map).'];
const ALL_DECISIONS = DECISIONS.concat([CLARIFY]);
const decisionsFor = (avail) => (avail.includes('CLARIFY') ? DECISIONS.filter((d) => d[0] !== 'MAP' && d[0] !== 'CHANGE').concat([CLARIFY]) : DECISIONS);
const needsField = (a) => a === 'CHANGE' || a === 'CLARIFY';
const SOURCE_TAG = { AI: ['LLM', 'AI PROPOSAL'], 'AI (recorded test fixture)': ['LLM', 'RECORDED FIXTURE'], deterministic: ['EXACT', 'DETERMINISTIC'], analyst: ['ANALYST', 'ANALYST'] };
function SourceTag({ source }) { if (!source) return <Tag kind="NONE" text="NO SUGGESTION" />; const t = SOURCE_TAG[source] || ['NONE', String(source).toUpperCase()]; return <Tag kind={t[0]} text={t[1]} />; }
const actionLabel = (a) => (ALL_DECISIONS.find((d) => d[0] === a) || [a, a])[1];
const decisionText = (d) => (d ? actionLabel(d.action) + (d.canonical_field ? ' → ' + d.canonical_field : '') : '');
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many || one + 's');
const fieldName = (x) => (typeof x === 'string' ? x : (x && (x.name || x.canonical_field)) || JSON.stringify(x));
const nextUndecided = (rows, from) => {
  const open = (rows || []).filter((r) => r.needs_attention && !r.decided);
  return open.find((r) => r.source_index > from) || open[0] || null;
};

export default function ReviewTab({ c, app, route, nav, openAction }) {
  const ref = c.case_ref;
  const awaiting = (c.progress && c.progress.awaiting_review) || [];
  const vid = route.sub || (awaiting[0] && awaiting[0].file_version_id) || null;
  const key = vid ? 'review:' + ref + ':' + vid : null;
  const rq = useQuery(key, (svc) => svc.getReview(ref, vid));
  const rv = rq.data && rq.data.file_version_id === vid ? rq.data : null;
  const [dialog, setDialog] = React.useState(null);
  const corrections = ((c.outstanding && c.outstanding.files_requiring_replacement) || []).filter((x) => x.cause === 'COLUMN_REJECTED');
  const open = (id) => nav('cases/' + ref + '/review/' + id);

  const files = awaiting.map((a) => ({ vid: a.file_version_id, category: a.category, title: a.title, name: a.original_filename, v: a.version_number, remaining: a.remaining, total: a.total }));
  if (vid && !files.some((f) => f.vid === vid)) files.push({ vid, category: rv ? rv.evidence_category : '', title: rv ? rv.category_title : 'Selected file', name: rv ? rv.original_filename : vid, v: rv ? rv.version_number : null, state: rv ? rv.version_status : null });

  if (!vid) {
    return <div className="rf-page"><PageHead c={c} />
      <Corrections items={corrections} onEvidence={() => nav('cases/' + ref + '/evidence')} />
      <Panel><Empty icon="checklist" title="No file awaits review" action={<div className="rf-row"><Button icon="file" onClick={() => nav('cases/' + ref + '/evidence')}>Open Evidence</Button><Button onClick={() => nav('cases/' + ref + '/package')}>Validation &amp; activation</Button></div>}>
        {c.actions.review.reason || 'Every mapping review for the current evidence is complete.'}
      </Empty></Panel>
    </div>;
  }

  const lockReason = !c.actions.review.enabled ? c.actions.review.reason || 'Review is not available.' : rv && !rv.editable ? 'This file version is not open for review (' + stateOf(rv.version_status).label + ').' : null;
  const afterFile = (detail) => {
    setDialog(null);
    const next = ((detail && detail.progress && detail.progress.awaiting_review) || []).find((a) => a.file_version_id !== vid);
    nav('cases/' + ref + '/review' + (next ? '/' + next.file_version_id : ''));
  };

  return <div className="rf-page">
    <PageHead c={c} />
    {files.length > 0 && <div className="rfc-files" role="tablist" aria-label="Files awaiting review">{files.map((f) => <button key={f.vid} type="button" role="tab" aria-selected={f.vid === vid} className={cx('rfc-file', f.vid === vid && 'is-selected')} onClick={() => open(f.vid)}>
      <Icon name="fileTable" /><span style={{ minWidth: 0 }}><span className="rfc-file__title">{f.category} · {f.title}</span><span className="rfc-file__meta rf-mono">{f.name}{f.v != null ? ' v' + f.v : ''}</span>
        <span className="rfc-file__meta">{f.remaining != null ? (f.remaining ? plural(f.remaining, 'decision') + ' outstanding of ' + f.total : 'All ' + f.total + ' decided · ready to confirm') : f.state ? stateOf(f.state).label : ''}</span></span></button>)}</div>}
    <Corrections items={corrections} onEvidence={() => nav('cases/' + ref + '/evidence')} />
    {lockReason && <Notice tone="locked" title="Read-only" actions={c.actions.resume.enabled ? <Button variant="primary" icon="play" onClick={() => openAction('resume')}>Resume Processing</Button> : null}>{lockReason}</Notice>}
    {rq.error && !rv ? <Notice tone="danger" title="The review could not be loaded" actions={<Button size="sm" onClick={rq.reload}>Retry</Button>}>{rq.error.message}</Notice>
      : !rv ? <Skeleton rows={6} />
      : <FileReview key={vid} c={c} app={app} rv={rv} lockReason={lockReason} onConfirm={() => setDialog('confirm')} onReject={() => setDialog('reject')} />}
    {dialog === 'confirm' && rv && <ConfirmDialog c={c} rv={rv} onClose={() => setDialog(null)} onDone={afterFile} />}
    {dialog === 'reject' && rv && <RejectDialog c={c} rv={rv} onClose={() => setDialog(null)} onDone={afterFile} />}
  </div>;
}

function PageHead({ c }) {
  const p = c.progress || {};
  return <div className="rf-page__head"><div><h2 className="rf-page__title">Mapping review</h2>
    <div className="rf-page__sub">{p.files_awaiting_review ? plural(p.files_awaiting_review, 'file') + ' awaiting review · ' + plural(p.decisions_outstanding || 0, 'decision') + ' outstanding' : 'No file awaits review'} · {plural(p.decisions_made || 0, 'decision')} recorded. Proposals are never applied without your decision.</div></div></div>;
}

function Corrections({ items, onEvidence }) {
  if (!items.length) return null;
  return <Notice tone="attention" title={'Correction requested for ' + plural(items.length, 'file')} actions={<Button size="sm" icon="upload" onClick={onEvidence}>Open Evidence</Button>}>
    {items.map((x) => x.category + ' v' + x.version + ' (' + stateOf(x.version_status).label + ')' + (x.detail ? ': ' + String(x.detail).replace(/[.\s]+$/, '') : '')).join(' · ')}. Upload a corrected file as a new version.</Notice>;
}

function FileReview({ c, app, rv, lockReason, onConfirm, onReject }) {
  const rows = rv.rows || [];
  const counts = rv.counts || {};
  const attention = rows.filter((r) => r.needs_attention);
  const groups = { open: attention.filter((r) => !r.decided), decided: attention.filter((r) => r.decided), all: rows };
  const [filter, setFilter] = React.useState(groups.open.length ? 'open' : groups.decided.length ? 'decided' : 'all');
  const visible = groups[filter];
  const [sel, setSel] = React.useState(() => (groups.open[0] || rows[0] || {}).source_index);
  const row = rows.find((r) => r.source_index === sel) || visible[0] || rows[0] || null;
  const readOnly = !!lockReason;
  const actions = rv.file_actions || [];
  const confirmWhy = readOnly ? lockReason : !rv.can_confirm ? (counts.remaining ? plural(counts.remaining, 'decision') + ' outstanding' : 'Confirmation is not available for this file.') : null;
  const notCovered = (rv.required_not_covered || []).map(fieldName);

  return <>
    <section className="rf-filereview is-open" aria-label="File review">
      <Icon name="fileTable" />
      <div className="rf-filereview__file">
        <div className="rf-row rf-row--wrap" style={{ gap: 8 }}><span className="rf-mono rf-strong" style={{ fontSize: 13 }}>{rv.original_filename}</span><span className="rf-mono rf-muted" style={{ fontSize: 12 }}>v{rv.version_number}</span><Pill state={rv.version_status} /><Enum>{rv.review_kind}</Enum></div>
        <div className="rf-filereview__meta">{rv.evidence_category} · {rv.category_title} · <span className="rf-mono">{rv.file_version_id}</span> · package <span className="rf-mono">{rv.package_id}</span></div>
        {rv.review_reason && <div className="rf-filereview__meta">{rv.review_reason}</div>}
        <div className="rfc-counts"><span>Need attention <b>{counts.attention != null ? counts.attention : attention.length}</b></span><span>Decided <b>{counts.decided != null ? counts.decided : groups.decided.length}</b></span><span>Outstanding <b>{counts.remaining != null ? counts.remaining : groups.open.length}</b></span><span>Recognised <b>{counts.recognised != null ? counts.recognised : '—'}</b></span></div>
      </div>
      <div className="rf-filereview__actions">
        {!actions.length ? <span className="rf-muted" style={{ fontSize: 12 }}>Not open for review · {stateOf(rv.version_status).label}</span> : <>
          {actions.includes('REJECT') && (readOnly ? <WithReason reason={lockReason}><Button variant="danger" disabled>Reject / Request correction</Button></WithReason> : <Button variant="danger" onClick={onReject}>Reject / Request correction</Button>)}
          {actions.includes('CONFIRM') && (confirmWhy ? <WithReason reason={confirmWhy}><Button icon="check" disabled>Confirm file</Button></WithReason> : <Button variant="primary" icon="check" onClick={onConfirm}>Confirm file</Button>)}
        </>}
      </div>
    </section>
    {notCovered.length > 0 && <Notice tone="attention" compact title="Required fields not covered">{notCovered.map((n) => <Enum key={n}>{n}</Enum>)}</Notice>}
    {rv.review_kind === 'MANUAL_MAPPING' && <Notice tone="attention" compact title="Manual mapping: no usable AI proposal">{(rv.unresolved_headers || []).length ? 'Unresolved column(s): ' + rv.unresolved_headers.join(', ') + '. ' : ''}Choose the field for each (Change), ignore it, or reject the file.</Notice>}
    {rv.proposal_provider_id && <Notice tone="info" compact title="Proposal source">{String(rv.proposal_provider_id).startsWith('recorded_stub') ? 'Recorded test fixture (not a live model)' : 'Live AI · ' + rv.proposal_provider_id}{rv.proposal_id ? ' · proposal ' + rv.proposal_id : ''}. Proposals are advisory: nothing is applied without your decision, and every choice is checked against the column values.</Notice>}
    {rv.clarifications_required > 0 && <Notice tone="attention" compact title={plural(rv.clarifications_required, 'financial column') + ' need an explicit choice'}>Ambiguous or interchangeable money fields cannot be mapped with one click. Use Clarify and name the field.</Notice>}
    <FinancialChecks fin={rv.financial_checks} />
    <section className="rf-panel rfc-reviewpanel">
      <header className="rf-panel__head"><div><h3 className="rf-panel__title">Columns</h3><div className="rf-panel__sub">Headers exactly as received. Recognised columns (exact canonical headers) are confirmed with the file.</div></div><span className="rf-spacer" />
        <Segmented items={[['open', 'Outstanding (' + groups.open.length + ')'], ['decided', 'Decided (' + groups.decided.length + ')'], ['all', 'All (' + rows.length + ')']]} active={filter} onChange={setFilter} /></header>
      <div className="rf-review">
        <div className="rf-review__list">
          {visible.length ? <Table dense caption="Columns needing a decision" columns={[{ key: 'pos', label: 'Col', width: 52 }, { key: 'hdr', label: 'Source header' }, { key: 'sug', label: 'Suggested field' }, { key: 'basis', label: 'Basis' }, { key: 'flags', label: '' }, { key: 'dec', label: 'Decision' }]}
            rows={visible.map((r) => ({ key: String(r.source_index), selected: row && r.source_index === row.source_index, onClick: () => setSel(r.source_index), cells: {
              pos: <span className="rf-colpos">{r.source_position}</span>,
              hdr: <span className="rf-srchdr" title={r.source_header}>{r.source_header}</span>,
              sug: r.suggested_field ? <span className="rf-canon is-proposed">{r.suggested_field}</span> : <span className="rf-canon is-none">No suggestion</span>,
              basis: <span className="rf-row rf-row--wrap" style={{ gap: 4 }}><SourceTag source={r.proposal_source} />{r.suggestion_basis === 'proposal' && r.proposal_class && <Enum>{r.proposal_class}</Enum>}</span>,
              flags: <span className="rf-row rf-row--wrap" style={{ gap: 4 }}>{r.field_required && <Tag kind="REQUIRED" />}{r.financial && <Tag kind="FINANCIAL" />}{r.duplicate && <Tag kind="CONFLICT" />}{r.clarification_required && !r.decided && <Tag kind="WARNING" text="CLARIFY" />}{r.value_check && r.value_check.status === 'FAIL' && <Tag kind="WARNING" text="VALUES FAIL" />}</span>,
              dec: !r.needs_attention && !r.decision ? <span className="rf-muted" style={{ fontSize: 12 }}>Recognised</span> : r.decided && r.decision ? <span className="rf-row" style={{ gap: 6 }}><Tag kind="ANALYST" text={r.decision.action} /><span className="rf-canon">{r.decision.canonical_field || '—'}</span></span> : <Pill state="M_REVIEW" label="Outstanding" />
            } }))} />
            : <Empty icon="check" title={filter === 'open' ? 'No column outstanding' : 'No column here'}>{filter === 'open' ? 'Every column that needs a decision has one. Confirm the file when you are satisfied.' : 'Choose another filter.'}</Empty>}
        </div>
        {row ? <Inspector key={row.source_index} c={c} app={app} rv={rv} row={row} readOnly={readOnly} lockReason={lockReason} onNext={setSel} /> : <aside className="rf-inspector"><div className="rf-inspector__body"><Empty title="Select a column" /></div></aside>}
      </div>
    </section>
  </>;
}

function Inspector({ c, app, rv, row, readOnly, lockReason, onNext }) {
  const ref = c.case_ref;
  const m = useMutation();
  const avail = row.available_actions || [];
  const choices = decisionsFor(avail);
  const [choice, setChoice] = React.useState(row.decision && choices.some((d) => d[0] === row.decision.action) && avail.includes(row.decision.action) ? row.decision.action : null);
  const [field, setField] = React.useState(row.decision && row.decision.action === 'CHANGE' ? row.decision.canonical_field || '' : '');
  const editable = !readOnly && row.needs_attention !== false;
  React.useEffect(() => {
    if (!editable) return undefined;
    const onKey = (e) => {
      const t = e.target && e.target.tagName;
      if (t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return;
      const d = choices[Number(e.key) - 1];
      if (d && avail.includes(d[0])) { setChoice(d[0]); m.reset(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editable, avail.join()]);
  const next = nextUndecided(rv.rows, row.source_index);
  const hasNext = next && next.source_index !== row.source_index;
  const needField = needsField(choice) && !field;
  const record = async () => {
    const r = await m.run((svc) => svc.postDecision(ref, rv.file_version_id, { action: choice, source_index: row.source_index, canonical_field: needsField(choice) ? field : undefined, expected_revision: c.revision }), { inline: true, key: 'review:' + ref + ':' + rv.file_version_id });
    if (r && r.rows) { const n = nextUndecided(r.rows, row.source_index); if (n && n.source_index !== row.source_index) onNext(n.source_index); }
  };
  const llmLabel = app && app.llm && app.llm.label;
  const fields = rv.canonical_fields || [];
  const why = (code) => (readOnly ? null : !avail.includes(code) ? (code === 'MAP' && !row.suggested_field ? 'No suggested field. Use Change or Ignore.' : 'Not available for this column.') : null);
  const desc = (d) => (d[0] === 'MAP' && row.suggested_field ? 'Use the suggested field ' + row.suggested_field + '.' : d[2]);
  return <aside className="rf-inspector" aria-label={'Column ' + row.source_position}>
    <div className="rf-inspector__head">
      <div className="rf-row rf-row--wrap" style={{ gap: 6 }}><span className="rf-colpos">{row.source_position}</span><span className="rf-srchdr">{row.source_header}</span><Icon name="arrowRight" size={12} className="rf-maparrow" />{row.suggested_field ? <span className="rf-canon is-proposed">{row.suggested_field}</span> : <span className="rf-canon is-none">No suggestion</span>}</div>
      <div className="rf-row rf-row--wrap" style={{ gap: 4, marginTop: 8 }}><BasisTag basis={row.suggestion_basis} />{row.field_type && <Enum>{row.field_type}</Enum>}<Tag kind={row.field_required ? 'REQUIRED' : 'OPTIONAL'} />{row.financial && <Tag kind="FINANCIAL" />}{row.duplicate && <Tag kind="CONFLICT" />}</div>
    </div>
    <div className="rf-inspector__body">
      <div className="rf-isec"><div className="rf-isec__title">Sample values<span className="rf-spacer" /><span className="rf-muted">{(row.samples || []).length} shown</span></div>
        {(row.samples || []).length ? <table className="rf-samples"><thead><tr><th>Value as received</th></tr></thead><tbody>{row.samples.slice(0, 6).map((s, i) => <tr key={i}><td>{s === '' ? <span className="rf-muted">(empty)</span> : s}</td></tr>)}</tbody></table> : <div className="rf-help">No samples returned.</div>}</div>
      {row.proposal_assessment && <div className="rf-isec"><div className="rf-assess"><div className="rf-assess__label"><Icon name="sparkNone" size={12} />{row.proposal_source === 'AI' ? 'Live AI proposal' : row.proposal_source || 'Proposal'} · not applied without your decision</div>
        <KV pairs={[['Source', <SourceTag source={row.proposal_source} />], ['Proposer said', <Enum>{row.proposal_assessment}</Enum>], ['Validated class', <Enum>{row.proposal_class || '—'}</Enum>]].concat((row.proposal_alternatives || []).length ? [['Alternatives', row.proposal_alternatives.join(', ')]] : [])} />
        {row.proposal_explanation && <div className="rf-help" style={{ marginTop: 6 }}><b>Explanation:</b> {row.proposal_explanation}</div>}
        {llmLabel && <div className="rf-help" style={{ marginTop: 6 }}>{llmLabel}</div>}</div></div>}
      {row.clarification_required && <div className="rf-isec"><Notice tone="attention" compact title="Explicit choice required">{row.clarification_reason}</Notice></div>}
      {(row.validation || row.note || row.value_check) && <div className="rf-isec"><div className="rf-isec__title">Checks and notes</div><div className="rf-stack rf-stack--2">{row.validation && <div className="rf-implication">{row.validation}</div>}{row.note && <div className="rf-help">{row.note}</div>}
        {row.value_check && <div className="rf-help">Value check ({row.value_check.field}): <b>{row.value_check.status}</b> · {row.value_check.failed} of {row.value_check.rows} value(s) break the field rule{row.value_check.empty ? ' · ' + row.value_check.empty + ' empty' : ''}</div>}</div></div>}
      {row.decision && <div className="rf-isec"><div className="rf-isec__title">Recorded decision</div><KV pairs={[['Decision', <span className="rf-strong">{decisionText(row.decision)}</span>], ['By', <span className="rf-mono">{row.decision.reviewer || '—'}</span>], ['At', fmtDateTime(row.decision.at)]].concat(row.decision.backend_action && row.decision.backend_action !== row.decision.action ? [['Recorded as', <Enum>{row.decision.backend_action}</Enum>]] : [])} /></div>}
      {row.needs_attention !== false && <div className="rf-isec"><div className="rf-isec__title">{row.decision ? 'Change the decision' : 'Decide'}</div>
        {readOnly && <div className="rf-help" style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}><Icon name="lock" size={12} />{lockReason}</div>}
        <div className={cx('rf-decisions', 'rf-decisions--3', readOnly && 'is-readonly')} role="radiogroup" aria-label="Mapping action">{choices.map((d, i) => { const w = why(d[0]); const off = readOnly || !!w; return <button key={d[0]} type="button" role="radio" aria-checked={choice === d[0]} className={cx('rf-decision', choice === d[0] && 'is-selected')} disabled={off} onClick={() => { setChoice(d[0]); m.reset(); }}>
          <span className="rf-row" style={{ justifyContent: 'space-between' }}><span className="rf-decision__label">{d[1]}</span>{!off && <span className="rf-kbd">{i + 1}</span>}</span><span className="rf-decision__code">{d[0]}</span><span className="rf-decision__desc">{w || desc(d)}</span></button>; })}</div>
        {needsField(choice) && !readOnly && <div className="rf-field" style={{ marginTop: 10 }}><label className="rf-label" htmlFor="rfc-field">Canonical field</label>
          <select id="rfc-field" className="rf-input rfc-select" value={field} onChange={(e) => { setField(e.target.value); m.reset(); }}><option value="">Choose a canonical field…</option>{fields.map((f) => <option key={f.name} value={f.name}>{f.name} · {f.requiredness || (f.required ? 'REQUIRED' : 'OPTIONAL')}{f.type ? ' · ' + f.type : ''}</option>)}</select>
          <div className="rf-help">{choice === 'CLARIFY' ? 'Name the field this column really holds (the proposal was ' + (row.suggested_field || 'none') + '). Recorded as a clarification; values and financial relationships are checked.' : 'Overrides the suggestion. The backend checks the choice against the column values.'}</div></div>}
      </div>}
    </div>
    {row.needs_attention !== false && <div className="rf-inspector__foot">
      {m.error && <div style={{ marginBottom: 8 }}><Notice tone="danger" compact title={'Not recorded' + (m.code ? ' · ' + m.code : '')}>{m.error}</Notice></div>}
      <div className="rf-row" style={{ justifyContent: 'flex-end' }}>
        {readOnly ? <WithReason reason={lockReason}><Button variant="primary" disabled>Record decision</Button></WithReason>
          : !choice || needField ? <WithReason reason={!choice ? 'Choose ' + choices.map((d) => d[1]).join(', ') : 'Choose a canonical field'}><Button variant="primary" disabled>Record decision</Button></WithReason>
          : <Button variant="primary" icon="check" loading={m.busy} onClick={record}>{m.busy ? 'Recording…' : hasNext && !row.decided ? 'Record & next' : 'Record decision'}</Button>}
      </div>
    </div>}
  </aside>;
}

function FinancialChecks({ fin }) {
  if (!fin || !fin.relationships_defined) return null;
  const tone = (st) => (st === 'FAIL' ? 'danger' : st === 'WARN' ? 'attention' : 'info');
  const cur = fin.current || [];
  const prop = fin.as_proposed || [];
  return <section className="rf-panel" aria-label="Financial value checks"><header className="rf-panel__head"><div><h3 className="rf-panel__title">Financial value checks</h3><div className="rf-panel__sub">Relationships between money columns, checked on every row of this file. A contradictory mapping is refused.</div></div></header>
    <div className="rf-stack rf-stack--2" style={{ padding: 12 }}>
      {cur.map((r) => <Notice key={'c' + r.relationship} tone={tone(r.status)} compact title={'Current decisions · ' + r.text + ' · ' + r.status}>{r.detail}</Notice>)}
      {prop.filter((r) => r.status !== 'NOT_EVALUATED').map((r) => <Notice key={'p' + r.relationship} tone={tone(r.status)} compact title={'If accepted as proposed · ' + r.status}>{r.detail}{r.better_assignment ? ' · Values fit: ' + Object.entries(r.better_assignment).map(([f, col]) => f + ' ← ' + col).join(', ') : ''}</Notice>)}
    </div></section>;
}

function ConfirmDialog({ c, rv, onClose, onDone }) {
  const m = useMutation();
  const decided = (rv.rows || []).filter((r) => r.decision);
  const go = async () => {
    const r = await m.run((svc) => svc.confirmReview(c.case_ref, rv.file_version_id, { expected_revision: c.revision }), { inline: true, success: 'File confirmed · ' + rv.original_filename + ' v' + rv.version_number + '. Validation runs automatically.' });
    if (r) onDone(r);
  };
  return <Dialog eyebrow="Confirm file mapping" title={'Confirm ' + rv.original_filename + ' v' + rv.version_number + '?'} error={m.error} onClose={m.busy ? undefined : onClose}
    foot={<><Button onClick={onClose} disabled={m.busy}>Cancel</Button><Button variant="primary" icon="check" loading={m.busy} onClick={go}>{m.busy ? 'Confirming…' : 'Confirm file'}</Button></>}>
    <div>Your {plural(decided.length, 'decision')} and the {plural((rv.counts && rv.counts.recognised) || 0, 'recognised column')} are confirmed together for this file version. Validation then runs automatically.</div>
    {decided.length > 0 && <div className="rf-table-wrap" style={{ maxHeight: 240 }}><table className="rf-table rf-table--dense"><thead><tr><th>Col</th><th>Source header</th><th>Decision</th></tr></thead><tbody>{decided.map((r) => <tr key={r.source_index}><td><span className="rf-colpos">{r.source_position}</span></td><td><span className="rf-srchdr">{r.source_header}</span></td><td>{decisionText(r.decision)}</td></tr>)}</tbody></table></div>}
  </Dialog>;
}

function RejectDialog({ c, rv, onClose, onDone }) {
  const m = useMutation();
  const go = async () => {
    const r = await m.run((svc) => svc.rejectReview(c.case_ref, rv.file_version_id, { expected_revision: c.revision }), { inline: true, success: 'Correction requested · ' + rv.original_filename + ' v' + rv.version_number + ' rejected' });
    if (r) onDone(r);
  };
  return <Dialog eyebrow="Reject / Request correction" title={'Reject ' + rv.original_filename + ' v' + rv.version_number + '?'} error={m.error} onClose={m.busy ? undefined : onClose}
    foot={<><Button onClick={onClose} disabled={m.busy}>Cancel</Button><Button variant="danger" loading={m.busy} onClick={go}>{m.busy ? 'Rejecting…' : 'Reject file'}</Button></>}>
    <div>This file version is rejected and recorded as requiring correction for <b>{rv.evidence_category} · {rv.category_title}</b>.</div>
    <Notice tone="info" compact>Upload a corrected file as a new version in the Evidence tab. It is processed and reviewed on its own; decisions on this version stay in its history and are not carried forward.</Notice>
  </Dialog>;
}
