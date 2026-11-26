"""Request and response models of the REST API (/api/v1). Requests forbid unknown fields. Responses are the client
contract: they never contain file-system paths or provider keys.
Stored artefacts that are already JSON documents (findings, evidence, final-pack metadata) are returned as objects."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Resp(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- common
class Problem(_Resp):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str


class DataEnvironment(_Resp):
    """The data environment this backend serves (no credentials): one database, and the storage profiles whose files it
    serves (the primary roots plus e.g. historical-demo). Every period of the database is shown."""
    label: str
    database: Optional[str] = None
    packs_root: str
    storage_profiles: list[str] = []


class Health(_Resp):
    status: Literal["ok", "degraded"]
    storage: bool
    registry: bool
    provider_configured: bool
    analyst_id: str
    single_process: bool = True
    version: str
    database: Optional[bool] = None  # None: no database configured (file-backed state, no monthly document management)
    environment: Optional[DataEnvironment] = None



# ---------------------------------------------------------------- packs
class PackSummary(_Resp):
    pack_id: str
    pack_content_sha256: str
    period_id: Optional[str]
    reporting_period: dict
    scenario_id: Optional[str]
    scenario_name: str = ""
    pack_kind: Literal["HISTORICAL_MONTHLY", "DEMONSTRATION_SCENARIO", "UPLOADED_DOCUMENTS"] = "UPLOADED_DOCUMENTS"
    engine_case_status: str
    evidence_completeness: str
    exceptions: dict
    control_summary: str
    outcomes: dict
    missing_evidence_items: int
    pack_review_status: str


class PackListItem(_Resp):
    pack_id: str
    verified: bool
    summary: Optional[PackSummary] = None
    problem: Optional[str] = None


class PackDetail(_Resp):
    summary: PackSummary
    metadata: dict
    executive_summary: dict
    statements: dict
    candidate_relationships: list[dict] = Field(default_factory=list, description="Unverified candidate relationships (DATE_AND_AMOUNT_COINCIDENCE); never evidence")
    verification: dict


class PackReconciliation(_Resp):
    pack_id: str
    accounts: list[dict]
    currency_scope: list[str]
    reconciliation_days: list[str]
    internal_by_currency_day: list[dict]
    external_by_account_day: list[dict]
    opening_positions: dict
    client_balances_note: str


class ControlCheck(_Resp):
    check_id: str
    control_code: str
    control_name: str
    check_outcome: Optional[str] = None
    result_counts: dict[str, int]
    exception_ids: list[str]


class PackControls(_Resp):
    pack_id: str
    checks: list[ControlCheck]


class PackSources(_Resp):
    pack_id: str
    files: list[dict]
    record_count: int
    missing_evidence: dict


class ExceptionView(_Resp):
    exception_id: str
    category: Optional[str] = None
    cause_category: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    review_status: Optional[str] = None
    evidence_status: Optional[str] = None
    account_id: Optional[str] = None
    currency: Optional[str] = None
    amount: Any = None
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    control_codes: Any = None
    investigation_group_id: Optional[str] = None
    affected_result_ids: list = []
    evidence_ids: list = []
    root_cause: Any = None
    flags: Any = None
    resolution_status: Literal["UNRESOLVED"] = "UNRESOLVED"


class ExceptionDetail(_Resp):
    exception: ExceptionView
    affected_results: list
    investigations: dict


# ---------------------------------------------------------------- investigations and jobs
class AiConfirmation(_Req):
    """The analyst's explicit authorisation of one paid AI operation. provider/model, when given, are what the confirmation
    dialog showed; they must still be the configured ones (409 AI_CONFIGURATION_CHANGED otherwise)."""
    confirmed: bool = False
    provider: Optional[str] = Field(None, max_length=32)
    model: Optional[str] = Field(None, max_length=64)
    fallback_provider: Optional[str] = Field(None, max_length=32, description="Legacy: only 'none' is accepted (there is no automatic fallback provider)")
    fallback_model: Optional[str] = Field(None, max_length=64)


class AutoInvestigationRequest(_Req):
    authorization: Optional[AiConfirmation] = Field(None, description="Required: the analyst's explicit AUTO_INVESTIGATION authorisation")
    retry: bool = Field(False, description="Re-queue only the exceptions whose latest attempt failed (after a provider issue is resolved)")


class SubmissionFinalPack(_Resp):
    final_pack_id: str
    generated_at: str
    final_content_sha256: str


class SubmissionEntry(_Resp):
    submission_id: str
    run_id: str
    submitted_at: str
    submitted_by: str
    status: Optional[str] = None
    pack_id: Optional[str] = None
    outcome: Optional[str] = None
    completed_at: Optional[str] = None
    error: str = ""
    auto_investigation: Optional[str] = None
    final_packs: list[SubmissionFinalPack] = []


class SubmissionPackage(_Resp):
    """One ZIP package of a period with its submissions (GET /periods/{period_id}/submissions)."""
    batch_id: str
    created_at: str
    status: str
    zip_name: Optional[str] = None
    zip_sha256: Optional[str] = None
    gate: Optional[dict] = None
    file_count: int
    submissions: list[SubmissionEntry]


# ---------------------------------------------------------------- packages and submission status (Phase B, read-only)
SubmissionStage = Literal["PACKAGE_REJECTED", "PACKAGE_INCOMPLETE", "READY_TO_SUBMIT", "AUDIT_RUNNING", "AUDIT_FAILED",
                          "AI_INVESTIGATING", "FINDINGS_TO_REVIEW", "READY_FOR_FINAL_REVIEW", "FINAL_REVIEW_IN_PROGRESS",
                          "FINAL_PACK_GENERATED"]


class PackageGate(_Resp):
    passed: bool
    missing_required: list[str] = []
    present_required: int = 0  # how many required document types are present
    required_total: int = 0
    reason: Optional[str] = None  # why a rejected package was refused (unsafe / unexpected / unreadable archive)


class SubmissionInvestigationCounts(_Resp):
    """Per exception of the submission's pack (total = exception count): running (latest own job queued / running),
    completed (an investigation produced for this submission), failed (latest own job failed / interrupted), not_started."""
    total: int
    completed: int
    failed: int
    running: int
    not_started: int = 0


class SubmissionDecisionCounts(_Resp):
    """The submission's own analyst decisions on its latest completed investigation per exception."""
    accepted: int
    rejected: int
    pending: int


