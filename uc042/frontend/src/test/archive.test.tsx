// Monthly archive and upload screens against an API-shaped source (backend responses as the FastAPI schemas define them),
// plus the period builder. The mock data source never simulates an upload; that is tested too.
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { BatchDetail, Period, PeriodDetail, ProcessingRun, SourceDocument } from "../api/types";
import { MockDataSource } from "../data/mock/MockDataSource";
import { buildArchivePeriods } from "../data/periods";
import { diskLoader, FAST, mockSource, NOW, PACKS, renderApp } from "./support";

const T = { timeout: 8000 };

function period(id: string, over: Partial<Period> = {}): Period {
  return { period_id: id, use_case: "UC-042", year: Number(id.slice(4, 8)), month: Number(id.slice(9)), status: "EMPTY",
    created_at: "2026-11-03T09:00:00+00:00", last_processed_at: null, title: "", reporting_status: "NO_DATA", published_investigations: 0,
    eligible_investigations: 0, latest_final_pack_at: null, documents_after_publication: 0, pending_reassessment: false, archive_state: "AWAITING_UPLOAD", batch_count: 0, document_count: 0,
    latest_batch_status: null, latest_validation_status: null, latest_run_status: null, pack_count: 0, scenario_packs: false,
    exceptions_total: 0, exceptions_open: 0, final_pack_count: 0, processing_supported: true, packs: [], ...over };
}

const SEPT = period("PER-2026-09", { status: "PROCESSED", reporting_status: "DETERMINISTIC_PACK_AVAILABLE", archive_state: "RESULTS_NO_FINAL_PACK", pack_count: 2, scenario_packs: true,
  packs: [PACKS.S05, PACKS.SC2].map((pack_id) => ({ pack_id, origin: "POC_SCENARIO" as const, scenario_id: pack_id.split("-")[1],
    processing_run_id: null, pack_content_sha256: "0".repeat(64), registered_at: "2026-11-03T09:00:00+00:00", verified: true,
    engine_case_status: "EXCEPTIONS_OPEN", evidence_completeness: "COMPLETE", exceptions_total: 1, exceptions_open: 1, final_packs: 0 })) });
const OCT = period("PER-2026-10", { status: "DOCUMENTS_UPLOADED", reporting_status: "VALIDATION_REQUIRED", archive_state: "DOCUMENTS_NO_RESULTS", batch_count: 1, document_count: 2,
  latest_batch_status: "VALIDATED", latest_validation_status: "WARNINGS" });

function doc(id: string, name: string, over: Partial<SourceDocument> = {}): SourceDocument {
  return { document_id: id, batch_id: "UPL-1", original_filename: name, evidence_id: "IN-02", category: "Institution and account inventory",
    file_format: "CSV", size_bytes: 2048, sha256: "a".repeat(64), reporting_period: "PER-2026-10", date_from: null, date_to: null,
    record_count: 4, validation_status: "VALID", checks: { messages: [], identified_by: "CSV header" }, storage_kind: "UPLOADED_ORIGINAL",
    created_at: "2026-11-03T09:00:00+00:00", review_decision: null, review_comment: "", reviewed_at: null, reviewed_by: null, ...over };
}

/** Captured mock reads plus an in-memory archive with the backend's rules for decisions, confirmation and processing. */
class ArchiveSource extends MockDataSource {
  override readonly capabilities = { activity: true, upload: true, realInvestigations: false, realGeneration: false };
  calls: string[] = [];
  detail: BatchDetail = {
    batch: { batch_id: "UPL-1", period_id: "PER-2026-10", origin: "UPLOAD", created_at: "2026-11-03T09:00:00+00:00", created_by: "analyst-1",
      file_count: 2, validation_status: "WARNINGS", status: "VALIDATED", error: "", confirmed_at: null, confirmed_by: null,
      summary: { documents: { VALID: 1, WARNING: 1, ERROR: 0 }, missing_required: ["IN-01"], missing_optional: ["IN-18"], decisions_pending: ["DOC-2"] } },
    documents: [doc("DOC-1", "account_inventory.csv"), doc("DOC-2", "account_inventory (1).csv", { validation_status: "WARNING",
      checks: { messages: [{ code: "DUPLICATE_IN_BATCH", level: "WARNING", message: "identical content to account_inventory.csv in this batch" }],
        decision_required: true } })],
    runs: [],
  };

