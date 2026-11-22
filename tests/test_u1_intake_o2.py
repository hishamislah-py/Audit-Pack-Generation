"""U1 - owner decision O2 applied at INTAKE (19 Nov 2026).

A column is recognised automatically only when its header EXACTLY equals the canonical field and no other column claims
that field. Case / whitespace variants and alternative names (approved aliases) are never applied automatically: the
file's category is still established deterministically (the complete header maps one-to-one onto exactly one category,
the unchanged Phase 2 identification rule) and the file goes to a HEADER_VARIANT column review. Driven through the
Ringfence case API and the package service; offline (one test uses the recorded LLM fixture)."""
import base64
from pathlib import Path

from smartparser.review.authority import Reviewer
from smartparser.webapp.context import AppContext

from .phase3b_support import TEST_POLICY, dump, tbl
from .test_ringfence_cases import (R, ctx_for, err, make_zip, new_case, settle, upload)
from .uc042_support import SEP, read

FX = Path(__file__).parent / "fixtures" / "recorded_llm" / "in10_ambiguous.json"
ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")


def variant(fid, change: dict[int, str]) -> bytes:
    r = tbl(fid)
    hdr = [change.get(i, h) for i, h in enumerate(r[0])]
    return dump([hdr] + r[1:])


def started_without(ctx, *skip):
    ref = new_case(ctx, data=make_zip(skip=skip))["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    settle(ctx, ref)
    return ref


def version_of(ctx, d, cat):
    slot = next(s for s in d["package"]["slots"] if s["evidence_category"] == cat)
    return slot["latest"]


def submit(ctx, ref, data, cat=None, name="file.csv"):
    upload(ctx, ref, name, data, cat)
    d = settle(ctx, ref)
    return d, version_of(ctx, d, cat) if cat else None


# 1 / 5 ------------------------------------------------------------------------------------------- exact and reordered
def test_exact_and_reordered_exact_headers_are_recognised_automatically(tmp_path):
    ctx = ctx_for(tmp_path)
    r = tbl("IN-01")
    reordered = dump([list(reversed(x)) for x in r])
    zipped = make_zip(replace={"IN-01": reordered})
    ref = new_case(ctx, data=zipped)["case_ref"]
    R(ctx, "POST", f"cases/{ref}/start")
    d = settle(ctx, ref)
    assert d["progress"]["categories_validated"] == 17 and d["progress"]["files_awaiting_review"] == 0
    v = version_of(ctx, d, "IN-01")
    assert v["version_status"] == "VALIDATED" and v["processing_status"] == "DETERMINISTIC:DETERMINISTIC"
    pkg = ctx.svc.load(d["package"]["package_id"])
    fv = pkg.versions[v["file_version_id"]]
    assert ctx.svc.store.abs(fv.handoff.preview_csv).read_bytes() == read(SEP, "IN-01")    # canonical order restored


# 2 / 3 / 4 ------------------------------------------------------------------------------- variants go to review
def _variant_case(tmp_path, change, label):
    ctx = ctx_for(tmp_path / label)
    ref = started_without(ctx, "IN-01")
    data = variant("IN-01", change)
    d, v = submit(ctx, ref, data, None, name=f"{label}.csv")          # NOT declared: the content decides the category
    v = version_of(ctx, d, "IN-01")
    assert v is not None, "the variant file must not be refused: its category is established deterministically"
    assert v["version_status"] == "REVIEW_REQUIRED" and v["processing_status"] == "HEADER_VARIANT:HUMAN_REVIEW"
    rv = R(ctx, "GET", f"cases/{ref}/review/{v['file_version_id']}")
    assert rv["review_kind"] == "HEADER_VARIANT"
    return ctx, ref, v, rv, data


def test_case_only_variation_requires_review(tmp_path):
    hdr = tbl("IN-01")[0]
    ctx, ref, v, rv, data = _variant_case(tmp_path, {0: hdr[0].upper()}, "case")
    att = [x for x in rv["rows"] if x["needs_attention"]]
    assert [(x["source_header"], x["suggested_field"]) for x in att] == [(hdr[0].upper(), hdr[0])]
    assert att[0]["available_actions"] == ["MAP", "IGNORE"]                      # no CHANGE (RULE_CONTRADICTION)
    assert rv["counts"]["recognised"] == len(hdr) - 1


def test_whitespace_variation_requires_review_and_original_header_is_preserved(tmp_path):
    hdr = tbl("IN-01")[0]
    ctx, ref, v, rv, data = _variant_case(tmp_path, {1: f" {hdr[1]}  "}, "ws")
    att = [x for x in rv["rows"] if x["needs_attention"]]
    assert [x["source_header"] for x in att] == [f" {hdr[1]}  "]                 # exactly as received
    assert att[0]["source_position"] == 2
    pid = R(ctx, "GET", f"cases/{ref}")["package"]["package_id"]
    fv = ctx.svc.load(pid).versions[v["file_version_id"]]
    assert ctx.svc.evidence.read_original(fv.source_sha256) == data              # stored original unchanged


def test_case_plus_whitespace_variation_requires_review(tmp_path):
    hdr = tbl("IN-01")[0]
    ctx, ref, v, rv, data = _variant_case(tmp_path, {i: f" {h.upper()} " for i, h in enumerate(hdr)}, "both")
    assert rv["counts"] == {"attention": len(hdr), "decided": 0, "remaining": len(hdr), "recognised": 0}


# 10 / 11 / 12 ------------------------------------------------------- analyst resolution, determinism, handoff
def test_analyst_resolves_variants_with_explicit_confirmation_and_deterministic_output(tmp_path):
    hdr = tbl("IN-01")[0]
    ctx, ref, v, rv, data = _variant_case(tmp_path, {0: hdr[0].upper(), 2: f" {hdr[2]}"}, "resolve")
    vid = v["file_version_id"]
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/review/{vid}/decision",
                         {"action": "CHANGE", "source_index": 0, "canonical_field": hdr[1]})) == "UNSUPPORTED_ACTION"
    pid = R(ctx, "GET", f"cases/{ref}")["package"]["package_id"]
    assert err(lambda: R(ctx, "POST", f"review/{pid}/{vid}/decision", {
        "action": "CHANGE", "source_index": 0, "canonical_field": hdr[1], "reason": "x"})) == "RULE_CONTRADICTION"
    for x in rv["rows"]:
        if x["needs_attention"]:
            out = R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "MAP", "source_index": x["source_index"]})
    assert out["counts"]["remaining"] == 0 and out["version_status"] == "REVIEW_REQUIRED"   # not confirmed by decisions
    d = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    fv = ctx.svc.load(pid).versions[vid]
    assert fv.version_status == "VALIDATED" and fv.confirmation is not None and fv.confirmation.reviewer_id == "test-analyst-1"
    rules = [x for x in ctx.svc.o.store.read("file_mappings")["file_mappings"] if x["intake_id"] == fv.intake_id]
    assert len(rules) == 1 and rules[0]["lifecycle"]["status"] == "active"      # the analyst's decision is recorded
    assert any(c["id"] == 1 and c["passed"] and "confirmed:" in c["detail"] for c in fv.handoff.checks)
    preview = ctx.svc.store.abs(fv.handoff.preview_csv).read_bytes()
    assert preview == read(SEP, "IN-01")                                           # canonical output, values untouched
    side = __import__("json").loads(ctx.svc.store.abs(fv.handoff.provenance).read_text(encoding="utf-8"))
    assert [c["original_header"] for c in side["columns"]][:3] == [hdr[0].upper(), hdr[1], f" {hdr[2]}"]
    again = [ctx.svc.reprocess_version(pid, vid) for _ in range(2)]                 # deterministic, repeatable
    assert all(a["version_status"] == "VALIDATED" for a in again)
    assert ctx.svc.load(pid).versions[vid].handoff.output_sha256 == fv.handoff.output_sha256
    assert not [e for e in ctx.events() if e["event_type"] == "PROVIDER_CALL"]   # no LLM anywhere (AI disabled)


