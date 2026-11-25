"""SQLAlchemy 2.x models for application state (PostgreSQL in operation; SQLite is accepted for offline tests).

One database, two schemas by ownership (migration 0003):
  audit       reporting periods and their packs, reconciliation (processing) runs, final review, final-pack records,
              the investigation publication registry and its authorisation decisions, and record provenance
  operations  uploaded documents, background jobs, exception investigation cases and the activity log
There is no users schema: this local POC has no user accounts (the reviewer is the configured analyst reference).
SQLite has no schemas: the test engine maps both schema names to its single namespace (uc042app.db.make_engine).

What does NOT live here (authoritative elsewhere, referenced by ID only):
  packs/<pack_id>/                 deterministic packs (immutable files; one packs root per storage profile)
  investigations/                  AI findings, evidence packets and ledgers (write-once files)
  final_packs/<final_pack_id>/     final audit-pack artefacts (write-once files)
  <document store>/objects/        original uploaded source documents (content-addressed files)
"""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")
AUDIT, OPERATIONS = "audit", "operations"
SCHEMAS = (AUDIT, OPERATIONS)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------------------------- audit: periods and packs
class ReconciliationPeriod(Base):
    __tablename__ = "reconciliation_periods"
    __table_args__ = {"schema": AUDIT}
    period_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # PER-YYYY-MM (the engine's period identifier)
    use_case: Mapped[str] = mapped_column(String(16), default="UC-042")
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))  # EMPTY | DOCUMENTS_UPLOADED | PROCESSING | PROCESSED | PROCESSING_FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="", server_default="")  # editable report title; period_id never changes
    # Storage profile of the period's existing artefacts (uc042lib.investigation.roots.PROFILES), e.g. historical-demo for
    # January-August 2026. "" = the backend's primary roots. Set by the unification migration; never inferred at runtime.
    storage_profile: Mapped[str] = mapped_column(String(32), default="", server_default="")


class PeriodPack(Base):
    """A deterministic pack belonging to a period (reference only; the pack itself stays in its packs root)."""
    __tablename__ = "period_packs"
    __table_args__ = (Index("ix_period_packs_pack_id", "pack_id"), {"schema": AUDIT})
    period_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.reconciliation_periods.period_id"), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origin: Mapped[str] = mapped_column(String(24))  # POC_SCENARIO | UPLOAD_PROCESSING
    scenario_id: Mapped[str] = mapped_column(String(16), default="")
    dataset: Mapped[str] = mapped_column(String(128), default="")
    processing_run_id: Mapped[str | None] = mapped_column(ForeignKey(f"{AUDIT}.processing_runs.run_id"), nullable=True)
    pack_content_sha256: Mapped[str] = mapped_column(String(64))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessingRun(Base):
    """A reconciliation run: the deterministic engine over a period's confirmed document set (analyst-initiated only)."""
    __tablename__ = "processing_runs"
    __table_args__ = {"schema": AUDIT}
    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    period_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.reconciliation_periods.period_id"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey(f"{OPERATIONS}.upload_batches.batch_id"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(24))  # QUEUED | RUNNING | SUCCEEDED | FAILED | BLOCKED
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JsonType, default=dict)  # pack_id, outcome, intake, findings, purpose
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))


# ---------------------------------------------------------------------------------------------- operations: documents
class UploadBatch(Base):
    __tablename__ = "upload_batches"
    __table_args__ = {"schema": OPERATIONS}
    batch_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    period_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.reconciliation_periods.period_id"), index=True)
    origin: Mapped[str] = mapped_column(String(24))  # UPLOAD | POC_DATASET_IMPORT
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer)
    validation_status: Mapped[str] = mapped_column(String(24))  # VALID | WARNINGS | INCOMPLETE | INVALID
    status: Mapped[str] = mapped_column(String(24))  # VALIDATED | CONFIRMED | PROCESSING | PROCESSED | PROCESSING_FAILED
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = {"schema": OPERATIONS}
    document_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey(f"{OPERATIONS}.upload_batches.batch_id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    evidence_id: Mapped[str | None] = mapped_column(String(8), nullable=True)  # IN-01 ... IN-19 when identified
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_format: Mapped[str] = mapped_column(String(8))  # CSV | PDF | OTHER
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    reporting_period: Mapped[str] = mapped_column(String(16))
    date_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(16))  # VALID | WARNING | ERROR
    checks: Mapped[dict] = mapped_column(JsonType, default=dict)  # classification, date analysis, duplicates, messages
    storage_ref: Mapped[str] = mapped_column(String(512))  # object:<sha256> or dataset:<dataset>/<relative path>
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # INCLUDE | EXCLUDE (duplicates)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # How the document arrived: INITIAL source document, ADDITIONAL_EVIDENCE for the period, or CORRECTION of an earlier
    # document (replaces_document_id). The replaced document is never changed; both stay in the history.
    submission_kind: Mapped[str] = mapped_column(String(24), default="INITIAL", server_default="INITIAL")
    submission_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    replaces_document_id: Mapped[str | None] = mapped_column(ForeignKey(f"{OPERATIONS}.source_documents.document_id"),
                                                             nullable=True, index=True)


# ---------------------------------------------------------------------------------------------- application state
class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = {"schema": OPERATIONS}
    job_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operation: Mapped[str] = mapped_column(String(24))
    pack_id: Mapped[str] = mapped_column(String(64), index=True)
    exception_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    submitted_at: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonType)  # the full job record


class ReviewSessionRow(Base):
    __tablename__ = "review_sessions"
    __table_args__ = {"schema": AUDIT}
    review_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonType)


