import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/ringfence.js";
import { Action, Button, Dialog, Drawer, Empty, Enum, Hash, Icon, KV, MutationError, Notice, Panel, Pill, Skeleton,
         StepStrip, bytes, usePolling, when } from "../components/ui.jsx";
import { useApp } from "../main.jsx";
import Review from "./Review.jsx";
import Reconciliation from "./Reconciliation.jsx";

const TABS = [["overview", "Overview"], ["parser", "Smart Parser"], ["evidence", "Evidence"], ["review", "Review"],
  ["package", "Validation & activation"], ["recon", "Reconciliation"], ["activity", "Activity"]];

export default function CaseScreen({ caseRef, tab, sub }) {
  const { app, refreshSlot } = useApp();
  const [c, setC] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState("");
  const [dialog, setDialog] = useState(null);
  const load = useCallback(() => api.caseDetail(caseRef).then((d) => { setC(d); setLoadError(null); return d; })
    .catch((e) => { setLoadError(e); return null; }), [caseRef]);
  const running = !!(c && (c.deferring || c.progress.current_operation ||
    (c.current_run && c.current_run.status === "PROCESSING")));
  const reconRunning = !!(c && c.progress.reconciliation.state === "RUNNING");
  usePolling(load, running ? 3000 : 5000, running || reconRunning, [caseRef]);

  // every mutation: loading state, structured error, refetch the backend state afterwards (never optimistic)
  const mutate = async (key, fn) => {
    setBusy(key); setError(null);
    try { const r = await fn(c ? c.revision : undefined); await load(); refreshSlot(); return r || true; }
    catch (e) { setError(e); if (e.code === "CASE_CHANGED") await load(); return null; }
    finally { setBusy(""); }
  };

  if (!c) return <div className="rf-page">{loadError ? <MutationError error={loadError} /> : <Skeleton lines={6} />}</div>;
  const a = c.actions, p = c.progress;
  const counts = { evidence: c.outstanding.missing_categories.length + c.outstanding.files_requiring_replacement.length +
    c.outstanding.refused_uploads.length, review: p.decisions_outstanding, parser: c.failed_runs };
  return <div className="rf-page">
    <header className="rf-casehead">
      <div className="rf-breadcrumb"><a href="#/queue">Work queue</a><Icon name="chevronRight" size={12} />
        <a href={"#/customers/" + c.customer_id}>{c.customer_name}</a><Icon name="chevronRight" size={12} />
        <span className="rf-mono">{c.case_ref}</span></div>
      <div className="rf-casehead__top"><div>
        <h1 className="rf-casehead__title">{c.customer_name} — {c.reporting_period}</h1>
        <div className="rf-casehead__meta"><span>Case <span className="rf-id">{c.case_ref}</span></span>
          <span>ZIP <b>{c.zip.filename}</b> ({bytes(c.zip.size)})</span><span>Received <b>{when(c.created_at)}</b></span>
          <span>Status since <b>{when(c.status_since)}</b></span>
          {c.other_cases_for_period > 0 && <span>{c.other_cases_for_period} other case(s) for this period</span>}</div>
        <div className="rf-casehead__state rf-gap" id="case-status"><Pill k={c.deferring ? "DEFERRING" : c.status} large />
          <Enum>{c.status}</Enum><StepStrip steps={c.steps} /></div>
      </div>
        <div className="rf-casehead__actions rf-casebar">
          {c.status === "WAITING" && <Action id="act-start" spec={a.start} variant="primary" icon="play" busy={busy === "start"}
            onClick={() => setDialog("start")}>Start Smart Parsing</Action>}
          {c.status === "PENDING" && <Action id="act-resume" spec={a.resume} variant="primary" icon="play" busy={busy === "resume"}
            onClick={() => setDialog("resume")}>Resume Processing</Action>}
          {c.status === "IN_PROGRESS" && <Action id="act-defer" spec={a.defer} icon="pause" busy={busy === "defer"}
            onClick={() => setDialog("defer")}>Defer Case</Action>}
          {a.retry_from_beginning.enabled && <Action id="act-retry" spec={a.retry_from_beginning} variant="danger" icon="refresh"
            busy={busy === "retry"} onClick={() => setDialog("retry")}>Retry from Beginning</Action>}
        </div></div>
      <nav className="rf-tabbar" role="tablist" aria-label="Case lifecycle">{TABS.map(([k, label]) =>
        <a key={k} role="tab" id={"tab-" + k} href={`#/case/${caseRef}/${k}`} aria-selected={tab === k}
          className={tab === k ? "is-active" : ""}>{label}{counts[k] ? <span className="rf-tabbar__n">{counts[k]}</span> : null}</a>)}</nav>
    </header>

    <StatusBanner c={c} />
    <MutationError error={error} onReload={load} />

    {tab === "overview" && <Overview c={c} />}
    {tab === "parser" && <Parser c={c} caseRef={caseRef} running={running} />}
    {tab === "evidence" && <Evidence c={c} caseRef={caseRef} mutate={mutate} busy={busy} />}
    {tab === "review" && <Review c={c} caseRef={caseRef} vid={sub} mutate={mutate} busy={busy} reloadCase={load} />}
    {tab === "package" && <Package c={c} mutate={mutate} busy={busy} caseRef={caseRef} />}
    {tab === "recon" && <Reconciliation c={c} caseRef={caseRef} mutate={mutate} busy={busy} />}
    {tab === "activity" && <Activity c={c} caseRef={caseRef} />}

    {dialog === "start" && <Dialog title="Start Smart Parsing" eyebrow={c.case_ref} onClose={() => setDialog(null)}
      foot={<><Button onClick={() => setDialog(null)}>Cancel</Button><Button id="confirm-start" variant="primary" icon="play"
        onClick={async () => { setDialog(null); if (await mutate("start", (r) => api.start(caseRef, r))) window.location.hash = `#/case/${caseRef}/parser`; }}>Start Smart Parsing</Button></>}>
      <p>Only this case is processed: <b>{c.customer_name}</b>, {c.reporting_period}. It becomes the case In Progress.</p>
      <KV pairs={[["Input ZIP", c.zip.filename], ["SHA-256", <Hash sha={c.zip.sha256} />],
        ["LLM proposals", app && app.llm ? app.llm.label : "…"]]} /></Dialog>}
    {dialog === "defer" && <Dialog title="Defer case" eyebrow={c.case_ref} onClose={() => setDialog(null)}
      foot={<><Button onClick={() => setDialog(null)}>Cancel</Button><Button id="confirm-defer" variant="primary"
        onClick={async () => { setDialog(null); await mutate("defer", (r) => api.defer(caseRef, r)); }}>Defer case</Button></>}>
      <p>Completed work and saved decisions are kept. {p.current_operation ? "The running operation finishes and its result is saved first; until then the case shows Deferral requested." : "The case becomes Pending and the active slot is released."}</p></Dialog>}
    {dialog === "resume" && <Dialog title="Resume processing" eyebrow={c.case_ref} onClose={() => setDialog(null)}
      foot={<><Button onClick={() => setDialog(null)}>Cancel</Button><Button id="confirm-resume" variant="primary" icon="play"
        onClick={async () => { setDialog(null); if (await mutate("resume", (r) => api.resume(caseRef, r))) window.location.hash = `#/case/${caseRef}/overview`; }}>Resume processing</Button></>}>
      <p>The case becomes In Progress. Kept work is not repeated:</p><ul className="rf-tasklist">{c.kept.map((k, i) => <li key={i}>{k}</li>)}</ul></Dialog>}
    {dialog === "retry" && <Dialog title="Retry from beginning" eyebrow={c.case_ref} onClose={() => setDialog(null)}
      foot={<><Button onClick={() => setDialog(null)}>Cancel</Button><Button id="confirm-retry" variant="danger" icon="refresh"
        onClick={async () => { setDialog(null); await mutate("retry", (r) => api.retry(caseRef, r)); }}>Start a fresh run</Button></>}>
      <p>A new run processes the <b>original ZIP</b> from the beginning into a new evidence package. The failed run {c.current_run && c.current_run.run_id} and its logs stay in the history, read-only.</p>
      <p>Files uploaded during the failed run are not carried forward; upload them again in the new run.</p></Dialog>}
  </div>;
}

