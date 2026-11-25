// Reconciliation periods (months) for the period overview. With the backend, they come from the monthly archive
// (GET /periods); with mock data, from the pack list. Months are never invented from scenario packs: the nine September
// packs stay nine September scenarios, and a month without supplied data is shown as having no data.
import type { PackKind, PackListItem, PackSummary, Period, PeriodPackRef, ReportingStatus, SubmissionKind } from "../api/types";
import type { PeriodState, ReconciliationPeriod } from "./models";

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function periodId(year: number, month: number): string {
  return `PER-${year}-${String(month).padStart(2, "0")}`;
}

export function periodLabel(id: string | null | undefined): string {
  const m = /^PER-(\d{4})-(\d{2})$/.exec(id ?? "");
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : id ?? "—";
}

/** Months from January of `today`'s year up to and including `today`'s month, newest first. */
export function buildPeriods(packs: PackListItem[], today: Date = new Date()): ReconciliationPeriod[] {
  const year = today.getUTCFullYear();
  const current = today.getUTCMonth() + 1;
  const out: ReconciliationPeriod[] = [];
  for (let month = current; month >= 1; month--) {
    const id = periodId(year, month);
    const inPeriod = packs.filter((p) => p.summary?.period_id === id);
    out.push({
      period_id: id, year, month, label: `${MONTHS[month - 1]} ${year}`, packs: inPeriod, is_current_month: month === current,
      state: inPeriod.length ? "AVAILABLE" : month === current ? "OPEN_FOR_UPLOAD" : "NO_DATA", archive: null,
    });
  }
  return out;
}

function archiveState(p: Period | undefined, isCurrent: boolean): PeriodState {
  if (p?.pack_count) return "AVAILABLE";
  if (p?.document_count) return "DOCUMENTS_ONLY";
  if (p || isCurrent) return "OPEN_FOR_UPLOAD";
  return "NO_DATA";
}

/** Months from January of `today`'s year to the current month, plus every archived period of other years; newest first. */
export function buildArchivePeriods(archive: Period[], packs: PackListItem[], today: Date = new Date()): ReconciliationPeriod[] {
  const year = today.getUTCFullYear();
  const current = today.getUTCMonth() + 1;
  const byId = new Map(archive.map((p) => [p.period_id, p]));
  const ids = new Set<string>(archive.map((p) => p.period_id));
  for (let month = 1; month <= current; month++) ids.add(periodId(year, month));
  return [...ids].sort().reverse().map((id) => {
    const [y, m] = [Number(id.slice(4, 8)), Number(id.slice(9, 11))];
    const rec = byId.get(id);
    const own = new Set(rec?.packs.map((x) => x.pack_id) ?? []);
    const isCurrent = y === year && m === current;
    return { period_id: id, year: y, month: m, label: periodLabel(id), is_current_month: isCurrent, archive: rec ?? null,
      packs: packs.filter((p) => own.has(p.pack_id) || (!rec && p.summary?.period_id === id)), state: archiveState(rec, isCurrent) };
  });
}

/** The reporting period a pack belongs to, read from its identifier (PACK-<scenario>-PER-YYYY-MM-<hash>). */
export function periodFromPackId(packId: string | null | undefined): string | undefined {
  const m = /-(PER-\d{4}-\d{2})-[0-9a-f]{12}$/.exec(packId ?? "");
  return m ? m[1] : undefined;
}

/** The reporting period a final audit pack belongs to (FAP-<scenario>-PER-YYYY-MM-v<n>-<hash>). */
export function periodFromFinalPackId(finalPackId: string | null | undefined): string | undefined {
  const m = /-(PER-\d{4}-\d{2})-v\d+-[0-9a-f]{12}$/.exec(finalPackId ?? "");
  return m ? m[1] : undefined;
}

export const PACK_KIND_LABEL: Record<PackKind, string> = {
  HISTORICAL_MONTHLY: "Historical monthly deterministic pack",
  DEMONSTRATION_SCENARIO: "Demonstration scenario",
  UPLOADED_DOCUMENTS: "Deterministic pack from uploaded documents",
};

/** The pack's kind as reported by the backend; packs from older captures without it fall back on their scenario identity. */
export function packKind(p: Pick<PackSummary, "scenario_id" | "pack_kind"> | Pick<PeriodPackRef, "scenario_id" | "pack_kind"> | null | undefined): PackKind {
  if (p?.pack_kind) return p.pack_kind;
  return p?.scenario_id && p.scenario_id !== "CASE" ? "DEMONSTRATION_SCENARIO" : "UPLOADED_DOCUMENTS";
}

export const REPORTING_STATUS_LABEL: Record<ReportingStatus, string> = {
  NO_DATA: "No data", DOCUMENTS_UPLOADED: "Documents uploaded", VALIDATION_REQUIRED: "Validation required",
  DETERMINISTIC_PACK_AVAILABLE: "Deterministic pack available", INVESTIGATION_AVAILABLE: "Investigation available",
  FINAL_PACK_PUBLISHED: "Final audit pack published", ADDITIONAL_EVIDENCE_RECEIVED: "Additional evidence received",
};

export const REPORTING_STATUS_TONE: Record<ReportingStatus, "ok" | "info" | "warn" | "neutral"> = {
  NO_DATA: "neutral", DOCUMENTS_UPLOADED: "info", VALIDATION_REQUIRED: "warn", DETERMINISTIC_PACK_AVAILABLE: "info",
  INVESTIGATION_AVAILABLE: "info", FINAL_PACK_PUBLISHED: "ok", ADDITIONAL_EVIDENCE_RECEIVED: "warn",
};

export const SUBMISSION_LABEL: Record<SubmissionKind, string> = {
  INITIAL: "Source document", ADDITIONAL_EVIDENCE: "Additional evidence", CORRECTION: "Correction",
};

/** The title shown for a period: its recorded report title, else the month and year. */
export function reportTitle(p: { title?: string | null; period_id: string }): string {
  return p.title?.trim() || `${periodLabel(p.period_id)} reconciliation`;
}
