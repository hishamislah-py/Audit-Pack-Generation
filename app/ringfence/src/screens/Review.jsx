import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/ringfence.js";
import { Button, Dialog, Empty, Enum, MutationError, Notice, Panel, Pill, Skeleton, Tag } from "../components/ui.jsx";

// provenance wording only; whether a column needs a decision and which actions exist come from the backend
const BASIS = { deterministic: ["EXACT", ""], diagnostic_name_match: ["VARIANT", "warning"], proposal: ["LLM PROPOSAL", "llm"],
                none: ["NO PROPOSAL", "none"] };

function Row({ r, fields, editable, onDecide, busy }) {
  const [field, setField] = useState(r.decision ? r.decision.canonical_field || "" : "");
  const can = (x) => editable && r.available_actions.includes(x);
  const [label, kind] = BASIS[r.suggestion_basis] || [r.suggestion_basis, ""];
  return <tr data-col={r.source_index} className={r.decided ? "is-decided" : ""}>
    <td className="rf-num">#{r.source_position}</td>
    <td className="rf-mono">{JSON.stringify(r.source_header).slice(1, -1)}</td>
    <td><div className="rf-samples-inline">{r.samples.slice(0, 4).map((s, i) => <code key={i}>{s === "" ? "∅" : s}</code>)}</div></td>
    <td><div className="rf-mono">{r.suggested_field || "—"}</div>
      <div className="rf-gap rf-small"><Tag kind={kind}>{label}</Tag>
        {r.proposal_assessment && <Enum>{r.proposal_assessment}</Enum>}
        {r.duplicate && <Tag kind="unresolved">DUPLICATE SOURCE</Tag>}
        {r.field_required && <Tag kind="required">REQUIRED</Tag>}
        {r.financial && <Tag kind="financial">£ FINANCIAL</Tag>}</div>
      {r.note && <div className="rf-small rf-muted">{r.note}</div>}</td>
    <td>{r.decided ? <Pill k="D_DONE" label={r.decision.action + (r.decision.canonical_field ? " → " + r.decision.canonical_field : "")} />
      : r.needs_attention ? <Pill k="D_OPEN" /> : <Pill k="RECOGNISED" />}</td>
    <td>{r.needs_attention && editable && <div className="rf-decide">
      {can("MAP") && <Button size="sm" id={`map-${r.source_index}`} busy={busy === "d" + r.source_index}
        onClick={() => onDecide(r, "MAP")}>Map</Button>}
      {can("CHANGE") && <><select aria-label="Canonical field" id={`field-${r.source_index}`} value={field} onChange={(e) => setField(e.target.value)}>
        <option value="">Choose field…</option>{fields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}</select>
        <Button size="sm" id={`change-${r.source_index}`} disabled={!field} onClick={() => onDecide(r, "CHANGE", field)}>Change</Button></>}
      {can("IGNORE") && <Button size="sm" id={`ignore-${r.source_index}`} onClick={() => onDecide(r, "IGNORE_COLUMN")}>Ignore</Button>}
    </div>}</td></tr>;
}

export default function Review({ c, caseRef, vid, mutate, busy, reloadCase }) {
  const files = c.outstanding.mapping_decisions;
  const sel = vid || (files[0] && files[0].file_version_id);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [show, setShow] = useState("remaining");
  const [rejecting, setRejecting] = useState(false);
  const load = useCallback(() => (sel ? api.review(caseRef, sel).then((x) => { setD(x); setError(null); }).catch(setError) : null), [caseRef, sel]);
  useEffect(() => { setD(null); load(); }, [load, c.revision]);
  if (!sel) return <Panel><Empty title="No file awaits mapping review">Columns that need a decision appear here after processing.</Empty></Panel>;
  const editable = !!(d && d.editable && c.actions.review.enabled);
  const decide = (r, action, field) => mutate("d" + r.source_index,
    (rv) => api.decide(caseRef, sel, { action, sourceIndex: r.source_index, field }, rv)).then(load);
  const rows = d ? d.rows.filter((r) => (show === "all" ? true : show === "remaining" ? r.needs_attention && !r.decided : r.needs_attention && r.decided)) : [];
  return <div className="rf-stack">
    <div className="rf-filterbar" id="review-files">{files.map((f) => <a key={f.file_version_id} href={`#/case/${caseRef}/review/${f.file_version_id}`}
      className={"rf-filter" + (f.file_version_id === sel ? " is-active" : "")}>{f.category} · {f.file_name}<span className="rf-filter__n">{f.outstanding} left</span></a>)}</div>
    {!c.actions.review.enabled && <Notice tone="locked" title="Read-only">{c.actions.review.reason}. Recorded decisions are shown.</Notice>}
    <MutationError error={error} />
    {!d ? <Skeleton /> : <Panel title={`${d.evidence_category} ${d.category_title} · v${d.version_number}`}
      sub={<>{d.review_reason} <Enum>{d.review_kind}</Enum></>} flush
      actions={<div className="rf-gap" id="review-counts"><span>{d.counts.decided} of {d.counts.attention} decided</span>
        <span className="rf-muted">· {d.counts.recognised} recognised</span></div>}
      foot={editable && <div className="rf-gap">
        <Button id="confirm-file" variant="primary" disabled={!d.can_confirm} busy={busy === "confirm"}
          title={d.can_confirm ? "" : "decide every remaining column first"}
          onClick={() => mutate("confirm", (rv) => api.confirmFile(caseRef, sel, rv))}>Confirm file mapping</Button>
        <Button id="reject-file" variant="danger" onClick={() => setRejecting(true)}>Reject / Request correction</Button>
        <span className="rf-small rf-muted">Confirming also confirms the recognised (exact) columns. Validation runs automatically.</span></div>}>
      <div className="rf-filterbar rf-mt">{[["remaining", `Remaining (${d.counts.remaining})`], ["decided", `Decided (${d.counts.decided})`], ["all", "All columns"]].map(([k, l]) =>
        <button key={k} type="button" data-show={k} className={"rf-filter" + (show === k ? " is-active" : "")} onClick={() => setShow(k)}>{l}</button>)}</div>
      <div className="rf-table-wrap"><table className="rf-table rf-table--dense" id="review-table"><caption className="rf-sr">Columns</caption>
        <thead><tr><th>#</th><th>Source column</th><th>Sample values</th><th>Suggested field</th><th>State</th><th>Decision</th></tr></thead>
        <tbody>{rows.map((r) => <Row key={r.source_index + ":" + (r.decided ? "d" : "o")} r={r} fields={d.canonical_fields}
          editable={editable} onDecide={decide} busy={busy} />)}</tbody></table>
        {rows.length === 0 && <Empty title={show === "remaining" ? "No remaining decisions in this file" : "Nothing to show"} />}</div>
      <div className="rf-small rf-muted rf-mt rf-panel__body">Source file <span className="rf-mono">{d.original_filename}</span> · {d.file_version_id}</div>
    </Panel>}
    {rejecting && <Dialog title="Reject file and request a corrected version" onClose={() => setRejecting(false)}
      foot={<><Button onClick={() => setRejecting(false)}>Cancel</Button><Button id="confirm-reject" variant="danger"
        onClick={async () => { setRejecting(false); await mutate("reject", (rv) => api.rejectFile(caseRef, sel, rv)); }}>Reject file</Button></>}>
      <p>The whole file version is rejected. A corrected file must be uploaded for this category; decisions made so far stay in the history.</p></Dialog>}
  </div>;
}
