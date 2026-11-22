"""Fix8 Agent A: D1 (live AI mapping wiring + manual fallback), D2 (atomic confirmation audit), D3 (mapping provenance),
D4 (financial clarification + relationship checks). Offline: provider responses here come from a FAKE OpenAI client
object (a test double of the SDK client, never a live call); the live evidence is produced separately on the server."""
import base64
import json
import time
from types import SimpleNamespace

import pytest

from smartparser.ai.live_config import MappingAISettings, build_mapping_gateway, read_env_allowlist
from smartparser.ai.prompting import SCHEMA_VERSION
from smartparser.mapping import financial
from smartparser.packages import review_api
from smartparser.review.audit import AuditLog
from smartparser.review.authority import Reviewer
from smartparser.webapp import api
from smartparser.webapp.context import AppContext
from smartparser.webapp.mapping_provenance import METHODS, SCHEMA, build_mapping_provenance

from .phase3b_support import TEST_POLICY, dump, tbl
from .test_ringfence_cases import make_zip, upload

ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
FAKE_KEY = "sk-TESTONLY-not-a-real-key-0000000000"


# ------------------------------------------------------------------------------------------------ helpers
class FakeResponses:
    """Test double of `client.responses` (no network). `answer(kwargs)` returns the response text or raises."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create(self, **kw):
        self.calls.append(kw)
        text = self.answer(kw)
        return SimpleNamespace(status="completed", output_text=text, id="resp_test_1", _request_id="req_test_1",
                               model=kw["model"], incomplete_details=None,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120,
                                                     output_tokens_details=SimpleNamespace(reasoning_tokens=5)))


def proposal_text(category, cols):
    return json.dumps({"response_schema": SCHEMA_VERSION, "category": category, "notes": "",
                       "columns": [{"source_index": i, "source_header": h, "canonical_field": f, "assessment": a,
                                    "alternatives": [], "explanation": f"test double: {h} looks like {f}",
                                    "evidence": ["header"]} for i, h, f, a in cols]})


def live_ctx(tmp_path, answer, env=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    envf = tmp_path / "ai.env"
    envf.write_text(f"OPENAI_API_KEY={FAKE_KEY}\nUC042_LLM_PROVIDER=openai\nUC042_LLM_MODEL=test-model\n"
                    "UC042_DATABASE_URL=postgres://never-read\n", encoding="utf-8")
    ctx = AppContext.__new__(AppContext)
    fake = FakeResponses(answer)
    import smartparser.ai.openai_provider as op
    orig = op.OpenAIMappingProposer.__init__

    def init(self, *a, **kw):
        kw["client"] = SimpleNamespace(responses=fake)
        orig(self, *a, **kw)
    op.OpenAIMappingProposer.__init__ = init
    try:
        ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None,
                         mapping_ai=MappingAISettings(enabled=True, env_file=str(envf) if env else None,
                                                      max_calls_per_day=5, max_retries=0))
    finally:
        op.OpenAIMappingProposer.__init__ = orig
    return ctx, fake


def R(ctx, method, path, body=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], {}, body or {})


def code_of(fn):
    try:
        fn()
    except Exception as exc:
        return api.to_http(exc).code
    raise AssertionError("no error")


def settle(ctx, ref, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        d = R(ctx, "GET", f"cases/{ref}")
        if not d["progress"]["current_operation"] and (d["current_run"] or {}).get("status") != "PROCESSING":
            return d
        time.sleep(0.2)
    raise AssertionError("not settled")


def case_with(ctx, category, data, filename="upload.csv"):
    """A started case (every required file except `category`) plus `data` uploaded declared as `category`."""
    ref = R(ctx, "POST", "cases", {"customer_name": "SYNTHETIC TEST Fix8 A", "reporting_period": "2026-09",
                                   "zip_name": "s.zip",
                                   "zip_b64": base64.b64encode(make_zip(skip=(category,))).decode()})["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    settle(ctx, ref)
    upload(ctx, ref, filename, data, category)
    d = settle(ctx, ref)
    vid = next(a["file_version_id"] for a in d["progress"]["awaiting_review"] if a["category"] == category) \
        if any(a["category"] == category for a in d["progress"]["awaiting_review"]) else None
    return ref, vid, d


def ev(ctx, *types):
    return [e for e in ctx.events() if e["event_type"] in types]


IN10_REN = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt", "amount": "txn_amt"}


def renamed_in10():
    r = tbl("IN-10")
    return dump([[IN10_REN.get(c, c) for c in r[0]]] + r[1:])


# ------------------------------------------------------------------------------------------------ D1 configuration
def test_env_allowlist_and_modes_never_expose_the_key(tmp_path):
    envf = tmp_path / "x.env"
    envf.write_text(f"OPENAI_API_KEY={FAKE_KEY}\nUC042_LLM_FALLBACK_PROVIDER=groq\nUC042_DATABASE_URL=pg://x\n"
                    "UC042_LLM_MODEL=m1\n", encoding="utf-8")
    vals = read_env_allowlist(envf)
    assert set(vals) == {"OPENAI_API_KEY", "UC042_LLM_MODEL"}
    log = AuditLog(tmp_path / "a.jsonl")
    gw, mode = build_mapping_gateway(MappingAISettings(enabled=False, env_file=str(envf)), log, tmp_path / "l.json")
    assert mode["mode"] == "DISABLED"
    gw, mode = build_mapping_gateway(MappingAISettings(enabled=True, env_file=None), log, tmp_path / "l.json")
    assert mode["mode"] == "UNAVAILABLE" and "--ai-env-file" in mode["problem"]
    gw, mode = build_mapping_gateway(MappingAISettings(enabled=True, env_file=str(envf)), log, tmp_path / "l.json")
    assert mode["mode"] == "LIVE" and mode["model"] == "m1" and mode["value_shapes_sent"] is False
    assert mode["auto_accept"] is False and gw.config.send_value_shapes is False and gw.config.store is False
    assert FAKE_KEY not in json.dumps(mode) and FAKE_KEY not in repr(gw.config)


# ------------------------------------------------------------------------------------------------ D1 / DEF-A1 manual
def test_ai_off_renamed_headers_open_a_manual_review_not_a_dead_end(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    assert R(ctx, "GET", "app")["llm"]["mode"] == "DISABLED"
    ref, vid, d = case_with(ctx, "IN-10", renamed_in10(), "cashbook.csv")
    assert vid, d["progress"]
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "MANUAL_MAPPING" and rv["version_status"] == "REVIEW_REQUIRED"
    assert sorted(rv["unresolved_headers"]) == sorted(IN10_REN.values())
    for h in IN10_REN.values():
        assert repr(h) in rv["review_reason"]
    rows = {r["source_header"]: r for r in rv["rows"] if r["needs_attention"]}
    assert set(rows) == set(IN10_REN.values())
    for r in rows.values():
        assert r["available_actions"] == ["CHANGE", "IGNORE"] and r["proposal_source"] is None
    assert [e["details"]["status"] for e in ev(ctx, "PROVIDER_CALL")] == ["DENIED"]
    for f, h in IN10_REN.items():
        R(ctx, "POST", f"cases/{ref}/review/{vid}/decision",
          {"action": "CHANGE", "source_index": rows[h]["source_index"], "canonical_field": f})
    out = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    assert out["progress"]["files_awaiting_review"] == 0
    assert ctx.svc.load(out["package"]["package_id"]).versions[vid].version_status == "VALIDATED"


# ------------------------------------------------------------------------------------------------ D1 live (double)
def test_live_proposal_is_reviewed_never_auto_applied_and_audited(tmp_path):
    def answer(kw):
        content = json.loads(kw["input"][0]["content"])["content"]
        assert all(not c["value_shapes"] for c in content["unresolved_columns"])          # owner default: no shapes
        idx = {c["source_header"]: c["source_index"] for c in content["unresolved_columns"]}
        truth = {v: k for k, v in IN10_REN.items()}
        return proposal_text("IN-10", [(idx[h], h, truth[h], "CLEAR") for h in idx])
    ctx, fake = live_ctx(tmp_path, answer)
    app = R(ctx, "GET", "app")["llm"]
    assert app["mode"] == "LIVE" and FAKE_KEY not in json.dumps(app)
    ref, vid, d = case_with(ctx, "IN-10", renamed_in10(), "cashbook.csv")
    assert len(fake.calls) == 1 and fake.calls[0]["store"] is False
    pc = ev(ctx, "PROVIDER_CALL")[-1]["details"]
    assert pc["status"] == "OK" and pc["provider_request_id"] == "req_test_1" and pc["provider_response_id"] == "resp_test_1"
    assert pc["usage"]["total_tokens"] == 120 and pc["model"] == "test-model"
    assert FAKE_KEY not in (ctx.root / "audit.jsonl").read_text(encoding="utf-8")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "AI_PROPOSAL" and rv["version_status"] == "REVIEW_REQUIRED"
    rows = {r["source_header"]: r for r in rv["rows"] if r["needs_attention"]}
    assert set(rows) == set(IN10_REN.values())
    assert rows["acct_no"]["proposal_source"] == "AI" and rows["acct_no"]["proposal_explanation"]
    assert rows["acct_no"]["available_actions"] == ["MAP", "CHANGE", "IGNORE"]
    # the money column: AMBIGUOUS by the validator (sign-sensitive) -> explicit clarification, never one-click MAP
    amt = rows["txn_amt"]
    assert amt["proposal_class"] == "AMBIGUOUS" and amt["clarification_required"]
    assert amt["available_actions"] == ["CLARIFY", "IGNORE"]
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/decision",
                             {"action": "MAP", "source_index": amt["source_index"]})) == "UNSUPPORTED_ACTION"
    pid = rv["package_id"]
    assert code_of(lambda: R(ctx, "POST", f"review/{pid}/{vid}/decision", {        # generic route: same rule
        "action": "MAP", "source_index": amt["source_index"], "reason": "t"})) == "CLARIFICATION_REQUIRED"
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/confirm".replace("confirm", f"review/{vid}/confirm"))) \
        == "DECISIONS_OUTSTANDING"
    for h, f in (("entry_ref", None), ("acct_no", None), ("posting_dt", None)):
        R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "MAP", "source_index": rows[h]["source_index"]})
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision",
      {"action": "CLARIFY", "source_index": amt["source_index"], "canonical_field": "amount"})
    cl = ev(ctx, "ANALYST_MAPPING_CLARIFIED")
    assert len(cl) == 1 and cl[0]["details"]["chosen_field"] == "amount" and cl[0]["details"]["accepted_as_proposed"]
    out = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    assert ctx.svc.load(out["package"]["package_id"]).versions[vid].version_status == "VALIDATED"
    assert not [e for e in ctx.events() if e["event_type"] == "POC_AUTO_DECISION" and e["approval_kind"]]


def test_unmappable_live_answer_stays_unresolved_and_provider_failure_goes_to_manual_review(tmp_path):
    def unmappable(kw):
        content = json.loads(kw["input"][0]["content"])["content"]
        return proposal_text("IN-10", [(c["source_index"], c["source_header"], "UNMAPPABLE", "UNMAPPABLE")
                                       for c in content["unresolved_columns"]])
    ctx, _ = live_ctx(tmp_path / "a", unmappable)
    ref, vid, _ = case_with(ctx, "IN-10", renamed_in10(), "cashbook.csv")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "UNMAPPABLE_PROPOSAL"
    for r in rv["rows"]:
        if r["needs_attention"]:
            assert r["suggested_field"] is None and "MAP" not in r["available_actions"]

    def boom(kw):
        raise RuntimeError("provider down")
    ctx2, fake = live_ctx(tmp_path / "b", boom)
    ref, vid, _ = case_with(ctx2, "IN-10", renamed_in10(), "cashbook.csv")
    rv = R(ctx2, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "MANUAL_MAPPING" and "provider" not in (rv["proposal_provider_id"] or "")
    assert [e["details"]["status"] for e in ev(ctx2, "PROVIDER_CALL")] == ["FAILED"]
    assert all(r["available_actions"] == ["CHANGE", "IGNORE"] for r in rv["rows"] if r["needs_attention"])


# ------------------------------------------------------------------------------------------------ D2
def v08_extra():
    r = tbl("IN-11")
    return dump([r[0] + ["operator_memo"]] + [x + ["free text memo"] for x in r[1:]])


def test_conflicting_change_is_refused_at_decision_time_and_confirm_is_atomic(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    ref, vid, _ = case_with(ctx, "IN-11", v08_extra(), "transactions_2026-09.csv")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "HEADER_COUNT_MISMATCH"
    memo = next(r for r in rv["rows"] if r["source_header"] == "operator_memo")
    n_dec = len(ev(ctx, "INTAKE_DECISION"))
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {
        "action": "CHANGE", "source_index": memo["source_index"], "canonical_field": "payment_reference"})) \
        == "DUPLICATE_TARGET"
    assert len(ev(ctx, "INTAKE_DECISION")) == n_dec                     # nothing recorded
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "IGNORE", "source_index": memo["source_index"]})
    # a failure DURING the apply phase: everything is restored, a FAILED event is recorded, no CONFIRMED event
    orig = ctx.svc.complete_review

    def failing(*a, **kw):
        raise ValueError("SIMULATED_FAILURE: injected by the test after the recognised columns were mapped")
    ctx.svc.complete_review = failing
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")) == "SIMULATED_FAILURE"
    ctx.svc.complete_review = orig
    case = ctx.svc.store.load_case(rv["package_id"], ctx.svc.load(rv["package_id"]).versions[vid].review_case_id)
    assert [d.source_header for d in case.decisions] == ["operator_memo"]          # no partial MAP decisions
    assert not ev(ctx, "ANALYST_REVIEW_CONFIRMED")
    failed = ev(ctx, "ANALYST_REVIEW_CONFIRMATION_FAILED")
    assert len(failed) == 1 and "SIMULATED_FAILURE" in failed[0]["details"]["reason"]
    assert ev(ctx, "REVIEW_COMPLETION_ROLLED_BACK")
    out = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")                     # retry succeeds, once
    assert ctx.svc.load(out["package"]["package_id"]).versions[vid].version_status == "VALIDATED"
    conf = ev(ctx, "ANALYST_REVIEW_CONFIRMED")
    assert len(conf) == 1 and conf[0]["details"]["recognised_columns_confirmed"] == 13
    assert conf[0]["seq"] > ev(ctx, "INTAKE_CASE_RESOLVED")[-1]["seq"]          # recorded only after success
    assert ctx.log.verify() > 0


def test_prevalidation_refusal_writes_nothing_but_the_failure_event(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    ref, vid, _ = case_with(ctx, "IN-11", v08_extra(), "transactions_2026-09.csv")
    pid = R(ctx, "GET", f"cases/{ref}/review/{vid}")["package_id"]
    v = ctx.svc.load(pid).versions[vid]
    # a conflicting decision recorded before Fix8 (historical state): written straight into the case, bypassing decide
    case = ctx.svc.store.load_case(pid, v.review_case_id)
    from smartparser.review.intake import CaseDecision
    case.decisions.append(CaseDecision(decision_id="legacy-1", source_index=13, source_header="operator_memo",
                                       action="CHANGE", canonical_field="payment_reference", reason="legacy",
                                       reviewer_id="x", reviewer_role="analyst", approval_kind="TEST",
                                       decided_at="2026-11-22T00:00:00+00:00"))
    ctx.svc.store.save_case(pid, case)
    probs = review_api.prevalidate(ctx.svc, pid, vid)
    assert probs and probs[0].startswith("DUPLICATE_TARGET")
    n = len(ctx.events())
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")) == "DUPLICATE_TARGET"
    new = ctx.events()[n:]
    assert [e["event_type"] for e in new] == ["ANALYST_REVIEW_CONFIRMATION_FAILED"]
    assert len(ctx.svc.store.load_case(pid, v.review_case_id).decisions) == 1


# ------------------------------------------------------------------------------------------------ D3
def test_mapping_provenance_header_variant_and_deterministic(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    r = tbl("IN-11")
    var = {"txn_id": "TXN_ID", "amount": " amount "}
    ref, vid, _ = case_with(ctx, "IN-11", dump([[var.get(c, c) for c in r[0]]] + r[1:]), "transactions_2026-09.csv")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "HEADER_VARIANT"
    for x in rv["rows"]:
        if x["needs_attention"]:
            R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "MAP", "source_index": x["source_index"]})
    R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    a = R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    assert a["activated"], a["reason"]
    pid, sid = a["case"]["package"]["package_id"], a["snapshot_id"]
    doc = build_mapping_provenance(ctx, pid, sid)
    assert doc["schema"] == SCHEMA and doc["snapshot_id"] == sid
    f11 = next(f for f in doc["files"] if f["evidence_category"] == "IN-11")
    assert f11["review_kind"] == "HEADER_VARIANT" and f11["version_status"] == "ACTIVE"
    case = ctx.svc.store.load_case(pid, ctx.svc.load(pid).versions[vid].review_case_id)
    for c in f11["columns"]:
        assert c["method"] in METHODS and c["disposition"] == "MAPPED" and c["validation"] == "PASS"
        assert c["rule_id"] == case.file_mapping_id and c["rule_version"] == 1          # attributed (D3 fix)
        assert c["decided_by"] == "test-analyst-1" and c["confirmed_by"] == "test-analyst-1" and c["audit_event_seqs"]
    assert not [n for n in doc["notes"] if "IN-11" in n and "ANALYST_REVIEW_CONFIRMED" in n]
    conf = ev(ctx, "ANALYST_REVIEW_CONFIRMED")[-1]
    assert all(conf["seq"] in c["audit_event_seqs"] and c["confirmed_at"] == conf["at"] for c in f11["columns"])
    by = {c["source_header"]: c for c in f11["columns"]}
    assert by["TXN_ID"]["method"] == "DETERMINISTIC_POLICY" and by["client_id"]["method"] == "DETERMINISTIC_EXACT"
    v = ctx.svc.load(pid).versions[vid]
    assert {x["rule_id"] for x in v.mapping_rule_refs} == {case.file_mapping_id}        # no longer empty
    side = json.loads(ctx.svc.store.abs(v.handoff.provenance).read_text(encoding="utf-8"))
    assert side["approval_references"] == [case.file_mapping_id]
    other = next(f for f in doc["files"] if f["evidence_category"] == "IN-10")
    assert other["review_kind"] is None and all(c["method"] == "DETERMINISTIC_EXACT" and c["confirmed_by"] is None
                                                for c in other["columns"])


# ------------------------------------------------------------------------------------------------ D4
def in12(swap=False, ambiguous=True, break_rows=0):
    r = [list(x) for x in tbl("IN-12")]
    h = r[0]
    gi, ni = h.index("gross_amount"), h.index("net_amount_reported")
    for k in range(1, 1 + break_rows):
        r[k][ni] = str(round(float(r[k][ni]) + 1.0, 2)) if "." in r[k][ni] else r[k][ni] + "1"
    if swap:
        for x in r[1:]:
            x[gi], x[ni] = x[ni], x[gi]
    if ambiguous:
        r[0] = [{"gross_amount": "Amount", "net_amount_reported": "Batch Value", "total_fees": "Fees",
                 "total_adjustments": "Adjustments"}.get(c, c) for c in h]
    return dump(r)


def test_relationship_unit_checks_on_synthetic_in12():
    r = tbl("IN-12")
    h = r[0]
    vals = {i: [x[i] for x in r[1:]] for i in range(len(h))}
    good = {i: f for i, f in enumerate(h)}
    res = financial.check_relationships("IN-12", h, good, vals)
    assert res[0]["status"] == "PASS" and res[0]["rows_checked"] == len(r) - 1
    gi, ni = h.index("gross_amount"), h.index("net_amount_reported")
    swapped = dict(good)
    swapped[gi], swapped[ni] = "net_amount_reported", "gross_amount"
    if any(x[h.index("total_fees")] not in ("0.00", "0") or x[h.index("total_adjustments")] not in ("0.00", "0")
           for x in r[1:]):
        bad = financial.check_relationships("IN-12", h, swapped, vals)[0]
        assert bad["status"] == "FAIL" and bad["contradictory"] and bad["better_assignment"]
    partial = {i: f for i, f in good.items() if f != "total_fees"}
    assert financial.check_relationships("IN-12", h, partial, vals)[0]["status"] == "NOT_EVALUATED"
    # one genuinely wrong row that no re-assignment explains: a warning left to reconciliation, never refused
    vals2 = {i: list(v) for i, v in vals.items()}
    vals2[ni][0] = str(float(vals2[ni][0]) + 7)
    w = financial.check_relationships("IN-12", h, good, vals2)[0]
    assert len(r) - 1 > 2
    if len(r) - 1 > 2:
        assert w["status"] == "WARN" and not w["contradictory"]


def ambiguous_in12_answer(swap):
    def answer(kw):
        content = json.loads(kw["input"][0]["content"])["content"]
        m = {"Amount": "net_amount_reported" if swap else "gross_amount",
             "Batch Value": "gross_amount" if swap else "net_amount_reported",
             "Fees": "total_fees", "Adjustments": "total_adjustments"}
        return proposal_text("IN-12", [(c["source_index"], c["source_header"], m[c["source_header"]], "AMBIGUOUS")
                                       for c in content["unresolved_columns"]])
    return answer


def test_swapped_gross_net_proposal_needs_clarification_and_is_refused_then_correct_choice_succeeds(tmp_path):
    ctx, _ = live_ctx(tmp_path, ambiguous_in12_answer(swap=True))
    ref, vid, _ = case_with(ctx, "IN-12", in12(), "settlement_batches_2026-09.csv")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    rows = {r["source_header"]: r for r in rv["rows"] if r["needs_attention"]}
    assert all(rows[h]["clarification_required"] and "MAP" not in rows[h]["available_actions"]
               for h in ("Amount", "Batch Value", "Fees", "Adjustments"))
    prop = rv["financial_checks"]["as_proposed"][0]
    tbl12 = tbl("IN-12")
    has_fees = any(float(x[tbl12[0].index("total_fees")]) or float(x[tbl12[0].index("total_adjustments")])
                   for x in tbl12[1:])
    assert has_fees                                         # the synthetic IN-12 has fee rows (swap is detectable)
    if has_fees:
        assert prop["status"] == "FAIL" and prop["better_assignment"]
    for h in ("Fees", "Adjustments", "Amount"):
        R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "CLARIFY", "source_index":
                                                             rows[h]["source_index"],
                                                             "canonical_field": rows[h]["suggested_field"]})
    if has_fees:            # accepting the swap as proposed completes a contradictory mapping: refused
        assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {
            "action": "CLARIFY", "source_index": rows["Batch Value"]["source_index"],
            "canonical_field": "gross_amount"})) == "FINANCIAL_RELATIONSHIP"
    # the analyst clarifies the real meaning: Amount = gross, Batch Value = net
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "CLARIFY", "source_index":
                                                         rows["Amount"]["source_index"], "canonical_field": "gross_amount"})
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "CLARIFY", "source_index":
                                                         rows["Batch Value"]["source_index"],
                                                         "canonical_field": "net_amount_reported"})
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["financial_checks"]["current"][0]["status"] == "PASS"
    cl = [e["details"] for e in ev(ctx, "ANALYST_MAPPING_CLARIFIED")]
    assert any(d["source_header"] == "Amount" and d["chosen_field"] == "gross_amount" and not d["accepted_as_proposed"]
               for d in cl)
    # the remaining columns (no fee/adj ambiguity) and confirm
    for r in rv["rows"]:
        if r["needs_attention"] and not r["decided"]:
            act = "MAP" if "MAP" in r["available_actions"] else "CLARIFY"
            R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": act, "source_index": r["source_index"],
                                                                 "canonical_field": r["suggested_field"]})
    out = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    assert ctx.svc.load(out["package"]["package_id"]).versions[vid].version_status == "VALIDATED"


def test_contradictory_values_refused_at_confirm_even_if_recorded_earlier(tmp_path):
    """Values where the relationship fails on most rows whatever the assignment: confirm refuses with a clear message."""
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None)
    r = [list(x) for x in tbl("IN-12")]
    h = r[0]
    ni = h.index("net_amount_reported")
    for x in r[1:]:
        x[ni] = "1.23"
    hdr = [{"net_amount_reported": "Batch Value"}.get(c, c) for c in h]
    ref, vid, _ = case_with(ctx, "IN-12", dump([hdr] + r[1:]), "settlement_batches_2026-09.csv")
    rv = R(ctx, "GET", f"cases/{ref}/review/{vid}")
    assert rv["review_kind"] == "MANUAL_MAPPING"
    bv = next(x for x in rv["rows"] if x["source_header"] == "Batch Value")
    if len(r) - 1 >= 1:
        assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {
            "action": "CHANGE", "source_index": bv["source_index"], "canonical_field": "net_amount_reported"})) \
            == "FINANCIAL_RELATIONSHIP"
