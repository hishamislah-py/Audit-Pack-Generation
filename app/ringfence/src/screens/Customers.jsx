import React, { useEffect, useState } from "react";
import { api } from "../api/ringfence.js";
import { Empty, MutationError, Panel, Pill, Skeleton, when } from "../components/ui.jsx";
import { CaseRows } from "./Queue.jsx";

export function Customers() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.customers().then(setRows).catch(setError); }, []);
  return <div className="rf-page">
    <div className="rf-page__head"><h1 className="rf-page__title">Customers</h1>
      <div className="rf-page__sub">Customers with registered cases (read-only)</div></div>
    <MutationError error={error} />
    <Panel flush title="Customers">{!rows ? <div className="rf-panel__body"><Skeleton /></div> : rows.length === 0
      ? <Empty title="No customers yet">A customer appears when its first case is registered.</Empty>
      : <div className="rf-table-wrap"><table className="rf-table" id="customers-table"><thead><tr><th>Customer</th><th>Cases</th>
        <th>Waiting</th><th>In progress</th><th>Pending</th><th>Completed</th></tr></thead>
        <tbody>{rows.map((c) => <tr key={c.customer_id} className="rf-clickable" onClick={() => { window.location.hash = "#/customers/" + c.customer_id; }}>
          <td><a className="rf-strong" href={"#/customers/" + c.customer_id}>{c.customer_name}</a><div className="rf-cell-sub rf-muted rf-mono">{c.customer_id}</div></td>
          <td>{c.cases}</td><td>{c.by_status.WAITING}</td><td>{c.by_status.IN_PROGRESS}</td><td>{c.by_status.PENDING}</td>
          <td>{c.by_status.COMPLETED}</td></tr>)}</tbody></table></div>}</Panel></div>;
}

export function CustomerProfile({ customerId }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.customer(customerId).then(setD).catch(setError); }, [customerId]);
  return <div className="rf-page">
    <div className="rf-breadcrumb"><a href="#/customers">Customers</a></div>
    <MutationError error={error} />
    {!d ? !error && <Skeleton /> : <>
      <div className="rf-page__head"><h1 className="rf-page__title">{d.customer_name}</h1>
        <div className="rf-page__sub rf-mono">{d.customer_id}</div></div>
      <Panel flush title="Cases"><CaseRows items={d.cases} /></Panel>
      <Panel title="Reconciliation history">{d.reconciliation_history.length === 0 ? <span className="rf-muted">No completed reconciliation yet</span> :
        <table className="rf-table rf-table--dense"><tbody>{d.reconciliation_history.map((r) => <tr key={r.case_ref}>
          <td className="rf-mono">{r.case_ref}</td><td className="rf-mono">{r.reporting_period}</td><td><Pill k={r.case_status} /></td>
          <td className="rf-mono">{r.reconciliation_run_id}</td><td>{when(r.at)}</td></tr>)}</tbody></table>}</Panel></>}
  </div>;
}
