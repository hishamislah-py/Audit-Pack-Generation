/* Closing & Audit Pack tab. Renders the closure record of the case's reconciliation run (impl_20261120 CONTRACT.md):
   readiness (backend blockers as sentences), investigation status, selections (fixed choices, no free text),
   analyst decisions, the preview (PDF / HTML / JSON in same-origin iframes), HOLD / GENERATE with acknowledgement
   checkboxes, the verified final pack with downloads, closure history and token usage.
   Every action is the backend's `actions.*` ({enabled, reason}); every mutation sends the closure revision. */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, Panel, KV, Notice, Table, Segmented, Tabs, Empty, Skeleton, Dialog, Pill, Enum, Hash, Icon } from '../../ui/index.jsx';
import { fmtDateTime, sevLevel } from '../format.js';
import { closureFileUrl } from '../../services/dataService.js';
import { useClosure, useAiConfig, useJobWatch, ActBtn, AiState, DecisionCell, DeterministicSummary, PackStatusLine, ClosureError, itemText, scalarText } from './closure.jsx';

const INCLUSIONS = [['INCLUDED', 'Included'], ['NOT_INVESTIGATED', 'Not investigated'], ['EXCLUDED_BY_ANALYST', 'Excluded']];
const FILES = [['pdf', 'Final report (PDF)', 'filePdf'], ['html', 'Final report (HTML)', 'file'], ['json', 'Final pack (JSON)', 'fileOther'], ['manifest', 'Manifest', 'checklist'], ['provenance.pdf', 'Provenance supplement (PDF)', 'filePdf'], ['provenance.json', 'Provenance supplement (JSON)', 'fileOther']];
const fmtN = (n) => (n == null ? '—' : Number(n).toLocaleString('en-GB'));
const Sev = ({ value }) => <span className={'rf-sev rf-sev--' + sevLevel(value)}><span className="rf-sev__bars" aria-hidden="true"><i /><i /><i /></span>{value || '—'}</span>;

function Readiness({ cl, openExc }) {
  const r = (cl.review && cl.review.readiness) || {};
  const blockers = r.blockers || [], warnings = r.warnings || [], checklist = r.checklist || [];
  const ids = (cl.exceptions || []).map((e) => e.exception_id);
  const links = (text) => ids.filter((id) => String(text).indexOf(id) > -1).map((id) => <Button key={id} size="sm" variant="link" iconRight="arrowRight" onClick={() => openExc(id)}>{id}</Button>);
  const item = (x) => (typeof x === 'object' && x ? x : { label: String(x) });
  return <Panel title="Readiness" sub="From the backend. Generation is possible only when nothing blocks it.">
    <div className="rf-stack rf-stack--3">
      {checklist.length > 0 && <ul className="rfe-check">{checklist.map((x0, i) => { const x = item(x0); const ok = x.done === true || x.ok === true;
        return <li key={i} className={ok ? 'is-ok' : 'is-open'}><Icon name={ok ? 'check' : 'clock'} size={14} />
          {x.exception_id ? <><Button size="sm" variant="link" onClick={() => openExc(x.exception_id)}><span className="rf-mono">{x.exception_id}</span></Button>
            {x.inclusion && <Pill state={x.inclusion} />}{x.disposition && <Enum>{x.disposition}</Enum>}{x.exception_resolution && <span className="rfe-small rf-secondary">exception {String(x.exception_resolution).toLowerCase()}</span>}</>
            : <span>{x.label || x.text || x.title || JSON.stringify(x)}</span>}</li>; })}</ul>}
      {blockers.length ? <div><div className="rf-label">Blocking closure · {blockers.length}</div><ul className="rfe-check">{blockers.map((b, i) => <li key={i} className="is-bad"><Icon name="alert" size={14} /><span>{itemText(b)}</span>{links(itemText(b))}</li>)}</ul></div>
        : <Notice tone="success" compact>Nothing blocks closure.</Notice>}
      {warnings.length > 0 && <div><div className="rf-label">Warnings · {warnings.length}</div><ul className="rfe-check">{warnings.map((w, i) => <li key={i} className="is-warn"><Icon name="info" size={14} /><span>{itemText(w)}</span>{links(itemText(w))}</li>)}</ul></div>}
    </div>
  </Panel>;
}