class SubmissionReviewRef(_Resp):
    review_id: str
    status: str


class SubmissionFinalPackRef(_Resp):
    final_pack_id: str
    generated_at: str
    version: Optional[int] = None


class SubmissionStatus(_Resp):
    submission_id: str
    run_id: str
    run_status: Optional[str] = None
    run_error: str = ""
    submitted_at: Optional[str] = None
    submitted_by: Optional[str] = None
    completed_at: Optional[str] = None
    pack_id: Optional[str] = None
    outcome: Optional[str] = None
    exception_count: Optional[int] = None
    auto_investigation_status: Optional[str] = None
    investigations: SubmissionInvestigationCounts
    decisions: SubmissionDecisionCounts
    review: Optional[SubmissionReviewRef] = None  # the active review session of (pack, submission), else the latest
    final_pack: Optional[SubmissionFinalPackRef] = None  # the submission's latest final pack
    stage: SubmissionStage


class SubmissionDetail(SubmissionStatus):
    """GET /submissions/{submission_id}: the submission's status plus its package."""
    batch_id: str
    display_name: str
    display_name_source: Literal["STORED", "DERIVED"]
    period_id: str
    zip_name: Optional[str] = None


class PackageItem(_Resp):
    """One ZIP submission package (GET /packages, PATCH /packages/{batch_id})."""
    batch_id: str
    display_name: str
    display_name_source: Literal["STORED", "DERIVED"]  # DERIVED: from the ZIP file name (no name was set)
    zip_name: Optional[str] = None
    zip_sha256: Optional[str] = None
    period_id: str
    created_at: str
    status: str
    gate: PackageGate
    document_count: int
    submissions_count: int
    submission_ids: list[str] = []  # newest first
    latest_submission: Optional[SubmissionStatus] = None
    stage: SubmissionStage  # the latest submission's stage, or the package's own (rejected / incomplete / ready to submit)


