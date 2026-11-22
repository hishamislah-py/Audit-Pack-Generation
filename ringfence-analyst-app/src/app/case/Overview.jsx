/* Case workspace · Overview tab.
   Renders the case detail payload (contract §3.3) as returned: steps[], progress.summary, outstanding,
   kept, actions, blocked_by, deferral, completed. Lifecycle rules stay in the backend: every action is
   guarded by c.actions[...] and shows its reason when disabled. */
import React from 'react';
import { Button, WithReason, Panel, KV, Notice, Tasks, CaseProgress, Outcome, Pill, Ref, Hash, Enum, Stats, Glyph } from '../../ui/index.jsx';
import { fmtDateTime, fmtPeriod, fmtBytes, catTitle, catInfo, unreadableOf, missingNotUnreadable } from '../format.js';

function Act({ a, label, onClick, variant = 'secondary', size = 'sm', icon, iconRight }) {
  const ok = !!(a && a.enabled);
  const btn = <Button variant={variant} size={size} icon={icon} iconRight={iconRight} disabled={!ok} onClick={ok ? onClick : undefined}>{label}</Button>;
  return ok ? btn : <WithReason reason={(a && a.reason) || 'Not available for this case.'}>{btn}</WithReason>;
}

const OUTCOME = {
  CLEAN: 'Reconciliation clean',
  EXCEPTIONS_OPEN: 'Reconciliation completed · exceptions open',
  EVIDENCE_INCOMPLETE: 'Reconciliation completed · evidence incomplete'
};

function StatusPanel({ c, A, p, openAction, go }) {
  if (c.status === 'WAITING') {
    return <section className="rf-next" aria-label="Next step">
      <div className="rf-next__eyebrow">Next step</div>
      <h2 className="rf-next__title">Start Smart Parsing</h2>
      <div className="rf-next__body">The original ZIP <span className="rf-mono">{c.zip && c.zip.filename}</span> is attached and has not been processed. Starting makes this case In Progress; only one case can be In Progress at a time.</div>
      {c.blocked_by && <Notice tone="attention" compact title={c.blocked_by.case_ref + ' is In Progress'}>{c.blocked_by.customer_name} · {fmtPeriod(c.blocked_by.reporting_period)}. Defer that case before starting this one.</Notice>}
      <div><Act a={A.start} label="Start Smart Parsing" variant="primary" size={null} icon="play" onClick={() => openAction('start')} /></div>
    </section>;
  }
  if (c.status === 'PENDING') {
    return <Notice tone="info" title="Pending · read-only" actions={<Act a={A.resume} label="Resume Processing" variant="primary" icon="play" onClick={() => openAction('resume')} />}>
      Opening a Pending case never resumes it. The work below is kept{c.deferred_at ? ' (deferred ' + fmtDateTime(c.deferred_at) + ')' : ''}.
      {c.blocked_by ? ' ' + c.blocked_by.case_ref + ' (' + c.blocked_by.customer_name + ') is In Progress; defer it before resuming this case.' : ''}
    </Notice>;
  }
  if (c.status === 'IN_PROGRESS' && c.deferring) {
    const w = (c.deferral && c.deferral.waiting_for) || [];
    return <Notice tone="attention" title="Deferral requested">
      Requested {fmtDateTime(c.deferral && c.deferral.requested_at)}. The running operation continues to the end; the case becomes Pending when it finishes. Nothing new can start meanwhile.
      {w.length > 0 && <span className="rf-row rf-row--wrap" style={{ marginTop: 6 }}>Waiting for: {w.map((x, i) => <span key={i} className="rf-evref" style={{ color: 'var(--ink-secondary)' }}>{x.job_id || '—'} · {x.kind} · {x.state}</span>)}</span>}
    </Notice>;
  }
  if (c.status === 'IN_PROGRESS' && p.current_operation) {
    const op = p.current_operation;
    return <Notice tone="info" title={'Processing · ' + op.kind}>
      <span className="rf-row rf-row--wrap"><span className="rf-tone-progress"><Glyph name="progress" size={10} /></span>
        {op.job_id && <span className="rf-mono">{op.job_id}</span>}<span>{op.state}</span>
        {op.files_total != null && <span>{op.files_processed || 0} of {op.files_total} file(s) processed</span>}
        {op.validation_running && <span>· validation running</span>}</span>
    </Notice>;
  }
  if (c.status === 'COMPLETED' && c.completed && OUTCOME[c.completed.case_status]) {
    const r = c.completed;
    return <Outcome status={r.case_status} title={OUTCOME[r.case_status]} actions={<Button size="sm" iconRight="arrowRight" onClick={() => go('recon')}>View reconciliation</Button>}>
      Completed {fmtDateTime(r.at)} · snapshot <span className="rf-mono">{r.snapshot_id}</span> · run <span className="rf-mono">{r.reconciliation_run_id}</span>
      {p.reconciliation && p.reconciliation.exceptions != null ? ' · ' + p.reconciliation.exceptions + ' exception(s)' : ''}. The case is read-only.
    </Outcome>;
  }
  return null;
}

