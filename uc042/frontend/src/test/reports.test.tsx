// Phase 7: monthly reports archive, report workspace, new monthly report, title change, supporting documents, period-aware
// labels and the PDF viewer fallback. The source is the captured mock data extended with an API-shaped archive (backend
// response shapes as the FastAPI schemas define them): February 2026 is a historical month with a published final audit
// pack, September 2026 one month with demonstration scenarios, October 2026 a month without records.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  BatchDetail, ExceptionInvestigations, ExceptionView, FinalPackDocument, FinalPackListItem, Health, PackListItem, Period, PeriodDetail,
  PeriodPackRef, SourceDocument,
} from "../api/types";
import { PdfViewer } from "../components/review/ReportViewer";
import type { Submission } from "../data/DataSource";
import { MockDataSource } from "../data/mock/MockDataSource";
import { buildArchivePeriods, packKind, periodFromFinalPackId, periodFromPackId, periodId, periodLabel } from "../data/periods";
import { diskLoader, FAST, NOW, PACKS, renderApp } from "./support";

const T = { timeout: 8000 };
const FEB_PACK = "PACK-H202602-PER-2026-02-195df2e1f216";
const FEB_FINAL = "FAP-H202602-PER-2026-02-v1-b8dd53bd2449";
const FEB_INV = "INV-EXC-H202602-01-6b1425b437f4";

function ref(pack_id: string, over: Partial<PeriodPackRef> = {}): PeriodPackRef {
  return { pack_id, origin: "POC_SCENARIO", scenario_id: pack_id.split("-")[1], processing_run_id: null, pack_content_sha256: "0".repeat(64),
    registered_at: "2026-11-04T05:41:00+00:00", verified: true, engine_case_status: "EXCEPTIONS_OPEN", evidence_completeness: "COMPLETE",
    exceptions_total: 1, exceptions_open: 1, final_packs: 0, ...over };
}

function period(id: string, over: Partial<Period> = {}): Period {
  return { period_id: id, use_case: "UC-042", year: Number(id.slice(4, 8)), month: Number(id.slice(9)), status: "PROCESSED",
    created_at: "2026-11-04T05:41:00+00:00", last_processed_at: null, title: "", reporting_status: "NO_DATA", published_investigations: 0,
    eligible_investigations: 0, latest_final_pack_at: null, documents_after_publication: 0, pending_reassessment: false,
    archive_state: "AWAITING_UPLOAD", batch_count: 0, document_count: 0, latest_batch_status: null, latest_validation_status: null,
    latest_run_status: null, pack_count: 0, scenario_packs: false, exceptions_total: 0, exceptions_open: 0, final_pack_count: 0,
    processing_supported: true, packs: [], ...over };
}

function doc(id: string, name: string, over: Partial<SourceDocument> = {}): SourceDocument {
  return { document_id: id, batch_id: "UPL-F1", original_filename: name, evidence_id: "IN-07", category: "Bank balance confirmations at 17:00",
    file_format: "CSV", size_bytes: 2048, sha256: "b".repeat(64), reporting_period: "PER-2026-02", date_from: null, date_to: null,
    record_count: 1, validation_status: "VALID", checks: { messages: [] }, storage_kind: "UPLOADED_ORIGINAL", created_at: "2026-11-04T09:00:00+00:00",
    review_decision: null, review_comment: "", reviewed_at: null, reviewed_by: null, submission_kind: "INITIAL", submission_reason: "",
    replaces_document_id: null, ...over };
}

/** Captured mock reads plus an archive with February (historical), September (scenarios) and October (no records). */
class ReportsSource extends MockDataSource {
  override readonly capabilities = { activity: true, upload: true, realInvestigations: false, realGeneration: false };
  calls: string[] = [];
  pending = false;
  febDocs: SourceDocument[] = [];
  titles: Record<string, string> = { "PER-2026-02": "February 2026 Reconciliation Audit" };