class UpdatePackageRequest(_Req):
    display_name: str = Field(max_length=1000, description="The package's display name (trimmed; at most 200 characters; "
                                                           "empty clears it, and the name derived from the ZIP file name is shown)")


class SubmissionRetryRequest(_Req):
    authorization: Optional[AiConfirmation] = Field(None, description="Required: the analyst's explicit AUTO_INVESTIGATION authorisation")
    exception_ids: Optional[list[str]] = Field(None, max_length=500, description="Limit the retry to these exceptions (default: every "
                                               "exception of the submission without a completed investigation)")


class ProcessRequest(_Req):
    ai_authorization: Optional[AiConfirmation] = Field(
        None, description="What the processing confirmation disclosed (provider, model). AI investigation of every "
                          "exception of the resulting pack is mandatory; the confirmation is its run-level authorisation, and a "
                          "configuration that changed since it was shown is refused")


class StartInvestigationRequest(_Req):
    mode: Literal["tools"] = "tools"
    retry_of: Optional[str] = Field(None, description="Job ID of an earlier failed or interrupted attempt being retried")
    authorization: Optional[AiConfirmation] = Field(None, description="Required: the analyst's explicit authorisation")


class Job(_Resp):
    job_id: str
    operation: Literal["INVESTIGATION", "PREVIEW", "PROCESSING"]
    pack_id: str
    exception_id: Optional[str] = None
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED"]
    submitted_at: str
    started_at: str = ""
    completed_at: str = ""
    error_summary: str = ""
    result: Optional[dict] = None
    retry_of: Optional[str] = None
    authorization_id: Optional[str] = None  # the pre-execution AI authorisation of an INVESTIGATION or PREVIEW job


class PublishedInvestigation(_Resp):
    investigation_id: str
    investigation_mode: Optional[str] = None
    investigated_at: Optional[str] = None
    validation_status: Optional[str] = None
    simulated: Optional[bool] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    findings_schema_version: Optional[str] = None
    overall_evidence_assessment: Optional[str] = None
    eligible: bool
    library_eligible: bool
    ineligible_reasons: list[str]
    registry: Optional[dict] = None
    authorization: Optional[dict] = None
    analyst_review: Optional["AnalystReview"] = None  # the analyst's active ACCEPT / REJECT decision; None = pending review
    submission_id: Optional[str] = None  # the ZIP submission whose audit run produced it (decided only in that submission's review)


class ExceptionInvestigations(_Resp):
    pack_id: str
    exception_id: str
    published: list[PublishedInvestigation]
    not_published: list[dict]
    active_jobs: list[Job]
    submission_id: Optional[str] = None  # set only on a submission-scoped request (?submission_id=)


class InvestigationDetail(_Resp):
    investigation_id: str
    pack_id: Optional[str]
    exception_id: Optional[str]
    investigation_mode: str
    investigated_at: Optional[str]
    investigation_status: Optional[str]
    validation_status: Optional[str]
    overall_evidence_assessment: Optional[str]
    investigation_summary: Optional[str]
    exception_resolution: Optional[str]
    model: dict
    tool_summary: Optional[dict]
    classification_summary: Optional[dict]
    findings_sha256: str
    eligible: bool
    ineligible_reasons: list[str]
    registry: Optional[dict]
    authorization: Optional[dict] = None
    analyst_review: Optional["AnalystReview"] = None
    submission_id: Optional[str] = None  # the ZIP submission that produced it (findings.execution), None for legacy


# ---------------------------------------------------------------- analyst review of AI investigations (Exception Workspace)
class AnalystReviewRequest(_Req):
    """ACCEPT (optional comment) or REJECT (mandatory reason for rejection, kept exactly as written). expected_revision is
    the review revision the analyst decided on (0 for the first decision); a decision on an out-of-date view is refused."""
    decision: Literal["ACCEPT", "REJECT"]
    comment: str = Field("", max_length=8000)
    rejection_reason: str = Field("", max_length=8000)
    expected_revision: int = Field(ge=0)
    submission_id: Optional[str] = Field(None, max_length=40, description="The ZIP submission whose review this decision belongs "
                                         "to (counts only there); omitted: the legacy period-level decision")