export default function OverviewTab({ c, app, nav, openAction }) {
  const ref = c.case_ref, A = c.actions || {}, o = c.outstanding || {}, p = c.progress || {};
  const go = (tab, extra) => nav('cases/' + ref + '/' + tab + (extra || ''));
  const upload = (cat) => go('evidence', '?upload=' + encodeURIComponent(cat));
  const groups = [];
  if ((o.mapping_decisions || []).length) groups.push({ label: 'Mapping decisions', tone: 'attention', glyph: 'review', items: o.mapping_decisions.map((m) => ({
    title: <>{m.file_name} <span className="rf-muted rf-mono">v{m.version}</span></>,
    detail: <>{m.category} {catTitle(app, m.category)} · {m.outstanding} of {m.total} column{m.total === 1 ? '' : 's'} outstanding{(m.columns || []).length > 0 && <> · {m.columns.map((col) => <span key={col} className="rf-srchdr" style={{ marginRight: 4 }}>{col}</span>)}</>}</>,
    action: <Act a={A.review} label="Review columns" onClick={() => go('review/' + encodeURIComponent(m.file_version_id))} />
  })) });
  if ((o.files_requiring_replacement || []).length) groups.push({ label: 'Files requiring correction', tone: 'danger', glyph: 'resubmit', items: o.files_requiring_replacement.map((f) => ({
    title: <>{f.category} {catTitle(app, f.category)} <span className="rf-muted rf-mono">v{f.version}</span></>,
    detail: <span className="rf-row rf-row--wrap"><Pill state={f.version_status} /><Enum>{f.cause}</Enum><span>{f.detail}</span></span>,
    action: <Act a={A.upload_evidence} label="Upload corrected file" icon="upload" onClick={() => upload(f.category)} />
  })) });
  const unreadable = unreadableOf(o.unreadable_members), missing = missingNotUnreadable(o);
  const openUnreadable = unreadable.filter((u) => u.open);
  if (openUnreadable.length) groups.push({ label: 'Unreadable in the original ZIP', tone: 'danger', glyph: 'resubmit', items: openUnreadable.map((u) => ({
    title: <>File <span className="rf-mono">{u.name}</span> in the original ZIP could not be read{u.error ? ': ' + u.error : ''}</>,
    detail: <>Upload a corrected file.{u.hint ? ' ' + u.hint : ''}</>,
    action: <Act a={A.upload_evidence} label="Upload corrected file" icon="upload" onClick={() => upload('')} />
  })) });
  if (missing.length) groups.push({ label: 'Missing required evidence', tone: 'danger', glyph: 'danger', items: missing.map((m) => ({
    title: <>{m.category} {m.title || catTitle(app, m.category)}</>,
    detail: (m.format || catInfo(app, m.category).format) + ' · required · no file in the package',
    action: <Act a={A.upload_evidence} label="Upload file" icon="upload" onClick={() => upload(m.category)} />
  })) });
  if ((o.refused_uploads || []).length) groups.push({ label: 'Refused uploads', tone: 'neutral', glyph: 'na', items: o.refused_uploads.map((r) => ({
    title: <span className="rf-mono">{r.filename}</span>,
    detail: <>{r.evidence_category} {catTitle(app, r.evidence_category)} · {r.reason} · {fmtDateTime(r.at)}</>
  })) });
  const OTHER = {
    RETRY_FROM_BEGINNING: ['Retry from Beginning', A.retry_from_beginning, () => openAction('retry')],
    ACTIVATE: ['Open activation', A.activate, () => go('package')],
    RUN_RECONCILIATION: ['Open reconciliation', A.reconcile, () => go('recon')]
  };
  if ((o.other || []).length) groups.push({ label: 'Next actions', tone: 'progress', glyph: 'active', items: o.other.map((x) => {
    const d = OTHER[x.kind];
    return { title: d ? d[0] : x.kind, detail: x.detail, action: d ? <Act a={d[1]} label={d[0]} variant="primary" onClick={d[2]} /> : null };
  }) });
  const readOnly = c.status === 'PENDING' || c.status === 'COMPLETED';
  const live = !!p.current_operation;
  const val = p.validation || {};
  const pkg = c.package;
  const history = (c.status_history || []).slice().reverse();

  return <div className="rf-workspace rfb-overview">
    <StatusPanel c={c} A={A} p={p} openAction={openAction} go={go} />
    <div className="rf-split rf-split--aside-lg">
      <div className="rf-stack">
        <Panel title="Progress" sub={'Last activity ' + fmtDateTime(p.last_activity_at || c.last_activity_at)}>
          <div className="rf-stack rf-stack--3">
            <CaseProgress steps={c.steps || []} labels />
            {(p.summary || []).length > 0 && <ul className="rfb-facts" aria-label="Progress facts">{p.summary.map((s, i) => <li key={i}>{i === 0 && live && <span className="rf-tone-progress"><Glyph name="progress" size={10} /></span>}<span>{s}</span></li>)}</ul>}
            <Stats items={[
              { label: 'Categories processed', value: (p.categories_processed != null ? p.categories_processed : '—') + ' / ' + (p.categories_total != null ? p.categories_total : '—'), note: p.required_total != null ? p.required_total + ' required' : null },
              { label: 'Validated', value: p.categories_validated != null ? p.categories_validated : '—', note: 'categories' },
              { label: 'Awaiting review', value: p.files_awaiting_review != null ? p.files_awaiting_review : '—', note: (p.decisions_outstanding || 0) + ' decision(s) outstanding' },
              { label: 'Decisions made', value: p.decisions_made != null ? p.decisions_made : '—' },
              { label: 'Validation', value: <Pill state={val.state || 'NOT_RUN'} />, note: val.state && val.state !== 'NOT_RUN' && val.current === false ? 'Out of date' : val.at ? fmtDateTime(val.at) : null }
            ]} />
          </div>
        </Panel>
        {(groups.length > 0 || (c.kept || []).length > 0)
          ? <Tasks title={groups.length ? 'Outstanding' : 'Nothing outstanding'} sub={readOnly ? (c.status === 'PENDING' ? 'Read-only while Pending. Resume Processing to act on these.' : 'The case is Completed and read-only.') : groups.length ? 'From the backend: what is left before the case can move on.' : null}
            groups={groups} kept={(c.kept || []).length ? c.kept : null} keptTitle="Kept" readOnly={readOnly} />
          : <Panel title="Outstanding"><span className="rf-muted">Nothing outstanding.</span></Panel>}
      </div>
      <div className="rf-stack">
        <Panel title="Case facts">
          <KV pairs={[
            ['Case', <Ref id={ref} copy />],
            ['Customer', <Button variant="link" onClick={() => nav('customers/' + encodeURIComponent(c.customer_id))}>{c.customer_name}</Button>],
            ['Reporting period', <>{fmtPeriod(c.reporting_period)} <span className="rf-mono rf-muted">{c.reporting_period}</span></>],
            ['Original ZIP', c.zip ? <div className="rf-stack rf-stack--2"><span className="rf-mono">{c.zip.filename} · {fmtBytes(c.zip.size)}</span><Hash sha={c.zip.sha256} /></div> : null],
            ['Received', fmtDateTime(c.created_at)],
            ['Status', <span className="rf-row rf-row--wrap"><Pill state={c.status} />{c.deferring && <Pill state="DEFERRAL_REQUESTED" />}<span className="rf-muted">since {fmtDateTime(c.status_since)}</span></span>],
            ['Started', c.started ? <>{c.started.by} · {fmtDateTime(c.started.at)}</> : <span className="rf-muted">Not started</span>],
            ['Current run', c.current_run ? <span className="rf-row rf-row--wrap"><span className="rf-mono">{c.current_run.run_id}</span><Pill state={c.current_run.status} /></span> : <span className="rf-muted">None</span>],
            ['Runs', (c.runs_total || 0) + ' total · ' + (c.failed_runs || 0) + ' failed'],
            ['Package', pkg ? <span className="rf-row rf-row--wrap"><span className="rf-mono">{pkg.package_id}</span><Pill state={pkg.package_status} /></span> : <span className="rf-muted">Created by the first run</span>],
            ['Active snapshot', (pkg && pkg.active_snapshot_id) || (c.activation && c.activation.snapshot_id) ? <span className="rf-mono">{(pkg && pkg.active_snapshot_id) || c.activation.snapshot_id}</span> : <span className="rf-muted">Not activated</span>],
            ['Other cases, same period', c.other_cases_for_period != null ? String(c.other_cases_for_period) : null],
            ['Revision', <span className="rf-mono">{c.revision}</span>]
          ]} />
        </Panel>
        <Panel title="Status history" sub="Newest first">
          {history.length ? <ol className="rfb-hist">{history.map((h, i) => <li key={i}><Pill state={h.status} /><div style={{ minWidth: 0 }}><div className="rf-secondary">{h.note || '—'}</div><div className="rf-muted rf-mono rfb-small">{fmtDateTime(h.at)}</div></div></li>)}</ol> : <span className="rf-muted">No status changes recorded.</span>}
        </Panel>
      </div>
    </div>
  </div>;
}
