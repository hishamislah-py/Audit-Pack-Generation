import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { SubmissionKind } from "../api/types";
import { Async, Kpis, Notice, Panel, SimulatedNotice } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { DropZone, ExpectedChecklist, UploadResults, UploadSteps } from "../components/upload";
import { kb } from "../components/upload/documents";
import { useData } from "../data/DataProvider";
import { periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { checkUpload, illustrativeFileNames } from "../lib/upload";

export function UploadPage() {
  const data = useData();
  return data.capabilities.upload ? <RealUpload /> : <DesignUpload />;
}

/** Backend upload: the files are sent, stored as originals, identified by content and validated. Nothing is processed until
 * the analyst confirms the batch on its page. */
function RealUpload() {
  const data = useData();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const periods = useApi(() => data.periods(), [data]);
  const current = periods.data?.find((p) => p.is_current_month);
  const periodId = params.get("period") ?? current?.period_id ?? "";
  const period = periods.data?.find((p) => p.period_id === periodId);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [kind, setKind] = useState<SubmissionKind>("INITIAL");
  const [reason, setReason] = useState("");
  const [replaces, setReplaces] = useState("");
  const correction = kind === "CORRECTION";
  // A correction names the earlier document of the same month that it replaces (that document is never changed).
  const existing = useApi(() => (correction && period?.archive ? data.archivePeriod(period.period_id) : Promise.resolve(null)),
    [data, correction, period?.period_id]);
  const earlier = existing.data?.documents ?? [];
  usePage([{ label: "Upload documents" }, { label: periodLabel(periodId) }], periodId ? { periodId } : {});
  const step = !periodId ? 0 : files.length === 0 ? 1 : 2;
  const names = new Map<string, number>();
  files.forEach((f) => names.set(f.name, (names.get(f.name) ?? 0) + 1));

  const submit = async () => {
    if (!period) return;
    setBusy(true);
    setError(undefined);
    try {
      if (!period.archive) await data.openPeriod(period.year, period.month);
      const batch = await data.uploadDocuments(period.period_id, files, kind === "INITIAL" ? undefined
        : { kind, reason: reason.trim(), replacesDocumentId: correction ? replaces : undefined });
      navigate(`/uploads/${batch.batch.batch_id}`);
    } catch (e) { setError(e); setBusy(false); }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">Monthly reconciliation</div><h1 className="page-title">Upload financial documents</h1>
          <p className="page-sub">Select the month, add its source files and send them for content identification and validation. Processing starts only after you confirm the batch.</p></div>
      </div>
      {params.get("new") && period && <Notice tone="ok" title={`Monthly report created for ${period.label}`}>Period {period.period_id}. Upload its financial documents below; they are validated before any processing.
        {" "}<Link to={`/reports/${period.period_id}`}>Open the monthly report</Link></Notice>}
      <UploadSteps current={step} />
      <div className="grid-final">
        <div className="stack">
          <Panel title="1. Reconciliation month">
            <Async state={periods}>{(rows) => (
              <div className="stack stack--sm">
                <label className="field"><span>Month</span>
                  <select className="select" value={periodId} onChange={(e) => { setParams({ period: e.target.value }); setError(undefined); }}>
                    {rows.map((p) => <option key={p.period_id} value={p.period_id}>{p.label}{p.state === "AVAILABLE" ? " (has results)" : p.state === "DOCUMENTS_ONLY" ? " (has documents)" : p.is_current_month ? " (current month)" : ""}</option>)}
                  </select>
                </label>
                {period?.archive && period.archive.document_count > 0 && <Notice tone="info">{period.label} already has {period.archive.document_count} document(s) in {period.archive.batch_count} batch(es).
                  A new batch never overwrites them: a newer version of an evidence type supersedes the earlier one for later processing runs, and duplicates are flagged for your decision.{" "}
                  <Link to={`/reports/${period.period_id}`}>Open the monthly report</Link></Notice>}
                {period?.archive?.scenario_packs && <Notice tone="warn">{period.label} holds registered deterministic packs. Uploading here adds a separate batch for the month; existing packs are not changed.</Notice>}
                {(period?.archive?.final_pack_count ?? 0) > 0 && <Notice tone="info">{period!.label} has a published final audit pack. Documents uploaded now are recorded as received after publication; the published pack is not changed.</Notice>}
                <label className="field"><span>These documents are</span>
                  <select className="select" value={kind} onChange={(e) => { setKind(e.target.value as SubmissionKind); setReplaces(""); setFiles((x) => (e.target.value === "CORRECTION" ? x.slice(0, 1) : x)); }}>
                    <option value="INITIAL">Source documents for the month</option><option value="ADDITIONAL_EVIDENCE">Additional evidence for the month</option>
                    <option value="CORRECTION">Correction of an earlier document</option></select></label>
                {correction && <label className="field"><span>Replaces</span>
                  <select className="select" value={replaces} onChange={(e) => setReplaces(e.target.value)}>
                    <option value="">Select the earlier document…</option>
                    {earlier.map((d) => <option key={d.document_id} value={d.document_id}>{d.original_filename} · {d.evidence_id ?? "unidentified"} · {d.document_id}</option>)}</select></label>}
                {correction && !existing.loading && earlier.length === 0 && <p className="xsmall muted">There is no earlier document in this month to correct.</p>}
                {kind !== "INITIAL" && <label className="field"><span>Reason for adding</span>
                  <input className="input" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} placeholder="Why this evidence is being added" /></label>}
                {correction && <p className="xsmall muted">A correction is one file. It is recorded as a new version linked to the document it replaces; the original stays stored and unchanged.</p>}
                {period && <p className="xsmall muted">{period.label} is processed by the same deterministic engine, configured for that month, once every required evidence type for the month is present and valid.</p>}
              </div>
            )}</Async>
          </Panel>
          <Panel title="2. Files" actions={files.length > 0 ? <button className="btn btn--sm btn--ghost" onClick={() => setFiles([])}>Clear</button> : undefined}>
            <div className="stack stack--sm">
              <DropZone onFiles={(f) => setFiles((x) => (correction ? f.slice(0, 1) : [...x, ...f]))} />
              {files.length > 0 && (
                <ul className="file-list" aria-label="Selected files">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`}><span><code>{f.name}</code> <span className="xsmall muted">{kb(f.size)}</span>
                      {(names.get(f.name) ?? 0) > 1 && <span className="xsmall"> · same name selected twice</span>}</span>
                      <button className="link-btn" onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>Remove</button></li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>
        </div>
        <div className="stack">
          <Panel title="3. Send for validation">
            <div className="stack stack--sm">
              <Kpis items={[{ label: "Files selected", value: files.length, tone: "sm" }, { label: "Total size", value: kb(files.reduce((n, f) => n + f.size, 0)), tone: "sm" }]} />
              <button className="btn btn--primary" disabled={busy || !period || files.length === 0 || (kind !== "INITIAL" && reason.trim().length < 3) || (correction && (files.length !== 1 || !replaces))} onClick={submit}>{busy ? "Uploading…" : "Upload and validate"}</button>
              <p className="xsmall muted">Every file is stored as an original (SHA-256) before it is checked, so nothing is lost even if it is rejected. The backend identifies each file by content
                (CSV header, PDF key details), checks the dates that decide the month, flags duplicates and lists missing categories.</p>
              {error ? <Notice tone="bad" title="Upload failed">{errorMessage(error)}</Notice> : null}
              <Link className="small" to={`/reports/${periodId}`}>Back to the {periodLabel(periodId)} report</Link>
            </div>
          </Panel>
          <Panel title="Expected documents" sub="UC-042 upload contract: IN-01 to IN-19" flush><ExpectedChecklist summary={checkUpload(periodId, [])} /></Panel>
        </div>
      </div>
    </div>
  );
}

/** Mock data (development and tests only): the design-phase pre-check on file names; nothing is uploaded. */
function DesignUpload() {
  const data = useData();
  const [params, setParams] = useSearchParams();
  const periods = useApi(() => data.periods(), [data]);
  const current = periods.data?.find((p) => p.is_current_month);
  const periodId = params.get("period") ?? current?.period_id ?? "";
  const period = periods.data?.find((p) => p.period_id === periodId);
  const [files, setFiles] = useState<Array<{ name: string; size: number; illustrative?: boolean }>>([]);
  const summary = useMemo(() => checkUpload(periodId, files), [periodId, files]);
  const [requested, setRequested] = useState(false);
  usePage([{ label: "Upload documents" }, { label: periodLabel(periodId) }]);
  const step = !periodId ? 0 : files.length === 0 ? 1 : summary.problems || summary.missing_required.length ? 2 : 3;

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">New reconciliation period</div><h1 className="page-title">Upload financial documents</h1>
          <p className="page-sub">Select the month, add its source files, and check them against the upload contract before processing.</p></div>
      </div>
      <SimulatedNotice>Design-only workflow. File contents are not read, uploaded or stored, and no dataset changes. The checks use file names, types and sizes;
        header and key-detail validation (the upload contract's identification rules) will run in the backend once ingestion exists.</SimulatedNotice>
      <UploadSteps current={step} />

      <div className="grid-final">
        <div className="stack">
          <Panel title="1. Reconciliation month">
            <Async state={periods}>{(rows) => (
              <div className="stack stack--sm">
                <label className="field"><span>Month</span>
                  <select className="select" value={periodId} onChange={(e) => { setParams({ period: e.target.value }); setFiles([]); setRequested(false); }}>
                    {rows.map((p) => <option key={p.period_id} value={p.period_id}>{p.label}{p.state === "AVAILABLE" ? " (has data)" : p.state === "OPEN_FOR_UPLOAD" ? " (current month)" : ""}</option>)}
                  </select>
                </label>
                {period?.state === "AVAILABLE" && <Notice tone="warn">{period.label} already has {period.packs.length} pack(s). How a re-upload versions a month is not defined yet; this check is for illustration.</Notice>}
              </div>
            )}</Async>
          </Panel>
          <Panel title="2. Files" actions={<>
            <button className="btn btn--sm" onClick={() => setFiles(illustrativeFileNames(periodId).map((name) => ({ name, size: 10240, illustrative: true })))}>Load illustrative file set</button>
            {files.length > 0 && <button className="btn btn--sm btn--ghost" onClick={() => setFiles([])}>Clear</button>}
          </>}>
            <div className="stack stack--sm">
              <DropZone onFiles={(f) => setFiles((x) => [...x, ...f.map(({ name, size }) => ({ name, size }))])} />
              {files.some((f) => f.illustrative) && <p className="xsmall muted">The illustrative set uses the synthetic file names of the upload contract for the selected month (sizes are placeholders). It contains no data.</p>}
            </div>
          </Panel>
          {files.length > 0 && (
            <Panel title="3. Classification and validation" meta={`${summary.files.length} file(s)`} flush>
              <UploadResults summary={summary} onRemove={(i) => setFiles((x) => x.filter((_, j) => j !== i))} />
            </Panel>
          )}
        </div>

        <div className="stack">
          <Panel title="4. Upload summary">
            <div className="stack stack--sm">
              <Kpis items={[
                { label: "Recognised documents", value: `${summary.recognised} / 19`, tone: "sm" },
                { label: "Files with problems", value: summary.problems, tone: summary.problems ? "bad" : "sm" },
                { label: "Missing required", value: summary.missing_required.length, tone: summary.missing_required.length ? "bad" : "sm" },
              ]} />
              {summary.missing_required.length > 0 && files.length > 0 && (
                <Notice tone="warn" title="Missing expected documents"><ul>{summary.missing_required.map((d) => <li key={d.id}>{d.id} · {d.description}</li>)}</ul></Notice>
              )}
              {summary.ready_for_processing && <Notice tone="ok">Every required document is present once and passes the pre-checks.</Notice>}
              <button className="btn btn--primary" disabled={!summary.ready_for_processing || !data.capabilities.upload} onClick={() => setRequested(true)}>5. Start processing</button>
              {!data.capabilities.upload && <p className="xsmall muted">Processing is not available with mock data: the backend has no ingestion endpoint in this mode. Run with the backend (VITE_DATA_SOURCE=api) to upload and process documents.</p>}
              {requested && <Notice tone="info">Processing requested.</Notice>}
              <Link className="small" to={`/?period=${periodId}`}>Back to {periodLabel(periodId)}</Link>
            </div>
          </Panel>
          <Panel title="Expected documents" sub="UC-042 upload contract: IN-01 to IN-19" flush><ExpectedChecklist summary={summary} /></Panel>
        </div>
      </div>
    </div>
  );
}
