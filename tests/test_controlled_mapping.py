"""Phase 2: controlled, deterministic CSV column mapping (reorder / policy whitespace+case / approved aliases only)."""
import csv
import io
import json
import sys
from pathlib import Path

import pytest

from smartparser import SmartParser
from smartparser.classify.csv_classifier import EXACT_ONLY_RULES
from smartparser.classify.evidence import classify_batch, classify_bytes
from smartparser.intake import EvidenceStore
from smartparser.mapping.controlled import (
    MappingPolicy, MappingRules, MappingRulesError, RULES_DIR, controlled_map, load_proposals, load_rules,
)

from .uc042_support import MAY, SEP, canonical_header, files_with_truth, read, registry

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).parent / "fixtures" / "mapping_rules"
sys.path.insert(0, str(ROOT / "tools"))
import build_variation_corpus  # noqa: E402
import evaluate_variation_corpus  # noqa: E402

CSV_IDS = [f"IN-{i:02d}" for i in range(1, 15)]


def approved_test_rules():
    return load_rules(registry(), FX / "test_approved_aliases.json", FX / "test_alias_proposals.json")


def cls(data, rules=None):
    return classify_bytes(data, registry(), rules=rules).result


def table(data: bytes):
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def dump(rows):
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode()


# ------------------------------------------------------------------------------------------------ rules governance
def test_production_rules_approve_nothing():
    rules = load_rules(registry())
    assert rules.aliases == []
    assert rules.policy == MappingPolicy(True, True, True, "reject", rules.policy.source)
    proposals = load_proposals(RULES_DIR / "alias_proposals.json")
    assert proposals and all(p["status"] == "proposed" and p["decision"] is None for p in proposals)
    for p in proposals:   # every proposal states category, field, header, reason and risk
        assert p["category"] in CSV_IDS and registry().get(p["category"]).field(p["canonical_field"])
        assert p["reason"] and p["risk"]


def test_active_alias_must_reference_an_approved_proposal():
    with pytest.raises(MappingRulesError, match="is proposed, not approved"):
        load_rules(registry(), FX / "unapproved_active_aliases.json")


def test_ambiguous_aliases_are_refused_at_load():
    with pytest.raises(MappingRulesError, match="ambiguous alias 'Reference'"):
        load_rules(registry(), FX / "ambiguous_approved_aliases.json", FX / "ambiguous_alias_proposals.json")


def test_alias_must_equal_its_proposal_and_decisions_need_metadata(tmp_path):
    cat = json.loads((FX / "test_alias_proposals.json").read_text(encoding="utf-8"))
    act = json.loads((FX / "test_approved_aliases.json").read_text(encoding="utf-8"))
    act["aliases"][0]["alias"] = "Something Else"
    (tmp_path / "a.json").write_text(json.dumps(act), encoding="utf-8")
    with pytest.raises(MappingRulesError, match="differs from its approved proposal"):
        load_rules(registry(), tmp_path / "a.json", FX / "test_alias_proposals.json")
    cat["proposals"][0]["decision"] = None
    (tmp_path / "c.json").write_text(json.dumps(cat), encoding="utf-8")
    with pytest.raises(MappingRulesError, match="needs decision"):
        load_proposals(tmp_path / "c.json")


def test_alias_colliding_with_another_canonical_field_is_refused(tmp_path):
    cat = json.loads((FX / "test_alias_proposals.json").read_text(encoding="utf-8"))
    p = next(x for x in cat["proposals"] if x["proposal_id"] == "AP-IN-09-PK-TITLE")
    p["proposed_header"] = "STATEMENT_ID"          # case-folds to IN-09's other canonical column statement_id
    act = {"policy": {}, "aliases": [{"alias_id": "AA-1", "category": "IN-09", "canonical_field": "bank_entry_id",
                                      "alias": "STATEMENT_ID", "proposal_id": "AP-IN-09-PK-TITLE"}]}
    (tmp_path / "c.json").write_text(json.dumps(cat), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(act), encoding="utf-8")
    with pytest.raises(MappingRulesError, match="ambiguous alias"):
        load_rules(registry(), tmp_path / "a.json", tmp_path / "c.json")


