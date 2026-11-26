/* S09 / S11 · Validation & activation. Validation runs automatically (contract §3.4): there is no
   "Run validation" button. Activation is offered only when actions.activate.enabled, and sends
   { confirm: true } only after the acknowledgement is ticked. */
import React from 'react';
import { useQuery, useMutation } from '../hooks.js';
import { Button, WithReason, Panel, KV, Notice, Table, Empty, Skeleton, Dialog, Pill, Enum, Ref, Hash, Icon, Glyph, Checks, Readiness, stateOf } from '../../ui/index.jsx';
import { fmtDateTime, catTitle } from '../format.js';

const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many || one + 's');
const VAL_TITLE = { NOT_RUN: 'Validation has not run', RUNNING: 'Validation running', PASSED: 'Validation passed', FAILED: 'Validation failed' };

export default function PackageTab({ c, app, nav, openAction, store }) {
  const ref = c.case_ref;
  const pkg = c.package;
  const [dialog, setDialog] = React.useState(false);
  if (!pkg) {
    const a = c.actions || {};
    const act = a.start && a.start.enabled ? ['start', 'Start Smart Parsing', 'play'] : a.resume && a.resume.enabled ? ['resume', 'Resume Processing', 'play'] : a.retry_from_beginning && a.retry_from_beginning.enabled ? ['retry', 'Retry from Beginning', 'refresh'] : null;
    return <div className="rf-page"><Head c={c} />
      <Panel><Empty icon="layers" title="No evidence package yet" action={act ? <Button variant="primary" icon={act[2]} onClick={() => openAction(act[0])}>{act[1]}</Button> : null}>
        The package is created by the Smart Parser run from the original ZIP. Validation runs automatically once processing and the required reviews are complete.{!act && a.activate && a.activate.reason ? ' ' + a.activate.reason : ''}
      </Empty></Panel></div>;
  }
  const sid = (c.activation && c.activation.snapshot_id) || pkg.active_snapshot_id || null;
  return <div className="rf-page">
    <Head c={c} />
    <div className="rf-split rf-split--aside-lg">
      <div className="rf-stack">
        <Validation c={c} />
        {sid && <Snapshot c={c} app={app} sid={sid} />}
        <ValidationHistory c={c} />
      </div>
      <div className="rf-stack">
        <Activation c={c} nav={nav} openAction={openAction} onActivate={() => setDialog(true)} />
        <PackageFacts c={c} app={app} />
      </div>
    </div>
    {dialog && <ActivateDialog c={c} store={store} onClose={() => setDialog(false)} />}
  </div>;
}

function Head({ c }) {
  const pkg = c.package;
  return <div className="rf-page__head"><div><h2 className="rf-page__title">Validation &amp; activation</h2>
    <div className="rf-page__sub rf-row rf-row--wrap" style={{ gap: 8 }}>{pkg ? <><span>Package</span><Ref id={pkg.package_id} copy /><Pill state={pkg.package_status} />{c.activation && <Pill state="ACTIVE" />}</> : <span>No package</span>}</div></div></div>;
}

function Validation({ c }) {
  const v = (c.progress && c.progress.validation) || { state: 'NOT_RUN' };
  const lv = c.package.latest_validation;
  const failed = lv ? lv.checks.filter((k) => !k.passed) : [];
  const checks = lv ? lv.checks.map((k) => ({ id: k.check_id, title: k.name, explain: k.detail, result: k.passed ? 'pass' : 'fail', blocking: true })) : [];
  return <Panel title={VAL_TITLE[v.state] || v.state} sub={(v.at ? 'Last run ' + fmtDateTime(v.at) : 'Runs automatically after every run, upload, confirmation and rejection') + (lv ? ' · ' + (lv.checks.length - failed.length) + ' of ' + lv.checks.length + ' checks passed' : '')}
    actions={<span className="rf-row" style={{ gap: 6 }}><Pill state={v.state} />{v.state !== 'RUNNING' && v.state !== 'NOT_RUN' && v.current === false && <Pill state="NOT_PROCESSED" label="Out of date" />}</span>} flush>
    <div className="rf-stack rf-stack--3" style={{ padding: v.state === 'RUNNING' || v.current === false || !lv ? '12px 16px 0' : 0 }}>
      {v.state === 'RUNNING' && <Notice tone="info" compact title="Validation is running">Checks PV-01…PV-09 run against the current evidence.{lv ? ' The previous result is shown until it finishes.' : ''}</Notice>}
      {v.state !== 'RUNNING' && v.current === false && lv && <Notice tone="attention" compact title="Out of date">The evidence changed after this validation. Validation runs again automatically when processing and reviews are complete.</Notice>}
    </div>
    {lv ? <Checks checks={checks} /> : v.state !== 'RUNNING' && <Empty icon="checklist" title="Not run yet">Validation runs automatically once the Smart Parser run and the required mapping reviews are complete.</Empty>}
  </Panel>;
}

