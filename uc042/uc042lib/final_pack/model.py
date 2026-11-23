"""Final audit-pack constants and input/output models (spec 06 §5). The final pack itself is canonical JSON assembled by
assemble.py; the models here type what callers supply (selections, review record, generation info) and the AI-generated
closing summary. Existing investigation models are imported, never copied."""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

PROJECT = Path(__file__).resolve().parents[2]
# Primary final packs are published OUTSIDE the source repository: uc042lib.runtime_paths.default_final_packs_root()
# (UC042_FINAL_PACKS_ROOT, else the per-user data directory), resolved when a pack is published or listed.

FINAL_PACK_SCHEMA_VERSION = "uc042-final-pack/1.0"
# 1.1: assembled with the analyst's ACCEPT / REJECT review of each selected investigation (analyst_reviews). A pack built
# without analyst reviews (library callers that do not supply them) keeps 1.0 and its exact earlier content.
REVIEWED_FINAL_PACK_SCHEMA_VERSION = "uc042-final-pack/1.1"
# 1.3 (owner-approved, 18 Nov 2026; renderer 3.0): a reviewed pack also carries the deterministic outcome_summary (figures
# and sentences built by rules from the stored engine results, never by AI), each NO_FINDINGS control check's engine note,
# and a closing summary that may be NOT_REQUIRED (no exception and no included investigation: no AI request is made).
# 1.2 is RESERVED for the separately gated rejected-AI-content change (A1) and is not used here; if A1 is approved it is
# defined on top of 1.3 (as 1.4). Stored 1.0 / 1.1 packs are unchanged and keep verifying with the renderer they declare.
OUTCOME_FINAL_PACK_SCHEMA_VERSION = "uc042-final-pack/1.3"
RESERVED_FINAL_PACK_SCHEMA_VERSIONS = {"uc042-final-pack/1.2": "rejected AI content as labelled rejected evidence (A1, not approved)"}
ASSEMBLER_VERSION = "uc042-final-assembler/1.0"
SNAPSHOT_VERSION = "uc042-review-snapshot/1.0"
RENDERER_VERSION = "uc042-final-report-renderer/1.0"  # standard PDF fonts (cp1252); every pack that declares no renderer
# Unicode PDF (bundled DejaVu fonts, no character substitution). Declared by final-pack schema 1.1 packs in
# metadata.report_renderer; a published pack always re-renders with the renderer it declares.
UNICODE_RENDERER_VERSION = "uc042-final-report-renderer/2.0-unicode"
# 2.1 (owner-approved, 17 Nov 2026): identical to 2.0 except that a table row taller than the space left on a page may split
# inside the row, so a long finding (for example 7,900 characters of copied amounts and dates) flows across pages instead of
# failing the whole generation with a LayoutError. Nothing is shortened. Declared by every newly assembled reviewed pack;
# packs that declare 2.0 (or 1.0) keep rendering exactly as they were published (verify_final_pack re-renders them).
SPLITTING_RENDERER_VERSION = "uc042-final-report-renderer/2.1-unicode"
# 3.0 (owner-approved, 18 Nov 2026): the outcome-first layout (report_v3.py): executive outcome on page 1, conditional
# exception and investigation sections, grouped limitations, technical appendix. Same fonts and row splitting as 2.1. The
# 1.0 / 2.0 / 2.1 builder (report.py build_report_v2) is frozen so every published pack re-renders byte for byte.
OUTCOME_RENDERER_VERSION = "uc042-final-report-renderer/3.0-unicode"
CURRENT_RENDERER_VERSION = OUTCOME_RENDERER_VERSION
UNICODE_RENDERERS = (UNICODE_RENDERER_VERSION, SPLITTING_RENDERER_VERSION, OUTCOME_RENDERER_VERSION)
OUTCOME_SUMMARY_VERSION = "uc042-outcome-summary/1.0"
# 1.1: adds status NOT_REQUIRED (a record that no AI closing summary was needed; no text, no provider request).
# 1.2 (23 Nov 2026, Session 1 TMS demo): the output carries a required group_assessments section (one assessment per engine
# investigation group and per candidate relationship supplied). Stored 1.0 / 1.1 summaries have no such field: it is omitted
# when absent, so their bytes, hashes and renderings are unchanged.
SUMMARY_SCHEMA_VERSION = "uc042-closing-summary/1.2"
# 1.4 (23 Nov 2026): the two ID lists are spelt out (allowed_refs only for source_refs; allowed_source_refs only for group
# assessment evidence), unverified_hypotheses must cite a hypothesis or CAND- ref, related_exception_ids guidance; live TC06
# refusal (an unverified_hypotheses item cited source records). Validation unchanged.
# 1.3 (23 Nov 2026): group assessment instructions. 1.2 (18 Nov 2026): with no citable reference (allowed_refs empty) every
# citation-dependent list stays empty; an item that cannot cite an allowed reference is omitted; an empty string is never a
# reference. Validation unchanged except that it names an empty reference explicitly. 1.1 (12 Nov 2026): one negation per
# disclaimer term.
# 1.5 (23 Nov 2026): mandatory relationship-reasoning procedure (origin, connecting records, shared keys, chronology,
# contradictions, coincidence, decision); matching amounts/dates/labels never sufficient; lineage only when the linked record
# is itself out of line. Validation unchanged.
SUMMARY_PROMPT_VERSION = "uc042-closing-summary-prompt/1.5"
# 1.1 (23 Nov 2026): each exception, investigation group, candidate relationship, accepted confirmed finding and conflict
# also carries its SOURCE evidence record IDs (only IDs of the pack's evidence register), group links / candidate detail
# text, and allowed_source_refs (their union): the only IDs a group assessment may cite as supporting or contradicting
# evidence. Engine control-result IDs are never source records.
# 1.2 (23 Nov 2026): each exception carries its engine root_cause; shared_record_links lists exception pairs whose evidence
# cites the same source record (deterministic facts, no conclusions).
SUMMARY_INPUT_VERSION = "uc042-closing-summary-input/1.2"
RELATIONSHIP_VERDICTS = ("EVIDENCE_BACKED", "UNVERIFIED", "COINCIDENCE_REJECTED")
ASSESSMENT_CONFIDENCE = ("LOW", "MEDIUM", "HIGH")
SUPPORTED_PACK_SCHEMAS = {"uc042-pack/0.1"}

