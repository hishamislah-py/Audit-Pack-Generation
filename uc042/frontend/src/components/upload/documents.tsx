// Source documents of the monthly archive (backend data): identification, dates, duplicates and analyst decisions.
import { Fragment, useState } from "react";
import { errorMessage } from "../../api/client";
import type { CheckMessage, DateColumn, ProcessingRun, SourceDocument } from "../../api/types";
import { useData } from "../../data/DataProvider";
import { SUBMISSION_LABEL } from "../../data/periods";
import { dateTime } from "../../lib/format";
import { Notice, StatusBadge } from "../common";
import { Link } from "react-router-dom";

const LEVEL_TONE = { ERROR: "bad", WARNING: "warn", INFO: "info" } as const;

export function kb(n: number) {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024).toFixed(1)} KB`;
}

function MessageList({ messages }: { messages: CheckMessage[] }) {
  if (!messages.length) return <div className="xsmall muted">No findings.</div>;
  return (
    <ul className="check-list">
      {messages.map((m, i) => (
        <li key={i}><StatusBadge status={m.level} tone={LEVEL_TONE[m.level]} label={m.code} /> <span className="small">{m.message}</span></li>
      ))}
    </ul>
  );
}

function DatesTable({ dates }: { dates: Record<string, DateColumn> }) {
  const rows = Object.entries(dates);
  if (!rows.length) return null;
  return (
    <table className="dtable dtable--compact">
      <thead><tr><th>Field</th><th>Date type</th><th>Decides the month</th><th>Range / value</th><th className="num">Outside month</th><th className="num">Invalid</th><th className="num">Missing</th></tr></thead>
      <tbody>{rows.map(([col, d]) => (
        <tr key={col}>
          <td className="mono xsmall">{col}</td>
          <td className="small">{d.role}</td>
          <td className="small">{d.value !== undefined ? "Document attribute" : d.governing ? "Yes" : "No"}</td>
          <td className="small mono">{d.value ?? (d.from ? `${d.from} → ${d.to}` : "—")}</td>
          <td className="num">{d.outside_month ?? "—"}</td>
          <td className="num">{d.invalid ?? "—"}</td>
          <td className="num">{d.missing ?? "—"}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}

function DecisionForm({ doc, onDone }: { doc: SourceDocument; onDone: () => void }) {
  const data = useData();
  const [comment, setComment] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const decide = async (decision: "INCLUDE" | "EXCLUDE") => {
    setBusy(true);
    setError(undefined);
    try {
      await data.reviewDocument(doc.document_id, { decision, comment });
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <div className="stack stack--sm">
      <label className="field"><span>Decision comment (required)</span>
        <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} aria-label={`Comment for ${doc.original_filename}`}
          placeholder="Why this document is included or excluded" />
      </label>
      <div className="actions">
        <button className="btn btn--sm" disabled={busy || comment.trim().length < 3 || doc.validation_status === "ERROR"} onClick={() => decide("INCLUDE")}>Include</button>
        <button className="btn btn--sm" disabled={busy || comment.trim().length < 3} onClick={() => decide("EXCLUDE")}>Exclude</button>
      </div>
      {error ? <Notice tone="bad">{errorMessage(error)}</Notice> : null}
    </div>
  );
}

export function DocumentTable({ documents, editable = false, onChange, showBatch = false, current }: {
  documents: SourceDocument[]; editable?: boolean; onChange?: () => void; showBatch?: boolean; current?: Set<string>;
}) {
  const data = useData();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="table-scroll">
      <table className="dtable dtable--compact">
        <thead><tr><th>File</th><th>Evidence</th><th>Format</th><th className="num">Records</th><th>Dates (deciding the month)</th>
          <th>Validation</th><th>Flags</th><th>Decision</th>{showBatch && <th>Batch</th>}<th /></tr></thead>
        <tbody>
          {documents.map((d) => {
            const flags = d.checks.messages.filter((m) => m.level !== "INFO");
            const isOpen = open === d.document_id;
            const pending = d.checks.decision_required && !d.review_decision;
            return (
              <Fragment key={d.document_id}>
                <tr className={d.validation_status === "ERROR" ? "is-fail" : undefined}>
                  <td><code className="small">{d.original_filename}</code><div className="xsmall muted">{kb(d.size_bytes)}{d.storage_kind === "POC_DATASET" ? " · demonstration scenario file (read-only)" : ""}
                    {d.submission_kind && d.submission_kind !== "INITIAL" ? <> · <span className="strong">{SUBMISSION_LABEL[d.submission_kind]}</span>{d.replaces_document_id ? <> of <span className="mono">{d.replaces_document_id}</span></> : null}</> : null}</div></td>
                  <td><span className="id">{d.evidence_id ?? "—"}</span><div className="xsmall muted">{d.category ?? "Not identified"}</div></td>
                  <td className="small">{d.file_format}</td>
                  <td className="num">{d.record_count ?? "—"}{d.file_format === "PDF" && d.record_count ? <span className="xsmall muted"> p.</span> : null}</td>
                  <td className="small mono">{d.date_from ? `${d.date_from} → ${d.date_to}` : "—"}</td>
                  <td><StatusBadge status={d.validation_status} /></td>
                  <td className="small">{flags.length ? [...new Set(flags.map((m) => m.code))].join(", ") : "—"}</td>
                  <td>{d.review_decision ? <StatusBadge status={d.review_decision} tone={d.review_decision === "EXCLUDE" ? "warn" : "ok"} />
                    : pending ? <StatusBadge status="DECISION_REQUIRED" tone="warn" label="Decision required" />
                    : current?.has(d.document_id) ? <StatusBadge status="IN_SET" tone="ok" label="In processing set" /> : "—"}</td>
                  {showBatch && <td><Link className="id" to={`/uploads/${d.batch_id}`}>{d.batch_id}</Link></td>}
                  <td><button className="link-btn" onClick={() => setOpen(isOpen ? null : d.document_id)} aria-expanded={isOpen}
                    aria-label={`${isOpen ? "Hide" : "Show"} checks for ${d.original_filename}`}>{isOpen ? "Hide" : "Checks"}</button></td>
                </tr>
                {isOpen && (
                  <tr className="is-detail"><td colSpan={showBatch ? 10 : 9}>
                    <div className="stack stack--sm">
                      {d.submission_kind && d.submission_kind !== "INITIAL" && <div className="small"><span className="strong">{SUBMISSION_LABEL[d.submission_kind]}</span>
                        {d.replaces_document_id ? <> replacing <span className="mono">{d.replaces_document_id}</span> (kept unchanged)</> : null} · reason: {d.submission_reason || "—"}</div>}
                      <MessageList messages={d.checks.messages} />
                      {d.checks.period && <div className="xsmall muted">Period basis: {d.checks.period.basis} · {d.checks.period.in_month} record(s) in the month,
                        {" "}{d.checks.period.outside_month} outside{d.checks.period.boundary_records ? `, ${d.checks.period.boundary_records} boundary` : ""}. Records are never moved between months.</div>}
                      {d.checks.dates && <DatesTable dates={d.checks.dates} />}
                      <div className="xsmall muted mono">SHA-256 {d.sha256} · {d.checks.identified_by ? `identified by ${d.checks.identified_by}` : "not identified"}
                        {d.review_decision ? ` · ${d.review_decision} by ${d.reviewed_by} at ${dateTime(d.reviewed_at)}: ${d.review_comment}` : ""}</div>
                      {data.documentContentUrl(d.document_id) && <a className="small" href={data.documentContentUrl(d.document_id)!}>Download the stored original</a>}
                      {editable && <DecisionForm doc={d} onDone={() => onChange?.()} />}
                    </div>
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RunTable({ runs }: { runs: ProcessingRun[] }) {
  if (!runs.length) return <div className="small muted" style={{ padding: 16 }}>No processing run yet.</div>;
  return (
    <div className="table-scroll">
      <table className="dtable dtable--compact">
        <thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Completed</th><th>Result</th></tr></thead>
        <tbody>{[...runs].reverse().map((r) => {
          const packId = r.result.pack_id as string | undefined;
          return (
            <tr key={r.run_id} className={r.status === "FAILED" || r.status === "BLOCKED" ? "is-fail" : undefined}>
              <td className="id">{r.run_id}<div className="xsmall muted">batch {r.batch_id}</div></td>
              <td><StatusBadge status={r.status} /></td>
              <td className="small nowrap">{r.started_at ? dateTime(r.started_at) : "—"}</td>
              <td className="small nowrap">{r.completed_at ? dateTime(r.completed_at) : "—"}</td>
              <td className="small">{packId ? <><Link className="id" to={`/packs/${packId}`}>{packId}</Link>
                <div className="xsmall muted">{String(r.result.outcome ?? "")}{r.result.exceptions !== undefined ? ` · ${String(r.result.exceptions)} exception(s)` : ""}</div></> : null}
                {r.error ? <div className="small">{r.error}</div> : null}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}
