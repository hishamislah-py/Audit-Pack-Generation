"""Phase 3B-3 - deterministic reprocessing of an original upload with the approved rules. No LLM is involved.

Steps: load the original bytes from the evidence store -> verify their SHA-256 -> verify the intake identity (the upload
event) -> establish the category (deterministically, or from a recorded human confirmation for exactly this upload) ->
load the governed rules (registry-bound, active only; a file mapping only for this intake + SHA-256) -> run the normal
pipeline (controlled_map, normalisation, validation, content check). The proposal mechanism is never called.

Reprocessing is repeatable: same bytes + same active rule versions -> same mapping and validation outcome.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..intake.store import EvidenceStore
from ..mapping.controlled import MappingRules
from ..models.enums import ClassificationStatus
from ..models.results import EvidenceResult
from ..pipeline import SmartParser


class ReprocessError(ValueError):
    pass


@dataclass
class ReprocessResult:
    result: EvidenceResult
    source_bytes: bytes
    original_intake_id: str
    source_sha256: str
    original_filename: str
    category: str | None
    category_basis: str                  # "deterministic" | "confirmed:<confirmation_id>"
    confirmation_id: str | None
    rules: MappingRules
    rules_used: list[dict] = field(default_factory=list)
    provider_calls: int = 0              # always 0: no proposer exists on this path


def reprocess(intake_id: str, evidence: EvidenceStore, registry, rules: MappingRules,
              confirmation=None, reporting_period: str | None = None) -> ReprocessResult:
    rec = evidence.find(intake_id)
    if rec is None:
        raise ReprocessError(f"unknown intake {intake_id}")
    data = evidence.read_original(rec.sha256)
    if data is None:
        raise ReprocessError(f"original bytes of intake {intake_id} are not stored")
    if hashlib.sha256(data).hexdigest() != rec.sha256:
        raise ReprocessError(f"stored original of intake {intake_id} does not match its SHA-256")
    forced, basis, conf_id = None, "deterministic", None
    if confirmation is not None:
        if (confirmation.intake_id, confirmation.source_sha256) != (intake_id, rec.sha256):
            raise ReprocessError("the category confirmation belongs to a different upload")
        forced, basis, conf_id = confirmation.category, f"confirmed:{confirmation.confirmation_id}", \
            confirmation.confirmation_id
    file_rules = rules.with_file_identity(intake_id, rec.sha256)
    # In-memory store: reprocessing is not a new upload and must not add intake records.
    parser = SmartParser(schemas=registry, store=EvidenceStore(None), mapping_rules=file_rules)
    res = parser.process_bytes(data, rec.original_filename, reporting_period or rec.reporting_period,
                               forced_category=forced)
    if forced is None and res.metadata.classification_status != ClassificationStatus.IDENTIFIED:
        raise ReprocessError("the category is neither identified deterministically nor confirmed by a person: "
                             + (res.classification.reason if res.classification else "not classified"))
    used = sorted({(m.variation, m.rule_id, m.rule_version) for m in (res.mapping.mappings if res.mapping else [])
                   if m.rule_id} | {("file_mapping", x["rule_id"], x["rule_version"])
                                   for x in (res.mapping.ignored_columns if res.mapping else [])},
                  key=lambda x: (x[1], x[2] or 0))
    return ReprocessResult(result=res, source_bytes=data, original_intake_id=intake_id, source_sha256=rec.sha256,
                           original_filename=rec.original_filename, category=res.metadata.evidence_category,
                           category_basis=basis, confirmation_id=conf_id, rules=file_rules,
                           rules_used=[{"kind": k, "rule_id": i, "rule_version": v} for k, i, v in used])