function Investigations({ cl, openExc }) {
  const ex = cl.exceptions || [];
  return <Panel flush title={'Investigation status · ' + ex.length + ' exception' + (ex.length === 1 ? '' : 's')} sub="AI investigations start automatically after reconciliation; each AI finding needs an analyst decision.">
    {ex.length ? <Table dense caption="Investigation status per exception" columns={[{ key: 'id', label: 'Exception' }, { key: 'sev', label: 'Severity' }, { key: 'cat', label: 'Finding' }, { key: 'ai', label: 'AI investigation' }, { key: 'n', label: 'Attempts', cls: 'is-num' }, { key: 'dec', label: 'Decision' }]}
      rows={ex.map((e) => ({ key: e.exception_id, onClick: () => openExc(e.exception_id), cells: {
        id: <span className="rf-mono rf-strong">{e.exception_id}</span>, sev: <Sev value={e.severity} />,
        cat: <><span className="rf-cell-main">{e.category || e.root_cause}</span>{e.missing_evidence && <span className="rf-cell-sub">missing evidence{e.account_id ? ' · ' + e.account_id : ''}</span>}{!e.missing_evidence && e.account_id && <span className="rf-cell-sub">{e.account_id}</span>}</>,
        ai: <AiState state={e.ai_state} />, n: e.attempts != null ? (Array.isArray(e.attempts) ? e.attempts.length : e.attempts) : null, dec: <DecisionCell e={e} /> } }))} />
      : <div style={{ padding: 16 }}><Empty icon="check" title="No exceptions">The reconciliation raised no exceptions. No AI investigation or decision is needed; the closing summary is not required.</Empty></div>}
  </Panel>;
}

function Selections({ cl, busy, onSet, openExc }) {
  const rv = cl.review || {};
  const sel = rv.selections || [];
  const a = cl.actions || {};
  const ex = cl.exceptions || [];
  if (!ex.length) return null;
  const cur = (id) => (sel.find((s) => s.exception_id === id) || {}).inclusion || null;
  const explicit = (id) => !!(sel.find((s) => s.exception_id === id) || {}).explicit;
  const can = a.set_selections && a.set_selections.enabled;
  return <Panel flush title="Selections" sub="What the final pack says about each exception. Fixed choices; the backend adds fixed wording for an exclusion (O4).">
    {!rv.review_id && <div style={{ padding: '12px 16px 0' }}><Notice tone="info" compact>Open the closing review to record selections.</Notice></div>}
    {rv.review_id && !can && <div style={{ padding: '12px 16px 0' }}><Notice tone="attention" compact>{(a.set_selections && a.set_selections.reason) || 'Selections cannot be changed now.'}</Notice></div>}
    <Table dense caption="Selections" columns={[{ key: 'id', label: 'Exception' }, { key: 'ai', label: 'AI' }, { key: 'dec', label: 'Decision' }, { key: 'sel', label: 'Inclusion' }, { key: 'src', label: '' }]}
      rows={ex.map((e) => ({ key: e.exception_id, cells: {
        id: <Button size="sm" variant="link" onClick={() => openExc(e.exception_id)}><span className="rf-mono">{e.exception_id}</span></Button>, ai: <AiState state={e.ai_state} />, dec: <DecisionCell e={e} />,
        sel: can && !busy ? <Segmented items={INCLUSIONS.filter((x) => x[0] !== 'INCLUDED' || e.investigation_id)} active={cur(e.exception_id)} onChange={(v) => { if (v !== cur(e.exception_id)) onSet(e, v); }} /> : cur(e.exception_id) ? <Pill state={cur(e.exception_id)} /> : <span className="rf-muted">Not set</span>, src: <span className="rfe-small rf-muted">{explicit(e.exception_id) ? 'set by analyst' : 'default'}</span> } }))} />
  </Panel>;
}

function Decisions({ cl }) {
  const ex = cl.exceptions || [];
  if (!ex.length) return null;
  const acc = ex.filter((e) => e.analyst_decision === 'ACCEPT').length, rej = ex.filter((e) => e.analyst_decision === 'REJECT').length;
  return <Panel title="Analyst decisions" sub="Decisions apply to AI findings and never change the engine exception status.">
    <div className="rfe-kvrow"><div className="rfe-num"><b>{acc}</b><span>AI findings accepted</span></div><div className="rfe-num"><b>{rej}</b><span>AI findings rejected</span></div><div className="rfe-num"><b>{ex.length - acc - rej}</b><span>No decision</span></div></div>
  </Panel>;
}

