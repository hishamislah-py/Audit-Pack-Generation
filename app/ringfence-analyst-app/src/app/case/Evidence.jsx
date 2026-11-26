/* Case workspace · Evidence tab (S07 / S10).
   Slots come from case.package.slots (contract §3.3); file detail from GET /api/packages/{pid}/versions/{vid}
   (+ /columns, /preview); history from /api/packages/{pid}/history. Uploads: POST /api/staging then
   POST /api/cases/{ref}/evidence. Processing starts immediately and validation runs automatically, so there is
   no "Process uploaded files" and no "Remove upload" (contract §7). */
import React from 'react';
import { Button, WithReason, Panel, KV, Notice, Table, Segmented, Empty, Dialog, Drawer, Pill, Enum, Tag, Ref, Hash, Versions, Icon, Glyph } from '../../ui/index.jsx';
import { useQuery, useMutation } from '../hooks.js';
import { fmtDateTime, fmtBytes, catTitle, catInfo, unreadableOf, missingNotUnreadable } from '../format.js';
import { fileToBase64 } from '../../services/dataService.js';

function Act({ a, label, onClick, variant = 'secondary', size = 'sm', icon }) {
  const ok = !!(a && a.enabled);
  const btn = <Button variant={variant} size={size} icon={icon} disabled={!ok} onClick={ok ? onClick : undefined}>{label}</Button>;
  return ok ? btn : <WithReason reason={(a && a.reason) || 'Not available for this case.'}>{btn}</WithReason>;
}
const Missing = ({ required }) => <span className={'rf-pill ' + (required ? 'rf-pill--danger' : '')}><Glyph name={required ? 'danger' : 'pending'} /><span>{required ? 'Missing · required' : 'Not supplied'}</span></span>;
const Err = ({ q }) => <Notice tone="danger" compact title="Could not load">{q.error.message}</Notice>;
const Loading = () => <div aria-busy="true"><span className="rf-skel" style={{ width: '70%', margin: '8px 0' }} /><span className="rf-skel" style={{ width: '50%', margin: '8px 0' }} /></div>;

/* Categories the backend says need a file: corrections first, then missing required. */
function uploadOptions(c, app) {
  const o = c.outstanding || {}, out = [], seen = new Set();
  (o.files_requiring_replacement || []).forEach((f) => { if (seen.has(f.category)) return; seen.add(f.category); out.push({ category: f.category, title: catTitle(app, f.category), format: catInfo(app, f.category).format, kind: 'correction · replaces v' + f.version + ' (' + f.version_status + ')' }); });
  (o.missing_categories || []).forEach((m) => { if (seen.has(m.category)) return; seen.add(m.category); out.push({ category: m.category, title: m.title || catTitle(app, m.category), format: m.format || catInfo(app, m.category).format, kind: 'missing · required' }); });
  return out;
}