class AnalystReviewer(_Resp):
    user_id: str
    display_name: str


class AnalystReview(_Resp):
    analyst_review_id: str
    period_id: str
    pack_id: str
    exception_id: str
    investigation_id: str
    findings_sha256: str
    findings_schema_version: str
    decision: Literal["ACCEPT", "REJECT"]
    comment: str
    rejection_reason: str
    reviewer: AnalystReviewer
    decided_at: str
    revision: int
    supersedes_review_id: Optional[str] = None
    active: bool
    pdf_unsupported_characters: list[dict] = []  # characters the audit PDF fonts cannot draw (final pack blocked until resolved)
    submission_id: Optional[str] = None  # the ZIP submission whose review this decision belongs to (None: legacy decision)


class ReviewHistoryEvent(_Resp):
    at: str
    kind: str
    label: str
    actor: Optional[str] = None
    pack_id: str
    exception_id: str
    investigation_id: Optional[str] = None
    details: dict


class ExceptionReviewHistory(_Resp):
    pack_id: str
    exception_id: str
    events: list[ReviewHistoryEvent]
    active_decisions: dict  # period-level (legacy) scope: {investigation_id: active decision}
    active_submission_decisions: dict = {}  # {submission_id: {investigation_id: active decision}}
    pending_investigations: list[str]
    exception_status: Literal["UNRESOLVED"]
    note: str


class InvestigationVerification(_Resp):
    investigation_id: str
    artefact_verified: bool
    artefact_problems: list[str]
    registry_verified: bool
    registry_problems: list[str]
    eligible: bool
    ineligible_reasons: list[str]


# ---------------------------------------------------------------- reviews
class SelectionIn(_Req):
    exception_id: str
    inclusion: Literal["INCLUDED", "NOT_INVESTIGATED", "EXCLUDED_BY_ANALYST"]
    investigation_id: Optional[str] = None
    reason: str = Field("", max_length=2000)


class SelectionsRequest(_Req):
    selections: list[SelectionIn] = Field(min_length=0, max_length=500)
    expected_revision: Optional[int] = Field(None, ge=1, description="Reject the change if the session revision differs")


class ReviewListItem(_Resp):
    review_id: str
    pack_id: str
    status: Literal["OPEN", "ON_HOLD", "GENERATING", "GENERATED", "GENERATION_FAILED"]
    created_at: str
    updated_at: str
    has_preview: bool
    final_pack_id: Optional[str] = None
    last_decision: Optional[dict] = None
    submission_id: Optional[str] = None
    run_id: Optional[str] = None
    batch_id: Optional[str] = None


class Readiness(_Resp):
    ready: bool
    blockers: list[dict]
    warnings: list[dict]
    info: list[dict]
    checklist: Optional[dict] = Field(None, description="Per-exception AI status, final-review disposition and next action, "
                                                        "with counts, the preview state and the closing-summary status")


class PreviewMeta(_Resp):
    preview_id: str
    selections_version: int
    snapshot_sha256: str
    inputs_fingerprint: str
    preview_final_pack_id: str
    preview_content_sha256: str
    closing_summary: dict
    created_at: str


class ReviewSession(_Resp):
    review_id: str
    pack_id: str
    pack_content_sha256: str
    status: Literal["OPEN", "ON_HOLD", "GENERATING", "GENERATED", "GENERATION_FAILED"]
    revision: int
    created_at: str
    updated_at: str
    selections: list[dict]
    selections_version: int
    current_preview: Optional[PreviewMeta] = None
    preview_job: Optional[Job] = None
    final_pack_id: Optional[str] = None
    last_decision_id: Optional[str] = None
    readiness: Readiness
    acknowledgement_text: str
    submission_id: Optional[str] = None  # the ZIP submission under review (its own investigations and decisions only)
    run_id: Optional[str] = None
    batch_id: Optional[str] = None


