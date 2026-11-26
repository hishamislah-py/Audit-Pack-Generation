import React, { useEffect, useState, useCallback, useRef } from "react";
import { get, post, stageFile } from "./api.js";
import { Pill, Panel, Button, Action, Dialog, ErrorBox, Notice, KV, Hash, Enum, Icon, when, bytes } from "./ui.jsx";
import Review from "./Review.jsx";

const TABS = [["overview", "Overview"], ["parser", "Smart Parser"], ["evidence", "Evidence"], ["review", "Review"],
  ["validation", "Validation & activation"], ["recon", "Reconciliation"], ["activity", "Activity"]];

export default function CaseView({ caseRef, tab, sub, app }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState(null);
  const load = useCallback(() => get("cases/" + caseRef).then((d) => { setC(d); return d; }).catch(setError), [caseRef]);
  useEffect(() => { load(); }, [load]);
  // poll only while the backend reports work in flight
  const live = c && (c.deferring || (c.progress && c.progress.current_operation) || (c.current_run && c.current_run.status === "PROCESSING"));
  useEffect(() => { if (!live) return; const t = setInterval(load, 1500); return () => clearInterval(t); }, [live, load]);

  const run = async (key, path, body) => {
    setBusy(key); setError(null);
    try { const r = await post(path, body); await load(); return r; } catch (e) { setError(e); await load(); return null; } finally { setBusy(""); }
  };
  if (!c) return <div className="rf-page">{error ? <ErrorBox error={error} /> : "Loading…"}</div>;
  const a = c.actions, p = c.progress;
  const statusKey = c.deferring ? "DEFERRING" : c.status;
  const tabCount = { evidence: p.missing_required.length + p.correction_required.length + p.refused_uploads.length,
    review: p.decisions_outstanding, parser: c.failed_runs };
  return <div className="rf-page">
    <header className="rf-casehead">
      <div className="rf-breadcrumb"><a href="#/queue">Work queue</a><Icon name="chevronRight" size={12} /><span>{c.customer_name}</span>
        <Icon name="chevronRight" size={12} /><span className="rf-mono">{c.case_ref}</span></div>
      <div className="rf-casehead__top"><div>
        <h1 className="rf-casehead__title">{c.customer_name} — {c.reporting_period}</h1>
        <div className="rf-casehead__meta"><span>Case <span className="rf-id">{c.case_ref}</span></span>
          <span>ZIP <b>{c.zip.filename}</b> ({bytes(c.zip.size)})</span><span>Received <b>{when(c.created_at)}</b></span>
          <span>Started by <b>{c.started ? c.started.by : "not started"}</b></span></div>
        <div className="rf-casehead__state" id="case-status"><Pill k={statusKey} large /> <Enum>{c.status}</Enum></div>
      </div>
        <div className="rf-casehead__actions rf-casebar">
          {c.status === "WAITING" && <Action id="act-start" spec={a.start} variant="primary" icon="play" busy={busy === "start"}
            onClick={() => setConfirm("start")}>Start Smart Parsing</Action>}
          {c.status === "PENDING" && <Action id="act-resume" spec={a.resume} variant="primary" icon="play" busy={busy === "resume"}
            onClick={() => run("resume", `cases/${caseRef}/resume`)}>Resume processing</Action>}
          {c.status === "IN_PROGRESS" && <Action id="act-defer" spec={a.defer} icon="pause" busy={busy === "defer"}
            onClick={() => run("defer", `cases/${caseRef}/defer`)}>Defer case</Action>}
          {a.retry_from_beginning.enabled && <Action id="act-retry" spec={a.retry_from_beginning} variant="danger" icon="refresh"
            onClick={() => setConfirm("retry")}>Retry from beginning</Action>}
        </div></div>
      <nav className="rf-tabbar" role="tablist">{TABS.map(([k, label]) => <a key={k} role="tab" href={`#/case/${caseRef}/${k}`}
        id={"tab-" + k} className={tab === k ? "is-active" : ""} aria-selected={tab === k}>{label}
        {tabCount[k] ? <span className="rf-tabbar__n">{tabCount[k]}</span> : null}</a>)}</nav>
    </header>

    {c.deferring && <Notice tone="attention" title="Deferral requested">The case moves to Pending when the running
      operation ({c.deferral.waiting_for.map((w) => w.kind).join(", ")}) has finished and saved its results. No new operation can start.</Notice>}
    {c.status === "PENDING" && <Notice tone="info" title="This case is pending">Opened read-only. Your saved progress is kept; choose
      Resume processing to continue{a.resume.enabled ? "" : ` (${a.resume.reason})`}.</Notice>}
    {c.status === "WAITING" && <Notice tone="info" title="Smart Parser has not started">The original ZIP is attached. Opening the case does not start processing.</Notice>}
    {c.status === "COMPLETED" && <Notice tone="success" title="Reconciliation finished">The case is completed. No correction or reactivation is possible.</Notice>}
    {c.current_run && c.current_run.status === "FAILED" && <Notice tone="danger" title={`Smart Parser run ${c.current_run.run_id} failed`}
      actions={a.retry_from_beginning.enabled && <Button variant="danger" icon="refresh" onClick={() => setConfirm("retry")}>Retry from beginning</Button>}>
      <Enum>{c.current_run.failure.code}</Enum> {c.current_run.failure.message} The original ZIP and the earlier runs are unchanged.</Notice>}
    <ErrorBox error={error} />

    {tab === "overview" && <Overview c={c} />}
    {tab === "parser" && <Parser c={c} />}
    {tab === "evidence" && <Evidence c={c} caseRef={caseRef} reload={load} setError={setError} />}
    {tab === "review" && <Review c={c} caseRef={caseRef} vid={sub} reload={load} />}
    {tab === "validation" && <Validation c={c} caseRef={caseRef} run={run} busy={busy} />}
    {tab === "recon" && <Recon c={c} caseRef={caseRef} run={run} busy={busy} />}
    {tab === "activity" && <Activity c={c} />}

    {confirm === "start" && <Dialog title="Start Smart Parsing" eyebrow={c.case_ref} onClose={() => setConfirm(null)}
      foot={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button id="confirm-start" variant="primary" icon="play"
        onClick={async () => { setConfirm(null); if (await run("start", `cases/${caseRef}/start`)) window.location.hash = `#/case/${caseRef}/parser`; }}>Start Smart Parsing</Button></>}>
      <p>Only this case is processed: <b>{c.customer_name}</b>, {c.reporting_period}.</p>
      <KV pairs={[["Input ZIP", c.zip.filename], ["SHA-256", <Hash sha={c.zip.sha256} />], ["LLM proposals", app && app.llm ? app.llm.label : "…"],
        ["Effect", "The case becomes In progress (the only active case) and run 1 starts from stage one."]]} /></Dialog>}
    {confirm === "retry" && <Dialog title="Retry from beginning" eyebrow={c.case_ref} onClose={() => setConfirm(null)}
      foot={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button id="confirm-retry" variant="danger" icon="refresh"
        onClick={async () => { setConfirm(null); await run("retry", `cases/${caseRef}/retry`, { confirm: true }); }}>Start a fresh run</Button></>}>
      <p>A new run with a new run ID processes the original ZIP from stage one into a new evidence package.</p>
      <p>The failed run {c.current_run && c.current_run.run_id} and its logs stay in the history, read-only. Nothing from it is reused.</p>
      <p>Corrections or missing files uploaded during the failed run are <b>not</b> carried forward: upload them again in the new run.</p></Dialog>}
  </div>;
}