  constructor() {
    super(diskLoader, FAST, () => NOW);
    // the API adapter gives direct file URLs for published final packs; the captured mock has none
    (this as unknown as { finalPackFileUrl: (id: string, kind: string) => string }).finalPackFileUrl = (id, kind) => `http://backend.test/api/v1/final-packs/${id}/${kind}`;
  }

  override health = async (): Promise<Health> => ({ status: "ok", storage: true, registry: true, provider_configured: true, analyst_id: "demo-reviewer",
    single_process: true, version: "test", database: true, environment: { label: "Historical demonstration", database: "uc042_history", packs_root: "demo_history/packs" } });

  private febPack(): PackListItem {
    return { pack_id: FEB_PACK, verified: true, problem: null, summary: { pack_id: FEB_PACK, pack_content_sha256: "1".repeat(64), period_id: "PER-2026-02",
      reporting_period: { period_id: "PER-2026-02", start: "2026-02-01", end: "2026-02-28" }, scenario_id: "H202602",
      scenario_name: "Historical demonstration month, February 2026", pack_kind: "HISTORICAL_MONTHLY", engine_case_status: "EVIDENCE_INCOMPLETE",
      evidence_completeness: "INCOMPLETE", exceptions: { total: 1, open: 1, by_severity: { Critical: 1 } }, control_summary: "NOT_FULLY_ASSESSED",
      outcomes: {}, missing_evidence_items: 1, pack_review_status: "NOT_REVIEWED" } };
  }

  override packs = async (): Promise<PackListItem[]> => {
    const sept = (await diskLoader.json<PackListItem[]>("api/v1/packs")).filter((p) => [PACKS.S05, PACKS.SC2].includes(p.pack_id));
    return [...sept, this.febPack()];
  };

  archive(): Period[] {
    const feb = period("PER-2026-02", { title: this.titles["PER-2026-02"], reporting_status: this.pending ? "ADDITIONAL_EVIDENCE_RECEIVED" : "FINAL_PACK_PUBLISHED",
      published_investigations: 2, eligible_investigations: 1, latest_final_pack_at: "2026-11-04T05:47:45+00:00",
      documents_after_publication: this.pending ? 1 : 0, pending_reassessment: this.pending, archive_state: "RESULTS_AND_FINAL_PACK",
      document_count: this.febDocs.length, batch_count: this.febDocs.length ? 1 : 0, pack_count: 1, scenario_packs: true, exceptions_total: 1,
      exceptions_open: 1, final_pack_count: 1,
      packs: [ref(FEB_PACK, { scenario_id: "H202602", pack_kind: "HISTORICAL_MONTHLY", engine_case_status: "EVIDENCE_INCOMPLETE", final_packs: 1, final_pack_ids: [FEB_FINAL],
        published_investigations: 2, eligible_investigations: 1 })] });
    const sept = period("PER-2026-09", { reporting_status: "DETERMINISTIC_PACK_AVAILABLE", archive_state: "RESULTS_NO_FINAL_PACK", pack_count: 2,
      scenario_packs: true, exceptions_total: 2, exceptions_open: 2, packs: [ref(PACKS.S05, { pack_kind: "DEMONSTRATION_SCENARIO" }), ref(PACKS.SC2, { pack_kind: "DEMONSTRATION_SCENARIO" })] });
    return [sept, feb];
  }

  override async periods() { return buildArchivePeriods(this.archive(), await this.packs(), new Date(NOW)); }

  override archivePeriod(id: string): Promise<PeriodDetail> {
    const p = this.archive().find((x) => x.period_id === id);
    if (!p) return Promise.reject(Object.assign(new Error("not found"), { code: "NOT_FOUND" }));
    const docs = id === "PER-2026-02" ? this.febDocs : [];
    return Promise.resolve({ period: p, batches: docs.length ? [{ batch_id: "UPL-F1", period_id: id, origin: "UPLOAD", created_at: "2026-11-04T09:00:00+00:00",
      created_by: "demo-reviewer", file_count: docs.length, validation_status: "VALID", status: "VALIDATED", summary: {}, error: "", confirmed_at: null, confirmed_by: null }] : [],
      documents: docs, runs: [], current_set: {}, missing_required: [], processing_supported: true, processing_limitation: null, evidence_types: {} });
  }