function UploadDialog({ c, app, initial, onClose }) {
  const A = c.actions || {};
  const opts = uploadOptions(c, app);
  const [cat, setCat] = React.useState(opts.some((x) => x.category === initial) ? initial : (opts[0] && opts[0].category) || '');
  const [file, setFile] = React.useState(null);
  const m = useMutation();
  const sel = opts.find((x) => x.category === cat);
  const allowed = !!(A.upload_evidence && A.upload_evidence.enabled);
  const submit = async () => {
    const r = await m.run(async (svc) => {
      // POST /api/staging returns { entries: [{ staging_id, ... }] } (api.py staging route)
      const s = await svc.stageFile({ name: file.name, data_b64: await fileToBase64(file) });
      const e = ((s && s.entries) || []).find((x) => x.staging_id);
      if (!e) throw { error: 'NOT_STAGED', message: 'The file could not be staged.' };
      return svc.submitEvidence(c.case_ref, { staging_id: e.staging_id, category: cat });
    }, { inline: true, success: 'File uploaded · processing started' });
    if (r) onClose();
  };
  const close = () => { if (!m.busy) onClose(); };
  const primary = <Button variant="primary" icon="upload" loading={m.busy} disabled={!allowed || !file || !cat} onClick={submit}>{m.busy ? 'Uploading…' : 'Upload and process'}</Button>;
  return <div className="rfb-fixed"><Dialog eyebrow={c.case_ref + ' · Upload evidence'} title="Upload missing or corrected file" error={m.error} onClose={close}
    foot={<><Button onClick={close} disabled={m.busy}>Cancel</Button>{allowed ? primary : <WithReason reason={(A.upload_evidence && A.upload_evidence.reason) || 'Upload is not available.'}>{primary}</WithReason>}</>}>
    {initial && !opts.some((x) => x.category === initial) && <Notice tone="attention" compact>{initial} does not need a file at the moment.</Notice>}
    {opts.length === 0
      ? <Notice tone="info" compact title="No file needed">No category is missing or awaiting correction.</Notice>
      : <div className="rf-field"><label className="rf-label" htmlFor="rfb-cat">Evidence category</label>
        <select id="rfb-cat" className="rf-input" value={cat} onChange={(e) => { setCat(e.target.value); m.reset(); }}>{opts.map((x) => <option key={x.category} value={x.category}>{x.category} {x.title} · {x.format} · {x.kind}</option>)}</select>
        <div className="rf-help">The category routes the file; the backend checks its content and decides intake or resubmission.</div></div>}
    <div className="rf-field"><label className="rf-label" htmlFor="rfb-file">File{sel && sel.format ? ' (' + sel.format + ')' : ''}</label>
      <input id="rfb-file" type="file" className="rf-input rfb-fileinput" accept={sel && sel.format ? '.' + sel.format.toLowerCase() : undefined} disabled={m.busy || !opts.length} onChange={(e) => { setFile((e.target.files && e.target.files[0]) || null); m.reset(); }} />
      {file && <div className="rf-help"><span className="rf-mono">{file.name}</span> · {fmtBytes(file.size)}</div>}</div>
    <ul className="rf-steps-mini">
      <li><span><Icon name="play" size={12} /></span><span>Processing starts as soon as the file is accepted; validation then runs automatically.</span></li>
      <li><span><Icon name="layers" size={12} /></span><span>A correction becomes a new version of the file. Earlier versions stay in the history, read-only.</span></li>
      <li><span><Icon name="x" size={12} /></span><span>Identical bytes for a category are refused. Nothing changes when an upload is refused.</span></li>
    </ul>
  </Dialog></div>;
}

