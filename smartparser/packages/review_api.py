"""Phase 3B-11 - the analyst mapping-review VIEW and ACTION layer used by the POC review screen.

This module only READS package / version / review state and FORWARDS analyst actions to the existing PackageService
methods (which call the existing review.intake / review.session functions with their authority checks and every
deterministic rule: DUPLICATE_TARGET, VALUE_INCOMPATIBLE, RULE_CONTRADICTION, required-field coverage, ...). It contains
no mapping, validation or lifecycle logic of its own: everything it returns is computed from stored state.

Two review mechanisms exist and both are presented in one table:
  * a column-review case (header-count mismatch, deterministic conflict, UNMAPPABLE proposal) - actions MAP, CHANGE,
    CHOOSE_DUPLICATE_SOURCE, IGNORE_COLUMN, LEAVE_UNRESOLVED; REJECT; complete;
  * a proposal review session (AMBIGUOUS / PLAUSIBLE proposals) - actions MAP (= confirm the proposal), CHANGE,
    LEAVE_UNRESOLVED (= leave unmapped); REJECT; complete (= approve + complete). IGNORE_COLUMN and
    CHOOSE_DUPLICATE_SOURCE do not exist in a proposal session and are not offered.
"""
from __future__ import annotations

from ..review.authority import AuthorityError
from ..review.session import ReviewError
from .service import PackageError, PackageService
from .store import PackageStoreError