function Activation({ c, nav, openAction, onActivate }) {
  const ref = c.case_ref;
  const a = c.actions.activate;
  if (c.activation) {
    return <Readiness tone="sealed" title="Package activated · locked" sub={'Snapshot ' + c.activation.snapshot_id + ' · ' + (c.activation.activated_by || '—') + ' · ' + fmtDateTime(c.activation.activated_at)}
      headAction={<Button size="sm" iconRight="arrowRight" onClick={() => nav('cases/' + ref + '/recon')}>Reconciliation</Button>}>
      <div style={{ padding: '10px 16px', fontSize: 13, lineHeight: '18px' }} className="rf-secondary">The package is an immutable snapshot. Evidence can no longer be uploaded, corrected or re-reviewed in this case.</div>
    </Readiness>;
  }
  if (a.enabled) {
    return <Readiness tone="ready" title="Ready to activate" sub="Validation PASSED for the current evidence." headAction={<Button variant="primary" icon="lock" onClick={onActivate}>Activate package…</Button>}>
      <div style={{ padding: '10px 16px', fontSize: 13, lineHeight: '18px' }} className="rf-secondary">Activation locks the package as an immutable snapshot. Reconciliation runs against that snapshot.</div>
    </Readiness>;
  }
  const o = c.outstanding || {};
  const v = (c.progress && c.progress.validation) || {};
  const lv = c.package && c.package.latest_validation;
  const failed = v.current !== false && lv ? lv.checks.filter((k) => !k.passed).map((k) => k.check_id) : [];
  const items = [];
  if (failed.length) items.push({ title: 'Validation failed', detail: 'The failed checks block activation. See the check details.', checks: failed });
  (o.mapping_decisions || []).forEach((x) => items.push({ title: 'Mapping review · ' + x.file_name + ' v' + x.version, detail: plural(x.outstanding, 'decision') + ' outstanding of ' + x.total + ' · ' + x.category, action: <Button size="sm" onClick={() => nav('cases/' + ref + '/review/' + x.file_version_id)}>Review</Button> }));
  (o.missing_categories || []).forEach((x) => items.push({ title: 'Missing required evidence · ' + x.category + ' ' + x.title, detail: 'Upload a ' + (x.format || '') + ' file in Evidence.', action: <Button size="sm" onClick={() => nav('cases/' + ref + '/evidence')}>Evidence</Button> }));
  (o.files_requiring_replacement || []).forEach((x) => items.push({ title: 'Correction required · ' + x.category + ' v' + x.version, detail: x.detail, checks: [x.cause, x.version_status], action: <Button size="sm" onClick={() => nav('cases/' + ref + '/evidence')}>Evidence</Button> }));
  (o.other || []).filter((x) => x.kind === 'RETRY_FROM_BEGINNING').forEach((x) => items.push({ title: 'Retry from Beginning', detail: x.detail, action: c.actions.retry_from_beginning.enabled ? <Button size="sm" icon="refresh" onClick={() => openAction('retry')}>Retry…</Button> : null }));
  return <Readiness tone="blocked" title="Activation not available" sub={a.reason || 'Not available.'} items={items}
    headAction={c.actions.resume.enabled ? <Button size="sm" variant="primary" icon="play" onClick={() => openAction('resume')}>Resume Processing</Button> : null} />;
}

