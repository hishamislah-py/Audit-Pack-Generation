// Reconciliation pack tables. Values are shown exactly as the engine reported them (formatted, never recalculated or
// summed). Internal reconciliation = safeguarding requirement vs resource (per currency and day); external reconciliation =
// the firm's ledger balance vs the bank balance (per account and day). The two are never mixed.
import { useNavigate } from "react-router-dom";
import type { Account, ExceptionInvestigations, ExceptionView, ExternalRow, InternalRow, PackSources } from "../../api/types";
import { EXPECTED_DOCUMENTS } from "../../lib/upload";
import { date } from "../../lib/format";
import { Amount, Empty, StatusBadge, UnresolvedTag } from "../common";

const Outcome = ({ v }: { v: string }) => <StatusBadge status={v} />;
const EvidenceStatus = ({ v }: { v: string | null | undefined }) => (v ? <StatusBadge status={v} /> : <span className="faint">—</span>);

export function InternalReconciliationTable({ rows }: { rows: InternalRow[] }) {
  if (!rows.length) return <Empty title="No internal reconciliation rows">The pack has no internal reconciliation results.</Empty>;
  return (
    <div className="table-scroll table-scroll--tall">
      <table className="dtable dtable--compact">
        <thead><tr><th>Date</th><th>Ccy</th><th className="num">Requirement</th><th className="num">Resource</th><th className="num">Difference</th>
          <th className="num">Firm reported</th><th>Outcome</th><th>Evidence</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.date}-${r.currency}`} className={r.difference_outcome === "FAIL" ? "is-fail" : undefined}>
              <td className="nowrap">{date(r.date)}</td><td>{r.currency}</td>
              <td className="num"><Amount value={r.requirement} currency={r.currency} /></td>
              <td className="num"><Amount value={r.resource} currency={r.currency} /></td>
              <td className="num"><Amount value={r.difference} currency={r.currency} flag /></td>
              <td className="num"><Amount value={r.difference_reported} currency={r.currency} /></td>
              <td><Outcome v={r.difference_outcome} /></td><td><EvidenceStatus v={r.evidence_status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExternalReconciliationTable({ rows }: { rows: ExternalRow[] }) {
  if (!rows.length) return <Empty title="No external reconciliation rows">The pack has no external reconciliation results.</Empty>;
  return (
    <div className="table-scroll table-scroll--tall">
      <table className="dtable dtable--compact">
        <thead><tr><th>Date</th><th>Account</th><th className="num">Ledger (firm)</th><th className="num">Bank</th><th className="num">Difference</th>
          <th className="num">Firm reported</th><th>Outcome</th><th>Evidence</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.date}-${r.account_id}`} className={r.difference_outcome === "FAIL" ? "is-fail" : undefined}>
              <td className="nowrap">{date(r.date)}</td><td className="id">{r.account_id}</td>
              <td className="num"><Amount value={r.ledger_balance} currency={r.currency} /></td>
              <td className="num"><Amount value={r.bank_balance} currency={r.currency} /></td>
              <td className="num"><Amount value={r.difference} currency={r.currency} flag /></td>
              <td className="num"><Amount value={r.difference_reported} currency={r.currency} /></td>
              <td><Outcome v={r.difference_outcome} /></td><td><EvidenceStatus v={r.evidence_status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Rows with a non-zero difference or a FAIL outcome, from both views, labelled by view. Nothing is netted. */
export function DifferencesTable({ internal, external }: { internal: InternalRow[]; external: ExternalRow[] }) {
  const rows = [
    ...internal.filter((r) => r.difference_outcome === "FAIL" || /[1-9]/.test(r.difference)).map((r) => ({ view: "Internal", scope: r.currency, ...r })),
    ...external.filter((r) => r.difference_outcome === "FAIL" || /[1-9]/.test(r.difference)).map((r) => ({ view: "External", scope: r.account_id, ...r })),
  ].sort((a, b) => a.date.localeCompare(b.date));
  if (!rows.length) return <Empty title="No reconciliation differences">Every internal and external difference is zero.</Empty>;
  return (
    <div className="table-scroll table-scroll--tall">
      <table className="dtable dtable--compact">
        <thead><tr><th>View</th><th>Date</th><th>Scope</th><th className="num">Difference</th><th>Outcome</th><th>Evidence</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.view}-${r.date}-${r.scope}`}>
              <td>{r.view === "Internal" ? "Internal (requirement vs resource)" : "External (ledger vs bank)"}</td>
              <td className="nowrap">{date(r.date)}</td><td className="id">{r.scope}</td>
              <td className="num"><Amount value={r.difference} currency={r.currency} flag /></td>
              <td><Outcome v={r.difference_outcome} /></td><td><EvidenceStatus v={r.evidence_status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AccountsTable({ accounts, external }: { accounts: Account[]; external: ExternalRow[] }) {
  return (
    <div className="table-scroll">
      <table className="dtable">
        <thead><tr><th>Account</th><th>Class</th><th>Ccy</th><th className="num">Bank balance (last day)</th></tr></thead>
        <tbody>
          {accounts.map((a) => {
            const last = external.filter((r) => r.account_id === a.account_id).at(-1);
            return (
              <tr key={a.account_id}>
                <td><div className="id">{a.account_id}</div><div className="xsmall muted">{a.designation_name || "—"} · {a.account_number_masked}</div></td>
                <td className="small">{a.account_class.replace(/_/g, " ").toLowerCase()}</td><td>{a.currency}</td>
                <td className="num">{last ? <><Amount value={last.bank_balance} currency={a.currency} /><div className="xsmall muted">{date(last.date)}</div></> : <span className="faint">not reconciled externally</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function filePeriod(name: string | undefined): string {
  const m = /(\d{4})-(\d{2})/.exec(name ?? "");
  return m ? `${m[1]}-${m[2]}` : "Undated";
}

export function SourceInventoryTable({ sources }: { sources: PackSources }) {
  return (
    <div className="table-scroll">
      <table className="dtable dtable--compact">
        <thead><tr><th>ID</th><th>File name</th><th>Category</th><th>Source type</th><th className="num">Records</th><th>Status</th><th>Period</th><th>SHA-256</th></tr></thead>
        <tbody>
          {sources.files.map((f) => {
            const exp = EXPECTED_DOCUMENTS.find((d) => d.id === f.evidence_id);
            return (
              <tr key={f.evidence_id}>
                <td className="id">{f.evidence_id}</td>
                <td><span className="file">{f.source_file?.split("/").pop() ?? "—"}</span><div className="xsmall muted">{f.description}</div></td>
                <td className="small">{exp?.category ?? "—"}</td>
                <td className="small">{exp?.source_type ?? (f.source_file?.endsWith(".pdf") ? "PDF" : "CSV")} · {f.evidence_kind.replace(/_/g, " ").toLowerCase()}</td>
                <td className="num">{f.record_count ?? "—"}</td>
                <td><StatusBadge status={f.availability} /> <span className="xsmall muted">{f.requirement.toLowerCase()}</span></td>
                <td className="nowrap small">{filePeriod(f.source_file)}</td>
                <td><code title={f.sha256}>{f.sha256 ? `${f.sha256.slice(0, 12)}…` : "—"}</code></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function aiStatus(row: ExceptionInvestigations | undefined): { label: string; status: string } {
  if (!row) return { label: "Loading…", status: "QUEUED" };
  if (row.active_jobs.length) return { label: "Running", status: "RUNNING" };
  if (row.published.some((p) => p.eligible)) return { label: "Eligible investigation", status: "COMPLETED" };
  if (row.published.length) return { label: `${row.published.length} ineligible`, status: "INTERRUPTED" };
  if (row.not_published.length) return { label: "Failed attempts only", status: "FAILED" };
  return { label: "Not run", status: "NOT_RUN" };
}

export function ExceptionRegisterTable({ packId, exceptions, investigations }: {
  packId: string; exceptions: ExceptionView[]; investigations?: ExceptionInvestigations[];
}) {
  const navigate = useNavigate();
  if (!exceptions.length) return <Empty title="No exceptions">The deterministic engine raised no exceptions for this pack.</Empty>;
  return (
    <div className="table-scroll">
      <table className="dtable">
        <thead><tr><th>ID</th><th>Dates</th><th>Account</th><th>Type</th><th className="num">Amount</th><th>Status</th><th>AI investigation</th><th /></tr></thead>
        <tbody>
          {exceptions.map((x) => {
            const ai = aiStatus(investigations?.find((i) => i.exception_id === x.exception_id));
            return (
              <tr key={x.exception_id} className="is-clickable" onClick={() => navigate(`/packs/${packId}/workspace/${x.exception_id}`)}>
                <td className="id">{x.exception_id}</td>
                <td className="nowrap">{date(x.first_date)}{x.last_date && x.last_date !== x.first_date ? ` – ${date(x.last_date)}` : ""}</td>
                <td className="id">{x.account_id ?? "—"}</td>
                <td className="small">{x.category}<div className="xsmall muted">{x.severity} · <EvidenceStatus v={x.evidence_status} /></div></td>
                <td className="num strong"><Amount value={x.amount} currency={x.currency} /></td>
                <td><UnresolvedTag /></td>
                <td><StatusBadge status={ai.status} label={ai.label} /></td>
                <td className="link-cell">Investigate →</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
