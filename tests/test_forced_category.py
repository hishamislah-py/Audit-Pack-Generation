"""Phase 3B-0: a supplied (forced / human-confirmed) category never bypasses the controlled mapping rules for UC-042
categories. Generic synthetic schemas keep the generic map_columns behaviour."""
import csv
import io
import json
from pathlib import Path

import pytest

from smartparser import SmartParser
from smartparser.intake import EvidenceStore
from smartparser.mapping.controlled import is_controlled, load_rules
from smartparser.schemas import SchemaRegistry

from .conftest import FIXTURES
from .uc042_support import SEP, read, registry

FX = Path(__file__).parent / "fixtures" / "mapping_rules"
CSV_IDS = [f"IN-{i:02d}" for i in range(1, 15)]


def tbl(fid):
    return list(csv.reader(io.StringIO(read(SEP, fid).decode("utf-8"))))


def dump(rows):
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode()


def camel(s):
    a, *b = s.split("_")
    return a + "".join(w.capitalize() for w in b)


@pytest.fixture
def parser(tmp_path):
    def make(rules=None, schemas=None):
        return SmartParser(schemas=schemas or registry(), store=EvidenceStore(tmp_path / "store"), mapping_rules=rules)
    return make


def forced(parser_, data, cat, filename="upload.csv", **kw):
    return parser_.process_bytes(data, filename, "2026-09", forced_category=cat, **kw)


def accepted(r, cat):
    return (r.metadata.evidence_category == cat and r.metadata.classification_status == "identified"
            and r.classification.method == "manual" and r.metadata.mapping_status == "complete"
            and r.mapping.unmapped_columns == [])


def rejected(r):
    codes = [i.code.value for i in r.issues]
    return (r.metadata.evidence_category is None and r.metadata.classification_status == "unknown"
            and r.metadata.mapping_status == "not_attempted" and "forced_category_rejected" in codes
            and r.metadata.processing_status == "needs_resolution")


# ------------------------------------------------------------------------------------------- routing rule
def test_routing_predicate_is_explicit():
    reg = registry()
    assert [c for c in CSV_IDS if is_controlled(reg.get(c))] == CSV_IDS
    assert not any(is_controlled(reg.get(f"IN-{i}")) for i in range(15, 20))       # PDFs
    assert not any(is_controlled(s) for s in SchemaRegistry([]).all())              # stubs
    synthetic = SchemaRegistry.from_directory(FIXTURES / "schemas", allow_non_official=True)
    assert not any(is_controlled(s) for s in synthetic.all())


# ------------------------------------------------------------------------------------------- accepted
@pytest.mark.parametrize("fid", CSV_IDS)
def test_forced_canonical_and_reordered_accepted(fid, parser):
    p = parser()
    r = forced(p, read(SEP, fid), fid)
    assert accepted(r, fid) and {m.method.value for m in r.mapping.mappings} == {"exact"}
    assert r.classification.confidence is None and r.classification.details["category_source"] == "supplied"
    rows = tbl(fid)
    rev = forced(p, dump([list(reversed(x)) for x in rows]), fid)
    assert accepted(rev, fid) and "reordered" in rev.classification.details["controlled_mapping"]["variations"]
    assert [x.values for x in rev.records] == [x.values for x in r.records]


def test_forced_whitespace_and_case_accepted_under_policy(parser):
    rows = tbl("IN-12")
    ws = forced(parser(), dump([[f" {c} " for c in rows[0]]] + rows[1:]), "IN-12")
    up = forced(parser(), dump([[c.upper() for c in rows[0]]] + rows[1:]), "IN-12")
    assert accepted(ws, "IN-12") and {m.variation for m in ws.mapping.mappings} == {"whitespace"}
    assert ws.mapping.mappings[0].original_header == f" {rows[0][0]} "
    assert accepted(up, "IN-12") and {m.method.value for m in up.mapping.mappings} == {"policy_normalised"}


def test_forced_approved_alias_accepted_with_test_rules(parser):
    rules = load_rules(registry(), FX / "test_approved_aliases.json", FX / "test_alias_proposals.json")
    rows = tbl("IN-11")
    r = forced(parser(rules), dump([["Txn ID"] + rows[0][1:]] + rows[1:]), "IN-11")
    assert accepted(r, "IN-11")
    m = r.mapping.mappings[0]
    assert (m.original_header, m.canonical_field, m.method.value, m.alias_id) == ("Txn ID", "txn_id", "alias",
                                                                                   "AA-IN-11-PK-TITLE")


def test_camelcase_accepted_only_when_explicitly_approved(parser, tmp_path):
    rows = tbl("IN-09")
    data = dump([[camel(rows[0][0])] + rows[0][1:]] + rows[1:])            # bankEntryId
    assert rejected(forced(parser(), data, "IN-09"))
    cat = {"proposals": [{"proposal_id": "AP-T", "category": "IN-09", "canonical_field": "bank_entry_id",
                          "proposed_header": "bankEntryId", "reason": "test", "risk": "test", "status": "approved",
                          "decision": {"decided_by": "TEST FIXTURE - not a business approval",
                                       "decided_at": "2026-11-18"}}]}
    act = {"policy": {}, "aliases": [{"alias_id": "AA-T", "category": "IN-09", "canonical_field": "bank_entry_id",
                                      "alias": "bankEntryId", "proposal_id": "AP-T"}]}
    (tmp_path / "c.json").write_text(json.dumps(cat), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(act), encoding="utf-8")
    rules = load_rules(registry(), tmp_path / "a.json", tmp_path / "c.json")
    assert accepted(forced(parser(rules), data, "IN-09"), "IN-09")


