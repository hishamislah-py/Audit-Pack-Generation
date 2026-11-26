import React, { useEffect, useState } from "react";
import { api } from "../api/ringfence.js";
import { Action, Button, Dialog, Drawer, Empty, Enum, KV, MutationError, Notice, Panel, Pill, Skeleton } from "../components/ui.jsx";

function ExceptionDrawer({ runId, excId, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.exception(runId, excId).then(setD).catch(setError); }, [runId, excId]);
  const e = d && d.exception;
  return <Drawer title={`Exception ${excId}`} sub={e ? `${e.severity} · ${e.category}` : ""} onClose={onClose}>
    <MutationError error={error} />
    {!d ? !error && <Skeleton /> : <>
      <Notice tone="info" title="Engine finding (read-only)">{d.note}</Notice>
      <KV pairs={[["Root cause", <span className="rf-mono">{e.root_cause}</span>], ["Account", <span className="rf-mono">{e.account_id || "—"}</span>],
        ["Currency", e.currency || "—"], ["Amount", <span className="rf-mono">{e.amount || "—"}</span>],
        ["Period", `${e.first_date || "—"} → ${e.last_date || "—"}`], ["Affected results", e.affected_results],
        ["Evidence status", e.evidence_status], ["Review status", <Enum>{e.review_status}</Enum>]]} />
      <Panel title={`Supporting evidence (${d.evidence.length})`} flush><ul className="rf-evlist" id="exception-evidence">{d.evidence.map((ev, i) =>
        <li key={i} className="rf-evitem"><div className="rf-mono rf-wrap">{ev.reference}</div>
          <div className="rf-small rf-muted">{ev.original_filename ? `${ev.original_filename} · version ${ev.version_number} · line ${ev.line ?? "—"}` : "not resolved to a file version"}</div>
          {ev.row && <div className="rf-small rf-wrap rf-mono">{Object.entries(ev.row).map(([k, v]) => `${k}=${v}`).join(" · ")}</div>}</li>)}</ul></Panel>
      <Panel title="Affected control results" flush><table className="rf-table rf-table--dense"><tbody>{d.affected_control_results.map((a, i) =>
        <tr key={i}><td className="rf-mono">{a.check_id}</td><td className="rf-mono">{a.scope}</td><td>{a.outcome && <Pill k={a.outcome} />}</td>
          <td className="rf-small">{a.control_result ? a.control_result.note : a.text}</td></tr>)}</tbody></table></Panel>
      {d.investigation_group && <Panel title="Engine investigation group (read-only)"><pre className="rf-codeblock">{JSON.stringify(d.investigation_group, null, 1)}</pre></Panel>}</>}
  </Drawer>;
}

export default function Reconciliation({ c, caseRef, mutate, busy }) {
  const r = c.progress.reconciliation;
  const runId = r.run_id || (c.completed && c.completed.reconciliation_run_id);
  const [res, setRes] = useState(null);
  const [error, setError] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const [exc, setExc] = useState(null);
  useEffect(() => { if (runId) api.reconRun(runId).then(setRes).catch(setError); }, [runId]);
  const failedJobs = c.package ? c.package.jobs.filter((j) => j.kind === "reconciliation" && j.state === "failed") : [];
  const o = res && res.outcomes;
  return <div className="rf-stack">
    <Panel title="Reconciliation" sub={c.activation ? `Snapshot ${c.activation.snapshot_id}` : "Locked until the package is activated"}
      actions={c.status === "IN_PROGRESS" && <Action id="act-reconcile" spec={c.actions.reconcile} variant="primary" busy={busy === "reconcile"}
        onClick={() => setConfirm(true)}>Run reconciliation</Action>}>
      {r.state === "NOT_RUN" && <Empty title="Not run">Reconciliation is an explicit analyst action on the activated snapshot.</Empty>}
      {r.state === "RUNNING" && <Notice tone="info" title="Reconciliation running">The UC-042 engine is processing the activated snapshot. This page refreshes every 5 seconds.</Notice>}
      {r.state === "FAILED" && <Notice tone="danger" title="Reconciliation failed">{r.error} The snapshot is unchanged.</Notice>}
      {failedJobs.length > 0 && <div className="rf-small rf-muted">{failedJobs.length} failed reconciliation run(s) kept in the history.</div>}
      <MutationError error={error} />
      {res && <div className="rf-stack" id="recon-outcome">
        <div className="rf-gap"><Pill k={res.case_status} large /><span>{res.exception_count} exception(s)</span></div>
        <div className="rf-figures">{[["Controls", res.total_results], ...Object.entries(o || {})].map(([k, v]) =>
          <div key={k} className="rf-figure"><b>{v}</b><span>{k}</span></div>)}</div>
        <div className="rf-small rf-muted">Integrity: {Object.entries(res.integrity_checks || {}).map(([k, v]) => `${k} ${v ? "✓" : "✕"}`).join(" · ")}</div>
      </div>}
    </Panel>
    {res && <Panel title="Exceptions" sub="Reconciliation findings (not evidence defects) · select one for its supporting evidence" flush>
      {res.exceptions.length === 0 ? <Empty title="No exceptions">The engine reported no exception for this snapshot.</Empty> :
        <div className="rf-table-wrap"><table className="rf-table rf-table--dense" id="exceptions-table"><thead><tr><th>Exception</th><th>Severity</th>
          <th>Category</th><th>Account</th><th>Amount</th><th>Affected</th></tr></thead>
          <tbody>{res.exceptions.map((e) => <tr key={e.exception_id} data-exception={e.exception_id} className="rf-clickable" onClick={() => setExc(e.exception_id)}>
            <td className="rf-mono">{e.exception_id}</td><td>{e.severity}</td><td>{e.category}</td><td className="rf-mono">{e.account_id}</td>
            <td className="rf-mono">{e.amount}</td><td>{e.affected_results}</td></tr>)}</tbody></table></div>}</Panel>}
    {confirm && <Dialog title="Run reconciliation" eyebrow={c.case_ref} onClose={() => setConfirm(false)}
      foot={<><Button onClick={() => setConfirm(false)}>Cancel</Button><Button id="confirm-reconcile" variant="primary"
        onClick={async () => { setConfirm(false); await mutate("reconcile", (rv) => api.reconcile(caseRef, rv)); }}>Run reconciliation</Button></>}>
      <p>The UC-042 engine reconciles the activated snapshot {c.activation && c.activation.snapshot_id}. When it finishes, the case becomes Completed and cannot be changed.</p></Dialog>}
    {exc && <ExceptionDrawer runId={runId} excId={exc} onClose={() => setExc(null)} />}
  </div>;
}