function Overview({ c }) {
  const p = c.progress;
  return <div className="rf-grid-2">
    <Panel title="Where this case stands" sub="Computed by the backend from the package, jobs and runs">
      <ul className="rf-summary" id="progress-summary">{p.summary.map((s, i) => <li key={i}>{s}</li>)}</ul>
      {p.missing_required.length > 0 && <div className="rf-mt"><Notice tone="attention" title="Missing required evidence">
        {p.missing_required.map((m) => m.category + " " + m.title).join(" · ")}</Notice></div>}
    </Panel>
    <Panel title="Original submission">
      <KV pairs={[["File", c.zip.filename], ["Size", bytes(c.zip.size)], ["SHA-256", <Hash sha={c.zip.sha256} />],
        ["Received", when(c.created_at)], ["Customer", c.customer_name + " (" + c.customer_id + ")"], ["Last activity", when(c.last_activity_at)]]} />
    </Panel>
    <Panel title="Status history">
      <ol className="rf-summary" id="status-history">{c.status_history.map((h, i) => <li key={i}><Pill k={h.status} /> {when(h.at)} <span className="rf-muted">{h.note}</span></li>)}</ol>
    </Panel>
  </div>;
}

function Parser({ c }) {
  return <div className="rf-stack">{[...c.runs].reverse().map((r) => <Panel key={r.run_id} title={`Run ${r.run_no} · ${r.run_id}`}
    sub={`Package ${r.package_id} · started ${when(r.started_at)} by ${r.started_by}${r.retry_of ? " · retry of " + r.retry_of : ""}`}
    actions={<Pill k={"RUN_" + r.status} />}>
    {r.failure && <Notice tone="danger" title={r.failure.code}>{r.failure.message}</Notice>}
    {r.not_carried_forward && r.not_carried_forward.length > 0 && <Notice tone="attention" title="Not carried forward from the failed run">
      Upload again if still needed: {r.not_carried_forward.flatMap((j) => j.files.map((f) => `${f.name}${f.category ? " (" + f.category + ")" : ""}`)).join(", ")}</Notice>}
    {r.intake_job && <><div className="rf-small rf-muted">Intake job {r.intake_job.job_id}: {r.intake_job.state}
      {r.intake_job.finished_at ? " · finished " + when(r.intake_job.finished_at) : ""} · {r.staged_entries} file(s) from the ZIP
      {r.skipped_entries.length ? ` · ${r.skipped_entries.length} system entries skipped` : ""}</div>
      <div className="rf-table-wrap rf-mt"><table className="rf-table rf-table--dense"><thead><tr><th>File</th><th>State</th><th>Category</th><th>Outcome</th></tr></thead>
        <tbody>{r.intake_job.files.map((f, i) => <tr key={i}><td className="rf-mono">{f.name}</td><td>{f.state}</td>
          <td className="rf-mono">{(f.outcome || {}).evidence_category || "—"}</td>
          <td>{f.outcome ? (f.outcome.version_status ? <Pill k={f.outcome.version_status} /> : (f.outcome.refused_reason || f.outcome.error)) : "—"}</td></tr>)}</tbody></table></div>
      {r.intake_job.trace && <details className="rf-mt"><summary>Failure log</summary><pre className="rf-trace">{r.intake_job.trace}</pre></details>}</>}
  </Panel>)}
    {c.runs.length === 0 && <Panel><div className="rf-empty"><div className="rf-empty__title">No runs yet</div></div></Panel>}</div>;
}