CASE_ACTIONS = ["MAP", "CHANGE", "CHOOSE_DUPLICATE_SOURCE", "IGNORE_COLUMN", "LEAVE_UNRESOLVED"]
SESSION_ACTIONS = ["MAP", "CHANGE", "LEAVE_UNRESOLVED"]
SESSION_ACTION = {"MAP": "APPROVE", "CHANGE": "CHANGE", "LEAVE_UNRESOLVED": "LEAVE_UNMAPPED"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def translate(exc: Exception) -> ApiError:
    msg = str(exc)
    head = msg.split(":", 1)[0].strip()
    code = head if head.replace("_", "").isalpha() and head.isupper() else None
    if isinstance(exc, AuthorityError):
        return ApiError(403, "NOT_AUTHORISED", msg)
    if isinstance(exc, ReviewError):
        return ApiError(400, code or "REVIEW_RULE", msg)
    if isinstance(exc, PackageStoreError):
        return ApiError(404, "NOT_FOUND", msg)
    if isinstance(exc, PackageError):
        return ApiError(409, "PACKAGE_STATE", msg)
    if isinstance(exc, ValueError):
        return ApiError(400, code or "INVALID", msg)
    return ApiError(500, "INTERNAL", type(exc).__name__)


# ================================================================================================ queue
def list_reviews(svc: PackageService) -> list[dict]:
    out = []
    for pid in svc.store.list():
        pkg = svc.store.load(pid)
        for v in pkg.versions.values():
            if v.version_status != "REVIEW_REQUIRED":
                continue
            dups, extra, missing = {}, [], []
            if v.review_case_id:
                case = svc.store.load_case(pid, v.review_case_id)
                kind, incoming = case.kind, case.incoming_header_count
                dups = {h: [p + 1 for p in ps] for h, ps in case.duplicate_incoming_headers.items()}   # 1-based
                extra = [x["source_header"] for x in case.extra_headers_diagnostic]
                missing = list(case.missing_fields_diagnostic)
            elif v.review_session_id:
                s, _ = svc.store.load_session(pid, v.review_session_id)
                kind, incoming = "PROPOSAL_REVIEW", len(s.headers)
            else:
                kind, incoming = None, None
            out.append({"package_id": pid, "reporting_period": pkg.reporting_period, "file_version_id": v.file_version_id,
                        "evidence_category": v.evidence_category, "original_filename": v.original_filename,
                        "version_number": v.version_number, "uploaded_at": v.uploaded_at, "review_kind": kind,
                        "incoming_header_count": incoming,
                        "expected_field_count": len(svc.reg.get(v.evidence_category).fields),
                        "review_reason": (v.reasons or [""])[0],
                        # diagnosis visible in the queue (additive; 1-based column positions)
                        "duplicate_headers": dups, "extra_headers": extra, "missing_fields": missing})
    return sorted(out, key=lambda r: (r["uploaded_at"], r["file_version_id"]))


# ================================================================================================ detail
def _fields(svc, category):
    return [{"name": f.name, "requiredness": f.requiredness, "required": bool(f.required or f.requiredness == "M"),
             "type": f.source_type} for f in svc.reg.get(category).fields]


def review_detail(svc: PackageService, package_id: str, file_version_id: str) -> dict:
    pkg = svc.store.load(package_id)
    v = pkg.versions.get(file_version_id)
    if v is None:
        raise ApiError(404, "NOT_FOUND", f"unknown file version {file_version_id}")
    fields = _fields(svc, v.evidence_category)
    required = {f["name"] for f in fields if f["required"]}
    d = {"package_id": package_id, "reporting_period": pkg.reporting_period, "package_status": pkg.package_status,
         "evidence_category": v.evidence_category, "category_title": svc.reg.get(v.evidence_category).title,
         "file_version_id": v.file_version_id, "version_number": v.version_number, "version_status": v.version_status,
         "original_filename": v.original_filename, "intake_id": v.intake_id, "source_sha256": v.source_sha256,
         "source_sha256_short": v.source_sha256[:12], "canonical_fields": fields,
         "expected_field_count": len(fields), "editable": v.version_status == "REVIEW_REQUIRED",
         "review_reason": (v.reasons or [""])[0], "processing_status": v.processing_status}
    if v.review_case_id:
        case = svc.store.load_case(package_id, v.review_case_id)
        eff = case.effective()
        claims = {i: f for f, ps in case.potential_duplicate_claims.items() for i in ps}
        rows = []
        for c in case.columns:
            dec = eff.get(c.source_index)
            rows.append({"source_index": c.source_index, "source_position": c.source_index + 1,
                         "source_header": c.source_header, "suggested_field": c.suggested_field,
                         "suggestion_basis": c.suggestion_basis, "proposal_field": c.proposal_field,
                         "proposal_assessment": c.proposal_assessment,
                         "validation": c.validation_class or ("DETERMINISTIC" if c.suggestion_basis in
                                                              ("deterministic", "diagnostic_name_match") else
                                                              "NO_SUGGESTION"),
                         "note": c.proposal_note, "same_header_positions": c.same_header_positions,
                         "duplicate_claim": claims.get(c.source_index),
                         "decision": None if dec is None else {"action": dec.action, "canonical_field": dec.canonical_field,
                                                               "reason": dec.reason, "reviewer": dec.reviewer_id,
                                                               "at": dec.decided_at, "group_id": dec.group_id}})
        mapped = case.mapped()
        d.update(mechanism="column_review_case", review_kind=case.kind, review_state=str(case.state),
                 review_id=case.case_id, incoming_header_count=case.incoming_header_count,
                 review_reason=case.review_reason or d["review_reason"], actions=CASE_ACTIONS, rows=rows,
                 missing_fields_diagnostic=case.missing_fields_diagnostic,
                 extra_headers_diagnostic=case.extra_headers_diagnostic,
                 duplicate_incoming_headers=case.duplicate_incoming_headers,
                 potential_duplicate_claims=case.potential_duplicate_claims,
                 summary={"decided": len(eff), "outstanding": [r["source_index"] for r in rows if r["decision"] is None],
                          "required_not_covered": sorted(required - set(mapped.values())),
                          "ignored": [{"source_index": i, "reason": x.reason} for i, x in sorted(eff.items())
                                      if x.action == "IGNORE_COLUMN"],
                          "unresolved": sorted(i for i, x in eff.items() if x.action == "LEAVE_UNRESOLVED"),
                          "content_classification": case.content_classification,
                          "final_summary": case.final_summary})
    elif v.review_session_id:
        s, req = svc.store.load_session(package_id, v.review_session_id)
        rows = [{"source_index": c["source_index"], "source_position": c["source_index"] + 1,
                 "source_header": s.headers[c["source_index"]], "suggested_field": c["canonical_field"],
                 "suggestion_basis": "deterministic", "proposal_field": None, "proposal_assessment": None,
                 "validation": "DETERMINISTIC", "note": "matched deterministically (not part of the review)",
                 "same_header_positions": [], "duplicate_claim": None, "read_only": True,
                 "decision": {"action": "DETERMINISTIC", "canonical_field": c["canonical_field"], "reason": "",
                              "reviewer": None, "at": None, "group_id": None}} for c in s.resolved_columns]
        for c in s.columns:
            dec = s.decisions.get(str(c.source_index))
            rows.append({"source_index": c.source_index, "source_position": c.source_index + 1,
                         "source_header": c.source_header, "suggested_field": c.proposed_field,
                         "suggestion_basis": "proposal", "proposal_field": c.proposed_field,
                         "proposal_assessment": c.proposer_assessment, "validation": str(c.validation_class),
                         "note": "; ".join(dg.message for dg in c.diagnostics) if c.diagnostics else None,
                         "same_header_positions": [], "duplicate_claim": None, "read_only": False,
                         "decision": None if dec is None else {"action": dec.action, "canonical_field": dec.final_field,
                                                               "reason": dec.basis, "reviewer": dec.reviewer_id,
                                                               "at": dec.decided_at, "group_id": None}})
        rows.sort(key=lambda r: r["source_index"])
        chosen = {r["decision"]["canonical_field"] for r in rows if r["decision"] and r["decision"]["canonical_field"]}
        d.update(mechanism="proposal_session", review_kind="PROPOSAL_REVIEW", review_state=str(s.state),
                 review_id=s.session_id, incoming_header_count=len(s.headers), actions=SESSION_ACTIONS, rows=rows,
                 missing_fields_diagnostic=[], extra_headers_diagnostic=[], duplicate_incoming_headers={},
                 potential_duplicate_claims={},
                 summary={"decided": len(s.decisions),
                          "outstanding": [r["source_index"] for r in rows if r["decision"] is None],
                          "required_not_covered": sorted(required - chosen), "ignored": [], "unresolved": sorted(
                              r["source_index"] for r in rows if r["decision"] and r["decision"]["action"] ==
                              "LEAVE_UNMAPPED"), "content_classification": None, "final_summary": s.final_summary})
    else:
        d.update(mechanism=None, review_kind=None, review_state=None, review_id=None, rows=[], actions=[],
                 incoming_header_count=None, summary={})
    d["outcome"] = outcome(svc, package_id, file_version_id)
    return d


def outcome(svc: PackageService, package_id: str, file_version_id: str) -> dict:
    pkg = svc.store.load(package_id)
    v = pkg.versions[file_version_id]
    h = v.handoff
    return {"version_status": v.version_status, "processing_status": v.processing_status,
            "reasons": v.reasons[-4:], "missing_fields": v.missing_fields,
            "reprocessed": h is not None and h.basis == "CSV_14_POINT_HANDOFF" and bool(h.checks),
            "handoff": None if h is None else {"eligible": h.eligible, "failed_checks": h.failed_checks,
                                               "checks": h.checks, "preview_csv": h.preview_csv,
                                               "provenance": h.provenance, "output_sha256": h.output_sha256},
            "preview_generated": bool(h and h.preview_csv),
            "eligible_for_package_activation": v.version_status == "VALIDATED",
            "mapping_rule_refs": v.mapping_rule_refs,
            "package_status": pkg.package_status, "pending_resubmissions": svc.pending_resubmissions(package_id)}


# ================================================================================================ actions
def decide(svc: PackageService, reviewer, package_id: str, file_version_id: str, action: str, source_index: int,
           reason: str, canonical_field: str | None = None, others_reason: str | None = None) -> dict:
    try:
        v = svc.store.load(package_id).versions[file_version_id]
        if not reason or not reason.strip():
            raise ReviewError("REASON_REQUIRED: every analyst decision needs a reason")
        if v.review_case_id:
            if action not in CASE_ACTIONS:
                raise ReviewError(f"UNSUPPORTED_ACTION: {action}")
            svc.decide(package_id, file_version_id, action, reviewer, reason, int(source_index), canonical_field or None,
                       others_reason or None)
        elif v.review_session_id:
            if action not in SESSION_ACTIONS:
                raise ReviewError(f"UNSUPPORTED_ACTION: {action} is not available in a proposal review")
            svc.review_session(package_id, file_version_id, reviewer, reason,
                               [(int(source_index), SESSION_ACTION[action],
                                 canonical_field if action == "CHANGE" else None)], approve=False)
        else:
            raise PackageError(f"{file_version_id} has no review")
    except ApiError:
        raise
    except Exception as exc:
        raise translate(exc) from None
    return review_detail(svc, package_id, file_version_id)


def reject(svc: PackageService, reviewer, package_id: str, file_version_id: str, reason: str) -> dict:
    try:
        if not reason or not reason.strip():
            raise ReviewError("REASON_REQUIRED: a rejection needs a reason")
        svc.reject_review(package_id, file_version_id, reviewer, reason)
    except Exception as exc:
        raise translate(exc) from None
    return review_detail(svc, package_id, file_version_id)


def complete(svc: PackageService, reviewer, package_id: str, file_version_id: str, basis: str) -> dict:
    try:
        if not basis or not basis.strip():
            raise ReviewError("REASON_REQUIRED: completing a review needs a basis")
        v = svc.store.load(package_id).versions[file_version_id]
    except Exception as exc:
        raise translate(exc) from None
    snap = _snapshot(svc, package_id, v)
    try:
        if v.review_session_id and not v.review_case_id:
            svc.review_session(package_id, file_version_id, reviewer, basis, [], approve=True)
        after = svc.complete_review(package_id, file_version_id, [reviewer], basis)
        if v.review_session_id and not v.review_case_id and after.version_status == "REVIEW_REQUIRED":
            # an approved but incomplete session writes nothing and would be stranded (APPROVED, never completable)
            raise ReviewError("SESSION_INCOMPLETE: the proposal review cannot be completed: "
                              + "; ".join(after.reasons[-1:]) + " - decide the remaining columns or reject the file")
    except Exception as exc:
        _rollback(svc, package_id, v, snap, reviewer, exc)
        raise translate(exc) from None
    return review_detail(svc, package_id, file_version_id)


# ------------------------------------------------------------------------------------------------ DEF-SV-02 (atomicity)
def _snapshot(svc: PackageService, package_id: str, v) -> dict:
    """Review state and active file-mapping rules before a completion attempt (to compensate a failed attempt)."""
    d = svc.store._dir(package_id)
    files = {}
    if v.review_session_id:
        p = d / "sessions" / f"{v.review_session_id}.json"
        files[p] = p.read_bytes() if p.is_file() else None
    if v.review_case_id:
        p = d / "cases" / f"{v.review_case_id}.json"
        files[p] = p.read_bytes() if p.is_file() else None
    rules = {(r["file_mapping_id"], int(r.get("rule_version", 1)))
             for r in svc.o.store.read("file_mappings").get("file_mappings", [])}
    return {"files": files, "rules": rules}


def _rollback(svc: PackageService, package_id: str, v, snap: dict, reviewer, exc: Exception) -> None:
    """A completion either finishes (version leaves REVIEW_REQUIRED) or leaves NO trace that blocks a retry: the session
    / case files are restored and any file mapping created for this upload by the failed attempt is revoked (recorded,
    never deleted). The audit trail keeps every event of the attempt plus REVIEW_COMPLETION_ROLLED_BACK."""
    now_v = svc.store.load(package_id).versions[v.file_version_id]
    if now_v.version_status != "REVIEW_REQUIRED":
        return                                              # the completion did take effect: nothing to undo
    from ..mapping.governed import Lifecycle
    restored = []
    for p, data in snap["files"].items():
        if data is not None and (not p.is_file() or p.read_bytes() != data):
            tmp = p.with_suffix(".rollback.tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
            restored.append(p.name)
    revoked = []
    for r in svc.o.store.read("file_mappings").get("file_mappings", []):
        key = (r["file_mapping_id"], int(r.get("rule_version", 1)))
        if key not in snap["rules"] and r.get("intake_id") == v.intake_id and                 (r.get("lifecycle") or {}).get("status", "active") == "active":
            svc.o.store.set_lifecycle("file_mappings", key[0], key[1], Lifecycle(
                status="revoked", revoked_at=svc.log.clock(), revoked_by="smartparser-completion-rollback",
                revoked_role="system", revocation_reason=f"review completion failed and was rolled back: {exc}"[:500]))
            revoked.append(key[0])
    if not restored and not revoked:
        return                                              # a refused precondition changed nothing
    svc.log.append("REVIEW_COMPLETION_ROLLED_BACK", actor_id=getattr(reviewer, "reviewer_id", None),
                   actor_role=getattr(reviewer, "role", None), intake_id=v.intake_id, source_sha256=v.source_sha256,
                   details={"package_id": package_id, "file_version_id": v.file_version_id,
                            "error": f"{type(exc).__name__}: {exc}"[:500], "restored_review_state": restored,
                            "revoked_file_mappings": revoked})
