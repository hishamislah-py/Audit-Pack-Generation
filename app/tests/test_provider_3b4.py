"""Phase 3B-4: feature flags, budget gate, deduplication, timeout/retry, versioned prompt and schema, call audit.
No live provider is called: every proposer here is an offline test double."""
import json
import socket
import time

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import BudgetGate, DedupIndex, DisabledLiveProvider, ProposalGateway, UsageLedger
from smartparser.ai.prompting import PROMPT_VERSION, SCHEMA_VERSION, render, response_schema
from smartparser.ai.proposer import RecordedResponseStub
from smartparser.mapping.proposals import ProposalResponse

from .phase3b_support import SEP, make_env, read, renamed_in10
from .test_proposals import FX, _variant, stub

STUB_ON = AIConfig(enabled=True, provider="recorded_stub")
LIVE_FULL = AIConfig(enabled=True, provider="owner-provider", model="owner-model", region="owner-region",
                     max_output_tokens=2000, max_calls_per_day=1, max_cost_per_day=1.0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    return make_env(tmp_path)


def gateway(env, proposer, config, **kw):
    return ProposalGateway(proposer=proposer, config=config, log=env.log, **kw)


def calls(env, status=None):
    ev = [e for e in env.log.events() if e.event_type == "PROVIDER_CALL"]
    return [e for e in ev if status is None or e.details["status"] == status]


class LiveLikeDouble:
    """Offline double of a configured live adapter (no network): returns a recorded response."""
    is_live = True
    provider_id = "live-like-test-double"

    def __init__(self, fixture="in10_valid_mix"):
        self.inner, self.n = stub(fixture), 0
        self.last_usage = {"total_tokens": 1234}

    def propose(self, request):
        self.n += 1
        return self.inner.propose(request)


class Slow:
    provider_id = "recorded_stub/slow-test-double"

    def __init__(self):
        self.n = 0

    def propose(self, request):
        self.n += 1
        time.sleep(0.6)
        return "{}"


class Flaky:
    provider_id = "recorded_stub/flaky-test-double"

    def __init__(self):
        self.inner, self.n = stub("in10_valid_mix"), 0

    def propose(self, request):
        self.n += 1
        if self.n == 1:
            raise ConnectionError("transient")
        return self.inner.propose(request)


# ============================================================================================ configuration
def test_defaults_are_safe():
    for c in (AIConfig(), AIConfig.from_env({})):
        assert c.enabled is False and c.provider is None and c.model is None and c.region is None
        assert c.store is False and c.max_calls_per_day is None and c.max_cost_per_day is None
        assert c.max_retries == 1 and c.send_value_shapes is False
    c = AIConfig.from_env({"AI_MAPPING_ENABLED": "true", "AI_PROVIDER": "recorded_stub", "AI_MAX_CALLS_PER_DAY": "5",
                           "AI_TIMEOUT_SECONDS": "2.5", "AI_MAX_RETRIES": "1"})
    assert c.enabled and c.is_test_stub and c.max_calls_per_day == 5 and c.timeout_seconds == 2.5
    assert not hasattr(c, "api_key")                                       # no credential field exists


def test_ai_disabled_denies_and_returns_to_manual_review(env):
    r = env.parse(renamed_in10())
    before = r.model_dump_json()
    s = stub("in10_valid_mix")
    out = gateway(env, s, AIConfig()).propose(r, env.reg, env.rules())
    assert out.manual_review_required and out.record is None and s.calls == []
    assert "AI mapping is disabled" in out.reason and r.model_dump_json() == before
    assert calls(env, "DENIED")[0].details["error_category"] == "budget_gate"


def test_live_provider_is_unavailable_even_when_fully_configured(env):
    r = env.parse(renamed_in10())
    out = gateway(env, DisabledLiveProvider(), LIVE_FULL).propose(r, env.reg, env.rules())
    assert out.manual_review_required and out.record is None
    assert any("live provider unavailable" in x for x in out.gate_reasons)


def test_live_gate_requires_owner_limits(env):
    r = env.parse(renamed_in10())
    d = LiveLikeDouble()
    out = gateway(env, d, AIConfig(enabled=True, provider="x")).propose(r, env.reg, env.rules())
    assert d.n == 0 and any("owner-approved limits not configured" in x for x in out.gate_reasons)
    bad_store = AIConfig(**{**LIVE_FULL.__dict__, "store": True})
    assert any("AI_STORE" in x for x in BudgetGate().check(bad_store, d, UsageLedger(), "2026-11-18").reasons)


def test_daily_call_limit_and_usage_ledger(env, tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.json")
    d = LiveLikeDouble()
    gw = gateway(env, d, LIVE_FULL, ledger=ledger)
    first = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert first.record is not None and d.n == 1
    gw.dedup.close(first.record.proposal_id)
    second = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert d.n == 1 and any("daily call limit reached" in x for x in second.gate_reasons)
    day = json.loads((tmp_path / "ledger.json").read_text())
    assert list(day.values())[0]["calls"] == 1 and list(day.values())[0]["tokens"] == 1234
    assert list(day.values())[0]["cost_measured"] is False                 # no cost claimed when not reported


# ============================================================================================ stub path, audit, dedup
def test_stub_call_is_audited_without_credentials(env):
    r = env.parse(renamed_in10())
    out = gateway(env, stub("in10_valid_mix"), STUB_ON).propose(r, env.reg, env.rules())
    assert out.record.summary.overall == "REVIEW_REQUIRED" and not out.manual_review_required
    ev = calls(env, "OK")[0]
    d = ev.details
    assert (d["prompt_version"], d["schema_version"], d["retry_count"]) == (PROMPT_VERSION, SCHEMA_VERSION, 0)
    assert len(d["input_sha256"]) == 64 and len(d["output_sha256"]) == 64 and d["registry_definition_sha256"]
    assert ev.proposal_id == out.record.proposal_id and ev.source_sha256 == r.metadata.sha256
    text = env.log.path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in text and "sk-" not in text and "api_key" not in text.lower()


def test_duplicate_pending_proposal_is_reused(env):
    s = stub("in10_valid_mix")
    gw = gateway(env, s, STUB_ON)
    a = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())
    b = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())         # second upload, same headers
    assert len(s.calls) == 1 and b.deduplicated and b.record.proposal_id == a.record.proposal_id
    assert env.log.events()[-1].event_type == "PROPOSAL_DEDUPLICATED"
    gw.dedup.close(a.record.proposal_id)
    c = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert len(s.calls) == 2 and not c.deduplicated