  constructor() { super(diskLoader, FAST, () => NOW); }
  override async periods() { return buildArchivePeriods([OCT, SEPT], await this.packs(), new Date(NOW)); }
  override archivePeriod(id: string): Promise<PeriodDetail> {
    const p = id === "PER-2026-10" ? OCT : SEPT;
    return Promise.resolve({ period: p, batches: [this.detail.batch], documents: this.detail.documents, runs: this.detail.runs, current_set: {},
      missing_required: ["IN-01"], processing_supported: p.processing_supported,
      processing_limitation: null,
      evidence_types: { "IN-01": "Reconciliation-day calendar", "IN-18": "Governance register" } });
  }
  override openPeriod(year: number, month: number) { this.calls.push(`open ${year}-${month}`); return Promise.resolve(period(`PER-${year}-${String(month).padStart(2, "0")}`)); }
  override uploadDocuments(periodId: string, files: File[]) { this.calls.push(`upload ${periodId} ${files.map((f) => f.name).join(",")}`); return Promise.resolve(this.detail); }
  override batch() { return Promise.resolve(structuredClone(this.detail)); }
  override reviewDocument(id: string, body: { decision: "INCLUDE" | "EXCLUDE"; comment: string }) {
    this.calls.push(`review ${id} ${body.decision} ${body.comment}`);
    const d = this.detail.documents.find((x) => x.document_id === id)!;
    Object.assign(d, { review_decision: body.decision, review_comment: body.comment, reviewed_by: "analyst-1", reviewed_at: "2026-11-03T10:00:00+00:00" });
    this.detail.batch.summary.decisions_pending = [];
    return Promise.resolve(d);
  }
  override confirmBatch() {
    this.calls.push("confirm");
    this.detail.batch = { ...this.detail.batch, status: "CONFIRMED", confirmed_at: "2026-11-03T10:01:00+00:00", confirmed_by: "analyst-1" };
    return Promise.resolve(this.detail);
  }
  override processBatch(): Promise<ProcessingRun> { this.calls.push("process"); return Promise.reject(new Error("not expected")); }
}

describe("monthly archive periods", () => {
  it("lists January to November plus archived periods, and invents nothing", () => {
    const packs = [PACKS.S05, PACKS.SC2, PACKS.S01].map((pack_id) => ({ pack_id, verified: true, problem: null,
      summary: { period_id: "PER-2026-09" } as never }));
    const rows = buildArchivePeriods([OCT, SEPT, period("PER-2025-12", { archive_state: "DOCUMENTS_NO_RESULTS", document_count: 3 })], packs, new Date(NOW));
    expect(rows[0].period_id).toBe("PER-2026-11");
    expect(rows.at(-1)!.period_id).toBe("PER-2025-12");
    const by = Object.fromEntries(rows.map((r) => [r.period_id, r]));
    expect(by["PER-2026-11"].state).toBe("OPEN_FOR_UPLOAD");
    expect(by["PER-2026-11"].archive).toBeNull();
    expect(by["PER-2026-10"].state).toBe("DOCUMENTS_ONLY");
    expect(by["PER-2026-09"].packs.map((p) => p.pack_id)).toEqual([PACKS.S05, PACKS.SC2]); // only the archive's own packs
    expect(by["PER-2026-08"].state).toBe("NO_DATA");
    expect(by["PER-2026-08"].packs).toEqual([]);
    expect(by["PER-2025-12"].state).toBe("DOCUMENTS_ONLY");
  });
});