FINAL_PACK_ID_RE = re.compile(r"^FAP-[A-Z0-9]{1,12}-PER-\d{4}-\d{2}-v\d{1,4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ACKNOWLEDGEMENT_TEXT = ("Generating this pack does not resolve any exception, confirm any hypothesis or establish compliance. "
                        "Unresolved exceptions will appear as UNRESOLVED.")
GENERATE_MEANING = ("GENERATE authorised assembly of this report. It does not resolve exceptions, prove hypotheses, "
                    "certify a clean reconciliation or establish regulatory compliance.")
AI_DISCLAIMER = ("AI-generated content in this report (investigation assessments, observations, hypotheses and the closing "
                 "summary) was produced by a language model from the supplied reconciliation and investigation records and "
                 "validated by deterministic rules. It is an aid to human review, not an audit or compliance opinion.")
CLOSING_SUMMARY_NOTICE = ("AI-generated summary based only on the supplied reconciliation and investigation records. It is not "
                          "an independent audit opinion, not a compliance certification, and does not resolve any exception.")
ANALYST_REVIEW_NOTICE = ("Each selected AI investigation was reviewed by the analyst. An ACCEPTED investigation's AI content is "
                         "reported in this pack. A REJECTED investigation's AI summary, findings, hypotheses and recommendations "
                         "are excluded from this report; the analyst's reason for rejection, shown exactly as recorded, is the "
                         "review content for that exception. The original AI investigation is kept unchanged by the "
                         "application. Neither decision resolves an exception.")
DATA_HANDLING = ("AI requests use the OpenAI Responses API with store=False (no application-state storage). OpenAI's default "
                 "abuse-monitoring retention still applies unless the organisation has approved Zero Data Retention or "
                 "Modified Abuse Monitoring; this has not been established for this project.")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------------------------
# Caller-supplied inputs
# --------------------------------------------------------------------------------------------------------------
class Selection(_Strict):
    """Which investigation (if any) represents an exception in the final pack. The caller decides; nothing is defaulted
    silently (default_selections() is an explicit helper)."""
    exception_id: str
    inclusion: Literal["INCLUDED", "NOT_INVESTIGATED", "EXCLUDED_BY_ANALYST"]
    investigation_id: Optional[str] = None
    reason: str = ""

    @model_validator(mode="after")
    def _consistent(self):
        if self.inclusion == "INCLUDED" and not self.investigation_id:
            raise ValueError(f"{self.exception_id}: INCLUDED requires investigation_id")
        if self.inclusion != "INCLUDED" and self.investigation_id:
            raise ValueError(f"{self.exception_id}: investigation_id is only allowed when INCLUDED")
        if self.inclusion == "EXCLUDED_BY_ANALYST" and not self.reason.strip():
            raise ValueError(f"{self.exception_id}: EXCLUDED_BY_ANALYST requires a reason")
        return self