  override exceptions = async (id: string): Promise<ExceptionView[]> => (id === FEB_PACK
    ? [{ exception_id: "EXC-H202602-01", category: "Missing bank evidence", cause_category: "", severity: "Critical", status: "OPEN",
      review_status: "AWAITING_HUMAN_REVIEW", evidence_status: "", account_id: "SGA-EUR-01", currency: "EUR", amount: null, first_date: "2026-02-16",
      last_date: "2026-02-16", control_codes: [], investigation_group_id: "", affected_result_ids: [], evidence_ids: [], root_cause: "", flags: "",
      resolution_status: "UNRESOLVED" }]
    : diskLoader.json<ExceptionView[]>(`api/v1/packs/${id}/exceptions`));

  override async packInvestigations(id: string): Promise<ExceptionInvestigations[]> {
    if (id !== FEB_PACK) return super.packInvestigations(id);
    return [{ pack_id: FEB_PACK, exception_id: "EXC-H202602-01", not_published: [], active_jobs: [], published: [
      { investigation_id: FEB_INV, investigation_mode: "tools", investigated_at: "2026-11-04T05:46:02+00:00", validation_status: "VALID", simulated: false,
        provider: "openai", model: "gpt-6-luna", findings_schema_version: "1.4", overall_evidence_assessment: "INSUFFICIENT_EVIDENCE", eligible: true,
        library_eligible: true, ineligible_reasons: [], registry: null }] }];
  }

  override async finalPacks(packId?: string): Promise<FinalPackListItem[]> {
    const item: FinalPackListItem = { final_pack_id: FEB_FINAL, pack_id: FEB_PACK, version: 1, supersedes_final_pack_id: null,
      generated_at: "2026-11-04T05:47:45+00:00", review_decision_id: "RD-1", final_content_sha256: "b8dd53bd".padEnd(64, "0") };
    return !packId || packId === FEB_PACK ? [item] : [];
  }

  override finalPackDocument(id: string): Promise<FinalPackDocument> {
    if (id !== FEB_FINAL) return super.finalPackDocument(id);
    return Promise.resolve({ closing_summary: { status: "GENERATED", unavailable_reason: "", model_metadata: {}, created_at: "2026-11-04T05:47:01+00:00",
      output: { overall_position: "The deterministic engine reports EVIDENCE_INCOMPLETE.", summary_text: "The reconciliation is not fully assessed because bank evidence for SGA-EUR-01 on 2026-02-16 is unavailable.",
        key_observations: [], unresolved_items: [{ exception_id: "EXC-H202602-01", text: "remains UNRESOLVED" }], unverified_hypotheses: [], evidence_gaps: [],
        suggested_next_steps: [], limitations: [] } } } as unknown as FinalPackDocument);
  }


  override openPeriod(year: number, month: number, title?: string): Promise<Period> {
    this.calls.push(`open ${year}-${month} ${title}`);
    return Promise.resolve(period(periodId(year, month), { title: title ?? "" }));
  }

  override renamePeriod(id: string, title: string): Promise<Period> {
    this.calls.push(`rename ${id} ${title}`);
    this.titles[id] = title;
    return Promise.resolve(this.archive().find((p) => p.period_id === id)!);
  }

  override uploadDocuments(id: string, files: File[], s?: Submission): Promise<BatchDetail> {
    this.calls.push(`upload ${id} ${files.map((f) => f.name).join(",")} ${s?.kind ?? "INITIAL"} ${s?.reason ?? ""} ${s?.replacesDocumentId ?? ""}`);
    return Promise.resolve({ batch: { batch_id: "UPL-NEW", period_id: id, origin: "UPLOAD", created_at: "2026-11-04T10:00:00+00:00", created_by: "demo-reviewer",
      file_count: files.length, validation_status: "VALID", status: "VALIDATED", summary: {}, error: "", confirmed_at: null, confirmed_by: null }, documents: [], runs: [] });
  }

