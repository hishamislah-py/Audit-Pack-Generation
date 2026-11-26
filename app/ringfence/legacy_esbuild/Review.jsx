import React, { useEffect, useState, useCallback } from "react";
import { get, post } from "./api.js";
import { Pill, Panel, Button, Dialog, ErrorBox, Notice, Tag, Enum } from "./ui.jsx";

const BASIS = { deterministic: "Recognised", diagnostic_name_match: "Name match", proposal: "AI proposal", none: "No suggestion" };

function Row({ r, fields, onDecide, editable }) {
  const [field, setField] = useState(r.decision ? r.decision.canonical_field || "" : r.suggested_field || "");
  const can = (a) => editable && r.available_actions.includes(a);
  return <tr data-col={r.source_index} className={r.decided ? "is-decided" : ""}>
    <td className="rf-num">#{r.source_position}</td>
    <td className="rf-mono">{r.source_header}</td>
    <td><div className="rf-samples-inline">{r.samples.slice(0, 4).map((s, i) => <code key={i}>{s === "" ? "∅" : s}</code>)}</div></td>
    <td><div className="rf-mono">{r.suggested_field || "—"}</div>
      <div className="rf-gap rf-small"><Tag kind={r.suggestion_basis === "proposal" ? "llm" : r.suggestion_basis === "none" ? "none" : ""}>{BASIS[r.suggestion_basis] || r.suggestion_basis}</Tag>
        {r.proposal_assessment && <Enum>{r.proposal_assessment}</Enum>}{r.duplicate && <Tag kind="unresolved">DUPLICATE</Tag>}
        {r.field_required && <Tag kind="required">REQUIRED</Tag>}{r.financial && <Tag kind="financial">£ FINANCIAL</Tag>}</div>
      {r.note && <div className="rf-small rf-muted">{r.note}</div>}</td>
    <td>{r.decided ? <><Pill k="D_DONE" label={r.decision.action + (r.decision.canonical_field ? " → " + r.decision.canonical_field : "")} /></>
      : r.needs_attention ? <Pill k="D_OPEN" /> : <Pill k="RECOGNISED" />}</td>
    <td>{r.needs_attention && editable && <div className="rf-decide">
      {can("MAP") && <Button size="sm" onClick={() => onDecide(r, "MAP")} id={`map-${r.source_index}`}>Map</Button>}
      {can("CHANGE") && <><select aria-label="Canonical field" value={field} id={`field-${r.source_index}`} onChange={(e) => setField(e.target.value)}>
        <option value="">Choose field…</option>{fields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}</select>
        <Button size="sm" disabled={!field} onClick={() => onDecide(r, "CHANGE", field)} id={`change-${r.source_index}`}>Change</Button></>}
      {can("IGNORE") && <Button size="sm" onClick={() => onDecide(r, "IGNORE")} id={`ignore-${r.source_index}`}>Ignore</Button>}</div>}</td>
  </tr>;
}

export default function Review({ c, caseRef, vid, reload }) {
  const files = c.progress.awaiting_review;
  const sel = vid || (files[0] && files[0].file_version_id);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [show, setShow] = useState("remaining");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => sel ? get(`cases/${caseRef}/review/${sel}`).then(setD).catch(setError) : Promise.resolve(), [caseRef, sel]);
  useEffect(() => { setD(null); load(); }, [load]);
  const editable = d && d.editable && c.actions.review.enabled;
  const act = async (key, path, body) => {
    setBusy(key); setError(null);
    try { await post(path, body); await load(); await reload(); } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const decide = (r, action, field) => act("d" + r.source_index, `cases/${caseRef}/review/${sel}/decision`,
    { action, source_index: r.source_index, canonical_field: field || null });
  if (!files.length && !vid) return <Panel><div className="rf-empty"><div className="rf-empty__title">No file awaits mapping review</div></div></Panel>;
  const rows = d ? d.rows.filter((r) => show === "all" ? true : show === "remaining" ? r.needs_attention && !r.decided : r.needs_attention && r.decided) : [];
  return <div className="rf-stack">
    <div className="rf-filterbar">{files.map((f) => <a key={f.file_version_id} href={`#/case/${caseRef}/review/${f.file_version_id}`}
      className={"rf-filter" + (f.file_version_id === sel ? " is-active" : "")}>{f.category} · {f.original_filename}<span className="rf-filter__n">{f.remaining ?? "?"} left</span></a>)}</div>
    {!c.actions.review.enabled && <Notice tone="locked" title="Read-only">{c.actions.review.reason}. Decisions already recorded are shown.</Notice>}
    <ErrorBox error={error} />
    {d && <Panel title={`${d.evidence_category} ${d.category_title} · v${d.version_number}`} sub={d.review_reason}
      actions={<div className="rf-gap" id="review-counts"><span>{d.counts.decided} of {d.counts.attention} decided</span>
        <span className="rf-muted">· {d.counts.recognised} recognised</span></div>} flush
      foot={editable && <div className="rf-gap">
        <Button id="confirm-file" variant="primary" disabled={!d.can_confirm} busy={busy === "confirm"}
          title={d.can_confirm ? "" : "decide every remaining column first"}
          onClick={() => act("confirm", `cases/${caseRef}/review/${sel}/confirm`)}>Confirm file mapping</Button>
        <Button id="reject-file" variant="danger" onClick={() => setRejecting(true)}>Reject file · request correction</Button>
        <span className="rf-small rf-muted">Confirming also confirms the recognised columns of this file. Package validation runs automatically.</span></div>}>
      <div className="rf-filterbar rf-mt">{[["remaining", `Remaining (${d.counts.remaining})`], ["decided", `Decided (${d.counts.decided})`], ["all", "All columns"]].map(([k, l]) =>
        <button key={k} type="button" data-show={k} className={"rf-filter" + (show === k ? " is-active" : "")} onClick={() => setShow(k)}>{l}</button>)}</div>
      <div className="rf-table-wrap"><table className="rf-table rf-table--dense" id="review-table"><thead><tr><th>#</th><th>Source column</th><th>Sample values</th>
        <th>Suggested field</th><th>State</th><th>Decision</th></tr></thead>
        <tbody>{rows.map((r) => <Row key={r.source_index + ":" + (r.decided ? "d" : "o")} r={r} fields={d.canonical_fields} editable={editable} onDecide={decide} />)}</tbody></table>
        {rows.length === 0 && <div className="rf-empty">{show === "remaining" ? "No remaining decisions in this file." : "Nothing to show."}</div>}</div>
    </Panel>}
    {rejecting && <Dialog title="Reject file and request a corrected version" onClose={() => setRejecting(false)}
      foot={<><Button onClick={() => setRejecting(false)}>Cancel</Button><Button id="confirm-reject" variant="danger"
        onClick={async () => { setRejecting(false); await act("reject", `cases/${caseRef}/review/${sel}/reject`); }}>Reject file</Button></>}>
      <p>The whole file version is rejected (for example a wrong category or unusable structure). A corrected file must be uploaded for this category; earlier decisions on this file are kept as history.</p></Dialog>}
  </div>;
}