class Reviewer(_Strict):
    user_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class AnalystReview(_Strict):
    """The analyst's latest (active) ACCEPT / REJECT decision on one published investigation, supplied by the caller (the
    application's append-only review record). The rejection reason is kept exactly as written: never trimmed, reworded or
    summarised. A decision never changes the investigation, the deterministic exception or its status."""
    analyst_review_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    exception_id: str = Field(min_length=1)
    decision: Literal["ACCEPT", "REJECT"]
    findings_sha256: str = Field(pattern=SHA256_RE.pattern, description="Hash of the findings.json the analyst reviewed")
    findings_schema_version: str = ""
    comment: str = ""
    rejection_reason: str = ""
    reviewer: Reviewer
    decided_at: str
    revision: int = Field(1, ge=1)

    @field_validator("decided_at")
    @classmethod
    def _utc(cls, v):
        """Canonical UTC (the same instant reads the same whatever offset it arrived with): the decision is part of the
        review snapshot hash, so a server or session time-zone change must never make an identical decision differ."""
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            raise ValueError("decided_at must carry a time zone")
        dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="microseconds" if dt.microsecond else "seconds")

    @model_validator(mode="after")
    def _consistent(self):
        if self.decision == "REJECT" and not self.rejection_reason.strip():
            raise ValueError(f"{self.investigation_id}: a REJECT decision requires a reason for rejection")
        if self.decision == "ACCEPT" and self.rejection_reason:
            raise ValueError(f"{self.investigation_id}: an ACCEPT decision has no reason for rejection")
        return self


class PriorDecision(_Strict):
    review_decision_id: str
    decision: Literal["HOLD"]
    decided_at: str
    comment: str = ""


class ReviewRecord(_Strict):
    """The human decision, supplied by the caller (later: the review service). Never invented by the library."""
    review_decision_id: str = Field(min_length=1)
    review_session_id: str = ""
    decision: Literal["GENERATE", "HOLD"]
    reviewer: Reviewer
    decided_at: str
    comment: str = ""
    acknowledgement_accepted: bool
    acknowledgement_text: str = ACKNOWLEDGEMENT_TEXT
    snapshot_sha256: str = Field(pattern=SHA256_RE.pattern)
    closing_summary_sha256: str = Field(pattern=SHA256_RE.pattern, description="Hash of the closing summary the reviewer read")
    acknowledged_summary_unavailable: bool = False
    prior_decisions: list[PriorDecision] = Field(default_factory=list)

    @field_validator("decided_at")
    @classmethod
    def _iso(cls, v):
        datetime.fromisoformat(v)
        return v


class GenerationInfo(_Strict):
    version: int = Field(1, ge=1)
    supersedes_final_pack_id: Optional[str] = None
    generated_at: Optional[str] = None  # ISO 8601; set at assembly when omitted

    @model_validator(mode="after")
    def _chain(self):
        if (self.version > 1) != bool(self.supersedes_final_pack_id):
            raise ValueError("version > 1 requires supersedes_final_pack_id, and version 1 must not supersede anything")
        if self.generated_at:
            datetime.fromisoformat(self.generated_at)
        return self


# --------------------------------------------------------------------------------------------------------------
# AI-generated closing summary (structured output) and its record
# --------------------------------------------------------------------------------------------------------------
class SummaryItem(_Strict):
    text: str = Field(min_length=10)
    source_refs: list[str] = Field(min_length=1, description="IDs from allowed_refs that support this item")


class UnresolvedItem(_Strict):
    exception_id: str
    text: str = Field(min_length=10)


