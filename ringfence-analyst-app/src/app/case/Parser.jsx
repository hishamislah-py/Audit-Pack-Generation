/* Case workspace · Smart Parser tab (simplified flow).
   One phase covers parsing, mapping review and validation. The screen shows, top to bottom:
     1. what happens next: the items that need the analyst (mapping review, failed validation checks, missing or
        unreadable evidence) or, when everything passed, a single "Start reconciliation" button;
     2. the files of the run and their outcome (the stage list and the audit log are not shown here;
        the full audit trail stays in Activity).
   Runs from case.runs (contract §3.3), the run detail from GET /api/cases/{ref}/runs/{run_id} (§3.5),
   polled while the run is PROCESSING (§5). Nothing advances on a client timer. */
import React from 'react';
import { Button, WithReason, Panel, Notice, Table, Empty, Pill, Glyph, StageStrip, Readiness } from '../../ui/index.jsx';
import { useQuery } from '../hooks.js';
import { fmtDateTime, catTitle, STAGE_STATE, unreadableOf, missingNotUnreadable } from '../format.js';
import StartReconButton, { reconAvailability } from './StartRecon.jsx';

function Act({ a, label, onClick, variant = 'secondary', size = 'sm', icon }) {
  const ok = !!(a && a.enabled);
  const btn = <Button variant={variant} size={size} icon={icon} disabled={!ok} onClick={ok ? onClick : undefined}>{label}</Button>;
  return ok ? btn : <WithReason reason={(a && a.reason) || 'Not available for this case.'}>{btn}</WithReason>;
}
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many || one + 's');

/* What the analyst has to do before reconciliation, or the Start reconciliation button when nothing is left. */
function NextStep({ c, nav, openAction, running }) {
  const ref = c.case_ref, A = c.actions || {};
  if (running) return null;
  if (c.activation) {
    // Everything passed and the backend started reconciliation by itself (or the analyst did): point to it.
    const rec = (c.progress && c.progress.reconciliation) || {};
    const live = rec.state === 'RUNNING' || rec.state === 'QUEUED';
    if (rec.state === 'COMPLETED') return <Readiness tone="ready" title={'Reconciliation complete' + (rec.case_status ? ' · ' + rec.case_status.replace(/_/g, ' ') : '')}
      sub={'All checks passed and reconciliation ran on the sealed evidence' + (rec.exceptions ? ' · ' + rec.exceptions + ' exception' + (rec.exceptions === 1 ? '' : 's') : '') + '.'}
      headAction={<Button variant="primary" icon="arrowRight" onClick={() => nav('cases/' + ref + '/recon')}>View result</Button>} />;
    if (c.status === 'COMPLETED') return null;
    return <Readiness tone="ready" title={live ? 'All checks passed · reconciliation is running' : 'All checks passed · reconciliation started'}
      sub="Smart Parsing is complete. The evidence is sealed and reconciliation runs on it."
      headAction={<Button variant="primary" icon="arrowRight" onClick={() => nav('cases/' + ref + '/recon')}>View reconciliation</Button>} />;
  }
  const o = c.outstanding || {};
  const v = (c.progress && c.progress.validation) || { state: 'NOT_RUN' };
  const lv = c.package && c.package.latest_validation;
  const failed = v.current !== false && lv ? lv.checks.filter((k) => !k.passed) : [];
  const items = [];
  (o.mapping_decisions || []).forEach((x) => items.push({ title: 'Confirm column mapping · ' + x.file_name, detail: plural(x.outstanding, 'decision') + ' outstanding of ' + x.total + ' · ' + x.category,
    action: <Button size="sm" variant="primary" onClick={() => nav('cases/' + ref + '/review/' + x.file_version_id)}>Review mapping</Button> }));
  failed.forEach((k) => items.push({ title: 'Validation check failed · ' + k.check_id + ' ' + k.name, detail: k.detail, checks: [k.check_id] }));
  missingNotUnreadable(o).forEach((x) => items.push({ title: 'Missing required evidence · ' + x.category + ' ' + (x.title || ''), detail: 'Upload a ' + (x.format || '') + ' file.',
    action: <Button size="sm" onClick={() => nav('cases/' + ref + '/evidence?upload=' + encodeURIComponent(x.category))}>Upload</Button> }));
  (o.files_requiring_replacement || []).forEach((x) => items.push({ title: 'Correction required · ' + x.category + ' v' + x.version, detail: x.detail, checks: [x.cause, x.version_status].filter(Boolean),
    action: <Button size="sm" onClick={() => nav('cases/' + ref + '/evidence')}>Evidence</Button> }));
  (o.other || []).filter((x) => x.kind === 'RETRY_FROM_BEGINNING').forEach((x) => items.push({ title: 'Retry from Beginning', detail: x.detail,
    action: A.retry_from_beginning && A.retry_from_beginning.enabled ? <Button size="sm" icon="refresh" onClick={() => openAction('retry')}>Retry…</Button> : null }));

  const av = reconAvailability(c);
  if (av.enabled) {
    return <Readiness tone="ready" title="All checks passed · ready for reconciliation"
      sub={(lv ? lv.checks.length + ' of ' + lv.checks.length + ' validation checks passed' : 'Validation passed') + (v.at ? ' · ' + fmtDateTime(v.at) : '')}
      headAction={<StartReconButton c={c} nav={nav} />} />;
  }
  if (items.length) return <Readiness tone="blocked" title={plural(items.length, 'item') + ' need your attention'} sub="Reconciliation can start once these are resolved." items={items} />;
  if (v.state === 'RUNNING') return <Notice tone="info" title="Checking the evidence">Validation is running on the processed files.</Notice>;
  return null;
}

