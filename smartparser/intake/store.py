"""Module A - upload intake and original-evidence preservation.

Originals are stored content-addressed by SHA-256 and never overwritten or
modified. The original filename is metadata only - it is never used as a path,
which removes path-traversal risk, and never used to decide the category.

ZIP extraction and multi-file batches are Phase 4.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..models.results import utcnow

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_reporting_period(period: str | None) -> str | None:
    if period is None:
        return None
    if not _PERIOD.match(period):
        raise ValueError(f"reporting_period must be YYYY-MM, got {period!r}")
    return period


def display_filename(name: str) -> str:
    """Strip any directory components a client may have sent; keep the rest verbatim."""
    return re.split(r"[\\/]", name)[-1] or "unnamed"


@dataclass
class IntakeRecord:
    evidence_id: str
    sha256: str
    size_bytes: int
    original_filename: str
    reporting_period: str | None
    stored_path: str | None
    received_at: str
    upload_id: str | None = None


@dataclass
class DuplicateCheck:
    same_period: list[IntakeRecord] = field(default_factory=list)
    other_periods: list[IntakeRecord] = field(default_factory=list)


class EvidenceStore:
    """Stores originals under ``root/originals`` and keeps a JSON index.

    ``root=None`` gives an in-memory store (no files written) - useful for tests
    and for one-off CLI runs.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else None
        self._lock = threading.Lock()
        self._index: list[IntakeRecord] = []
        if self.root:
            (self.root / "originals").mkdir(parents=True, exist_ok=True)
            self._reload()

    def _reload(self) -> None:
        """Phase 3B-8: the on-disk index is the source of truth. Re-read it before every read and before every append,
        so two store instances (or two orchestrators) on the same root never overwrite each other's intake records
        (previously each instance kept a stale private copy and the last writer silently dropped the other's records)."""
        if self.root:
            idx = self.root / "index.json"
            self._index = [IntakeRecord(**r) for r in json.loads(idx.read_text("utf-8"))] if idx.exists() else []

    def check_duplicate(self, sha256: str, reporting_period: str | None) -> DuplicateCheck:
        self._reload()
        dc = DuplicateCheck()
        for r in self._index:
            if r.sha256 == sha256:
                (dc.same_period if r.reporting_period == reporting_period else dc.other_periods).append(r)
        return dc

    def save(self, data: bytes, original_filename: str, reporting_period: str | None,
             upload_id: str | None = None) -> IntakeRecord:
        digest = sha256_bytes(data)
        stored_path = None
        with self._lock:
            if self.root:
                target = self.root / "originals" / digest[:2] / digest
                if not target.exists():           # content-addressed: never overwrite
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(target)
                stored_path = str(target)
            rec = IntakeRecord(
                evidence_id=str(uuid.uuid4()), sha256=digest, size_bytes=len(data),
                original_filename=display_filename(original_filename),
                reporting_period=reporting_period, stored_path=stored_path,
                received_at=utcnow().isoformat(), upload_id=upload_id,
            )
            self._reload()                        # 3B-8: append to the CURRENT on-disk index, never a stale copy
            self._index.append(rec)
            if self.root:
                idx = self.root / "index.json"
                tmp = idx.with_suffix(".tmp")         # 3B-8: atomic replace - a crash never leaves a truncated index
                tmp.write_text(json.dumps([r.__dict__ for r in self._index], indent=2), "utf-8")
                tmp.replace(idx)
        return rec

    def find(self, evidence_id: str) -> IntakeRecord | None:
        """The intake record of one upload event (Phase 3B-3: reprocessing verifies the intake identity)."""
        self._reload()
        return next((r for r in self._index if r.evidence_id == evidence_id), None)

    def read_original(self, sha256: str) -> bytes | None:
        if not self.root:
            return None
        p = self.root / "originals" / sha256[:2] / sha256
        return p.read_bytes() if p.exists() else None
