"""Phase 3B-2 - append-only JSONL audit log with a hash chain.

Every event is validated against a strict schema before it is written. Events are only ever appended (the file is
opened in append mode); each event carries the SHA-256 of the previous event, so any edit, deletion or reordering of
history is detected by `verify()`. Timestamps come from an injectable clock, so tests are deterministic.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_TYPES = Literal[
    "PROPOSAL_REVIEW_OPENED", "COLUMN_DECIDED", "PROPOSAL_APPROVED", "PROPOSAL_REJECTED", "REVISION_REQUESTED",
    "REVISION_CREATED", "RULE_CREATED", "RULE_ACTIVATED", "RULE_REVOKED", "RULE_SUPERSEDED", "CATEGORY_CONFIRMED",
    "PROVIDER_CALL", "PROPOSAL_DEDUPLICATED", "REPROCESSED", "HANDOFF_EVALUATED", "HANDOFF_PREVIEW_WRITTEN",
    "POC_AUTO_DECISION", "INTAKE_CASE_OPENED", "INTAKE_DECISION", "INTAKE_CASE_RESOLVED", "INTAKE_CASE_HELD",
    "INTAKE_CASE_REJECTED",
    # Phase 3B-9 evidence-package lifecycle (identifiers in `details`: package_id, file_version_id,
    # previous_file_version_id, snapshot_id, evidence_category, reporting_period, reason / outcome)
    "PACKAGE_CREATED", "PACKAGE_FILE_RECEIVED", "FILE_VERSION_CREATED", "FILE_VERSION_VALIDATED",
    "FILE_VERSION_REJECTED", "RESUBMISSION_REQUESTED", "RESUBMISSION_RECEIVED", "FILE_VERSION_REVIEW_REQUIRED",
    "FILE_VERSION_SUPERSEDED", "FILE_VERSION_ACTIVATED", "PACKAGE_VALIDATION_STARTED", "PACKAGE_VALIDATION_FAILED",
    "PACKAGE_VALIDATED", "PACKAGE_SNAPSHOT_CREATED", "PACKAGE_SNAPSHOT_ACTIVATED",
    # Phase 3B-11 reconciliation adapter (the UC-042 engine itself is unchanged)
    "RECONCILIATION_INPUT_STAGED", "RECONCILIATION_EXECUTED", "RECONCILIATION_FAILED",
    # Ringfence case workflow (additive; webapp/cases.py). Case lifecycle and analyst-initiated actions, recorded with
    # the analyst as actor immediately before the existing service call.
    "CASE_CREATED", "CASE_STARTED", "CASE_RUN_STARTED", "CASE_RUN_FAILED", "CASE_RETRY_REQUESTED",
    "CASE_DEFERRAL_REQUESTED", "CASE_DEFERRED", "CASE_RESUMED", "CASE_COMPLETED",
    "ANALYST_EVIDENCE_UPLOADED", "ANALYST_REVIEW_CONFIRMED", "ANALYST_CORRECTION_REQUESTED",
    "ANALYST_VALIDATION_REQUESTED", "ANALYST_ACTIVATION_REQUESTED", "ANALYST_RECONCILIATION_REQUESTED",
    # DEF-SV-02: a failed review completion is compensated (review state restored, its new rule revoked)
    "REVIEW_COMPLETION_ROLLED_BACK",
    # Ringfence closure (webapp/closure.py): audit pack, AI authorisations and investigations, analyst decisions on AI
    # findings, the closing review and the final audit pack. Actor = the signed-in user; system_reviewer_id in details.
    "AUDIT_PACK_GENERATED", "AUDIT_PACK_UNAVAILABLE",
    "AI_AUTHORIZED", "AI_AUTHORIZATION_REFUSED",
    "AI_INVESTIGATION_QUEUED", "AI_INVESTIGATION_PUBLISHED", "AI_INVESTIGATION_NOT_PUBLISHED", "AI_INVESTIGATION_FAILED",
    "ANALYST_INVESTIGATION_ACCEPTED", "ANALYST_INVESTIGATION_REJECTED",
    "CLOSING_REVIEW_OPENED", "CLOSING_SELECTIONS_CHANGED", "CLOSING_PREVIEW_REQUESTED", "CLOSING_PREVIEW_READY",
    "CLOSING_PREVIEW_FAILED", "CLOSING_REVIEW_HELD",
    "FINAL_PACK_GENERATED", "FINAL_PACK_GENERATION_FAILED",
    # Fix8 (22 Nov 2026, lead-registered so no agent edits this allowlist):
    # D2 - a refused/failed file confirmation is recorded as such (never as ANALYST_REVIEW_CONFIRMED)
    "ANALYST_REVIEW_CONFIRMATION_FAILED",
    # D4 - an analyst's explicit clarification of an ambiguous financial mapping
    "ANALYST_MAPPING_CLARIFIED",
    # D7 - a restricted action refused for lack of authorisation, and an audited supervisor override
    "ACCESS_DENIED", "SUPERVISOR_OVERRIDE",
]
GENESIS = "0" * 64


class AuditError(ValueError):
    pass


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int = Field(ge=1)
    event_id: str
    event_type: EVENT_TYPES
    at: str
    actor_id: str | None = None
    actor_role: str | None = None
    approval_kind: Literal["TEST", "BUSINESS", "POC_AUTO"] | None = None
    proposal_id: str | None = None
    session_id: str | None = None
    rule_id: str | None = None
    intake_id: str | None = None
    source_sha256: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _append_lock(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class AuditLog:
    def __init__(self, path: str | Path, clock: Callable[[], str] = utc_now):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def events(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                out.append(AuditEvent.model_validate_json(line))
            except Exception as exc:
                raise AuditError(f"{self.path.name} line {n}: malformed audit record ({exc})") from exc
        return out

    def verify(self) -> int:
        """Check the schema, sequence and hash chain of the whole log. Returns the number of events."""
        prev = GENESIS
        events = self.events()
        for i, e in enumerate(events, start=1):
            body = e.model_dump()
            stored = body.pop("hash")
            if e.seq != i:
                raise AuditError(f"event {e.event_id}: sequence {e.seq}, expected {i}")
            if e.prev_hash != prev:
                raise AuditError(f"event {e.event_id}: broken chain (history changed)")
            if _digest(body) != stored:
                raise AuditError(f"event {e.event_id}: content does not match its hash")
            prev = stored
        return len(events)

    def append(self, event_type: str, **fields) -> AuditEvent:
        with _append_lock(self.path):                  # sequence + hash chain: one appender at a time per log file
            return self._append(event_type, **fields)

    def _append(self, event_type: str, **fields) -> AuditEvent:
        events = self.events()
        prev = events[-1].hash if events else GENESIS
        body = {"seq": len(events) + 1, "event_id": str(uuid.uuid4()), "event_type": event_type, "at": self.clock(),
                "prev_hash": prev, **{k: v for k, v in fields.items()}}
        body.setdefault("details", {})
        candidate = AuditEvent.model_validate({**body, "hash": GENESIS})   # schema check before writing
        payload = candidate.model_dump()
        payload.pop("hash")
        event = AuditEvent.model_validate({**payload, "hash": _digest(payload)})
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:   # append only, never rewritten
            f.write(event.model_dump_json() + "\n")
        return event