export default function ParserTab({ c, app, route, nav, openAction, store }) {
  const ref = c.case_ref, A = c.actions || {};
  const runs = c.runs || [];
  const latestId = (c.current_run && c.current_run.run_id) || (runs.length ? runs[runs.length - 1].run_id : null);
  const runId = route.sub || latestId;
  const sel = runs.find((r) => r.run_id === runId) || null;
  const q = useQuery(sel ? 'run:' + ref + ':' + runId : null, (svc) => svc.getRun(ref, runId), { poll: sel && sel.status === 'PROCESSING' ? store.POLL.case : null });

  if (!runs.length) {
    return <div className="rf-workspace"><Panel><Empty icon="parser" title="Smart Parsing has not started"
      action={c.status === 'WAITING' ? <Act a={A.start} label="Start Smart Parsing" variant="primary" size={null} icon="play" onClick={() => openAction('start')} /> : null}>
      Starting reads the original ZIP <span className="rf-mono">{c.zip && c.zip.filename}</span> and lists every file here with its result.</Empty></Panel></div>;
  }
  const d = q.data && q.data.run_id === runId ? q.data : null;
  const isLatest = sel && sel.run_id === latestId;
  const running = !!(sel && sel.status === 'PROCESSING');
  const stages = (d && d.stages) || [];
  const stageStates = stages.map((s) => STAGE_STATE[s.status] || 'pending');
  const stagesDone = stageStates.filter((s) => s === 'done' || s === 'attention' || s === 'skipped').length;
  const job = (d && d.intake_job) || (sel && sel.intake_job) || null;
  const files = (job && job.files) || [];
  const ncf = (sel && sel.not_carried_forward) || [];
  const unreadable = unreadableOf((d && d.unreadable_entries) || (sel && sel.unreadable_entries) || (isLatest ? (c.outstanding || {}).unreadable_members : null));
  const okCount = files.filter((f) => f.outcome && typeof f.outcome === 'object' ? !f.outcome.error && !f.outcome.refused_reason && f.outcome.version_status === 'VALIDATED' : f.outcome === 'VALIDATED').length;

  return <div className="rf-workspace rfb-run">
    {c.deferring && <Notice tone="attention" title="Deferral requested">The running job continues to the end; the case becomes Pending when it finishes. Nothing new starts meanwhile.</Notice>}
    {!sel && <Notice tone="attention" title="Run not found">{runId} is not a run of this case.</Notice>}
    {sel && sel.failure && <Notice tone="danger" title={'Run ' + sel.run_no + ' failed · ' + sel.failure.code}
      actions={isLatest ? <Act a={A.retry_from_beginning} label="Retry from Beginning" variant="primary" icon="refresh" onClick={() => openAction('retry')} /> : null}>
      {sel.failure.message}{sel.failure.stage ? ' Stage: ' + sel.failure.stage + '.' : ''} {fmtDateTime(sel.failure.at)}.
      {isLatest ? ' Retry from Beginning starts a new run from the original ZIP; files uploaded to this run are not carried forward.' : ' A later run replaced this one.'}
    </Notice>}
    {unreadable.length > 0 && <Notice tone="attention" title={unreadable.length + ' file(s) in the original ZIP could not be read'}
      actions={isLatest ? <Act a={A.upload_evidence} label="Upload corrected file" variant="primary" icon="upload" onClick={() => nav('cases/' + ref + '/evidence?upload=')} /> : null}>
      The rest of the ZIP was processed. For each file below, upload a corrected file:
      <ul className="rfb-plain">{unreadable.map((u, i) => <li key={i} data-unreadable={u.name}>File <span className="rf-mono">{u.name}</span> could not be read{u.error ? ': ' + u.error : ''}</li>)}</ul>
    </Notice>}
    {ncf.length > 0 && <Notice tone="attention" title="Not carried forward from the failed run">
      This retry used the original ZIP only. Upload these files again if they are still needed:
      <ul className="rfb-plain">{ncf.map((j, i) => (j.files || []).map((f, k) => <li key={i + '-' + k}><span className="rf-mono">{f.name}</span> · {f.category} {catTitle(app, f.category)}</li>))}</ul>
    </Notice>}
    {isLatest && <NextStep c={c} nav={nav} openAction={openAction} running={running} />}

    {sel && <Panel title={'Uploaded files' + (files.length ? ' · ' + files.length : '')}
      sub={running ? 'Processing… ' + (stages.length ? stagesDone + ' of ' + stages.length + ' steps done' : '') : files.length ? okCount + ' of ' + files.length + ' validated · run ' + sel.run_no + ' · ' + fmtDateTime(sel.finished_at || sel.started_at) : null}
      actions={<Pill state={sel.status} />} flush>
      {running && stages.length > 0 && <div style={{ padding: '12px 16px 0' }}><StageStrip states={stageStates} /></div>}
      {q.error && !d ? <div style={{ padding: 16 }}><Notice tone="danger" compact title="Could not load the run">{q.error.message}</Notice></div>
        : files.length ? <Table dense caption="Files in this run" columns={[{ key: 'name', label: 'File' }, { key: 'cat', label: 'Category' }, { key: 'out', label: 'Result', cls: 'is-tight' }]}
          rows={files.map((f, i) => { const cat = f.category || (f.outcome && typeof f.outcome === 'object' && f.outcome.evidence_category) || f.declared_category || null; return { key: i, cells: {
            name: <span className="rf-mono rfb-small rfb-wrap">{f.name}</span>,
            cat: cat ? <span className="rfb-small"><span className="rf-mono">{cat}</span> <span className="rf-muted">{catTitle(app, cat)}</span></span> : <span className="rf-muted rfb-small">—</span>,
            out: f.state === 'running' || f.state === 'processing' ? <span className="rf-row rfb-small"><span className="rf-tone-progress"><Glyph name="progress" size={10} /></span>processing</span>
              : f.outcome ? (typeof f.outcome !== 'object' ? <Pill state={f.outcome} /> : f.outcome.error ? <Pill state="FAILED" label="Error" title={f.outcome.error} /> : f.outcome.refused_reason ? <Pill state="REJECTED" label="Refused" title={f.outcome.refused_reason} /> : <Pill state={f.outcome.version_status} />)
              : <span className="rf-muted rfb-small">{f.state}</span> } }; })} />
        : <div style={{ padding: '12px 16px' }} className="rf-muted">{!d ? 'Loading…' : sel.status === 'FAILED' ? 'No file was registered by this run.' : 'Files appear as soon as they are identified.'}</div>}
    </Panel>}

    {runs.length > 1 && <Panel title="Earlier runs" sub={runs.length + ' runs · newest first'} flush>
      <Table dense caption="Smart Parser runs" columns={[{ key: 'run', label: 'Run' }, { key: 'status', label: 'Status', cls: 'is-tight' }]}
        rows={runs.slice().reverse().map((r) => ({ key: r.run_id, selected: r.run_id === runId, onClick: () => nav('cases/' + ref + '/parser/' + encodeURIComponent(r.run_id)), cells: {
          run: <><span className="rf-cell-main">Run {r.run_no}{r.retry_of ? ' · retry' : ''}</span><span className="rf-cell-sub">Started {fmtDateTime(r.started_at)}{r.failure ? ' · ' + r.failure.code : ''}</span></>,
          status: <Pill state={r.status} /> } }))} />
    </Panel>}
  </div>;
}
