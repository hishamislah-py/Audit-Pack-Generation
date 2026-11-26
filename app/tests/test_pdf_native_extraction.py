"""Experiment A: native PDF extraction and canonical mapping (no OCR). Isolated: the module is not wired into the
pipeline, packages, handoff or submission. Real PDFs come from tests/fixtures/uc042_canonical (copies of UC-042
synthetic evidence); constructed variants are built into tmp_path by tools/pdfx_build_variants.py."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from smartparser.orchestration.policy import Decision
from smartparser.pdf_extraction import extract_document
from smartparser.schemas import SchemaRegistry

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "uc042_canonical"
SEP = FIX / "PER-2026-09_set_01_clean_baseline"
DOCS = SEP / "supporting_documents"
MAY_POLICY_11 = FIX / "PER-2026-05_demo_history" / "supporting_documents" / "safeguarding_reconciliation_policy_v1.1.pdf"

# Ground truth: the values uc042lib.generate.write_pdfs (and the historical-demo generator for v1.1) wrote, which
# uc042lib.prepare._pdf_details also returns for these files.
TRUTH = {
    "ack_letter_SGA-GBP-01.pdf": ("IN-15", {"Letter reference": "ACK-INST01-4471", "Institution": "Example Bank plc",
                                            "Account name": "Synthetic EMI Ltd Safeguarding Account (GBP)",
                                            "Account number": "****4471", "Currency": "GBP", "Letter date": "2024-03-01"}),
    "ack_letter_SGA-EUR-01.pdf": ("IN-16", {"Letter reference": "ACK-INST01-8823", "Institution": "Example Bank plc",
                                            "Account name": "Synthetic EMI Ltd Safeguarding Account (EUR)",
                                            "Account number": "****8823", "Currency": "EUR", "Letter date": "2024-03-01"}),
    "safeguarding_reconciliation_policy_v1.2.pdf": ("IN-17", {
        "Document version": "1.2", "Effective date": "2026-05-07", "Safeguarding method": "SEGREGATION",
        "Reconciliation method": "STANDARD", "Reconciliation point": "17:00 Europe/London",
        "Frequency": "Each reconciliation day", "Internal reconciliation basis": "Per currency"}),
    "governance_register_2026-09.pdf": ("IN-18", {"Accountable person": "A. Example (synthetic)",
                                                  "Role": "Chief Financial Officer (synthetic)", "Allocated from": "2026-05-07"}),
    "rep027_submission_receipt_2026-08.pdf": ("IN-19", {
        "Return": "REP027 monthly safeguarding return", "Period": "2026-08", "Due date": "2026-09-21",
        "Submitted at": "2026-09-17T11:02:00+01:00", "Submission reference": "SYN-RD-2026-08-0001"}),
}


@pytest.fixture(scope="module")
def reg():
    return SchemaRegistry.from_directory()


@pytest.fixture(scope="module")
def inventory():
    with open(SEP / "source_data" / "account_inventory.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("pdfx_build_variants", ROOT / "tools" / "pdfx_build_variants.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("pdfx_variants")
    manifest = mod.build(out)
    return out, manifest


def run(reg, path, inventory=None, period="PER-2026-09"):
    return extract_document(path.read_bytes(), path.name, reg, inventory=inventory, period_id=period)


@pytest.mark.parametrize("name", sorted(TRUTH))
def test_real_pdf_extracts_every_canonical_field_exactly(reg, inventory, name):
    cat, truth = TRUTH[name]
    r = run(reg, DOCS / name, inventory)
    assert (r.native_text, r.category, r.decision, r.ocr_used, r.applied) == ("SUCCEEDED", cat, Decision.DETERMINISTIC, False, False)
    assert {f.label: f.value for f in r.fields} == truth
    assert all(f.status == "EXTRACTED" and f.canonical_field == f"{cat}.{f.label}" for f in r.fields)


def test_field_provenance_is_exact(reg, inventory):
    path = DOCS / "rep027_submission_receipt_2026-08.pdf"
    r = run(reg, path, inventory)
    assert r.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    f = next(x for x in r.fields if x.label == "Submitted at")
    assert len(f.occurrences) == 1
    o = f.occurrences[0]
    assert (o.page, o.text) == (1, "Submitted at: 2026-09-17T11:02:00+01:00")
    assert o.text.endswith(f.value)


def test_original_bytes_are_never_modified(reg, inventory):
    for p in sorted(DOCS.glob("*.pdf")):
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        run(reg, p, inventory)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == before


def test_letter_without_inventory_is_ambiguous_and_routed_to_review(reg):
    r = run(reg, DOCS / "ack_letter_SGA-GBP-01.pdf", inventory=None)
    assert r.category is None and r.candidate_categories == ["IN-15", "IN-16"]
    assert r.decision == Decision.HUMAN_REVIEW
    assert all(v.level != "CROSS_DOC" for f in r.fields for v in f.validations)   # cross-doc rules wait for the slot


def test_cross_document_values_are_checked_against_the_slot_account(reg, inventory):
    r = run(reg, DOCS / "ack_letter_SGA-EUR-01.pdf", inventory)
    cross = {v.rule_id: v.result for f in r.fields for v in f.validations if v.level == "CROSS_DOC"}
    assert cross == {"LETTER-REF": "PASS", "LETTER-ACCOUNT-NUMBER": "PASS", "LETTER-CURRENCY": "PASS", "LETTER-ACCOUNT-NAME": "PASS"}


def test_policy_applicability_follows_the_period(reg, inventory):
    assert run(reg, MAY_POLICY_11, inventory, period="PER-2026-01").decision == Decision.DETERMINISTIC
    r = run(reg, MAY_POLICY_11, inventory, period="PER-2026-09")
    assert r.decision == Decision.HUMAN_REVIEW
    assert any("POLICY-APPLIES failed" in x for x in r.reasons)


def test_policy_v11_replacement_character_does_not_break_extraction(reg, inventory):
    r = run(reg, MAY_POLICY_11, inventory, period="PER-2026-01")
    assert {f.label: f.value for f in r.fields}["Document version"] == "1.1"


def test_unmapped_key_value_lines_are_reported_not_mapped(reg, inventory):
    r = run(reg, DOCS / "governance_register_2026-09.pdf", inventory)
    assert [u.key for u in r.unmapped] == ["Critical individuals for safeguarding operations"]
    assert r.unmapped[0].near_miss_of is None
    assert "Critical individuals for safeguarding operations" not in {f.label for f in r.fields}


EXPECTED = {
    "V01_multipage_letter_GBP.pdf": Decision.DETERMINISTIC,
    "V02_table_layout_letter_GBP.pdf": Decision.REJECT_OR_HOLD,
    "V03_receipt_missing_label.pdf": Decision.REJECT_OR_HOLD,
    "V04_governance_conflict.pdf": Decision.HUMAN_REVIEW,
    "V05_governance_near_miss.pdf": Decision.REJECT_OR_HOLD,
    "V06_image_only_letter.pdf": Decision.REJECT_OR_HOLD,
    "V07_wrapped_account_name.pdf": Decision.HUMAN_REVIEW,
    "V08_policy_unregistered_v1.3.pdf": Decision.REJECT_OR_HOLD,
    "V09_receipt_bad_timestamp.pdf": Decision.HUMAN_REVIEW,
    "V10_letter_unknown_reference.pdf": Decision.HUMAN_REVIEW,
    "V11_governance_allocated_after_period.pdf": Decision.DETERMINISTIC,
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_constructed_variant_routing(reg, inventory, variants, name):
    out, manifest = variants
    r = run(reg, out / name, inventory)
    assert r.decision == EXPECTED[name], (r.decision, r.reasons)
    assert r.applied is False and r.ocr_used is False
    truth = manifest[name]["source_values"]
    for f in r.fields:   # whatever is EXTRACTED equals what the document says, except a flagged (wrapped) value
        if f.status == "EXTRACTED" and "POSSIBLY_WRAPPED" not in f.flags:
            assert f.value == truth[f.label]


def test_multipage_provenance_points_to_page_two(reg, inventory, variants):
    r = run(reg, variants[0] / "V01_multipage_letter_GBP.pdf", inventory)
    assert r.page_count == 2 and {o.page for f in r.fields for o in f.occurrences} == {2}


def test_table_layout_gives_candidates_only(reg, inventory, variants):
    r = run(reg, variants[0] / "V02_table_layout_letter_GBP.pdf", inventory)
    assert r.candidate_categories == ["IN-15", "IN-16"]
    assert all(f.status == "NOT_LINE_ANCHORED" and f.value is None for f in r.fields)
    assert {f.label: f.candidate_values[0] for f in r.fields}["Letter reference"] == "ACK-INST01-4471"


def test_conflict_is_never_resolved(reg, inventory, variants):
    f = next(x for x in run(reg, variants[0] / "V04_governance_conflict.pdf", inventory).fields if x.label == "Allocated from")
    assert (f.status, f.value, f.candidate_values) == ("CONFLICT", None, ["2026-05-07", "2026-06-01"])


def test_near_miss_label_is_reported_not_mapped(reg, inventory, variants):
    r = run(reg, variants[0] / "V05_governance_near_miss.pdf", inventory)
    assert [(u.key, u.near_miss_of) for u in r.unmapped] == [("Accountable Person", "Accountable person")]
    assert next(f for f in r.fields if f.label == "Accountable person").status == "MISSING"


def test_image_only_pdf_is_not_read(reg, inventory, variants):
    r = run(reg, variants[0] / "V06_image_only_letter.pdf", inventory)
    assert (r.native_text, r.fields, r.ocr_used) == ("IMAGE_ONLY", [], False)
    assert r.image_count >= 1


def test_wrapped_value_is_flagged_not_accepted(reg, inventory, variants):
    f = next(x for x in run(reg, variants[0] / "V07_wrapped_account_name.pdf", inventory).fields if x.label == "Account name")
    assert "POSSIBLY_WRAPPED" in f.flags and f.review_reasons


def test_malformed_value_is_preserved_and_flagged(reg, inventory, variants):
    f = next(x for x in run(reg, variants[0] / "V09_receipt_bad_timestamp.pdf", inventory).fields if x.label == "Submitted at")
    assert f.value == "17/09/2026 11:02"   # exactly as written: never reformatted
    assert any(v.result == "FAIL" and v.detail.startswith("FORMAT:") for v in f.validations)


def test_business_rule_failure_is_reported_without_blocking_extraction(reg, inventory, variants):
    r = run(reg, variants[0] / "V11_governance_allocated_after_period.pdf", inventory)
    assert r.decision == Decision.DETERMINISTIC
    v = next(v for f in r.fields for v in f.validations if v.rule_id == "GOV-ALLOCATED-FROM")
    assert (v.level, v.result) == ("CONTROL", "FAIL")


def test_not_a_pdf_and_damaged_pdf(reg):
    assert extract_document(b"hello", "x.pdf", reg).native_text == "UNREADABLE"
    assert extract_document(b"%PDF-1.4 garbage", "x.pdf", reg).native_text == "UNREADABLE"


def test_results_are_reproducible(reg, inventory):
    a = [run(reg, p, inventory).model_dump() for p in sorted(DOCS.glob("*.pdf"))]
    b = [run(reg, p, inventory).model_dump() for p in sorted(DOCS.glob("*.pdf"))]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_experiment_is_isolated_from_workflows():
    """No workflow module imports the experiment (pipeline, packages, handoff, orchestration, review UI, reconciliation)."""
    for sub in ("pipeline.py", "packages", "handoff", "orchestration", "review_ui", "reconciliation", "classify", "intake"):
        for p in ([ROOT / "smartparser" / sub] if sub.endswith(".py") else (ROOT / "smartparser" / sub).rglob("*.py")):
            assert "pdf_extraction" not in p.read_text(encoding="utf-8"), p


def test_registry_definitions_unchanged_by_experiment(reg):
    for cat in ("IN-15", "IN-16", "IN-17", "IN-18", "IN-19"):
        assert all(l.value_type is None for l in reg.get(cat).pdf.labels)   # no types were added to the registry