function StatusBanner({ c }) {
  if (c.deferring) return <Notice tone="attention" title="Deferral requested">The case becomes Pending when the running operation
    ({c.deferral.waiting_for.map((w) => w.kind).join(", ")}) has finished and saved its result. No new operation can start.</Notice>;
  if (c.status === "WAITING") return <Notice tone="info" title="Waiting">The original ZIP is attached; Smart Parsing has not started. Opening the case does not start it.
    {c.blocked_by ? ` Start is unavailable while ${c.blocked_by.case_ref} (${c.blocked_by.customer_name}) is In Progress.` : ""}</Notice>;
  if (c.status === "PENDING") return <Notice tone="info" title="Pending · inspect only">Saved work is kept. Nothing can change until you resume the case.
    {c.blocked_by ? ` Resume is unavailable while ${c.blocked_by.case_ref} (${c.blocked_by.customer_name}) is In Progress.` : ""}</Notice>;
  if (c.status === "COMPLETED") return <Notice tone="success" title="Completed">Reconciliation finished{c.completed ? ` (${c.completed.case_status})` : ""}. No correction or reactivation is possible.</Notice>;
  if (c.current_run && c.current_run.status === "FAILED") return <Notice tone="danger" title={`Smart Parser run ${c.current_run.run_id} failed`}>
    <Enum>{c.current_run.failure.code}</Enum> {c.current_run.failure.message} The original ZIP and earlier runs are unchanged.</Notice>;
  return null;
}

