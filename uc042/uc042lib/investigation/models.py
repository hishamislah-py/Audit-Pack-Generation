"""Structured investigation output (Pydantic). The LLM must return LLMInvestigationOutput; Python wraps it into
InvestigationResult with identity, provenance and validation fields that the model cannot set."""
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, model_serializer

EvidenceAssessment = Literal["EVIDENCE_SUFFICIENT", "PARTIALLY_SUFFICIENT", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _explanation(description, min_length=10, max_length=None):
    """Findings schema 1.4 field. The JSON schema given to the model is a required, non-empty string (strict structured
    output), while Python accepts None: artefacts written under schema 1.3 or earlier never had the field, and None means
    'not supplied' there. Nothing is ever back-filled."""
    schema = {"type": "string", "minLength": min_length, "description": description}
    if max_length:
        schema["maxLength"] = max_length
    return Annotated[Optional[str], WithJsonSchema(schema)]


class ConfirmedFinding(_Strict):
    finding_id: str = Field(pattern=r"^F-\d{2}$")
    claim: str = Field(min_length=10)
    explanation: str
    evidence_ids: list[str] = Field(min_length=1, description="Citation IDs from the evidence packet")
    supporting_records: list[str] = Field(default_factory=list, description="Source record evidence IDs relied upon")
    title: _explanation("Short factual title of what the records show", 5, 160) = Field(default=None, min_length=5, max_length=160)
    audit_relevance: _explanation("Why this observation matters to the discrepancy") = Field(default=None, min_length=10)
    establishes: _explanation("What the cited evidence establishes, and nothing more") = Field(default=None, min_length=10)
    does_not_establish: _explanation("What the evidence does not establish (for example the cause)") = Field(default=None, min_length=10)


class Hypothesis(_Strict):
    hypothesis_id: str = Field(pattern=r"^H-\d{2}$")
    possible_explanation: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradictory_evidence: list[str] = Field(default_factory=list)
    limitations: str
    status: Literal["HYPOTHESIS"]
    rationale: _explanation("Why this possible explanation was considered") = Field(default=None, min_length=10)


class ContradictoryItem(_Strict):
    """Two pieces of evidence about the same subject, period, account/scope and measure that materially disagree."""
    # compared_evidence and same_measure_and_scope are required in model output (strict schema); their defaults only keep
    # artefacts written under findings schema 1.2 and earlier readable.
    item_id: str = Field(pattern=r"^C-\d{2}$")
    description: str
    evidence_ids: list[str] = Field(min_length=1)
    compared_evidence: list[str] = Field(default_factory=list, min_length=2, max_length=2,
                                         description="Exactly the two evidence IDs whose values disagree")
    same_measure_and_scope: str = Field(default_factory=str, min_length=20,
                                        description="Why both concern the same measure, subject, period and account/scope")


class MissingEvidenceItem(_Strict):
    item_id: str = Field(pattern=r"^M-\d{2}$")
    description: str
    expected_source: str
    impact: str
    related_ids: list[str] = Field(default_factory=list, description="Packet IDs (MISS-, SEARCH-, results) describing the gap")


class NextStep(_Strict):
    step_id: str = Field(pattern=r"^S-\d{2}$")
    action: str
    rationale: str
    evidence_needed: str


class LLMInvestigationOutput(_Strict):
    """Exactly what the model must return."""
    investigation_summary: str = Field(min_length=20)
    confirmed_findings: list[ConfirmedFinding]
    hypotheses: list[Hypothesis]
    contradictory_evidence: list[ContradictoryItem]
    missing_evidence: list[MissingEvidenceItem]
    open_questions: list[str]
    recommended_next_steps: list[NextStep]
    overall_evidence_assessment: EvidenceAssessment
    evidence_references: list[str] = Field(description="Every packet ID cited anywhere in this output")


class ModelMetadata(BaseModel):
    provider: str
    model: str
    simulated: bool
    prompt_version: str
    workflow_version: str
    findings_schema_version: str
    attempts: int = 1
    usage: dict = Field(default_factory=dict)
    provider_response: dict = Field(default_factory=dict, description="Provider response/request IDs, resolved model, status")
    investigation_mode: str = ""
    tool_registry_version: str = ""
    # phase 4: what the model saw. The view is a pure function of the stored packet and this version, so an auditor can
    # regenerate it byte for byte; both are part of the investigation identity (empty for adapters that send no view).
    model_view_version: str = ""
    model_view_sha256: str = ""
    retrieval_rule_version: str = ""  # phase 6: deterministic retrieval rules (empty for fixed / tools mode)


class InvestigationResult(BaseModel):
    """Persisted artefact. Investigation completion is separate from exception resolution."""
    investigation_id: str
    pack_id: str
    pack_content_sha256: str
    exception_id: str
    original_exception_status: str
    original_review_status: str
    original_evidence_status: str
    investigation_scope: dict
    investigation_route: str
    investigation_status: Literal["COMPLETED", "FAILED"]
    exception_resolution: Literal["NOT_RESOLVED_BY_INVESTIGATION"] = "NOT_RESOLVED_BY_INVESTIGATION"
    investigation_summary: str = ""
    confirmed_findings: list[ConfirmedFinding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    contradictory_evidence: list[ContradictoryItem] = Field(default_factory=list)
    missing_evidence: list[MissingEvidenceItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recommended_next_steps: list[NextStep] = Field(default_factory=list)
    overall_evidence_assessment: EvidenceAssessment | None = None
    evidence_references: list[str] = Field(default_factory=list)
    evidence_packet_sha256: str = ""
    investigation_mode: Literal["fixed", "tools", "deterministic"] = "fixed"
    evidence_ledger_sha256: str = Field("", description="tools mode: hash of the accumulated evidence ledger (initial packet + tool results)")
    tool_summary: dict = Field(default_factory=dict, description="tools mode: calls, rounds, stop reason, tools used")
    classification_summary: dict = Field(default_factory=dict, description="Python-derived: findings by class and the kinds of evidence gap")
    model_metadata: ModelMetadata | None = None
    validation_status: Literal["VALID", "REJECTED", "NOT_VALIDATED"]
    validation_findings: list[str] = Field(default_factory=list)
    failure_reason: str = ""
    investigated_at: str = ""
    statement: str = ("AI investigation findings are an aid to human review. They do not change any deterministic control "
                      "outcome, do not resolve or close any exception, and are not a compliance opinion.")
    # The audit-run execution that produced this result (independent ZIP submissions, 17 Nov 2026): submission_id, run_id,
    # authorization_id and job_id. It is part of the stored findings and therefore of the investigation identity, so every
    # execution is its own artefact: an identical result from another submission, run or job never shares (or is compared
    # with) this one. Empty for investigations outside a submission run; it is then omitted from the stored findings, which
    # keeps their bytes and identity exactly as before.
    execution: dict = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _omit_empty_execution(self, handler):
        data = handler(self)
        if isinstance(data, dict) and not data.get("execution"):
            data.pop("execution", None)
        return data
