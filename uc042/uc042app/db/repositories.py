"""SQL implementations of every repository interface (SQLAlchemy 2.x; PostgreSQL in operation, SQLite in offline tests).
They return the same JSON-compatible dicts as the file-backed repositories, so services do not change."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..repositories.base import (ActivityRepository, AiAuthorizationRepository, AuthorizationRepository, CaseRepository,
                                 ConcurrentUpdate, DuplicateRecord, FinalPackRecordRepository, JobRepository, LineageRepository,
                                 PeriodRepository, ProcessingRunRepository, RegistryRepository, ReviewRepository, UploadRepository)
from . import models as m


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite returns naive datetimes; values are always stored as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class _Repo:
    def __init__(self, sessions):
        self.sessions = sessions


# ---------------------------------------------------------------------------------------------- application state
class SqlJobRepository(_Repo, JobRepository):
    def create(self, job):
        with self.sessions.begin() as s:
            s.add(m.JobRow(job_id=job["job_id"], operation=job["operation"], pack_id=job["pack_id"], exception_id=job.get("exception_id"),
                           status=job["status"], submitted_at=job["submitted_at"], data=job))
        return job

    def get(self, job_id):
        with self.sessions() as s:
            row = s.get(m.JobRow, job_id)
            return dict(row.data) if row else None

    def update(self, job_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.JobRow, job_id, with_for_update=True)
            if row is None:
                raise KeyError(job_id)
            data = dict(row.data, **changes)
            row.data, row.status = data, data["status"]
            return data

    def list(self, pack_id=None, exception_id=None, statuses=None):
        q = select(m.JobRow).order_by(m.JobRow.submitted_at)
        if pack_id is not None:
            q = q.where(m.JobRow.pack_id == pack_id)
        if exception_id is not None:
            q = q.where(m.JobRow.exception_id == exception_id)
        if statuses is not None:
            q = q.where(m.JobRow.status.in_(list(statuses)))
        with self.sessions() as s:
            return [dict(r.data) for r in s.scalars(q)]


class SqlReviewRepository(_Repo, ReviewRepository):
    def create(self, session):
        with self.sessions.begin() as s:
            s.add(m.ReviewSessionRow(review_id=session["review_id"], pack_id=session["pack_id"], status=session["status"],
                                     revision=session["revision"], created_at=session["created_at"], data=session))
        return session

    def get(self, review_id):
        with self.sessions() as s:
            row = s.get(m.ReviewSessionRow, review_id)
            return dict(row.data) if row else None

    def save(self, session, expected_revision):
        new = dict(session, revision=expected_revision + 1)
        with self.sessions.begin() as s:  # optimistic concurrency: the UPDATE only matches the expected revision
            res = s.execute(update(m.ReviewSessionRow).where(m.ReviewSessionRow.review_id == session["review_id"],
                                                             m.ReviewSessionRow.revision == expected_revision)
                            .values(revision=new["revision"], status=new["status"], data=new))
            if res.rowcount != 1:
                raise ConcurrentUpdate(f"review {session['review_id']} changed")
        return new

    def list(self, pack_id=None):
        q = select(m.ReviewSessionRow).order_by(m.ReviewSessionRow.created_at)
        if pack_id is not None:
            q = q.where(m.ReviewSessionRow.pack_id == pack_id)
        with self.sessions() as s:
            return [dict(r.data) for r in s.scalars(q)]

    def append_decision(self, review_id, decision):
        with self.sessions.begin() as s:
            seq = (s.scalar(select(func.max(m.ReviewDecisionRow.seq)).where(m.ReviewDecisionRow.review_id == review_id)) or 0) + 1
            s.add(m.ReviewDecisionRow(review_decision_id=decision["review_decision_id"], review_id=review_id, seq=seq,
                                      decided_at=decision["decided_at"], data=decision))
        return decision

    def decisions(self, review_id):
        with self.sessions() as s:
            return [dict(r.data) for r in s.scalars(select(m.ReviewDecisionRow).where(m.ReviewDecisionRow.review_id == review_id)
                                                     .order_by(m.ReviewDecisionRow.seq))]

    def save_preview(self, review_id, preview_id, meta, document):
        try:
            with self.sessions.begin() as s:
                s.add(m.PreviewRow(preview_id=preview_id, review_id=review_id, meta=meta, document=document))
        except IntegrityError:
            raise FileExistsError(preview_id) from None  # write-once, like the file store

    def get_preview(self, review_id, preview_id):
        with self.sessions() as s:
            row = s.get(m.PreviewRow, preview_id)
            if row is None or row.review_id != review_id:
                return None, None
            return dict(row.meta), row.document


class SqlFinalPackRecordRepository(_Repo, FinalPackRecordRepository):
    def create(self, record):
        try:
            with self.sessions.begin() as s:
                s.add(m.FinalPackRecordRow(review_decision_id=record["review_decision_id"], review_id=record["review_id"],
                                           pack_id=record["pack_id"], status=record["status"], created_at=record["created_at"], data=record))
        except IntegrityError:
            raise DuplicateRecord(record["review_decision_id"]) from None
        return record

    def get(self, decision_id):
        with self.sessions() as s:
            row = s.get(m.FinalPackRecordRow, decision_id)
            return dict(row.data) if row else None

    def update(self, decision_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.FinalPackRecordRow, decision_id, with_for_update=True)
            data = dict(row.data, **changes)
            row.data, row.status = data, data["status"]
            return data

    def list(self, pack_id=None):
        q = select(m.FinalPackRecordRow).order_by(m.FinalPackRecordRow.created_at)
        if pack_id is not None:
            q = q.where(m.FinalPackRecordRow.pack_id == pack_id)
        with self.sessions() as s:
            return [dict(r.data) for r in s.scalars(q)]


class SqlRegistryRepository(_Repo, RegistryRepository):
    def append(self, entry):
        try:
            with self.sessions.begin() as s:
                s.add(m.RegistryEntryRow(seq=entry["seq"], investigation_id=entry["investigation_id"], record_type=entry["record_type"],
                                         recorded_at=entry["recorded_at"], data=entry))
        except IntegrityError:
            raise DuplicateRecord(f"registry seq {entry['seq']}") from None

    def entries(self):
        with self.sessions() as s:
            return [dict(r.data) for r in s.scalars(select(m.RegistryEntryRow).order_by(m.RegistryEntryRow.seq))]

    def signature(self):
        """Changes whenever any entry changes (not only on append), so a row edited outside the application invalidates
        cached eligibility exactly as an edited registry file does. The registry is small (one row per publication)."""
        digest = hashlib.sha256()
        for entry in self.entries():
            digest.update(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        return digest.hexdigest()


# ---------------------------------------------------------------------------------------------- monthly management
def _row_dict(row, cols):
    out = {}
    for c in cols:
        v = getattr(row, c)
        out[c] = _iso(v) if isinstance(v, datetime) else v
    return out


PERIOD_COLS = ("period_id", "use_case", "year", "month", "status", "created_at", "last_processed_at", "note", "title",
               "storage_profile")
CASE_COLS = ("case_id", "period_id", "pack_id", "exception_id", "status", "human_resolution", "revision", "created_at", "created_by",
             "updated_at")
ENTRY_COLS = ("entry_id", "case_id", "seq", "kind", "text", "evidence_refs", "details", "created_at", "created_by")
AUTH_COLS = ("id", "investigation_id", "status", "basis", "recorded_at", "recorded_by")
AI_AUTH_COLS = ("id", "authorization_id", "operation", "result", "period_id", "pack_id", "exception_id", "review_id", "case_id", "job_id",
                "provider", "model", "authorized_by", "authorized_at", "details")
LINEAGE_COLS = ("pack_id", "period_id", "predecessor_pack_id", "lineage_root_pack_id", "purpose", "processing_run_id", "reason",
                "change_summary", "recorded_at", "recorded_by")
PACK_COLS = ("period_id", "pack_id", "origin", "scenario_id", "dataset", "processing_run_id", "pack_content_sha256", "registered_at")
BATCH_COLS = ("batch_id", "period_id", "origin", "created_at", "created_by", "file_count", "validation_status", "status", "summary",
              "error", "confirmed_at", "confirmed_by")
DOC_COLS = ("document_id", "batch_id", "original_filename", "evidence_id", "category", "file_format", "size_bytes", "sha256",
            "reporting_period", "date_from", "date_to", "record_count", "validation_status", "checks", "storage_ref", "created_at",
            "review_decision", "review_comment", "reviewed_at", "reviewed_by", "submission_kind", "submission_reason",
            "replaces_document_id")
RUN_COLS = ("run_id", "period_id", "batch_id", "job_id", "status", "started_at", "completed_at", "error", "result", "created_at", "created_by")
DT_FIELDS = {"created_at", "last_processed_at", "registered_at", "confirmed_at", "reviewed_at", "started_at", "completed_at",
             "updated_at", "recorded_at"}


def _values(d):
    return {k: (_dt(v) if k in DT_FIELDS else v) for k, v in d.items()}


class SqlActivityRepository(_Repo, ActivityRepository):
    def append(self, event):
        with self.sessions.begin() as s:
            s.add(m.ActivityEvent(**_values(dict(event, at=_dt(event["at"])))))

    def recent(self, limit=50, entity_type=None, entity_id=None):
        q = select(m.ActivityEvent).order_by(m.ActivityEvent.at.desc(), m.ActivityEvent.id.desc()).limit(limit)
        if entity_type:
            q = q.where(m.ActivityEvent.entity_type == entity_type)
        if entity_id:
            q = q.where(m.ActivityEvent.entity_id == entity_id)
        with self.sessions() as s:
            return [_row_dict(r, ("at", "actor", "action", "entity_type", "entity_id", "details")) for r in s.scalars(q)]


class SqlPeriodRepository(_Repo, PeriodRepository):
    def get(self, period_id):
        with self.sessions() as s:
            row = s.get(m.ReconciliationPeriod, period_id)
            return _row_dict(row, PERIOD_COLS) if row else None

    def list(self):
        with self.sessions() as s:
            return [_row_dict(r, PERIOD_COLS) for r in s.scalars(select(m.ReconciliationPeriod).order_by(m.ReconciliationPeriod.period_id.desc()))]

    def ensure(self, period_id, year, month, status="EMPTY", title=""):
        with self.sessions.begin() as s:
            row = s.get(m.ReconciliationPeriod, period_id)
            if row is None:
                row = m.ReconciliationPeriod(period_id=period_id, year=year, month=month, status=status, created_at=_now(), note="",
                                             title=title)
                s.add(row)
                s.flush()
            return _row_dict(row, PERIOD_COLS)

    def update(self, period_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.ReconciliationPeriod, period_id, with_for_update=True)
            for k, v in _values(changes).items():
                setattr(row, k, v)
            return _row_dict(row, PERIOD_COLS)

    def packs(self, period_id=None):
        q = select(m.PeriodPack).order_by(m.PeriodPack.registered_at, m.PeriodPack.pack_id)
        if period_id:
            q = q.where(m.PeriodPack.period_id == period_id)
        with self.sessions() as s:
            return [_row_dict(r, PACK_COLS) for r in s.scalars(q)]

    def add_pack(self, record):
        with self.sessions.begin() as s:
            if s.get(m.PeriodPack, (record["period_id"], record["pack_id"])) is None:
                s.add(m.PeriodPack(**_values(record)))

    def storage_profiles(self):
        """The storage profiles recorded on periods (those whose artefacts are outside the primary roots)."""
        with self.sessions() as s:
            q = select(m.ReconciliationPeriod.storage_profile).where(m.ReconciliationPeriod.storage_profile != "").distinct()
            return sorted(s.scalars(q))


class SqlUploadRepository(_Repo, UploadRepository):
    def create_batch(self, batch, documents):
        with self.sessions.begin() as s:
            s.add(m.UploadBatch(**_values(batch)))
            s.flush()
            for d in documents:
                s.add(m.SourceDocument(**_values(d)))

    def batch(self, batch_id):
        with self.sessions() as s:
            row = s.get(m.UploadBatch, batch_id)
            return _row_dict(row, BATCH_COLS) if row else None

    def batches(self, period_id):
        with self.sessions() as s:
            q = select(m.UploadBatch).where(m.UploadBatch.period_id == period_id).order_by(m.UploadBatch.created_at)
            return [_row_dict(r, BATCH_COLS) for r in s.scalars(q)]

    def update_batch(self, batch_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.UploadBatch, batch_id, with_for_update=True)
            for k, v in _values(changes).items():
                setattr(row, k, v)
            return _row_dict(row, BATCH_COLS)

    def documents(self, batch_id=None, period_id=None):
        q = select(m.SourceDocument).order_by(m.SourceDocument.evidence_id, m.SourceDocument.original_filename)
        if batch_id:
            q = q.where(m.SourceDocument.batch_id == batch_id)
        if period_id:
            q = q.join(m.UploadBatch).where(m.UploadBatch.period_id == period_id)
        with self.sessions() as s:
            return [_row_dict(r, DOC_COLS) for r in s.scalars(q)]

    def document(self, document_id):
        with self.sessions() as s:
            row = s.get(m.SourceDocument, document_id)
            return _row_dict(row, DOC_COLS) if row else None

    def update_document(self, document_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.SourceDocument, document_id, with_for_update=True)
            for k, v in _values(changes).items():
                setattr(row, k, v)
            return _row_dict(row, DOC_COLS)

    def find_documents(self, sha256=None, original_filename=None, period_id=None):
        q = select(m.SourceDocument).join(m.UploadBatch)
        if sha256:
            q = q.where(m.SourceDocument.sha256 == sha256)
        if original_filename:
            q = q.where(m.SourceDocument.original_filename == original_filename)
        if period_id:
            q = q.where(m.UploadBatch.period_id == period_id)
        with self.sessions() as s:
            return [_row_dict(r, DOC_COLS) for r in s.scalars(q)]


class SqlProcessingRunRepository(_Repo, ProcessingRunRepository):
    def create(self, run):
        with self.sessions.begin() as s:
            s.add(m.ProcessingRun(**_values(run)))
        return run

    def get(self, run_id):
        with self.sessions() as s:
            row = s.get(m.ProcessingRun, run_id)
            return _row_dict(row, RUN_COLS) if row else None

    def update(self, run_id, changes):
        with self.sessions.begin() as s:
            row = s.get(m.ProcessingRun, run_id, with_for_update=True)
            for k, v in _values(changes).items():
                setattr(row, k, v)
            return _row_dict(row, RUN_COLS)

    def list(self, period_id=None, batch_id=None):
        q = select(m.ProcessingRun).order_by(m.ProcessingRun.created_at)
        if period_id:
            q = q.where(m.ProcessingRun.period_id == period_id)
        if batch_id:
            q = q.where(m.ProcessingRun.batch_id == batch_id)
        with self.sessions() as s:
            return [_row_dict(r, RUN_COLS) for r in s.scalars(q)]


class SqlAuthorizationRepository(_Repo, AuthorizationRepository):
    def record(self, investigation_id, status, basis, recorded_by):
        with self.sessions.begin() as s:
            row = m.InvestigationAuthorizationRow(investigation_id=investigation_id, status=status, basis=basis, recorded_at=_now(),
                                                  recorded_by=recorded_by)
            s.add(row)
            s.flush()
            return _row_dict(row, AUTH_COLS)

    def current(self, investigation_id):
        q = (select(m.InvestigationAuthorizationRow).where(m.InvestigationAuthorizationRow.investigation_id == investigation_id)
             .order_by(m.InvestigationAuthorizationRow.id.desc()).limit(1))
        with self.sessions() as s:
            row = s.scalars(q).first()
            return _row_dict(row, AUTH_COLS) if row else None

    def list(self):
        with self.sessions() as s:
            return [_row_dict(r, AUTH_COLS) for r in s.scalars(select(m.InvestigationAuthorizationRow)
                                                                .order_by(m.InvestigationAuthorizationRow.id))]


class SqlAiAuthorizationRepository(_Repo, AiAuthorizationRepository):
    """Insert and read only: the service never updates or deletes a record (and PostgreSQL refuses it, migration 0004)."""
    def record(self, rec):
        with self.sessions.begin() as s:
            row = m.AiExecutionAuthorizationRow(**dict(rec, authorized_at=_dt(rec["authorized_at"])))
            s.add(row)
            s.flush()
            return _row_dict(row, AI_AUTH_COLS)

    def get(self, authorization_id):
        with self.sessions() as s:
            row = s.scalars(select(m.AiExecutionAuthorizationRow)
                            .where(m.AiExecutionAuthorizationRow.authorization_id == authorization_id)).first()
            return _row_dict(row, AI_AUTH_COLS) if row else None

    def list(self, pack_id=None, exception_id=None, review_id=None, job_id=None, period_id=None):
        t = m.AiExecutionAuthorizationRow
        q = select(t).order_by(t.id)
        for col, value in ((t.pack_id, pack_id), (t.exception_id, exception_id), (t.review_id, review_id), (t.job_id, job_id),
                           (t.period_id, period_id)):
            if value is not None:
                q = q.where(col == value)
        with self.sessions() as s:
            return [_row_dict(r, AI_AUTH_COLS) for r in s.scalars(q)]


class SqlLineageRepository(_Repo, LineageRepository):
    def add(self, row):
        try:
            with self.sessions.begin() as s:
                r = m.PackLineageRow(**dict(row, recorded_at=_dt(row["recorded_at"])))
                s.add(r)
                s.flush()
                return _row_dict(r, LINEAGE_COLS)
        except IntegrityError as e:
            raise DuplicateRecord(f"lineage of {row['pack_id']} is already recorded") from e

    def get(self, pack_id):
        with self.sessions() as s:
            r = s.get(m.PackLineageRow, pack_id)
            return _row_dict(r, LINEAGE_COLS) if r else None

    def list(self, period_id=None, lineage_root_pack_id=None):
        t = m.PackLineageRow
        q = select(t).order_by(t.recorded_at, t.pack_id)
        if period_id is not None:
            q = q.where(t.period_id == period_id)
        if lineage_root_pack_id is not None:
            q = q.where(t.lineage_root_pack_id == lineage_root_pack_id)
        with self.sessions() as s:
            return [_row_dict(r, LINEAGE_COLS) for r in s.scalars(q)]


class SqlCaseRepository(_Repo, CaseRepository):
    def create(self, case):
        try:
            with self.sessions.begin() as s:
                s.add(m.ExceptionCaseRow(**_values(case)))
        except IntegrityError:
            raise DuplicateRecord(f"{case['pack_id']}/{case['exception_id']}") from None
        return case

    def get(self, case_id):
        with self.sessions() as s:
            row = s.get(m.ExceptionCaseRow, case_id)
            return _row_dict(row, CASE_COLS) if row else None

    def find(self, pack_id, exception_id):
        q = select(m.ExceptionCaseRow).where(m.ExceptionCaseRow.pack_id == pack_id, m.ExceptionCaseRow.exception_id == exception_id)
        with self.sessions() as s:
            row = s.scalars(q).first()
            return _row_dict(row, CASE_COLS) if row else None

    def list(self, period_id=None, pack_id=None):
        q = select(m.ExceptionCaseRow).order_by(m.ExceptionCaseRow.created_at, m.ExceptionCaseRow.case_id)
        if period_id:
            q = q.where(m.ExceptionCaseRow.period_id == period_id)
        if pack_id:
            q = q.where(m.ExceptionCaseRow.pack_id == pack_id)
        with self.sessions() as s:
            return [_row_dict(r, CASE_COLS) for r in s.scalars(q)]

    def append_entry(self, case_id, entry, expected_revision, changes=None):
        with self.sessions.begin() as s:
            row = s.get(m.ExceptionCaseRow, case_id, with_for_update=True)
            if row is None:
                raise KeyError(case_id)
            if row.revision != expected_revision:
                raise ConcurrentUpdate(f"case {case_id} changed")
            seq = (s.scalar(select(func.max(m.ExceptionCaseEntryRow.seq)).where(m.ExceptionCaseEntryRow.case_id == case_id)) or 0) + 1
            e = m.ExceptionCaseEntryRow(**_values(dict(entry, case_id=case_id, seq=seq)))
            s.add(e)
            for k, v in _values(dict(changes or {}, revision=expected_revision + 1, updated_at=entry["created_at"])).items():
                setattr(row, k, v)
            s.flush()
            return _row_dict(row, CASE_COLS), _row_dict(e, ENTRY_COLS)

    def entries(self, case_id):
        q = select(m.ExceptionCaseEntryRow).where(m.ExceptionCaseEntryRow.case_id == case_id).order_by(m.ExceptionCaseEntryRow.seq)
        with self.sessions() as s:
            return [_row_dict(r, ENTRY_COLS) for r in s.scalars(q)]


class SqlRepositories:
    """All repositories over one database (the application-state store of record when UC042_DATABASE_URL is set)."""

    def __init__(self, sessions):
        self.sessions = sessions
        self.cases = SqlCaseRepository(sessions)
        self.authorizations = SqlAuthorizationRepository(sessions)
        self.ai_authorizations = SqlAiAuthorizationRepository(sessions)
        self.lineage = SqlLineageRepository(sessions)
        self.jobs = SqlJobRepository(sessions)
        self.reviews = SqlReviewRepository(sessions)
        self.final_packs = SqlFinalPackRecordRepository(sessions)
        self.registry = SqlRegistryRepository(sessions)
        self.activity = SqlActivityRepository(sessions)
        self.periods = SqlPeriodRepository(sessions)
        self.uploads = SqlUploadRepository(sessions)
        self.runs = SqlProcessingRunRepository(sessions)