function Overview({ c }) {
  const o = c.outstanding, p = c.progress;
  const empty = !o.mapping_decisions.length && !o.missing_categories.length && !o.files_requiring_replacement.length &&
    !o.refused_uploads.length && !o.other.length;
  return <div className="rf-grid-2">
    <Panel title="Outstanding tasks" sub={c.status === "PENDING" ? "Read-only until the case is resumed" : "From the backend"} id="outstanding">
      {empty ? <span className="rf-muted">Nothing outstanding</span> : <ul className="rf-tasklist">
        {o.mapping_decisions.map((m) => <li key={m.file_version_id}><a href={`#/case/${c.case_ref}/review/${m.file_version_id}`}>
          {m.category} {m.file_name}</a>: {m.outstanding} of {m.total} column decision(s) outstanding ({m.columns.join(", ")})</li>)}
        {o.missing_categories.map((m) => <li key={m.category}>Missing required evidence: <a href={`#/case/${c.case_ref}/evidence`}>{m.category} {m.title}</a> ({m.format})</li>)}
        {o.files_requiring_replacement.map((f) => <li key={f.file_version_id}>Replace {f.category} v{f.version} ({f.cause === "COLUMN_REJECTED" ? "rejected" : "structure failed"}): <span className="rf-muted">{f.detail}</span></li>)}
        {o.refused_uploads.length > 0 && <li>{o.refused_uploads.length} uploaded file(s) not accepted: <a href={`#/case/${c.case_ref}/evidence`}>see Evidence</a></li>}
        {o.other.map((x) => <li key={x.kind}><Enum>{x.kind}</Enum> {x.detail}</li>)}</ul>}
    </Panel>
    <Panel title="Where this case stands"><ul className="rf-summary" id="progress-summary">{p.summary.map((s, i) => <li key={i}>{s}</li>)}</ul>
      {c.kept.length > 0 && <><div className="rf-label rf-mt">Kept work</div><ul className="rf-summary">{c.kept.map((k, i) => <li key={i}>{k}</li>)}</ul></>}</Panel>
    <Panel title="Original submission"><KV pairs={[["File", c.zip.filename], ["Size", bytes(c.zip.size)], ["SHA-256", <Hash sha={c.zip.sha256} />],
      ["Received", when(c.created_at)], ["Customer", `${c.customer_name} (${c.customer_id})`], ["Last activity", when(c.last_activity_at)],
      ["Started", c.started ? `${c.started.by} · ${when(c.started.at)}` : "not started"]]} /></Panel>
    <Panel title="Status history"><ol className="rf-summary" id="status-history">{c.status_history.map((h, i) =>
      <li key={i}><Pill k={h.status} /> {when(h.at)} <span className="rf-muted">{h.note}</span></li>)}</ol></Panel>
  </div>;
}