class OpenReviewRequest(_Req):
    submission_id: Optional[str] = Field(None, max_length=40, description="Review one ZIP submission's audit result: only the "
                                         "investigations and analyst decisions of that submission's run are used")


class PreviewRequest(_Req):
    authorization: Optional[AiConfirmation] = Field(None, description="Required: the analyst's explicit authorisation of the "
                                                                      "closing-summary call")


class DecisionRequest(_Req):
    decision: Literal["GENERATE", "HOLD"]
    snapshot_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")
    comment: str = Field("", max_length=4000)
    acknowledgement_accepted: bool = False
    acknowledged_summary_unavailable: bool = False


class DecisionResponse(_Resp):
    decision: dict
    session_status: str
    final_pack: Optional[dict] = None


class ReviewHistory(_Resp):
    review_id: str
    decisions: list[dict]
    final_pack_records: list[dict]


# ---------------------------------------------------------------- final packs
class FinalPackListItem(_Resp):
    final_pack_id: str
    pack_id: str
    version: int
    supersedes_final_pack_id: Optional[str]
    generated_at: str
    review_decision_id: str
    final_content_sha256: str
    submission_id: Optional[str] = None  # traceability: ZIP submission -> upload batch -> audit run -> this final pack
    run_id: Optional[str] = None
    batch_id: Optional[str] = None


class FinalPackDetail(_Resp):
    final_pack_id: str
    status: str
    version: int
    supersedes_final_pack_id: Optional[str]
    generated_at: str
    source_pack: dict
    final_content_sha256: str
    human_review: dict
    files: dict
    record: Optional[dict]


class FinalPackVerification(_Resp):
    final_pack_id: str
    verified: bool
    problems: list[str]


# ---------------------------------------------------------------- monthly document management (Phase 4)
class CreatePeriodRequest(_Req):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    title: Optional[str] = Field(None, max_length=200, description="Report title; the period ID is derived from year and month")


class UpdatePeriodRequest(_Req):
    title: str = Field(min_length=3, max_length=200)


class PeriodPackRef(_Resp):
    pack_id: str
    origin: Literal["POC_SCENARIO", "UPLOAD_PROCESSING"]
    scenario_id: str = ""
    processing_run_id: Optional[str] = None
    pack_content_sha256: str
    registered_at: str
    verified: bool = True
    engine_case_status: Optional[str] = None
    evidence_completeness: Optional[str] = None
    exceptions_total: int = 0
    exceptions_open: int = 0
    final_packs: int = 0
    final_pack_ids: list[str] = []
    pack_kind: Optional[Literal["HISTORICAL_MONTHLY", "DEMONSTRATION_SCENARIO", "UPLOADED_DOCUMENTS"]] = None
    scenario_name: str = ""
    published_investigations: int = 0
    eligible_investigations: int = 0
    excluded_investigations: int = 0
    predecessor_pack_id: Optional[str] = None  # set for a pack produced by reassessing an earlier pack of the period
    lineage_root_pack_id: Optional[str] = None
    investigation_counts: Optional[dict[str, int]] = None


class Period(_Resp):
    period_id: str
    use_case: str
    year: int
    month: int
    status: str
    created_at: str
    last_processed_at: Optional[str] = None
    title: str = ""
    title_source: Literal["STORED", "DERIVED"] = "STORED"
    storage_profile: str = ""
    reporting_status: Literal["NO_DATA", "DOCUMENTS_UPLOADED", "VALIDATION_REQUIRED", "DETERMINISTIC_PACK_AVAILABLE",
                              "INVESTIGATION_AVAILABLE", "FINAL_PACK_PUBLISHED", "ADDITIONAL_EVIDENCE_RECEIVED"]
    published_investigations: int = 0
    eligible_investigations: int = 0
    excluded_investigations: int = 0
    reassessment_runs: int = 0
    latest_reassessment_status: Optional[str] = None
    latest_final_pack_at: Optional[str] = None
    documents_after_publication: int = 0
    pending_reassessment: bool = False
    archive_state: Literal["RESULTS_AND_FINAL_PACK", "RESULTS_NO_FINAL_PACK", "DOCUMENTS_NO_RESULTS", "AWAITING_UPLOAD"]
    batch_count: int
    document_count: int
    latest_batch_status: Optional[str] = None
    latest_validation_status: Optional[str] = None
    latest_run_status: Optional[str] = None
    pack_count: int
    scenario_packs: bool
    exceptions_total: int
    exceptions_open: int
    final_pack_count: int
    processing_supported: bool
    processing_limitation: Optional[str] = None
    investigation_counts: Optional[dict[str, int]] = None
    packs: list[PeriodPackRef]


