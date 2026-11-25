// Human review panel and the HOLD / GENERATE confirmation flows. GENERATE is presented as authorisation to assemble the
// report from the previewed inputs, never as resolution of exceptions or certification of compliance. HOLD never
// publishes anything. Both go through the DataSource (simulated in mock mode).
import { useState } from "react";
import { ApiError, errorMessage } from "../../api/client";
import type { DecisionResponse, ExceptionInvestigations, ExceptionView, Inclusion, ReviewSession, Selection } from "../../api/types";
import { useData } from "../../data/DataProvider";
import { Amount, ErrorPanel, Modal, Notice } from "../common";

export const EDITABLE: ReadonlyArray<ReviewSession["status"]> = ["OPEN", "ON_HOLD", "GENERATION_FAILED"];

export function DecisionPanel({ session, unresolved, onDecided }: { session: ReviewSession; unresolved: number; onDecided: (r: DecisionResponse) => void }) {
  const data = useData();
  const [comment, setComment] = useState("");
  const [ack, setAck] = useState(false);
  const [ackSummary, setAckSummary] = useState(false);
  const [modal, setModal] = useState<"HOLD" | "GENERATE" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const preview = session.current_preview;
  const summaryUnavailable = preview?.closing_summary.status === "UNAVAILABLE";
  const canGenerate = !!preview && ack && (!summaryUnavailable || ackSummary) && session.readiness.ready;

  const submit = async (decision: "HOLD" | "GENERATE") => {
    setBusy(true);
    setError(undefined);
    try {
      const r = await data.decide(session.review_id, decision === "HOLD"
        ? { decision, comment, ...(preview ? { snapshot_sha256: preview.snapshot_sha256 } : {}) }
        : { decision, comment, snapshot_sha256: preview?.snapshot_sha256 ?? null, acknowledgement_accepted: ack, acknowledged_summary_unavailable: ackSummary });
      setModal(null);
      setComment("");
      setAck(false);
      onDecided(r);
    } catch (e) {
      setError(e);
      setModal(null);
    } finally {
      setBusy(false);
    }
  };
  const stale = error instanceof ApiError && error.code === "PREVIEW_STALE";

  return (
    <div className="stack stack--sm">
      <label className="field"><span>Reviewer note (included in the decision record)</span>
        <textarea className="textarea" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Required for HOLD; optional for GENERATE" />
      </label>
      <label className="check"><input type="checkbox" checked={ack} disabled={!preview} onChange={(e) => setAck(e.target.checked)} /><span>{session.acknowledgement_text}</span></label>
      {summaryUnavailable && (
        <label className="check"><input type="checkbox" checked={ackSummary} onChange={(e) => setAckSummary(e.target.checked)} />
          <span>The AI closing summary is unavailable. I acknowledge the pack will be generated without it.</span></label>
      )}
      <div className="grid-2">
        <button className="btn btn--decision" onClick={() => setModal("HOLD")} disabled={busy}>HOLD</button>
        <button className="btn btn--primary btn--decision" onClick={() => setModal("GENERATE")} disabled={busy || !canGenerate}>GENERATE</button>
      </div>
      {!preview && <p className="xsmall muted">GENERATE needs a current preview. Generate the preview and read the report first.</p>}
      {preview && !ack && <p className="xsmall muted">Accept the statement above to enable GENERATE.</p>}
      {error !== undefined && (
        <Notice tone="bad" title={stale ? "The preview is stale" : "The decision was not recorded"}>
          <p>{errorMessage(error)}</p>
          {stale && <p>Inputs changed since the preview. Generate a new preview, read it, and decide again.</p>}
        </Notice>
      )}

      {modal === "HOLD" && (
        <Modal title="Save decision: HOLD" onClose={() => !busy && setModal(null)} footer={<>
          <button className="btn btn--ghost" onClick={() => setModal(null)} disabled={busy}>Cancel</button>
          <button className="btn btn--primary" onClick={() => submit("HOLD")} disabled={busy || !comment.trim()}>{busy ? "Saving…" : "SAVE HOLD"}</button>
        </>}>
          <p className="modal__text">The review and your note are saved. <strong>No final audit pack is generated.</strong> You can return, regenerate the preview and decide later.</p>
          <label className="field"><span>Reason for hold (required)</span>
            <textarea className="textarea" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="For example: awaiting the bank's payment trace for the unexplained debit" /></label>
          {data.kind === "mock" && <p className="xsmall muted">Simulated: the decision is held in this browser session only.</p>}
        </Modal>
      )}
      {modal === "GENERATE" && (
        <Modal title="Authorise final audit-pack assembly" onClose={() => !busy && setModal(null)} footer={<>
          <button className="btn btn--ghost" onClick={() => setModal(null)} disabled={busy}>Cancel</button>
          <button className="btn btn--primary" onClick={() => submit("GENERATE")} disabled={busy}>{busy ? <><span className="spinner" /> Generating…</> : "GENERATE PACK"}</button>
        </>}>
          <p className="modal__text">GENERATE authorises assembly of the final audit pack from the previewed inputs (snapshot <code>{preview?.snapshot_sha256.slice(0, 12)}</code>) for <code>{session.pack_id}</code>.</p>
          <p className="modal__text">It does <strong>not</strong> resolve exceptions, confirm hypotheses, certify a clean reconciliation or establish compliance.
            {" "}{unresolved} exception(s) will be reported as UNRESOLVED. The pack cannot be edited after generation.</p>
          {data.kind === "mock" && <Notice tone="mock" title="Simulated">No pack is assembled or published in this design phase; the result is a session-only simulated record.</Notice>}
        </Modal>
      )}
    </div>
  );
}