function Parser({ c, caseRef, running }) {
  const runs = [...c.runs].reverse();
  const [sel, setSel] = useState(runs[0] ? runs[0].run_id : null);
  const [run, setRun] = useState(null);
  const loadRun = useCallback(() => sel ? api.run(caseRef, sel).then(setRun).catch(() => {}) : null, [caseRef, sel]);
  usePolling(loadRun, 3000, running, [sel, c.revision]);
  if (!runs.length) return <Panel><Empty title="No runs yet">Start Smart Parsing from the case header.</Empty></Panel>;
  return <div className="rf-split rf-split--aside-lg">
    <Panel title={run ? `Run ${run.run_no} · ${run.run_id}` : "Run"} sub={run ? `Package ${run.package_id} · started ${when(run.started_at)} by ${run.started_by}${run.retry_of ? " · retry of " + run.retry_of : ""} · evidence: ${run.evidence_source}` : ""}
      actions={run && <Pill k={"RUN_" + run.status} />} id="run-panel">
      {!run ? <Skeleton /> : <div className="rf-stack">
        {run.failure && <Notice tone="danger" title={run.failure.code}>{run.failure.message}</Notice>}
        {run.not_carried_forward && run.not_carried_forward.length > 0 && <Notice tone="attention" title="Not carried forward from the failed run">
          Upload again if still needed: {run.not_carried_forward.flatMap((j) => j.files.map((f) => `${f.name}${f.category ? " (" + f.category + ")" : ""}`)).join(", ")}</Notice>}
        <ol className="rf-stages" id="stages">{run.stages.map((s, i) => <li key={s.key} data-stage={s.key}
          className={"rf-stage is-" + ({ completed: "done", running: "running", failed: "failed", requires_review: "attention",
            requires_attention: "attention", not_required: "skipped", blocked: "attention" }[s.status] || "pending")}>
          <span className="rf-stage__glyph"><span className="rf-stage__num">{i + 1}</span></span>
          <div><div className="rf-stage__head"><span className="rf-stage__name">{s.title}</span> <Enum>{s.status}</Enum></div>
            <div className="rf-stage__desc">{s.explanation}{s.evidence ? ` · ${s.evidence}` : ""}</div></div>
          <div className="rf-stage__meta rf-muted rf-small">{s.finished_at ? when(s.finished_at) : ""}</div></li>)}</ol>
        {run.intake_job && run.intake_job.trace && <details><summary>Failure log</summary><pre className="rf-codeblock">{run.intake_job.trace}</pre></details>}
        <div className="rf-small rf-muted">LLM proposals: {run.llm_mode ? run.llm_mode.label : ""}</div></div>}
    </Panel>
    <div className="rf-stack">
      <Panel title="Runs for this case" flush><table className="rf-table rf-table--dense" id="runs-table"><tbody>{runs.map((r) =>
        <tr key={r.run_id} className={"rf-clickable" + (r.run_id === sel ? " is-selected" : "")} onClick={() => setSel(r.run_id)}>
          <td className="rf-mono">{r.run_id}</td><td><Pill k={"RUN_" + r.status} /></td><td className="rf-nowrap">{when(r.started_at)}</td></tr>)}</tbody></table></Panel>
      {run && run.intake_job && <Panel title="Files" flush><table className="rf-table rf-table--dense"><tbody>{run.intake_job.files.map((f, i) =>
        <tr key={i}><td className="rf-mono">{f.name}</td><td>{f.state}</td><td>{f.outcome ? (f.outcome.version_status ? <Pill k={f.outcome.version_status} /> :
          <span className="rf-small">{f.outcome.refused_reason || f.outcome.error}</span>) : "—"}</td></tr>)}</tbody></table></Panel>}
      {run && run.events.length > 0 && <Panel title="Run events" flush><div className="rf-log" role="log" aria-live="polite">{run.events.slice(-40).map((e) =>
        <div key={e.seq} className="rf-log__row"><span className="rf-log__time">{when(e.at)}</span><span className="rf-log__msg rf-mono">{e.event_type}</span></div>)}</div></Panel>}
    </div></div>;
}

function Upload({ c, caseRef, category, label, mutate, busy }) {
  const ref = useRef(null);
  const can = c.actions.upload_evidence;
  const key = "upload-" + category;
  return <><input ref={ref} type="file" hidden id={"file-" + category} onChange={async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (f) await mutate(key, (r) => api.uploadEvidence(caseRef, f, category, r));
  }} />
    <Button size="sm" icon="upload" id={key} busy={busy === key} disabled={!can.enabled} title={can.reason || ""}
      onClick={() => ref.current.click()}>{label}</Button></>;
}

