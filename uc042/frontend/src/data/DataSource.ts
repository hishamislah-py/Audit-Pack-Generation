// The single seam between screens and data. Screens only call a DataSource; they never know whether it is the mock
// adapter (this design phase) or the FastAPI adapter. Method names and payloads mirror the backend endpoints, so swapping
// adapters does not change any screen.
import type {
  AiAuthorization, AiConfiguration, AiConfirmation, CaseDetail, CaseEntry, CaseEntryRequest, CaseSummary, DashboardSummary,
  InvestigationToolCalls, PackLineage, PeriodExceptionOverview, ReassessmentPlan, ReconcileRequest,
  BatchDetail, DocumentReviewRequest, Period, PeriodDetail, ProcessingRun, SourceDocument,
  DecisionRequest, DecisionResponse, Evidence, ExceptionDetail, ExceptionInvestigations, ExceptionView, FinalPackDetail,
  FinalPackDocument, FinalPackListItem, FinalPackVerification, Findings, Health, InvestigationDetail,
  InvestigationVerification, Job, PackDetail, PackListItem, PackReconciliation, PackSources, ReviewHistory, ReviewListItem,
  ReviewSession, Selection, SubmissionKind,
} from "../api/types";
import type { ActivityItem, ReconciliationPeriod } from "./models";

export type SourceKind = "mock" | "api";

/** How documents are added: INITIAL source documents (default), ADDITIONAL_EVIDENCE for the period, or a CORRECTION that
 * replaces one earlier document (which is kept unchanged). A reason is required for evidence and corrections. */
export interface Submission {
  kind: SubmissionKind;
  reason?: string;
  replacesDocumentId?: string;
}

export interface DataSource {
  readonly kind: SourceKind;
  /** What this source cannot do yet, so screens can say so instead of pretending. */
  readonly capabilities: { activity: boolean; upload: boolean; realInvestigations: boolean; realGeneration: boolean };

  health(): Promise<Health>;
  periods(): Promise<ReconciliationPeriod[]>;
  activity(): Promise<ActivityItem[]>;

  // Monthly document management (backend with database only; the mock source rejects these, it never simulates an upload).
  archivePeriod(periodId: string): Promise<PeriodDetail>;
  /** Create (or return the existing) period of a month; the period ID is derived from year and month. */
  openPeriod(year: number, month: number, title?: string): Promise<Period>;
  /** Change a period's report title (the period ID and pack references never change). */
  renamePeriod(periodId: string, title: string): Promise<Period>;
  uploadDocuments(periodId: string, files: File[], submission?: Submission): Promise<BatchDetail>;
  batch(batchId: string): Promise<BatchDetail>;
  reviewDocument(documentId: string, body: DocumentReviewRequest): Promise<SourceDocument>;
  confirmBatch(batchId: string): Promise<BatchDetail>;
  processBatch(batchId: string): Promise<ProcessingRun>;
  processingRun(runId: string): Promise<ProcessingRun>;
  documentContentUrl(documentId: string): string | null;
  /** Explicit, analyst-initiated reconciliation of a period (INITIAL, or REASSESSMENT after new evidence). */
  reconcile(periodId: string, body: ReconcileRequest): Promise<ProcessingRun>;
  reassessmentPlan(periodId: string): Promise<ReassessmentPlan>;
  periodLineage(periodId: string): Promise<PackLineage[]>;
  /** Every pack of the period with its exceptions and investigations, in one request. */
  periodExceptions(periodId: string): Promise<PeriodExceptionOverview[]>;
  /** Dashboard counts from the backend's records (the selected period's, and global totals labelled as global). */
  dashboard(periodId?: string): Promise<DashboardSummary>;
  /** Drop cached list data (periods, packs) after a change, so the next read shows it. */
  invalidate(): void;

  packs(): Promise<PackListItem[]>;
  pack(packId: string): Promise<PackDetail>;
  reconciliation(packId: string): Promise<PackReconciliation>;
  sources(packId: string): Promise<PackSources>;
  exceptions(packId: string): Promise<ExceptionView[]>;
  exception(packId: string, exceptionId: string): Promise<ExceptionDetail>;
  packInvestigations(packId: string): Promise<ExceptionInvestigations[]>;

  /** Starts a paid AI investigation: only with the analyst's explicit authorisation (recorded before the job runs). */
  startInvestigation(packId: string, exceptionId: string, authorization: AiConfirmation, retryOf?: string | null): Promise<Job>;
  /** The exception's supporting source records retrieved WITHOUT AI from the pack's verified sources. */
  sourceEvidence(packId: string, exceptionId: string): Promise<Evidence>;
  aiConfiguration(): Promise<AiConfiguration>;
  aiAuthorizations(filter?: { packId?: string; exceptionId?: string; reviewId?: string; jobId?: string }): Promise<AiAuthorization[]>;
  toolCalls(investigationId: string): Promise<InvestigationToolCalls>;
  cases(filter?: { periodId?: string; packId?: string }): Promise<CaseSummary[]>;
  openCase(packId: string, exceptionId: string): Promise<CaseDetail>;
  caseDetail(caseId: string): Promise<CaseDetail>;
  addCaseEntry(caseId: string, body: CaseEntryRequest): Promise<CaseEntry>;
  caseAi(caseId: string, authorization: AiConfirmation, retryOf?: string | null): Promise<Job>;
  job(jobId: string): Promise<Job>;
  investigation(investigationId: string): Promise<InvestigationDetail>;
  findings(investigationId: string): Promise<Findings>;
  evidence(investigationId: string): Promise<Evidence>;
  verifyInvestigation(investigationId: string): Promise<InvestigationVerification>;

  reviews(filter?: { packId?: string; status?: string }): Promise<ReviewListItem[]>;
  openReview(packId: string): Promise<ReviewSession>;
  review(reviewId: string): Promise<ReviewSession>;
  setSelections(reviewId: string, selections: Selection[], expectedRevision?: number): Promise<ReviewSession>;
  /** Generates the AI closing summary and preview: only with the analyst's explicit authorisation of the summary call. */
  requestPreview(reviewId: string, authorization: AiConfirmation): Promise<Job>;
  previewHtml(reviewId: string, snapshot: string): Promise<string>;
  previewDocument(reviewId: string, snapshot: string): Promise<FinalPackDocument>;
  previewPdf(reviewId: string, snapshot: string): Promise<Blob>;
  decide(reviewId: string, body: DecisionRequest): Promise<DecisionResponse>;
  reviewHistory(reviewId: string): Promise<ReviewHistory>;

  /** lineage: every version of the pack's reporting-period reassessment lineage (not only this deterministic pack's). */
  finalPacks(packId?: string, lineage?: boolean): Promise<FinalPackListItem[]>;
  finalPack(finalPackId: string): Promise<FinalPackDetail>;
  /** null: verification is not available from this source (the mock never claims a verification it did not run). */
  verifyFinalPack(finalPackId: string): Promise<FinalPackVerification | null>;
  finalPackDocument(finalPackId: string): Promise<FinalPackDocument>;
  finalPackHtml(finalPackId: string): Promise<string>;
  finalPackPdf(finalPackId: string): Promise<Blob>;
  finalPackFileUrl(finalPackId: string, kind: "json" | "html" | "pdf"): string | null;
}
