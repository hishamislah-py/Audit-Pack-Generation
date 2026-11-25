// Every backend endpoint the UI uses, in one place (paths exactly as exposed by uc042app; see GET /openapi.json).
import { LONG_TIMEOUT_MS, apiUrl, request } from "./client";
import type {
  ActivityEvent, AiAuthorization, AiConfiguration, AiConfirmation, BatchDetail, CaseDetail, CaseEntry, CaseEntryRequest, CaseSummary,
  DashboardSummary, InvestigationToolCalls, PackLineage, PeriodExceptionOverview, ReassessmentPlan, ReconcileRequest, DocumentReviewRequest, Period, PeriodDetail, ProcessingRun, SourceDocument,
  DecisionRequest, DecisionResponse, Evidence, ExceptionDetail, ExceptionInvestigations, ExceptionView, FinalPackDetail,
  FinalPackDocument, FinalPackListItem, FinalPackVerification, Findings, Health, InvestigationDetail,
  InvestigationVerification, Job, PackDetail, PackListItem, PackReconciliation, PackSources, PreviewMeta, ReviewHistory,
  ReviewListItem, ReviewSession, Selection,
} from "./types";

const e = encodeURIComponent;
const V1 = "/api/v1";

export const api = {
  health: () => request<Health>("/health"),

  // monthly document management (requires the backend database)
  periods: () => request<Period[]>(`${V1}/periods`),
  createPeriod: (year: number, month: number, title?: string) =>
    request<Period>(`${V1}/periods`, { method: "POST", body: title ? { year, month, title } : { year, month } }),
  updatePeriod: (periodId: string, title: string) => request<Period>(`${V1}/periods/${e(periodId)}`, { method: "PATCH", body: { title } }),
  period: (periodId: string) => request<PeriodDetail>(`${V1}/periods/${e(periodId)}`),
  upload: (periodId: string, files: File[], submission?: { kind: string; reason?: string; replacesDocumentId?: string }) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    if (submission) {
      form.append("submission_kind", submission.kind);
      if (submission.reason) form.append("reason", submission.reason);
      if (submission.replacesDocumentId) form.append("replaces_document_id", submission.replacesDocumentId);
    }
    return request<BatchDetail>(`${V1}/periods/${e(periodId)}/uploads`, { method: "POST", body: form, timeoutMs: LONG_TIMEOUT_MS });
  },
  batch: (batchId: string) => request<BatchDetail>(`${V1}/uploads/${e(batchId)}`),
  confirmBatch: (batchId: string) => request<BatchDetail>(`${V1}/uploads/${e(batchId)}/confirm`, { method: "POST" }),
  processBatch: (batchId: string) => request<ProcessingRun>(`${V1}/uploads/${e(batchId)}/process`, { method: "POST" }),
  document: (documentId: string) => request<SourceDocument>(`${V1}/documents/${e(documentId)}`),
  reviewDocument: (documentId: string, body: DocumentReviewRequest) =>
    request<SourceDocument>(`${V1}/documents/${e(documentId)}/review`, { method: "POST", body: { ...body } }),
  documentContentUrl: (documentId: string) => apiUrl(`${V1}/documents/${e(documentId)}/content`),
  processingRun: (runId: string) => request<ProcessingRun>(`${V1}/processing-runs/${e(runId)}`),
  reconcile: (periodId: string, body: ReconcileRequest) =>
    request<ProcessingRun>(`${V1}/periods/${e(periodId)}/reconciliation`, { method: "POST", body: { ...body } }),
  reassessmentPlan: (periodId: string) => request<ReassessmentPlan>(`${V1}/periods/${e(periodId)}/reassessment`),
  periodLineage: (periodId: string) => request<PackLineage[]>(`${V1}/periods/${e(periodId)}/lineage`),
  periodExceptions: (periodId: string) =>
    request<PeriodExceptionOverview[]>(`${V1}/periods/${e(periodId)}/exception-overview`),
  dashboard: (periodId?: string) => request<DashboardSummary>(`${V1}/dashboard${periodId ? `?period_id=${e(periodId)}` : ""}`),
  activity: (limit = 50) => request<ActivityEvent[]>(`${V1}/activity?limit=${limit}`),

  // packs (read-only)
  packs: () => request<PackListItem[]>(`${V1}/packs`),
  pack: (packId: string) => request<PackDetail>(`${V1}/packs/${e(packId)}`),
  reconciliation: (packId: string) => request<PackReconciliation>(`${V1}/packs/${e(packId)}/reconciliation`),
  sources: (packId: string) => request<PackSources>(`${V1}/packs/${e(packId)}/sources`),
  exceptions: (packId: string) => request<ExceptionView[]>(`${V1}/packs/${e(packId)}/exceptions`),
  exception: (packId: string, exceptionId: string) =>
    request<ExceptionDetail>(`${V1}/packs/${e(packId)}/exceptions/${e(exceptionId)}`),

  // investigations and jobs
  packInvestigations: (packId: string) => request<ExceptionInvestigations[]>(`${V1}/packs/${e(packId)}/investigations`),
  exceptionInvestigations: (packId: string, exceptionId: string) =>
    request<ExceptionInvestigations>(`${V1}/packs/${e(packId)}/exceptions/${e(exceptionId)}/investigations`),
  startInvestigation: (packId: string, exceptionId: string, authorization: AiConfirmation, retryOf?: string | null) =>
    request<Job>(`${V1}/packs/${e(packId)}/exceptions/${e(exceptionId)}/investigations`, {
      method: "POST", body: { mode: "tools", authorization: { ...authorization }, ...(retryOf ? { retry_of: retryOf } : {}) },
    }),
  sourceEvidence: (packId: string, exceptionId: string) =>
    request<Evidence>(`${V1}/packs/${e(packId)}/exceptions/${e(exceptionId)}/source-evidence`),
  aiConfiguration: () => request<AiConfiguration>(`${V1}/ai/configuration`),
  aiAuthorizations: (filter: { packId?: string; exceptionId?: string; reviewId?: string; jobId?: string } = {}) => {
    const q = new URLSearchParams();
    if (filter.packId) q.set("pack_id", filter.packId);
    if (filter.exceptionId) q.set("exception_id", filter.exceptionId);
    if (filter.reviewId) q.set("review_id", filter.reviewId);
    if (filter.jobId) q.set("job_id", filter.jobId);
    const qs = q.toString();
    return request<AiAuthorization[]>(`${V1}/ai/confirmations${qs ? `?${qs}` : ""}`);
  },
  toolCalls: (id: string) => request<InvestigationToolCalls>(`${V1}/investigations/${e(id)}/tool-calls`),

  // exception investigation cases (an analyst's own record; a case decision never changes the pack or a final pack)
  cases: (filter: { periodId?: string; packId?: string } = {}) => {
    const q = new URLSearchParams();
    if (filter.periodId) q.set("period_id", filter.periodId);
    if (filter.packId) q.set("pack_id", filter.packId);
    const qs = q.toString();
    return request<CaseSummary[]>(`${V1}/cases${qs ? `?${qs}` : ""}`);
  },
  openCase: (packId: string, exceptionId: string) =>
    request<CaseDetail>(`${V1}/packs/${e(packId)}/exceptions/${e(exceptionId)}/case`, { method: "POST" }),
  caseDetail: (caseId: string) => request<CaseDetail>(`${V1}/cases/${e(caseId)}`),
  addCaseEntry: (caseId: string, body: CaseEntryRequest) =>
    request<CaseEntry>(`${V1}/cases/${e(caseId)}/entries`, { method: "POST", body: { ...body } }),
  caseAi: (caseId: string, authorization: AiConfirmation, retryOf?: string | null) =>
    request<Job>(`${V1}/cases/${e(caseId)}/ai-investigation`, {
      method: "POST", body: { authorization: { ...authorization }, ...(retryOf ? { retry_of: retryOf } : {}) },
    }),
  job: (jobId: string) => request<Job>(`${V1}/jobs/${e(jobId)}`),
  investigation: (id: string) => request<InvestigationDetail>(`${V1}/investigations/${e(id)}`),
  findings: (id: string) => request<Findings>(`${V1}/investigations/${e(id)}/findings`),
  evidence: (id: string, params: { offset?: number; limit?: number; evidenceId?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.offset) q.set("offset", String(params.offset));
    if (params.limit) q.set("limit", String(params.limit));
    if (params.evidenceId) q.set("evidence_id", params.evidenceId);
    const qs = q.toString();
    return request<Evidence>(`${V1}/investigations/${e(id)}/evidence${qs ? `?${qs}` : ""}`);
  },
  verifyInvestigation: (id: string) => request<InvestigationVerification>(`${V1}/investigations/${e(id)}/verify`),

  // reviews
  reviews: (filter: { packId?: string; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (filter.packId) q.set("pack_id", filter.packId);
    if (filter.status) q.set("status", filter.status);
    const qs = q.toString();
    return request<ReviewListItem[]>(`${V1}/reviews${qs ? `?${qs}` : ""}`);
  },
  openReview: (packId: string) => request<ReviewSession>(`${V1}/packs/${e(packId)}/reviews`, { method: "POST" }),
  review: (reviewId: string) => request<ReviewSession>(`${V1}/reviews/${e(reviewId)}`),
  setSelections: (reviewId: string, selections: Selection[], expectedRevision?: number) =>
    request<ReviewSession>(`${V1}/reviews/${e(reviewId)}/selections`, {
      method: "PATCH", body: { selections, ...(expectedRevision ? { expected_revision: expectedRevision } : {}) },
    }),
  requestPreview: (reviewId: string, authorization: AiConfirmation) =>
    request<Job>(`${V1}/reviews/${e(reviewId)}/preview`, { method: "POST", body: { authorization: { ...authorization } } }),
  previewMeta: (reviewId: string) => request<PreviewMeta>(`${V1}/reviews/${e(reviewId)}/preview`),
  previewHtml: (reviewId: string, snapshot: string) =>
    request<string>(`${V1}/reviews/${e(reviewId)}/preview/html?snapshot=${e(snapshot)}`, { as: "text" }),
  previewDocument: (reviewId: string, snapshot: string) =>
    request<FinalPackDocument>(`${V1}/reviews/${e(reviewId)}/preview/json?snapshot=${e(snapshot)}`),
  previewPdfUrl: (reviewId: string, snapshot: string) =>
    apiUrl(`${V1}/reviews/${e(reviewId)}/preview/pdf?snapshot=${e(snapshot)}`),
  decide: (reviewId: string, body: DecisionRequest) =>
    request<DecisionResponse>(`${V1}/reviews/${e(reviewId)}/decision`, {
      method: "POST", body: body as unknown as Record<string, unknown>, timeoutMs: LONG_TIMEOUT_MS,
    }),
  reviewHistory: (reviewId: string) => request<ReviewHistory>(`${V1}/reviews/${e(reviewId)}/history`),

  // final packs (immutable, read-only)
  finalPacks: (packId?: string, lineage = false) =>
    request<FinalPackListItem[]>(`${V1}/final-packs${packId ? `?pack_id=${e(packId)}${lineage ? "&lineage=true" : ""}` : ""}`),
  finalPack: (id: string) => request<FinalPackDetail>(`${V1}/final-packs/${e(id)}`),
  verifyFinalPack: (id: string) => request<FinalPackVerification>(`${V1}/final-packs/${e(id)}/verify`, { timeoutMs: LONG_TIMEOUT_MS }),
  finalPackDocument: (id: string) => request<FinalPackDocument>(`${V1}/final-packs/${e(id)}/json`),
  finalPackHtml: (id: string) => request<string>(`${V1}/final-packs/${e(id)}/html`, { as: "text" }),
  finalPackPdf: (id: string) => request<Blob>(`${V1}/final-packs/${e(id)}/pdf`, { as: "blob" }),
  finalPackFileUrl: (id: string, kind: "json" | "html" | "pdf") => apiUrl(`${V1}/final-packs/${e(id)}/${kind}`),
};

export type Api = typeof api;