function Evidence({ c, caseRef, mutate, busy }) {
  const o = c.outstanding;
  const [drawer, setDrawer] = useState(null);
  const slots = c.package ? c.package.slots : [];
  return <div className="rf-stack">
    {!c.actions.upload_evidence.enabled && <Notice tone="locked" title="Uploads unavailable">{c.actions.upload_evidence.reason}</Notice>}
    <Panel title="Missing required evidence" sub="No file has been received for these categories" id="missing-panel">
      {o.missing_categories.length === 0 ? <span className="rf-muted">None</span> : <table className="rf-table rf-table--dense"><tbody>
        {o.missing_categories.map((m) => <tr key={m.category} data-missing={m.category}><td><Pill k="MISSING" /></td>
          <td className="rf-mono">{m.category}</td><td>{m.title} · {m.format}</td>
          <td className="rf-right"><Upload c={c} caseRef={caseRef} category={m.category} label="Upload file" mutate={mutate} busy={busy} /></td></tr>)}</tbody></table>}
    </Panel>
    <Panel title="Files requiring replacement" sub="A corrected version is required" id="correction-panel">
      {o.files_requiring_replacement.length === 0 ? <span className="rf-muted">None</span> : <table className="rf-table rf-table--dense"><tbody>
        {o.files_requiring_replacement.map((f) => <tr key={f.file_version_id} data-correction={f.category}><td><Pill k={f.version_status} /></td>
          <td className="rf-mono">{f.category}</td><td>v{f.version} · <Enum>{f.cause}</Enum><div className="rf-small rf-muted">{f.detail}</div></td>
          <td className="rf-right"><Upload c={c} caseRef={caseRef} category={f.category} label="Upload corrected file" mutate={mutate} busy={busy} /></td></tr>)}</tbody></table>}
    </Panel>
    {o.refused_uploads.length > 0 && <Panel title="Files not accepted" sub="Upload the file again under the missing category it belongs to (the content is still checked)">
      <table className="rf-table rf-table--dense"><tbody>{o.refused_uploads.map((u, i) => <tr key={i}><td className="rf-mono">{u.filename}</td>
        <td className="rf-small">{u.reason}</td><td><Hash sha={u.source_sha256} /></td></tr>)}</tbody></table></Panel>}
    <Panel title="Evidence inventory" flush>{slots.length === 0 ? <Empty title="No package yet">Start Smart Parsing to process the ZIP.</Empty> :
      <div className="rf-table-wrap"><table className="rf-table rf-table--dense" id="inventory"><thead><tr><th>Category</th><th>Required</th>
        <th>Latest file</th><th>Versions</th><th>Status</th></tr></thead>
        <tbody>{slots.map((s) => <tr key={s.evidence_category} className={s.latest ? "rf-clickable" : ""}
          onClick={() => s.latest && setDrawer(s)}><td className="rf-mono">{s.evidence_category}</td><td>{s.required ? "Required" : "Optional"}</td>
          <td className="rf-mono">{s.latest ? s.latest.original_filename : "—"}</td><td>{s.versions}</td>
          <td>{s.latest ? <Pill k={s.latest.version_status} /> : <Pill k={s.required ? "MISSING" : "RECEIVED"} label={s.required ? "Missing" : "Not supplied"} />}</td></tr>)}</tbody></table></div>}</Panel>
    {drawer && <FileDrawer pid={c.package.package_id} slot={drawer} onClose={() => setDrawer(null)} />}
  </div>;
}

function FileDrawer({ pid, slot, onClose }) {
  const [v, setV] = useState(null);
  const [cols, setCols] = useState(null);
  useEffect(() => {
    api.fileVersion(pid, slot.latest.file_version_id).then(setV).catch(() => setV(null));
    api.fileColumns(pid, slot.latest.file_version_id).then(setCols).catch(() => setCols(null));
  }, [pid, slot]);
  return <Drawer title={`${slot.evidence_category} · ${slot.latest.original_filename}`} sub={`version ${slot.latest.version_number}`} onClose={onClose}>
    {!v ? <Skeleton /> : <>
      <KV pairs={[["Status", <Pill k={v.version.version_status} />], ["SHA-256", <Hash sha={v.version.source_sha256} />],
        ["Intake", <span className="rf-mono">{v.version.intake_id}</span>], ["Processing", <Enum>{v.version.processing_status}</Enum>],
        ["Reasons", v.version.reasons.slice(-3).join(" · ")]]} />
      <Panel title="Version history" flush><table className="rf-table rf-table--dense"><tbody>{v.history.map((h) =>
        <tr key={h.file_version_id}><td>v{h.version_number}</td><td className="rf-mono">{h.original_filename}</td><td><Pill k={h.version_status} /></td></tr>)}</tbody></table></Panel>
      {cols && cols.columns && cols.columns.length > 0 && <Panel title="Source columns" flush><table className="rf-table rf-table--dense"><tbody>
        {cols.columns.map((x) => <tr key={x.source_index}><td className="rf-mono">{x.source_header}</td>
          <td><div className="rf-samples-inline">{x.samples.slice(0, 3).map((s, i) => <code key={i}>{s}</code>)}</div></td></tr>)}</tbody></table></Panel>}</>}
  </Drawer>;
}