# ------------------------------------------------------------------------------------------- rejected
def _variants(fid):
    rows = tbl(fid)
    h, body = rows[0], rows[1:]
    return {
        "camelCase": dump([[camel(c) for c in h]] + body),
        "hyphenated": dump([[c.replace("_", "-") for c in h]] + body),
        "proposed_only_alias": dump([[" ".join(w.upper() if w == "id" else w.capitalize() for w in h[0].split("_"))]
                                     + h[1:]] + body),
        "missing_field": dump([r[:-1] for r in rows]),
        "extra_field": dump([h + ["note"]] + [r + ["kept"] for r in body]),
        "duplicate_target": dump([h + [h[0].upper()]] + [r + [r[0]] for r in body]),
    }


@pytest.mark.parametrize("fid", CSV_IDS)
@pytest.mark.parametrize("kind", ["camelCase", "hyphenated", "proposed_only_alias", "missing_field", "extra_field",
                                  "duplicate_target"])
def test_forced_category_does_not_override_structural_failures(fid, kind, parser):
    data = _variants(fid)[kind]
    if kind == "camelCase" and all("_" not in c for c in tbl(fid)[0]):
        pytest.skip("no multi-word column")
    r = forced(parser(), data, fid)
    assert rejected(r), (kind, r.classification.reason)
    assert r.classification.details["forced_category"] == fid
    assert r.classification.diagnosis["controlled_mapping"]["rejections"]
    source_rows = len(tbl(fid)) - 1                                    # IN-14 fixture has a header only
    assert len(r.records) == source_rows                               # source cells kept, nothing dropped
    if source_rows:
        assert r.records[0].original


def test_extra_column_is_reported_not_dropped(parser):
    r = forced(parser(), _variants("IN-02")["extra_field"], "IN-02")
    assert r.classification.diagnosis["controlled_mapping"]["unexpected_columns"] == ["note"]
    assert r.records[0].original["note"] == "kept" and r.records[0].source_line == 2


def test_forced_ambiguous_alias_rejected(parser):
    rows = tbl("IN-09")
    i = rows[0].index("bank_reference")
    data = dump([rows[0][:i] + ["Reference"] + rows[0][i + 1:]] + rows[1:])
    r = forced(parser(), data, "IN-09")
    assert rejected(r) and "Reference" in r.classification.diagnosis["controlled_mapping"]["unexpected_columns"]


@pytest.mark.parametrize("content,claimed", [("IN-09", "IN-10"), ("IN-10", "IN-09"), ("IN-07", "IN-08"),
                                             ("IN-08", "IN-07"), ("IN-05", "IN-06"), ("IN-06", "IN-05")])
def test_wrong_forced_category_rejected_for_confusable_pairs(content, claimed, parser):
    r = forced(parser(), read(SEP, content), claimed)
    assert rejected(r)
    assert r.classification.details["content_classification"]["category"] == content
    assert f"identifies as {content}" in r.classification.reason       # reported, never substituted silently


@pytest.mark.parametrize("pdf_cat", ["IN-15", "IN-17", "IN-19"])
def test_forcing_a_pdf_category_onto_a_csv_is_rejected(pdf_cat, parser):
    r = forced(parser(), read(SEP, "IN-09"), pdf_cat)
    assert rejected(r) and "PDF evidence category" in r.classification.reason


def test_misleading_filename_never_decides(parser):
    p = parser()
    ok = forced(p, read(SEP, "IN-09"), "IN-09", filename="sga_cashbook_entries_2026-09.csv")
    bad = forced(p, read(SEP, "IN-09"), "IN-10", filename="sga_cashbook_entries_2026-09.csv")
    assert accepted(ok, "IN-09") and rejected(bad)


def test_manual_mapping_refused_for_uc042_categories(parser):
    rows = tbl("IN-09")
    data = dump([["bankEntryId"] + rows[0][1:]] + rows[1:])
    with pytest.raises(ValueError, match="manual_mapping is not accepted for IN-09"):
        forced(parser(), data, "IN-09", manual_mapping={"bankEntryId": "bank_entry_id"})
    with pytest.raises(ValueError, match="manual_mapping is not accepted for IN-09"):
        parser().process_bytes(read(SEP, "IN-09"), "x.csv", "2026-09", manual_mapping={"bank_entry_id": "bank_entry_id"})


# ------------------------------------------------------------------------------------------- generic path intact
def test_generic_synthetic_schema_keeps_loose_mapping(parser):
    synthetic = SchemaRegistry.from_directory(FIXTURES / "schemas", allow_non_official=True)
    data = b"Entry-ID,Posting Date,AMT,CCY\nE1,01/10/2026,100.00,gbp\n"
    r = parser(schemas=synthetic).process_bytes(data, "x.csv", "2026-10", forced_category="TST-LEDGER")
    assert r.metadata.evidence_category == "TST-LEDGER" and r.metadata.mapping_status == "complete"
    assert {m.method.value for m in r.mapping.mappings} >= {"normalised", "alias"}
    r2 = parser(schemas=synthetic).process_bytes(
        b"Ref No,Booked,Sum,Ccy\nR1,2026-10-01,3.50,GBP\n", "y.csv", "2026-10", forced_category="TST-LEDGER",
        manual_mapping={"Ref No": "entry_id", "Booked": "entry_date", "Sum": "amount"})
    assert r2.metadata.mapping_status == "complete" and r2.classification.method == "manual"


def test_production_rules_still_approve_nothing():
    assert load_rules(registry()).aliases == []
