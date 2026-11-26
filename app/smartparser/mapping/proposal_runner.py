"""Phase 3B-1 - the proposal execution boundary.

`run_proposal(result, registry, proposer)` is a SEPARATE step after the normal pipeline. It never changes the
EvidenceResult it is given, and it calls the proposer only when all of these hold:
  1. the file is a CSV that the deterministic pipeline did NOT map (not identified + complete);
  2. a category was explicitly supplied (process_bytes(forced_category=...)) - proposals never decide a category;
  3. that category is a UC-042 controlled category;
  4. the controlled rules leave at least one source column unresolved.
Otherwise it returns a clear not-eligible reason and the proposer is not called.

What the proposer receives: the confirmed category's field context, the columns the rules already resolved, and for each
unresolved column its (sanitised) header and character-class value SHAPES (e.g. '9.9', 'A-9'). Never cell values, never
rows. Sample values stay local and are used only to check proposed fields against UC-042 value rules.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError

from ..models.enums import ClassificationStatus, MappingStatus
from ..models.results import EvidenceResult
from ..schemas.registry import SchemaRegistry
from .controlled import MappingRules, controlled_map, is_controlled
from .proposals import (
    ColumnAssessment, Diagnostic, FieldContext, ProposalRecord, ProposalRequest, ProposalResponse, ProposalStatus,
    ProposalSummary, ResolvedColumn, UnresolvedColumn, ValidationClass, _sanitise, validate_proposal,
)

MAX_SHAPES = 3


@dataclass
class ProposalOutcome:
    eligible: bool
    reason: str
    proposer_called: bool = False
    request: ProposalRequest | None = None
    record: ProposalRecord | None = None
    details: dict = field(default_factory=dict)
    # Phase 3B-4 gateway metadata
    manual_review_required: bool = False
    deduplicated: bool = False
    gate_reasons: list = field(default_factory=list)


def value_shape(v: str) -> str:
    """Character-class shape of a value: digit runs -> 9, upper-case runs -> A, lower-case runs -> a."""
    s = re.sub(r"[0-9]+", "9", v)
    s = re.sub(r"[A-Z]+", "A", s)
    return re.sub(r"[a-z]+", "a", s)[:24]


def _default_rules(registry):
    from ..classify.csv_classifier import default_rules   # local import: avoid a classify <-> mapping cycle
    return default_rules(registry)


def eligibility(result: EvidenceResult, registry: SchemaRegistry):
    """(eligible, reason, schema)."""
    m = result.metadata
    if m.file_format != "csv" or result.csv_extraction is None:
        return False, "not a CSV with a readable header", None
    if m.classification_status == ClassificationStatus.IDENTIFIED and m.mapping_status == MappingStatus.COMPLETE:
        return False, "already mapped by the deterministic rules; proposals are never generated for mapped files", None
    cls = result.classification
    forced = (cls.details or {}).get("forced_category") if cls else None
    if not forced:
        return False, ("category not confirmed: proposals need a category supplied by a caller or reviewer "
                       "(forced_category); they never decide the category"), None
    schema = registry.get(forced)
    if not is_controlled(schema):
        return False, f"{forced} is not a UC-042 CSV category under controlled mapping", None
    by_content = (cls.details or {}).get("content_classification") or {}
    if by_content.get("category") and by_content["category"] != forced:
        return False, (f"the supplied category {forced} conflicts with the content, which identifies as "
                       f"{by_content['category']}; the category must be resolved by a person before any column "
                       "proposal"), None
    return True, "", schema


def build_request(result: EvidenceResult, schema, rules: MappingRules):
    raw = list(result.csv_extraction.raw_headers)
    cm = controlled_map(raw, schema, rules)
    mapped_pos = {x["source_position"] for x in cm.mappings}
    conflicts = cm.duplicate_fields
    resolved = [ResolvedColumn(source_index=x["source_position"], source_header=_sanitise(x["source_header"]),
                               canonical_field=x["canonical_field"])
                for x in cm.mappings if x["canonical_field"] not in conflicts]
    samples = {c.index: list(c.sample_values) for c in result.csv_extraction.columns}
    unresolved = []
    for i, h in enumerate(raw):
        if i in mapped_pos:
            continue
        shapes = list(dict.fromkeys(value_shape(v) for v in samples.get(i, [])))[:MAX_SHAPES]
        reason = "ambiguous under the controlled rules" if h in cm.ambiguous_columns else \
            f"not a canonical {schema.category} column or approved alias"
        unresolved.append(UnresolvedColumn(source_index=i, source_header=_sanitise(h), value_shapes=shapes,
                                           reason=reason))
    req = ProposalRequest(
        request_id=str(uuid.uuid4()), intake_id=result.metadata.evidence_id, source_sha256=result.metadata.sha256,
        category=schema.category, category_name=schema.official_name or schema.title,
        canonical_fields=[FieldContext(name=f.name, source_type=f.source_type, requiredness=f.requiredness,
                                       description=f.description, allowed_values=f.constraints.allowed_values)
                          for f in schema.fields],
        resolved_columns=resolved, unresolved_columns=unresolved, missing_required_fields=cm.missing_fields,
        deterministic_conflicts=conflicts)
    return req, raw, samples, cm


def run_proposal(result: EvidenceResult, registry: SchemaRegistry, proposer,
                 rules: MappingRules | None = None, revision_of: str | None = None) -> ProposalOutcome:
    ok, reason, schema = eligibility(result, registry)
    if not ok:
        return ProposalOutcome(eligible=False, reason=reason)
    rules = rules or _default_rules(registry)
    req, raw, samples, cm = build_request(result, schema, rules)
    if not req.unresolved_columns:
        return ProposalOutcome(eligible=False, request=req, reason=(
            "no unresolved source column: the controlled rules map every column; the remaining problems "
            f"({'; '.join(cm.rejections)}) cannot be solved by a column proposal"))
    record_base = dict(
        proposal_id=str(uuid.uuid4()), request_id=req.request_id, intake_id=req.intake_id,
        source_sha256=req.source_sha256, original_filename=result.metadata.original_filename,
        confirmed_category=schema.category, category_source="supplied",
        registry_definition_sha256=hashlib.sha256(schema.model_dump_json().encode()).hexdigest(),
        mapping_rules=rules.source, provider_id=getattr(proposer, "provider_id", type(proposer).__name__),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), revision_of=revision_of)
    try:
        text = proposer.propose(req)
    except Exception as exc:   # provider failures never affect the deterministic result
        return _failed(req, raw, record_base, None, f"PROVIDER_ERROR: {type(exc).__name__}: {exc}", proposer_called=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(text, str) else None
    try:
        response = ProposalResponse.model_validate(json.loads(text))
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        return _failed(req, raw, record_base, digest, f"MALFORMED_RESPONSE: {type(exc).__name__}: "
                                                      f"{str(exc).splitlines()[0][:300]}", proposer_called=True)
    cols, summary = validate_proposal(req, schema, response, raw, samples)
    record = ProposalRecord(**record_base, response_sha256=digest, columns=cols, summary=summary)
    return ProposalOutcome(eligible=True, reason="proposal generated and validated (advisory only)",
                           proposer_called=True, request=req, record=record)


def _failed(req, raw, base, digest, error, proposer_called) -> ProposalOutcome:
    cols = [ColumnAssessment(source_index=u.source_index, source_header=raw[u.source_index], proposed_field=None,
                             proposer_assessment=None, status=ProposalStatus.REJECTED,
                             validation_class=ValidationClass.NO_MATCH,
                             diagnostics=[Diagnostic(code="RESPONSE_INVALID", message=error)])
            for u in req.unresolved_columns]
    summary = ProposalSummary(overall="REJECTED", class_counts={k.value: (len(cols) if k == ValidationClass.NO_MATCH
                                                                          else 0) for k in ValidationClass},
                              required_fields_unresolved=req.missing_required_fields, reasons=[error])
    record = ProposalRecord(**base, response_sha256=digest, response_error=error, columns=cols, summary=summary)
    return ProposalOutcome(eligible=True, reason=error, proposer_called=proposer_called, request=req, record=record)
