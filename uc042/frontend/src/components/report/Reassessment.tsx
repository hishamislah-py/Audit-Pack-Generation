// Reassessment of a published month: what would be used (the backend's read-only plan), the explicit Reassess action with
// a required reason and confirmation, the run's outcome and the period's pack lineage. Published packs are never changed.
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../api/client";
import type { ProcessingRun } from "../../api/types";
import { useData } from "../../data/DataProvider";
import { periodLabel } from "../../data/periods";
import { useApi } from "../../hooks/useApi";
import { isActive, useJobPoller } from "../../hooks/useJobPoller";
import { dateTime } from "../../lib/format";
import { Async, Empty, KeyValue, Modal, Notice, Panel, StatusBadge } from "../common";

export function ReassessmentPanel({ periodId, onDone }: { periodId: string; onDone: () => void }) {
  const data = useData();
  const [tick, setTick] = useState(0);
  const plan = useApi(() => data.reassessmentPlan(periodId), [data, periodId, tick]);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [run, setRun] = useState<ProcessingRun | null>(null);
  const { job } = useJobPoller(run?.job_id ?? null, async () => {
    if (run) setRun(await data.processingRun(run.run_id));
    setTick((t) => t + 1);
    onDone();
  });
  const start = async () => {
    setBusy(true);
    setError(undefined);
    try {
      setRun(await data.reconcile(periodId, { purpose: "REASSESSMENT", reason: reason.trim() }));
      setConfirming(false);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const running = !!run && (job ? isActive(job) : run.status === "QUEUED" || run.status === "RUNNING");
  return (
    <Panel id="reassessment" title="Reassessment" sub="New evidence after publication is assessed explicitly: the published pack stays as it is and the new result is linked to it">
      <Async state={plan} label="Checking what a reassessment would use…">{(p) => {
        const baseline = p.baseline ? Object.keys(p.baseline.files).length : 0;
        const fromBaseline = Object.entries(p.effective_set).filter(([, v]) => v.source === "BASELINE").map(([k]) => k);
        const fromUploads = Object.entries(p.effective_set).filter(([, v]) => v.source === "UPLOADED").map(([k]) => k);
        return (
          <div className="stack stack--sm">
            <KeyValue items={[
              ["Previous published result", p.latest_final_pack_id ? <><Link className="id" to={`/final-packs/${p.latest_final_pack_id}`}>{p.latest_final_pack_id}</Link> · {dateTime(p.latest_final_pack_at)}</> : "none"],
              ["Pack being reassessed", p.target_pack_id ? <Link className="id" to={`/packs/${p.target_pack_id}`}>{p.target_pack_id}</Link> : "—"],
              ["Original source documents", p.baseline ? <>{baseline} file(s) of <span className="mono">{p.baseline.pack_id}</span>, verified against their recorded SHA-256 ({p.baseline.storage_profile} storage)</>
                : p.target_pack_id ? "the month's uploaded documents (latest confirmed versions)" : "—"],
              ["Document set", `${fromUploads.length} type(s) from uploads${fromBaseline.length ? `, ${fromBaseline.length} from the verified originals` : ""}`],
            ]} />
            {fromUploads.length > 0 && p.baseline && <p className="xsmall muted">Uploaded documents supersede the originals for: <span className="mono">{fromUploads.join(", ")}</span></p>}
            {p.baseline_problems.length > 0 && <Notice tone="bad" title="The original source documents cannot be verified"><ul>{p.baseline_problems.map((x) => <li key={x}>{x}</li>)}</ul></Notice>}
            <div className="section-label">Evidence received after publication ({p.new_documents.length})</div>
            {p.new_documents.length === 0 ? <p className="small muted">None.</p> : (
              <table className="dtable dtable--compact"><tbody>{p.new_documents.map((d) => (
                <tr key={d.document_id}><td className="small"><code>{d.original_filename}</code><div className="xsmall muted">{d.evidence_id ?? d.category ?? "unidentified"} · {d.submission_kind.toLowerCase().replace(/_/g, " ")}</div></td>
                  <td className="xsmall">{d.submission_reason}</td><td><StatusBadge status={d.validation_status} /></td>
                  <td><Link className="id xsmall" to={`/uploads/${d.batch_id}`}>{d.batch_id}</Link></td></tr>
              ))}</tbody></table>
            )}
            {p.blockers.length > 0 && <Notice tone="warn" title="Reassessment cannot start yet"><ul>{p.blockers.map((b) => <li key={b}>{b}</li>)}</ul></Notice>}
            <div><button className="btn btn--primary" disabled={!p.can_reassess || running || busy} onClick={() => setConfirming(true)}>Reassess {periodLabel(periodId)}</button></div>
            {run && <RunOutcome run={run} running={running} />}
            {confirming && (
              <Modal title={`Reassess ${periodLabel(periodId)}`} onClose={() => !busy && setConfirming(false)} footer={<>
                <button className="btn btn--ghost" onClick={() => setConfirming(false)} disabled={busy}>Cancel</button>
                <button className="btn btn--primary" onClick={start} disabled={busy || reason.trim().length < 3}>{busy ? "Starting…" : "Start reassessment"}</button>
              </>}>
                <p className="modal__text">The deterministic engine runs again over the document set above and publishes a <strong>new</strong> deterministic pack,
                  linked to <span className="mono">{p.target_pack_id}</span>. Nothing published is changed. A new final audit pack needs a new final review.</p>
                <label className="field"><span>Reason (required)</span>
                  <textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: bank confirmation for 16 Feb received" /></label>
                {error !== undefined && <Notice tone="bad">{errorMessage(error)}</Notice>}
              </Modal>
            )}
          </div>
        );
      }}</Async>
      <Lineage periodId={periodId} tick={tick} />
    </Panel>
  );
}

function RunOutcome({ run, running }: { run: ProcessingRun; running: boolean }) {
  const pack = run.result.pack_id as string | undefined;
  if (running) return <Notice tone="info" title={<><span className="spinner" /> Reassessment {run.run_id} is running</>}>The engine is processing the document set.</Notice>;
  if (run.status !== "SUCCEEDED") return <Notice tone="bad" title={`Reassessment ${run.status.toLowerCase()}`}>{run.error || "See the processing runs."}</Notice>;
  return (
    <Notice tone="ok" title="Reassessment complete">New deterministic pack <Link className="id" to={`/packs/${pack}`}>{pack}</Link> ({String(run.result.exceptions ?? "?")} exception(s)).
      {" "}<Link to={`/packs/${pack}/review`}>Go to its final review</Link> to publish a new final-pack version.</Notice>
  );
}

function Lineage({ periodId, tick }: { periodId: string; tick: number }) {
  const data = useData();
  const rows = useApi(() => data.periodLineage(periodId), [data, periodId, tick]);
  return (
    <div style={{ marginTop: 16 }}>
      <div className="section-label">Pack lineage</div>
      <Async state={rows}>{(r) => r.length === 0 ? <Empty>No reassessment yet: every pack of this month is an original result.</Empty> : (
        <table className="dtable dtable--compact">
          <thead><tr><th>Reassessed pack</th><th>Reassesses</th><th>What changed</th><th>Reason</th><th>Recorded</th></tr></thead>
          <tbody>{r.map((x) => {
            const c = x.change_summary;
            return (
              <tr key={x.pack_id}><td><Link className="id" to={`/packs/${x.pack_id}`}>{x.pack_id}</Link></td>
                <td><Link className="id" to={`/packs/${x.predecessor_pack_id}`}>{x.predecessor_pack_id}</Link></td>
                <td className="xsmall">Inputs changed: {c.inputs_changed?.length ? c.inputs_changed.join(", ") : "none"}
                  {c.exceptions && <div>Exceptions {c.exceptions.before} → {c.exceptions.after}{c.exceptions.added.length ? ` (new: ${c.exceptions.added.join(", ")})` : ""}{c.exceptions.removed.length ? ` (gone: ${c.exceptions.removed.join(", ")})` : ""}</div>}
                  {c.engine_case_status && <div>Engine status {c.engine_case_status[0]} → {c.engine_case_status[1]}</div>}</td>
                <td className="xsmall">{x.reason}</td><td className="xsmall nowrap">{dateTime(x.recorded_at)}</td></tr>
            );
          })}</tbody>
        </table>
      )}</Async>
    </div>
  );
}