function PreviewFrames({ ref_, preview }) {
  const [tab, setTab] = React.useState('pdf');
  const v = '?preview=' + encodeURIComponent(preview.preview_id || '');
  const url = closureFileUrl(ref_, 'review/preview.' + tab) + v;
  return <div className="rf-stack rf-stack--3">
    <div className="rf-row rf-row--wrap" style={{ gap: 8 }}><Tabs items={[['pdf', 'PDF'], ['html', 'HTML'], ['json', 'JSON']]} active={tab} onChange={setTab} /><span className="rf-spacer" />
      <a className="rf-btn rf-btn--quiet rf-btn--sm" href={url} target="_blank" rel="noopener"><Icon name="external" /><span>Open in a new tab</span></a></div>
    <iframe key={tab + preview.preview_id} className="rfe-frame" title={'Closing preview ' + tab.toUpperCase()} src={url} sandbox={tab === 'html' ? '' : undefined} />
  </div>;
}

function FinalPack({ c, cl }) {
  const fp0 = cl.final_pack;
  const q = useQuery(fp0 ? 'finalpack:' + c.case_ref + ':' + fp0.final_pack_id + ':' + fp0.status + ':' + String(fp0.verified) + ':' + (fp0.problems || []).length : null, (svc) => svc.getFinalPack(c.case_ref));
  if (!fp0) return null;
  const f = q.data || fp0;
  // Integrity (D8): both the closure view and /final-pack recompute it from the files; "Verified" only when every
  // source says so, never from a stale flag. A generated pack whose files no longer verify is an integrity failure.
  const integrityFailed = fp0.status === 'GENERATED' && (fp0.verified === false || fp0.integrity === 'FAILED' || (q.data && (q.data.verified === false || q.data.integrity === 'FAILED')));
  const verified = !integrityFailed && fp0.verified === true && (!q.data || q.data.verified === true);
  const failed = integrityFailed || f.status === 'GENERATION_FAILED' || f.status === 'FAILED' || f.verified === false;
  const problems = (q.data && q.data.problems && q.data.problems.length ? q.data.problems : fp0.problems) || [];
  const failTitle = integrityFailed ? 'Integrity check failed' : f.verified === false ? 'Verification failed' : 'Generation failed';
  const ref = c.case_ref;
  const LABEL = Object.fromEntries(FILES.map((x) => [x[0], x]));
  const files = (Array.isArray(f.files) && f.files.length && typeof f.files[0] === 'object'
    ? f.files.map((x) => ({ key: x.key, name: x.name, sha256: x.sha256, url: x.url || closureFileUrl(ref, 'final-pack/' + x.key) }))
    : FILES.map((x) => ({ key: x[0], url: closureFileUrl(ref, 'final-pack/' + x[0]) })))
    .map((x) => Object.assign(x, { label: (LABEL[x.key] || [0, x.key])[1], icon: (LABEL[x.key] || [0, 0, 'file'])[2] }));
  return <Panel title="Final audit pack" sub={<span className="rf-mono">{f.final_pack_id}</span>}
    actions={verified ? <span className="rfe-verified"><Icon name="seal" size={14} />Verified</span> : failed ? <Pill state="GENERATION_FAILED" label={failTitle} /> : <Pill state={f.status || 'GENERATING'} />}>
    <div className="rf-stack rf-stack--3">
      {q.error && <Notice tone="danger" compact title="Final pack details could not be loaded">{q.error.message}</Notice>}
      {failed && <Notice tone="danger" title={failTitle}>{problems.length ? <ul className="rfe-list">{problems.map((p, i) => <li key={i}>{itemText(p)}</li>)}</ul> : 'The backend reported no detail.'} {integrityFailed ? 'The files on disk no longer match the hashes recorded when the pack was generated. Downloads are refused; nothing is repaired, overwritten or re-signed.' : 'A pack that does not verify is never treated as generated.'}</Notice>}
      <KV pairs={[['Status', <Pill state={f.status} />], ['Integrity', integrityFailed ? <Pill state="GENERATION_FAILED" label="Integrity check failed" /> : verified ? 'Files match the hashes recorded at generation' + (f.integrity_checked_at ? ' (checked ' + fmtDateTime(f.integrity_checked_at) + ')' : '') : '—'], ['Authorised by', f.authorised_by || '—'], ['Generated', fmtDateTime(f.generated_at)]]} />
      {verified && <ul className="rfe-downloads">{files.map((x) => <li key={x.key}><Icon name={x.icon} size={14} /><span>{x.label}</span>{x.name && <span className="rf-mono rf-muted rfe-small">{x.name}</span>}{x.sha256 && <Hash sha={x.sha256} />}<span className="rf-spacer" />
        <a className="rf-btn rf-btn--quiet rf-btn--sm" href={x.url} target="_blank" rel="noopener"><span>Open</span></a>
        <a className="rf-btn rf-btn--secondary rf-btn--sm" href={x.url + (x.url.indexOf('?') > -1 ? '&' : '?') + 'download=1'} download={x.name || true}><span>Download</span></a></li>)}</ul>}
    </div>
  </Panel>;
}