function FileDrawer({ c, app, vid, onClose, onUpload, nav }) {
  const pid = c.package.package_id, ref = c.case_ref, A = c.actions || {}, o = c.outstanding || {};
  const fv = useQuery('fv:' + ref + ':' + vid, (svc) => svc.getFileVersion(pid, vid));
  const cols = useQuery('cols:' + ref + ':' + vid, (svc) => svc.getVersionColumns(pid, vid));
  const [wantPreview, setWantPreview] = React.useState(false);
  React.useEffect(() => { setWantPreview(false); }, [vid]);
  const prev = useQuery('prev:' + ref + ':' + vid, (svc) => svc.getVersionPreview(pid, vid), { enabled: wantPreview });
  React.useEffect(() => { const k = (e) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [onClose]);
  const d = fv.data, v = d && d.version;
  const cat = v ? v.evidence_category : (c.package.slots || []).map((s) => s.latest && s.latest.file_version_id === vid ? s.evidence_category : null).find(Boolean);
  const review = (o.mapping_decisions || []).find((x) => x.file_version_id === vid);
  const fix = (o.files_requiring_replacement || []).find((x) => x.file_version_id === vid);
  const lines = typeof prev.data === 'string' ? prev.data.split('\n').filter((l, i, a) => l !== '' || i < a.length - 1) : [];
  const history = (d && d.history) || [];
  return <div className="rfb-drawer-host">
    <div className="rfb-drawer-catch" onClick={onClose} aria-hidden="true" />
    <Drawer label="File version" head={<div className="rf-row rf-row--top">
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="rf-dialog__eyebrow">{cat ? cat + ' · ' + catTitle(app, cat) : 'Evidence file'}</div>
        <h2 className="rf-dialog__title rf-ellipsis">{v ? v.original_filename : vid}</h2>
        <div className="rf-row rf-row--wrap" style={{ marginTop: 6 }}>{v && <Pill state={v.version_status} />}<span className="rf-mono rf-muted rfb-small">{vid}{v ? ' · v' + v.version_number : ''}</span></div>
      </div>
      <Button variant="quiet" size="sm" icon="x" aria-label="Close file detail" onClick={onClose} />
    </div>}
    foot={<>{review && <Act a={A.review} label="Open mapping review" variant="primary" icon="mapping" onClick={() => nav('cases/' + ref + '/review/' + encodeURIComponent(vid))} />}
      {fix && <Act a={A.upload_evidence} label="Upload corrected file" variant="primary" icon="upload" onClick={() => onUpload(fix.category)} />}
      <span className="rf-spacer" /><Button onClick={onClose}>Close</Button></>}>
      {fv.error ? <Err q={fv} /> : !v ? <Loading /> : <>
        <section className="rf-isec"><h3 className="rf-isec__title">Details</h3>
          {v.structure_error && <div style={{ marginBottom: 10 }}><Notice tone="danger" compact title="Structure check failed">{v.structure_error}</Notice></div>}
          <KV pairs={[
            ['File version', <Ref id={v.file_version_id} copy />],
            ['Version', 'v' + v.version_number],
            ['Status', <Pill state={v.version_status} />],
            ['Processing', v.processing_status ? <span className="rf-mono">{v.processing_status}</span> : null],
            ['Received', fmtDateTime(v.uploaded_at || v.received_at)],
            ['Source', v.source ? <Enum>{v.source}</Enum> : null],
            ['Intake', v.intake_id ? <span className="rf-mono">{v.intake_id}</span> : null],
            ['SHA-256', v.source_sha256 ? <Hash sha={v.source_sha256} /> : null]
          ].filter((x) => x[1] != null)} />
        </section>
        {(v.status_history || []).length > 0 && <section className="rf-isec"><h3 className="rf-isec__title">Status history</h3>
          <ol className="rfb-hist">{v.status_history.slice().reverse().map((h, i) => <li key={i}><Pill state={h.status} /><span className="rf-muted rf-mono rfb-small">{fmtDateTime(h.at)}</span></li>)}</ol></section>}
        {history.length > 0 && <section className="rf-isec"><h3 className="rf-isec__title">Version chain<span className="rf-spacer" /><span className="rf-muted">{history.length} version{history.length > 1 ? 's' : ''}</span></h3>
          <Versions versions={history.slice().reverse().map((h) => ({
            v: 'v' + h.version_number, current: h.file_version_id === vid,
            title: <><span className="rf-ellipsis">{h.original_filename}</span><Pill state={h.version_status} />{h.file_version_id === vid && <span className="rf-muted rfb-small">Viewing</span>}</>,
            meta: [['ID', <span className="rf-mono">{h.file_version_id}</span>], ['Received', fmtDateTime(h.uploaded_at || h.received_at)], ['SHA-256', h.source_sha256 ? <Hash sha={h.source_sha256} /> : '—']]
          }))} />
          <div className="rf-help" style={{ marginTop: 8 }}>Corrections are new versions. Earlier versions and their decisions are kept as history and are read-only.</div></section>}
        <section className="rf-isec"><h3 className="rf-isec__title">Mapping decisions</h3>
          {(d.decisions || []).length
            ? <Table dense columns={[{ key: 'col', label: 'Source column' }, { key: 'dec', label: 'Decision' }, { key: 'by', label: 'By · at' }]} rows={d.decisions.map((x, i) => ({ key: i, cells: {
              col: <span className="rf-srchdr">{x.source_header}</span>,
              dec: <><Enum>{(x.decision || x).action}</Enum>{(x.decision || x).canonical_field ? <span className="rf-mono"> → {(x.decision || x).canonical_field}</span> : null}</>,
              by: <span className="rf-muted rfb-small">{(x.decision || x).reviewer || '—'} · {fmtDateTime((x.decision || x).at)}</span> } }))} />
            : <span className="rf-muted">No mapping decisions recorded for this version.</span>}
        </section>
        <section className="rf-isec"><h3 className="rf-isec__title">Source columns</h3>
          {cols.error ? <Err q={cols} /> : !cols.data ? <Loading /> : (cols.data.columns || []).length
            ? <div className="rf-table-wrap"><table className="rf-samples"><thead><tr><th>Header (as received)</th><th>Samples</th><th className="rf-right">Rows</th><th className="rf-right">Empty</th><th className="rf-right">Distinct</th></tr></thead>
              <tbody>{cols.data.columns.map((col, i) => <tr key={i}><td>{col.source_header}</td><td className="rfb-wrap">{(col.samples || []).slice(0, 3).join(' · ')}</td><td className="rf-right">{col.rows != null ? col.rows : '—'}</td><td className="rf-right">{col.empty != null ? col.empty : '—'}</td><td className="rf-right">{col.distinct != null ? col.distinct : '—'}</td></tr>)}</tbody></table></div>
            : <span className="rf-muted">No column profile returned for this version.</span>}
        </section>
        <section className="rf-isec"><h3 className="rf-isec__title">Canonical preview<span className="rf-spacer" />{!wantPreview && <Button size="sm" icon="eye" onClick={() => setWantPreview(true)}>Load canonical preview</Button>}</h3>
          {!wantPreview ? <span className="rf-muted">The canonical preview is returned as CSV (whole file).</span>
            : prev.error ? <Err q={prev} /> : prev.data === undefined ? <Loading />
              : <><pre className="rfb-pre">{lines.slice(0, 20).join('\n')}</pre><div className="rf-help" style={{ marginTop: 6 }}>Showing {Math.min(20, lines.length)} of {lines.length} line(s).</div></>}
        </section>
        <section className="rf-isec"><h3 className="rf-isec__title">Events</h3>
          {(d.events || []).length ? <ol className="rfb-hist">{d.events.map((e, i) => <li key={e.event_id || i}><Enum>{e.event_type}</Enum><span className="rf-muted rfb-small">{e.actor_id ? e.actor_id + ' · ' : ''}{fmtDateTime(e.at)}</span></li>)}</ol> : <span className="rf-muted">No events recorded for this version.</span>}
        </section>
      </>}
    </Drawer>
  </div>;
}

function HistoryPanel({ c }) {
  const pid = c.package.package_id;
  const h = useQuery('hist:' + c.case_ref + ':' + pid, (svc) => svc.getPackageHistory(pid));
  const d = h.data;
  const passed = (v) => (v.passed != null ? v.passed : v.state === 'PASSED');
  return <Panel title="Package history" sub={<span className="rf-mono">{pid}</span>}>
    {h.error ? <Err q={h} /> : !d ? <Loading /> : <div className="rf-stack rf-stack--3">
      <div><div className="rf-isec__title">Validations</div>
        {(d.validations || []).length ? <ol className="rfb-hist">{d.validations.slice().reverse().map((v, i) => <li key={i}><Pill state={passed(v) ? 'PASSED' : 'FAILED'} /><div style={{ minWidth: 0 }}><div className="rf-secondary">{fmtDateTime(v.at)}{v.current === true ? ' · current' : v.current === false ? ' · out of date' : ''}</div>
          {(v.failed || []).length > 0 && <div className="rf-row rf-row--wrap" style={{ marginTop: 2 }}>{v.failed.map((id) => <Enum key={id}>{id}</Enum>)}</div>}</div></li>)}</ol>
          : <span className="rf-muted">No validation has run.</span>}</div>
      <div><div className="rf-isec__title">Snapshots</div>
        {(d.snapshots || []).length ? <ol className="rfb-hist">{d.snapshots.map((s, i) => <li key={s.snapshot_id || i}><Pill state="ACTIVE" /><div><span className="rf-mono">{s.snapshot_id}</span><div className="rf-muted rfb-small">{fmtDateTime(s.at || s.created_at)}{s.entries != null ? ' · ' + (Array.isArray(s.entries) ? s.entries.length : s.entries) + ' entries' : ''}</div></div></li>)}</ol>
          : <span className="rf-muted">No snapshot yet. A snapshot is created when the package is activated.</span>}</div>
      <div className="rf-muted rfb-small">{(d.categories || []).reduce((a, k) => a + ((k.versions || []).length), 0)} file version(s) received across {(d.categories || []).length} categor{(d.categories || []).length === 1 ? 'y' : 'ies'}.</div>
    </div>}
  </Panel>;
}

export default function EvidenceTab({ c, app, route, nav, openAction }) {
  const ref = c.case_ref, A = c.actions || {}, o = c.outstanding || {}, p = c.progress || {};
  const base = 'cases/' + ref + '/evidence';
  const [filter, setFilter] = React.useState('all');
  const [upload, setUpload] = React.useState(null);
  const qUpload = route.query ? route.query.upload : undefined;
  React.useEffect(() => { if (qUpload != null) setUpload(qUpload); }, [qUpload]);
  const closeUpload = React.useCallback(() => { setUpload(null); if (qUpload != null) nav(base + (route.sub ? '/' + encodeURIComponent(route.sub) : '')); }, [qUpload, route.sub, base, nav]);
  const closeDrawer = React.useCallback(() => nav(base), [nav, base]);

  if (!c.package) {
    return <div className="rf-workspace"><Panel><Empty icon="archive" title="Evidence appears after Smart Parsing"
      action={c.status === 'WAITING' ? <Act a={A.start} label="Start Smart Parsing" variant="primary" size={null} icon="play" onClick={() => openAction('start')} /> : null}>
      The original ZIP <span className="rf-mono">{c.zip && c.zip.filename}</span> is attached. Its files are classified into the evidence categories when Smart Parsing runs.</Empty></Panel></div>;
  }
  const cats = new Map(((app && app.categories) || []).map((k) => [k.category, k]));
  const needs = new Set([].concat((o.mapping_decisions || []).map((x) => x.category), (o.files_requiring_replacement || []).map((x) => x.category), (o.missing_categories || []).map((x) => x.category)));
  const slots = c.package.slots || [];
  const shown = slots.filter((s) => filter === 'all' || (filter === 'action' ? needs.has(s.evidence_category) : !s.latest));
  const op = p.current_operation;
  const missingN = slots.filter((s) => !s.latest).length;
  const rows = shown.map((s) => {
    const k = cats.get(s.evidence_category) || {}, l = s.latest;
    return { key: s.evidence_category, selected: !!(l && route.sub === l.file_version_id), className: needs.has(s.evidence_category) ? 'is-flagged' : (!l ? 'is-muted' : undefined),
      onClick: l ? () => nav(base + '/' + encodeURIComponent(l.file_version_id)) : undefined,
      cells: {
        cat: <><span className="rf-cell-main"><span className="rf-mono">{s.evidence_category}</span> {k.title || ''}</span><span className="rf-cell-sub">{k.format || ''}</span></>,
        req: <Tag kind={s.required ? 'REQUIRED' : 'OPTIONAL'} />,
        file: l ? <div className="rf-file"><Icon name={k.format === 'PDF' ? 'filePdf' : 'fileTable'} /><div style={{ minWidth: 0 }}><span className="rf-file__name">{l.original_filename}</span><span className="rf-file__path">{l.file_version_id} · v{l.version_number}</span></div></div> : <span className="rf-muted">No file</span>,
        status: l ? <Pill state={l.version_status} /> : <Missing required={s.required} />,
        proc: l && l.processing_status ? <span className="rf-mono rfb-small">{l.processing_status}</span> : null,
        ver: s.versions ? <span className="rf-num">{s.versions}</span> : null
      } };
  });
  const fixes = o.files_requiring_replacement || [], missing = missingNotUnreadable(o), refused = o.refused_uploads || [], unreadable = unreadableOf(o.unreadable_members);

  return <div className="rf-workspace rfb-evidence">
    {c.activation && <Notice tone="locked" title="Package ACTIVE · locked">Activated as <span className="rf-mono">{c.activation.snapshot_id}</span> by {c.activation.activated_by} · {fmtDateTime(c.activation.activated_at)}. Evidence can no longer change.</Notice>}
    {op && (op.kind === 'resubmission' || op.kind === 'intake') && <Notice tone="info" title={op.kind === 'resubmission' ? 'Processing an uploaded file' : 'Smart Parser run in progress'}>
      <span className="rf-row rf-row--wrap"><span className="rf-tone-progress"><Glyph name="progress" size={10} /></span>{op.job_id && <span className="rf-mono">{op.job_id}</span>}<span>{op.state}</span>{op.files_total != null && <span>· {op.files_processed || 0} of {op.files_total} file(s)</span>}{op.validation_running && <span>· validation running</span>}</span>
    </Notice>}
    <div className="rf-split rf-split--aside-lg">
      <div className="rf-stack">
        <Panel title="Evidence categories" sub={<>Package <span className="rf-mono">{c.package.package_id}</span> · <Pill state={c.package.package_status} /></>} flush
          actions={<div className="rf-row"><Segmented items={[['all', 'All ' + slots.length], ['action', 'Needs action ' + needs.size], ['missing', 'No file ' + missingN]]} active={filter} onChange={setFilter} /></div>}>
          {rows.length ? <Table dense caption="Evidence categories" columns={[{ key: 'cat', label: 'Category' }, { key: 'req', label: 'Required', cls: 'is-tight' }, { key: 'file', label: 'Latest file' }, { key: 'status', label: 'Status', cls: 'is-tight' }, { key: 'proc', label: 'Processing', cls: 'is-tight' }, { key: 'ver', label: 'Versions', cls: 'is-num' }]} rows={rows} />
            : <Empty icon="check" title={filter === 'action' ? 'Nothing needs action' : 'Every category has a file'}>Switch the filter to see all categories.</Empty>}
        </Panel>
        <HistoryPanel c={c} />
      </div>
      <div className="rf-stack">
        <Panel title="Upload evidence" sub="Missing or corrected files only">
          <div className="rf-stack rf-stack--3">
            <Act a={A.upload_evidence} label="Upload missing or corrected file" variant="primary" size={null} icon="upload" onClick={() => setUpload('')} />
            <div className="rf-help">Each upload is processed immediately and then validated automatically.</div>
          </div>
        </Panel>
        {unreadable.length > 0 && <Panel title="Unreadable in the original ZIP" sub={unreadable.length + ' file(s) · the rest of the ZIP was processed'}>
          <ul className="rf-tasks__list rfb-list">{unreadable.map((u, i) => <li key={i} className="rf-tasks__item" data-unreadable={u.name}><span className={u.open ? 'rf-tone-danger' : 'rf-tone-neutral'}><Glyph name={u.open ? 'resubmit' : 'success'} still /></span>
            <div style={{ minWidth: 0 }}><div className="rf-strong">File <span className="rf-mono">{u.name}</span> in the original ZIP could not be read{u.error ? ': ' + u.error : ''}</div>
              <div className="rf-tasks__detail">{u.open ? 'Upload a corrected file. Its category is decided by its content.' : 'No corrected file is needed now.'}{u.hint && u.open ? <div style={{ marginTop: 4 }}>{u.hint}</div> : null}</div>
              {u.open && <div style={{ marginTop: 6 }}><Act a={A.upload_evidence} label="Upload corrected file" icon="upload" onClick={() => setUpload('')} /></div>}</div><div /></li>)}</ul>
        </Panel>}
        <Panel title="Requires correction" sub={fixes.length + ' file(s)'}>
          {fixes.length ? <ul className="rf-tasks__list rfb-list">{fixes.map((f) => <li key={f.file_version_id} className="rf-tasks__item"><span className="rf-tone-danger"><Glyph name="resubmit" still /></span>
            <div style={{ minWidth: 0 }}><div className="rf-strong">{f.category} {catTitle(app, f.category)} <span className="rf-mono rf-muted">v{f.version}</span></div>
              <div className="rf-tasks__detail"><span className="rf-row rf-row--wrap"><Pill state={f.version_status} /><Enum>{f.cause}</Enum></span><div style={{ marginTop: 4 }}>{f.detail}</div></div>
              <div className="rf-row rf-row--wrap" style={{ marginTop: 6 }}><Button size="sm" variant="quiet" icon="eye" onClick={() => nav(base + '/' + encodeURIComponent(f.file_version_id))}>View file</Button><Act a={A.upload_evidence} label="Upload corrected file" icon="upload" onClick={() => setUpload(f.category)} /></div></div><div /></li>)}</ul>
            : <span className="rf-muted">No file requires correction.</span>}
        </Panel>
        <Panel title="Missing required" sub={missing.length + ' categor' + (missing.length === 1 ? 'y' : 'ies')}>
          {missing.length ? <ul className="rf-tasks__list rfb-list">{missing.map((m) => <li key={m.category} className="rf-tasks__item"><span className="rf-tone-danger"><Glyph name="danger" still /></span>
            <div style={{ minWidth: 0 }}><div className="rf-strong">{m.category} {m.title || catTitle(app, m.category)}</div><div className="rf-tasks__detail">{m.format || catInfo(app, m.category).format} · required · no file</div>
              <div style={{ marginTop: 6 }}><Act a={A.upload_evidence} label="Upload file" icon="upload" onClick={() => setUpload(m.category)} /></div></div><div /></li>)}</ul>
            : <span className="rf-muted">No required category is missing.</span>}
        </Panel>
        {refused.length > 0 && <Panel title="Refused uploads" sub="Nothing was changed by these uploads">
          <ol className="rfb-hist">{refused.map((r, i) => <li key={i}><span className="rf-tone-neutral"><Glyph name="na" /></span><div style={{ minWidth: 0 }}><div className="rf-mono rf-ellipsis">{r.filename}</div><div className="rf-secondary">{r.evidence_category} · {r.reason}</div><div className="rf-muted rfb-small">{fmtDateTime(r.at)}</div>{r.source_sha256 && <Hash sha={r.source_sha256} />}</div></li>)}</ol>
        </Panel>}
      </div>
    </div>
    {route.sub && <FileDrawer c={c} app={app} vid={route.sub} nav={nav} onClose={closeDrawer} onUpload={(cat) => setUpload(cat)} />}
    {upload != null && <UploadDialog c={c} app={app} initial={upload} onClose={closeUpload} />}
  </div>;
}
