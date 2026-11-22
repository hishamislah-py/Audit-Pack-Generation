"""Phase 1 baseline: content-only classification of the 19 UC-042 evidence categories.

Ground truth comes from each fixture dataset's own manifest; the classifier only ever receives bytes.
"""
import csv
import hashlib
import io

import pytest

from smartparser import SmartParser
from smartparser.classify.csv_classifier import EXACT_ONLY_RULES
from smartparser.classify.evidence import classify_batch, classify_bytes
from smartparser.classify.pdf_classifier import letter_refs_from_inventory
from smartparser.intake import EvidenceStore

from .pdfgen import blank_pdf, image_only_pdf, text_pdf
from .uc042_support import MAY, SEP, UC042_ROOT, canonical_header, files_with_truth, needs_uc042, read, registry

CSV_IDS = [f"IN-{i:02d}" for i in range(1, 15)]


def classify(data: bytes, refs=None):
    # Phase 1 behaviour is pinned with the exact-only rules: these tests describe the canonical-header path. The
    # Phase 2 controlled-mapping tiers (reorder / whitespace / case / approved alias) are tested in test_controlled_mapping.py.
    return classify_bytes(data, registry(), refs, rules=EXACT_ONLY_RULES).result


def refs_for(dataset):
    return letter_refs_from_inventory(list(csv.DictReader(io.StringIO(read(dataset, "IN-02").decode("utf-8")))),
                                      registry())


def make_csv(header, rows=(), delimiter=",") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def rows_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))[1:]


# ------------------------------------------------------------------------------------------- fixture integrity
@pytest.mark.parametrize("dataset", [SEP, MAY], ids=["2026-09", "2026-05"])
def test_fixtures_are_unmodified_copies(dataset):
    for path, _fid, row in files_with_truth(dataset):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], path.name


# ------------------------------------------------------------------------------------------- every category
@pytest.mark.parametrize("dataset", [SEP, MAY], ids=["2026-09", "2026-05"])
def test_every_file_of_a_dataset_is_classified_from_content(dataset):
    truth = files_with_truth(dataset)
    keyed = {f"K{i}": (p, fid) for i, (p, fid, _) in enumerate(truth)}
    out = classify_batch([(k, p.read_bytes()) for k, (p, _) in keyed.items()], registry())
    got = {k: (fc.result.status, fc.result.category) for k, fc in out.items()}
    assert got == {k: ("identified", fid) for k, (_, fid) in keyed.items()}


@pytest.mark.parametrize("fid", CSV_IDS)
def test_each_csv_category_by_exact_header_in_two_periods(fid):
    for dataset in (SEP, MAY):
        r = classify(read(dataset, fid))
        assert (r.status, r.category, r.method) == ("identified", fid, "csv_exact_header")
        assert r.content_check["nonconforming_rows"] == 0
        assert r.details["canonical_serialisation"] is True


@pytest.mark.parametrize("fid", ["IN-17", "IN-18", "IN-19"])
def test_single_slot_pdfs_identified_by_labels(fid):
    r = classify(read(SEP, fid))
    assert (r.status, r.category, r.method) == ("identified", fid, "pdf_text_pattern")
    assert set(r.details["labels_found"]) >= {l.label for l in registry().get(fid).pdf.labels}


def test_optional_categories_absent_from_a_period_are_not_invented():
    """May 2026 supplies no IN-18/IN-19; nothing in that set is classified as either."""
    out = classify_batch([(str(p), p.read_bytes()) for p, _, _ in files_with_truth(MAY)], registry())
    assert not {fc.result.category for fc in out.values()} & {"IN-18", "IN-19"}


# ------------------------------------------------------------------------------------------- filenames
def test_identical_content_under_different_filenames(tmp_path):
    """The pipeline reaches the same category whatever the file is called, including misleading names."""
    parser = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path))
    data = read(SEP, "IN-09")
    names = ["bank_statement_entries_2026-09.csv", "x.csv", "transactions_2026-09.csv", "IN-11.csv", "report.pdf",
             "noext"]
    cats = {parser.process_bytes(data, n, "2026-09").metadata.evidence_category for n in names}
    assert cats == {"IN-09"}
    pdf = read(SEP, "IN-17")
    assert {parser.process_bytes(pdf, n).metadata.evidence_category
            for n in ["safeguarding_reconciliation_policy_v1.2.pdf", "account_inventory.csv", "a.bin"]} == {"IN-17"}


def test_misleading_filename_does_not_change_category(tmp_path):
    parser = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path))
    r = parser.process_bytes(read(SEP, "IN-03"), "account_inventory.csv", "2026-09")
    assert r.metadata.evidence_category == "IN-03"