# ------------------------------------------------------------------------------------------------ tier A preserved
@pytest.mark.parametrize("dataset", [SEP, MAY], ids=["2026-09", "2026-05"])
def test_canonical_files_still_take_the_exact_header_route(dataset):
    out = classify_batch([(str(p), p.read_bytes()) for p, fid, _ in files_with_truth(dataset)], registry())
    for p, fid, _ in files_with_truth(dataset):
        r = out[str(p)].result
        assert (r.status, r.category) == ("identified", fid)
        if r.category in CSV_IDS:
            assert r.method == "csv_exact_header" and r.confidence == 1.0


# ------------------------------------------------------------------------------------------------ tier B
@pytest.mark.parametrize("fid", CSV_IDS)
def test_reordered_file_maps_every_column_and_keeps_provenance(fid, tmp_path):
    rows = table(read(SEP, fid))
    order = list(reversed(range(len(rows[0]))))
    data = dump([[r[i] for i in order] for r in rows])
    r = cls(data)
    assert (r.status, r.category, r.method) == ("identified", fid, "csv_controlled_mapping")
    assert r.confidence < 1.0 and "reordered" in r.details["controlled_mapping"]["variations"]
    for m in r.details["controlled_mapping"]["mappings"]:
        assert m["source_header"] == rows[0][order[m["source_position"]]] == m["canonical_field"]
        assert m["canonical_position"] == canonical_header(fid).index(m["canonical_field"])
    # the pipeline uses exactly that mapping and yields the same records as the canonical file
    p = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path))
    var, ref = p.process_bytes(data, "v.csv", "2026-09"), p.process_bytes(read(SEP, fid), "c.csv", "2026-09")
    assert var.metadata.mapping_status == "complete" and var.mapping.unmapped_columns == []
    assert all(m.variation == "exact" and m.original_header == m.canonical_field for m in var.mapping.mappings)
    assert [rec.values for rec in var.records] == [rec.values for rec in ref.records]
    assert var.metadata.validation_status == ref.metadata.validation_status


def test_whitespace_and_case_follow_the_policy():
    h = canonical_header("IN-07")
    body = table(read(SEP, "IN-07"))[1:]
    padded, upper = dump([[f" {c} " for c in h]] + body), dump([[c.upper() for c in h]] + body)
    r = cls(padded)
    assert r.category == "IN-07" and r.details["controlled_mapping"]["variations"] == ["whitespace"]
    assert r.details["controlled_mapping"]["mappings"][0]["source_header"] == f" {h[0]} "   # original kept
    assert cls(upper).details["controlled_mapping"]["variations"] == ["case"]
    no_trim = MappingRules(MappingPolicy(trim_whitespace=False), [], "t")
    no_case = MappingRules(MappingPolicy(case_insensitive=False), [], "t")
    assert cls(padded, no_trim).status == "unknown" and cls(upper, no_case).status == "unknown"
    assert cls(padded, no_case).category == "IN-07" and cls(upper, no_trim).category == "IN-07"
    no_reorder = MappingRules(MappingPolicy(allow_reorder=False), [], "t")
    rev = dump([list(reversed(r)) for r in table(read(SEP, "IN-07"))])
    assert cls(rev, no_reorder).status == "unknown" and cls(rev, EXACT_ONLY_RULES).status == "unknown"


def test_pipeline_records_policy_normalised_mapping(tmp_path):
    h = canonical_header("IN-13")
    data = dump([[c.upper() for c in h]] + table(read(SEP, "IN-13"))[1:])
    res = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path)).process_bytes(data, "x.csv", "2026-09")
    assert res.classification.method == "csv_controlled_mapping"
    m = res.mapping.mappings[0]
    assert (m.source_column, m.original_header, m.canonical_field, m.method, m.variation, m.source_index) == \
        ("LINE_ID", "LINE_ID", "line_id", "policy_normalised", "case", 0)
    assert res.records[0].original["LINE_ID"] and res.records[0].values["line_id"] == res.records[0].original["LINE_ID"]


