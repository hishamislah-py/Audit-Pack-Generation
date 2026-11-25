// Phase 8 screens: review URLs are read-only, paid AI operations need an explicit authorisation, reassessment is an explicit
// action, cases and investigations are reachable, activity codes are readable, and list data is shared but never stale
// after a change. Offline: the mock source (with selected methods replaced by spies) or a stubbed fetch.
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail, Period, PeriodDetail, ReassessmentPlan } from "../api/types";
import { activityLabel, createApiSource } from "../data/apiSource";
import { PACKS, confirmAi, mockSource, renderApp } from "./support";

const T = { timeout: 15000 };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function backendSource() {
  const source = mockSource();
  Object.assign(source, { capabilities: { activity: true, upload: true, realInvestigations: true, realGeneration: true } });
  return source;
}

describe("B: a review URL is read-only", () => {
  it("never opens a review on load or refresh; only the explicit action does, exactly once", async () => {
    const source = mockSource();
    const open = vi.spyOn(source, "openReview");
    const view = renderApp(`/packs/${PACKS.S05}/review`, source);
    expect(await screen.findByRole("button", { name: "Open a new final review" }, T)).toBeInTheDocument();
    view.unmount();
    renderApp(`/packs/${PACKS.S05}/review`, source); // a refresh
    await screen.findByRole("button", { name: "Open a new final review" }, T);
    expect(open).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Open a new final review" }));
    expect(await screen.findByRole("heading", { name: "Final audit pack review" }, T)).toBeInTheDocument();
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("shows an active review instead of opening another", async () => {
    const source = mockSource();
    const s = await source.openReview(PACKS.S05);
    const open = vi.spyOn(source, "openReview");
    renderApp(`/packs/${PACKS.S05}/review`, source);
    expect(await screen.findByRole("heading", { name: "Final audit pack review" }, T)).toBeInTheDocument();
    expect((await screen.findAllByText(s.review_id, undefined, T)).length).toBeGreaterThan(0);
    expect(open).not.toHaveBeenCalled();
  });
});

describe("C: paid AI operations need an explicit authorisation", () => {
  it("cancel sends nothing; confirming sends one authorised request with the provider and model shown", async () => {
    const source = mockSource();
    const start = vi.spyOn(source, "startInvestigation");
    renderApp(`/packs/${PACKS.SC2}/workspace/EXC-SC2-01`, source);
    await userEvent.click(await screen.findByRole("button", { name: "Run investigation" }, T));
    const dialog = await screen.findByRole("dialog", { name: "Authorise an AI investigation" }, T);
    expect(within(dialog).getByText(/may incur charges/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot resolve the exception/i)).toBeInTheDocument();
    expect(within(dialog).getByText("EXC-SC2-01", { exact: false })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Authorise and run" })).toBeDisabled(); // not before the statement is accepted
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await confirmAi("Authorise an AI investigation");
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][2]).toEqual({ confirmed: true, provider: "mock", model: "simulated" });
  });

  it("the closing summary has its own authorisation; cancel requests no preview", async () => {
    const source = mockSource();
    const preview = vi.spyOn(source, "requestPreview");
    renderApp(`/packs/${PACKS.S05}/review`, source);
    await userEvent.click(await screen.findByRole("button", { name: "Open a new final review" }, T));
    await userEvent.click(await screen.findByRole("button", { name: "Generate closing summary and preview" }, T));
    const dialog = await screen.findByRole("dialog", { name: "Authorise the AI closing summary" }, T);
    expect(within(dialog).getByText(/does not resolve exceptions/i)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(preview).not.toHaveBeenCalled();
  });
});

describe("D: reassessment is an explicit, confirmed action", () => {
  it("shows the plan and starts a REASSESSMENT only after a reason is given and confirmed", async () => {
    const source = backendSource();
    const archive = { period_id: "PER-2026-09", title: "September 2026 Reconciliation Audit", reporting_status: "ADDITIONAL_EVIDENCE_RECEIVED",
      pending_reassessment: true, documents_after_publication: 1, final_pack_count: 1, document_count: 1, batch_count: 1, packs: [],
      latest_final_pack_at: "2026-11-04T05:47:45+00:00" } as unknown as Period;
    source.archivePeriod = async () => ({ period: archive, batches: [], documents: [], runs: [], current_set: {}, missing_required: [],
      processing_supported: true, evidence_types: {} } as unknown as PeriodDetail);
    source.finalPacks = async () => [{ final_pack_id: "FAP-H202602-PER-2026-02-v1-b8dd53bd2449", pack_id: PACKS.S05, version: 1,
      supersedes_final_pack_id: null, generated_at: "2026-11-04T05:47:45+00:00", review_decision_id: "RD-x", final_content_sha256: "x" }];
    const plan: ReassessmentPlan = { period_id: "PER-2026-09", latest_final_pack_id: "FAP-H202602-PER-2026-02-v1-b8dd53bd2449",
      latest_final_pack_at: "2026-11-04T05:47:45+00:00", target_pack_id: "PACK-H202602-PER-2026-02-195df2e1f216", pending_reassessment: true,
      uploaded_set: {}, baseline: { pack_id: "PACK-H202602-PER-2026-02-195df2e1f216", dataset: "2026-02", storage_profile: "historical-demo",
        files: { "IN-01": { source_file: "source_data/x.csv", sha256: "a" } } }, baseline_problems: [],
      effective_set: { "IN-01": { source: "BASELINE" } }, missing_required: [],
      new_documents: [{ document_id: "DOC-1", original_filename: "bank_email.pdf", evidence_id: null, category: "Supporting evidence",
        submission_kind: "ADDITIONAL_EVIDENCE", submission_reason: "bank e-mail", created_at: "2026-11-04T10:00:00+00:00", validation_status: "WARNING", batch_id: "UPL-1" }],
      can_reassess: true, blockers: [] };
    source.reassessmentPlan = async () => plan;
    const reconcile = vi.fn(async () => ({ run_id: "RUN-1", period_id: "PER-2026-02", batch_id: "UPL-1", job_id: null, status: "QUEUED",
      started_at: null, completed_at: null, error: "", created_at: "", created_by: "", result: {} }));
    source.reconcile = reconcile as unknown as typeof source.reconcile;
    renderApp("/reports/PER-2026-09", source);
    expect(await screen.findByText("bank_email.pdf", undefined, T)).toBeInTheDocument();
    expect(screen.getByText(/verified against their recorded SHA-256/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reassess September 2026" }));
    const dialog = await screen.findByRole("dialog", { name: "Reassess September 2026" });
    const go = within(dialog).getByRole("button", { name: "Start reassessment" });
    expect(go).toBeDisabled(); // a reason is required
    await userEvent.type(within(dialog).getByRole("textbox"), "bank e-mail received");
    await userEvent.click(go);
    await waitFor(() => expect(reconcile).toHaveBeenCalledWith("PER-2026-09", { purpose: "REASSESSMENT", reason: "bank e-mail received" }));
  });
});

describe("E: exception investigation cases", () => {
  it("shows the case, says a disposition resolves nothing, and appends an entry at the case revision", async () => {
    const source = backendSource();
    const exc = (await source.exceptions(PACKS.SC2))[0];
    const c = { case_id: "CASE-" + "1".repeat(24), period_id: "PER-2026-09", pack_id: PACKS.SC2, exception_id: exc.exception_id, status: "OPEN",
      human_resolution: "UNRESOLVED", revision: 3, created_at: "", created_by: "a", updated_at: "", exception: exc, entries: [],
      supporting_evidence: [], evidence_gaps: [], notes: [], confirmed_observations: [], hypotheses: [], human_decisions: [], ai_requests: [],
      ai_jobs: [], ai_investigations: { published: [], not_published: [] }, missing_evidence_in_pack: [] } as CaseDetail;
    source.caseDetail = async () => c;
    source.sourceEvidence = async () => ({ source: "deterministic_retrieval", sha256: "x", total_records: 1, offset: 0, limit: 1,
      source_records: [{ evidence_id: "IN-09:REC-1", fields: { amount: "1.00" }, source_file: "bank.csv", source_line: 2 }], allowed_citation_ids: [],
      searches: [], relationships: [], control_results: [], conflicts: [], missing_evidence: [], candidate_relationships: [] });
    const add = vi.fn(async () => ({}));
    source.addCaseEntry = add as unknown as typeof source.addCaseEntry;
    renderApp(`/cases/${c.case_id}`, source);
    expect(await screen.findByText(/it resolves nothing by itself/, undefined, T)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Cite IN-09:REC-1" }, T));
    await userEvent.selectOptions(screen.getByLabelText("Entry kind"), "OBSERVATION");
    await userEvent.type(screen.getByLabelText("Entry text"), "Bank shows the debit.");
    await userEvent.click(screen.getByRole("button", { name: "Add entry" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith(c.case_id, { kind: "OBSERVATION", text: "Bank shows the debit.",
      evidence_refs: ["IN-09:REC-1"], expected_revision: 3 }));
  });
});

describe("F: an investigation link opens the investigation", () => {
  it("shows the stored record, findings, eligibility and a link to its exception workspace", async () => {
    const source = mockSource();
    source.toolCalls = async (id) => ({ investigation_id: id, tool_registry_version: "v", summary: null, tool_calls: [] });
    renderApp("/investigations/INV-EXC-SC2-01-eb2021ac50e9", source);
    expect(await screen.findByRole("heading", { name: "INV-EXC-SC2-01-eb2021ac50e9" }, T)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open the exception workspace" }, T)).toHaveAttribute("href",
      `/packs/${PACKS.SC2}/workspace/EXC-SC2-01?inv=INV-EXC-SC2-01-eb2021ac50e9`);
    expect(await screen.findByText(/Confirmed findings/, undefined, T)).toBeInTheDocument();
  });
});

describe("G: readable activity", () => {
  it("labels the new event codes and never shows a raw constant", () => {
    for (const code of ["DATABASE_UNIFIED", "CASE_DECISION_RECORDED", "REASSESSMENT_STARTED", "REVIEW_OPENED", "REVIEW_HOLD", "REVIEW_GENERATED", "AI_AUTHORIZED"]) {
      expect(activityLabel(code)).not.toMatch(/_/);
    }
    expect(activityLabel("SOMETHING_NEW")).toBe("Something new");
  });
});

describe("H: shared list data", () => {
  it("serves concurrent callers with one request and drops the cache after a change", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(new URL(url).pathname);
      return new Response(JSON.stringify(url.includes("/periods") || url.includes("/packs") ? [] : { ok: true }), { status: 200,
        headers: { "Content-Type": "application/json" } });
    }));
    const api = createApiSource();
    await Promise.all([api.periods(), api.periods(), api.packs(), api.periods()]);
    expect(calls.filter((c) => c === "/api/v1/periods")).toHaveLength(1);
    expect(calls.filter((c) => c === "/api/v1/packs")).toHaveLength(1);
    await api.renamePeriod("PER-2026-02", "February report");
    await api.periods();
    expect(calls.filter((c) => c === "/api/v1/periods")).toHaveLength(2); // the change made the next read fresh
  });
});

describe("I.4: source evidence without AI, with provenance", () => {
  it("shows engine records apart from AI-tool records, labels their origin and inspects file, line and SHA-256", async () => {
    const source = backendSource();
    const base = { searches: [], relationships: [], control_results: [], conflicts: [], missing_evidence: [], candidate_relationships: [],
      allowed_citation_ids: [], offset: 0, limit: 10, sha256: "x" };
    const engine = { evidence_id: "IN-09:BE-1", fields: { amount: "10.00", currency: "EUR" }, file_id: "IN-09", file_sha256: "a".repeat(64),
      source_file: "source_data/bank_statement_entries_2026-09.csv", source_line: 7, record_type: "Bank statement entry", retrieved_via: "cited by control result C07" };
    const tool = { ...engine, evidence_id: "IN-12:SB-9", file_id: "IN-12", source_file: "source_data/settlement_batches_2026-09.csv", source_line: 3,
      retrieved_via: "tool get_settlement_batch: batch header" };
    source.sourceEvidence = async () => ({ ...base, source: "deterministic_retrieval", total_records: 1, source_records: [engine] });
    source.evidence = async () => ({ ...base, source: "evidence_ledger", total_records: 2, source_records: [engine, tool] });
    renderApp(`/packs/${PACKS.SC2}/workspace/EXC-SC2-01`, source);
    const enginePanel = (await screen.findByText("Supporting evidence · engine retrieval (no AI)", undefined, T)).closest("section")!;
    expect(await within(enginePanel as HTMLElement).findByText("IN-09:BE-1", undefined, T)).toBeInTheDocument();
    expect(within(enginePanel as HTMLElement).queryByText("IN-12:SB-9")).not.toBeInTheDocument();
    const aiPanel = (await screen.findByText("Records retrieved by the AI investigation's tool calls", undefined, T)).closest("section")!;
    expect(within(aiPanel as HTMLElement).getByText("IN-12:SB-9")).toBeInTheDocument();
    expect(within(aiPanel as HTMLElement).getByText(/not AI findings/)).toBeInTheDocument();
    await userEvent.click(within(enginePanel as HTMLElement).getByText("IN-09:BE-1"));
    const inspector = await screen.findByRole("region", { name: "Citation IN-09:BE-1" });
    expect(within(inspector).getByText(/Engine retrieval \(no AI\)/, { selector: "span" })).toBeInTheDocument();
    expect(within(inspector).getByText("a".repeat(64))).toBeInTheDocument();
    expect(within(inspector).getByText("source_data/bank_statement_entries_2026-09.csv")).toBeInTheDocument();
  });
});
