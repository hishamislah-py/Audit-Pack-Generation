"""Final audit-pack constants and input/output models (spec 06 §5). The final pack itself is canonical JSON assembled by
assemble.py; the models here type what callers supply (selections, review record, generation info) and the AI-generated
closing summary. Existing investigation models are imported, never copied."""
import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT = Path(__file__).resolve().parents[2]
FINAL_PACKS_ROOT = PROJECT / "final_packs"

FINAL_PACK_SCHEMA_VERSION = "uc042-final-pack/1.0"
ASSEMBLER_VERSION = "uc042-final-assembler/1.0"
SNAPSHOT_VERSION = "uc042-review-snapshot/1.0"
RENDERER_VERSION = "uc042-final-report-renderer/1.0"
SUMMARY_SCHEMA_VERSION = "uc042-closing-summary/1.0"
SUMMARY_PROMPT_VERSION = "uc042-closing-summary-prompt/1.0"
SUMMARY_INPUT_VERSION = "uc042-closing-summary-input/1.0"
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


class ClosingSummary(_Strict):
    """The closing-summary record supplied to the assembler. GENERATED carries validated output; UNAVAILABLE records an
    explicit failure (never a substitute text)."""
    status: Literal["GENERATED", "UNAVAILABLE"]
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
        return self