  override batch(): Promise<BatchDetail> {
    return this.uploadDocuments("PER-2026-02", []);
  }
}

afterEach(() => vi.restoreAllMocks());

describe("period-aware labels", () => {
  it("derives the period of packs and final packs from their identifiers", () => {
    expect(periodLabel(periodFromPackId(FEB_PACK))).toBe("February 2026");
    expect(periodLabel(periodFromFinalPackId(FEB_FINAL))).toBe("February 2026");
    expect(periodFromPackId(PACKS.S05)).toBe("PER-2026-09");
    expect(periodId(2026, 11)).toBe("PER-2026-11");
    expect(packKind({ scenario_id: "H202602", pack_kind: "HISTORICAL_MONTHLY" })).toBe("HISTORICAL_MONTHLY");
    expect(packKind({ scenario_id: "SC2" })).toBe("DEMONSTRATION_SCENARIO");
    expect(packKind({ scenario_id: "CASE" })).toBe("UPLOADED_DOCUMENTS");
  });

  it("contains no September-only assumptions in the screens", () => {
    const root = join(__dirname, "..");
    const files: string[] = [];
    const walk = (d: string) => readdirSync(d).forEach((n) => { const p = join(d, n); if (statSync(p).isDirectory()) { if (n !== "test" && n !== "mock") walk(p); } else if (/\.tsx?$/.test(n)) files.push(p); });
    walk(root);
    for (const f of files) {
      const text = readFileSync(f, "utf-8");
      for (const phrase of ["the only month with data", "POC test scenario", "DEFAULT_PERIOD", "PER-2026-09\""]) {
        expect(text.includes(phrase), `${phrase} in ${f}`).toBe(false);
      }
    }
  });
});

describe("monthly reports archive", () => {
  it("lists one entry per month from the backend records, with statuses from those records", async () => {
    renderApp("/reports", new ReportsSource());
    const feb = await screen.findByRole("row", { name: /February 2026/ }, T);
    expect(within(feb).getByText("February 2026 Reconciliation Audit")).toBeInTheDocument();
    expect(within(feb).getByText("PER-2026-02")).toBeInTheDocument();
    expect(within(feb).getByText("Final audit pack published")).toBeInTheDocument();
    expect(within(feb).getByText("1 historical monthly pack")).toBeInTheDocument();
    const sept = screen.getByRole("row", { name: /September 2026/ });
    expect(within(sept).getByText("2 demonstration scenarios")).toBeInTheDocument(); // grouped in one month, not separate months
    expect(within(sept).getByText("Deterministic pack available")).toBeInTheDocument();
    const oct = screen.getByRole("row", { name: /October 2026/ });
    expect(within(oct).getByText("No data")).toBeInTheDocument(); // an empty month is not shown as a completed report
    expect(within(oct).queryByText(/Published/)).toBeNull();
    expect(screen.getAllByRole("row", { name: /September 2026/ })).toHaveLength(1);
    // report 19: one database; the note names it and states that every period of it is listed
    expect(screen.getByText(/Every reporting period of this database is listed/)).toBeInTheDocument();
    expect(screen.getByText("Historical demonstration")).toBeInTheDocument();
  });

  it("filters, searches and sorts, and opens the month's report", async () => {
    renderApp("/reports", new ReportsSource());
    await screen.findByRole("row", { name: /February 2026/ }, T);
    await userEvent.selectOptions(screen.getByLabelText("Final audit pack"), "published");
    expect(screen.getAllByRole("row")).toHaveLength(2); // header + February
    await userEvent.selectOptions(screen.getByLabelText("Final audit pack"), "");
    await userEvent.type(screen.getByLabelText("Search title or period"), "PER-2026-09");
    expect(screen.getAllByRole("row").map((r) => r.textContent)).toEqual([expect.any(String), expect.stringContaining("September 2026")]);
    await userEvent.clear(screen.getByLabelText("Search title or period"));
    await userEvent.selectOptions(screen.getByLabelText("Reporting status"), "NO_DATA");
    expect(screen.queryByRole("row", { name: /February 2026/ })).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Reporting status"), "");
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "oldest");
    const rows = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(rows[0]).toBe("January 2026");
    await userEvent.click(screen.getByRole("row", { name: /February 2026/ }));
    expect(await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T)).toBeInTheDocument();
  });
});