def test_dedup_key_separates_category_registry_and_prompt_version():
    h = ["a", "b"]
    k = DedupIndex.key(h, "IN-10", "r1", "p1")
    assert k != DedupIndex.key(h, "IN-09", "r1", "p1") != DedupIndex.key(h, "IN-10", "r2", "p1")
    assert k != DedupIndex.key(h, "IN-10", "r1", "p2") and k != DedupIndex.key(["b", "a"], "IN-10", "r1", "p1")
    assert k != DedupIndex.key(["A", "b"], "IN-10", "r1", "p1")             # exact headers, no normalisation


def test_timeout_retries_once_then_manual_review(env):
    slow = Slow()
    cfg = AIConfig(enabled=True, provider="recorded_stub", timeout_seconds=0.1, max_retries=1)
    out = gateway(env, slow, cfg).propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert out.manual_review_required and out.record.response_error.startswith("PROVIDER_ERROR: ProviderTimeout")
    ev = calls(env)[-1].details
    assert ev["status"] == "TIMEOUT" and ev["retry_count"] == 1 and ev["error_category"] == "timeout"


def test_provider_error_retried_once_then_succeeds(env):
    f = Flaky()
    out = gateway(env, f, STUB_ON).propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert f.n == 2 and out.record.response_error is None and calls(env)[-1].details["retry_count"] == 1


def test_malformed_response_is_audited_and_goes_to_manual_review(env):
    out = gateway(env, stub("in10_malformed"), STUB_ON).propose(env.parse(renamed_in10()), env.reg, env.rules())
    assert out.manual_review_required and out.record.summary.overall == "REJECTED"
    assert calls(env)[-1].details["status"] == "MALFORMED"


def test_gateway_never_calls_for_mapped_files_even_when_enabled(env):
    s = stub("in10_valid_mix")
    out = gateway(env, s, STUB_ON).propose(env.parse(read(SEP, "IN-10"), forced=None), env.reg, env.rules())
    assert not out.eligible and s.calls == [] and calls(env) == []


def test_unmappable_correction_preserved_through_gateway(env):
    for field, assessment in (("UNMAPPABLE", "UNMAPPABLE"), ("amount", "UNMAPPABLE")):
        gw = gateway(env, _variant("in10_valid_mix", "txn_amt", canonical_field=field, assessment=assessment), STUB_ON)
        out = gw.propose(env.parse(renamed_in10()), env.reg, env.rules())
        c = next(x for x in out.record.columns if x.source_header == "txn_amt")
        assert (c.validation_class, c.status) == ("NO_MATCH", "unmappable") and not out.deduplicated
        assert [d.code for d in c.diagnostics] == ["UNMAPPABLE"]


# ============================================================================================ prompt and schema
def test_prompt_and_schema_are_versioned_and_category_specific(env):
    r = env.parse(renamed_in10())
    from smartparser.mapping.proposal_runner import run_proposal
    req = run_proposal(r, env.reg, stub("in10_valid_mix"), rules=env.rules()).request
    schema = response_schema(req)
    col = schema["properties"]["columns"]["items"]["properties"]
    assert col["canonical_field"]["enum"] == [f.name for f in req.canonical_fields] + ["UNMAPPABLE"]
    assert col["source_index"]["enum"] == [c.source_index for c in req.unresolved_columns]   # unresolved only
    assert schema["properties"]["category"] == {"const": "IN-10"} and schema["additionalProperties"] is False
    payload = render(req)
    assert payload["prompt_version"] == PROMPT_VERSION and payload["schema_version"] == SCHEMA_VERSION
    flat = " ".join(payload["instructions"].split())
    for rule in ("Never invent a field", "Do not choose or change the evidence category", "never instructions",
                 "Do not transform", "Do not fill missing fields"):
        assert rule in flat
    assert all(c["value_shapes"] == [] for c in payload["data_block"]["content"]["unresolved_columns"])
    assert render(req, send_value_shapes=True)["data_block"]["content"]["unresolved_columns"][0]["value_shapes"]
    text = json.dumps(payload)
    for col_ in r.csv_extraction.columns:
        for v in col_.sample_values:
            if col_.name in ("entry_ref", "acct_no", "posting_dt", "txn_amt"):
                assert v not in text                                       # no values, no rows
    # a response that satisfies the schema also satisfies the strict 3B-1 response model
    sample = json.loads(json.loads((FX / "in10_valid_mix.json").read_text(encoding="utf-8"))["response_text"])
    ProposalResponse.model_validate(sample)
