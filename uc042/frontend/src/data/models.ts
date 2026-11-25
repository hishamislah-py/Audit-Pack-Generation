// Frontend view models: reconciliation periods as shown on the dashboard (built from the backend archive, GET /periods, or
// in mock mode from the pack list), activity items, and the design-only upload pre-check used with mock data. Every other
// type is the backend schema in ../api/types.ts.
import type { PackListItem, Period } from "../api/types";

// AVAILABLE: packs exist · DOCUMENTS_ONLY: documents uploaded, no results yet · OPEN_FOR_UPLOAD: the current month or an
// opened period without documents · NO_DATA: no data was supplied for the month (nothing is invented for it).
export type PeriodState = "AVAILABLE" | "DOCUMENTS_ONLY" | "OPEN_FOR_UPLOAD" | "NO_DATA";

export interface ReconciliationPeriod {
  period_id: string; // "PER-YYYY-MM", the engine's period identifier
  year: number;
  month: number; // 1-12
  label: string; // "September 2026"
  state: PeriodState;
  packs: PackListItem[]; // packs whose summary.period_id equals period_id
  is_current_month: boolean;
  archive: Period | null; // the backend archive record; null in mock mode or when the month has never been opened
}

export interface ActivityItem {
  at: string; // ISO timestamp
  actor: string;
  action: string;
  entity: string;
  link?: string;
  simulated: boolean; // true for actions taken in the mock session (never sent to a backend)
}

export type UploadStatus = "VALID" | "DUPLICATE" | "UNKNOWN_DOCUMENT" | "UNSUPPORTED_TYPE" | "WRONG_PERIOD" | "EMPTY_FILE";

export interface ExpectedDocument {
  id: string; // IN-01 ... IN-19 (upload contract)
  category: string;
  description: string;
  source_type: "CSV" | "PDF";
  required: boolean;
  file_pattern: RegExp; // matched against the file name only
  period_offset: number; // 0 = the reconciliation month; -1 = previous month (monthly return receipt); null-like = undated
  dated: boolean;
}

export interface UploadCheck {
  file_name: string;
  size: number;
  status: UploadStatus;
  document_id: string | null;
  category: string | null;
  source_type: string | null;
  messages: string[];
}

export interface UploadSummary {
  period_id: string;
  files: UploadCheck[];
  missing_required: ExpectedDocument[];
  missing_optional: ExpectedDocument[];
  recognised: number;
  problems: number;
  ready_for_processing: boolean; // true when every required document is present once and valid
}