function PackageFacts({ c, app }) {
  const pkg = c.package;
  const slots = pkg.slots || [];
  const present = slots.filter((s) => s.latest);
  const v = c.progress && c.progress.validation;
  return <Panel title="Package" sub={plural(present.length, 'category', 'categories') + ' with a file · ' + (c.progress ? c.progress.categories_validated + ' validated' : '')}>
    <KV pairs={[['Package', <Ref id={pkg.package_id} copy />], ['Status', <Pill state={pkg.package_status} />], ['Validation', v ? <span className="rf-row" style={{ gap: 6 }}><Enum>{v.state}</Enum>{v.failed_checks && v.failed_checks.length > 0 && <span className="rf-muted">{v.failed_checks.join(', ')}</span>}</span> : '—'], ['Active snapshot', pkg.active_snapshot_id ? <Ref id={pkg.active_snapshot_id} copy /> : <span className="rf-muted">None</span>], ['Original ZIP', <Hash sha={c.zip.sha256} />]]} />
  </Panel>;
}

function ValidationHistory({ c }) {
  const pid = c.package.package_id;
  const h = useQuery('hist:' + c.case_ref + ':' + pid, (svc) => svc.getPackageHistory(pid));
  const vals = ((h.data && h.data.validations) || []).slice().reverse();
  if (h.error) return <Notice tone="danger" compact title="Validation history could not be loaded">{h.error.message}</Notice>;
  if (!h.data) return null;
  if (!vals.length) return null;
  return <Panel title="Validation history" sub={plural(vals.length, 'run') + ' for this package'} flush>
    <Table dense columns={[{ key: 'at', label: 'Run at' }, { key: 'res', label: 'Result' }, { key: 'failed', label: 'Failed checks' }, { key: 'cur', label: '' }]}
      rows={vals.map((x, i) => ({ key: String(i), cells: { at: fmtDateTime(x.at), res: <Pill state={x.passed ? 'PASSED' : 'FAILED'} />, failed: (x.failed || []).length ? <span className="rf-row rf-row--wrap" style={{ gap: 4 }}>{x.failed.map((id) => <Enum key={id}>{id}</Enum>)}</span> : null, cur: i === 0 ? <span className="rf-muted" style={{ fontSize: 12 }}>Latest</span> : <span className="rf-muted" style={{ fontSize: 12 }}>Superseded</span> } }))} />
  </Panel>;
}

