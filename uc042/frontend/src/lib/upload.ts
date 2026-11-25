// Client-side PRE-CHECK of an upload set against the UC-042 upload contract (docs/UC042_UPLOAD_CONTRACT.md): one set is
// up to 19 files (14 CSV + 5 PDF); IN-18 and IN-19 are optional. This checks names, types, sizes, periods and duplicates
// only. The contract identifies files by CSV header and PDF key details; that content validation belongs to the backend
// ingestion step, which does not exist yet. Nothing is uploaded or stored.
import type { ExpectedDocument, UploadCheck, UploadSummary } from "../data/models";

const P = "(\\d{4})-(\\d{2})";
const doc = (id: string, category: string, description: string, source_type: "CSV" | "PDF", required: boolean, pattern: string, period_offset = 0, dated = true): ExpectedDocument =>
  ({ id, category, description, source_type, required, file_pattern: new RegExp(`^${pattern}$`, "i"), period_offset, dated });

export const EXPECTED_DOCUMENTS: ExpectedDocument[] = [
  doc("IN-01", "Reconciliation scope", "Reconciliation-day calendar", "CSV", true, `recon_calendar_${P}\\.csv`),
  doc("IN-02", "Reconciliation scope", "Institution and account inventory", "CSV", true, "account_inventory\\.csv", 0, false),
  doc("IN-03", "Client money", "Client balance snapshots", "CSV", true, `client_balance_snapshots_${P}\\.csv`),
  doc("IN-04", "Client money", "Unallocated receipts register", "CSV", true, `unallocated_register_${P}\\.csv`),
  doc("IN-05", "Firm reconciliation records", "Internal reconciliation records", "CSV", true, `internal_recon_records_${P}\\.csv`),
  doc("IN-06", "Firm reconciliation records", "External reconciliation records", "CSV", true, `external_recon_records_${P}\\.csv`),
  doc("IN-07", "Bank evidence", "Bank balance confirmations", "CSV", true, `bank_balance_confirmations_${P}\\.csv`),
  doc("IN-08", "Bank evidence", "End-of-day bank statements", "CSV", true, `bank_statements_eod_${P}\\.csv`),
  doc("IN-09", "Bank evidence", "Bank statement entries", "CSV", true, `bank_statement_entries_${P}\\.csv`),
  doc("IN-10", "Firm ledger", "Safeguarding-account cash book", "CSV", true, `sga_cashbook_entries_${P}\\.csv`),
  doc("IN-11", "Client money", "Client transactions", "CSV", true, `transactions_${P}\\.csv`),
  doc("IN-12", "Settlement", "Settlement batch headers", "CSV", true, `settlement_batches_${P}\\.csv`),
  doc("IN-13", "Settlement", "Settlement batch lines", "CSV", true, `settlement_lines_${P}\\.csv`),
  doc("IN-14", "Firm reconciliation records", "Discrepancy and corrective-action log", "CSV", true, `discrepancy_log_${P}\\.csv`),
  doc("IN-15", "Bank evidence", "Acknowledgement letter, SGA-GBP-01", "PDF", true, "ack_letter_SGA-GBP-01\\.pdf", 0, false),
  doc("IN-16", "Bank evidence", "Acknowledgement letter, SGA-EUR-01", "PDF", true, "ack_letter_SGA-EUR-01\\.pdf", 0, false),
  doc("IN-17", "Reconciliation scope", "Safeguarding reconciliation policy", "PDF", true, "safeguarding_reconciliation_policy_v[\\d.]+\\.pdf", 0, false),
  doc("IN-18", "Governance", "Governance register", "PDF", false, `governance_register_${P}\\.pdf`),
  doc("IN-19", "Governance", "Monthly safeguarding return receipt (previous month)", "PDF", false, `rep027_submission_receipt_${P}\\.pdf`, -1),
];

function expectedMonth(periodId: string, offset: number): string {
  const m = /^PER-(\d{4})-(\d{2})$/.exec(periodId);
  if (!m) return "";
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1 + offset, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function checkUpload(periodId: string, files: Array<{ name: string; size: number }>): UploadSummary {
  const seen = new Map<string, string>(); // document id -> first file name
  const names = new Set<string>();
  const checks: UploadCheck[] = files.map((f) => {
    const base: UploadCheck = { file_name: f.name, size: f.size, status: "VALID", document_id: null, category: null, source_type: null, messages: [] };
    const ext = f.name.toLowerCase().split(".").pop();
    if (ext !== "csv" && ext !== "pdf") return { ...base, status: "UNSUPPORTED_TYPE", messages: ["Only CSV and PDF files are part of an upload set."] };
    if (names.has(f.name.toLowerCase())) return { ...base, status: "DUPLICATE", messages: ["The same file name was added twice."] };
    names.add(f.name.toLowerCase());
    const match = EXPECTED_DOCUMENTS.map((d) => ({ d, m: d.file_pattern.exec(f.name) })).find((x) => x.m);
    if (!match) return { ...base, status: "UNKNOWN_DOCUMENT", source_type: ext.toUpperCase(), messages: ["Not recognised as one of the 19 expected documents (IN-01 to IN-19)."] };
    const { d, m } = match;
    const out: UploadCheck = { ...base, document_id: d.id, category: d.category, source_type: d.source_type };
    if (f.size === 0) return { ...out, status: "EMPTY_FILE", messages: ["The file is empty."] };
    if (d.dated && m && m[1]) {
      const want = expectedMonth(periodId, d.period_offset);
      if (`${m[1]}-${m[2]}` !== want) {
        return { ...out, status: "WRONG_PERIOD", messages: [`Dated ${m[1]}-${m[2]}; this period expects ${want}${d.period_offset ? " (previous month's return)" : ""}.`] };
      }
    }
    if (seen.has(d.id)) return { ...out, status: "DUPLICATE", messages: [`A second file for ${d.id}; ${seen.get(d.id)} was added first.`] };
    seen.set(d.id, f.name);
    return out;
  });
  const valid = new Set(checks.filter((c) => c.status === "VALID").map((c) => c.document_id));
  const missing = EXPECTED_DOCUMENTS.filter((d) => !valid.has(d.id));
  const missing_required = missing.filter((d) => d.required);
  const problems = checks.filter((c) => c.status !== "VALID").length;
  return { period_id: periodId, files: checks, missing_required, missing_optional: missing.filter((d) => !d.required),
    recognised: valid.size, problems, ready_for_processing: missing_required.length === 0 && problems === 0 };
}

/** File names of the September 2026 synthetic set (as in uc042_dataset), for an illustrative walk-through only. */
export function illustrativeFileNames(periodId: string): string[] {
  const ym = expectedMonth(periodId, 0);
  const prev = expectedMonth(periodId, -1);
  return [
    `recon_calendar_${ym}.csv`, "account_inventory.csv", `client_balance_snapshots_${ym}.csv`, `unallocated_register_${ym}.csv`,
    `internal_recon_records_${ym}.csv`, `external_recon_records_${ym}.csv`, `bank_balance_confirmations_${ym}.csv`,
    `bank_statements_eod_${ym}.csv`, `bank_statement_entries_${ym}.csv`, `sga_cashbook_entries_${ym}.csv`, `transactions_${ym}.csv`,
    `settlement_batches_${ym}.csv`, `settlement_lines_${ym}.csv`, `discrepancy_log_${ym}.csv`, "ack_letter_SGA-GBP-01.pdf",
    "ack_letter_SGA-EUR-01.pdf", "safeguarding_reconciliation_policy_v1.2.pdf", `governance_register_${ym}.pdf`,
    `rep027_submission_receipt_${prev}.pdf`,
  ];
}
