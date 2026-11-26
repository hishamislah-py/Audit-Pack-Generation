import React, { useEffect, useState, useCallback } from "react";
import { get, post, fileToBase64 } from "./api.js";
import { Pill, Panel, Button, Dialog, ErrorBox, Notice, when, bytes } from "./ui.jsx";

const FILTERS = [["", "All"], ["IN_PROGRESS", "In progress"], ["WAITING", "Waiting"], ["PENDING", "Pending"], ["COMPLETED", "Completed"]];

function NewCase({ onClose, onCreated }) {
  const [f, setF] = useState({ customer: "", period: "", file: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const c = await post("cases", { customer_name: f.customer, reporting_period: f.period, zip_name: f.file ? f.file.name : "",
        zip_b64: f.file ? await fileToBase64(f.file) : "" });
      onCreated(c);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return <Dialog title="Register a customer submission" eyebrow="POC · synthetic data" onClose={onClose}
    foot={<><Button onClick={onClose}>Cancel</Button><Button id="create-case" variant="primary" busy={busy} onClick={submit}
      disabled={!f.customer || !f.period || !f.file}>Register case</Button></>}>
    <div className="rf-form">
      <p className="rf-secondary">The original ZIP is attached to a new case in the Waiting state. Nothing is processed until an analyst opens the case and starts Smart Parsing.</p>
      <label className="rf-field"><span className="rf-label">Customer</span>
        <input id="nc-customer" className="rf-input" value={f.customer} onChange={(e) => setF({ ...f, customer: e.target.value })} /></label>
      <label className="rf-field"><span className="rf-label">Reporting period (YYYY-MM)</span>
        <input id="nc-period" className="rf-input" placeholder="2026-09" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} /></label>
      <label className="rf-field"><span className="rf-label">Original submission (ZIP)</span>
        <input id="nc-file" type="file" accept=".zip" onChange={(e) => setF({ ...f, file: e.target.files[0] || null })} /></label>
      <ErrorBox error={error} />
    </div></Dialog>;
}

export default function Queue() {
  const [status, setStatus] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => get("cases" + (status ? "?status=" + status : "")).then((d) => { setData(d); setError(null); }).catch(setError), [status]);
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);
  const counts = data ? data.counts : {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return <div className="rf-page">
    <div className="rf-page__head rf-row">
      <div><h1 className="rf-page__title">Work queue</h1>
        <div className="rf-page__sub">{data ? data.ordering : "Loading…"}</div></div>
      <span className="rf-spacer" />
      <Button id="new-case" icon="plus" onClick={() => setAdding(true)}>Register submission</Button>
    </div>
    {data && data.active_case_ref && <Notice tone="info" title="One case is in progress">
      <a href={"#/case/" + data.active_case_ref}>{data.active_case_ref}</a> holds the active slot. Defer it before starting or resuming another case.</Notice>}
    <ErrorBox error={error} />
    <Panel flush title="Cases" actions={<div className="rf-filterbar" role="tablist">{FILTERS.map(([k, label]) =>
      <button key={k} type="button" role="tab" aria-selected={status === k} className={"rf-filter" + (status === k ? " is-active" : "")}
        data-filter={k || "ALL"} onClick={() => setStatus(k)}>{label}<span className="rf-filter__n">{k ? counts[k] ?? 0 : total}</span></button>)}</div>}>
      {!data ? <div className="rf-empty">Loading…</div> : data.items.length === 0 ? <div className="rf-empty"><div className="rf-empty__title">No cases</div></div> :
        <div className="rf-table-wrap"><table className="rf-table" id="queue-table">
          <thead><tr><th>Case</th><th>Customer</th><th>Period</th><th>Original ZIP</th><th>Received</th><th>Status</th><th>Progress</th><th>Last activity</th><th /></tr></thead>
          <tbody>{data.items.map((c) => <tr key={c.case_ref} data-case={c.case_ref}>
            <td className="rf-nowrap"><a className="rf-mono" href={"#/case/" + c.case_ref}>{c.case_ref}</a></td>
            <td className="rf-strong">{c.customer_name}</td>
            <td className="rf-mono rf-nowrap">{c.reporting_period}</td>
            <td><div className="rf-cell-main">{c.zip.filename}</div><div className="rf-cell-sub rf-muted">{bytes(c.zip.size)}</div></td>
            <td className="rf-nowrap">{when(c.created_at)}</td>
            <td className="case-status"><Pill k={c.deferring ? "DEFERRING" : c.status} />
              {c.current_run && c.current_run.status === "FAILED" && <div className="rf-mt"><Pill k="RUN_FAILED" label="Last run failed" /></div>}</td>
            <td><ul className="rf-queue-progress">{c.progress.summary.map((s, i) => <li key={i}>{s}</li>)}</ul></td>
            <td className="rf-nowrap">{when(c.last_activity_at)}</td>
            <td><a className="rf-btn rf-btn--quiet rf-btn--sm" href={"#/case/" + c.case_ref}>Open</a></td>
          </tr>)}</tbody></table></div>}
    </Panel>
    {adding && <NewCase onClose={() => setAdding(false)} onCreated={(c) => { setAdding(false); window.location.hash = "#/case/" + c.case_ref; }} />}
  </div>;
}
