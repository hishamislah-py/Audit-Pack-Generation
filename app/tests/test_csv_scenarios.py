"""End-to-end CSV scenarios from spec section 8 (items 1-9, 16-19 for CSV).

Each test states the expected behaviour in its docstring and asserts it.
"""
from decimal import Decimal
from datetime import date

from smartparser import SmartParser
from smartparser.intake import EvidenceStore
from smartparser.mapping.templates import TemplateStatus
from smartparser.schemas import SchemaRegistry

from .conftest import LEDGER_OK, codes


# 1 --------------------------------------------------------------------------
def test_01_correctly_structured_csv(run):
    """Identified as TST-LEDGER by header match, all fields mapped exactly,
    values normalised (Decimal, date), valid, original values preserved."""
    r = run(LEDGER_OK)
    m = r.metadata
    assert m.evidence_category == "TST-LEDGER"
    assert m.classification_status == "identified"
    assert r.classification.method == "csv_header_match"
    assert m.extraction_status == "success"
    assert m.mapping_status == "complete"
    assert all(x.method == "exact" for x in r.mapping.mappings)
    assert m.validation_status in ("valid", "valid_with_warnings")
    assert r.validation.error_count == 0
    assert len(r.records) == 3
    rec = r.records[2]
    assert rec.values["amount"] == Decimal("1250.75")
    assert rec.values["entry_date"] == date(2026, 10, 3)
    assert rec.values["description"] == "Transfer, inbound"   # quoted delimiter kept
    assert rec.original["amount"] == "1250.75"
    assert rec.source_line == 4 and rec.row_number == 3
    assert r.flags.parsed_successfully and not r.flags.needs_resolution
    # provisional test schema is flagged, never presented as verified
    assert "schema_unverified" in codes(r)
    assert m.processing_status == "completed_with_warnings"


# 2 --------------------------------------------------------------------------
def test_02_reordered_columns(run):
    """Column order does not matter: same category, same mapping by name."""
    csv = ("currency,description,amount,entry_id,entry_date\n"
           "GBP,Opening,100.00,E1,2026-10-01\n")
    r = run(csv)
    assert r.metadata.evidence_category == "TST-LEDGER"
    assert r.metadata.mapping_status == "complete"
    assert {m.canonical_field: m.source_index for m in r.mapping.mappings}["entry_id"] == 3
    assert r.records[0].values["amount"] == Decimal("100.00")
    assert r.validation.error_count == 0


# 3 --------------------------------------------------------------------------
def test_03_alternative_column_names(run):
    """Known aliases (CCY, AMT, Posting Date) and normalised variants
    (Entry-ID) map deterministically; the method used is recorded."""
    csv = ("Entry-ID,Posting Date,AMT,CCY\n"
           "E1,01/10/2026,100.00,gbp\n"
           "E2,15/10/2026,5.00,EUR\n")
    r = run(csv)
    methods = {m.canonical_field: m.method.value for m in r.mapping.mappings}
    assert methods == {"entry_id": "normalised", "entry_date": "alias",
                       "amount": "alias", "currency": "alias"}
    assert r.metadata.mapping_status == "complete"
    assert r.records[0].values["currency"] == "GBP"
    assert r.records[0].original["CCY"] == "gbp"
    assert r.records[1].values["entry_date"] == date(2026, 10, 15)


# 4 --------------------------------------------------------------------------
def test_04_extra_columns_preserved_not_invalidating(run):
    """Extra columns are preserved per record and listed as unmapped; they
    are INFO only and do not invalidate the file."""
    csv = ("entry_id,entry_date,amount,currency,Internal Note,Branch\n"
           "E1,2026-10-01,100.00,GBP,check later,LDN\n")
    r = run(csv)
    assert r.mapping.unmapped_columns == ["Internal Note", "Branch"]
    assert r.records[0].unmapped == {"Internal Note": "check later", "Branch": "LDN"}
    assert r.flags.unmapped_columns
    assert r.validation.error_count == 0
    assert r.metadata.validation_status != "invalid"
    unmapped_issues = [i for i in r.validation.issues if i.code == "unmapped_column"]
    assert all(i.severity == "info" for i in unmapped_issues) and len(unmapped_issues) == 2


