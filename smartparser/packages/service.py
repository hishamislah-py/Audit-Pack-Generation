"""Phase 3B-9 - evidence package service: package intake, controlled resubmission, review completion, all-or-nothing
snapshot activation and the reconciliation-ready manifest (single-user POC; file-based; deterministic; audited).

Every file - first upload or correction - goes through the EXISTING workflow from the beginning (MappingOrchestrator:
header-count gate -> deterministic -> proposal (only when eligible) -> validation -> policy / HITL -> reprocess ->
14-point handoff -> preview). Nothing here maps, proposes or validates columns itself, and a corrected upload never
reuses an earlier file-specific mapping (file mappings are bound to one intake + SHA-256; a correction is a new intake).

Version status from the file outcome:
    equal count, eligible (deterministic / auto-accept)            -> VALIDATED
    equal count, not eligible / held                               -> FAILED_VALIDATION        (new version needed)
    more columns than fields (header-count gate)                   -> REVIEW_REQUIRED          (mapping review)
    fewer columns than fields (header-count gate)                  -> RESUBMISSION_REQUIRED    (missing source columns)
    proposal review / deterministic-conflict review                -> REVIEW_REQUIRED
    review completed: RESOLVED + eligible                          -> VALIDATED
                      HELD, required field not covered            -> RESUBMISSION_REQUIRED
                      HELD, columns left unresolved only           -> REVIEW_REQUIRED (the case can be revisited)
                      rejected by the reviewer                     -> REJECTED
    content identifies as another category                         -> REJECTED (never switched automatically)

Submission to UC-042 stays disabled: the output is an immutable snapshot + manifest marked NOT submitted, NOT reconciled.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..classify.pdf_classifier import letter_refs_from_inventory
from ..csv_engine.reader import read_csv
from ..handoff.eligibility import check_handoff
from ..handoff.reprocess import ReprocessError, reprocess
from ..identify.detect import identify
from ..intake.store import EvidenceStore, validate_reporting_period
from ..orchestration.orchestrator import MappingOrchestrator, WorkflowResult
from ..orchestration.policy import Decision
from ..pipeline import SmartParser
from ..review import intake as intake_review
from ..review.intake import CaseState
from ..review.session import ReviewContext, approve_proposal, decide_column, open_review
from .models import (NEEDS_NEW_VERSION, EvidenceFile, EvidencePackage, FileVersion, HandoffSummary, PackageCheck,
                     PackageSnapshot, PackageValidationResult, SnapshotEntry, StatusChange)
from .store import PackageStore, PackageStoreError

USABLE = {"VALIDATED", "ACTIVE"}


class PackageError(ValueError):
    pass


@dataclass
class Submission:
    data: bytes
    filename: str
    declared_category: str | None = None   # the analyst's slot choice; verified against the content, never trusted alone


@dataclass
class FileOutcome:
    filename: str
    source_sha256: str
    evidence_category: str | None
    file_version: FileVersion | None        # None: refused before a version was created (see refused_reason)
    refused_reason: str | None = None
    workflow: WorkflowResult | None = None  # transient result of the existing workflow (not persisted)


@dataclass
class ActivationResult:
    validation: PackageValidationResult
    activated: bool
    snapshot: PackageSnapshot | None
    manifest_path: Path | None
    reason: str


class PackageService:
    def __init__(self, store: PackageStore, orchestrator: MappingOrchestrator, authority, actor_id: str = "analyst"):
        self.store, self.o, self.authority, self.actor = store, orchestrator, authority, actor_id
        self.reg, self.log, self.evidence = orchestrator.registry, orchestrator.log, orchestrator.evidence
        # previews live inside the package store so snapshot references are relative and self-contained
        self.o.preview_dir = self.store.root / "previews"

    # ================================================================================================ helpers
    def _now(self) -> str:
        return self.log.clock()

    def _audit(self, event: str, pkg: EvidencePackage, v: FileVersion | None = None, actor: str | None = None,
               role: str = "analyst", **details) -> None:
        d = {"package_id": pkg.package_id, "reporting_period": pkg.reporting_period}
        if v is not None:
            d.update(file_version_id=v.file_version_id, evidence_category=v.evidence_category,
                     version_number=v.version_number, previous_file_version_id=v.previous_version_id,
                     version_status=v.version_status)
        d.update(details)
        self.log.append(event, actor_id=actor or self.actor, actor_role=role,
                        intake_id=v.intake_id if v else None, source_sha256=v.source_sha256 if v else None, details=d)

    def _set_status(self, v: FileVersion, status: str, note: str = "") -> None:
        v.version_status = status
        v.status_history.append(StatusChange(status=status, at=self._now(), note=note))

    def _save(self, pkg: EvidencePackage) -> EvidencePackage:
        pkg.package_status = self._package_status(pkg)
        pkg.updated_at = self._now()
        return self.store.save(pkg)

    def load(self, package_id: str) -> EvidencePackage:
        return self.store.load(package_id)

    def _version(self, pkg: EvidencePackage, file_version_id: str) -> FileVersion:
        v = pkg.versions.get(file_version_id)
        if v is None:
            raise PackageError(f"unknown file version {file_version_id} in package {pkg.package_id}")
        return v

    def _letter_refs(self, pkg: EvidencePackage, selection: dict[str, str] | None = None) -> dict[str, str] | None:
        """{letter ref: category} from the package's own account inventory (IN-02) - the UC-042 rule for resolving the
        acknowledgement-letter PDFs. None when the package has no usable IN-02 yet."""
        vid = (selection or {}).get("IN-02")
        if vid is None:
            latest = pkg.latest("IN-02")
            vid = latest.file_version_id if latest and latest.version_status in USABLE else None
        if vid is None:
            return None
        v = pkg.versions[vid]
        data = self.evidence.read_original(v.source_sha256)
        ident = identify(data, v.original_filename)
        table = read_csv(data, ident.encoding, ident.delimiter)
        return letter_refs_from_inventory([dict(zip(table.raw_headers, r.cells)) for r in table.rows], self.reg)

    def _content_category(self, data: bytes, filename: str, refs) -> str | None:
        """What the CONTENT deterministically identifies as (exact header / controlled mapping / PDF labels); in memory,
        no intake record, no file-specific rule. The filename is never used."""
        res = SmartParser(schemas=self.reg, store=EvidenceStore(None),
                          mapping_rules=self.o.store.load()).process_bytes(data, filename, None, letter_refs=refs)
        return res.metadata.evidence_category if res.metadata.classification_status == "identified" else None

    def _refuse(self, pkg: EvidencePackage, sub: Submission, sha: str, category: str | None, reason: str,
                event: str = "PACKAGE_FILE_RECEIVED") -> FileOutcome:
        pkg.unassigned_uploads.append({"filename": sub.filename, "source_sha256": sha, "declared_category":
                                       sub.declared_category, "evidence_category": category, "reason": reason,
                                       "at": self._now()})
        self._audit(event, pkg, outcome="REFUSED", filename=sub.filename, source_sha256=sha,
                    evidence_category=category, reason=reason)
        self._save(pkg)
        return FileOutcome(sub.filename, sha, category, None, refused_reason=reason)

    # ================================================================================================ package
    def create_package(self, reporting_period: str, required_categories: list[str] | None = None) -> EvidencePackage:
        try:
            period = validate_reporting_period(reporting_period)
        except ValueError as exc:
            raise PackageError(str(exc)) from exc
        if period is None:
            raise PackageError("a package needs a reporting period (YYYY-MM)")
        required = required_categories if required_categories is not None else \
            [s.category for s in self.reg.defined() if s.requirement == "REQUIRED"]     # the UC-042 upload contract
        unknown = [c for c in required if self.reg.get(c) is None]
        if unknown or not required or len(set(required)) != len(required):
            raise PackageError(f"invalid required evidence categories {required} (unknown: {unknown})")
        now = self._now()
        pkg = EvidencePackage(package_id=f"PKG-{period}-{uuid.uuid4().hex[:6]}", reporting_period=period,
                              created_at=now, updated_at=now, required_evidence_categories=list(required),
                              evidence_files={c: EvidenceFile(evidence_category=c, required=True) for c in required})
        self.store.create(pkg)
        self._audit("PACKAGE_CREATED", pkg, required_evidence_categories=list(required))
        return pkg

    # ================================================================================================ intake
    def submit(self, package_id: str, submissions: list[Submission]) -> list[FileOutcome]:
        """Initial package intake (and later first files for still-empty slots). CSV files are processed before PDFs so
        the package's own account inventory can resolve the acknowledgement letters."""
        order = sorted(range(len(submissions)), key=lambda i: submissions[i].filename.lower().endswith(".pdf") or
                       submissions[i].data[:5] == b"%PDF-")
        out: dict[int, FileOutcome] = {}
        for i in order:
            sub = submissions[i]
            pkg = self.store.load(package_id)
            sha = hashlib.sha256(sub.data).hexdigest()
            content = self._content_category(sub.data, sub.filename, self._letter_refs(pkg))
            category = sub.declared_category or content
            if category is None:
                out[i] = self._refuse(pkg, sub, sha, None, "the evidence category could not be identified from the "
                                      "content; declare the category this file is for")
                continue
            if self.reg.get(category) is None:
                out[i] = self._refuse(pkg, sub, sha, category, f"unknown evidence category {category}")
                continue
            slot = pkg.evidence_files.get(category)
            if slot is not None and slot.version_ids:
                latest = pkg.latest(category)
                out[i] = self._refuse(pkg, sub, sha, category,
                                      f"the package already has {category} v{latest.version_number} "
                                      f"({latest.version_status}); a second active file for one category is not "
                                      "allowed - use resubmission for a correction")
                continue
            if slot is None:                                                      # an optional category
                pkg.evidence_files[category] = EvidenceFile(evidence_category=category, required=False)
            out[i] = self._new_version(pkg, category, sub, sha, content, previous=None, reason=None)
        return [out[i] for i in range(len(submissions))]

    def resubmit(self, package_id: str, category: str, data: bytes, filename: str, reason: str) -> FileOutcome:
        """Controlled resubmission of ONE evidence file. The correction is a new intake and a new version, processed by
        the full workflow; the earlier versions and their bytes are kept unchanged."""
        pkg = self.store.load(package_id)
        if category not in pkg.evidence_files:
            raise PackageError(f"{category} is not an evidence category of package {package_id}")
        latest = pkg.latest(category)
        if latest is None:
            raise PackageError(f"{category} has no version yet: submit it as a first file, not a resubmission")
        sub = Submission(data, filename, category)
        sha = hashlib.sha256(data).hexdigest()
        same = [v for v in pkg.history(category) if v.source_sha256 == sha]
        if same:                                   # idempotent: a repeated / unchanged upload never makes a version
            return self._refuse(pkg, sub, sha, category,
                                f"identical bytes were already uploaded as {category} v{same[0].version_number} "
                                f"({same[0].file_version_id}, {same[0].version_status}); no new version created",
                                event="RESUBMISSION_RECEIVED")
        if latest.version_status in ("VALIDATED", "ACTIVE"):
            # 3B-10 policy: an accepted file is never voluntarily replaced (use reprocess_version to re-check it)
            self._audit("RESUBMISSION_RECEIVED", pkg, outcome="REFUSED", filename=filename, source_sha256=sha,
                        evidence_category=category, reason=f"{category} v{latest.version_number} is "
                        f"{latest.version_status}: voluntary replacement of an accepted file is not allowed")
            raise PackageError(f"{category} v{latest.version_number} is {latest.version_status}: an accepted file "
                               "cannot be voluntarily replaced (only RESUBMISSION_REQUIRED / FAILED_VALIDATION / "
                               "REJECTED files take a corrected version)")
        if latest.version_status in ("REVIEW_REQUIRED", "RECEIVED"):
            # a correction may not race an open review - complete or reject that review first
            raise PackageError(f"{category} v{latest.version_number} is {latest.version_status}: complete or reject "
                               "its review before uploading a correction")
        if not reason or not reason.strip():
            raise PackageError("a resubmission needs a replacement reason")
        content = self._content_category(data, filename, self._letter_refs(pkg))
        return self._new_version(pkg, category, sub, sha, content, previous=latest, reason=reason)

    def _new_version(self, pkg: EvidencePackage, category: str, sub: Submission, sha: str, content: str | None,
                     previous: FileVersion | None, reason: str | None) -> FileOutcome:
        schema = self.reg.get(category)
        slot = pkg.evidence_files[category]
        wr = None
        base = dict(file_version_id=f"FV-{uuid.uuid4().hex[:10]}", package_id=pkg.package_id,
                    evidence_category=category, version_number=len(slot.version_ids) + 1,
                    original_filename=sub.filename, source_sha256=sha, uploaded_at=self._now(),
                    reporting_period=pkg.reporting_period, content_category=content,
                    previous_version_id=previous.file_version_id if previous else None, replacement_reason=reason)
        if content is not None and content != category:
            # never switched: stored for traceability and rejected for this slot
            rec = self.evidence.save(sub.data, sub.filename, pkg.reporting_period)
            v = FileVersion(**base, intake_id=rec.evidence_id, version_status="REJECTED",
                            processing_status="CATEGORY_CHECK:REJECTED",
                            reasons=[f"the content identifies as {content}, not {category}; the file is not a "
                                     f"{'replacement for' if previous else 'file for'} {category}"])
        elif schema.evidence_format == "pdf":
            v = self._pdf_version(pkg, base, sub)
        else:
            wr = self.o.process(sub.data, sub.filename, pkg.reporting_period, category=category)
            v = FileVersion(**base, intake_id=wr.intake_id, version_status="RECEIVED",
                            processing_status=f"{wr.route}:{wr.decision.value}", reasons=list(wr.reasons))
            self._apply_workflow(pkg, v, wr)
        v.status_history.insert(0, StatusChange(status="RECEIVED", at=v.uploaded_at, note=sub.filename))
        if v.version_status != "RECEIVED":
            v.status_history.append(StatusChange(status=v.version_status, at=self._now(), note="; ".join(v.reasons)[:500]))
        pkg.versions[v.file_version_id] = v
        slot.version_ids.append(v.file_version_id)
        self._audit("RESUBMISSION_RECEIVED" if previous else "PACKAGE_FILE_RECEIVED", pkg, v, outcome="ACCEPTED",
                    filename=sub.filename, replacement_reason=reason)
        self._audit("FILE_VERSION_CREATED", pkg, v, processing_status=v.processing_status)
        self._audit_status(pkg, v)
        self._save(pkg)
        return FileOutcome(sub.filename, sha, category, v, workflow=wr)

    def _pdf_version(self, pkg: EvidencePackage, base: dict, sub: Submission) -> FileVersion:
        """PDF evidence: the existing content classification (letters resolved through the package's IN-02). Field
        extraction / handoff for PDFs is not implemented (Phase 1 scope): the version is VALIDATED on classification
        only, and that basis is recorded."""
        res = SmartParser(schemas=self.reg, store=self.evidence).process_bytes(
            sub.data, sub.filename, pkg.reporting_period, letter_refs=self._letter_refs(pkg))
        cls = res.classification
        got = res.metadata.evidence_category if res.metadata.classification_status == "identified" else None
        ok = got == base["evidence_category"]
        return FileVersion(**base, intake_id=res.metadata.evidence_id,
                           version_status="VALIDATED" if ok else "FAILED_VALIDATION",
                           processing_status=f"PDF:{res.metadata.classification_status}",
                           reasons=[cls.reason if cls else "not classified"],
                           handoff=HandoffSummary(eligible=ok, basis="PDF_CONTENT_CLASSIFICATION_ONLY"))

    def _apply_workflow(self, pkg: EvidencePackage, v: FileVersion, wr: WorkflowResult) -> None:
        """Map an orchestrator / complete_case / complete_session result onto the version (status, review references,
        rules, confirmation, handoff summary). The workflow itself is never changed here."""
        if wr.intake_case is not None:
            v.review_case_id = wr.intake_case.case_id
            self.store.save_case(pkg.package_id, wr.intake_case)
        if wr.review_session is not None:
            v.review_session_id = wr.review_session.session_id
            self.store.save_session(pkg.package_id, wr.review_session,
                                    wr.proposal.request if wr.proposal and wr.proposal.request else None)
        if wr.confirmation is not None:
            v.confirmation = wr.confirmation
        if wr.reprocessed is not None:
            v.mapping_rule_refs = list(wr.reprocessed.rules_used)
        if wr.eligibility is not None:
            v.handoff = HandoffSummary(
                eligible=wr.eligibility.eligible, failed_checks=[c.check_id for c in wr.eligibility.failed],
                output_sha256=wr.preview["output_sha256"] if wr.preview else None,
                preview_csv=self.store.rel(wr.preview["csv"]) if wr.preview else None,
                provenance=self.store.rel(wr.preview["sidecar"]) if wr.preview else None,
                checks=[{"id": c.check_id, "name": c.name, "passed": c.passed, "detail": c.detail}
                        for c in wr.eligibility.checks])
        case = wr.intake_case
        if wr.route == "HEADER_COUNT_GATE":
            if case.count_difference < 0:
                v.version_status, v.missing_fields = "RESUBMISSION_REQUIRED", list(case.missing_fields_diagnostic)
                v.reasons.append(f"the file has {case.incoming_header_count} columns, {v.evidence_category} needs "
                                 f"{case.expected_field_count}: required source columns are missing - upload a corrected "
                                 "file (missing columns are never filled or inferred)")
            else:
                v.version_status = "REVIEW_REQUIRED"
        elif wr.route in ("CASE_HELD", "SESSION_HELD"):
            summary = (case.final_summary if case else wr.review_session.final_summary) or {}
            missing = summary.get("missing_required_fields")
            unresolved = summary.get("unresolved_positions") if case else None
            v.missing_fields = list(missing or [])
            if missing and not unresolved:
                # every column decided, a required field still has no source column: a corrected file is needed
                v.version_status = "RESUBMISSION_REQUIRED"
            else:
                # 3B-11: a column the analyst deliberately LEFT UNRESOLVED keeps the version under review (the held
                # case can be revisited, or rejected -> resubmission); it never becomes VALIDATED
                v.version_status = "REVIEW_REQUIRED"
        elif wr.decision in (Decision.DETERMINISTIC, Decision.AUTO_ACCEPT) or wr.route in ("CASE_RESOLVED",
                                                                                          "SESSION_RESOLVED"):
            v.version_status = "VALIDATED" if (wr.eligibility and wr.eligibility.eligible and wr.preview) \
                else "FAILED_VALIDATION"
        elif wr.decision == Decision.HUMAN_REVIEW:
            v.version_status = "REVIEW_REQUIRED"
        else:                                                   # REJECT_OR_HOLD on the proposal path
            v.version_status = "FAILED_VALIDATION"
            rec = wr.proposal.record if wr.proposal else None
            if rec is not None:
                v.missing_fields = list(rec.summary.required_fields_unresolved)

    def _audit_status(self, pkg: EvidencePackage, v: FileVersion) -> None:
        s = v.version_status
        if s == "VALIDATED":
            self._audit("FILE_VERSION_VALIDATED", pkg, v, role="system", actor="smartparser-package-service",
                        handoff=v.handoff.model_dump() if v.handoff else None)
        elif s in ("RESUBMISSION_REQUIRED", "FAILED_VALIDATION"):
            self._audit("RESUBMISSION_REQUESTED", pkg, v, role="system", actor="smartparser-package-service",
                        reason="; ".join(v.reasons), missing_fields=v.missing_fields)
        elif s == "REVIEW_REQUIRED":
            self._audit("FILE_VERSION_REVIEW_REQUIRED", pkg, v, role="system", actor="smartparser-package-service",
                        review_case_id=v.review_case_id, review_session_id=v.review_session_id, reason="; ".join(v.reasons))
        elif s == "REJECTED":
            self._audit("FILE_VERSION_REJECTED", pkg, v, role="system", actor="smartparser-package-service",
                        reason="; ".join(v.reasons))

    # ================================================================================================ reprocess
    def reprocess_version(self, package_id: str, file_version_id: str) -> dict:
        """Re-run the deterministic file-level checks of an EXISTING version (3B-10): same intake, same SHA-256, same
        recorded confirmation and current rules -> reprocess (no LLM) -> 14-point handoff -> canonical output rebuilt in a
        temporary folder and compared with the recorded preview hash. NO new version, NO status change, NO snapshot; the
        recorded preview and provenance sidecar are not rewritten. The outcome is audited (REPROCESSED /
        HANDOFF_EVALUATED, purpose reprocess_existing_version)."""
        import tempfile
        from ..handoff.writer import write_preview
        pkg = self.store.load(package_id)
        v = self._version(pkg, file_version_id)
        if v.handoff is None or v.handoff.basis != "CSV_14_POINT_HANDOFF":
            raise PackageError(f"{file_version_id} has no CSV handoff to reprocess ({v.version_status})")
        rr = reprocess(v.intake_id, self.evidence, self.reg, self.o.store.load(), v.confirmation)
        el = check_handoff(rr, self.reg, self.o.handoff_policy)
        out_sha = None
        if el.eligible:
            with tempfile.TemporaryDirectory() as tmp:
                out_sha = write_preview(rr, el, self.reg, tmp)["output_sha256"]
        report = {"file_version_id": v.file_version_id, "intake_id": v.intake_id, "source_sha256": rr.source_sha256,
                  "eligible": el.eligible, "failed_checks": [c.check_id for c in el.failed],
                  "checks_run": len(el.checks), "provider_calls": rr.provider_calls, "output_sha256": out_sha,
                  "matches_recorded_preview": out_sha is not None and out_sha == v.handoff.output_sha256,
                  "version_status": v.version_status}
        base = dict(actor_id="smartparser-package-service", actor_role="system", intake_id=v.intake_id,
                    source_sha256=v.source_sha256)
        common = {"package_id": pkg.package_id, "file_version_id": v.file_version_id, "evidence_category":
                  v.evidence_category, "reporting_period": pkg.reporting_period,
                  "purpose": "reprocess_existing_version"}
        self.log.append("REPROCESSED", **base, details={**common, "rules_used": rr.rules_used,
                                                        "provider_calls": rr.provider_calls,
                                                        "category_basis": rr.category_basis})
        self.log.append("HANDOFF_EVALUATED", **base, details={**common, "eligible": el.eligible,
                                                              "failed_checks": report["failed_checks"],
                                                              "matches_recorded_preview":
                                                              report["matches_recorded_preview"]})
        return report

    # ================================================================================================ review
    def _reviewable(self, package_id: str, file_version_id: str) -> tuple[EvidencePackage, FileVersion]:
        pkg = self.store.load(package_id)
        v = self._version(pkg, file_version_id)
        if v.version_status != "REVIEW_REQUIRED":
            raise PackageError(f"{v.file_version_id} is {v.version_status}, not under review")
        return pkg, v

    def review_case(self, package_id: str, file_version_id: str):
        pkg, v = self._reviewable(package_id, file_version_id)
        if not v.review_case_id:
            raise PackageError(f"{file_version_id} has no column-review case")
        case = self.store.load_case(package_id, v.review_case_id)
        return case, self.o.case_context(case)

    def decide(self, package_id: str, file_version_id: str, action: str, reviewer, reason: str, source_index: int,
               canonical_field: str | None = None, others_reason: str | None = None):
        case, ctx = self.review_case(package_id, file_version_id)
        out = intake_review.decide(case, action, reviewer, reason, self.authority, self.log, ctx, source_index,
                                   canonical_field, others_reason)
        self.store.save_case(package_id, case)                  # persisted after every decision (resumable)
        return out

    def reject_review(self, package_id: str, file_version_id: str, reviewer, reason: str) -> FileVersion:
        pkg, v = self._reviewable(package_id, file_version_id)
        if v.review_case_id:
            case = self.store.load_case(package_id, v.review_case_id)
            intake_review.reject_case(case, reviewer, reason, self.authority, self.log)
            self.store.save_case(package_id, case)
        else:
            from ..review.session import reject_proposal
            s, req = self.store.load_session(package_id, v.review_session_id)
            reject_proposal(s, reviewer, reason, self.authority, self.log)
            self.store.save_session(package_id, s, req)
        v.reasons.append(f"rejected by {reviewer.reviewer_id}: {reason}")
        self._set_status(v, "REJECTED", reason)
        self._audit("FILE_VERSION_REJECTED", pkg, v, actor=reviewer.reviewer_id, role=reviewer.role, reason=reason)
        self._save(pkg)
        return v

    def session_context(self, package_id: str, file_version_id: str):
        pkg, v = self._reviewable(package_id, file_version_id)
        if not v.review_session_id:
            raise PackageError(f"{file_version_id} has no proposal review session")
        s, req = self.store.load_session(package_id, v.review_session_id)
        data = self.evidence.read_original(v.source_sha256)
        if data is None or hashlib.sha256(data).hexdigest() != v.source_sha256:
            raise PackageError("the stored original is missing or does not match the version's SHA-256")
        res = SmartParser(schemas=self.reg, store=EvidenceStore(None)).process_bytes(data, v.original_filename,
                                                                                    v.reporting_period)
        ctx = ReviewContext(req, self.reg.get(s.category), list(res.csv_extraction.raw_headers),
                            {c.index: list(c.sample_values) for c in res.csv_extraction.columns})
        return s, req, ctx

    def review_session(self, package_id: str, file_version_id: str, reviewer, basis: str,
                       decisions: list[tuple[int, str, str | None]], approve: bool = True):
        """Proposal-session review: decisions = [(source_index, APPROVE|CHANGE|REJECT|LEAVE_UNMAPPED, final_field)];
        then (optionally) approve. Persisted after the call (resumable)."""
        s, req, ctx = self.session_context(package_id, file_version_id)
        if s.state == "PROPOSED":
            open_review(s, reviewer, self.authority, self.log)
        for idx, action, fld in decisions:
            decide_column(s, idx, action, reviewer, basis, self.authority, self.log, ctx, final_field=fld)
        if approve:
            approve_proposal(s, reviewer, basis, self.authority, self.log, ctx)
        self.store.save_session(package_id, s, req)
        return s

    def complete_review(self, package_id: str, file_version_id: str, reviewers, basis: str,
                        category_reviewer=None) -> FileVersion:
        """Finalise the version's review through the EXISTING completion (complete_case / complete_session: re-verify
        the original, governed file mapping, deterministic reprocess, 14-point handoff, preview) and record the
        outcome on the version."""
        pkg, v = self._reviewable(package_id, file_version_id)
        if v.review_case_id:
            case = self.store.load_case(package_id, v.review_case_id)
            try:
                wr = self.o.complete_case(case, reviewers, basis, self.authority, category_reviewer=category_reviewer)
            finally:
                self.store.save_case(package_id, case)
        else:
            s, req = self.store.load_session(package_id, v.review_session_id)
            wr = self.o.complete_session(s, reviewers, basis, self.authority, category_reviewer=category_reviewer,
                                         content_category=v.content_category)
            self.store.save_session(package_id, s, req)
        v.processing_status = f"{wr.route}:{wr.decision.value}"
        v.reasons.extend(wr.reasons)
        self._apply_workflow(pkg, v, wr)
        v.status_history.append(StatusChange(status=v.version_status, at=self._now(), note="; ".join(wr.reasons)[:500]))
        self._audit_status(pkg, v)
        self._save(pkg)
        return v

    # ================================================================================================ status
    def pending_resubmissions(self, package_id: str) -> dict[str, str]:
        """{category: latest version id} for categories that need a corrected file - and ONLY those."""
        pkg = self.store.load(package_id)
        return {c: pkg.latest(c).file_version_id for c in pkg.evidence_files
                if pkg.latest(c) is not None and pkg.latest(c).version_status in NEEDS_NEW_VERSION}

    def candidate(self, pkg: EvidencePackage) -> dict[str, str | None]:
        """The selection a new snapshot would use: for every category, the LATEST version if it is VALIDATED / ACTIVE,
        otherwise nothing (a pending required category blocks; it is never filled with an older version)."""
        out = {}
        for c, slot in pkg.evidence_files.items():
            latest = pkg.latest(c)
            if latest is not None and latest.version_status in USABLE:
                out[c] = latest.file_version_id
            elif slot.required:
                out[c] = None
        return out

    def _package_status(self, pkg: EvidencePackage) -> str:
        latest = {c: pkg.latest(c) for c in pkg.evidence_files}
        if not pkg.versions:
            return "RECEIVED"
        if any(v is not None and v.version_status in NEEDS_NEW_VERSION for v in latest.values()):
            return "RESUBMISSION_REQUIRED"
        if any(v is not None and v.version_status in ("REVIEW_REQUIRED", "RECEIVED") for v in latest.values()):
            return "REVIEW_REQUIRED"
        if any(latest[c] is None for c in pkg.required_evidence_categories):
            return "INCOMPLETE"
        if pkg.active_snapshot_id:
            snap = self.store.load_snapshot(pkg.package_id, pkg.active_snapshot_id)
            if {e.evidence_category: e.file_version_id for e in snap.entries} == \
                    {c: x for c, x in self.candidate(pkg).items() if x}:
                return "RECONCILIATION_READY"
        return "READY_FOR_VALIDATION"

    # ================================================================================================ validation
    def _file_level_now(self, pkg: EvidencePackage, v: FileVersion, selection: dict[str, str]) -> tuple[bool, str]:
        """Re-run the file-level checks NOW (not trusting the stored status): CSV -> deterministic reprocess (no LLM)
        with the recorded confirmation + current rules -> 14-point handoff, and the preview file still has its hash;
        PDF -> content classification with the package's selected IN-02."""
        if v.handoff and v.handoff.basis == "PDF_CONTENT_CLASSIFICATION_ONLY":
            data = self.evidence.read_original(v.source_sha256)
            got = self._content_category(data, v.original_filename, self._letter_refs(pkg, selection))
            return got == v.evidence_category, f"PDF classified as {got} (field extraction not implemented)"
        try:
            rr = reprocess(v.intake_id, self.evidence, self.reg, self.o.store.load(), v.confirmation)
        except ReprocessError as exc:
            return False, f"reprocess failed: {exc}"
        el = check_handoff(rr, self.reg, self.o.handoff_policy)
        if not el.eligible:
            return False, f"handoff checks failed now: {[c.check_id for c in el.failed]}"
        if rr.provider_calls != 0 or rr.category != v.evidence_category:
            return False, "reprocess result differs"
        if not (v.handoff and v.handoff.preview_csv and v.handoff.output_sha256):
            return False, "no canonical preview recorded"
        p = self.store.abs(v.handoff.preview_csv)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != v.handoff.output_sha256:
            return False, "canonical preview missing or changed"
        return True, "reprocessed deterministically; 14/14 handoff checks pass; preview hash verified"

    def validate(self, package_id: str) -> PackageValidationResult:
        pkg = self.store.load(package_id)
        sel = self.candidate(pkg)
        self._audit("PACKAGE_VALIDATION_STARTED", pkg, role="system", actor="smartparser-package-service",
                    selection=sel)
        checks: list[PackageCheck] = []
        add = lambda i, n, ok, d="": checks.append(PackageCheck(check_id=i, name=n, passed=bool(ok), detail=d))  # noqa
        req = pkg.required_evidence_categories
        no_file = [c for c in req if not pkg.evidence_files[c].version_ids]
        add("PV-01", "every required evidence category is present", not no_file, f"missing: {no_file}" if no_file else
            f"{len(req)} required categories")
        chosen = {c: x for c, x in sel.items() if x}
        active_counts = {c: sum(pkg.versions[x].version_status == "ACTIVE" for x in s.version_ids)
                         for c, s in pkg.evidence_files.items()}
        dup_active = {c: n for c, n in active_counts.items() if n > 1}
        add("PV-02", "exactly one selected version per category", all(chosen.get(c) for c in req) and not dup_active
            and len(set(chosen.values())) == len(chosen), f"unselected: {[c for c in req if not chosen.get(c)]}; "
            f"multiple active: {dup_active}")
        slots = list(pkg.evidence_files)        # required AND optional slots: a pending optional file also blocks
        resub = [c for c in slots if pkg.latest(c) and pkg.latest(c).version_status in NEEDS_NEW_VERSION]
        add("PV-03", "no file awaits resubmission", not resub, f"awaiting a corrected file: {resub}")
        review = [c for c in slots if pkg.latest(c) and pkg.latest(c).version_status in ("REVIEW_REQUIRED", "RECEIVED")]
        add("PV-04", "no selected / required file is under review", not review, f"under review: {review}")
        bad_file = {}
        for c, x in chosen.items():
            ok, why = self._file_level_now(pkg, pkg.versions[x], chosen)
            if not ok:
                bad_file[c] = why
        add("PV-05", "every selected file passes its file-level checks (re-run now)", not bad_file, json.dumps(bad_file))
        period_bad = []
        for c, x in chosen.items():
            v, rec = pkg.versions[x], self.evidence.find(pkg.versions[x].intake_id)
            if v.reporting_period != pkg.reporting_period or rec is None or rec.reporting_period != pkg.reporting_period:
                period_bad.append(c)
        add("PV-06", "reporting periods consistent with the package", not period_bad,
            f"{pkg.reporting_period}; inconsistent: {period_bad}")
        member_bad = [c for c, x in chosen.items() if pkg.versions[x].package_id != pkg.package_id
                      or pkg.versions[x].evidence_category != c or x not in pkg.evidence_files[c].version_ids]
        add("PV-07", "package membership valid (same package, own category slot)", not member_bad, str(member_bad))
        sha_bad = []
        for c, x in chosen.items():
            v = pkg.versions[x]
            rec, data = self.evidence.find(v.intake_id), self.evidence.read_original(v.source_sha256)
            if rec is None or rec.sha256 != v.source_sha256 or data is None or \
                    hashlib.sha256(data).hexdigest() != v.source_sha256:
                sha_bad.append(c)
        add("PV-08", "every selected file has a valid intake and SHA-256 (stored bytes re-hashed)", not sha_bad,
            str(sha_bad))
        not_valid = [c for c, x in chosen.items() if pkg.versions[x].version_status not in USABLE
                     or not (pkg.versions[x].handoff and pkg.versions[x].handoff.eligible)]
        add("PV-09", "the selection references exactly the validated file versions", not not_valid, str(not_valid))
        res = PackageValidationResult(validation_id=f"PVR-{uuid.uuid4().hex[:10]}", package_id=pkg.package_id,
                                      at=self._now(), selection={c: x for c, x in sel.items() if x},
                                      checks=checks, passed=all(c.passed for c in checks))
        pkg = self.store.load(package_id)
        pkg.validation_results.append(res)
        self._audit("PACKAGE_VALIDATED" if res.passed else "PACKAGE_VALIDATION_FAILED", pkg, role="system",
                    actor="smartparser-package-service", validation_id=res.validation_id,
                    failed_checks=[c.check_id for c in checks if not c.passed],
                    outcome={c.check_id: c.passed for c in checks})
        self._save(pkg)
        return res

    # ================================================================================================ activation
    @staticmethod
    def _selection_sha(entries: list[SnapshotEntry]) -> str:
        body = sorted((e.evidence_category, e.file_version_id, e.source_sha256) for e in entries)
        return hashlib.sha256(json.dumps(body).encode()).hexdigest()

    def activate(self, package_id: str) -> ActivationResult:
        """All-or-nothing: the complete candidate (unchanged active versions + every validated replacement) is
        validated as a set; only then is a new immutable snapshot created and activated. Otherwise nothing changes."""
        res = self.validate(package_id)
        pkg = self.store.load(package_id)
        if not res.passed:
            return ActivationResult(res, False, None, None, "package validation failed: " +
                                    ", ".join(f"{c.check_id} {c.detail}" for c in res.checks if not c.passed))
        entries = []
        for c in sorted(res.selection):
            v = pkg.versions[res.selection[c]]
            entries.append(SnapshotEntry(evidence_category=c, file_version_id=v.file_version_id,
                                         version_number=v.version_number, intake_id=v.intake_id,
                                         original_filename=v.original_filename, source_sha256=v.source_sha256,
                                         reporting_period=v.reporting_period, handoff=v.handoff,
                                         mapping_rule_refs=v.mapping_rule_refs,
                                         confirmation_id=v.confirmation.confirmation_id if v.confirmation else None))
        sel_sha = self._selection_sha(entries)
        if pkg.active_snapshot_id:
            active = self.store.load_snapshot(package_id, pkg.active_snapshot_id)
            if active.selection_sha256 == sel_sha:                  # repeated activation: idempotent, nothing new
                return ActivationResult(res, False, active, self.store.manifest_path(package_id, active.snapshot_id),
                                        f"the selection is already the active snapshot {active.snapshot_id}")
        seq = len(pkg.snapshot_ids) + 1
        sid = f"SNAP-{seq:03d}-{sel_sha[:8]}"
        snap = PackageSnapshot(snapshot_id=sid, package_id=package_id, reporting_period=pkg.reporting_period,
                               sequence=seq, created_at=self._now(), entries=entries, selection_sha256=sel_sha,
                               validation_id=res.validation_id, previous_snapshot_id=pkg.active_snapshot_id)
        try:
            self.store.write_snapshot(snap)
        except PackageStoreError:
            existing = self.store.load_snapshot(package_id, sid)    # recovery after an interrupted activation
            if existing.selection_sha256 != sel_sha:
                raise
            snap = existing
        self._audit("PACKAGE_SNAPSHOT_CREATED", pkg, role="system", actor="smartparser-package-service",
                    snapshot_id=sid, selection_sha256=sel_sha, selection=res.selection, validation_id=res.validation_id)
        superseded = []
        for c, vid in res.selection.items():
            slot = pkg.evidence_files[c]
            for old_id in slot.version_ids:
                old = pkg.versions[old_id]
                if old_id == vid:
                    if old.version_status != "ACTIVE":
                        self._set_status(old, "ACTIVE", f"selected by {sid}")
                        self._audit("FILE_VERSION_ACTIVATED", pkg, old, role="system",
                                    actor="smartparser-package-service", snapshot_id=sid)
                elif old.version_number < pkg.versions[vid].version_number and \
                        old.version_status not in ("SUPERSEDED", "REJECTED"):
                    self._set_status(old, "SUPERSEDED", f"replaced by {pkg.versions[vid].file_version_id} in {sid}")
                    superseded.append(old_id)
                    self._audit("FILE_VERSION_SUPERSEDED", pkg, old, role="system",
                                actor="smartparser-package-service", snapshot_id=sid,
                                superseded_by=pkg.versions[vid].file_version_id)
            slot.active_version_id = vid
        manifest = self._manifest(pkg, snap, res, superseded)
        try:
            mpath = self.store.write_manifest(package_id, sid, manifest)
        except PackageStoreError:
            mpath = self.store.manifest_path(package_id, sid)
        pkg.snapshot_ids.append(sid)
        pkg.active_snapshot_id = sid
        self._audit("PACKAGE_SNAPSHOT_ACTIVATED", pkg, role="system", actor="smartparser-package-service",
                    snapshot_id=sid, previous_snapshot_id=snap.previous_snapshot_id, superseded_versions=superseded,
                    manifest=self.store.rel(mpath))
        self._save(pkg)
        return ActivationResult(res, True, snap, mpath, f"snapshot {sid} activated")

    def _manifest(self, pkg: EvidencePackage, snap: PackageSnapshot, res: PackageValidationResult,
                  superseded: list[str]) -> dict:
        files = []
        for e in snap.entries:
            v = pkg.versions[e.file_version_id]
            h = e.handoff
            files.append({
                "evidence_category": e.evidence_category, "file_version_id": e.file_version_id,
                "version_number": e.version_number, "previous_version_id": v.previous_version_id,
                "replacement_reason": v.replacement_reason, "intake_id": e.intake_id,
                "original_filename": e.original_filename, "source_sha256": e.source_sha256,
                "canonical_preview": {"path": h.preview_csv, "sha256": h.output_sha256} if h and h.preview_csv else None,
                "provenance": {"path": h.provenance} if h and h.provenance else None,
                "file_level": {"eligible": h.eligible if h else False, "basis": h.basis if h else None,
                               "failed_checks": h.failed_checks if h else []},
                "mapping_rule_refs": e.mapping_rule_refs, "confirmation_id": e.confirmation_id,
                "processing_status": v.processing_status,
            })
        return {
            "manifest_schema": "smartparser-reconciliation-ready-package/1.0",
            "status": "RECONCILIATION_READY_NOT_SUBMITTED",
            "submission_authorised": False,
            "reconciliation_status": "NOT_RUN",
            "note": "a validated, immutable selection of evidence file versions for the next integration stage; nothing "
                    "was submitted to UC-042 and no reconciliation has been run",
            "package_id": pkg.package_id, "snapshot_id": snap.snapshot_id, "sequence": snap.sequence,
            "previous_snapshot_id": snap.previous_snapshot_id, "reporting_period": pkg.reporting_period,
            "selection_sha256": snap.selection_sha256, "validation_id": res.validation_id,
            "validation_timestamp": res.at,
            "package_validation": {"passed": res.passed, "checks": [c.model_dump() for c in res.checks]},
            "required_evidence_categories": pkg.required_evidence_categories,
            "selected_evidence_categories": [e.evidence_category for e in snap.entries],
            "files": files,
            "superseded_versions": superseded,
        }

    # ================================================================================================ inspection
    def verify_snapshot(self, package_id: str, snapshot_id: str) -> list[PackageCheck]:
        """Re-inspect an (active or historical) snapshot: immutable record intact, selection hash reproducible, every
        selected original still has its SHA-256, every preview still has its hash, the manifest matches."""
        pkg = self.store.load(package_id)
        snap = self.store.load_snapshot(package_id, snapshot_id)
        out = []
        add = lambda i, n, ok, d="": out.append(PackageCheck(check_id=i, name=n, passed=bool(ok), detail=d))  # noqa
        add("SV-1", "selection hash reproducible", self._selection_sha(snap.entries) == snap.selection_sha256)
        bad = [e.evidence_category for e in snap.entries
               if (d := self.evidence.read_original(e.source_sha256)) is None or hashlib.sha256(d).hexdigest()
               != e.source_sha256 or (self.evidence.find(e.intake_id) or None) is None]
        add("SV-2", "every selected original present with its SHA-256 and intake", not bad, str(bad))
        pv_bad = [e.evidence_category for e in snap.entries if e.handoff and e.handoff.preview_csv and
                  hashlib.sha256(self.store.abs(e.handoff.preview_csv).read_bytes()).hexdigest() != e.handoff.output_sha256]
        add("SV-3", "every canonical preview has its recorded hash", not pv_bad, str(pv_bad))
        mp = self.store.manifest_path(package_id, snapshot_id)
        man = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else None
        add("SV-4", "manifest matches the snapshot", man is not None and
            [(f["evidence_category"], f["file_version_id"], f["source_sha256"]) for f in man["files"]] ==
            [(e.evidence_category, e.file_version_id, e.source_sha256) for e in snap.entries]
            and man["selection_sha256"] == snap.selection_sha256 and man["submission_authorised"] is False)
        add("SV-5", "every selected version belongs to this package", all(
            e.file_version_id in pkg.versions and pkg.versions[e.file_version_id].package_id == package_id
            for e in snap.entries))
        return out
