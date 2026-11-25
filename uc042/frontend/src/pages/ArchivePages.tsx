// Monthly archive (backend data): one reconciliation period, and one upload batch with its validation, the analyst's
// decisions on flagged documents, confirmation and processing. Nothing here deletes or overwrites a document or a pack.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { BatchDetail } from "../api/types";
import { Async, Kpis, Notice, Panel, StatusBadge } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { DocumentTable, RunTable } from "../components/upload/documents";
import { useData } from "../data/DataProvider";
import { periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { useJobPoller } from "../hooks/useJobPoller";
import { dateTime } from "../lib/format";

function MockOnly() {
  return <Notice tone="info" title="Backend required">The monthly archive comes from the backend database. Start the app with VITE_DATA_SOURCE=api and the
    backend running; mock data never simulates uploaded documents.</Notice>;
}

function Labelled({ ids, types }: { ids: string[]; types: Record<string, string> }) {
  return <ul>{ids.map((id) => <li key={id}><span className="id">{id}</span> · {types[id] ?? ""}</li>)}</ul>;
}

function BatchActions({ detail, supported, limitation, published, reload }: { detail: BatchDetail; supported: boolean | undefined; limitation: string | null;
  published: boolean; reload: () => void }) {
  const data = useData();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const b = detail.batch;
  const active = detail.runs.find((r) => r.status === "QUEUED" || r.status === "RUNNING");
  const { job } = useJobPoller(active?.job_id, () => reload());
  const pending = b.summary.decisions_pending ?? [];
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try { await fn(); reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  if (b.origin !== "UPLOAD") return <Notice tone="info">Demonstration scenario documents, registered read-only from the synthetic data set. They are archive records and are never processed.</Notice>;
  return (
    <div className="stack stack--sm">
      {b.status === "VALIDATED" && (
        <>
          {pending.length > 0 && <Notice tone="warn" title="Decisions required">{pending.length} flagged document(s) need an Include or Exclude decision with a comment
            (open “Checks” on the document). Nothing is removed automatically.</Notice>}
          <button className="btn btn--primary" disabled={busy || pending.length > 0 || b.validation_status === "INVALID"}
            onClick={() => run(() => data.confirmBatch(b.batch_id))}>Confirm batch</button>
          <p className="xsmall muted">Confirming fixes the decisions. Documents with errors are never processed.</p>
        </>
      )}
      {b.status !== "VALIDATED" && (
        <>
          {supported === false && <Notice tone="warn" title="Processing not available">{limitation}</Notice>}
          {published && !active ? (
            <Notice tone="info" title="This month has a published final audit pack">New evidence for a published month is assessed explicitly, never by the
              normal processing action: use <Link to={`/reports/${b.period_id}#reassessment`}>Reassess in the {periodLabel(b.period_id)} report</Link>. The published
              pack is kept and the new result is linked to it.</Notice>
          ) : active ? <Notice tone="info">Processing run {active.run_id} is {job?.status ?? active.status.toLowerCase()}…</Notice> : (
            <button className="btn btn--primary" disabled={busy || !supported || (b.summary.missing_required ?? []).length > 0}
              onClick={() => run(() => data.processBatch(b.batch_id))}>{detail.runs.length ? "Start a new processing run" : "Start processing"}</button>
          )}
          {(b.summary.missing_required ?? []).length > 0 && <p className="xsmall muted">Processing needs every required evidence type in the period's document set.</p>}
          {detail.runs.length > 0 && !active && <p className="xsmall muted">A new run never overwrites an earlier run or pack; identical documents give the identical pack.</p>}
        </>
      )}
      {error ? <Notice tone="bad">{errorMessage(error)}</Notice> : null}
    </div>
  );
}

export function BatchPage() {
  const { batchId = "" } = useParams();
  const data = useData();
  const state = useApi(() => data.batch(batchId), [data, batchId]);
  const periodId = state.data?.batch.period_id ?? "";
  const period = useApi(() => (periodId ? data.archivePeriod(periodId) : Promise.resolve(null)), [data, periodId]);
  usePage([{ label: "Monthly reports", to: "/reports" }, { label: periodLabel(periodId), to: `/reports/${periodId}` }, { label: batchId }], periodId ? { periodId } : undefined);
  if (!data.capabilities.upload) return <MockOnly />;
  return (
    <Async state={state}>{(d) => {
      const b = d.batch;
      const s = b.summary;
      const types = period.data?.evidence_types ?? {};
      return (
        <div className="stack">
          <div className="page-head">
            <div><div className="eyebrow">Upload batch · <Link to={`/reports/${b.period_id}`}>{periodLabel(b.period_id)}</Link></div>
              <h1 className="page-title mono">{b.batch_id}</h1>
              <p className="page-sub">Uploaded {dateTime(b.created_at)} by {b.created_by} · validation <StatusBadge status={b.validation_status} /> · status <StatusBadge status={b.status} />
                {b.confirmed_at ? <> · confirmed {dateTime(b.confirmed_at)}</> : null}</p></div>
          </div>
          <div className="grid-final">
            <div className="stack">
              <Panel title="Batch summary">
                <div className="stack stack--sm">
                  {s.documents && <Kpis items={[
                    { label: "Valid", value: s.documents.VALID, tone: "sm" },
                    { label: "Warnings", value: s.documents.WARNING, tone: s.documents.WARNING ? "bad" : "sm" },
                    { label: "Errors", value: s.documents.ERROR, tone: s.documents.ERROR ? "bad" : "sm" },
                  ]} />}
                  {(s.missing_required ?? []).length > 0 && <Notice tone="warn" title="Missing required evidence (period document set)"><Labelled ids={s.missing_required!} types={types} /></Notice>}
                  {(s.missing_optional ?? []).length > 0 && <Notice tone="info" title="Optional evidence not supplied"><Labelled ids={s.missing_optional!} types={types} /></Notice>}
                  {s.documents && (s.missing_required ?? []).length === 0 && <Notice tone="ok">Every required evidence type is present in the period's document set.</Notice>}
                  <BatchActions detail={d} supported={period.data?.processing_supported} limitation={period.data?.processing_limitation ?? null}
                    published={(period.data?.period.final_pack_count ?? 0) > 0} reload={state.reload} />
                </div>
              </Panel>
            </div>
            <div className="stack">
              <Panel title="How documents were checked">
                <ul className="small">
                  <li>Identified by content: the exact CSV header, or the key details printed in a PDF (file names are not trusted).</li>
                  <li>Dates are judged on the field that decides the month for each evidence type; other dates are reported as timing differences. Records are never moved between months.</li>
                  <li>Duplicates (same content, same name with different content, repeated record IDs) are flagged, never removed.</li>
                  <li>PDFs are stored as originals with their key details; their content is not read by the AI investigation.</li>
                </ul>
              </Panel>
            </div>
          </div>
          <Panel title="Documents" meta={`${d.documents.length} file(s)`} flush>
            <DocumentTable documents={d.documents} editable={b.status === "VALIDATED" && b.origin === "UPLOAD"} onChange={state.reload} />
          </Panel>
          <Panel title="Processing runs" flush><RunTable runs={d.runs} /></Panel>
        </div>
      );
    }}</Async>
  );
}
