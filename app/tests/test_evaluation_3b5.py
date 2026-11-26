"""Phase 3B-5: evaluation dataset, end-to-end scenarios A-J, separate metrics, and the explicit Phase 3B-1 UNMAPPABLE
correction regression (including proof that the regression test fails against the pre-correction rule)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import eval_3b5  # noqa: E402

from smartparser.mapping import proposals as P  # noqa: E402

CORPUS = ROOT / "corpus" / "phase3b_eval"


@pytest.fixture(scope="module")
def evaluation():
    results, metrics = eval_3b5.run(CORPUS)
    return {r["case_id"]: r for r in results}, metrics


def test_dataset_is_reproducible_and_matches_committed_copy(tmp_path):
    a = eval_3b5.build(tmp_path / "a")
    b = eval_3b5.build(tmp_path / "b")
    assert a == b
    committed = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["cases"]
    assert committed == a
    for c in a:
        assert (tmp_path / "a" / c["data_file"]).read_bytes() == (CORPUS / c["data_file"]).read_bytes()
        assert c["ground_truth_source"] and "expected" in c and c["truth_category"]


def test_dataset_covers_every_required_case_type():
    cases = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["cases"]
    types = {c["case_type"] for c in cases}
    assert types == {"canonical", "reordered", "case_whitespace", "approved_alias", "proposed_alias",
                     "unfamiliar_clear", "ambiguous", "duplicate_target", "missing_required", "extra_column",
                     "wrong_forced_category", "sign_perspective", "prompt_injection", "malformed_response",
                     "explicit_unmappable", "provider_disabled", "budget_exceeded", "duplicate_pending",
                     "approved_layout", "revoked_rule", "handoff_rejection", "handoff_preview"}
    assert {c["case_id"].split("_")[0] for c in cases if c["case_type"] == "canonical"} == \
        {f"IN-{i:02d}" for i in range(1, 15)}
    wrong = {(c["truth_category"], c["supply_category"]) for c in cases if c["case_type"] == "wrong_forced_category"}
    assert wrong == {("IN-09", "IN-10"), ("IN-10", "IN-09"), ("IN-07", "IN-08"), ("IN-08", "IN-07"),
                     ("IN-05", "IN-06"), ("IN-06", "IN-05")}


def test_every_case_behaves_as_expected(evaluation):
    by_id, metrics = evaluation
    assert metrics["fail"] == [] and metrics["pass"] == len(by_id) == 68


@pytest.mark.parametrize("scenario,ids", [
    ("A", ["IN-01_canonical", "IN-14_canonical"]), ("B", ["IN-09_reordered", "IN-07_case_ws"]),
    ("C", ["unfamiliar_clear"]), ("D", ["sign_perspective"]),
    ("E", ["unmappable_form_A", "unmappable_form_B", "unmappable_form_C"]), ("F", ["missing_required"]),
    ("G", ["revoked_layout"]), ("H", ["provider_disabled", "budget_exceeded"]), ("I", ["approved_layout_reprocess"]),
    ("J", ["wrong_IN-09_as_IN-10", "wrong_IN-07_as_IN-08", "wrong_IN-05_as_IN-06"]),
])
def test_end_to_end_scenarios(evaluation, scenario, ids):
    by_id, _ = evaluation
    for i in ids:
        r = by_id[i]
        assert r["scenario"] == scenario and r["result"] == "PASS", (i, r["diffs"])
        if scenario in ("A", "B", "I"):
            assert r["proposer_calls"] == 0 and r["eligible"] and r["preview_equals_canonical"]
        if scenario == "C":
            assert r["proposer_calls"] == 1 and r["review"] == "APPROVED" and r["eligible"]
            assert r["provider_calls_during_reprocessing"] == 0 and r["final_category"] == "IN-10"
        if scenario == "D":
            assert r["classes"]["txn_amt"] == "AMBIGUOUS" and r["review"] == "NOT_REVIEWED" and not r["eligible"]
        if scenario == "E":
            assert (r["classes"]["txn_amt"], r["statuses"]["txn_amt"]) == ("NO_MATCH", "unmappable")
            assert not r["eligible"] and r["review"] == "APPROVED"
        if scenario == "F":
            assert r["summary_missing"] == ["currency", "dc_indicator", "entry_type", "payment_reference"]
            assert not r["eligible"]
        if scenario == "G":
            assert r["history_intact"] and r["category"] is None and not r["eligible"]
        if scenario == "H":
            assert r["proposer_calls"] == 0 and r["manual_review"] and r["unresolved"]
        if scenario == "J":
            assert r["category"] is None and r["proposer_calls"] == 0


def test_metrics_are_separate_and_honest(evaluation):
    _, m = evaluation
    assert set(m) >= {"classification", "proposal_quality", "review", "reprocessing", "handoff", "operations"}
    assert "overall_accuracy" not in json.dumps(m)                           # no single misleading score
    assert m["classification"]["wrong_forced_category_rejection_rate"] == 1.0
    assert m["reprocessing"]["provider_calls_during_reprocessing"] == 0
    assert m["handoff"]["eligible"] == m["handoff"]["previews_equal_canonical_source"]
    assert m["operations"]["tokens_cost_latency"].startswith("not measured")
    assert "no production or third-party accuracy" in m["note"]


# ============================================================================================ correction regression
def _correction_columns(evaluation):
    by_id, _ = evaluation
    return {t: by_id[f"unmappable_form_{t}"] for t in "ABC"}


def test_unmappable_correction_forms_a_b_c(evaluation):
    cols = _correction_columns(evaluation)
    for tag, r in cols.items():
        assert (r["classes"]["txn_amt"], r["statuses"]["txn_amt"]) == ("NO_MATCH", "unmappable"), tag
        assert r["diagnostics"]["txn_amt"] == ["UNMAPPABLE"], tag              # no field checks, no conflicts
    assert "DUPLICATE_TARGET" not in json.dumps(cols["C"]["diagnostics"])   # already-mapped field: no false conflict
    assert cols["B"]["proposed"]["txn_amt"] == "amount"                      # named field kept for diagnostics only


def test_regression_would_fail_against_pre_correction_rule(monkeypatch):
    """Re-create the pre-correction behaviour (UNMAPPABLE recognised only as the field) and show form B regresses to
    AMBIGUOUS - i.e. the regression test above detects the original defect."""
    # pre-correction: only canonical_field == UNMAPPABLE was explicit; a real field with assessment UNMAPPABLE was
    # validated as that field. For form B the field is `amount` (sign-sensitive), so the old outcome was AMBIGUOUS.
    monkeypatch.setattr(P, "_explicit_unmappable", lambda c: c.canonical_field == P.UNMAPPABLE)
    case = next(c for c in json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["cases"]
                if c["case_id"] == "unmappable_form_B")
    r = eval_3b5.run_case(case, CORPUS)
    assert (r["classes"]["txn_amt"], r["statuses"]["txn_amt"]) == ("AMBIGUOUS", "ambiguous")
    assert eval_3b5.compare(case, r)                                          # the evaluation flags the regression
