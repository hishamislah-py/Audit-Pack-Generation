/* Case workspace · Smart Parser tab (S05 / S06).
   Runs from case.runs (contract §3.3); stages, events and llm_mode from GET /api/cases/{ref}/runs/{run_id}
   (§3.5), polled while the run is PROCESSING (§5). Stages are shown exactly as the backend reports them:
   nothing advances on a client timer. PROCESSING is displayed as Running; there is no paused run (§7). */
import React from 'react';
import { Button, WithReason, Panel, KV, Notice, Table, Empty, Pill, Enum, Ref, Stages, StageStrip, RunLog, Glyph } from '../../ui/index.jsx';
import { useQuery } from '../hooks.js';
import { fmtDateTime, fmtTimeSec, catTitle, STAGE_STATE, STAGE_LABEL, unreadableOf } from '../format.js';

function Act({ a, label, onClick, variant = 'secondary', size = 'sm', icon }) {
  const ok = !!(a && a.enabled);
  const btn = <Button variant={variant} size={size} icon={icon} disabled={!ok} onClick={ok ? onClick : undefined}>{label}</Button>;
  return ok ? btn : <WithReason reason={(a && a.reason) || 'Not available for this case.'}>{btn}</WithReason>;
}
const evTone = (t) => (/FAILED|REFUSED|REJECTED/.test(t) ? ['danger', 'danger'] : /COMPLETED|PASSED|CONFIRMED/.test(t) ? ['success', 'success'] : /STARTED|REQUESTED/.test(t) ? ['progress', 'active'] : ['neutral', 'dot']);

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
      Starting creates run 1 from the original ZIP <span className="rf-mono">{c.zip && c.zip.filename}</span> and shows its nine stages here as the backend reports them.</Empty></Panel></div>;
  }
  const d = q.data && q.data.run_id === runId ? q.data : null;
  const isLatest = sel && sel.run_id === latestId;
  const stages = (d && d.stages) || [];
  const mapped = stages.map((s) => ({
    name: s.title || s.key, desc: s.explanation,
    note: [s.detail, ...(s.evidence || [])].filter(Boolean).join(' · ') || (s.status === 'failed' && sel && sel.failure ? sel.failure.message : null),
    meta: <span className="rf-muted rfb-small">{STAGE_LABEL[s.status] || s.status}</span>,
    time: s.started_at ? fmtTimeSec(s.started_at) + (s.finished_at ? ' → ' + fmtTimeSec(s.finished_at) : '') : null,
    state: STAGE_STATE[s.status] || 'pending'
  }));
  const events = (d && d.events) || [];
  const job = (d && d.intake_job) || (sel && sel.intake_job) || null;
  const files = (job && job.files) || [];
  const ncf = (sel && sel.not_carried_forward) || [];
  const unreadable = unreadableOf((d && d.unreadable_entries) || (sel && sel.unreadable_entries) || (isLatest ? (c.outstanding || {}).unreadable_members : null));
  const done = mapped.filter((s) => s.state === 'done' || s.state === 'attention' || s.state === 'skipped').length;

  return <div className="rf-workspace rfb-run">
    {c.deferring && <Notice tone="attention" title="Deferral requested">The running job continues to the end; the case becomes Pending when it finishes. Nothing new starts meanwhile.</Notice>}
    {!sel && <Notice tone="attention" title="Run not found">{runId} is not a run of this case. Choose a run from the list.</Notice>}
    {sel && sel.failure && <Notice tone="danger" title={'Run ' + sel.run_no + ' failed · ' + sel.failure.code}
      actions={isLatest ? <Act a={A.retry_from_beginning} label="Retry from Beginning" variant="primary" icon="refresh" onClick={() => openAction('retry')} /> : null}>
      {sel.failure.message}{sel.failure.stage ? ' Stage: ' + sel.failure.stage + '.' : ''} {fmtDateTime(sel.failure.at)}.
      {isLatest ? ' Retry from Beginning starts a new run from the original ZIP; files uploaded to this run are not carried forward.' : ' A later run replaced this one.'}
    </Notice>}
    {unreadable.length > 0 && <Notice tone="attention" title={unreadable.length + ' file(s) in the original ZIP could not be read'}
      actions={isLatest ? <Act a={A.upload_evidence} label="Upload corrected file" variant="primary" icon="upload" onClick={() => nav('cases/' + ref + '/evidence?upload=')} /> : null}>
      The rest of the ZIP was processed. For each file below, upload a corrected file in Evidence:
      <ul className="rfb-plain">{unreadable.map((u, i) => <li key={i} data-unreadable={u.name}>File <span className="rf-mono">{u.name}</span> in the original ZIP could not be read{u.error ? ': ' + u.error : ''}</li>)}</ul>
    </Notice>}
    {ncf.length > 0 && <Notice tone="attention" title="Not carried forward from the failed run">
      This retry used the original ZIP only. Upload these files again if they are still needed:
      <ul className="rfb-plain">{ncf.map((j, i) => (j.files || []).map((f, k) => <li key={i + '-' + k}><span className="rf-mono">{f.name}</span> · {f.category} {catTitle(app, f.category)} <span className="rf-muted rf-mono">({j.job_id})</span></li>))}</ul>
    </Notice>}
    <div className="rf-split rf-split--aside-lg">
      <div className="rf-stack">
        {sel && <Panel title={'Run ' + sel.run_no + ' · stages'} sub={stages.length ? done + ' of ' + stages.length + ' stages finished' : 'Loading stages…'} actions={<Pill state={sel.status} />}>
          {q.error && !d ? <Notice tone="danger" compact title="Could not load the run">{q.error.message}</Notice>
            : !d ? <div aria-busy="true"><span className="rf-skel" style={{ width: '80%', margin: '8px 0' }} /><span className="rf-skel" style={{ width: '60%', margin: '8px 0' }} /></div>
              : <div className="rf-stack rf-stack--3"><StageStrip states={mapped.map((s) => s.state)} /><Stages stages={mapped} /></div>}
        </Panel>}
        {sel && <Panel title="Run log" sub="Recorded audit events of the intake job">
          {events.length ? <RunLog rows={events.map((e, i) => { const t = evTone(e.event_type); return { t: fmtTimeSec(e.at), tone: t[0], glyph: t[1], latest: i === events.length - 1, m: <>{e.event_type}{e.actor_id ? <span className="rf-muted"> · {e.actor_id}</span> : null}</> }; })} />
            : <span className="rf-muted">{d ? 'No events recorded yet.' : 'Loading…'}</span>}
        </Panel>}
      </div>
      <div className="rf-stack">
        <Panel title="Runs" sub={runs.length + ' run(s) · newest first'} flush>
          <Table dense caption="Smart Parser runs" columns={[{ key: 'run', label: 'Run' }, { key: 'status', label: 'Status', cls: 'is-tight' }]}
            rows={runs.slice().reverse().map((r) => ({ key: r.run_id, selected: r.run_id === runId, onClick: () => nav('cases/' + ref + '/parser/' + encodeURIComponent(r.run_id)), cells: {
              run: <><span className="rf-cell-main">Run {r.run_no}{r.retry_of ? ' · retry' : ''}</span><span className="rf-cell-sub rf-mono rfb-wrap">{r.run_id}</span><span className="rf-cell-sub">Started {fmtDateTime(r.started_at)}{r.failure ? ' · ' + r.failure.code : ''}</span></>,
              status: <Pill state={r.status} /> } }))} />
        </Panel>
        {sel && <Panel title="Run details">
          <KV pairs={[
            ['Run', <Ref id={sel.run_id} copy />],
            ['Status', <Pill state={sel.status} />],
            ['Package', sel.package_id ? <span className="rf-mono">{sel.package_id}</span> : null],
            ['Started', <>{fmtDateTime(sel.started_at)}{sel.started_by ? ' · ' + sel.started_by : ''}</>],
            ['Finished', sel.finished_at ? fmtDateTime(sel.finished_at) : <span className="rf-muted">Not finished</span>],
            ['Evidence source', <span className="rf-row rf-row--wrap"><Enum>{sel.evidence_source || 'ORIGINAL_ZIP'}</Enum><span className="rf-mono rf-muted rfb-small">{c.zip && c.zip.filename}</span></span>],
            ['Entries', sel.staged_entries != null || sel.skipped_entries != null ? (sel.staged_entries != null ? sel.staged_entries : '—') + ' staged · ' + (Array.isArray(sel.skipped_entries) ? sel.skipped_entries.length : sel.skipped_entries != null ? sel.skipped_entries : '—') + ' skipped' : <span className="rf-muted">Not read yet</span>],
            ['Retry of', sel.retry_of ? <Button variant="link" onClick={() => nav('cases/' + ref + '/parser/' + encodeURIComponent(sel.retry_of))}><span className="rf-mono">{sel.retry_of}</span></Button> : null],
            ['Intake job', job ? <span className="rf-row rf-row--wrap"><span className="rf-mono">{job.job_id}</span><span className="rf-muted">{job.state}</span></span> : null],
            ['Proposals', d && d.llm_mode ? <span className="rf-row rf-row--wrap"><Enum>{d.llm_mode.mode}</Enum><span>{d.llm_mode.label}</span></span> : (app && app.llm ? <span className="rf-row rf-row--wrap"><Enum>{app.llm.mode}</Enum><span>{app.llm.label}</span></span> : null)]
          ].filter((x) => x[1] != null)} />
          {job && job.error && !(sel.failure && sel.failure.message === job.error) && <div style={{ marginTop: 10 }}><Notice tone="danger" compact title="Job error">{job.error}</Notice></div>}
        </Panel>}
        {sel && <Panel title="Files in this run" sub={files.length ? files.length + ' file(s)' : null} flush>
          {files.length ? <Table dense caption="Files processed by the intake job" columns={[{ key: 'name', label: 'File' }, { key: 'state', label: 'State', cls: 'is-tight' }, { key: 'out', label: 'Outcome', cls: 'is-tight' }]}
            rows={files.map((f, i) => ({ key: i, cells: { name: <span className="rf-mono rfb-small rfb-wrap">{f.name}</span>, state: <span className="rfb-small">{f.state === 'running' || f.state === 'processing' ? <span className="rf-row"><span className="rf-tone-progress"><Glyph name="progress" size={10} /></span>processing</span> : f.state}</span>, out: f.outcome ? (typeof f.outcome !== 'object' ? <Pill state={f.outcome} /> : f.outcome.error ? <Pill state="FAILED" label="Error" title={f.outcome.error} /> : f.outcome.refused_reason ? <Pill state="REJECTED" label="Refused" title={f.outcome.refused_reason} /> : <Pill state={f.outcome.version_status} />) : null } }))} />
            : <div style={{ padding: '12px 16px' }} className="rf-muted">{sel.status === 'FAILED' ? 'No file was registered by this run.' : 'Files appear when the identify stage finishes.'}</div>}
        </Panel>}
      </div>
    </div>
  </div>;
}
