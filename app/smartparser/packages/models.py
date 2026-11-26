"""Phase 3B-9 - evidence package data model.

    EvidencePackage      one reporting period; one slot (EvidenceFile) per evidence category; all versions; snapshots
    EvidenceFile         the slot of one category: its versions in order, and the version selected by the active snapshot
    FileVersion          one upload for one slot: its own intake ID + SHA-256 (never overwritten), its processing outcome
    PackageSnapshot      IMMUTABLE: the exact versions (and hashes) selected for downstream reconciliation
    PackageValidationResult  the package-level checks run over one candidate selection

Existing models are reused, not duplicated: the intake record (intake.store.IntakeRecord) is the upload identity, the
column-review case (review.intake) and proposal session (review.session) are the HITL state, CategoryConfirmation
(review.approvals) is the category confirmation, FileMappingRule ids are the mapping references, and the 14-point
handoff result is summarised from handoff.eligibility.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..review.approvals import CategoryConfirmation

VersionStatus = Literal[
    "RECEIVED",                # stored, not yet processed (only visible if processing was interrupted)
    "REVIEW_REQUIRED",         # a person must decide (column-review case or proposal session)
    "RESUBMISSION_REQUIRED",   # required source columns are missing: a corrected file is needed
    "FAILED_VALIDATION",       # processed, but cannot become eligible (held / data errors / not eligible)
    "VALIDATED",               # every file-level check passed: candidate for activation
    "ACTIVE",                  # selected by the active package snapshot
    "SUPERSEDED",              # was active (or validated) and was replaced by a newer activated version
    "REJECTED",                # rejected (wrong category, reviewer rejection)
]
# A new version of the slot is needed (these block the package until a corrected file validates).
NEEDS_NEW_VERSION = {"RESUBMISSION_REQUIRED", "FAILED_VALIDATION", "REJECTED"}
# 3B-10: ONLY these states accept a corrected version. A VALIDATED / ACTIVE (accepted) file is never voluntarily
# replaced, and a file under open review must be completed or rejected first. Re-checking an accepted file is
# PackageService.reprocess_version (same intake, no new version).

PackageStatus = Literal[
    "RECEIVED",                # created, no file yet
    "RESUBMISSION_REQUIRED",   # at least one required category waits for a corrected file
    "REVIEW_REQUIRED",         # at least one required category waits for a reviewer
    "INCOMPLETE",              # at least one required category has no file at all
    "READY_FOR_VALIDATION",    # every required category has a VALIDATED/ACTIVE latest version; not yet activated
    "RECONCILIATION_READY",    # the active snapshot is exactly the current selection and passed package validation
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusChange(_Strict):
    status: str
    at: str
    note: str = ""


class HandoffSummary(_Strict):
    eligible: bool
    failed_checks: list[int] = Field(default_factory=list)
    output_sha256: str | None = None
    preview_csv: str | None = None          # path relative to the package store root
    provenance: str | None = None           # path relative to the package store root
    basis: Literal["CSV_14_POINT_HANDOFF", "PDF_CONTENT_CLASSIFICATION_ONLY"] = "CSV_14_POINT_HANDOFF"
    checks: list[dict] = Field(default_factory=list)   # 3B-11: every handoff check {id, name, passed, detail}


class FileVersion(_Strict):
    file_version_id: str
    package_id: str
    evidence_category: str
    version_number: int = Field(ge=1)
    intake_id: str
    original_filename: str
    source_sha256: str
    uploaded_at: str
    reporting_period: str
    version_status: VersionStatus
    processing_status: str                  # "<route>:<decision>" from the orchestrator, or "PDF:<classification>"
    reasons: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    content_category: str | None = None     # what the content identifies as (deterministic), if anything
    review_case_id: str | None = None
    review_session_id: str | None = None
    previous_version_id: str | None = None
    replacement_reason: str | None = None
    mapping_rule_refs: list[dict] = Field(default_factory=list)   # {kind, rule_id, rule_version}
    confirmation: CategoryConfirmation | None = None
    handoff: HandoffSummary | None = None
    status_history: list[StatusChange] = Field(default_factory=list)


class EvidenceFile(_Strict):
    evidence_category: str
    required: bool
    version_ids: list[str] = Field(default_factory=list)       # in version order
    active_version_id: str | None = None


class PackageCheck(_Strict):
    check_id: str
    name: str
    passed: bool
    detail: str = ""


class PackageValidationResult(_Strict):
    validation_id: str
    package_id: str
    at: str
    selection: dict[str, str]               # category -> file_version_id (the candidate)
    checks: list[PackageCheck]
    passed: bool


class SnapshotEntry(_Strict):
    evidence_category: str
    file_version_id: str
    version_number: int
    intake_id: str
    original_filename: str
    source_sha256: str
    reporting_period: str
    handoff: HandoffSummary | None
    mapping_rule_refs: list[dict] = Field(default_factory=list)
    confirmation_id: str | None = None


class PackageSnapshot(_Strict):
    snapshot_id: str
    package_id: str
    reporting_period: str
    sequence: int = Field(ge=1)
    created_at: str
    entries: list[SnapshotEntry]
    selection_sha256: str                   # hash over (category, version id, source sha) - reproducible
    validation_id: str
    validation_status: Literal["PASSED"] = "PASSED"
    previous_snapshot_id: str | None = None
    submission_authorised: Literal[False] = False
    reconciliation_status: Literal["NOT_RUN"] = "NOT_RUN"


class EvidencePackage(_Strict):
    package_id: str
    reporting_period: str
    created_at: str
    updated_at: str
    package_status: PackageStatus = "RECEIVED"
    required_evidence_categories: list[str]
    evidence_files: dict[str, EvidenceFile] = Field(default_factory=dict)
    versions: dict[str, FileVersion] = Field(default_factory=dict)
    active_snapshot_id: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    validation_results: list[PackageValidationResult] = Field(default_factory=list)
    unassigned_uploads: list[dict] = Field(default_factory=list)    # refused before a slot was assigned (traceable)
    revision: int = 0

    def latest(self, category: str) -> FileVersion | None:
        slot = self.evidence_files.get(category)
        return self.versions[slot.version_ids[-1]] if slot and slot.version_ids else None

    def history(self, category: str) -> list[FileVersion]:
        slot = self.evidence_files.get(category)
        return [self.versions[v] for v in slot.version_ids] if slot else []