# 5 --------------------------------------------------------------------------
def test_05_missing_optional_fields(run):
    """Missing optional fields are reported (info) and do not invalidate."""
    csv = "entry_id,entry_date,amount,currency\nE1,2026-10-01,1.00,GBP\n"
    r = run(csv)
    assert set(r.mapping.missing_optional_fields) == {"description", "settled", "line_count", "status"}
    assert r.mapping.missing_required_fields == []
    assert r.validation.error_count == 0
    assert not r.flags.missing_required_fields


# 6 --------------------------------------------------------------------------
def test_06_missing_required_field(run):
    """A missing required column is reported as an error; no value is invented;
    the file is still classified (identified) but validation is invalid."""
    csv = "entry_id,entry_date,description,currency\nE1,2026-10-01,x,GBP\n"
    r = run(csv)
    assert r.metadata.classification_status == "identified"
    assert r.metadata.evidence_category == "TST-LEDGER"
    assert r.mapping.missing_required_fields == ["amount"]
    assert r.metadata.mapping_status == "incomplete"
    assert r.metadata.validation_status == "invalid"
    assert "missing_required_field" in codes(r)
    assert "amount" not in r.records[0].values         # not filled
    assert r.flags.missing_required_fields
    assert r.metadata.processing_status == "completed_with_errors"


# 7 --------------------------------------------------------------------------
def test_07_invalid_data_types(run):
    """Unparseable values are errors with row/column/original value; the
    normalised value is None, the original is kept; other rows unaffected."""
    csv = ("entry_id,entry_date,amount,currency,line_count,settled,status\n"
           "E1,2026-10-01,abc,GBP,2,yes,OPEN\n"
           "E2,2026-02-30,10.00,GB,-1,maybe,PENDING\n"
           "E3,2026-10-03,10.005,GBP,3,no,CLOSED\n"
           "E4,2026-10-04,1e5,GBP,1,no,OPEN\n"
           "E5,2026-10-05,7.00,GBP,1,no,OPEN\n")
    r = run(csv)
    errs = [(i.code.value, i.row, i.field) for i in r.validation.issues if i.severity == "error"]
    assert ("invalid_value", 1, "amount") in errs
    assert ("invalid_value", 2, "entry_date") in errs      # 30 Feb
    assert ("invalid_value", 2, "currency") in errs        # 'GB'
    assert ("constraint_violation", 2, "line_count") in errs
    assert ("invalid_value", 2, "settled") in errs
    assert ("constraint_violation", 2, "status") in errs
    assert ("constraint_violation", 3, "amount") in errs   # >2 dp
    assert ("invalid_value", 4, "amount") in errs          # scientific notation rejected
    assert r.records[0].values["amount"] is None
    assert r.records[0].original["amount"] == "abc"
    assert r.records[0].invalid_fields == ["amount"]
    assert r.records[4].invalid_fields == []
    assert r.flags.invalid_values and r.flags.partially_parsed
    assert r.metadata.validation_status == "invalid"
    bad = next(i for i in r.validation.issues if i.row == 1 and i.field == "amount")
    assert bad.value == "abc" and bad.column == "amount" and bad.source_line == 2


# 8 --------------------------------------------------------------------------
def test_08_different_date_formats(run):
    """Mixed but unambiguous date representations are normalised to ISO dates."""
    csv = ("entry_id,entry_date,amount,currency\n"
           "E1,2026-10-01,1,GBP\n"
           "E2,15/10/2026,1,GBP\n"
           "E3,03 Oct 2026,1,GBP\n"
           "E4,20261004,1,GBP\n"
           "E5,October 5 2026,1,GBP\n"
           "E6,2026/10/06,1,GBP\n"
           "E7,07-Oct-26,1,GBP\n")
    r = run(csv)
    got = [x.values["entry_date"] for x in r.records]
    assert got == [date(2026, 10, d) for d in (1, 15, 3, 4, 5, 6, 7)]
    assert "invalid_value" not in codes(r)
    assert "two_digit_year" in codes(r)  # the 26 in 07-Oct-26 is reported, not silent


def test_08b_ambiguous_date_order_is_reported(run):
    """All-ambiguous DD/MM vs MM/DD: UK default applied and a warning raised."""
    csv = "entry_id,entry_date,amount,currency\nE1,01/02/2026,1,GBP\nE2,03/04/2026,1,GBP\n"
    r = run(csv)
    assert r.records[0].values["entry_date"] == date(2026, 2, 1)
    w = [i for i in r.validation.issues if i.code == "ambiguous_date_order"]
    assert w and w[0].severity == "warning"