function History({ c }) {
  const q = useQuery('closurehist:' + c.case_ref, (svc) => svc.getClosureHistory(c.case_ref));
  const d = q.data;
  const ev = (d && (d.events || (Array.isArray(d) ? d : []))) || [];
  return <Panel flush title={'Closure history' + (d ? ' · ' + ev.length : '')} sub="Audit events from the case's hash-chained audit log">
    {q.error ? <div style={{ padding: 16 }}><Notice tone="danger" compact>{q.error.message}</Notice></div> : !d ? <div style={{ padding: 16 }}><span className="rf-skel" style={{ width: '60%' }} /></div>
      : ev.length ? <Table dense caption="Closure history" maxHeight={420} columns={[{ key: 'at', label: 'Time' }, { key: 't', label: 'Event' }, { key: 'by', label: 'Actor' }, { key: 'd', label: 'Detail' }]}
        rows={ev.slice().reverse().map((e, i) => { const det = e.details || {}; return { key: e.event_id || i, cells: { at: <span className="rf-nowrap">{fmtDateTime(e.at || e.created_at)}</span>, t: <Enum>{e.event_type || e.type}</Enum>, by: e.actor_id || e.actor || det.actor, d: <span className="rf-mono rfe-small rf-wrap">{['exception_id', 'investigation_id', 'review_id', 'preview_id', 'failure_id', 'final_pack_id', 'pack_id', 'job_id'].filter((k) => det[k]).map((k) => det[k]).join(' · ') || (e.reason ? itemText(e.reason) : '')}</span> } }; })} />
        : <div style={{ padding: 16 }} className="rf-help">No closure events yet.</div>}
  </Panel>;
}

function Usage({ u, ai }) {
  if (!u) return null;
  return <Panel title="AI token usage" sub="All AI calls for this closure">
    <KV pairs={[['Calls', fmtN(u.calls)], ['Input tokens', fmtN(u.input_tokens)], ['Cached input tokens', fmtN(u.cached_input_tokens)], ['Output tokens', fmtN(u.output_tokens)],
      ['Cost', u.cost != null ? scalarText(u.cost) : u.cost_note || 'cost unavailable (no price configured)'],
      ['Provider', ai ? [ai.provider, ai.model].filter(Boolean).join(' · ') || '—' : '—']]} />
  </Panel>;
}

