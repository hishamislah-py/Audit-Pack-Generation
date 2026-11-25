// Response and request shapes of the UC-042 FastAPI backend (/api/v1), mirroring uc042app/api/schemas.py and the stored
// documents it returns (findings, evidence, final-pack JSON). Only fields the UI reads are typed; the rest stay open.

export type Money = string; // decimal string exactly as reported by the engine (never recalculated in the browser)

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  [extra: string]: unknown;
}

export interface Health {
  status: "ok" | "degraded";
  storage: boolean;
  registry: boolean;
  provider_configured: boolean;
  analyst_id: string;
  single_process: boolean;
  version: string;
  database: boolean | null; // null: no database configured (no monthly document management)
  environment?: DataEnvironment | null;
}

/** The data environment the backend serves: one database and packs root. Environments are separate and not combined. */
export interface DataEnvironment {
  label: string;
  database: string | null;
  packs_root: string;
  storage_profiles?: string[]; // "primary" plus each storage profile whose artefact folders are served
}

/** An authorisation decision on a published investigation (AUTHORIZATION_DISCREPANCY: kept, but not in the approved set). */
export interface InvestigationAuthorization {
  status: "APPROVED" | "AUTHORIZATION_DISCREPANCY";
  basis: string;
  recorded_at: string;
  recorded_by: string;
}

/** HISTORICAL_MONTHLY: a historical monthly deterministic pack · DEMONSTRATION_SCENARIO: one synthetic test scenario of a
 * month (e.g. the nine September 2026 scenarios) · UPLOADED_DOCUMENTS: processed from uploaded documents. */
export type PackKind = "HISTORICAL_MONTHLY" | "DEMONSTRATION_SCENARIO" | "UPLOADED_DOCUMENTS";

// ---------------------------------------------------------------- packs
export interface PackSummary {
  pack_id: string;
  pack_content_sha256: string;
  period_id: string | null;
  reporting_period: { start: string; end: string; period_id: string };
  scenario_id: string | null;
  scenario_name?: string;
  pack_kind?: PackKind;
  engine_case_status: string;
  evidence_completeness: string;
  exceptions: { total: number; open: number; by_severity: Record<string, number> };
  control_summary: string;
  outcomes: Record<string, number>;
  missing_evidence_items: number;
  pack_review_status: string;
}

export interface PackListItem {
  pack_id: string;
  verified: boolean;
  summary: PackSummary | null;
  problem: string | null;
}

export interface Account {
  account_id: string;
  account_class: string;
  account_number_masked: string;
  currency: string;
  designation_name: string;
  evidence_id: string;
}

export interface PackDetail {
  summary: PackSummary;
  metadata: {
    pack_id: string;
    accounts: Account[];
    currency_scope: string[];
    entity: { entity_id: string; notice: string };
    reporting_period: { start: string; end: string; period_id: string };
    source_dataset: { dataset: string; scenario_id: string; scenario_name: string };
    synthetic_notice: string;
    [k: string]: unknown;
  };
  executive_summary: Record<string, unknown>;
  statements: Record<string, unknown>;
  verification: { verified: boolean; pack_content_sha256: string };
}

export interface InternalRow {
  date: string;
  currency: string;
  requirement: Money;
  resource: Money;
  difference: Money;
  difference_reported: Money;
  difference_outcome: string;
  requirement_outcome: string;
  evidence_status: string;
  [k: string]: unknown;
}

export interface ExternalRow {
  date: string;
  account_id: string;
  currency: string;
  bank_balance: Money;
  ledger_balance: Money;
  difference: Money;
  difference_reported: Money;
  difference_outcome: string;
  bank_outcome: string;
  ledger_outcome: string;
  evidence_status: string;
  [k: string]: unknown;
}

export interface PackReconciliation {
  pack_id: string;
  accounts: Account[];
  currency_scope: string[];
  reconciliation_days: string[];
  internal_by_currency_day: InternalRow[];
  external_by_account_day: ExternalRow[];
  opening_positions: Record<string, unknown>;
  client_balances_note: string;
}

export interface SourceFile {
  evidence_id: string;
  description: string;
  source_file?: string;
  sha256?: string;
  availability: string;
  requirement: string;
  record_count?: string;
  record_unit?: string;
  evidence_kind: string;
}

