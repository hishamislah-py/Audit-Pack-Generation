// MOCK adapter for the design phase. Reads are the captured responses of the real backend (September 2026 scenario
// packs); actions (investigation runs, previews, HOLD / GENERATE) are SIMULATED in memory with the backend's own rules and
// error codes, and are lost on reload. Nothing is sent anywhere, nothing is published, and verification is never claimed.
import { ApiError } from "../../api/client";
import type {
  AiAuthorization, AiConfiguration, AiConfirmation, CaseDetail, CaseEntry, CaseSummary, DashboardSummary, InvestigationToolCalls,
  PackLineage, PeriodExceptionOverview, ReassessmentPlan,
  BatchDetail, DocumentReviewRequest, Period, PeriodDetail, ProcessingRun, SourceDocument,
  Decision, DecisionRequest, DecisionResponse, Evidence, ExceptionDetail, ExceptionInvestigations, ExceptionView, FinalPackDetail,
  FinalPackDocument, FinalPackListItem, FinalPackRecord, Findings, Health, InvestigationDetail, InvestigationVerification, Job, PackDetail,
  PackListItem, PackReconciliation, PackSources, PreviewMeta, Readiness, ReviewHistory, ReviewListItem, ReviewSession, Selection,
} from "../../api/types";
import type { DataSource } from "../DataSource";
import type { ActivityItem } from "../models";
import { buildPeriods } from "../periods";
import { fetchLoader, type FixtureLoader } from "./fixtures";

export const MOCK_ANALYST = { user_id: "mock-analyst", display_name: "Mock Analyst" };
const EDITABLE = ["OPEN", "ON_HOLD", "GENERATION_FAILED"];

export interface MockTiming { queuedMs: number; investigationMs: number; previewMs: number; generateMs: number }
export const DEFAULT_TIMING: MockTiming = { queuedMs: 600, investigationMs: 4500, previewMs: 2500, generateMs: 1500 };

interface PreviewTemplate {
  preview: PreviewMeta;
  selections: Selection[];
  readiness: Readiness;
  acknowledgement_text: string;
}

interface SimJob {
  job: Job;
  created: number;
  durationMs: number;
  outcome: { status: "COMPLETED" | "FAILED"; result: Record<string, unknown> | null; error: string };
  onComplete?: () => void;
  completed: boolean;
}

interface SimReview {
  core: Omit<ReviewSession, "readiness" | "preview_job" | "current_preview" | "acknowledgement_text">;
  preview: PreviewMeta | null;
  previewJobId: string | null;
  template: PreviewTemplate;
  decisions: Decision[];
}

interface SimFinalPack { item: FinalPackListItem; detail: FinalPackDetail; previewPackId: string }

