"""Phase 3B-4 - provider gateway: feature flag, budget gate, deduplication, timeout + one retry, audited calls.

`ProposalGateway.propose(result, registry)` wraps the Phase 3B-1 `run_proposal`:
  1. the 3B-1 eligibility gate (mapped files, unconfirmed or conflicting categories never reach a proposer);
  2. deduplication - an identical PENDING proposal (exact ordered headers + category + registry definition hash +
     prompt version) is returned again, no new call;
  3. the budget gate - AI disabled, provider unavailable, owner limits not configured, or a daily limit reached:
     DENIED, no call, the file goes to manual review;
  4. the call itself with a timeout and at most `max_retries` retries on provider errors/timeouts;
  5. an audit record for every call attempt (provider, model, prompt/schema version, registry hash, input/output
     hashes, usage, duration, retries, status, error category). Credentials are never part of a record.
Any failure leaves the deterministic result untouched and returns `manual_review_required=True`.

No live provider exists: `DisabledLiveProvider` always raises and imports no network library.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..mapping.governed import definition_sha256, header_fingerprint
from ..mapping.proposal_runner import ProposalOutcome, eligibility, run_proposal
from ..review.audit import AuditLog
from .config import AIConfig
from .prompting import PROMPT_VERSION, SCHEMA_VERSION, payload_sha256, render


class ProviderUnavailable(RuntimeError):
    pass


class ProviderTimeout(RuntimeError):
    pass


class DisabledLiveProvider:
    """Placeholder for a future live provider adapter. Provider, model, region and data policy are owner decisions;
    until they are made this adapter cannot be called and performs no network access."""
    provider_id = "live-provider (NOT CONFIGURED - owner decision pending)"
    is_live = True

    def propose(self, request) -> str:
        raise ProviderUnavailable("no live provider is configured or authorised")


@dataclass
class GateDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


class UsageLedger:
    """Per-day call/token/cost counters (JSON file or memory). Cost is recorded only when a provider reports it."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._data = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else {}

    def today(self, day: str) -> dict:
        return self._data.get(day, {"calls": 0, "tokens": 0, "cost": 0.0, "cost_measured": False})

    def record(self, day: str, usage: dict | None) -> None:
        d = self.today(day)
        d["calls"] += 1
        if usage:
            d["tokens"] += int(usage.get("total_tokens", 0))
            if "cost" in usage:
                d["cost"] += float(usage["cost"])
                d["cost_measured"] = True
        self._data[day] = d
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")


class BudgetGate:
    def check(self, config: AIConfig, proposer, ledger: UsageLedger, day: str) -> GateDecision:
        reasons = []
        if not config.enabled:
            reasons.append("AI mapping is disabled (AI_MAPPING_ENABLED is off)")
        if config.is_test_stub:
            if getattr(proposer, "provider_id", "").startswith("recorded_stub"):
                return GateDecision(not reasons, reasons)       # test stub: no live budget is consumed
            reasons.append("AI_PROVIDER=recorded_stub but the proposer is not the recorded test stub")
            return GateDecision(False, reasons)
        if getattr(proposer, "is_live", False) is not True:
            reasons.append("the proposer is not a live provider adapter")
        if isinstance(proposer, DisabledLiveProvider):
            reasons.append("live provider unavailable: not configured or authorised")
        missing = [n for n, v in (("AI_PROVIDER", config.provider), ("AI_MODEL", config.model),
                                  ("AI_REGION", config.region), ("AI_MAX_OUTPUT_TOKENS", config.max_output_tokens),
                                  ("AI_MAX_CALLS_PER_DAY", config.max_calls_per_day),
                                  ("AI_MAX_COST_PER_DAY", config.max_cost_per_day)) if v in (None, 0)]
        if missing:
            reasons.append(f"owner-approved limits not configured: {missing}")
        if config.store:
            reasons.append("AI_STORE must be false")
        used = ledger.today(day)
        if config.max_calls_per_day and used["calls"] >= config.max_calls_per_day:
            reasons.append(f"daily call limit reached ({used['calls']}/{config.max_calls_per_day})")
        if config.max_cost_per_day is not None and used["cost"] >= config.max_cost_per_day:
            reasons.append("daily cost limit reached")
        return GateDecision(not reasons, reasons)


class DedupIndex:
    """Pending proposals by (exact header fingerprint, category, registry definition hash, prompt version)."""

    def __init__(self):
        self._pending: dict[tuple, ProposalOutcome] = {}
        self._text: dict[str, str] = {}            # proposal_id -> the provider's raw response text (DEF-SV-01 replay)

    @staticmethod
    def key(headers: list[str], category: str, registry_hash: str, prompt_version: str = PROMPT_VERSION) -> tuple:
        return (header_fingerprint(headers), category, registry_hash, prompt_version)

    def get(self, key):
        return self._pending.get(key)

    def put(self, key, outcome: ProposalOutcome, response_text: str | None = None) -> None:
        self._pending[key] = outcome
        if response_text is not None:
            self._text[outcome.record.proposal_id] = response_text

    def response_text(self, proposal_id: str) -> str | None:
        return self._text.get(proposal_id)

    def close(self, proposal_id: str) -> None:
        """A proposal leaves 'pending' once its review is closed (approved / rejected / revised)."""
        self._pending = {k: v for k, v in self._pending.items() if v.record.proposal_id != proposal_id}
        self._text.pop(proposal_id, None)