# ------------------------------------------------------------------------------------------- CSV header variants
def test_unknown_header():
    r = classify(make_csv(["foo", "bar", "baz"], [["1", "2", "3"]]))
    assert r.status == "unknown" and r.category is None
    assert r.diagnosis["status"] == "UNKNOWN"


def test_missing_header_column_not_accepted():
    h = canonical_header("IN-09")
    r = classify(make_csv([c for c in h if c != "dc_indicator"]))
    assert r.status == "unknown" and r.category is None
    assert r.diagnosis["closest"] == "IN-09" and r.diagnosis["missing"] == ["dc_indicator"]


def test_extra_header_column_not_accepted():
    h = canonical_header("IN-07") + ["comments"]
    r = classify(make_csv(h))
    assert r.status == "unknown" and r.diagnosis["closest"] == "IN-07" and r.diagnosis["extra"] == ["comments"]


def test_reordered_header_not_accepted():
    h = canonical_header("IN-12")
    h[0], h[1] = h[1], h[0]
    r = classify(make_csv(h))
    assert r.status == "unknown" and r.diagnosis["closest"] == "IN-12" and r.diagnosis["misordered"]


def test_incorrect_casing_not_accepted():
    h = [c.upper() for c in canonical_header("IN-01")]
    r = classify(make_csv(h))
    assert r.status == "unknown" and r.diagnosis["closest"] == "IN-01" and r.diagnosis["case_or_spacing"]


def test_header_whitespace_not_accepted():
    h = canonical_header("IN-02")
    h[0] = " " + h[0]
    r = classify(make_csv(h))
    assert r.status == "unknown" and r.diagnosis["closest"] == "IN-02"


def test_duplicate_headers_not_accepted():
    h = canonical_header("IN-13")
    r = classify(make_csv(h + [h[0]]))
    assert r.status == "unknown" and r.diagnosis["duplicate_columns"] == [h[0]]


def test_header_equally_close_to_two_categories_is_ambiguous():
    """The IN-07/IN-08 shared columns plus two IN-08-only columns: overlap 5/9 with IN-07 and 7/11 with IN-08, within the
    tie band, so not even a likely category is named."""
    shared = [c for c in canonical_header("IN-07") if c in canonical_header("IN-08")]
    r = classify(make_csv(shared + ["statement_date", "entry_count"]))
    assert r.status == "ambiguous" and r.category is None
    assert sorted(r.diagnosis["candidates"]) == ["IN-07", "IN-08"]


def test_header_closer_to_one_category_names_it_but_is_not_accepted():
    shared = [c for c in canonical_header("IN-07") if c in canonical_header("IN-08")]
    r = classify(make_csv(shared))
    assert r.status == "unknown" and r.category is None and r.diagnosis["closest"] == "IN-07"


def test_exact_header_with_bom_is_canonical():
    r = classify(b"\xef\xbb\xbf" + read(SEP, "IN-06"))
    assert (r.status, r.category) == ("identified", "IN-06") and r.details["canonical_serialisation"]


def test_exact_header_with_other_delimiter_is_identified_but_flagged():
    data = read(SEP, "IN-08")
    semi = make_csv(canonical_header("IN-08"), rows_of(data), delimiter=";")
    r = classify(semi)
    assert (r.status, r.category) == ("identified", "IN-08")
    assert r.details["canonical_serialisation"] is False and "delimiter ';'" in r.warnings[0]


def test_nonconforming_rows_keep_category_and_are_reported():
    h = canonical_header("IN-10")
    good = rows_of(read(SEP, "IN-10"))[:3]
    bad = list(good[0])
    bad[h.index("amount")] = "1,000.00"
    bad[h.index("dc_indicator")] = "X"
    r = classify(make_csv(h, good + [bad]))
    assert (r.status, r.category) == ("identified", "IN-10")
    assert r.content_check["nonconforming_rows"] == 1
    assert set(r.content_check["by_field"]) == {"amount", "dc_indicator"}
    assert any("break the IN-10 field rules" in w for w in r.warnings)


def test_header_only_files():
    r = classify(make_csv(canonical_header("IN-14")))
    assert (r.status, r.category) == ("identified", "IN-14") and "allowed" in r.warnings[0]
    r = classify(make_csv(canonical_header("IN-09")))
    assert (r.status, r.category) == ("identified", "IN-09") and "NO_RECORDS" in r.warnings[0]


def test_empty_file():
    r = classify(b"")
    assert r.status == "unknown" and r.unsupported == "empty"
    assert classify(b"   \n\n").unsupported == "empty"