function Package({ c, mutate, busy, caseRef }) {
  const [ack, setAck] = useState(false);
  const [snap, setSnap] = useState(null);
  const v = c.package && c.package.latest_validation;
  const pv = c.progress.validation;
  useEffect(() => {
    if (c.activation) api.snapshot(c.package.package_id, c.activation.snapshot_id).then(setSnap).catch(() => setSnap(null));
  }, [c.activation && c.activation.snapshot_id]);
  return <div className="rf-stack">
    <Panel title="Package validation" sub={pv.state === "NOT_RUN" ? "Runs automatically after processing" :
      `${pv.state} · ${when(pv.at)}${pv.current === false ? " · out of date" : ""} · runs automatically`}>
      {!v ? <Empty title="Not validated yet">Validation runs at the end of Smart Parsing and after every upload or review confirmation.</Empty> :
        <table className="rf-table rf-table--dense" id="pv-table"><tbody>{v.checks.map((ch) => <tr key={ch.check_id}>
          <td className="rf-mono">{ch.check_id}</td><td>{ch.name}</td><td><Pill k={ch.passed ? "PASS" : "FAIL"} /></td>
          <td className="rf-small">{ch.passed ? "" : ch.detail}</td></tr>)}</tbody></table>}
    </Panel>
    <Panel title="Activation" sub="One activation per case; the package becomes immutable; no second approver">
      {c.activation ? <div className="rf-stack" id="activation-result"><div className="rf-gap"><Pill k="ACTIVE" large /> <span className="rf-mono">{c.activation.snapshot_id}</span></div>
        <KV pairs={[["Activated by", c.activation.activated_by || "—"], ["Activated at", when(c.activation.activated_at)],
          ["Manifest SHA-256", c.activation.manifest_sha256 ? <Hash sha={c.activation.manifest_sha256} /> : "—"],
          ["Snapshot verification", snap ? snap.verification.map((x) => `${x.check_id} ${x.passed ? "pass" : "FAIL"}`).join(" · ") : "…"],
          ["Files", snap ? String(snap.snapshot.entries.length) : "…"]]} /></div> :
        <div className="rf-stack">
          <label className="rf-gap"><input type="checkbox" id="ack" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            I confirm the validated evidence set should be sealed as an immutable snapshot for reconciliation.</label>
          <Action id="act-activate" spec={ack ? c.actions.activate : { enabled: false, reason: c.actions.activate.reason || "tick the confirmation first" }}
            variant="primary" icon="lock" busy={busy === "activate"}
            onClick={() => mutate("activate", (r) => api.activate(caseRef, r))}>Activate package</Action></div>}
    </Panel></div>;
}

function Activity({ c, caseRef }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.caseActivity(caseRef).then(setD).catch(setError); }, [caseRef, c.revision]);
  if (error) return <MutationError error={error} />;
  if (!d) return <Skeleton />;
  return <div className="rf-stack">
    <Panel title="Case status changes"><ol className="rf-summary">{d.status_history.map((h, i) => <li key={i}>
      {i > 0 ? <><Pill k={d.status_history[i - 1].status} /> → </> : null}<Pill k={h.status} /> {when(h.at)} <span className="rf-muted">{h.note}</span></li>)}</ol></Panel>
    <Panel title="Activity" sub={d.chain.verified ? `Audit chain verified (${d.chain.events} events in the log)` : "Audit chain NOT verified"} flush>
      <div className="rf-table-wrap"><table className="rf-table rf-table--dense" id="activity-table"><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Details</th></tr></thead>
        <tbody>{d.events.slice(0, 400).map((e) => <tr key={e.event_id}><td className="rf-nowrap">{when(e.at)}</td><td className="rf-mono">{e.event_type}</td>
          <td>{e.actor_role === "system" || !e.actor_id ? <span className="rf-muted">system</span> : <span className="rf-mono">{e.actor_id}</span>}</td>
          <td className="rf-small">{Object.entries(e.details).filter(([k]) => k !== "case_ref").slice(0, 4).map(([k, v]) =>
            `${k}: ${typeof v === "object" ? JSON.stringify(v).slice(0, 70) : String(v).slice(0, 70)}`).join(" · ")}</td></tr>)}</tbody></table></div></Panel>
  </div>;
}