class UploadBatch(_Resp):
    batch_id: str
    period_id: str
    origin: Literal["UPLOAD", "POC_DATASET_IMPORT", "ZIP_SUBMISSION"]
    created_at: str
    created_by: str
    file_count: int
    validation_status: str
    status: str
    summary: dict
    error: str = ""
    confirmed_at: Optional[str] = None
    confirmed_by: Optional[str] = None
    display_name: Optional[str] = None  # ZIP packages only: summary.package.display_name, else derived from the ZIP name


class SourceDocument(_Resp):
    document_id: str
    batch_id: str
    original_filename: str
    evidence_id: Optional[str] = None
    category: Optional[str] = None
    file_format: str
    size_bytes: int
    sha256: str
    reporting_period: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    record_count: Optional[int] = None
    validation_status: Literal["VALID", "WARNING", "ERROR"]
    checks: dict
    storage_kind: Literal["UPLOADED_ORIGINAL", "POC_DATASET"]
    created_at: str
    review_decision: Optional[Literal["INCLUDE", "EXCLUDE"]] = None
    review_comment: str = ""
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    submission_kind: Literal["INITIAL", "ADDITIONAL_EVIDENCE", "CORRECTION"] = "INITIAL"
    submission_reason: str = ""
    replaces_document_id: Optional[str] = None


class ProcessingRun(_Resp):
    run_id: str
    period_id: str
    batch_id: str
    job_id: Optional[str] = None
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "INTERRUPTED"]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: str = ""
    result: dict
    created_at: str
    created_by: str


class BatchDetail(_Resp):
    batch: UploadBatch
    documents: list[SourceDocument]
    runs: list[ProcessingRun]


class ReconcileRequest(_Req):
    purpose: Literal["INITIAL", "REASSESSMENT"] = "INITIAL"
    reason: str = Field("", max_length=500)
    ai_authorization: Optional[AiConfirmation] = Field(
        None, description="What the processing confirmation disclosed (provider, model). AI investigation of every "
                          "exception of the resulting pack is mandatory; the confirmation is its run-level authorisation, and a "
                          "configuration that changed since it was shown is refused")


class PeriodDetail(_Resp):
    period: Period
    batches: list[UploadBatch]
    documents: list[SourceDocument]
    runs: list[ProcessingRun]
    current_set: dict[str, str]
    missing_required: list[str]
    processing_supported: bool
    processing_limitation: Optional[str] = None
    evidence_types: dict[str, str]


class DocumentReviewRequest(_Req):
    decision: Literal["INCLUDE", "EXCLUDE"]
    comment: str = Field(min_length=3, max_length=2000)


class ActivityEvent(_Resp):
    at: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    details: dict


# ---------------------------------------------------------------- exception investigation cases
CASE_ENTRY_KINDS = Literal["NOTE", "EVIDENCE", "EVIDENCE_GAP", "OBSERVATION", "HYPOTHESIS", "DECISION"]
CASE_RESOLUTIONS = Literal["UNRESOLVED", "EXPLAINED_BY_ANALYST", "ESCALATED"]


