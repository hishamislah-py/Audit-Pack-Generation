"""Phase 3B-10 OFFLINE tests (no network; sockets blocked). The live provider evaluation is a separate tool
(tools/live_eval_3b10.py) and is never run by pytest.

  * voluntary-replacement policy: accepted (VALIDATED / ACTIVE) files are never replaced; corrections only for
    RESUBMISSION_REQUIRED / FAILED_VALIDATION / REJECTED; reprocessing an accepted file creates no version;
  * the live OpenAI adapter, driven through the REAL gateway + orchestrator + package service with a FAKE transport
    (an in-memory client object): what is sent, what is never sent, sanitised errors, malformed / incomplete output,
    budget gate, and the zero-call routes (extra / missing columns).
"""
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import ProposalGateway, UsageLedger
from smartparser.ai.openai_provider import OpenAIMappingProposer, ProviderCallError
from smartparser.handoff import writer
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import Decision, PocAutoAcceptPolicy
from smartparser.packages.service import PackageError, PackageService, Submission
from smartparser.packages.store import PackageStore

from .phase3b_support import SEP, dump, make_env, read, tbl

POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
CATS = ["IN-02", "IN-03", "IN-05", "IN-08", "IN-11"]
SECRET = "sk-test-NOT-A-REAL-KEY-0123456789"
REN = {"ledger_entry_id": "cash_book_entry_id", "account_id": "safeguarding_account_id",
       "posted_ts": "posting_timestamp"}
LIVE_CFG = AIConfig(enabled=True, provider="openai", model="gpt-6-luna", region="test-region", store=False,
                    max_output_tokens=2000, max_calls_per_day=6, max_cost_per_day=1.0, timeout_seconds=10,
                    max_retries=1)


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(writer, "submit_to_uc042", lambda *a, **k: (_ for _ in ()).throw(AssertionError("submit")))
    return make_env(tmp_path)