def test_08c_us_order_detected_from_column_evidence(run):
    csv = "entry_id,entry_date,amount,currency\nE1,10/25/2026,1,GBP\nE2,01/02/2026,1,GBP\n"
    r = run(csv)
    assert r.records[1].values["entry_date"] == date(2026, 1, 2)
    assert "ambiguous_date_order" not in codes(r)


def test_08d_inconsistent_date_order_needs_resolution(run):
    csv = ("entry_id,entry_date,amount,currency\n"
           "E1,25/10/2026,1,GBP\nE2,10/25/2026,1,GBP\nE3,01/02/2026,1,GBP\n")
    r = run(csv)
    assert "inconsistent_date_order" in codes(r)
    assert r.records[0].values["entry_date"] == date(2026, 10, 25)
    assert r.records[2].values["entry_date"] is None      # genuinely undeterminable
    assert r.flags.needs_resolution
    assert r.metadata.processing_status == "needs_resolution"


def test_08e_decimal_representations(run):
    csv = ("entry_id,entry_date,amount,currency\n"
           "E1,2026-10-01,\"1,234.56\",GBP\n"
           "E2,2026-10-01,(50.00),GBP\n"
           "E3,2026-10-01,£12.00,GBP\n"
           "E4,2026-10-01,-0.10,GBP\n"
           "E5,2026-10-01,GBP 7.25,GBP\n")
    r = run(csv)
    assert [x.values["amount"] for x in r.records] == [
        Decimal("1234.56"), Decimal("-50.00"), Decimal("12.00"), Decimal("-0.10"), Decimal("7.25")]
    assert r.validation.error_count == 0


def test_08f_decimal_comma_file(run):
    """A semicolon file with European decimals is detected per column."""
    csv = ("entry_id;entry_date;amount;currency\n"
           "E1;01.10.2026;1.234,56;EUR\n"
           "E2;02.10.2026;12,50;EUR\n")
    r = run(csv)
    assert r.identification.delimiter == ";"
    assert [x.values["amount"] for x in r.records] == [Decimal("1234.56"), Decimal("12.50")]


# 9 --------------------------------------------------------------------------
def test_09_unfamiliar_layout(run):
    """Headers matching no schema: category unknown, needs resolution, but
    the CSV is still extracted and every original value preserved."""
    csv = "Foo,Bar,Baz\n1,2,3\n4,5,6\n"
    r = run(csv)
    assert r.metadata.classification_status == "unknown"
    assert r.metadata.evidence_category is None
    assert r.metadata.extraction_status == "success"
    assert r.flags.unknown_category and r.flags.needs_resolution
    assert r.metadata.processing_status == "needs_resolution"
    assert r.records[1].original == {"Foo": "4", "Bar": "5", "Baz": "6"}
    assert "unknown_category" in codes(r)


def test_09b_unfamiliar_layout_with_validated_template(parser):
    """Once a human-validated template exists for that layout, the same layout
    is classified and mapped via the template (tier 4), filename irrelevant."""
    headers = ["Ref No", "Booked", "Sum", "Ccy Code", "Free text"]
    parser.templates.add("TST-LEDGER", "1.0.0", headers,
                         {"Ref No": "entry_id", "Booked": "entry_date", "Sum": "amount",
                          "Ccy Code": "currency"}, status=TemplateStatus.VALIDATED)
    data = b"Booked,Ref No,Sum,Ccy Code,Free text\n2026-10-01,R1,9.99,GBP,x\n"
    r = parser.process_bytes(data, "totally_random_name.csv", "2026-10")
    assert r.metadata.evidence_category == "TST-LEDGER"
    assert r.classification.method == "mapping_template"
    assert {m.method.value for m in r.mapping.mappings} == {"template"}
    assert r.mapping.unmapped_columns == ["Free text"]
    assert r.records[0].values["amount"] == Decimal("9.99")


def test_09c_proposed_template_not_applied(parser):
    headers = ["Ref No", "Booked", "Sum", "Ccy Code"]
    parser.templates.add("TST-LEDGER", "1.0.0", headers,
                         {"Ref No": "entry_id", "Booked": "entry_date", "Sum": "amount",
                          "Ccy Code": "currency"})  # PROPOSED by default
    r = parser.process_bytes(b"Ref No,Booked,Sum,Ccy Code\nR1,2026-10-01,1,GBP\n", "a.csv", "2026-10")
    assert r.metadata.classification_status == "unknown"