export default function ClosingTab({ c, app, nav, store }) {
  const ref = c.case_ref;
  const jobs = useJobWatch(ref);
  const q = useClosure(c, jobs.running.length > 0);
  const ai = useAiConfig();
  const m = useMutation();
  const [dlg, setDlg] = React.useState(null);
  const [ack, setAck] = React.useState(false);
  const [ackSum, setAckSum] = React.useState(false);
  const cl = q.data;
  const pvId = cl && cl.review && cl.review.current_preview ? cl.review.current_preview.preview_id : null;
  React.useEffect(() => { setAck(false); setAckSum(false); }, [pvId]); // an acknowledgement belongs to one preview
  if (c.status !== 'COMPLETED') return <div className="rf-workspace"><Panel><Empty icon="lock" title="Closing starts after reconciliation" action={<Button icon="arrowRight" onClick={() => nav('cases/' + ref + '/recon')}>Reconciliation</Button>}>The audit pack, AI investigations, the closing review and the final PDF become available when a reconciliation run completes.</Empty></Panel></div>;
  if (!cl) return <div className="rf-workspace">{q.error ? <ClosureError err={q.error} reload={q.reload} /> : <Skeleton rows={6} />}</div>;

  const a = cl.actions || {};
  const rv = cl.review || {};
  const pv = rv.current_preview || null;
  const unavailable = cl.pack && cl.pack.status === 'UNAVAILABLE';
  const lock = unavailable ? 'Audit pack unavailable: ' + (cl.pack.reason || 'no reason reported') : cl.frozen ? 'Closure is frozen: the final pack has been generated.' : null;
  const rev = cl.revision;
  const openExc = (id) => nav('cases/' + ref + '/recon/' + encodeURIComponent(cl.recon_run_id) + '/' + encodeURIComponent(id));
  const needAi = a.preview && a.preview.requires_confirm_ai != null ? !!a.preview.requires_confirm_ai : (cl.exceptions || []).length > 0;
  const summaryUnavailable = pv && pv.closing_summary_status === 'UNAVAILABLE';
  const aiCfg = ai.data || cl.ai || {};

  const run = async (fn, opts) => m.run(fn, Object.assign({ inline: false }, opts));
  const openReview = () => run((svc) => svc.openClosingReview(ref, { expected_revision: rev }), { success: 'Closing review opened' });
  const setSel = (e, inclusion) => {
    // The backend merges selections by exception: only the changed one is sent.
    const next = Object.assign({ exception_id: e.exception_id, inclusion }, inclusion === 'INCLUDED' && e.investigation_id ? { investigation_id: e.investigation_id } : {});
    return run((svc) => svc.setClosingSelections(ref, { selections: [next], expected_revision: rev }), { success: e.exception_id + ' · ' + inclusion.replace(/_/g, ' ').toLowerCase() });
  };
  const preview = async (confirmAi) => {
    const r = await m.run((svc) => svc.requestClosingPreview(ref, { confirm_ai: !!confirmAi, expected_revision: rev }), { inline: !!dlg });
    if (!r) return;
    setDlg(null);
    if (r.reused) store.toast('info', 'Preview reused: the inputs have not changed since the current preview');
    else if (r.job_id) { store.toast('success', 'Preview requested'); jobs.watch(r.job_id, 'Closing preview'); }
  };
  const decide = async (decision) => {
    const r = await m.run((svc) => svc.decideClosingReview(ref, { decision, acknowledgement_accepted: ack, acknowledged_summary_unavailable: ackSum, snapshot_sha256: pv ? pv.snapshot_sha256 : null, expected_revision: rev }), { inline: !!dlg, success: decision === 'HOLD' ? 'Closing review on hold' : 'Final pack generation started' });
    if (!r) return;
    setDlg(null);
    const jid = r.job_id || (r.decision && r.decision.job_id);
    if (jid) jobs.watch(jid, 'Final pack generation');
  };
  const genBlock = !pv ? 'Generate a preview first.' : !ack ? 'Tick the acknowledgement first.' : summaryUnavailable && !ackSum ? 'Acknowledge that the closing summary is unavailable.' : null;

  return <div className="rf-workspace rfe-closing">
    <div className="rf-row rf-row--wrap" style={{ gap: 10 }}>
      {cl.state === 'INTEGRITY_FAILED' ? <Pill state="GENERATION_FAILED" size="lg" label="Integrity check failed" /> : <Pill state={cl.state} size="lg" />}{cl.frozen && <Pill state="ACTIVE_LOCKED" label="Frozen" />}
      <span className="rfe-small rf-secondary">Run <span className="rf-mono">{cl.recon_run_id}</span> · snapshot <span className="rf-mono">{cl.snapshot_id}</span> · revision {rev}</span>
      <span className="rf-spacer" />{(q.refreshing || jobs.running.length > 0) && <span className="rf-stale"><span className="rf-live" />{jobs.running.length ? jobs.running.map((j) => j.label).join(', ') + ' running' : 'Refreshing'}</span>}
      <Button size="sm" icon="refresh" onClick={q.reload}>Refresh</Button>
    </div>
    {q.error && <Notice tone="danger" compact title="Refresh failed">{q.error.message}</Notice>}
    {unavailable && <Notice tone="danger" title="Audit pack unavailable">
      {cl.pack.reason || 'The backend reported no reason.'}
      <div style={{ marginTop: 6 }}>Closure cannot continue: the audit pack is the basis for AI investigations, the closing review and the final PDF. The reconciliation results stay as they are; nothing is mocked or worked around. The reasons are listed under Readiness.</div>
    </Notice>}
    {cl.last_generation_failure && !cl.frozen && <Notice tone="danger" title="Final pack generation failed">{itemText(cl.last_generation_failure.error || cl.last_generation_failure)}</Notice>}
    {cl.frozen && (cl.state === 'INTEGRITY_FAILED' || (cl.final_pack && cl.final_pack.verified === false)
      ? <Notice tone="danger" title="Integrity check failed">The final pack was generated, but its files no longer match the hashes recorded at generation: {((cl.final_pack && cl.final_pack.problems) || []).map(itemText).join('; ') || 'no detail reported'}. Downloads are refused. Closure stays read-only; nothing is repaired, overwritten or re-signed.</Notice>
      : cl.frozen && <Notice tone="locked" title="Closure frozen">The final pack has been generated and verified. Closure is read-only.</Notice>)}
    <div className="rfe-grid">
      <div className="rf-stack">
        <DeterministicSummary s={cl.deterministic_summary} />
        <PackStatusLine pack={cl.pack} />
        <Readiness cl={cl} openExc={openExc} />
        <Investigations cl={cl} openExc={openExc} />
        <Selections cl={cl} busy={m.busy} onSet={setSel} openExc={openExc} />
        <Decisions cl={cl} />
        <Panel title="Closing review" sub={rv.review_id ? <span className="rf-mono">{rv.review_id}{rv.status ? ' · ' + rv.status : ''}</span> : 'Not opened'}
          actions={!rv.review_id ? <ActBtn a={a.open_review} label="Open closing review" variant="primary" icon="checklist" onClick={openReview} loading={m.busy} extraReason={lock} /> : null}>
          <div className="rf-stack rf-stack--3">
            <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>
              <ActBtn a={a.preview} label={pv ? 'Generate preview again' : 'Generate preview'} variant={pv ? 'secondary' : 'primary'} icon="eye" extraReason={lock} loading={m.busy && !dlg}
                onClick={() => (needAi ? (m.reset(), setDlg('preview')) : preview(false))} />
              {pv && <span className="rfe-small rf-secondary">Current preview <span className="rf-mono">{pv.preview_id}</span>{pv.reused ? <> · <span className="rfe-badge">reused</span></> : null}{pv.closing_summary_status ? <> · closing summary <Enum>{pv.closing_summary_status}</Enum></> : null}{pv.stale ? <> · <span className="rf-tone-attention">stale: generate again</span></> : null}</span>}
            </div>
            {pv && pv.snapshot_sha256 && <KV pairs={[['Preview snapshot', <Hash sha={pv.snapshot_sha256} />], ['Created', fmtDateTime(pv.created_at)]]} />}
            {rv.last_preview_failure && (!pv || String(rv.last_preview_failure.at || '') > String(pv.created_at || '')) && <Notice tone="danger" compact title="The last preview was refused">
              {itemText(rv.last_preview_failure.error)}
              {(rv.last_preview_failure.rejected_text_leaks || []).length > 0 && <ul className="rfe-list">{rv.last_preview_failure.rejected_text_leaks.map((k, i) => <li key={i}><span className="rf-mono">{k.investigation_id}</span> {k.rejected_source}: “{k.text}” found at <span className="rf-mono">{(k.found_at || []).join(', ')}</span></li>)}</ul>}
              <div className="rfe-small rf-secondary">Recorded as <span className="rf-mono">{rv.last_preview_failure.failure_id}</span> in the closure history.</div>
            </Notice>}
            {summaryUnavailable && <Notice tone="attention" compact title="AI closing summary unavailable">{pv.closing_summary_unavailable_reason || 'The backend reported no reason.'}</Notice>}
            {pv ? <PreviewFrames ref_={ref} preview={pv} /> : <div className="rf-help">No preview yet. The preview shows exactly what the final pack will contain.</div>}
            {pv && !cl.frozen && <div className="rfe-acks">
              <label className="rfe-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>I have reviewed this preview and authorise the final audit pack on this basis.</span></label>
              {summaryUnavailable && <label className="rfe-ack"><input type="checkbox" checked={ackSum} onChange={(e) => setAckSum(e.target.checked)} /><span>I acknowledge that the AI closing summary is unavailable and the pack will state this.</span></label>}
            </div>}
            <div className="rf-row rf-row--wrap" style={{ gap: 8 }}>
              <ActBtn a={a.hold} label="Hold" icon="pause" extraReason={lock} onClick={() => { m.reset(); setDlg('hold'); }} />
              <ActBtn a={a.generate} label="Generate final pack" variant="primary" icon="seal" extraReason={lock || genBlock} onClick={() => { m.reset(); setDlg('generate'); }} />
            </div>
          </div>
        </Panel>
        <FinalPack c={c} cl={cl} />
      </div>
      <aside className="rf-stack">
        <Panel title="AI" sub="Server configuration">
          <KV pairs={[['Available', aiCfg.available ? 'Yes' : 'No'], ['Provider', aiCfg.provider || '—'], ['Model', aiCfg.model || '—']].concat(aiCfg.problem ? [['Problem', aiCfg.problem]] : [])} />
        </Panel>
        <Usage u={cl.usage} ai={aiCfg} />
        <History c={c} />
      </aside>
    </div>

    {dlg === 'preview' && <div className="rfd-layer"><Dialog eyebrow={ref + ' · Closing preview'} title="Generate the preview with an AI closing summary?" error={m.error} onClose={m.busy ? undefined : () => setDlg(null)}
      foot={<><Button onClick={() => setDlg(null)} disabled={m.busy}>Cancel</Button><Button variant="primary" loading={m.busy} onClick={() => preview(true)}>{aiCfg.available === false ? 'Generate without AI summary' : 'Confirm and generate'}</Button></>}>
      <div className="rf-stack rf-stack--3">
        <KV pairs={[['Provider', aiCfg.provider || '—'], ['Model', aiCfg.model || '—'], ['Stored by provider', aiCfg.store === false || aiCfg.store == null ? 'No (store: false)' : String(aiCfg.store)]]} />
        <Notice tone="info" compact title="Data notice">{aiCfg.data_notice || 'Raw evidence from this case is sent to the AI provider for the closing summary (approved for this POC; store: false).'}</Notice>
        {aiCfg.available === false && <Notice tone="attention" compact title="AI unavailable">{aiCfg.problem || 'No AI provider is configured.'} The closing summary will be shown as unavailable and you will need to acknowledge that before generating.</Notice>}
        <div className="rf-help">If nothing has changed since the current preview, the backend reuses it and no AI call is made.</div>
      </div></Dialog></div>}
    {(dlg === 'hold' || dlg === 'generate') && <div className="rfd-layer"><Dialog eyebrow={ref + ' · Closing review'} error={m.error} onClose={m.busy ? undefined : () => setDlg(null)}
      title={dlg === 'hold' ? 'Put the closing review on hold?' : 'Generate the final audit pack?'}
      foot={<><Button onClick={() => setDlg(null)} disabled={m.busy}>Cancel</Button><Button variant="primary" icon={dlg === 'hold' ? 'pause' : 'seal'} loading={m.busy} onClick={() => decide(dlg === 'hold' ? 'HOLD' : 'GENERATE')}>{dlg === 'hold' ? 'Hold' : 'Generate final pack'}</Button></>}>
      {dlg === 'hold' ? <div className="rf-help">Records HOLD with fixed wording (no free-text reason, O4). You can generate later.</div>
        : <div className="rf-stack rf-stack--3"><KV pairs={[['Preview', pv ? <span className="rf-mono">{pv.preview_id}</span> : '—'], ['Snapshot', pv && pv.snapshot_sha256 ? <Hash sha={pv.snapshot_sha256} /> : '—']]} />
          <div className="rf-help">The final pack is generated from this preview, verified, and the closure is then frozen. You are recorded as the person who authorised it.</div></div>}
    </Dialog></div>}
  </div>;
}