# ------------------------------------------------------------------------------------------------ tier C
def test_approved_alias_accepted_only_when_approved():
    h = canonical_header("IN-11")
    data = dump([["Txn ID"] + h[1:]] + table(read(SEP, "IN-11"))[1:])
    prod = cls(data)
    assert prod.status == "unknown" and prod.category is None
    assert [x["proposal_id"] for x in prod.diagnosis["unapproved_alias_proposals"]] == ["AP-IN-11-PK-TITLE"]
    assert "not approved" in prod.reason or "proposed" in prod.reason
    ok = cls(data, approved_test_rules())
    assert (ok.status, ok.category) == ("identified", "IN-11")
    assert ok.details["aliases_used"] == ["AA-IN-11-PK-TITLE"]
    m = ok.details["controlled_mapping"]["mappings"][0]
    assert (m["source_header"], m["canonical_field"], m["match"]) == ("Txn ID", "txn_id", "alias")


# ------------------------------------------------------------------------------------------------ rejections
def test_rejections_report_columns_and_never_drop_them(tmp_path):
    h = canonical_header("IN-02")
    rows = table(read(SEP, "IN-02"))
    extra = dump([h + ["analyst_comment"]] + [r + ["keep me"] for r in rows[1:]])
    r = cls(extra)
    assert r.status == "unknown"
    assert r.diagnosis["controlled_mapping"]["unexpected_columns"] == ["analyst_comment"]
    res = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path)).process_bytes(extra, "x.csv", "2026-09")
    assert res.records[0].original["analyst_comment"] == "keep me"          # data preserved, not discarded
    missing = cls(dump([r[:-1] for r in rows]))
    assert missing.diagnosis["controlled_mapping"]["missing_fields"] == [h[-1]]
    dup = cls(dump([h + [h[0].upper()]] + [r + [r[0]] for r in rows[1:]]))
    assert dup.diagnosis["controlled_mapping"]["duplicate_fields"] == {h[0]: [h[0], h[0].upper()]}


def test_unknown_header_diagnostic_is_useful():
    r = cls(dump([["col_1", "col_2", "col_3"], ["a", "b", "c"]]))
    assert r.status == "unknown" and "col_1" in r.reason and "documented UC-042 column names" in r.reason


# ------------------------------------------------------------------------------------------------ corpus
def test_corpus_is_reproducible_and_matches_the_committed_copy(tmp_path):
    a = build_variation_corpus.build(tmp_path / "a")
    b = build_variation_corpus.build(tmp_path / "b")
    assert a == b
    committed = json.loads((ROOT / "corpus" / "phase2_variations" / "manifest.json").read_text(encoding="utf-8"))
    assert committed["cases"] == a
    for c in a:
        assert (tmp_path / "a" / c["file"]).read_bytes() == (ROOT / "corpus" / "phase2_variations" / c["file"]).read_bytes()


def test_every_corpus_case_behaves_as_expected():
    rows = evaluate_variation_corpus.evaluate(ROOT / "corpus" / "phase2_variations")
    assert len({r["category"] for r in rows}) == 14
    assert [r["case_id"] for r in rows if r["result"] != "PASS"] == []
    types = {r["case_type"] for r in rows}
    assert types >= {"canonical", "renamed_file", "reordered", "whitespace", "case", "approved_alias",
                     "proposed_alias", "missing_column", "extra_column", "duplicate_mapping", "ambiguous_alias",
                     "unknown_header", "hard_negative"}


@pytest.mark.parametrize("case_id,expected", [
    ("HN_01_IN10_dressed_as_IN09", None), ("HN_02_IN09_named_as_cashbook", "IN-09"),
    ("HN_03_IN07_plus_IN08_columns", None), ("HN_04_IN08_reordered", "IN-08"),
    ("HN_05_IN06_named_as_internal", "IN-06"), ("HN_06_IN05_reduced_to_IN06_shared", None),
])
def test_hard_negatives(case_id, expected, tmp_path):
    corpus = ROOT / "corpus" / "phase2_variations"
    case = next(c for c in json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["cases"]
                if c["case_id"] == case_id)
    data = (corpus / case["file"]).read_bytes()
    assert cls(data).category == expected
    res = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path)).process_bytes(data, case["upload_filename"])
    assert res.metadata.evidence_category == expected