def test_09d_other_category_discriminated(run):
    """A balance file shares 'currency' with the ledger but is classified correctly."""
    csv = "Acct,balance_date,closing_balance,CCY\nA1,2026-10-31,500.00,GBP\n"
    r = run(csv)
    assert r.metadata.evidence_category == "TST-BALANCE"
    cands = {c.category for c in r.classification.candidates}
    assert "TST-LEDGER" in cands     # considered, but rejected (signature missing)


# 16 -------------------------------------------------------------------------
def test_16_csv_with_wrong_extension(run):
    """Content decides the format: a CSV named .pdf is parsed as CSV with an
    extension-mismatch warning."""
    r = run(LEDGER_OK, filename="ledger.pdf")
    assert r.metadata.file_format == "csv"
    assert "extension_mismatch" in codes(r)
    assert r.metadata.evidence_category == "TST-LEDGER"


def test_16b_binary_with_csv_extension_rejected(run):
    r = run(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4, filename="data.csv")
    assert r.metadata.processing_status == "rejected"
    assert "unsupported_file" in codes(r)


# 17 -------------------------------------------------------------------------
def test_17_corrupted_and_empty_files(run):
    assert run(b"", filename="a.csv").metadata.processing_status == "rejected"
    assert "empty_file" in codes(run(b"   \n\n", filename="b.csv"))
    garbage = bytes([0x00, 0xFF, 0x13, 0x88, 0x00, 0x9C]) * 300
    r = run(garbage, filename="c.csv")
    assert r.metadata.processing_status == "rejected"
    assert "corrupted_file" in codes(r)
    # Original bytes are still hashed/preserved for audit
    assert r.metadata.sha256 and r.metadata.provenance.stored_path


def test_17b_malformed_quoting_partial(run):
    """Unterminated quote mid-file: rows before it are kept, extraction partial."""
    csv = 'entry_id,entry_date,amount,currency\nE1,2026-10-01,1,GBP\nE2,2026-10-02,"2,GBP\nE3,x,y,z\n'
    r = run(csv)
    assert r.metadata.extraction_status in ("partial", "failed")
    assert "malformed_csv" in codes(r)


def test_17c_ragged_rows(run):
    csv = "entry_id,entry_date,amount,currency\nE1,2026-10-01,1,GBP\nE2,2026-10-02,2\nE3,2026-10-03,3,GBP,EXTRA\n"
    r = run(csv)
    rag = [i for i in r.validation.issues if i.code == "ragged_row"]
    assert [i.row for i in rag] == [2, 3]
    assert r.records[2].unmapped["__extra_value_1"] == "EXTRA"


# 18 -------------------------------------------------------------------------
def test_18_duplicate_upload_same_period(run):
    """Same bytes twice in the same period: second result warns; both are
    processed independently with distinct evidence ids."""
    a = run(LEDGER_OK, filename="x.csv")
    b = run(LEDGER_OK, filename="x_copy.csv")
    assert "duplicate_upload" not in codes(a)
    assert "duplicate_upload" in codes(b)
    assert a.metadata.sha256 == b.metadata.sha256
    assert a.metadata.evidence_id != b.metadata.evidence_id
    assert a.metadata.provenance.stored_path == b.metadata.provenance.stored_path  # stored once


def test_18b_duplicate_records_within_file(run):
    csv = ("entry_id,entry_date,amount,currency\n"
           "E1,2026-10-01,1,GBP\nE1,2026-10-02,2,GBP\nE1,2026-10-02,2,GBP\n")
    r = run(csv)
    dups = [i for i in r.validation.issues if i.code == "duplicate_record"]
    assert [i.row for i in dups] == [2, 3]
    assert any(i.code == "duplicate_row" and i.row == 3 for i in r.validation.issues)


# 19 -------------------------------------------------------------------------
def test_19_different_reporting_months(run):
    """Same file for two months: kept as separate evidence tagged with its own
    period; cross-period reuse is flagged, not silently merged."""
    oct_ = run(LEDGER_OK, period="2026-10")
    nov = run(LEDGER_OK, period="2026-11")
    assert oct_.metadata.reporting_period == "2026-10"
    assert nov.metadata.reporting_period == "2026-11"
    assert "duplicate_upload" not in codes(nov)
    assert "duplicate_upload_other_period" in codes(nov)


def test_19b_invalid_period_rejected(run):
    import pytest
    with pytest.raises(ValueError):
        run(LEDGER_OK, period="Oct-2026")


