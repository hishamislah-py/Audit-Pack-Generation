"""Unit tests for individual modules (registry, identification, normalisers, mapping)."""
from decimal import Decimal

import pytest

from smartparser.identify import IdentificationError, detect_delimiter, identify
from smartparser.mapping.engine import map_columns
from smartparser.mapping.names import normalise_name
from smartparser.mapping.templates import TemplateRegistry, TemplateStatus, layout_fingerprint
from smartparser.normalise import values as nv
from smartparser.schemas import (
    OFFICIAL_CATEGORIES, SchemaDefinition, SchemaRegistry, SchemaRegistryError,
)


# ---------------------------------------------------------------- schema registry
def test_official_registry_has_19_missing_stubs():
    # Phase 1 populated the shipped definitions from UC-042 (see test_registry.py). The stub behaviour is unchanged
    # and still applies to any registry without definitions: SchemaRegistry([]) fills all 19 categories with stubs.
    reg = SchemaRegistry([])
    assert len(reg.all()) == 19 == len(OFFICIAL_CATEGORIES)
    assert sorted(reg.missing_categories()) == sorted(OFFICIAL_CATEGORIES)
    assert reg.defined() == []
    assert reg.get("IN-18").optional_evidence and reg.get("IN-19").optional_evidence
    assert reg.get("IN-15").evidence_format == "pdf"


def test_schema_rules():
    f = [{"name": "a", "type": "string"}]
    with pytest.raises(ValueError, match="definition_source"):
        SchemaDefinition(category="X", title="x", evidence_format="csv",
                         verification_status="verified", fields=f)
    with pytest.raises(ValueError, match="matches both"):
        SchemaDefinition(category="X", title="x", evidence_format="csv", verification_status="provisional",
                         fields=[{"name": "amount", "type": "decimal", "aliases": ["value"]},
                                 {"name": "Value", "type": "decimal"}])
    with pytest.raises(ValueError, match="must define fields"):
        SchemaDefinition(category="X", title="x", evidence_format="csv", verification_status="provisional")
    with pytest.raises(SchemaRegistryError, match="Unknown category"):
        SchemaRegistry([SchemaDefinition(category="IN-99", title="x", evidence_format="csv")])
    with pytest.raises(SchemaRegistryError, match="contradicts"):
        SchemaRegistry([SchemaDefinition(category="IN-15", title="x", evidence_format="csv")])


# ---------------------------------------------------------------- identification
def test_identify_formats():
    assert identify(b"%PDF-1.7\n...", "a.bin").detected_format == "pdf"
    assert identify(b"PK\x03\x04rest", "a.zip").detected_format == "zip"
    with pytest.raises(IdentificationError) as e:
        identify(b"\xd0\xcf\x11\xe0" + b"\x00" * 50, "a.csv")
    assert e.value.kind == "unsupported"
    with pytest.raises(IdentificationError) as e:
        identify(b"just some prose without structure", "notes.txt2")
    assert e.value.kind == "unsupported"


def test_delimiter_respects_quotes():
    text = 'a;b;c\n"x, y, z";2;3\n"p, q";5;6\n'
    assert detect_delimiter(text)[0] == ";"
    assert detect_delimiter('a,b\n"1;2;3",4\n')[0] == ","


# ---------------------------------------------------------------- normalisation
@pytest.mark.parametrize("raw,conv,expected", [
    ("1,234.56", ".", "1234.56"), ("(1,000.00)", ".", "-1000.00"), ("100-", ".", "-100"),
    ("€ 5.10", ".", "5.10"), ("-£3.00", ".", "-3.00"), ("£-3.00", ".", "-3.00"),
    ("1 234 567.89", ".", "1234567.89"), ("1.234,56", ",", "1234.56"), ("0.000001", ".", "0.000001"),
    ("100.10 EUR", ".", "100.10"),
])
def test_parse_decimal_ok(raw, conv, expected):
    p = nv.parse_decimal(raw, conv)
    assert p.ok and p.value == Decimal(expected) and str(p.value) == str(Decimal(expected))


@pytest.mark.parametrize("raw", ["1,23.4", "12,5", "1e3", "abc", "1.2.3", "--1", "(-1)", "12 34"])
def test_parse_decimal_rejects(raw):
    assert not nv.parse_decimal(raw, ".").ok


def test_decimal_convention_detection():
    assert nv.detect_decimal_convention(["1.234,56", "12,5"]) == (",", None)
    assert nv.detect_decimal_convention(["1,234.56", "1.5"]) == (".", None)
    assert nv.detect_decimal_convention(["1,234", "5,000"]) == (".", "ambiguous")
    assert nv.detect_decimal_convention(["1,234.56", "12,5"])[1] == "inconsistent"


def test_integer_and_bool_and_currency():
    assert nv.parse_integer("1,000").value == 1000
    assert not nv.parse_integer("1.5").ok
    assert not nv.parse_integer("10.0").ok
    assert nv.parse_boolean("Y").value is True and nv.parse_boolean("0").value is False
    assert nv.parse_currency_code(" eur ").value == "EUR"
    p = nv.parse_currency_code("ZZZ")
    assert p.ok and "unknown_iso4217_code" in p.notes


def test_datetime():
    assert nv.parse_datetime("2026-10-01T10:15:00Z").value.tzinfo is not None
    assert nv.parse_datetime("01/10/2026 09:30").value.hour == 9
    assert not nv.parse_datetime("2026-10-01").ok       # date only where datetime required
    assert not nv.parse_date("31/04/2026").ok


# ---------------------------------------------------------------- mapping
SCHEMA = SchemaDefinition(
    category="T", title="t", evidence_format="csv", verification_status="provisional",
    schema_version="1.0.0",
    fields=[{"name": "currency", "type": "currency_code", "required": True, "aliases": ["CCY"]},
            {"name": "amount", "type": "decimal", "required": True},
            {"name": "note", "type": "string"}])


def test_name_normalisation():
    assert normalise_name(" Client ID ") == normalise_name("clientId") == normalise_name("client-id") == "client_id"
    assert normalise_name("﻿Amount (GBP)") == "amount_gbp"


def test_mapping_tiers_and_missing():
    m = map_columns(["CCY", "Note", "Extra"], SCHEMA)
    assert {x.canonical_field: x.method.value for x in m.mappings} == {"currency": "alias", "note": "normalised"}
    assert m.unmapped_columns == ["Extra"]
    assert m.missing_required_fields == ["amount"] and m.status == "incomplete"


def test_template_compatibility_and_versioning(tmp_path):
    reg = TemplateRegistry(tmp_path / "t.json")
    t1 = reg.add("T", "1.0.0", ["Sum", "C"], {"Sum": "amount"}, status=TemplateStatus.VALIDATED)
    t2 = reg.add("T", "1.0.0", ["Sum", "C"], {"Sum": "amount", "C": "currency"}, status=TemplateStatus.VALIDATED)
    assert t2.version == 2 and reg.all()[0].status == "superseded"
    assert t1.layout_fingerprint == layout_fingerprint(["C", "Sum"])   # order independent
    m = map_columns(["C", "Sum"], SCHEMA, reg)
    assert m.status == "complete" and m.template_id == t2.template_id
    assert reg.find_compatible(["Sum", "C"], "T", "2.0.0") == []     # schema version must match
    # persisted and reloadable
    assert len(TemplateRegistry(tmp_path / "t.json").all()) == 2
    with pytest.raises(ValueError):
        reg.add("T", "1.0.0", ["A", "B"], {"A": "amount", "B": "amount"})