class GroupAssessment(_Strict):
    """One related-exception assessment (summary schema 1.2): an engine investigation group (GRP-) or a candidate
    relationship (CAND-) from the input. The common cause is ALWAYS a hypothesis; supporting / contradicting evidence are
    SOURCE record IDs from allowed_source_refs only. Validated deterministically in summary.validate_closing_summary."""
    group_id: str = Field(description="The GRP- group ID or CAND- candidate ID being assessed (from the input)")
    exception_ids: list[str] = Field(min_length=1, description="The exception IDs of that group or candidate; when a group "
                                     "is split into several assessments, the part this assessment covers (the parts must "
                                     "cover each exception of the group exactly once)")
    related_exception_ids: list[str] = Field(description="Other exceptions of this pack that appear related (may be empty)")
    relationship_verdict: Literal[RELATIONSHIP_VERDICTS] = Field(
        description="EVIDENCE_BACKED: the link is supported by cited source records. UNVERIFIED: plausible but not "
                    "established. COINCIDENCE_REJECTED: an apparent link (for example the same date and amount) is "
                    "contradicted or unsupported by the records")
    common_cause_hypothesis: str = Field(min_length=10, description="The likely common cause, worded as an unverified "
                                         "hypothesis (may, could, possibly), or an explicit statement that the evidence is "
                                         "insufficient or that no common cause is supported")
    supporting_evidence: list[str] = Field(description="Source record IDs from allowed_source_refs that support the link")
    contradicting_evidence: list[str] = Field(description="Source record IDs from allowed_source_refs that contradict it")
    missing_evidence: list[str] = Field(description="Evidence that would confirm or rule out the link (plain statements)")
    analyst_action: str = Field(min_length=10, description="What the analyst should check or do next (a recommendation)")
    confidence: Literal[ASSESSMENT_CONFIDENCE] = Field(description="Confidence in the verdict (an UNVERIFIED verdict is never HIGH)")
    rationale: str = Field(min_length=10, description="Why this verdict, referring to the cited records")


class ClosingSummaryOutput(_Strict):
    """Exactly what the model returns for the closing summary."""
    overall_position: str = Field(min_length=30, description="Overall reconciliation position, as reported by the engine")
    summary_text: str = Field(min_length=50, description="Plain-language closing summary for an analyst or compliance reviewer")
    key_observations: list[SummaryItem] = Field(description="Most important evidence-supported observations")
    unresolved_items: list[UnresolvedItem] = Field(description="Important unresolved exceptions")
    unverified_hypotheses: list[SummaryItem] = Field(description="Hypotheses that remain unverified")
    evidence_gaps: list[SummaryItem] = Field(description="Material evidence gaps")
    suggested_next_steps: list[SummaryItem] = Field(description="Suggested next actions (recommendations only)")
    limitations: list[str] = Field(description="Important limitations of the records and of this summary")
    # Summary schema 1.2. Required by validation for input 1.1 (one per supplied group and candidate; [] when none). None =
    # a summary written before 1.2: omitted when serialised so stored summaries keep their exact bytes and hashes.
    group_assessments: Optional[list[GroupAssessment]] = Field(
        default=None, description="One assessment per investigation group and candidate relationship in the input "
                                  "(an empty list when the input has none)")

    @model_serializer(mode="wrap")
    def _omit_absent_group_assessments(self, handler):
        data = handler(self)
        if isinstance(data, dict) and data.get("group_assessments") is None:
            data.pop("group_assessments", None)
        return data


class ClosingSummary(_Strict):
    """The closing-summary record supplied to the assembler. GENERATED carries validated output; UNAVAILABLE records an
    explicit failure (never a substitute text); NOT_REQUIRED (summary schema 1.1, final-pack schema 1.3) records that no AI
    closing summary was needed because the pack has no exception and no included investigation: no request was made."""
    status: Literal["GENERATED", "UNAVAILABLE", "NOT_REQUIRED"]
    summary_schema_version: str = SUMMARY_SCHEMA_VERSION
    prompt_version: str = SUMMARY_PROMPT_VERSION
    source_fingerprint: str = Field(pattern=SHA256_RE.pattern)
    snapshot_sha256: str = Field(pattern=SHA256_RE.pattern)
    output: Optional[ClosingSummaryOutput] = None
    validation_findings: list[str] = Field(default_factory=list)
    unavailable_reason: str = ""
    model_metadata: dict = Field(default_factory=dict)
    created_at: str = ""

    @model_validator(mode="after")
    def _shape(self):
        if self.status == "GENERATED" and self.output is None:
            raise ValueError("a GENERATED closing summary requires output")
        if self.status == "UNAVAILABLE" and (self.output is not None or not self.unavailable_reason.strip()):
            raise ValueError("an UNAVAILABLE closing summary has no output and requires unavailable_reason")
        if self.status == "NOT_REQUIRED" and (self.output is not None or self.unavailable_reason or self.model_metadata):
            raise ValueError("a NOT_REQUIRED closing summary has no output, no failure reason and no model metadata")
        return self
