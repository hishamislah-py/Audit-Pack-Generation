"""Phase 1 registry: the 19 UC-042 evidence categories, generated from the UC-042 code with provenance."""
import json

import pytest

from smartparser.registry_import import GENERATOR_VERSION, compare_with_directory, generate
from smartparser.schemas import OFFICIAL_CATEGORIES, SchemaDefinition, SchemaRegistry, SchemaRegistryError
from smartparser.schemas.registry import DEFAULT_DEFINITIONS_DIR

from .uc042_support import UC042_ROOT, needs_uc042, registry

CSV_IDS = [f"IN-{i:02d}" for i in range(1, 15)]
PDF_IDS = [f"IN-{i:02d}" for i in range(15, 20)]


def test_all_19_categories_verified_with_provenance():
    reg = registry()
    assert sorted(s.category for s in reg.all()) == sorted(OFFICIAL_CATEGORIES)
    assert reg.missing_categories() == []
    for s in reg.all():
        assert s.verification_status == "verified" and s.is_defined
        assert s.definition_source.startswith("UC-042 uc042lib.schema.")
        assert s.provenance["generator"] == GENERATOR_VERSION
        assert s.provenance["definition"] in (f"uc042lib.schema.CSV_FILES['{s.category}']",
                                              f"uc042lib.schema.PDF_FILES['{s.category}']")
        assert set(s.provenance["source_sha256"]) >= {"uc042lib/schema.py", "uc042lib/prepare.py", "uc042lib/policy.py"}
        assert s.official_name and s.canonical_filename_pattern


def test_csv_categories_have_exact_header_contracts():
    reg = registry()
    for fid in CSV_IDS:
        s = reg.get(fid)
        assert s.evidence_format == "csv" and s.classification.match_policy == "exact_header"
        assert s.csv.header == [f.name for f in s.fields]                    # column order
        assert [f.position for f in s.fields] == list(range(len(s.fields)))
        assert s.csv.delimiter == "," and s.csv.primary_key == [s.fields[0].name]
        for f in s.fields:
            assert f.requiredness in ("M", "C", "O") and f.source_type and f.provenance
            assert f.required is True                     # every UC-042 column must be present (exact header)
            assert f.nullable == (f.requiredness != "M")
    assert sum(len(registry().get(fid).fields) for fid in CSV_IDS) == 153
    # the canonical headers are pairwise distinct, so an exact match can never be ambiguous
    assert len(reg.exact_header_index()) == 14


def test_types_enums_conditions_and_period_rules_come_from_uc042():
    reg = registry()
    in10 = reg.get("IN-10")
    entry = in10.field("entry_type")
    assert entry.source_type == "enum" and "OWN_FUNDS_TOPUP" in entry.constraints.allowed_values
    assert "uc042lib.schema.ENUMS[('IN-10', 'entry_type')]" in entry.provenance
    assert in10.field("amount").constraints.pattern == r"^\d+\.\d{2}$"           # uc042lib.money.UNSIGNED_RE
    assert reg.get("IN-03").field("balance").constraints.pattern == r"^-?\d+\.\d{2}$"   # SIGNED_RE
    assert in10.field("currency").constraints.allowed_values == ["EUR", "GBP"]   # structure.CURRENCIES
    cond = reg.get("IN-11").field("settlement_batch_id")
    assert cond.requiredness == "C" and cond.condition == "required for card transactions"
    assert reg.get("IN-04").csv.empty_allowed and reg.get("IN-14").csv.empty_allowed
    assert not reg.get("IN-09").csv.empty_allowed
    assert reg.get("IN-01").csv.scope_file and reg.get("IN-02").csv.scope_file
    assert reg.get("IN-09").period_rule == {"in_period": ["booking_date", "booking_ts"]}
    assert "IN-05" in reg.get("IN-14").period_rule["event_ref"]["sources"]
    # recorded honestly where UC-042 leaves something undefined
    assert any("cause_category" in u for u in reg.get("IN-14").unresolved)