describe("monthly report workspace", () => {
  it("shows February with its pack type, exception, investigation, closing summary and published audit pack", async () => {
    renderApp("/reports/PER-2026-02", new ReportsSource());
    expect(await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T)).toBeInTheDocument();
    expect(screen.getByText("Monthly report · PER-2026-02")).toBeInTheDocument();
    expect((screen.getByLabelText("Period") as HTMLSelectElement).value).toBe("PER-2026-02"); // topbar shows the selected period
    expect(await screen.findByText("Historical monthly deterministic pack", undefined, T)).toBeInTheDocument();
    await waitFor(() => expect(within(document.getElementById("exceptions")!).getByText("EXC-H202602-01")).toBeInTheDocument(), T);
    expect(await screen.findByText(FEB_INV, { exact: false }, T)).toBeInTheDocument();
    expect(await screen.findByText(/bank evidence for SGA-EUR-01 on 2026-02-16 is unavailable/, undefined, T)).toBeInTheDocument();
    const published = within(document.getElementById("audit-packs")!).getByRole("link", { name: FEB_FINAL });
    expect(published).toHaveAttribute("href", `/final-packs/${FEB_FINAL}`);
    for (const k of ["JSON", "HTML", "PDF"]) expect(screen.getByRole("link", { name: k })).toHaveAttribute("href", expect.stringContaining(`${FEB_FINAL}/${k.toLowerCase()}`));
    expect(screen.queryByText(/Additional evidence received after publication/)).toBeNull(); // no new evidence: no pending reassessment
    expect(screen.queryByText("Does not include evidence received after publication")).toBeNull();
    expect(screen.queryByText(/Scenario H202602/)).toBeNull(); // a historical month is not labelled as a test scenario
  });

  it("keeps the selected period when navigating, and selecting another month updates the screens", async () => {
    renderApp("/reports/PER-2026-02", new ReportsSource());
    await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T);
    await userEvent.click(screen.getByRole("link", { name: "Monthly reports" }));
    await screen.findByRole("row", { name: /February 2026/ }, T);
    expect((screen.getByLabelText("Period") as HTMLSelectElement).value).toBe("PER-2026-02");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "PER-2026-09");
    expect(await screen.findByText("Monthly report · PER-2026-09", undefined, T)).toBeInTheDocument();
    expect(await screen.findByText(/2 demonstration scenarios of this one month/, undefined, T)).toBeInTheDocument();
  });

  it("changes the title explicitly without changing the period ID", async () => {
    const src = new ReportsSource();
    renderApp("/reports/PER-2026-02", src);
    await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T);
    await userEvent.click(screen.getByRole("button", { name: "Change title" }));
    const input = screen.getByLabelText("Report title");
    await userEvent.clear(input);
    await userEvent.type(input, "February 2026 Safeguarding Audit");
    await userEvent.click(screen.getByRole("button", { name: "Save title" }));
    await waitFor(() => expect(src.calls).toContain("rename PER-2026-02 February 2026 Safeguarding Audit"));
    expect(await screen.findByRole("heading", { name: "February 2026 Safeguarding Audit" }, T)).toBeInTheDocument();
    expect(screen.getByText("Monthly report · PER-2026-02")).toBeInTheDocument();
  });

  it("adds supporting evidence to the open month without asking for the month again", async () => {
    const src = new ReportsSource();
    renderApp("/reports/PER-2026-02", src);
    await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T);
    expect(screen.getByText(/has a published final audit pack \(FAP-H202602/)).toBeInTheDocument();
    const upload = screen.getByRole("button", { name: "Upload and validate" });
    expect(upload).toBeDisabled(); // a reason and a file are required
    await userEvent.type(screen.getByLabelText("Reason for adding"), "Bank confirmation for 16 Feb received from the bank");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["statement_id,account_id\n"], "bank_confirmation_16feb.csv", { type: "text/csv" }));
    await userEvent.click(upload);
    await waitFor(() => expect(src.calls).toContain("upload PER-2026-02 bank_confirmation_16feb.csv ADDITIONAL_EVIDENCE Bank confirmation for 16 Feb received from the bank "));
  });

  it("links a correction to the document it replaces (one file only)", async () => {
    const src = new ReportsSource();
    src.febDocs = [doc("DOC-1", "confirmations.csv")];
    renderApp("/reports/PER-2026-02", src);
    await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T);
    await userEvent.selectOptions(screen.getByLabelText("Type"), "CORRECTION");
    await userEvent.type(screen.getByLabelText("Reason for adding"), "Corrected confirmation from the bank");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["x"], "confirmations_v2.csv", { type: "text/csv" }));
    expect(screen.getByRole("button", { name: "Upload and validate" })).toBeDisabled(); // the replaced document must be chosen
    await userEvent.selectOptions(screen.getByLabelText("Replaces"), "DOC-1");
    await userEvent.click(screen.getByRole("button", { name: "Upload and validate" }));
    await waitFor(() => expect(src.calls).toContain("upload PER-2026-02 confirmations_v2.csv CORRECTION Corrected confirmation from the bank DOC-1"));
  });

  it("shows that a published pack has not incorporated evidence received after publication", async () => {
    const src = new ReportsSource();
    src.pending = true;
    src.febDocs = [doc("DOC-2", "late_confirmation.csv", { submission_kind: "ADDITIONAL_EVIDENCE", submission_reason: "late evidence", created_at: "2026-11-04T10:00:00+00:00" })];
    renderApp("/reports/PER-2026-02", src);
    expect(await screen.findByText(/Additional evidence received after publication/, undefined, T)).toBeInTheDocument();
    expect(screen.getByText("Does not include evidence received after publication")).toBeInTheDocument();
    expect(screen.getAllByText("Additional evidence").length).toBeGreaterThan(0);
    expect(within(document.getElementById("audit-packs")!).getByRole("link", { name: FEB_FINAL })).toBeInTheDocument(); // the published version stays available
  });
});