class CaseEntryRequest(_Req):
    kind: CASE_ENTRY_KINDS
    text: str = Field(max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    expected_revision: int = Field(ge=0, description="The case revision the entry was written against (optimistic concurrency)")
    resolution: Optional[CASE_RESOLUTIONS] = Field(None, description="DECISION only: the human resolution of the case")
    close: Optional[bool] = Field(None, description="DECISION only: close (true) or keep/reopen (false) the case")


class CaseAiRequest(_Req):
    retry_of: Optional[str] = Field(None, description="Job ID of an earlier failed or interrupted attempt being retried")
    note: str = Field("", max_length=500)
    authorization: Optional[AiConfirmation] = Field(None, description="Required: the analyst's explicit authorisation")


class CaseEntry(_Resp):
    entry_id: str
    case_id: str
    seq: int
    kind: Literal["NOTE", "EVIDENCE", "EVIDENCE_GAP", "OBSERVATION", "HYPOTHESIS", "DECISION", "AI_REQUEST"]
    text: str
    evidence_refs: list[str]
    details: dict
    created_at: str
    created_by: str


class CaseSummary(_Resp):
    case_id: str
    period_id: str
    pack_id: str
    exception_id: str
    status: Literal["OPEN", "CLOSED"]
    human_resolution: CASE_RESOLUTIONS
    revision: int
    created_at: str
    created_by: str
    updated_at: str


class CaseDetail(CaseSummary):
    """The case with its append-only history. `exception` is the deterministic exception exactly as recorded in the pack
    (never changed by the case). Confirmed observations, hypotheses, evidence gaps and human decisions are listed apart."""
    exception: dict
    entries: list[CaseEntry]
    supporting_evidence: list[CaseEntry]
    evidence_gaps: list[CaseEntry]
    notes: list[CaseEntry]
    confirmed_observations: list[CaseEntry]
    hypotheses: list[CaseEntry]
    human_decisions: list[CaseEntry]
    ai_requests: list[CaseEntry]
    ai_jobs: list[Job]
    ai_investigations: dict
    missing_evidence_in_pack: list


# ---------------------------------------------------------------- AI authorisation, reassessment, lineage, dashboard (phase 8)
class AiConfiguration(_Resp):
    provider: str
    model: str
    reasoning_effort: Optional[str] = None
    provider_configured: bool
    configuration_problem: Optional[str] = None
    investigation_mode: str
    tool_limits: dict
    charges_notice: str
    statements: dict[str, str]


class AiAuthorization(_Resp):
    id: int
    authorization_id: str
    operation: Literal["INVESTIGATION", "CLOSING_SUMMARY", "AUTO_INVESTIGATION"]
    result: str
    period_id: str
    pack_id: str
    exception_id: Optional[str] = None
    review_id: Optional[str] = None
    case_id: Optional[str] = None
    job_id: Optional[str] = None
    provider: str
    model: str
    authorized_by: str
    authorized_at: str
    details: dict


class ReassessmentPlan(_Resp):
    period_id: str
    latest_final_pack_id: Optional[str] = None
    latest_final_pack_at: Optional[str] = None
    target_pack_id: Optional[str] = None
    pending_reassessment: bool
    uploaded_set: dict[str, str]
    baseline: Optional[dict] = None
    baseline_problems: list[str]
    effective_set: dict[str, dict]
    missing_required: list[str]
    new_documents: list[dict]
    can_reassess: bool
    blockers: list[str]


class PackLineage(_Resp):
    pack_id: str
    period_id: str
    predecessor_pack_id: str
    lineage_root_pack_id: str
    purpose: str
    processing_run_id: str
    reason: str
    change_summary: dict
    recorded_at: str
    recorded_by: str


class InvestigationCounts(_Resp):
    published: int
    eligible: int
    running: int
    rejected_attempts: int
    unregistered: int
    authorization_discrepancy: int
    ineligible_other: int


class DashboardSummary(_Resp):
    period_id: Optional[str] = None
    packs: int
    exceptions: int
    exceptions_open: int
    exceptions_with_eligible_investigation: int
    investigations: InvestigationCounts
    final_packs_period: int
    latest_final_pack_period_at: Optional[str] = None
    final_packs_global: int
    latest_final_pack_global_at: Optional[str] = None
    pending_reviews_period: int
    pending_reviews_global: int
    per_pack: list[dict]


# Forward references to AnalystReview (defined after the models that use it).
PublishedInvestigation.model_rebuild()
InvestigationDetail.model_rebuild()