def test_pdf_categories_labels_slots_and_policy_versions():
    reg = registry()
    for fid in PDF_IDS:
        s = reg.get(fid)
        assert s.evidence_format == "pdf" and s.pdf.labels and s.fields == []
        assert s.pdf.label_pattern == "^{label}: (.+)$"
        assert all(lbl.value_type is None for lbl in s.pdf.labels)   # UC-042 defines no PDF value types
        assert any("value types are not defined" in u for u in s.unresolved)
    assert reg.get("IN-18").optional_evidence and reg.get("IN-19").optional_evidence
    assert reg.get("IN-18").requirement == reg.get("IN-19").requirement == "OPTIONAL"
    assert not any(reg.get(f).optional_evidence for f in CSV_IDS + ["IN-15", "IN-16", "IN-17"])
    gbp, eur = reg.get("IN-15").pdf, reg.get("IN-16").pdf
    assert gbp.shared_label_group == ["IN-16"] and eur.shared_label_group == ["IN-15"]
    assert (gbp.slot_account_id, eur.slot_account_id) == ("SGA-GBP-01", "SGA-EUR-01")
    pol = reg.get("IN-17").pdf
    assert {v.version: v.effective for v in pol.policy_versions} == {"1.1": "2025-10-01", "1.2": "2026-05-07"}
    assert next(v for v in pol.policy_versions if v.version == "1.2").required_markings == ["SYNTHETIC DOCUMENT - UC-042 POC"]
    assert [lbl.label for lbl in pol.labels][0] == "Document version"
    assert reg.get("IN-15").pdf.labels[5].role == "Letter issue date"           # analysis.PDF_DATE_ROLES


def test_relationships_are_recorded_with_provenance():
    reg = registry()
    in02 = {(r.field, r.target_category) for r in reg.get("IN-02").relationships}
    assert ("acknowledgement_letter_ref", "IN-15") in in02 and ("acknowledgement_letter_ref", "IN-16") in in02
    in06 = {(r.field, r.target_category) for r in reg.get("IN-06").relationships}
    assert ("bank_statement_id", "IN-07") in in06
    assert all(r.provenance for s in reg.all() for r in s.relationships)


def test_registry_rejects_colliding_content_identities():
    defs = {s.category: s for s in registry().all()}
    clone = defs["IN-08"].model_copy(update={"category": "IN-07"})   # IN-07 given IN-08's header
    with pytest.raises(SchemaRegistryError, match="same canonical header"):
        SchemaRegistry([clone, defs["IN-08"]])
    bad = json.loads(defs["IN-15"].model_dump_json())
    bad["pdf"]["shared_label_group"] = []
    with pytest.raises(SchemaRegistryError, match="shared_label_group"):
        SchemaRegistry([SchemaDefinition.model_validate(bad), defs["IN-16"]])


def test_exact_header_policy_requires_a_csv_contract():
    with pytest.raises(ValueError, match="exact_header matching needs a csv contract"):
        SchemaDefinition(category="X", title="x", evidence_format="csv", verification_status="provisional",
                         fields=[{"name": "a", "type": "string"}], classification={"match_policy": "exact_header"})


@needs_uc042
def test_shipped_registry_is_in_sync_with_uc042_code():
    """The JSON files are exactly what the controlled import produces from the current UC-042 code."""
    assert compare_with_directory(generate(UC042_ROOT), DEFAULT_DEFINITIONS_DIR) == []


@needs_uc042
def test_generation_reads_uc042_values_not_copies(tmp_path):
    """Spot-check a few generated values against the live UC-042 modules."""
    import sys
    sys.path.insert(0, str(UC042_ROOT))
    from uc042lib import policy, schema
    defs = generate(UC042_ROOT)
    for fid, (_, name, cols) in schema.CSV_FILES.items():
        assert defs[fid]["csv"]["header"] == [c[0] for c in cols] and defs[fid]["official_name"] == name
    for fid, (_, name, req, labels) in schema.PDF_FILES.items():
        assert [x["label"] for x in defs[fid]["pdf"]["labels"]] == labels and defs[fid]["requirement"] == req
    assert sorted(v["version"] for v in defs["IN-17"]["pdf"]["policy_versions"]) == sorted(policy.POLICY_VERSIONS)
