import React, { useCallback, useState } from "react";
import { api } from "../api/ringfence.js";
import { Button, Dialog, MutationError, Notice, Panel, Pill, Skeleton, Empty, StepStrip, bytes, when, usePolling } from "../components/ui.jsx";
import { useApp } from "../main.jsx";

const FILTERS = [["", "All"], ["IN_PROGRESS", "In progress"], ["WAITING", "Waiting"], ["PENDING", "Pending"], ["COMPLETED", "Completed"]];

export function RegisterDialog({ onClose, onCreated }) {
  const [customer, setCustomer] = useState("");
  const [period, setPeriod] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { onCreated(await api.registerCase({ customerName: customer, period, file })); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return <Dialog title="Register a customer submission" eyebrow="Case registration" onClose={onClose}
    foot={<><Button onClick={onClose}>Cancel</Button>
      <Button id="create-case" variant="primary" busy={busy} disabled={!customer || !period || !file} onClick={submit}>Register case</Button></>}>
    <div className="rf-form">
      <p className="rf-secondary">The original ZIP is attached to a new case that waits in the queue. Nothing is processed until Smart Parsing is started from the case.</p>
      <label className="rf-field"><span className="rf-label">Customer</span>
        <input id="nc-customer" className="rf-input" value={customer} onChange={(e) => setCustomer(e.target.value)} /></label>
      <label className="rf-field"><span className="rf-label">Reporting period (YYYY-MM)</span>
        <input id="nc-period" className="rf-input" placeholder="2026-09" value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
      <label className="rf-field"><span className="rf-label">Original submission (ZIP)</span>
        <input id="nc-file" type="file" accept=".zip" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
      <MutationError error={error} />
    </div></Dialog>;
}

function CaseRows({ items }) {
  return <div className="rf-table-wrap"><table className="rf-table" id="queue-table">
    <caption className="rf-sr">Cases</caption>
    <thead><tr><th>Case</th><th>Customer</th><th>Period</th><th>Original ZIP</th><th>Received</th><th>Status</th>
      <th>Progress</th><th>Last activity</th><th /></tr></thead>
    <tbody>{items.map((c) => <tr key={c.case_ref} data-case={c.case_ref} className="rf-clickable"
      onClick={() => { window.location.hash = "#/case/" + c.case_ref; }}>
      <td className="rf-nowrap"><a className="rf-mono" href={"#/case/" + c.case_ref}>{c.case_ref}</a></td>
      <td className="rf-strong">{c.customer_name}{c.other_cases_for_period > 0 &&
        <div className="rf-cell-sub rf-muted">{c.other_cases_for_period} other case(s) this period</div>}</td>
      <td className="rf-mono rf-nowrap">{c.reporting_period}</td>
      <td><div className="rf-cell-main">{c.zip.filename}</div><div className="rf-cell-sub rf-muted">{bytes(c.zip.size)}</div></td>
      <td className="rf-nowrap">{when(c.created_at)}</td>
      <td className="case-status"><Pill k={c.deferring ? "DEFERRING" : c.status} />
        {c.current_run && c.current_run.status === "FAILED" && <div className="rf-mt"><Pill k="RUN_FAILED" label="Last run failed" /></div>}
        {c.completed && c.completed.case_status && <div className="rf-mt"><Pill k={c.completed.case_status} /></div>}</td>
      <td><StepStrip steps={c.steps} compact /><ul className="rf-queue-progress">{c.progress.summary.slice(0, 3).map((s, i) => <li key={i}>{s}</li>)}</ul></td>
      <td className="rf-nowrap">{when(c.last_activity_at)}</td>
      <td><a className="rf-btn rf-btn--quiet rf-btn--sm" href={"#/case/" + c.case_ref} onClick={(e) => e.stopPropagation()}>Open</a></td>
    </tr>)}</tbody></table></div>;
}

export default function Queue() {
  const { refreshSlot } = useApp();
  const [status, setStatus] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => api.cases(status).then((d) => { setData(d); setError(null); }).catch(setError), [status]);
  const live = !!(data && data.items.some((c) => c.progress.current_operation || c.deferring ||
    (c.current_run && c.current_run.status === "PROCESSING")));
  usePolling(load, live ? 3000 : 30000, true, [status]);
  const counts = data ? data.counts : {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const active = data && data.active_case;
  return <div className="rf-page">
    <div className="rf-page__head rf-row">
      <div><h1 className="rf-page__title">Work queue</h1>
        <div className="rf-page__sub">{data ? data.ordering : "Loading…"}</div></div>
      <span className="rf-spacer" />
      <Button id="new-case" icon="plus" onClick={() => setAdding(true)}>Register submission</Button>
    </div>
    {active && <section className="rf-panel rf-active-panel" id="active-panel"><div className="rf-panel__body rf-row rf-row--wrap">
      <div><div className="rf-label">In Progress</div><a className="rf-strong" href={"#/case/" + active.case_ref}>{active.case_ref}</a>
        <span className="rf-muted"> · {active.customer_name} · {active.reporting_period}</span></div>
      <span className="rf-spacer" />{active.deferring ? <Pill k="DEFERRING" /> : <Pill k="IN_PROGRESS" />}
      <a className="rf-btn rf-btn--secondary rf-btn--sm" href={"#/case/" + active.case_ref}>Open case</a></div></section>}
    {data && !active && <Notice tone="info" title="No case In Progress">Open a Waiting or Pending case to start or resume it. The oldest is listed first.</Notice>}
    <MutationError error={error} />
    <Panel flush title="Cases" actions={<div className="rf-filterbar" role="tablist">{FILTERS.map(([k, label]) =>
      <button key={k} type="button" role="tab" aria-selected={status === k} data-filter={k || "ALL"}
        className={"rf-filter" + (status === k ? " is-active" : "")} onClick={() => setStatus(k)}>
        {label}<span className="rf-filter__n">{k ? counts[k] ?? 0 : total}</span></button>)}</div>}>
      {!data ? <div className="rf-panel__body"><Skeleton lines={4} /></div> : data.items.length === 0
        ? <Empty title="No cases">Register a customer submission to create the first case.</Empty>
        : <CaseRows items={data.items} />}
    </Panel>
    {adding && <RegisterDialog onClose={() => setAdding(false)}
      onCreated={(c) => { setAdding(false); refreshSlot(); window.location.hash = "#/case/" + c.case_ref; }} />}
  </div>;
}

export { CaseRows };