describe("new monthly report", () => {
  it("derives the period ID, prevents a duplicate month and creates the period with its title", async () => {
    const src = new ReportsSource();
    renderApp("/reports/new", src);
    await userEvent.selectOptions(await screen.findByLabelText("Month", undefined, T), "2");
    expect(await screen.findByText(/February 2026 already exists/, undefined, T)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create and continue to upload" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Open February 2026" })).toHaveAttribute("href", "/reports/PER-2026-02");
    await userEvent.selectOptions(screen.getByLabelText("Month"), "12");
    expect(await screen.findByText(/has not started yet/, undefined, T)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Month"), "10");
    expect(screen.getByText("PER-2026-10")).toBeInTheDocument();
    expect((screen.getByLabelText("Report title") as HTMLInputElement).value).toBe("October 2026 Reconciliation Audit");
    await userEvent.clear(screen.getByLabelText("Report title"));
    await userEvent.type(screen.getByLabelText("Report title"), "October 2026 Safeguarding Audit");
    await userEvent.click(screen.getByRole("button", { name: "Create and continue to upload" }));
    await waitFor(() => expect(src.calls).toContain("open 2026-10 October 2026 Safeguarding Audit"));
  });
});

describe("PDF viewer", () => {
  it("never shows a blank frame where the browser cannot display PDFs inline", async () => {
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => { created.push(b); return "blob:pdf"; }, revokeObjectURL: () => undefined }));
    render(<PdfViewer load={() => Promise.resolve(new Blob(["%PDF-1.4"]))} title="report" downloadName="FAP-x.pdf" inline={false} />);
    expect(await screen.findByText("This browser cannot display PDFs inside the page")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute("download", "FAP-x.pdf");
    expect(created[0].type).toBe("application/pdf"); // typed for the browser's viewer; the bytes are unchanged
    cleanup();
    render(<PdfViewer load={() => Promise.resolve(new Blob(["%PDF-1.4"], { type: "application/pdf" }))} title="report" inline />);
    expect(await screen.findByTitle("report")).toHaveAttribute("src", "blob:pdf");
    expect(screen.getByRole("link", { name: "Open the PDF in a new tab" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

// Report 19: the UI parts of the Phase 7 outstanding issues (corrections from the upload page, the upload target follows the
// selected month) plus the workflow links in the sidebar and the single-database environment note.
describe("gap closure (report 19)", () => {
  afterEach(cleanup);

  it("uploads a correction from the upload page, linked to the document it replaces", async () => {
    const src = new ReportsSource();
    src.febDocs = [doc("DOC-1", "confirmations.csv")];
    renderApp("/upload?period=PER-2026-02", src);
    await userEvent.selectOptions(await screen.findByLabelText("These documents are", undefined, T), "CORRECTION");
    await userEvent.type(screen.getByLabelText("Reason for adding"), "Corrected confirmation from the bank");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["x"], "confirmations_v2.csv", { type: "text/csv" }));
    expect(screen.getByRole("button", { name: "Upload and validate" })).toBeDisabled(); // the replaced document must be chosen
    await userEvent.selectOptions(await screen.findByLabelText("Replaces", undefined, T), "DOC-1");
    await userEvent.click(screen.getByRole("button", { name: "Upload and validate" }));
    await waitFor(() => expect(src.calls).toContain("upload PER-2026-02 confirmations_v2.csv CORRECTION Corrected confirmation from the bank DOC-1"));
  });

  it("targets the selected month with the dashboard's upload button", async () => {
    renderApp("/?period=PER-2026-02", new ReportsSource());
    const link = await screen.findByRole("link", { name: "Upload documents for February 2026" }, T);
    expect(link).toHaveAttribute("href", "/upload?period=PER-2026-02");
    expect(screen.queryByRole("link", { name: /Upload documents for November 2026/ })).toBeNull();
  });

  it("opens the selected month's report from the workflow items when no pack is open", async () => {
    renderApp("/reports/PER-2026-02", new ReportsSource());
    await screen.findByRole("heading", { name: "February 2026 Reconciliation Audit" }, T);
    const nav = screen.getByRole("navigation", { name: "Workflow" });
    const recon = within(nav).getByRole("link", { name: /Reconciliation pack/ });
    expect(recon).toHaveAttribute("href", "/reports/PER-2026-02#reconciliation");
    expect(recon).not.toHaveAttribute("aria-disabled");
    expect(within(nav).getByRole("link", { name: /Exceptions & investigation/ })).toHaveAttribute("href", "/reports/PER-2026-02#exceptions");
  });

  it("describes one database with its storage profiles, and counts excluded investigations apart", async () => {
    const src = new ReportsSource();
    src.health = async () => ({ status: "ok", storage: true, registry: true, provider_configured: true, analyst_id: "demo-reviewer", single_process: true,
      version: "test", database: true, environment: { label: "UC-042 (unified)", database: "uc042", packs_root: "packs", storage_profiles: ["primary", "historical-demo"] } });
    const archive = src.archive.bind(src);
    src.archive = () => archive().map((p) => (p.period_id === "PER-2026-02" ? { ...p, published_investigations: 1, excluded_investigations: 1 } : p));
    renderApp("/reports", src);
    expect(await screen.findByText(/Every reporting period of this database is listed/, undefined, T)).toBeInTheDocument();
    expect(screen.getByText(/primary, historical-demo/)).toBeInTheDocument();
    expect(screen.queryByText(/not combined into one archive/)).toBeNull();
    expect(within(await screen.findByRole("row", { name: /February 2026/ }, T)).getByText(/\+1 excluded/)).toBeInTheDocument();
  });
});