class _GuardedProposer:
    """Timeout + retries around a proposer; collects call metadata for the audit record."""

    def __init__(self, inner, config: AIConfig):
        self.inner, self.config = inner, config
        self.provider_id = getattr(inner, "provider_id", type(inner).__name__)
        self.attempts, self.status, self.error, self.duration_ms = 0, "NOT_CALLED", None, 0
        self.input_sha256 = self.output_sha256 = None
        self.usage = None
        self.text = None

    def propose(self, request) -> str:
        payload = render(request, self.config.send_value_shapes)
        self.input_sha256 = payload_sha256(payload)
        if not self.config.send_value_shapes:
            # Data minimisation (owner decision pending): the proposer itself never receives value shapes either.
            request = request.model_copy(update={"unresolved_columns": [
                c.model_copy(update={"value_shapes": []}) for c in request.unresolved_columns]})
        start = time.monotonic()
        last = None
        for attempt in range(1 + max(0, self.config.max_retries)):
            self.attempts = attempt + 1
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(self.inner.propose, request)
            try:
                text = fut.result(timeout=self.config.timeout_seconds)
                ex.shutdown(wait=False)
                self.status, self.duration_ms = "OK", int((time.monotonic() - start) * 1000)
                self.output_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(text, str) else None
                self.usage = getattr(self.inner, "last_usage", None)
                self.text = text if isinstance(text, str) else None
                return text
            except concurrent.futures.TimeoutError:
                ex.shutdown(wait=False)
                last = ProviderTimeout(f"no response within {self.config.timeout_seconds}s")
                self.status, self.error = "TIMEOUT", "timeout"
            except Exception as exc:          # provider failure: retry once, never partial
                ex.shutdown(wait=False)
                last = exc
                self.status, self.error = "FAILED", type(exc).__name__
        self.duration_ms = int((time.monotonic() - start) * 1000)
        raise last


@dataclass
class ProposalGateway:
    proposer: object
    config: AIConfig
    log: AuditLog
    ledger: UsageLedger = field(default_factory=UsageLedger)
    dedup: DedupIndex = field(default_factory=DedupIndex)
    gate: BudgetGate = field(default_factory=BudgetGate)

    def _audit(self, status, registry_hash, category, result, **extra):
        self.log.append("PROVIDER_CALL", intake_id=result.metadata.evidence_id, source_sha256=result.metadata.sha256,
                        proposal_id=extra.pop("proposal_id", None),
                        details={"status": status, "provider_id": getattr(self.proposer, "provider_id", None),
                                 "model": self.config.model, "prompt_version": PROMPT_VERSION,
                                 "schema_version": SCHEMA_VERSION, "registry_definition_sha256": registry_hash,
                                 "category": category, **extra})

    def propose(self, result, registry, rules=None) -> ProposalOutcome:
        ok, reason, schema = eligibility(result, registry)
        if not ok:
            return ProposalOutcome(eligible=False, reason=reason)
        reg_hash = definition_sha256(schema)
        key = DedupIndex.key(list(result.csv_extraction.raw_headers), schema.category, reg_hash)
        pending = self.dedup.get(key)
        if pending is not None:
            return self._reuse(pending, result, registry, rules)
        day = datetime.now(timezone.utc).date().isoformat()
        decision = self.gate.check(self.config, self.proposer, self.ledger, day)
        if not decision.allowed:
            self._audit("DENIED", reg_hash, schema.category, result, error_category="budget_gate",
                        reasons=decision.reasons)
            return ProposalOutcome(eligible=True, reason="proposal not requested: " + "; ".join(decision.reasons),
                                   manual_review_required=True, gate_reasons=decision.reasons)
        guarded = _GuardedProposer(self.proposer, self.config)
        outcome = run_proposal(result, registry, guarded, rules=rules)
        if guarded.attempts:
            self.ledger.record(day, guarded.usage)
        err = outcome.record.response_error if outcome.record else None
        status = guarded.status if guarded.status != "OK" else ("MALFORMED" if err else "OK")
        self._audit(status, reg_hash, schema.category, result, proposal_id=outcome.record.proposal_id if outcome.record else None,
                    input_sha256=guarded.input_sha256, output_sha256=guarded.output_sha256, usage=guarded.usage,
                    duration_ms=guarded.duration_ms, retry_count=max(0, guarded.attempts - 1),
                    error_category=guarded.error or ("malformed_response" if err else None))
        outcome.manual_review_required = bool(err)
        if outcome.record is not None and not err:
            self.dedup.put(key, outcome, guarded.text)
        return outcome

    def _reuse(self, pending: ProposalOutcome, result, registry, rules) -> ProposalOutcome:
        """DEF-SV-01 fix. A deduplicated upload reuses the pending proposal's RESPONSE (no provider call) but never the
        first upload's identity or validation: the cached response text is replayed through the existing run_proposal,
        so the request and record carry THIS upload's intake ID and SHA-256 and the deterministic validator re-checks
        the proposal against THIS file's values. The proposal ID is kept (same provider response)."""
        pid = pending.record.proposal_id
        text = self.dedup.response_text(pid)
        if text is None:                        # no cached text (e.g. an outcome put without it): a fresh call is safer
            self.dedup.close(pid)
            return self.propose(result, registry, rules)

        class _Replay:
            provider_id = pending.record.provider_id

            def propose(self, request):
                return text
        oc = run_proposal(result, registry, _Replay(), rules=rules)
        if oc.record is not None:
            oc.record = oc.record.model_copy(update={"proposal_id": pid})
        self.log.append("PROPOSAL_DEDUPLICATED", proposal_id=pid, intake_id=result.metadata.evidence_id,
                        source_sha256=result.metadata.sha256,
                        details={"reused_for_intake": result.metadata.evidence_id,
                                 "first_intake": pending.record.intake_id,
                                 "revalidated_for_this_upload": oc.record is not None})
        oc.proposer_called, oc.deduplicated = False, True
        oc.reason = "identical pending proposal response re-validated for this upload (no provider call)"
        oc.manual_review_required = pending.manual_review_required or bool(oc.record and oc.record.response_error)
        return oc