# extra --------------------------------------------------------------------------
def test_encodings_and_delimiters(run):
    base = "entry_id\tentry_date\tamount\tcurrency\tdescription\nE1\t2026-10-01\t1.00\tEUR\tCafé Zürich\n"
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
        r = run(base, encoding=enc, filename=f"t_{enc}.csv")
        assert r.metadata.evidence_category == "TST-LEDGER", enc
        assert r.records[0].values["description"] == "Café Zürich", enc
        assert r.identification.delimiter == "\t"
    pipe = run("entry_id|entry_date|amount|currency\nE1|2026-10-01|1|GBP\n")
    assert pipe.identification.delimiter == "|" and pipe.validation.error_count == 0


def test_preamble_and_empty_rows(run):
    csv = ("Ledger export\nGenerated 2026-11-01\n\n"
           "entry_id,entry_date,amount,currency\nE1,2026-10-01,1,GBP\n\n,,,\nE2,2026-10-02,2,GBP\n")
    r = run(csv)
    assert r.csv_extraction.header_line == 4
    assert len(r.records) == 2 and r.records[1].source_line == 8
    assert "preamble_rows" in codes(r) and "empty_row" in codes(r)


def test_null_handling(run):
    csv = "entry_id,entry_date,amount,currency,description\nE1,2026-10-01,N/A,GBP,NULL\n"
    r = run(csv)
    assert r.records[0].values["description"] is None
    assert any(i.code == "null_not_allowed" and i.field == "amount" for i in r.validation.issues)


def test_ambiguous_mapping_recorded_not_chosen(run):
    """Two source columns for one field: recorded as ambiguous, neither chosen."""
    csv = "entry_id,entry_date,amount,AMT,currency\nE1,2026-10-01,1,2,GBP\n"
    r = run(csv)
    assert r.metadata.mapping_status == "ambiguous"
    assert r.mapping.ambiguities[0].source_columns == ["amount", "AMT"]
    assert "amount" not in r.records[0].values
    assert r.records[0].original["AMT"] == "2"
    assert r.flags.needs_resolution
    assert r.metadata.processing_status == "needs_resolution"


def test_forced_category_and_manual_mapping(run):
    csv = "Ref No,Booked,Sum,Ccy\nR1,2026-10-01,3.50,GBP\n"
    r = run(csv, forced_category="TST-LEDGER",
            manual_mapping={"Ref No": "entry_id", "Booked": "entry_date", "Sum": "amount"})
    assert r.classification.method == "manual"
    assert r.metadata.mapping_status == "complete"   # Ccy -> currency via normalised alias
    assert r.records[0].values["amount"] == Decimal("3.50")


def test_official_registry_recognised_but_schema_unavailable(tmp_path):
    """With an official registry of stubs, a user-assigned IN category is
    'recognised but not mapped': originals preserved, needs resolution.
    (Phase 1 populated the shipped definitions; SchemaRegistry([]) is the all-stub registry this test was written for.
    The populated registry's behaviour is tested in test_registry.py / test_classification_baseline.py.)"""
    p = SmartParser(schemas=SchemaRegistry([]), store=EvidenceStore(tmp_path))
    r = p.process_bytes(LEDGER_OK.encode(), "x.csv", "2026-10", forced_category="IN-11")
    assert r.metadata.evidence_category == "IN-11"
    assert r.metadata.extraction_status == "success"
    assert r.metadata.mapping_status == "schema_unavailable"
    assert r.records[0].original["amount"] == "100.00"
    assert r.metadata.processing_status == "needs_resolution"
    auto = p.process_bytes(LEDGER_OK.encode(), "y.csv", "2026-10")
    assert auto.metadata.classification_status == "unknown"
    assert "No CSV schema definitions" in auto.classification.reason


def test_pdf_and_zip_not_yet_implemented(run):
    r = run(b"%PDF-1.4\n%fake\n", filename="letter.pdf")
    assert r.metadata.file_format == "pdf"
    assert r.metadata.processing_status == "not_implemented"
    z = run(b"PK\x05\x06" + b"\x00" * 18, filename="pack.zip")
    assert z.metadata.file_format == "zip" and z.metadata.processing_status == "not_implemented"


def test_result_serialises_to_json(run):
    import json
    r = run(LEDGER_OK)
    doc = json.loads(r.model_dump_json())
    assert doc["records"][0]["values"]["amount"] == "100.00"   # Decimal -> string, no float
    assert doc["metadata"]["sha256"] == r.metadata.sha256
