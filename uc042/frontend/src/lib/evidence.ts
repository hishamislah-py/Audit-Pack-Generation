// Groups an investigation's evidence records (ledger or packet) by source and summarises each row for display. Values
// are read from the record fields as stored; the debit/credit indicator is shown exactly as recorded (D / C, or the
// settlement direction), never inferred or re-signed.
import type { SourceRecord } from "../api/types";

export interface EvidenceGroup { key: string; title: string; files: string[] }

export const EVIDENCE_GROUPS: EvidenceGroup[] = [
  { key: "bank", title: "Bank records", files: ["IN-09", "IN-08", "IN-07"] },
  { key: "cashbook", title: "Cashbook entries (firm ledger)", files: ["IN-10"] },
  { key: "settlement", title: "Settlement records", files: ["IN-12", "IN-13"] },
  { key: "transactions", title: "Client transactions", files: ["IN-11"] },
  { key: "recon", title: "Reconciliation records (as reported by the firm)", files: ["IN-05", "IN-06"] },
  { key: "other", title: "Other records", files: [] },
];

export function groupOf(fileId: string | undefined): string {
  return EVIDENCE_GROUPS.find((g) => g.files.includes(fileId ?? ""))?.key ?? "other";
}

export function groupRecords(records: SourceRecord[]): Array<EvidenceGroup & { records: SourceRecord[] }> {
  return EVIDENCE_GROUPS.map((g) => ({ ...g, records: records.filter((r) => groupOf(r.file_id) === g.key) }));
}

const s = (v: unknown) => (v === null || v === undefined || v === "" ? undefined : String(v));

export interface RecordSummary { date?: string; description?: string; dc?: string; amount?: string; currency?: string }

export function summarise(r: SourceRecord): RecordSummary {
  const f = r.fields ?? {};
  const date = s(f.booking_date) ?? s(f.posted_ts)?.slice(0, 10) ?? s(f.settlement_date) ?? s(f.statement_date) ?? s(f.recon_date)
    ?? s(f.clearing_date) ?? s(f.cycle_date) ?? s(f.as_at_ts)?.slice(0, 10) ?? s(f.receipt_date) ?? s(f.logged_ts)?.slice(0, 10);
  const description = s(f.narrative_text) ?? (s(f.entry_type) ? `${f.entry_type}${f.payment_reference ? ` · ${f.payment_reference}` : ""}` : undefined)
    ?? (s(f.batch_id) && s(f.counterparty_type) ? `${f.counterparty_type} batch ${f.batch_id}` : undefined)
    ?? (s(f.line_type) ? `${f.line_type}${f.fee_code ? ` ${f.fee_code}` : ""} · ${f.batch_id ?? ""}` : undefined)
    ?? (s(f.txn_type) ? `${f.txn_type} ${f.status ?? ""} · ${f.payment_reference ?? ""}` : undefined)
    ?? (s(f.ext_recon_id) ? `External reconciliation ${f.account_id ?? ""}` : undefined)
    ?? (s(f.recon_run_id) ? `Internal reconciliation ${f.currency ?? ""}` : undefined)
    ?? (s(f.statement_id) && s(f.closing_balance_amount) ? `End-of-day statement ${f.statement_id}` : undefined)
    ?? s(f.description) ?? r.record_type;
  const dc = s(f.dc_indicator) ?? s(f.balance_dc_indicator) ?? s(f.closing_balance_dc) ?? s(f.direction);
  const amount = s(f.amount) ?? s(f.net_amount_reported) ?? s(f.balance_amount) ?? s(f.closing_balance_amount)
    ?? s(f.difference_reported) ?? s(f.balance);
  return { date, description, dc, amount, currency: s(f.currency) };
}
