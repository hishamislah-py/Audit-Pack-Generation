"""Persistence interfaces for application state. Services depend only on these. This POC implements them with files
(files.py); a later phase can implement the same interfaces with a database without changing services or API contracts.
Records are plain JSON-compatible dicts.

Controlled artefacts (packs/, investigations/, final_packs/) are NOT application state: they stay files, read and written
only through the libraries.
"""
from abc import ABC, abstractmethod


class ConcurrentUpdate(Exception):
    """The record changed since it was read (optimistic concurrency)."""


class DuplicateRecord(Exception):
    """A record with the same unique key already exists."""


class JobRepository(ABC):
    @abstractmethod
    def create(self, job): ...

    @abstractmethod
    def get(self, job_id): ...

    @abstractmethod
    def update(self, job_id, changes): """Merge changes and return the updated job."""

    @abstractmethod
    def list(self, pack_id=None, exception_id=None, statuses=None): ...


class ReviewRepository(ABC):
    @abstractmethod
    def create(self, session): ...

    @abstractmethod
    def get(self, review_id): ...

    @abstractmethod
    def save(self, session, expected_revision):
        """Store the session if its stored revision equals expected_revision (else ConcurrentUpdate); returns it with
        revision + 1."""

    @abstractmethod
    def list(self, pack_id=None): ...

    @abstractmethod
    def append_decision(self, review_id, decision): """Append-only: decisions are never edited or deleted."""

    @abstractmethod
    def decisions(self, review_id): ...

    @abstractmethod
    def save_preview(self, review_id, preview_id, meta, document): """Write-once."""

    @abstractmethod
    def get_preview(self, review_id, preview_id): """(meta, document) or (None, None)."""


class FinalPackRecordRepository(ABC):
    """One row per GENERATE decision: GENERATING -> GENERATED | GENERATION_FAILED."""

    @abstractmethod
    def create(self, record): """DuplicateRecord if the decision already has a record."""

    @abstractmethod
    def get(self, decision_id): ...

    @abstractmethod
    def update(self, decision_id, changes): ...

    @abstractmethod
    def list(self, pack_id=None): ...


class RegistryRepository(ABC):
    """The investigation publication registry: an ordered list of entries, only ever appended to."""

    @abstractmethod
    def append(self, entry): ...

    @abstractmethod
    def entries(self): ...

    @abstractmethod
    def signature(self): """An opaque value that changes whenever the registry changes."""


# ---------------------------------------------------------------------------------------------- database-only (monthly
# document management). These have SQL implementations only (uc042app/db/repositories.py): PostgreSQL in operation,
# SQLite for offline tests. Records are JSON-compatible dicts with ISO timestamps.
class ActivityRepository(ABC):
    @abstractmethod
    def append(self, event): ...

    @abstractmethod
    def recent(self, limit=50, entity_type=None, entity_id=None): ...


class PeriodRepository(ABC):
    @abstractmethod
    def get(self, period_id): ...

    @abstractmethod
    def list(self): ...

    @abstractmethod
    def ensure(self, period_id, year, month, status="EMPTY", title=""): """Create the period if missing (title only on creation); return it."""

    @abstractmethod
    def update(self, period_id, changes): ...

    @abstractmethod
    def packs(self, period_id=None): ...

    @abstractmethod
    def add_pack(self, record): """Register a pack reference (idempotent on period_id + pack_id)."""


class UploadRepository(ABC):
    @abstractmethod
    def create_batch(self, batch, documents): """Insert a batch and its documents in one transaction."""

    @abstractmethod
    def batch(self, batch_id): ...

    @abstractmethod
    def batches(self, period_id): ...

    @abstractmethod
    def update_batch(self, batch_id, changes): ...

    @abstractmethod
    def documents(self, batch_id=None, period_id=None): ...

    @abstractmethod
    def document(self, document_id): ...

    @abstractmethod
    def update_document(self, document_id, changes): ...

    @abstractmethod
    def find_documents(self, sha256=None, original_filename=None, period_id=None): ...


class ProcessingRunRepository(ABC):
    @abstractmethod
    def create(self, run): ...

    @abstractmethod
    def get(self, run_id): ...

    @abstractmethod
    def update(self, run_id, changes): ...

    @abstractmethod
    def list(self, period_id=None, batch_id=None): ...


class AuthorizationRepository(ABC):
    @abstractmethod
    def record(self, investigation_id, status, basis, recorded_by): """Append an authorisation decision; return it."""

    @abstractmethod
    def current(self, investigation_id): """The decision in force (the latest), or None."""

    @abstractmethod
    def list(self): ...


class AiAuthorizationRepository(ABC):
    """Pre-execution AI authorisations: append-only and immutable (there is no update or delete)."""
    @abstractmethod
    def record(self, rec): """Append one authorisation record; return it (with its database id)."""

    @abstractmethod
    def get(self, authorization_id): ...

    @abstractmethod
    def list(self, pack_id=None, exception_id=None, review_id=None, job_id=None, period_id=None): """Oldest first."""


class InvestigationReviewRepository(ABC):
    """The analyst's ACCEPT / REJECT decisions on published investigations: append-only and immutable. Each investigation's
    decisions are numbered by revision 1, 2, ...; the latest is the active decision."""
    @abstractmethod
    def append(self, rec, expected_revision):
        """Store rec as revision expected_revision + 1, only if the investigation's latest stored revision is
        expected_revision (0 = no decision yet); ConcurrentUpdate otherwise. Returns the stored record."""

    @abstractmethod
    def list(self, pack_id=None, exception_id=None, investigation_id=None): """Oldest first."""


class LineageRepository(ABC):
    """Reassessment lineage of deterministic packs (one row per reassessed pack; written once)."""
    @abstractmethod
    def add(self, row): ...

    @abstractmethod
    def get(self, pack_id): """The pack's lineage row, or None (the pack is its own lineage root)."""

    @abstractmethod
    def list(self, period_id=None, lineage_root_pack_id=None): ...


class CaseRepository(ABC):
    @abstractmethod
    def create(self, case): """Insert a new case; DuplicateRecord if the pack's exception already has one."""

    @abstractmethod
    def get(self, case_id): ...

    @abstractmethod
    def find(self, pack_id, exception_id): ...

    @abstractmethod
    def list(self, period_id=None, pack_id=None): ...

    @abstractmethod
    def append_entry(self, case_id, entry, expected_revision, changes=None):
        """In one transaction: insert the entry with the next seq and apply changes to the case, only if the case is
        still at expected_revision (ConcurrentUpdate otherwise). Returns (case, entry)."""

    @abstractmethod
    def entries(self, case_id): ...