function Uploader({ c, caseRef, category, label, reload, setError }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const can = c.actions.upload_evidence;
  const pick = async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    setBusy(true); setError(null);
    try { const sid = await stageFile(f); await post(`cases/${caseRef}/evidence`, { staging_id: sid, category }); await reload(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  };
  return <><input ref={ref} type="file" hidden id={"file-" + category} onChange={pick} />
    <Button size="sm" icon="upload" busy={busy} disabled={!can.enabled} title={can.reason || ""} id={"upload-" + category}
      onClick={() => ref.current.click()}>{label}</Button></>;
}

function Evidence({ c, caseRef, reload, setError }) {
  const p = c.progress;
  const cats = c.package ? c.package.slots : [];
  return <div className="rf-stack">
    {!c.actions.upload_evidence.enabled && <Notice tone="locked" title="Uploads unavailable">{c.actions.upload_evidence.reason}</Notice>}
    <Panel title="Missing required evidence" sub="No file has been received for these categories" id="missing-panel">
      {p.missing_required.length === 0 ? <span className="rf-muted">None</span> :
        <table className="rf-table rf-table--dense"><tbody>{p.missing_required.map((m) => <tr key={m.category} data-missing={m.category}>
          <td><Pill k="MISSING" /></td><td className="rf-mono">{m.category}</td><td>{m.title}</td>
          <td className="rf-right"><Uploader c={c} caseRef={caseRef} category={m.category} label="Upload file" reload={reload} setError={setError} /></td></tr>)}</tbody></table>}
    </Panel>
    <Panel title="Files requiring correction" sub="A file was received but a corrected version is required" id="correction-panel">
      {p.correction_required.length === 0 ? <span className="rf-muted">None</span> :
        <table className="rf-table rf-table--dense"><tbody>{p.correction_required.map((m) => <tr key={m.category} data-correction={m.category}>
          <td><Pill k={m.version_status} /></td><td className="rf-mono">{m.category}</td><td>{m.title} · v{m.version_number}<div className="rf-small rf-muted">{m.reason}</div></td>
          <td className="rf-right"><Uploader c={c} caseRef={caseRef} category={m.category} label="Upload corrected file" reload={reload} setError={setError} /></td></tr>)}</tbody></table>}
    </Panel>
    {p.refused_uploads.length > 0 && <Panel title="Files not accepted" sub="Upload again under the category the file is for">
      <table className="rf-table rf-table--dense"><tbody>{p.refused_uploads.map((u, i) => <tr key={i}><td className="rf-mono">{u.filename}</td>
        <td className="rf-small">{u.reason}</td><td><Hash sha={u.source_sha256} /></td></tr>)}</tbody></table></Panel>}
    <Panel title="Evidence inventory" flush>{cats.length === 0 ? <div className="rf-empty">No package yet</div> :
      <div className="rf-table-wrap"><table className="rf-table rf-table--dense"><thead><tr><th>Category</th><th>Required</th><th>Latest file</th><th>Versions</th><th>Status</th></tr></thead>
        <tbody>{cats.map((s) => <tr key={s.evidence_category}><td className="rf-mono">{s.evidence_category}</td><td>{s.required ? "Required" : "Optional"}</td>
          <td className="rf-mono">{s.latest ? s.latest.original_filename : "—"}</td><td>{s.versions}</td>
          <td>{s.latest ? <Pill k={s.latest.version_status} /> : <Pill k={s.required ? "MISSING" : "RECEIVED"} label={s.required ? "Missing" : "Not supplied"} />}</td></tr>)}</tbody></table></div>}</Panel>
  </div>;
}

function Validation({ c, caseRef, run, busy }) {
  const [ack, setAck] = useState(false);
  const v = c.package && c.package.latest_validation;
  const pv = c.progress.validation;
  return <div className="rf-stack">
    <Panel title="Package validation" sub={pv.state === "NOT_RUN" ? "Not run yet" : `${pv.state} · ${when(pv.at)}${pv.current === false ? " · out of date" : ""}`}
      actions={<Action id="act-validate" spec={c.actions.validate} busy={busy === "validate"} onClick={() => run("validate", `cases/${caseRef}/validate`)}>Run validation</Action>}>
      {!v ? <span className="rf-muted">Validation runs automatically after processing.</span> :
        <table className="rf-table rf-table--dense" id="pv-table"><tbody>{v.checks.map((ch) => <tr key={ch.check_id}><td className="rf-mono">{ch.check_id}</td>
          <td>{ch.name}</td><td><Pill k={ch.passed ? "PASS" : "FAIL"} /></td><td className="rf-small">{ch.passed ? "" : ch.detail}</td></tr>)}</tbody></table>}
    </Panel>
    <Panel title="Activation" sub={c.progress.activation ? "Activated as " + c.progress.activation.snapshot_id : "One activation per case; no second approver"}>
      {c.progress.activation ? <Pill k="ACTIVE" large /> : <div className="rf-stack">
        <label className="rf-gap"><input type="checkbox" id="ack" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I confirm the validated evidence set should be sealed as an immutable snapshot for reconciliation.</label>
        <Action id="act-activate" spec={ack ? c.actions.activate : { enabled: false, reason: c.actions.activate.reason || "tick the confirmation first" }}
          variant="primary" icon="lock" busy={busy === "activate"} onClick={() => run("activate", `cases/${caseRef}/activate`, { confirm: true })}>Activate package</Action></div>}
    </Panel></div>;
}

function Recon({ c, caseRef, run, busy }) {
  const r = c.progress.reconciliation;
  const [res, setRes] = useState(null);
  useEffect(() => { if (r.run_id) get("runs/" + r.run_id).then(setRes).catch(() => setRes(null)); }, [r.run_id]);
  return <div className="rf-stack">
    <Panel title="Reconciliation" sub={r.state === "NOT_RUN" ? "Not run" : r.state}
      actions={<Action id="act-reconcile" spec={c.actions.reconcile} variant="primary" busy={busy === "reconcile"} onClick={() => run("reconcile", `cases/${caseRef}/reconcile`)}>Run reconciliation</Action>}>
      {r.state === "RUNNING" && <Notice tone="info" title="Reconciliation running">The UC-042 engine is processing the active snapshot.</Notice>}
      {r.state === "FAILED" && <Notice tone="danger" title="Reconciliation failed">{r.error}</Notice>}
      {res && <><div className="rf-gap" id="recon-outcome"><Pill k={res.case_status} large /> <span>{res.exception_count} exception(s) · {res.total_results} control results</span></div>
        <div className="rf-table-wrap rf-mt"><table className="rf-table rf-table--dense"><thead><tr><th>Exception</th><th>Severity</th><th>Category</th><th>Account</th><th>Amount</th></tr></thead>
          <tbody>{res.exceptions.map((e) => <tr key={e.exception_id}><td className="rf-mono">{e.exception_id}</td><td>{e.severity}</td><td>{e.category}</td>
            <td className="rf-mono">{e.account_id}</td><td className="rf-mono">{e.amount}</td></tr>)}</tbody></table></div></>}
    </Panel></div>;
}

function Activity({ c }) {
  const [ev, setEv] = useState(null);
  const pid = c.package && c.package.package_id;
  useEffect(() => { get("activity" + (pid ? "?package_id=" + pid : "")).then(setEv).catch(() => setEv(null)); }, [pid, c.last_activity_at]);
  const rows = ev ? ev.events : [];
  return <Panel title="Activity" sub={ev ? (ev.chain.verified ? `Audit chain verified (${ev.chain.events} events)` : "Audit chain NOT verified") : "Loading…"} flush>
    <div className="rf-table-wrap"><table className="rf-table rf-table--dense"><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Details</th></tr></thead>
      <tbody>{rows.slice(0, 300).map((e) => <tr key={e.event_id}><td className="rf-nowrap">{when(e.at)}</td><td className="rf-mono">{e.event_type}</td>
        <td className="rf-mono">{e.actor_id || "system"}</td><td className="rf-small">{Object.entries(e.details).filter(([k]) => !["package_id"].includes(k))
          .slice(0, 4).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v).slice(0, 80) : String(v).slice(0, 80)}`).join(" · ")}</td></tr>)}</tbody></table></div></Panel>;
}