const hex = (n: number) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "+00:00");
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class MockDataSource implements DataSource {
  readonly kind = "mock" as const;
  readonly capabilities = { activity: true, upload: false, realInvestigations: false, realGeneration: false };
  private jobs = new Map<string, SimJob>();
  private sessions = new Map<string, SimReview>();
  private finals: SimFinalPack[] = [];
  private events: ActivityItem[] = [];

  constructor(private load: FixtureLoader = fetchLoader(), private timing: MockTiming = DEFAULT_TIMING,
              private now: () => number = () => Date.now()) {}

  // ------------------------------------------------------------------ reads (captured backend responses)
  health = () => this.load.json<Health>("health");
  packs = () => this.load.json<PackListItem[]>("api/v1/packs");
  pack = (id: string) => this.load.json<PackDetail>(`api/v1/packs/${id}`);
  reconciliation = (id: string) => this.load.json<PackReconciliation>(`api/v1/packs/${id}/reconciliation`);
  sources = (id: string) => this.load.json<PackSources>(`api/v1/packs/${id}/sources`);
  exceptions = (id: string) => this.load.json<ExceptionView[]>(`api/v1/packs/${id}/exceptions`);
  investigation = (id: string) => this.load.json<InvestigationDetail>(`api/v1/investigations/${id}`);
  findings = (id: string) => this.load.json<Findings>(`api/v1/investigations/${id}/findings`);
  evidence = (id: string) => this.load.json<Evidence>(`api/v1/investigations/${id}/evidence`);
  verifyInvestigation = (id: string) => this.load.json<InvestigationVerification>(`api/v1/investigations/${id}/verify`);

  async periods() { return buildPeriods(await this.packs(), new Date(this.now())); }

  async exception(packId: string, exceptionId: string): Promise<ExceptionDetail> {
    const d = await this.load.json<ExceptionDetail>(`api/v1/packs/${packId}/exceptions/${exceptionId}`);
    return { ...d, investigations: { ...d.investigations, active_jobs: this.activeJobs(packId, exceptionId) } };
  }

  async packInvestigations(packId: string): Promise<ExceptionInvestigations[]> {
    const rows = await this.load.json<ExceptionInvestigations[]>(`api/v1/packs/${packId}/investigations`);
    return rows.map((r) => ({ ...r, active_jobs: this.activeJobs(packId, r.exception_id) }));
  }

  async activity(): Promise<ActivityItem[]> {
    const packs = await this.packs();
    const captured: ActivityItem[] = [];
    for (const p of packs) {
      for (const row of await this.load.json<ExceptionInvestigations[]>(`api/v1/packs/${p.pack_id}/investigations`)) {
        for (const i of row.published) {
          if (!i.investigated_at) continue;
          captured.push({ at: i.investigated_at, actor: `${i.provider ?? "AI"} ${i.model ?? ""}`.trim(), simulated: false,
            action: `AI investigation published (${i.investigation_mode} mode, ${i.validation_status})`, entity: i.investigation_id,
            link: `/packs/${p.pack_id}/workspace/${row.exception_id}?inv=${i.investigation_id}` });
        }
      }
    }
    return [...this.events, ...captured].sort((a, b) => b.at.localeCompare(a.at));
  }

  // ------------------------------------------------------------------ simulated jobs
  private record(action: string, entity: string, link?: string) {
    this.events.push({ at: iso(this.now()), actor: MOCK_ANALYST.display_name, action, entity, link, simulated: true });
  }

  private view(sim: SimJob): Job {
    const elapsed = this.now() - sim.created;
    if (elapsed >= sim.durationMs) {
      if (!sim.completed) {
        sim.completed = true;
        sim.onComplete?.();
      }
      return { ...sim.job, status: sim.outcome.status, started_at: iso(sim.created + this.timing.queuedMs),
        completed_at: iso(sim.created + sim.durationMs), result: sim.outcome.result, error_summary: sim.outcome.error };
    }
    if (elapsed >= this.timing.queuedMs) return { ...sim.job, status: "RUNNING", started_at: iso(sim.created + this.timing.queuedMs) };
    return sim.job;
  }

  private activeJobs(packId: string, exceptionId?: string, operation = "INVESTIGATION"): Job[] {
    return [...this.jobs.values()].map((s) => this.view(s))
      .filter((j) => j.pack_id === packId && j.operation === operation && (!exceptionId || j.exception_id === exceptionId)
        && (j.status === "QUEUED" || j.status === "RUNNING"));
  }

  private newJob(operation: Job["operation"], packId: string, exceptionId: string | null, durationMs: number,
                 outcome: SimJob["outcome"], retryOf: string | null = null, onComplete?: () => void): Job {
    const job: Job = { job_id: `JOB-${hex(24)}`, operation, pack_id: packId, exception_id: exceptionId, status: "QUEUED",
      submitted_at: iso(this.now()), started_at: "", completed_at: "", error_summary: "", result: null, retry_of: retryOf };
    this.jobs.set(job.job_id, { job, created: this.now(), durationMs, outcome, onComplete, completed: false });
    return job;
  }

  async job(jobId: string): Promise<Job> {
    const sim = this.jobs.get(jobId);
    if (!sim) throw new ApiError(404, "NOT_FOUND", "job not found");
    return this.view(sim);
  }

  async startInvestigation(packId: string, exceptionId: string, authorization: AiConfirmation, retryOf?: string | null): Promise<Job> {
    if (authorization?.confirmed !== true) throw new ApiError(422, "AUTHORIZATION_REQUIRED", "an investigation needs the analyst's explicit authorisation");
    const detail = await this.exception(packId, exceptionId);
    const active = this.activeJobs(packId, exceptionId);
    if (active.length) {
      throw new ApiError(409, "INVESTIGATION_ACTIVE", "an investigation of this exception is already queued or running",
        { type: "about:blank", title: "Conflict", status: 409, detail: "", code: "INVESTIGATION_ACTIVE", job_id: active[0].job_id });
    }
    const latest = [...detail.investigations.published].sort((a, b) => (b.investigated_at ?? "").localeCompare(a.investigated_at ?? ""))[0];
    const outcome: SimJob["outcome"] = latest
      ? { status: "COMPLETED", error: "", result: { investigation_id: latest.investigation_id, persist_outcome: "SIMULATED", simulated: true,
          note: "Simulated run: no AI call was made. The result shown is the latest investigation already captured for this exception." } }
      : { status: "FAILED", result: { simulated: true, persist_outcome: "SIMULATED" },
          error: "SIMULATED: AI investigations run on the backend. No investigation exists for this exception in the mock data set." };
    this.record("Started AI investigation (simulated)", exceptionId, `/packs/${packId}/workspace/${exceptionId}`);
    return this.newJob("INVESTIGATION", packId, exceptionId, this.timing.investigationMs, outcome, retryOf ?? null);
  }

  // ------------------------------------------------------------------ simulated review sessions
  private readiness(s: SimReview): Readiness {
    const blockers: Readiness["blockers"] = [];
    for (const j of this.activeJobs(s.core.pack_id)) blockers.push({ code: "INVESTIGATION_RUNNING", detail: `an investigation of ${j.exception_id} is ${j.status}` });
    const previewJob = s.previewJobId ? this.view(this.jobs.get(s.previewJobId)!) : null;
    if (previewJob && (previewJob.status === "QUEUED" || previewJob.status === "RUNNING")) blockers.push({ code: "PREVIEW_IN_PROGRESS", detail: "a preview is being generated" });
    if (EDITABLE.includes(s.core.status) && !s.preview) blockers.push({ code: "PREVIEW_REQUIRED", detail: "generate a preview (with the closing summary) before deciding" });
    const warnings: Readiness["warnings"] = s.core.selections.filter((x) => x.inclusion === "NOT_INVESTIGATED")
      .map((x) => ({ code: "NOT_INVESTIGATED", detail: `${x.exception_id} will be reported as not investigated` }));
    if (s.preview?.closing_summary.status === "UNAVAILABLE") {
      warnings.push({ code: "CLOSING_SUMMARY_UNAVAILABLE", detail: `the AI closing summary could not be generated: ${s.preview.closing_summary.unavailable_reason}. GENERATE requires acknowledging this.` });
    }
    if (this.finals.some((f) => f.item.pack_id === s.core.pack_id)) warnings.push({ code: "FINAL_PACK_EXISTS", detail: "a final pack already exists; a new one will be the next version" });
    return { blockers, warnings, info: s.template.readiness.info, ready: blockers.length === 0 };
  }

  private sessionView(s: SimReview): ReviewSession {
    const previewJob = s.previewJobId ? this.view(this.jobs.get(s.previewJobId)!) : null; // may complete the job first
    return { ...s.core, current_preview: s.preview, preview_job: previewJob, readiness: this.readiness(s),
      acknowledgement_text: s.template.acknowledgement_text };
  }

  private session(reviewId: string): SimReview {
    const s = this.sessions.get(reviewId);
    if (!s) throw new ApiError(404, "NOT_FOUND", "review session not found");
    return s;
  }

  private touch(s: SimReview, changes: Partial<SimReview["core"]>) {
    s.core = { ...s.core, ...changes, revision: s.core.revision + 1, updated_at: iso(this.now()) };
  }

  async reviews(filter: { packId?: string; status?: string } = {}): Promise<ReviewListItem[]> {
    return [...this.sessions.values()].map((s) => this.sessionView(s))
      .filter((s) => (!filter.packId || s.pack_id === filter.packId) && (!filter.status || s.status === filter.status))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map((s) => {
        const last = this.sessions.get(s.review_id)!.decisions.at(-1);
        return { review_id: s.review_id, pack_id: s.pack_id, status: s.status, created_at: s.created_at, updated_at: s.updated_at,
          has_preview: !!s.current_preview, final_pack_id: s.final_pack_id,
          last_decision: last ? { review_decision_id: last.review_decision_id, decision: last.decision, decided_at: last.decided_at, comment: last.comment } : null };
      });
  }

  async openReview(packId: string): Promise<ReviewSession> {
    const existing = [...this.sessions.values()].find((s) => s.core.pack_id === packId && s.core.status !== "GENERATED");
    if (existing) return this.sessionView(existing);
    const pack = await this.pack(packId);
    const template = await this.load.json<PreviewTemplate>(`previews/${packId}.meta`);
    const at = iso(this.now());
    const s: SimReview = {
      core: { review_id: `RS-${hex(24)}`, pack_id: packId, pack_content_sha256: pack.summary.pack_content_sha256, status: "OPEN",
        revision: 1, created_at: at, updated_at: at, selections: template.selections, selections_version: 1, final_pack_id: null,
        last_decision_id: null },
      preview: null, previewJobId: null, template, decisions: [],
    };
    this.sessions.set(s.core.review_id, s);
    this.record("Opened final audit-pack review (simulated)", s.core.review_id, `/reviews/${s.core.review_id}`);
    return this.sessionView(s);
  }

  async review(reviewId: string) { return this.sessionView(this.session(reviewId)); }

  async setSelections(reviewId: string, selections: Selection[], expectedRevision?: number): Promise<ReviewSession> {
    const s = this.session(reviewId);
    if (!EDITABLE.includes(s.core.status)) throw new ApiError(409, "SESSION_NOT_EDITABLE", `the review session is ${s.core.status} and cannot be changed`);
    if (expectedRevision && expectedRevision !== s.core.revision) throw new ApiError(409, "REVIEW_CONFLICT", "the review session was changed by another request; reload it");
    const exceptions = await this.exceptions(s.core.pack_id);
    const ids = selections.map((x) => x.exception_id).sort();
    if (JSON.stringify(ids) !== JSON.stringify(exceptions.map((x) => x.exception_id).sort())) {
      throw new ApiError(422, "SELECTION_INCOMPLETE", "every exception in the pack needs exactly one selection");
    }
    for (const sel of selections) {
      if (sel.inclusion === "EXCLUDED_BY_ANALYST" && !sel.reason?.trim()) throw new ApiError(422, "SELECTION_INVALID", `${sel.exception_id}: EXCLUDED_BY_ANALYST requires a reason`);
      if (sel.inclusion === "INCLUDED") {
        const d = await this.exception(s.core.pack_id, sel.exception_id);
        const row = d.investigations.published.find((p) => p.investigation_id === sel.investigation_id);
        if (!row?.eligible) throw new ApiError(422, "INELIGIBLE_SELECTION", `${sel.exception_id}: ${sel.investigation_id} is not eligible: ${(row?.ineligible_reasons ?? ["not found"]).join("; ")}`);
      }
    }
    this.touch(s, { selections, selections_version: s.core.selections_version + 1, status: "OPEN" });
    s.preview = null;
    return this.sessionView(s);
  }

  async requestPreview(reviewId: string, authorization: AiConfirmation): Promise<Job> {
    if (authorization?.confirmed !== true) throw new ApiError(422, "AUTHORIZATION_REQUIRED", "the closing summary needs the analyst's explicit authorisation");
    const s = this.session(reviewId);
    if (!EDITABLE.includes(s.core.status)) throw new ApiError(409, "SESSION_NOT_EDITABLE", `the review session is ${s.core.status}`);
    const blockers = this.readiness(s).blockers.filter((b) => b.code !== "PREVIEW_REQUIRED");
    if (blockers.length) {
      throw new ApiError(409, "BLOCKED", `the preview is blocked: ${blockers.map((b) => b.detail).join("; ")}`,
        { type: "about:blank", title: "Conflict", status: 409, detail: "", code: "BLOCKED", blockers });
    }
    s.preview = null;
    const version = s.core.selections_version;
    const job = this.newJob("PREVIEW", s.core.pack_id, null, this.timing.previewMs,
      { status: "COMPLETED", error: "", result: { review_id: reviewId, simulated: true } }, null, () => {
        if (s.core.selections_version === version && EDITABLE.includes(s.core.status)) {
          s.preview = { ...s.template.preview, preview_id: `PV-${hex(24)}`, selections_version: version, created_at: iso(this.now()) };
        }
      });
    s.previewJobId = job.job_id;
    this.record("Requested closing summary and preview (simulated)", reviewId, `/reviews/${reviewId}`);
    return job;
  }

  private current(reviewId: string, snapshot: string): SimReview {
    const s = this.session(reviewId);
    if (!s.preview) throw new ApiError(404, "NO_PREVIEW", "this review has no current preview; request one");
    if (snapshot !== s.preview.snapshot_sha256) throw new ApiError(409, "PREVIEW_STALE", "this preview is no longer current");
    return s;
  }

  async previewHtml(reviewId: string, snapshot: string) { return this.load.text(`previews/${this.current(reviewId, snapshot).core.pack_id}.html`); }
  async previewDocument(reviewId: string, snapshot: string) { return this.load.json<FinalPackDocument>(`previews/${this.current(reviewId, snapshot).core.pack_id}`); }
  async previewPdf(reviewId: string, snapshot: string) { return this.load.blob(`previews/${this.current(reviewId, snapshot).core.pack_id}.pdf`); }

  async decide(reviewId: string, body: DecisionRequest): Promise<DecisionResponse> {
    const s = this.session(reviewId);
    if (s.core.status === "GENERATING") throw new ApiError(409, "GENERATION_IN_PROGRESS", "this review is being generated");
    if (s.core.status === "GENERATED") {
      throw new ApiError(409, "SESSION_CLOSED", "this review has already produced a final pack",
        { type: "about:blank", title: "Conflict", status: 409, detail: "", code: "SESSION_CLOSED", final_pack_id: s.core.final_pack_id });
    }
    const decision = (): Decision => ({
      review_decision_id: `RD-${hex(24)}`, review_id: reviewId, pack_id: s.core.pack_id, decision: body.decision, decided_at: iso(this.now()),
      reviewer: MOCK_ANALYST, comment: (body.comment ?? "").trim(), acknowledgement_accepted: !!body.acknowledgement_accepted,
      snapshot_sha256: s.preview?.snapshot_sha256 ?? "", preview_id: s.preview?.preview_id ?? "", closing_summary_sha256: s.preview?.closing_summary.sha256 ?? "",
    });
    if (body.decision === "HOLD") {
      if (!body.comment?.trim()) throw new ApiError(422, "COMMENT_REQUIRED", "HOLD requires a comment giving the reason");
      if (body.snapshot_sha256 && body.snapshot_sha256 !== s.preview?.snapshot_sha256) throw new ApiError(409, "PREVIEW_STALE", "the preview has changed; reload it");
      const d = decision();
      s.decisions.push(d);
      this.touch(s, { status: "ON_HOLD", last_decision_id: d.review_decision_id });
      s.preview = null;
      this.record("Recorded HOLD (simulated; nothing published)", reviewId, `/reviews/${reviewId}`);
      return { decision: d, session_status: "ON_HOLD", final_pack: null };
    }
    if (!s.preview) throw new ApiError(409, "PREVIEW_REQUIRED", "no current preview; generate and read a preview first");
    if (body.snapshot_sha256 !== s.preview.snapshot_sha256) throw new ApiError(409, "PREVIEW_STALE", "the decision does not match the current preview; reload the preview");
    if (body.acknowledgement_accepted !== true) throw new ApiError(422, "ACKNOWLEDGEMENT_REQUIRED", `GENERATE requires accepting: ${s.template.acknowledgement_text}`);
    if (s.preview.closing_summary.status === "UNAVAILABLE" && body.acknowledged_summary_unavailable !== true) {
      throw new ApiError(422, "SUMMARY_UNAVAILABLE_ACK_REQUIRED", "the AI closing summary is unavailable; GENERATE requires acknowledging that");
    }
    const blockers = this.readiness(s).blockers;
    if (blockers.length) throw new ApiError(409, "BLOCKED", `generation is blocked: ${blockers.map((b) => b.detail).join("; ")}`);
    const d = decision();
    s.decisions.push(d);
    this.touch(s, { status: "GENERATING", last_decision_id: d.review_decision_id });
    await delay(this.timing.generateMs);
    const previous = this.finals.filter((f) => f.item.pack_id === s.core.pack_id);
    const version = previous.length + 1;
    const scenario = s.core.pack_id.split("-")[1];
    const id = `SIM-FAP-${scenario}-PER-2026-09-v${version}`;
    const at = iso(this.now());
    const record: FinalPackRecord = { review_decision_id: d.review_decision_id, review_id: reviewId, pack_id: s.core.pack_id, status: "GENERATED",
      version, supersedes_final_pack_id: previous.at(-1)?.item.final_pack_id ?? null, created_at: at, final_pack_id: id,
      final_content_sha256: null, error_summary: "", simulated: true };
    const item: FinalPackListItem = { final_pack_id: id, pack_id: s.core.pack_id, version, supersedes_final_pack_id: record.supersedes_final_pack_id,
      generated_at: at, review_decision_id: d.review_decision_id, final_content_sha256: "" };
    const files = Object.fromEntries((["json", "html", "pdf"] as const).map((k) => [k, { name: `${k === "json" ? "final_pack" : "report"}.${k}`, sha256: "", size_bytes: 0,
      media_type: { json: "application/json", html: "text/html", pdf: "application/pdf" }[k] }]));
    const detail: FinalPackDetail = { final_pack_id: id, status: "SIMULATED", version, supersedes_final_pack_id: item.supersedes_final_pack_id, generated_at: at,
      source_pack: { pack_id: s.core.pack_id, pack_content_sha256: s.core.pack_content_sha256 }, final_content_sha256: "",
      human_review: { review_decision_id: d.review_decision_id, decision: "GENERATE", reviewer: d.reviewer, decided_at: d.decided_at, comment: d.comment,
        acknowledgement_accepted: true }, files, record };
    this.finals.push({ item, detail, previewPackId: s.core.pack_id });
    this.touch(s, { status: "GENERATED", final_pack_id: id });
    this.record("GENERATE recorded (simulated final pack; nothing published)", id, `/final-packs/${id}`);
    return { decision: d, session_status: "GENERATED", final_pack: record };
  }

  async reviewHistory(reviewId: string): Promise<ReviewHistory> {
    const s = this.session(reviewId);
    return { review_id: reviewId, decisions: s.decisions,
      final_pack_records: this.finals.filter((f) => f.detail.record?.review_id === reviewId).map((f) => f.detail.record!) };
  }

  // ------------------------------------------------------------------ simulated final packs
  private final(id: string): SimFinalPack {
    const f = this.finals.find((x) => x.item.final_pack_id === id);
    if (!f) throw new ApiError(404, "NOT_FOUND", "final pack not found (simulated packs exist only in this browser session)");
    return f;
  }

  async finalPacks(packId?: string, _lineage?: boolean) { return this.finals.filter((f) => !packId || f.item.pack_id === packId).map((f) => f.item); }
  async finalPack(id: string) { return this.final(id).detail; }
  async verifyFinalPack(id: string) { this.final(id); return null; } // never claims a verification it did not run
  async finalPackDocument(id: string) { return this.load.json<FinalPackDocument>(`previews/${this.final(id).previewPackId}`); }
  async finalPackHtml(id: string) { return this.load.text(`previews/${this.final(id).previewPackId}.html`); }
  async finalPackPdf(id: string) { return this.load.blob(`previews/${this.final(id).previewPackId}.pdf`); }
  finalPackFileUrl() { return null; }

  // ------------------------------------------------------------------ monthly documents: never simulated
  private notAvailable(): Promise<never> {
    return Promise.reject(new ApiError(0, "NOT_AVAILABLE_WITH_MOCK_DATA",
      "Document upload and processing need the backend (VITE_DATA_SOURCE=api); mock data never simulates them."));
  }
  archivePeriod(_periodId: string): Promise<PeriodDetail> { return this.notAvailable(); }
  openPeriod(_year: number, _month: number, _title?: string): Promise<Period> { return this.notAvailable(); }
  renamePeriod(_periodId: string, _title: string): Promise<Period> { return this.notAvailable(); }
  uploadDocuments(_periodId: string, _files: File[]): Promise<BatchDetail> { return this.notAvailable(); }
  batch(_batchId: string): Promise<BatchDetail> { return this.notAvailable(); }
  reviewDocument(_documentId: string, _body: DocumentReviewRequest): Promise<SourceDocument> { return this.notAvailable(); }
  confirmBatch(_batchId: string): Promise<BatchDetail> { return this.notAvailable(); }
  processBatch(_batchId: string): Promise<ProcessingRun> { return this.notAvailable(); }
  processingRun(_runId: string): Promise<ProcessingRun> { return this.notAvailable(); }
  documentContentUrl(_documentId: string): string | null { return null; }
  reconcile(): Promise<ProcessingRun> { return this.notAvailable(); }
  reassessmentPlan(_periodId: string): Promise<ReassessmentPlan> { return this.notAvailable(); }
  async periodLineage(_periodId: string): Promise<PackLineage[]> { return []; } // captured packs have no reassessment lineage
  async periodExceptions(periodId: string): Promise<PeriodExceptionOverview[]> {
    const packs = (await this.packs()).filter((p) => p.summary?.period_id === periodId);
    return Promise.all(packs.map(async (p) => ({ pack_id: p.pack_id, exceptions: await this.exceptions(p.pack_id),
      investigations: await this.packInvestigations(p.pack_id) })));
  }
  invalidate() { /* nothing is cached */ }
  sourceEvidence(_packId: string, _exceptionId: string): Promise<Evidence> { return this.notAvailable(); }
  async aiConfiguration(): Promise<AiConfiguration> {
    return { provider: "mock", model: "simulated", reasoning_effort: null, provider_configured: true, configuration_problem: null,
      investigation_mode: "tools", tool_limits: {}, charges_notice: "Mock data: nothing is sent to any provider and nothing is charged.",
      statements: { INVESTIGATION: "Simulated investigation (mock data): no AI call is made.",
        CLOSING_SUMMARY: "Simulated preview (mock data): no AI call is made." } };
  }
  async aiAuthorizations(): Promise<AiAuthorization[]> { return []; }
  toolCalls(_investigationId: string): Promise<InvestigationToolCalls> { return this.notAvailable(); }
  async cases(): Promise<CaseSummary[]> { return []; }
  openCase(_packId: string, _exceptionId: string): Promise<CaseDetail> { return this.notAvailable(); }
  caseDetail(_caseId: string): Promise<CaseDetail> { return this.notAvailable(); }
  addCaseEntry(): Promise<CaseEntry> { return this.notAvailable(); }
  caseAi(): Promise<Job> { return this.notAvailable(); }

  /** Counts from the captured packs and this session's simulated records (no fixture is invented). */
  async dashboard(periodId?: string): Promise<DashboardSummary> {
    const packs = (await this.packs()).filter((p) => p.summary && (!periodId || p.summary.period_id === periodId));
    const rows = (await Promise.all(packs.map((p) => this.packInvestigations(p.pack_id)))).flat();
    const published = rows.flatMap((r) => r.published);
    const finals = await this.finalPacks();
    const ids = new Set(packs.map((p) => p.pack_id));
    const pending = (await this.reviews()).filter((r) => ["OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED"].includes(r.status));
    return { period_id: periodId ?? null, packs: packs.length,
      exceptions: packs.reduce((n, p) => n + (p.summary?.exceptions.total ?? 0), 0),
      exceptions_open: packs.reduce((n, p) => n + (p.summary?.exceptions.open ?? 0), 0),
      exceptions_with_eligible_investigation: rows.filter((r) => r.published.some((i) => i.eligible)).length,
      investigations: { published: published.filter((i) => i.registry).length, eligible: published.filter((i) => i.eligible).length,
        running: rows.reduce((n, r) => n + r.active_jobs.length, 0), rejected_attempts: rows.reduce((n, r) => n + r.not_published.length, 0),
        unregistered: published.filter((i) => !i.registry).length, authorization_discrepancy: 0, ineligible_other: 0 },
      final_packs_period: finals.filter((f) => ids.has(f.pack_id)).length, latest_final_pack_period_at: null,
      final_packs_global: finals.length, latest_final_pack_global_at: finals.at(-1)?.generated_at ?? null,
      pending_reviews_period: pending.filter((r) => ids.has(r.pack_id)).length, pending_reviews_global: pending.length, per_pack: [] };
  }
}