const INCLUSIONS: Array<[Inclusion, string]> = [["INCLUDED", "Include investigation"], ["NOT_INVESTIGATED", "Not investigated"], ["EXCLUDED_BY_ANALYST", "Exclude (reason required)"]];

export function SelectionEditor({ session, exceptions, investigations, onSaved, onCancel }: {
  session: ReviewSession; exceptions: ExceptionView[]; investigations: ExceptionInvestigations[]; onSaved: (s: ReviewSession) => void; onCancel: () => void;
}) {
  const data = useData();
  const [draft, setDraft] = useState<Selection[]>(session.selections);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>();
  const update = (id: string, change: Partial<Selection>) => setDraft((d) => d.map((s) => (s.exception_id === id ? { ...s, ...change } : s)));
  const save = async () => {
    setSaving(true);
    setError(undefined);
    try {
      onSaved(await data.setSelections(session.review_id, draft.map((s) => ({ exception_id: s.exception_id, inclusion: s.inclusion,
        investigation_id: s.inclusion === "INCLUDED" ? s.investigation_id ?? null : null, reason: s.reason ?? "" })), session.revision));
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title="Investigation selections" wide onClose={onCancel} footer={<>
      <span className="xsmall muted">Saving invalidates the current closing summary and preview.</span>
      <button className="btn btn--ghost" onClick={onCancel}>Cancel</button>
      <button className="btn btn--primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save selections"}</button>
    </>}>
      <div className="table-scroll">
        <table className="dtable dtable--compact">
          <thead><tr><th>Exception</th><th className="num">Amount</th><th>Inclusion</th><th>Investigation / reason</th></tr></thead>
          <tbody>
            {draft.map((s) => {
              const x = exceptions.find((e) => e.exception_id === s.exception_id);
              const published = investigations.find((i) => i.exception_id === s.exception_id)?.published ?? [];
              return (
                <tr key={s.exception_id}>
                  <td className="id">{s.exception_id}<div className="xsmall muted">{x?.category}</div></td>
                  <td className="num"><Amount value={x?.amount} currency={x?.currency} /></td>
                  <td><select className="select" aria-label={`Inclusion for ${s.exception_id}`} value={s.inclusion}
                    onChange={(e) => update(s.exception_id, { inclusion: e.target.value as Inclusion, investigation_id: e.target.value === "INCLUDED" ? published.find((p) => p.eligible)?.investigation_id ?? null : null })}>
                    {INCLUSIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
                  <td>
                    {s.inclusion === "INCLUDED" && (
                      <select className="select" aria-label={`Investigation for ${s.exception_id}`} value={s.investigation_id ?? ""} onChange={(e) => update(s.exception_id, { investigation_id: e.target.value })}>
                        <option value="">Select an investigation…</option>
                        {published.map((p) => <option key={p.investigation_id} value={p.investigation_id} disabled={!p.eligible}>{p.investigation_id} · {p.eligible ? "eligible" : "ineligible"}</option>)}
                      </select>
                    )}
                    {s.inclusion === "EXCLUDED_BY_ANALYST" && <input className="input" aria-label={`Exclusion reason for ${s.exception_id}`} value={s.reason ?? ""} placeholder="Reason (required)" onChange={(e) => update(s.exception_id, { reason: e.target.value })} />}
                    {s.inclusion === "NOT_INVESTIGATED" && <span className="small muted">Reported from the deterministic results only</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {error !== undefined && <ErrorPanel error={error} title="Selections were not saved" />}
    </Modal>
  );
}