def test_unresolved_or_excluded_variant_never_becomes_eligible(tmp_path):
    hdr = tbl("IN-01")[0]
    ctx, ref, v, rv, data = _variant_case(tmp_path, {0: hdr[0].upper()}, "ignore")
    vid = v["file_version_id"]
    d = R(ctx, "GET", f"cases/{ref}")
    assert not d["actions"]["activate"]["enabled"]                              # a variant under review blocks activation
    val = R(ctx, "POST", f"cases/{ref}/validate")["package"]["latest_validation"]
    assert not val["passed"] and "PV-04" in [c["check_id"] for c in val["checks"] if not c["passed"]]
    R(ctx, "POST", f"cases/{ref}/review/{vid}/decision", {"action": "IGNORE", "source_index": 0})   # required field
    d = R(ctx, "POST", f"cases/{ref}/review/{vid}/confirm")
    pid = d["package"]["package_id"]
    fv = ctx.svc.load(pid).versions[vid]
    assert fv.version_status == "RESUBMISSION_REQUIRED" and not (fv.handoff and fv.handoff.preview_csv)
    assert hdr[0] in fv.missing_fields


# 7 -------------------------------------------------------------------------------------------- duplicate claims
def test_duplicate_canonical_claims_need_an_explicit_decision(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = started_without(ctx, "IN-01")
    r = tbl("IN-01")
    dup = dump([[r[0][0]] + [r[0][0].upper()] + r[0][2:]] + r[1:])              # col 2 claims field 1 as well
    d, v = submit(ctx, ref, dup, None, "dup.csv")                               # undeclared: not identifiable
    assert v is None and [u["filename"] for u in d["progress"]["refused_uploads"]] == ["dup.csv"]
    d, v = submit(ctx, ref, dup, "IN-01", "dup.csv")                           # declared: routed to a person
    rv = R(ctx, "GET", f"cases/{ref}/review/{v['file_version_id']}")
    assert v["version_status"] == "REVIEW_REQUIRED" and rv["review_kind"] == "DETERMINISTIC_CONFLICT"
    dups = [x for x in rv["rows"] if x["duplicate"]]
    assert len(dups) == 2 and all(x["needs_attention"] and not x["decided"] for x in dups)
    assert not rv["can_confirm"]


# 8 / 9 ---------------------------------------------------------------------- unidentified, wrong declaration
def test_unfamiliar_headers_are_refused_not_guessed(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = started_without(ctx, "IN-01")
    r = tbl("IN-01")
    data = dump([[f"col_{i}" for i in range(len(r[0]))]] + r[1:])
    d, _ = submit(ctx, ref, data, None, "mystery.csv")
    assert [m["category"] for m in d["progress"]["missing_required"]] == ["IN-01"]
    assert [u["filename"] for u in d["progress"]["refused_uploads"]] == ["mystery.csv"]


def test_declared_category_cannot_override_the_content_of_a_variant_file(tmp_path):
    ctx = ctx_for(tmp_path)
    ref = started_without(ctx, "IN-01", "IN-03")
    hdr = tbl("IN-01")[0]
    d, v = submit(ctx, ref, variant("IN-01", {0: hdr[0].upper()}), "IN-03", "x.csv")   # IN-01 content as IN-03
    assert v["version_status"] == "REJECTED"
    corr = {x["category"]: x for x in d["progress"]["correction_required"]}
    assert "content identifies as IN-01, not IN-03" in corr["IN-03"]["reason"]


# proposal path (recorded fixture) -------------------------------------------------------------------------
def test_variant_columns_beside_proposals_are_reviewed_not_fixed_context(tmp_path):
    ctx = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=None, recorded=[FX])
    ref = started_without(ctx, "IN-10")
    r = tbl("IN-10")
    ren = {"ledger_entry_id": "entry_ref", "account_id": "acct_no", "posted_ts": "posting_dt", "amount": "txn_amt",
           "currency": "CURRENCY"}                                               # + one case variant
    d, v = submit(ctx, ref, dump([[ren.get(c, c) for c in r[0]]] + r[1:]), "IN-10", "cb.csv")
    assert len(ctx.stub.calls) == 1 and [u.source_header for u in ctx.stub.calls[0].unresolved_columns] == \
        ["entry_ref", "acct_no", "posting_dt", "txn_amt"]                       # only unfamiliar headers sent
    rv = R(ctx, "GET", f"cases/{ref}/review/{v['file_version_id']}")
    assert rv["review_kind"] == "HEADER_VARIANT"
    att = {x["source_header"]: x for x in rv["rows"] if x["needs_attention"]}
    assert set(att) == {"entry_ref", "acct_no", "posting_dt", "txn_amt", "CURRENCY"}
    assert att["CURRENCY"]["suggested_field"] == "currency" and att["txn_amt"]["suggestion_basis"] == "proposal"