function Snapshot({ c, app, sid }) {
  const pid = c.package.package_id;
  const q = useQuery('snap:' + c.case_ref + ':' + sid, (svc) => svc.getSnapshot(pid, sid));
  const s = q.data;
  const act = c.activation || {};
  const manifestSha = act.manifest_sha256 || (s && s.manifest && s.manifest.sha256);
  return <>
    <section className="rf-seal" aria-label="Active snapshot">
      <div className="rf-seal__head"><Icon name="seal" size={18} /><div style={{ flex: 1, minWidth: 0 }}><div className="rf-seal__title">Snapshot {sid}</div><div className="rf-seal__sub">Immutable evidence set · reconciliation runs against it</div></div>{s && <Pill state={s.is_active ? 'ACTIVE' : 'SUPERSEDED'} />}</div>
      <div className="rf-seal__rule" />
      <KV cols pairs={[['Snapshot', <Ref id={sid} copy />], ['Activated by', <span className="rf-mono">{act.activated_by || '—'}</span>], ['Activated at', act.activated_at ? fmtDateTime(act.activated_at) : '—'], ['Reconciliation eligible', s ? (s.reconciliation_eligible ? 'Yes' : 'No') : '…']]} />
      {manifestSha && <KV pairs={[['Manifest SHA-256', <Hash sha={manifestSha} full />]]} />}
    </section>
    {q.error ? <Notice tone="danger" compact title="Snapshot could not be loaded">{q.error.message}</Notice> : !s ? <Skeleton rows={3} /> : <>
      <Panel title="Snapshot verification" sub={((s.verification || []).filter((v) => v.passed).length) + ' of ' + (s.verification || []).length + ' checks passed'}>
        <div className="rf-row rf-row--wrap" style={{ gap: 6 }}>{(s.verification || []).map((v) => <Pill key={v.check_id} state={v.passed ? 'PASS' : 'FAIL'} label={v.check_id + (v.name ? ' · ' + v.name : '')} title={v.detail || undefined} />)}</div>
        {(s.runs || []).length > 0 && <div className="rf-stack rf-stack--2" style={{ marginTop: 12 }}><div className="rf-label">Reconciliation runs on this snapshot</div>{s.runs.map((r) => <div key={r.run_id} className="rf-row" style={{ gap: 8 }}><Ref id={r.run_id} /><Pill state={r.case_status || r.state} /></div>)}</div>}
      </Panel>
      <Panel title="Snapshot entries" sub={plural(((s.snapshot && s.snapshot.entries) || []).length, 'file version')} flush>
        <Table dense columns={[{ key: 'cat', label: 'Category' }, { key: 'file', label: 'File' }, { key: 'v', label: 'Version', width: 64 }, { key: 'fv', label: 'File version' }, { key: 'sha', label: 'SHA-256' }]}
          rows={((s.snapshot && s.snapshot.entries) || []).map((e) => ({ key: e.file_version_id, cells: { cat: <span><span className="rf-mono">{e.evidence_category}</span> <span className="rf-muted">{catTitle(app, e.evidence_category)}</span></span>, file: <span className="rf-mono" style={{ fontSize: 12 }}>{e.original_filename}</span>, v: 'v' + e.version_number, fv: <span className="rf-mono" style={{ fontSize: 12 }}>{e.file_version_id}</span>, sha: e.source_sha256 ? <Hash sha={e.source_sha256} /> : null } }))} />
      </Panel>
    </>}
  </>;
}

function ActivateDialog({ c, store, onClose }) {
  const m = useMutation();
  const [ack, setAck] = React.useState(false);
  const [refused, setRefused] = React.useState(null);
  const pkg = c.package;
  const v = (c.progress && c.progress.validation) || {};
  const files = (pkg.slots || []).filter((s) => s.latest).length;
  const go = async () => {
    setRefused(null);
    const r = await m.run((svc) => svc.activateCase(c.case_ref, { confirm: true }), { inline: true });
    if (!r) return;
    if (r.activated === false) { setRefused(r.reason || 'The package was not activated.'); return; }
    store.toast('success', 'Package activated · ' + r.snapshot_id);
    onClose();
  };
  return <Dialog eyebrow="Activate package" title={'Activate ' + pkg.package_id + '?'} error={m.error || (refused ? 'Not activated: ' + refused : null)} onClose={m.busy ? undefined : onClose}
    foot={<><Button onClick={onClose} disabled={m.busy}>Cancel</Button>{ack ? <Button variant="primary" icon="lock" loading={m.busy} onClick={go}>{m.busy ? 'Activating…' : 'Activate package'}</Button> : <WithReason reason="Tick the acknowledgement first"><Button variant="primary" icon="lock" disabled>Activate package</Button></WithReason>}</>}>
    <KV pairs={[['Case', <Ref id={c.case_ref} />], ['Package', <Ref id={pkg.package_id} />], ['Validation', <span>{stateOf(v.state).label}{v.at ? ' · ' + fmtDateTime(v.at) : ''}</span>], ['Evidence', plural(files, 'category', 'categories') + ' with a current file']]} />
    <Notice tone="locked" title="Activation is final">Activation creates an immutable snapshot of the current evidence. Afterwards no file can be uploaded, corrected or re-reviewed in this case; reconciliation runs against the snapshot.</Notice>
    <label className="rfc-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} disabled={m.busy} /><span>I understand the package will be locked and the snapshot cannot be changed.</span></label>
  </Dialog>;
}