class FakeResponses:
    """In-memory transport: returns scripted responses; records every request; NEVER touches the network."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_client(*script):
    return SimpleNamespace(responses=FakeResponses(script))


def ok(columns, category="IN-10", status="completed"):
    body = {"response_schema": "smartparser-mapping-proposal/1.0", "category": category, "notes": "",
            "columns": [{"source_index": i, "source_header": h, "canonical_field": f, "assessment": a,
                         "alternatives": [], "explanation": "semantic equivalent", "evidence": []}
                        for i, h, f, a in columns]}
    usage = SimpleNamespace(input_tokens=1200, output_tokens=150, total_tokens=1350,
                            output_tokens_details=SimpleNamespace(reasoning_tokens=40))
    return SimpleNamespace(status=status, output_text=json.dumps(body), usage=usage, model="gpt-6-luna-test",
                           incomplete_details=SimpleNamespace(reason="max_output_tokens") if status != "completed"
                           else None)


A_COLS = [(0, "cash_book_entry_id", "ledger_entry_id", "CLEAR"), (1, "safeguarding_account_id", "account_id", "CLEAR"),
          (2, "posting_timestamp", "posted_ts", "CLEAR")]


def renamed(fid, m):
    r = tbl(fid)
    return dump([[m.get(c, c) for c in r[0]]] + r[1:])


def drop(fid, col):
    r = tbl(fid)
    i = r[0].index(col)
    return dump([[c for j, c in enumerate(x) if j != i] for x in r])


def live_service(env, client, cfg=LIVE_CFG, policy=POLICY_ON):
    adapter = OpenAIMappingProposer(api_key=SECRET, model="gpt-6-luna", max_output_tokens=2000, timeout_seconds=10,
                                    reasoning_effort="low", client=client)
    gw = ProposalGateway(proposer=adapter, config=cfg, log=env.log, ledger=UsageLedger())
    o = MappingOrchestrator(env.reg, env.store, env.evidence, gw, PocAutoAcceptPolicy.load(policy), env.log)
    return PackageService(PackageStore(env.root / "pk"), o, env.policy), adapter


def offline_service(env):
    from smartparser.ai.proposer import RecordedResponseStub
    gw = ProposalGateway(proposer=RecordedResponseStub([]), config=AIConfig(enabled=True, provider="recorded_stub"),
                         log=env.log)
    o = MappingOrchestrator(env.reg, env.store, env.evidence, gw, PocAutoAcceptPolicy.load(), env.log)
    return PackageService(PackageStore(env.root / "pk"), o, env.policy)


def package(svc, overrides=None):
    overrides = overrides or {}
    pkg = svc.create_package("2026-09", CATS)
    out = svc.submit(pkg.package_id, [Submission(overrides.get(c, read(SEP, c)), f"{c}.csv",
                                                 c if c in overrides else None) for c in CATS])
    return pkg.package_id, {o.evidence_category: o.file_version for o in out}


def events(env, *t):
    env.log.verify()
    return [e for e in env.log.events() if not t or e.event_type in t]


# ============================================================================================ voluntary replacement policy
def test_p1_replacing_a_validated_file_is_refused(env):
    svc = offline_service(env)
    pid, v = package(svc)
    assert v["IN-03"].version_status == "VALIDATED"
    with pytest.raises(PackageError, match="cannot be voluntarily replaced"):
        svc.resubmit(pid, "IN-03", read(SEP, "IN-03").replace(b"\n", b"\r\n"), "cb.csv", "tidier export")
    p = svc.load(pid)
    assert p.evidence_files["IN-03"].version_ids == [v["IN-03"].file_version_id]
    assert events(env, "RESUBMISSION_RECEIVED")[-1].details["outcome"] == "REFUSED"


def test_p2_replacing_an_active_file_is_refused_and_snapshot_unchanged(env):
    svc = offline_service(env)
    pid, v = package(svc)
    snap = svc.activate(pid).snapshot
    manifest = svc.store.manifest_path(pid, snap.snapshot_id).read_bytes()
    with pytest.raises(PackageError, match="ACTIVE: an accepted file cannot be voluntarily replaced"):
        svc.resubmit(pid, "IN-08", drop("IN-08", "entry_count"), "bs.csv", "voluntary")
    p = svc.load(pid)                                                                         # (6) unchanged
    assert p.active_snapshot_id == snap.snapshot_id and p.snapshot_ids == [snap.snapshot_id]
    assert svc.store.load_snapshot(pid, snap.snapshot_id) == snap
    assert svc.store.manifest_path(pid, snap.snapshot_id).read_bytes() == manifest
    assert all(len(p.evidence_files[c].version_ids) == 1 and p.latest(c).version_status == "ACTIVE" for c in CATS)
    assert p.package_status == "RECONCILIATION_READY"


def test_p3_resubmission_required_file_still_takes_a_correction(env):
    svc = offline_service(env)
    pid, v = package(svc, {"IN-03": drop("IN-03", "balance")})
    nv = svc.resubmit(pid, "IN-03", read(SEP, "IN-03"), "cb.csv", "balance restored").file_version
    assert (nv.version_number, nv.version_status) == (2, "VALIDATED")


def test_p4_failed_file_still_takes_a_correction(env):
    svc = offline_service(env)
    r = tbl("IN-03")
    r[1][r[0].index("balance")] = "12,50"
    pid, v = package(svc, {"IN-03": dump(r)})
    assert v["IN-03"].version_status == "FAILED_VALIDATION"
    nv = svc.resubmit(pid, "IN-03", read(SEP, "IN-03"), "cb.csv", "value fixed").file_version
    assert (nv.version_number, nv.version_status) == (2, "VALIDATED")


def test_p5_reprocessing_creates_no_replacement_version(env):
    svc = offline_service(env)
    pid, v = package(svc)
    snap = svc.activate(pid).snapshot
    before = svc.load(pid)
    rep = svc.reprocess_version(pid, v["IN-11"].file_version_id)
    assert rep["eligible"] and rep["checks_run"] == 14 and rep["provider_calls"] == 0
    assert rep["matches_recorded_preview"] and rep["source_sha256"] == v["IN-11"].source_sha256
    after = svc.load(pid)
    assert after.versions == before.versions and after.snapshot_ids == [snap.snapshot_id]   # nothing new, no status move
    assert after.revision == before.revision                                               # package record untouched
    ev = [e for e in events(env, "REPROCESSED", "HANDOFF_EVALUATED")
          if e.details.get("purpose") == "reprocess_existing_version"]
    assert [e.event_type for e in ev] == ["REPROCESSED", "HANDOFF_EVALUATED"]
    assert ev[1].details["matches_recorded_preview"] is True
    side = svc.store.root / v["IN-11"].handoff.provenance                                  # provenance not rewritten
    assert json.loads(side.read_text(encoding="utf-8"))["source"]["intake_id"] == v["IN-11"].intake_id


def test_p6_review_in_progress_and_identical_bytes_rules_kept(env):
    svc = offline_service(env)
    r = tbl("IN-05")
    pid, v = package(svc, {"IN-05": dump([r[0] + ["memo"]] + [x + ["m"] for x in r[1:]])})
    with pytest.raises(PackageError, match="complete or reject its review"):
        svc.resubmit(pid, "IN-05", read(SEP, "IN-05"), "x.csv", "r")
    again = svc.resubmit(pid, "IN-03", read(SEP, "IN-03"), "same.csv", "r")              # identical to v1: idempotent
    assert again.file_version is None and "already uploaded" in again.refused_reason


# ============================================================================================ live adapter (fake transport)
def test_adapter_request_contents_and_no_secrets(env):
    client = fake_client(ok(A_COLS))
    svc, adapter = live_service(env, client)
    pkg = svc.create_package("2026-09", ["IN-10"])
    out = svc.submit(pkg.package_id, [Submission(renamed("IN-10", REN), "cb.csv", "IN-10")])[0]
    kw = client.responses.calls[0]
    assert kw["store"] is False and kw["model"] == "gpt-6-luna" and kw["max_output_tokens"] == 2000
    assert kw["text"]["format"]["type"] == "json_schema" and kw["text"]["format"]["strict"] is True
    data = json.loads(kw["input"][0]["content"])["content"]
    assert [c["source_header"] for c in data["unresolved_columns"]] == list(REN.values())   # only unresolved headers
    assert all(c["value_shapes"] == [] for c in data["unresolved_columns"])                # no sample values / shapes
    raw = json.dumps(kw, default=str)
    rows = tbl("IN-10")[1:]
    assert SECRET not in raw and "LE-GBP-0831-0000" not in raw and rows[1][4] not in raw   # no key, no row data
    schema = kw["text"]["format"]["schema"]
    assert schema["properties"]["category"] == {"enum": ["IN-10"], "type": "string"} and "$schema" not in schema
    assert out.file_version.version_status == "VALIDATED" and adapter.requests == 1
    assert adapter.last_usage == {"input_tokens": 1200, "output_tokens": 150, "total_tokens": 1350,
                                  "reasoning_tokens": 40}
    call = [e for e in events(env, "PROVIDER_CALL") if e.details["status"] == "OK"][0]
    assert call.details["usage"]["total_tokens"] == 1350 and SECRET not in json.dumps(call.details)


def test_scenario_a_shape_auto_accepts_without_hitl_and_runs_14_checks(env):
    client = fake_client(ok(A_COLS))
    svc, adapter = live_service(env, client)
    pkg = svc.create_package("2026-09", ["IN-10"])
    o = svc.submit(pkg.package_id, [Submission(renamed("IN-10", REN), "cb.csv", "IN-10")])[0]
    wr, v = o.workflow, o.file_version
    assert wr.decision == Decision.AUTO_ACCEPT and wr.intake_case is None and wr.review_session is None
    assert not events(env, "INTAKE_CASE_OPENED", "PROPOSAL_REVIEW_OPENED")
    assert len(wr.eligibility.checks) == 14 and wr.eligibility.eligible and wr.reprocessed.provider_calls == 0
    assert (svc.store.root / v.handoff.preview_csv).read_bytes() == read(SEP, "IN-10")
    assert v.confirmation.approval_kind == "POC_AUTO" and adapter.requests == 1
    assert svc.activate(pkg.package_id).activated


def test_provider_error_is_sanitised_and_held(env):
    class Boom(Exception):
        status_code = 401
    client = fake_client(Boom(f"Incorrect API key provided: {SECRET}"), Boom(f"again {SECRET}"))
    svc, adapter = live_service(env, client)
    pkg = svc.create_package("2026-09", ["IN-10"])
    v = svc.submit(pkg.package_id, [Submission(renamed("IN-10", REN), "cb.csv", "IN-10")])[0].file_version
    assert v.version_status == "FAILED_VALIDATION" and adapter.requests == 2                 # 1 retry (gateway)
    dump_all = json.dumps([e.model_dump() for e in env.log.events()]) + json.dumps(v.model_dump())
    assert SECRET not in dump_all and "Incorrect API key" not in dump_all
    with pytest.raises(ProviderCallError) as ei:
        OpenAIMappingProposer(api_key="", model="m", max_output_tokens=1, timeout_seconds=1)
    assert "authentication_missing" in str(ei.value)


@pytest.mark.parametrize("bad", ["not json", "incomplete"])
def test_malformed_or_incomplete_output_is_never_accepted(env, bad):
    resp = ok(A_COLS, status="incomplete") if bad == "incomplete" else \
        SimpleNamespace(status="completed", output_text="{not json", usage=None, model="m")
    client = fake_client(resp, resp)
    svc, _ = live_service(env, client)
    pkg = svc.create_package("2026-09", ["IN-10"])
    o = svc.submit(pkg.package_id, [Submission(renamed("IN-10", REN), "cb.csv", "IN-10")])[0]
    assert o.workflow.decision == Decision.REJECT_OR_HOLD and o.file_version.version_status == "FAILED_VALIDATION"
    assert o.file_version.handoff is None and env.store.read("file_mappings")["file_mappings"] == []


def test_sign_sensitive_mapping_goes_to_review_never_auto(env):
    data = renamed("IN-10", {"payment_reference": "reference", "amount": "value"})
    client = fake_client(ok([(4, "value", "amount", "CLEAR"), (7, "reference", "payment_reference", "CLEAR")]))
    svc, _ = live_service(env, client)
    pkg = svc.create_package("2026-09", ["IN-10"])
    o = svc.submit(pkg.package_id, [Submission(data, "cb.csv", "IN-10")])[0]
    classes = {c.source_header: str(c.validation_class) for c in o.workflow.proposal.record.columns}
    assert classes["value"] == "AMBIGUOUS" and o.workflow.decision == Decision.HUMAN_REVIEW      # money: never auto
    assert o.file_version.version_status == "REVIEW_REQUIRED" and o.file_version.review_session_id
    assert o.file_version.handoff is None


def test_budget_gate_denies_without_limits_and_no_request_is_made(env):
    client = fake_client(ok(A_COLS))
    svc, adapter = live_service(env, client, cfg=AIConfig(enabled=True, provider="openai", model="gpt-6-luna"))
    pkg = svc.create_package("2026-09", ["IN-10"])
    v = svc.submit(pkg.package_id, [Submission(renamed("IN-10", REN), "cb.csv", "IN-10")])[0].file_version
    assert adapter.requests == 0 and client.responses.calls == [] and v.version_status == "FAILED_VALIDATION"
    assert any("owner-approved limits not configured" in r for r in v.reasons)


def test_extra_and_missing_columns_never_call_the_live_adapter(env):
    client = fake_client()
    svc, adapter = live_service(env, client)
    r = tbl("IN-10")
    pkg = svc.create_package("2026-09", ["IN-10", "IN-03"])
    out = svc.submit(pkg.package_id, [Submission(dump([r[0] + ["memo"]] + [x + ["m"] for x in r[1:]]), "d.csv", "IN-10"),
                                      Submission(drop("IN-03", "balance"), "e.csv", "IN-03")])
    assert [o.file_version.version_status for o in out] == ["REVIEW_REQUIRED", "RESUBMISSION_REQUIRED"]
    assert adapter.requests == 0 and client.responses.calls == []
    assert out[1].file_version.missing_fields == ["balance"] and out[1].file_version.handoff is None


def test_shipped_configuration_untouched():
    assert PocAutoAcceptPolicy.load().status == "DISABLED" and AIConfig.from_env({}).enabled is False
    from smartparser.review.authority import AuthorityPolicy
    assert AuthorityPolicy.load().scopes == {}