def test_malformed_csv_data_row_is_reported():
    """The header is exact (the UC-042 identity), so the category is named; the unterminated quote is reported."""
    data = make_csv(canonical_header("IN-01")) + b'2026-09-01,PER-2026-09,"true,,basis\n'
    r = classify(data)
    assert (r.status, r.category) == ("identified", "IN-01")
    assert any("reading stopped early" in w for w in r.warnings)


def test_malformed_csv_header_is_not_classified():
    data = (b'"' + ",".join(canonical_header("IN-01")).encode() + b"\n2026-09-01,PER-2026-09,true,,x\n")
    r = classify(data)
    assert r.status == "unknown" and r.category is None and r.unsupported == "unsupported"


@pytest.mark.parametrize("data,kind", [
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "unsupported"),
    (b"\xd0\xcf\x11\xe0" + b"\x00" * 64, "unsupported"),
    (bytes(range(256)) * 4, "unsupported"),
    (b"just some prose without any delimiter at all", "unsupported"),
])
def test_unsupported_file_types(data, kind):
    r = classify(data)
    assert r.status == "unknown" and r.unsupported == kind


def test_zip_is_not_classified_in_phase1():
    r = classify(b"PK\x05\x06" + b"\x00" * 18)
    assert r.status == "unknown" and r.unsupported == "zip"


# ------------------------------------------------------------------------------------------- PDFs
def test_scanned_image_only_pdf_is_unsupported(tmp_path):
    r = classify(image_only_pdf())
    assert r.status == "unknown" and r.unsupported == "image_only_pdf" and "OCR is not supported" in r.reason
    res = SmartParser(schemas=registry(), store=EvidenceStore(tmp_path)).process_bytes(image_only_pdf(), "scan.pdf")
    assert res.identification.ocr_required is True
    assert "pdf_image_only" in [i.code.value for i in res.issues]


def test_pdf_without_text_or_images():
    r = classify(blank_pdf())
    assert r.status == "unknown" and r.unsupported == "pdf_no_text"


def test_unreadable_pdf():
    r = classify(b"%PDF-1.4\n%fake\n")
    assert r.status == "unknown" and r.unsupported == "pdf_unreadable"


def test_pdf_with_partial_labels_is_unknown():
    r = classify(text_pdf(["Accountable person: A. Person", "Role: SMF"]))   # IN-18 lacks 'Allocated from'
    assert r.status == "unknown" and r.diagnosis["closest"] == "IN-18"
    assert r.diagnosis["missing_labels"] == ["Allocated from"]


def test_pdf_with_two_complete_label_sets_is_ambiguous():
    lines = ["Accountable person: A. Person", "Role: SMF", "Allocated from: 2026-01-01",
             "Return: REP027", "Period: 2026-08", "Due date: 2026-09-15", "Submitted at: 2026-09-10T10:00:00+01:00",
             "Submission reference: SUB-1"]
    r = classify(text_pdf(lines))
    assert r.status == "ambiguous" and "IN-18" in r.reason and "IN-19" in r.reason


def test_label_must_be_a_line_of_its_own():
    r = classify(text_pdf(["Note that Accountable person: A, Role: B and Allocated from: C appear inline"]))
    assert r.status == "unknown"


# ------------------------------------------------------------------------------------------- GBP / EUR letters
@pytest.mark.parametrize("dataset", [SEP, MAY], ids=["2026-09", "2026-05"])
def test_letters_are_ambiguous_without_an_account_inventory(dataset):
    for fid in ("IN-15", "IN-16"):
        r = classify(read(dataset, fid))
        assert r.status == "ambiguous" and r.category is None and "IN-02" in r.reason


@pytest.mark.parametrize("dataset", [SEP, MAY], ids=["2026-09", "2026-05"])
def test_letters_resolved_through_the_inventory_letter_reference(dataset):
    refs = refs_for(dataset)
    gbp, eur = classify(read(dataset, "IN-15"), refs), classify(read(dataset, "IN-16"), refs)
    assert (gbp.status, gbp.category) == ("identified", "IN-15")
    assert (eur.status, eur.category) == ("identified", "IN-16")
    assert gbp.details["slot_resolution"]["account_id"] == "SGA-GBP-01"
    assert eur.details["slot_resolution"]["account_id"] == "SGA-EUR-01"