describe("Dashboard with the monthly archive", () => {
  it("shows a month with documents but no results, and the archive table columns", async () => {
    renderApp("/?period=PER-2026-10", new ArchiveSource());
    expect(await screen.findByText("October 2026: documents uploaded, no results yet", undefined, T)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the monthly report" })).toHaveAttribute("href", "/reports/PER-2026-10");
    expect(screen.queryByText(/processing is not available/)).toBeNull(); // every month is processable, subject to its inputs
    const oct = screen.getByRole("row", { name: /October 2026/ });
    expect(within(oct).getByText("Documents, no results")).toBeInTheDocument();
    expect(within(oct).getByText("WARNINGS")).toBeInTheDocument();
    for (const h of ["Documents", "Validation", "Processing", "AI coverage", "Final pack"]) expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("row", { name: /September 2026/ }));
    expect(await screen.findByText(/2 demonstration scenarios for September 2026/, undefined, T)).toBeInTheDocument();
  });

  it("opens a month without data only on request", async () => {
    const src = new ArchiveSource();
    renderApp("/?period=PER-2026-08", src);
    expect(await screen.findByText("No reconciliation data for August 2026", undefined, T)).toBeInTheDocument();
    expect(src.calls).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Open August 2026 for upload" }));
    await waitFor(() => expect(src.calls).toEqual(["open 2026-8"]));
  });
});

describe("Upload batch review", () => {
  it("requires a commented decision on a flagged duplicate, then confirms; processing waits for the missing evidence", async () => {
    const src = new ArchiveSource();
    renderApp("/uploads/UPL-1", src);
    const confirm = await screen.findByRole("button", { name: "Confirm batch" }, T);
    expect(confirm).toBeDisabled();
    expect(screen.getByText("Decision required")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show checks for account_inventory (1).csv" }));
    expect(screen.getByText(/identical content to account_inventory.csv/)).toBeInTheDocument();
    const exclude = screen.getByRole("button", { name: "Exclude" });
    expect(exclude).toBeDisabled(); // a comment is required
    await userEvent.type(screen.getByLabelText("Comment for account_inventory (1).csv"), "Same file twice");
    await userEvent.click(exclude);
    await waitFor(() => expect(src.calls).toContain("review DOC-2 EXCLUDE Same file twice"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm batch" })).toBeEnabled(), T);
    await userEvent.click(screen.getByRole("button", { name: "Confirm batch" }));
    expect(await screen.findByText(/Processing needs every required evidence type/, undefined, T)).toBeInTheDocument();
    expect(screen.queryByText("Processing not available")).toBeNull();
    expect(screen.getByRole("button", { name: "Start processing" })).toBeDisabled(); // IN-01 is missing for October
    expect(src.calls).not.toContain("process");
    expect(screen.getByText(/Reconciliation-day calendar/)).toBeInTheDocument(); // missing IN-01 named with its label
  });
});

describe("Real upload", () => {
  it("opens the month if needed, sends the files and shows the batch", async () => {
    const src = new ArchiveSource();
    renderApp("/upload?period=PER-2026-11", src);
    const input = await screen.findByLabelText("Choose files", undefined, T);
    await userEvent.upload(input, [new File(["a,b\n"], "account_inventory.csv", { type: "text/csv" }), new File(["%PDF-"], "policy.pdf")]);
    expect(within(screen.getByRole("list", { name: "Selected files" })).getAllByRole("listitem")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Upload and validate" }));
    await waitFor(() => expect(src.calls).toEqual(["open 2026-11", "upload PER-2026-11 account_inventory.csv,policy.pdf"]));
    expect(await screen.findByRole("heading", { name: "UPL-1" }, T)).toBeInTheDocument();
  });

  it("is never simulated with mock data", async () => {
    const src = mockSource();
    await expect(src.uploadDocuments("PER-2026-11", [])).rejects.toMatchObject({ code: "NOT_AVAILABLE_WITH_MOCK_DATA" });
    renderApp("/periods/PER-2026-09", src); // the Phase 4 period URL opens the monthly report workspace
    expect(await screen.findByText(/Source documents come from the backend database \(not available with mock data\)/, undefined, T)).toBeInTheDocument();
    cleanup();
    renderApp("/reports/new", src);
    expect(await screen.findByText("Backend required", undefined, T)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create and continue to upload" })).toBeDisabled();
  });
});