export interface PackSources {
  pack_id: string;
  files: SourceFile[];
  record_count: number;
  missing_evidence: { items: Array<Record<string, unknown>>; statement: string; optional_not_provided: unknown[] };
}

export interface ExceptionView {
  exception_id: string;
  category: string | null;
  cause_category: string | null;
  severity: string | null;
  status: string | null;
  review_status: string | null;
  evidence_status: string | null;
  account_id: string | null;
  currency: string | null;
  amount: Money | null;
  first_date: string | null;
  last_date: string | null;
  control_codes: unknown;
  investigation_group_id: string | null;
  affected_result_ids: string[];
  evidence_ids: string[];
  root_cause: unknown;
  flags: unknown;
  resolution_status: "UNRESOLVED";
}

export interface AffectedResult {
  result_id: string;
  check_id: string;
  control_code: string;
  control_name: string;
  outcome: string;
  computed: string;
  reported: string;
  evidence_status: string;
  note: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------- investigations and jobs
export type JobStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "INTERRUPTED";

export interface Job {
  job_id: string;
  operation: "INVESTIGATION" | "PREVIEW" | "PROCESSING";
  pack_id: string;
  exception_id: string | null;
  status: JobStatus;
  submitted_at: string;
  started_at: string;
  completed_at: string;
  error_summary: string;
  result: Record<string, unknown> | null;
  retry_of: string | null;
  authorization_id?: string | null; // the pre-execution AI authorisation of an INVESTIGATION or PREVIEW job
}

export interface RegistrySummary {
  seq: number;
  record_type: "NEW_PUBLICATION" | "LEGACY_BASELINE_IMPORT";
  recorded_at: string;
  findings_sha256: string;
  evidence_packet_sha256: string;
  findings_schema_version: string;
  prompt_version: string;
  note: string;
}

export interface PublishedInvestigation {
  investigation_id: string;
  investigation_mode: string | null;
  investigated_at: string | null;
  validation_status: string | null;
  simulated: boolean | null;
  provider: string | null;
  model: string | null;
  findings_schema_version: string | null;
  overall_evidence_assessment: string | null;
  eligible: boolean;
  library_eligible: boolean;
  ineligible_reasons: string[];
  registry: RegistrySummary | null;
  authorization?: InvestigationAuthorization | null;
}

export interface NotPublishedAttempt {
  record: string;
  investigation_status: string;
  validation_status: string;
  failure_reason: string;
}

export interface ExceptionInvestigations {
  pack_id: string;
  exception_id: string;
  published: PublishedInvestigation[];
  not_published: NotPublishedAttempt[];
  active_jobs: Job[];
}

export interface ExceptionDetail {
  exception: ExceptionView;
  affected_results: AffectedResult[];
  investigations: ExceptionInvestigations;
}

export interface InvestigationDetail {
  investigation_id: string;
  pack_id: string | null;
  exception_id: string | null;
  investigation_mode: string;
  investigated_at: string | null;
  investigation_status: string | null;
  validation_status: string | null;
  overall_evidence_assessment: string | null;
  investigation_summary: string | null;
  exception_resolution: string | null;
  model: Record<string, unknown>;
  tool_summary: Record<string, unknown> | null;
  classification_summary: Record<string, unknown> | null;
  findings_sha256: string;
  eligible: boolean;
  ineligible_reasons: string[];
  registry: RegistrySummary | null;
  authorization?: InvestigationAuthorization | null;
}

export interface ConfirmedFinding {
  finding_id: string;
  claim: string;
  explanation: string;
  evidence_ids: string[];
  supporting_records: string[];
  title?: string | null;
  audit_relevance?: string | null;
  establishes?: string | null;
  does_not_establish?: string | null;
}

export interface Hypothesis {
  hypothesis_id: string;
  possible_explanation: string;
  supporting_evidence: string[];
  contradictory_evidence: string[];
  limitations: string;
  status: "HYPOTHESIS";
  rationale?: string | null;
}

export interface ContradictoryItem {
  item_id: string;
  description: string;
  evidence_ids: string[];
  compared_evidence?: string[];
  same_measure_and_scope?: string;
}

export interface MissingEvidenceItem {
  item_id: string;
  description: string;
  expected_source: string;
  impact: string;
  related_ids: string[];
}

export interface NextStep {
  step_id: string;
  action: string;
  rationale: string;
  evidence_needed: string;
}

export interface Findings {
  investigation_id: string;
  pack_id: string;
  exception_id: string;
  investigation_summary: string;
  investigation_status: string;
  validation_status: string;
  exception_resolution: string;
  overall_evidence_assessment: string | null;
  confirmed_findings: ConfirmedFinding[];
  hypotheses: Hypothesis[];
  contradictory_evidence: ContradictoryItem[];
  missing_evidence: MissingEvidenceItem[];
  open_questions: string[];
  recommended_next_steps: NextStep[];
  evidence_references: string[];
  classification_summary: {
    unverified_candidate_relationships?: string[];
    deterministic_conflicts?: string[];
    [k: string]: unknown;
  };
  statement: string;
  [k: string]: unknown;
}

export interface SourceRecord {
  evidence_id: string;
  fields: Record<string, unknown>;
  file_id?: string;
  file_sha256?: string;
  record_type?: string;
  source_file?: string;
  source_line?: number;
  retrieved_via?: string;
  join_key?: string;
  [k: string]: unknown;
}

/** Evidence records: of one investigation (its ledger or packet), or (deterministic_retrieval) the exception's supporting
 * source records retrieved without AI from the pack's verified sources (pack_id, exception_id and route are then set). */
export interface Evidence {
  investigation_id?: string;
  pack_id?: string;
  exception_id?: string;
  route?: string;
  source: "evidence_ledger" | "evidence_packet" | "deterministic_retrieval";
  sha256: string;
  total_records: number;
  offset: number;
  limit: number;
  source_records: SourceRecord[];
  allowed_citation_ids: string[];
  searches: Array<{ search_id: string; description: string; result: string; found: unknown[]; query: unknown }>;
  relationships: Array<{ from: string; to: string; relationship: string; join_key?: string }>;
  control_results: Array<{ result_id: string; outcome: string; computed: string; reported: string; note: string; [k: string]: unknown }>;
  conflicts: Array<Record<string, unknown>>;
  missing_evidence: Array<Record<string, unknown>>;
  candidate_relationships: Array<Record<string, unknown>>;
}

export interface InvestigationVerification {
  investigation_id: string;
  artefact_verified: boolean;
  artefact_problems: string[];
  registry_verified: boolean;
  registry_problems: string[];
  eligible: boolean;
  ineligible_reasons: string[];
}

// ---------------------------------------------------------------- reviews
export type ReviewStatus = "OPEN" | "ON_HOLD" | "GENERATING" | "GENERATED" | "GENERATION_FAILED";
export type Inclusion = "INCLUDED" | "NOT_INVESTIGATED" | "EXCLUDED_BY_ANALYST";

export interface Selection {
  exception_id: string;
  inclusion: Inclusion;
  investigation_id?: string | null;
  reason?: string;
}

export interface ReadinessItem {
  code: string;
  detail: string;
}

export interface Readiness {
  ready: boolean;
  blockers: ReadinessItem[];
  warnings: ReadinessItem[];
  info: ReadinessItem[];
}

export interface ClosingSummaryMeta {
  status: "GENERATED" | "UNAVAILABLE";
  sha256: string;
  unavailable_reason: string;
  failure: { kind: string; detail: string } | null;
  model: string | null;
  provider: string | null;
  created_at: string;
}

export interface PreviewMeta {
  preview_id: string;
  selections_version: number;
  snapshot_sha256: string;
  inputs_fingerprint: string;
  preview_final_pack_id: string;
  preview_content_sha256: string;
  closing_summary: ClosingSummaryMeta;
  created_at: string;
}

export interface ReviewSession {
  review_id: string;
  pack_id: string;
  pack_content_sha256: string;
  status: ReviewStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  selections: Selection[];
  selections_version: number;
  current_preview: PreviewMeta | null;
  preview_job: Job | null;
  final_pack_id: string | null;
  last_decision_id: string | null;
  readiness: Readiness;
  acknowledgement_text: string;
}

export interface ReviewListItem {
  review_id: string;
  pack_id: string;
  status: ReviewStatus;
  created_at: string;
  updated_at: string;
  has_preview: boolean;
  final_pack_id: string | null;
  last_decision: { review_decision_id: string; decision: "HOLD" | "GENERATE"; decided_at: string; comment: string } | null;
}

export interface Decision {
  review_decision_id: string;
  review_id: string;
  pack_id: string;
  decision: "HOLD" | "GENERATE";
  decided_at: string;
  reviewer: { user_id: string; display_name: string };
  comment: string;
  acknowledgement_accepted: boolean;
  snapshot_sha256: string;
  preview_id: string;
  closing_summary_sha256: string;
}

export interface DecisionRequest {
  decision: "HOLD" | "GENERATE";
  snapshot_sha256?: string | null;
  comment?: string;
  acknowledgement_accepted?: boolean;
  acknowledged_summary_unavailable?: boolean;
}

export interface FinalPackRecord {
  review_decision_id: string;
  review_id: string;
  pack_id: string;
  status: "GENERATING" | "GENERATED" | "GENERATION_FAILED";
  version: number;
  supersedes_final_pack_id: string | null;
  created_at: string;
  final_pack_id: string | null;
  final_content_sha256: string | null;
  error_summary: string;
  [k: string]: unknown;
}

export interface DecisionResponse {
  decision: Decision;
  session_status: ReviewStatus;
  final_pack: FinalPackRecord | null;
}

export interface ReviewHistory {
  review_id: string;
  decisions: Decision[];
  final_pack_records: FinalPackRecord[];
}

// ---------------------------------------------------------------- final packs (and previews: same canonical document)
export interface FinalPackListItem {
  final_pack_id: string;
  pack_id: string;
  version: number;
  supersedes_final_pack_id: string | null;
  generated_at: string;
  review_decision_id: string;
  final_content_sha256: string;
}

export interface FinalPackDetail {
  final_pack_id: string;
  status: string;
  version: number;
  supersedes_final_pack_id: string | null;
  generated_at: string;
  source_pack: { pack_id: string; pack_content_sha256: string; [k: string]: unknown };
  final_content_sha256: string;
  human_review: {
    review_decision_id: string;
    decision: string;
    reviewer: { user_id: string; display_name: string };
    decided_at: string;
    comment: string;
    acknowledgement_accepted: boolean;
  };
  files: Record<string, { name: string; sha256: string; size_bytes: number; media_type: string }>;
  record: FinalPackRecord | null;
}

export interface FinalPackVerification {
  final_pack_id: string;
  verified: boolean;
  problems: string[];
}

export interface SummaryItem {
  text: string;
  source_refs: string[];
}

export interface ClosingSummaryOutput {
  overall_position: string;
  summary_text: string;
  key_observations: SummaryItem[];
  unresolved_items: Array<{ exception_id: string; text: string }>;
  unverified_hypotheses: SummaryItem[];
  evidence_gaps: SummaryItem[];
  suggested_next_steps: SummaryItem[];
  limitations: string[];
}

export interface FinalPackDocument {
  final_pack_schema_version: string;
  metadata: {
    final_pack_id: string;
    version: number;
    status: string;
    generated_at: string;
    source_pack: { pack_id: string; pack_content_sha256: string };
    reporting_period: { start: string; end: string; period_id: string };
    [k: string]: unknown;
  };
  executive_summary: Record<string, unknown>;
  exception_register: Array<{
    exception: ExceptionView & Record<string, unknown>;
    resolution_status: "UNRESOLVED";
    investigation: {
      inclusion: Inclusion;
      investigation_id: string | null;
      reason: string;
      investigation_mode: string | null;
      overall_evidence_assessment: string | null;
    };
  }>;
  ai_investigations: Array<{
    investigation_id: string;
    exception_id: string;
    investigation_mode: string;
    model: string;
    investigated_at: string;
    findings_sha256: string;
    [k: string]: unknown;
  }>;
  human_review: Record<string, unknown>;
  closing_summary: {
    status: "GENERATED" | "UNAVAILABLE";
    output: ClosingSummaryOutput | null;
    unavailable_reason: string;
    model_metadata: Record<string, unknown>;
    created_at: string;
  };
  statements: Record<string, string>;
  final_content_sha256: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------- monthly document management (Phase 4)
export type ArchiveState = "RESULTS_AND_FINAL_PACK" | "RESULTS_NO_FINAL_PACK" | "DOCUMENTS_NO_RESULTS" | "AWAITING_UPLOAD";

export interface CreatePeriodRequest {
  year: number;
  month: number;
  title?: string | null;
}

export interface UpdatePeriodRequest {
  title: string;
}

export type ReportingStatus = "NO_DATA" | "DOCUMENTS_UPLOADED" | "VALIDATION_REQUIRED" | "DETERMINISTIC_PACK_AVAILABLE"
  | "INVESTIGATION_AVAILABLE" | "FINAL_PACK_PUBLISHED" | "ADDITIONAL_EVIDENCE_RECEIVED";

export type SubmissionKind = "INITIAL" | "ADDITIONAL_EVIDENCE" | "CORRECTION";

export interface PeriodPackRef {
  pack_id: string;
  origin: "POC_SCENARIO" | "UPLOAD_PROCESSING";
  scenario_id: string;
  processing_run_id: string | null;
  pack_content_sha256: string;
  registered_at: string;
  verified: boolean;
  engine_case_status: string | null;
  evidence_completeness: string | null;
  exceptions_total: number;
  exceptions_open: number;
  final_packs: number;
  final_pack_ids?: string[];
  pack_kind?: PackKind | null;
  scenario_name?: string;
  published_investigations?: number; // registered and not an authorisation discrepancy
  eligible_investigations?: number;
  excluded_investigations?: number; // published artefacts that are unregistered or an authorisation discrepancy
  predecessor_pack_id?: string | null; // a pack produced by reassessing an earlier pack of the period
  lineage_root_pack_id?: string | null;
  investigation_counts?: Record<string, number> | null;
}

export interface Period {
  period_id: string;
  use_case: string;
  year: number;
  month: number;
  status: string; // EMPTY | DOCUMENTS_UPLOADED | PROCESSING | PROCESSED | PROCESSING_FAILED
  created_at: string;
  last_processed_at: string | null;
  title: string;
  title_source?: "STORED" | "DERIVED"; // DERIVED: no title was ever stored; the month's default title is shown
  storage_profile?: string;
  reporting_status: ReportingStatus;
  published_investigations: number;
  eligible_investigations: number;
  excluded_investigations?: number;
  reassessment_runs?: number;
  latest_reassessment_status?: string | null;
  latest_final_pack_at: string | null;
  documents_after_publication: number;
  pending_reassessment: boolean;
  archive_state: ArchiveState;
  batch_count: number;
  document_count: number;
  latest_batch_status: string | null;
  latest_validation_status: string | null;
  latest_run_status: string | null;
  pack_count: number;
  scenario_packs: boolean;
  exceptions_total: number;
  exceptions_open: number;
  final_pack_count: number;
  processing_supported: boolean;
  processing_limitation?: string | null;
  investigation_counts?: Record<string, number> | null;
  packs: PeriodPackRef[];
}

export interface UploadBatch {
  batch_id: string;
  period_id: string;
  origin: "UPLOAD" | "POC_DATASET_IMPORT";
  created_at: string;
  created_by: string;
  file_count: number;
  validation_status: string; // VALID | WARNINGS | INCOMPLETE | INVALID
  status: string; // VALIDATED | CONFIRMED | PROCESSING | PROCESSED | PROCESSING_FAILED | ARCHIVED_SCENARIO
  summary: BatchSummary;
  error: string;
  confirmed_at: string | null;
  confirmed_by: string | null;
}

/** Shape of UploadBatch.summary for UPLOAD batches (POC_DATASET_IMPORT batches carry pack_id / scenario_id instead). */
export interface BatchSummary {
  documents?: { VALID: number; WARNING: number; ERROR: number };
  identified?: string[];
  missing_in_batch?: string[];
  missing_required?: string[];
  missing_optional?: string[];
  decisions_pending?: string[];
  processing_set?: Record<string, string>;
  pack_id?: string;
  scenario_id?: string;
  [extra: string]: unknown;
}

export interface CheckMessage {
  code: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
  [extra: string]: unknown;
}

export interface DateColumn {
  role: string;
  type?: "date" | "timestamp";
  governing?: boolean;
  from?: string | null;
  to?: string | null;
  invalid?: number;
  missing?: number;
  outside_month?: number;
  value?: string; // PDF key-detail dates
}

export interface DocumentChecks {
  messages: CheckMessage[];
  dates?: Record<string, DateColumn>;
  period?: { basis: string; in_month: number; outside_month: number; boundary_records: number };
  key_details?: Record<string, string>;
  identified_by?: string;
  decision_required?: boolean;
  [extra: string]: unknown;
}

export interface SourceDocument {
  document_id: string;
  batch_id: string;
  original_filename: string;
  evidence_id: string | null;
  category: string | null;
  file_format: string;
  size_bytes: number;
  sha256: string;
  reporting_period: string;
  date_from: string | null;
  date_to: string | null;
  record_count: number | null;
  validation_status: "VALID" | "WARNING" | "ERROR";
  checks: DocumentChecks;
  storage_kind: "UPLOADED_ORIGINAL" | "POC_DATASET";
  created_at: string;
  review_decision: "INCLUDE" | "EXCLUDE" | null;
  review_comment: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  submission_kind?: SubmissionKind;
  submission_reason?: string;
  replaces_document_id?: string | null;
}

export interface ProcessingRun {
  run_id: string;
  period_id: string;
  batch_id: string;
  job_id: string | null;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "BLOCKED" | "INTERRUPTED";
  started_at: string | null;
  completed_at: string | null;
  error: string;
  result: Record<string, unknown>;
  created_at: string;
  created_by: string;
}

export interface BatchDetail {
  batch: UploadBatch;
  documents: SourceDocument[];
  runs: ProcessingRun[];
}

export interface PeriodDetail {
  period: Period;
  batches: UploadBatch[];
  documents: SourceDocument[];
  runs: ProcessingRun[];
  current_set: Record<string, string>;
  missing_required: string[];
  processing_supported: boolean;
  processing_limitation: string | null;
  evidence_types: Record<string, string>;
}

export interface DocumentReviewRequest {
  decision: "INCLUDE" | "EXCLUDE";
  comment: string;
}

export interface ActivityEvent {
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
}

// ---------------------------------------------------------------- phase 8: AI authorisation, reassessment, lineage, cases, dashboard
/** The analyst's explicit authorisation of one paid AI operation (provider/model as the dialog showed them). */
export interface AiConfirmation {
  confirmed: boolean;
  provider?: string | null;
  model?: string | null;
}

export interface AiConfiguration {
  provider: string;
  model: string;
  reasoning_effort: string | null;
  provider_configured: boolean;
  configuration_problem: string | null;
  investigation_mode: string;
  tool_limits: Record<string, number>;
  charges_notice: string;
  statements: Record<"INVESTIGATION" | "CLOSING_SUMMARY", string>;
}

export interface AiAuthorization {
  id: number;
  authorization_id: string;
  operation: "INVESTIGATION" | "CLOSING_SUMMARY";
  result: string;
  period_id: string;
  pack_id: string;
  exception_id: string | null;
  review_id: string | null;
  case_id: string | null;
  job_id: string | null;
  provider: string;
  model: string;
  authorized_by: string;
  authorized_at: string;
  details: Record<string, unknown>;
}

export interface ReconcileRequest {
  purpose: "INITIAL" | "REASSESSMENT";
  reason: string;
}

export interface ReassessmentPlan {
  period_id: string;
  latest_final_pack_id: string | null;
  latest_final_pack_at: string | null;
  target_pack_id: string | null;
  pending_reassessment: boolean;
  uploaded_set: Record<string, string>;
  baseline: { pack_id: string; dataset: string; storage_profile: string; files: Record<string, { source_file: string; sha256: string }> } | null;
  baseline_problems: string[];
  effective_set: Record<string, { source: "UPLOADED" | "BASELINE"; document_id?: string; pack_id?: string; source_file?: string; sha256?: string }>;
  missing_required: string[];
  new_documents: Array<{ document_id: string; original_filename: string; evidence_id: string | null; category: string | null;
    submission_kind: SubmissionKind; submission_reason: string; created_at: string; validation_status: string; batch_id: string }>;
  can_reassess: boolean;
  blockers: string[];
}

export interface PackLineage {
  pack_id: string;
  period_id: string;
  predecessor_pack_id: string;
  lineage_root_pack_id: string;
  purpose: string;
  processing_run_id: string;
  reason: string;
  change_summary: {
    inputs_changed?: string[]; inputs_added?: string[]; inputs_removed?: string[];
    engine_case_status?: [string | null, string | null]; evidence_completeness?: [string | null, string | null];
    exceptions?: { before: number; after: number; added: string[]; removed: string[]; unchanged: string[] };
    baseline_files?: string[]; [k: string]: unknown;
  };
  recorded_at: string;
  recorded_by: string;
}

export interface InvestigationCounts {
  published: number;
  eligible: number;
  running: number;
  rejected_attempts: number;
  unregistered: number;
  authorization_discrepancy: number;
  ineligible_other: number;
}

export interface DashboardSummary {
  period_id: string | null;
  packs: number;
  exceptions: number;
  exceptions_open: number;
  exceptions_with_eligible_investigation: number;
  investigations: InvestigationCounts;
  final_packs_period: number;
  latest_final_pack_period_at: string | null;
  final_packs_global: number;
  latest_final_pack_global_at: string | null;
  pending_reviews_period: number;
  pending_reviews_global: number;
  per_pack: Array<Record<string, unknown>>;
}

export type CaseEntryKind = "NOTE" | "EVIDENCE" | "EVIDENCE_GAP" | "OBSERVATION" | "HYPOTHESIS" | "DECISION" | "AI_REQUEST";
export type CaseResolution = "UNRESOLVED" | "EXPLAINED_BY_ANALYST" | "ESCALATED";

export interface CaseEntry {
  entry_id: string;
  case_id: string;
  seq: number;
  kind: CaseEntryKind;
  text: string;
  evidence_refs: string[];
  details: Record<string, unknown>;
  created_at: string;
  created_by: string;
}

export interface CaseSummary {
  case_id: string;
  period_id: string;
  pack_id: string;
  exception_id: string;
  status: "OPEN" | "CLOSED";
  human_resolution: CaseResolution;
  revision: number;
  created_at: string;
  created_by: string;
  updated_at: string;
}

export interface CaseDetail extends CaseSummary {
  exception: ExceptionView;
  entries: CaseEntry[];
  supporting_evidence: CaseEntry[];
  evidence_gaps: CaseEntry[];
  notes: CaseEntry[];
  confirmed_observations: CaseEntry[];
  hypotheses: CaseEntry[];
  human_decisions: CaseEntry[];
  ai_requests: CaseEntry[];
  ai_jobs: Job[];
  ai_investigations: { published: PublishedInvestigation[]; not_published: NotPublishedAttempt[] };
  missing_evidence_in_pack: Array<Record<string, unknown>>;
}

export interface CaseEntryRequest {
  kind: Exclude<CaseEntryKind, "AI_REQUEST">;
  text: string;
  evidence_refs: string[];
  expected_revision: number;
  resolution?: CaseResolution | null;
  close?: boolean | null;
}

/** The tool calls an investigation recorded (metadata only; no record contents). */
export interface InvestigationToolCalls {
  investigation_id: string;
  tool_registry_version: string | null;
  summary: Record<string, unknown> | null;
  tool_calls: Array<{ call_id: string; tool: string; arguments: Record<string, unknown>; status: string; round: number;
    evidence_ids: string[]; new_evidence_ids: string[]; search_ids: string[]; records_returned: number; deduplicated: boolean;
    truncated: boolean; error: string; requested_at: string }>;
}

/** One pack of a period with its exceptions (as recorded) and their investigations: the month's exception overview. */
export interface PeriodExceptionOverview {
  pack_id: string;
  exceptions: ExceptionView[];
  investigations: ExceptionInvestigations[];
}