def test_letter_slot_follows_the_inventory_not_the_currency_label():
    """UC-042 resolves the slot by the IN-02 letter reference only. If the inventory assigns the GBP letter's reference
    to SGA-EUR-01, the letter is IN-16, although its own text says Currency: GBP."""
    refs = refs_for(SEP)
    swapped = {ref: ("IN-16" if cat == "IN-15" else "IN-15") for ref, cat in refs.items()}
    r = classify(read(SEP, "IN-15"), swapped)
    assert r.category == "IN-16" and r.details["observed_not_used_for_slot"]["Currency"] == "GBP"


def test_letter_reference_not_in_inventory_is_ambiguous():
    r = classify(read(SEP, "IN-15"), {"ACK-SOMETHING-ELSE": "IN-15"})
    assert r.status == "ambiguous" and "does not match" in r.reason


def test_batch_with_two_inventories_does_not_resolve_letters():
    inv = read(SEP, "IN-02")
    other = inv.replace(b"SGA-GBP-01", b"SGA-GBP-09")        # a second, different inventory
    out = classify_batch([("a", inv), ("b", other), ("l", read(SEP, "IN-15"))], registry())
    assert out["l"].result.status == "ambiguous"
    assert any("2 files identify as an account inventory" in w for w in out["l"].result.warnings)


# ------------------------------------------------------------------------------------------- policy versions
def test_policy_versions_identified():
    sep = classify(read(SEP, "IN-17"))
    assert (sep.category, sep.details["policy_version"]) == ("IN-17", "1.2")
    versions = sorted(classify(read(MAY, "IN-17", n)).details["policy_version"] for n in (0, 1))
    assert versions == ["1.1", "1.2"]
    v11 = next(classify(read(MAY, "IN-17", n)) for n in (0, 1) if classify(read(MAY, "IN-17", n)).details["policy_version"] == "1.1")
    assert v11.details["policy_classification"] == "ILLUSTRATIVE_SYNTHETIC"


POLICY_LINES = ["Document version: {v}", "Effective date: {d}", "Safeguarding method: SEGREGATION",
                "Reconciliation method: STANDARD", "Reconciliation point: 17:00 Europe/London",
                "Frequency: Each reconciliation day", "Internal reconciliation basis: Per currency"]


def policy_pdf(version, effective, markings=("SYNTHETIC DOCUMENT - UC-042 POC",)):
    return text_pdf([line.format(v=version, d=effective) for line in POLICY_LINES] + list(markings))


def test_synthetic_policy_with_registered_details_is_recognised():
    r = classify(policy_pdf("1.2", "2026-05-07"))
    assert (r.status, r.category, r.details["policy_version"]) == ("identified", "IN-17", "1.2")


@pytest.mark.parametrize("version,effective,markings,problem", [
    ("9.9", "2026-05-07", ("SYNTHETIC DOCUMENT - UC-042 POC",), "unsupported policy version '9.9'"),
    ("1.2", "2026-06-01", ("SYNTHETIC DOCUMENT - UC-042 POC",), "not the registered 2026-05-07"),
    ("1.2", "2026-05-07", (), "lacks the required marking"),
    ("1.1", "2025-10-01", ("ILLUSTRATIVE SYNTHETIC DOCUMENT",), "lacks the required marking"),
])
def test_unrecognised_policy_is_not_accepted(version, effective, markings, problem):
    r = classify(policy_pdf(version, effective, markings))
    assert r.status == "unknown" and r.category is None
    assert r.diagnosis["status"] == "POLICY_NOT_RECOGNISED" and problem in r.reason


# ------------------------------------------------------------------------------------------- whole corpus
@needs_uc042
def test_all_uc042_datasets_classify_as_declared():
    """Every evidence file of every UC-042 dataset (September sets and January-August history)."""
    from pathlib import Path
    import csv as _csv
    total = 0
    for parent in ("uc042_dataset", "demo_history/datasets", "UC042_JAN_AUG_HISTORICAL_DEMO"):
        for m in sorted((UC042_ROOT / parent).rglob("manifest.csv")):
            ds = m.parent
            if not any((ds / d).is_dir() for d in ("source_data", "supporting_documents")):
                continue
            with open(m, encoding="utf-8", newline="") as f:
                declared = {r["relative_path"]: r["file_id"] for r in _csv.DictReader(f)}
            files = sorted(p for d in ("source_data", "supporting_documents") if (ds / d).is_dir()
                           for p in (ds / d).iterdir() if p.is_file())
            assert {p.relative_to(ds).as_posix() for p in files} == set(declared), ds
            out = classify_batch([(p.relative_to(ds).as_posix(), p.read_bytes()) for p in files], registry())
            for key, fc in out.items():
                assert (fc.result.status, fc.result.category) == ("identified", declared[key]), (ds, key)
            total += len(files)
    assert total == 445