class ReviewDecisionRow(Base):
    """Append-only: rows are inserted, never updated or deleted by the application."""
    __tablename__ = "review_decisions"
    __table_args__ = (UniqueConstraint("review_id", "seq"), {"schema": AUDIT})
    review_decision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.review_sessions.review_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    decided_at: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonType)


class PreviewRow(Base):
    """Write-once preview fingerprints and documents (the preview document is application state, not an artefact)."""
    __tablename__ = "previews"
    __table_args__ = {"schema": AUDIT}
    preview_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.review_sessions.review_id"), index=True)
    meta: Mapped[dict] = mapped_column(JsonType)
    document: Mapped[dict] = mapped_column(JsonType)


class FinalPackRecordRow(Base):
    __tablename__ = "final_pack_records"
    __table_args__ = {"schema": AUDIT}
    review_decision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(40), index=True)
    pack_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonType)


class RegistryEntryRow(Base):
    """Investigation publication registry (append-only; seq is the order of registration)."""
    __tablename__ = "investigation_registry"
    __table_args__ = {"schema": AUDIT}
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    investigation_id: Mapped[str] = mapped_column(String(48), index=True)
    record_type: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonType)


class InvestigationAuthorizationRow(Base):
    """Append-only authorisation decisions about published investigations. The latest row per investigation is in force.
    APPROVED: part of the approved published set. AUTHORIZATION_DISCREPANCY: kept (artefact and registry entry are never
    changed) but excluded from the approved set, so it is not eligible for a final audit pack. No row: the registry alone
    decides (an analyst-initiated job in this backend)."""
    __tablename__ = "investigation_authorizations"
    __table_args__ = {"schema": AUDIT}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(32))  # APPROVED | AUTHORIZATION_DISCREPANCY
    basis: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[str] = mapped_column(String(64))


class AiExecutionAuthorizationRow(Base):
    """Append-only, immutable: the analyst's explicit confirmation of one paid AI operation, recorded BEFORE the job that
    calls the model is submitted (migration 0004; on PostgreSQL a trigger refuses UPDATE and DELETE). Refused confirmations
    (provider not configured, an operation already running, ...) are recorded too. Distinct from investigation_authorizations,
    which decides whether an already-published investigation belongs to the approved set."""
    __tablename__ = "ai_execution_authorizations"
    __table_args__ = {"schema": AUDIT}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    authorization_id: Mapped[str] = mapped_column(String(40), unique=True)  # AIA-<hex>
    operation: Mapped[str] = mapped_column(String(32))  # INVESTIGATION | CLOSING_SUMMARY
    result: Mapped[str] = mapped_column(String(48))  # AUTHORIZED | REFUSED_<reason code>
    period_id: Mapped[str] = mapped_column(String(16), index=True)
    pack_id: Mapped[str] = mapped_column(String(64), index=True)
    exception_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    authorized_by: Mapped[str] = mapped_column(String(64))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JsonType, default=dict)


class PackLineageRow(Base):
    """A deterministic pack produced by a REASSESSMENT run: its predecessor (the pack it reassesses) and the first pack of
    the period's lineage. A pack without a row is its own lineage root (every independent demonstration scenario)."""
    __tablename__ = "pack_lineage"
    __table_args__ = {"schema": AUDIT}
    pack_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    period_id: Mapped[str] = mapped_column(String(16), ForeignKey(f"{AUDIT}.reconciliation_periods.period_id"), index=True)
    predecessor_pack_id: Mapped[str] = mapped_column(String(64))
    lineage_root_pack_id: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # REASSESSMENT
    processing_run_id: Mapped[str] = mapped_column(String(40), ForeignKey(f"{AUDIT}.processing_runs.run_id"))
    reason: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[str] = mapped_column(String(64))


class RecordProvenanceRow(Base):
    """Where a migrated record came from: one row per source record copied, merged or renumbered by a migration."""
    __tablename__ = "record_provenance"
    __table_args__ = (UniqueConstraint("source_database", "source_table", "source_key"), {"schema": AUDIT})
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    migration_id: Mapped[str] = mapped_column(String(48), index=True)
    source_database: Mapped[str] = mapped_column(String(64))
    source_table: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(256))
    target_table: Mapped[str] = mapped_column(String(64))
    target_key: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(24))  # COPIED | MERGED | RENUMBERED
    source_row: Mapped[dict] = mapped_column(JsonType)  # the complete original row, as read
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------------------------- operations: cases
class ExceptionCaseRow(Base):
    """An analyst's investigation case for one exception of one pack. The deterministic exception in the pack is never
    changed; the case's human_resolution starts UNRESOLVED and changes only by an explicit human DECISION entry."""
    __tablename__ = "exception_cases"
    __table_args__ = (UniqueConstraint("pack_id", "exception_id"), {"schema": OPERATIONS})
    case_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    period_id: Mapped[str] = mapped_column(ForeignKey(f"{AUDIT}.reconciliation_periods.period_id"), index=True)
    pack_id: Mapped[str] = mapped_column(String(64), index=True)
    exception_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))  # OPEN | CLOSED
    human_resolution: Mapped[str] = mapped_column(String(32))  # UNRESOLVED | EXPLAINED_BY_ANALYST | ESCALATED
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExceptionCaseEntryRow(Base):
    """Append-only case history: notes, evidence, evidence gaps, confirmed observations, hypotheses, human decisions and
    AI requests/results. Rows are inserted, never updated or deleted."""
    __tablename__ = "exception_case_entries"
    __table_args__ = (UniqueConstraint("case_id", "seq"), {"schema": OPERATIONS})
    entry_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey(f"{OPERATIONS}.exception_cases.case_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list] = mapped_column(JsonType, default=list)
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_entity", "entity_type", "entity_id"), {"schema": OPERATIONS})
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
