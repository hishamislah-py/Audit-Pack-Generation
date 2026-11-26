"""Build the Phase 2 controlled-variation corpus (reproducible; byte-identical on every run).

Source: the canonical September 2026 CSVs in tests/fixtures/uc042_canonical/PER-2026-09_set_01_clean_baseline/ - which
are themselves byte-for-byte copies of UC-042's set_01_clean_baseline. The originals are only read; every variation is
a new file. Each case is listed in manifest.csv / manifest.json with its source file and hash, the transformation, the
expected outcome and the rule set it is expected under.

    py -3.11 tools/build_variation_corpus.py [--out corpus/phase2_variations]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SOURCE = HERE / "tests" / "fixtures" / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"
PROD, TEST = "production", "test_approved_aliases"


def read_source():
    with open(SOURCE / "manifest.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["format"] == "CSV"]
    return {r["file_id"]: SOURCE / r["relative_path"] for r in rows}


def table(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))


def dump(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode("utf-8")


def cols(rows, order):
    return [[r[i] for i in order] for r in rows]


def title(name: str) -> str:
    return " ".join(w.upper() if w == "id" else w.capitalize() for w in name.split("_"))


def build(out: Path) -> list[dict]:
    sources = read_source()
    out.mkdir(parents=True, exist_ok=True)
    cases = []

    def add(case_id, cat, kind, data, transformation, expected, expected_category, rules=PROD, filename=None,
            source_cat=None, note=""):
        name = f"{case_id}.csv"
        (out / name).write_bytes(data)
        src = sources[source_cat or cat]
        cases.append({"case_id": case_id, "category": cat, "case_type": kind, "file": name,
                      "upload_filename": filename or name, "source_file": src.relative_to(HERE).as_posix(),
                      "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                      "sha256": hashlib.sha256(data).hexdigest(), "transformation": transformation,
                      "rules": rules, "expected": expected, "expected_category": expected_category or "", "note": note})

    for cat, path in sorted(sources.items()):
        rows = table(path)
        h, body = rows[0], rows[1:]
        n = len(h)
        pk = h[0]
        add(f"{cat}_01_canonical", cat, "canonical", path.read_bytes(), "unchanged copy", "accept", cat)
        add(f"{cat}_02_renamed_file", cat, "renamed_file", path.read_bytes(), "unchanged content, misleading upload name",
            "accept", cat, filename=f"renamed_{cat.replace('-', '')}_export.txt")
        add(f"{cat}_03_reordered", cat, "reordered", dump(cols(rows, list(reversed(range(n))))),
            "all columns in reverse order (data moved with its column)", "accept", cat)
        add(f"{cat}_04_whitespace", cat, "whitespace", dump([[f"  {c} " for c in h]] + body),
            "every header padded with surrounding spaces", "accept", cat)
        add(f"{cat}_05_case", cat, "case", dump([[c.upper() for c in h]] + body), "every header upper-cased",
            "accept", cat)
        alias_rows = dump([[title(pk)] + h[1:]] + body)
        add(f"{cat}_06_alias_approved", cat, "approved_alias", alias_rows,
            f"key column '{pk}' renamed to its alias '{title(pk)}' (approved in the TEST rules only)", "accept", cat,
            rules=TEST, note="test-fixture approval, not a business approval")
        add(f"{cat}_07_alias_proposed_only", cat, "proposed_alias", alias_rows,
            f"key column '{pk}' renamed to '{title(pk)}' (proposal AP-{cat}-PK-TITLE, status proposed)", "reject", None,
            note="same bytes as case 06, evaluated under the production rules")
        add(f"{cat}_08_missing_column", cat, "missing_column", dump(cols(rows, list(range(n - 1)))),
            f"last column '{h[-1]}' removed", "reject", None)
        add(f"{cat}_09_extra_column", cat, "extra_column", dump([h + ["analyst_comment"]] + [r + ["x"] for r in body]),
            "extra column 'analyst_comment' appended", "reject", None, note="reported as unexpected, never dropped")
        add(f"{cat}_10_duplicate_mapping", cat, "duplicate_mapping",
            dump([h + [pk.upper()]] + [r + [r[0]] for r in body]),
            f"second column '{pk.upper()}' that maps to '{pk}' again", "reject", None)
        add(f"{cat}_11_unknown_header", cat, "unknown_header", dump([[f"col_{i + 1}" for i in range(n)]] + body),
            "every header replaced by col_1..col_n", "reject", None)

    # ambiguous alias: 'Reference' is proposed for two IN-09 fields
    rows = table(sources["IN-09"])
    h = rows[0]
    i = h.index("bank_reference")
    add("IN-09_12_ambiguous_alias", "IN-09", "ambiguous_alias", dump([h[:i] + ["Reference"] + h[i + 1:]] + rows[1:]),
        "bank_reference renamed 'Reference' (proposed for bank_reference AND end_to_end_ref)", "reject", None)

    # hard negatives between confusable categories
    r10 = table(sources["IN-10"])
    h10 = ["bank_entry_id" if c == "ledger_entry_id" else "booking_ts" if c == "posted_ts" else c for c in r10[0]]
    add("HN_01_IN10_dressed_as_IN09", "IN-10", "hard_negative", dump([h10] + r10[1:]),
        "IN-10 cash book with ledger_entry_id/posted_ts renamed to the IN-09 names bank_entry_id/booking_ts",
        "reject", None, note="must be neither IN-09 nor IN-10")
    add("HN_02_IN09_named_as_cashbook", "IN-09", "hard_negative", sources["IN-09"].read_bytes(),
        "IN-09 content uploaded as sga_cashbook_entries_2026-09.csv", "accept", "IN-09",
        filename="sga_cashbook_entries_2026-09.csv", note="filename must not decide")
    r07 = table(sources["IN-07"])
    add("HN_03_IN07_plus_IN08_columns", "IN-07", "hard_negative",
        dump([r07[0] + ["statement_date", "entry_count"]] + [r + ["", ""] for r in r07[1:]]),
        "IN-07 with the IN-08-only columns statement_date and entry_count added", "reject", None,
        note="must be neither IN-07 (extra columns) nor IN-08 (missing columns)")
    r08 = table(sources["IN-08"])
    add("HN_04_IN08_reordered", "IN-08", "hard_negative", dump(cols(r08, list(reversed(range(len(r08[0])))))),
        "IN-08 reordered (shares statement_id/account_id/as_at_ts/currency with IN-07)", "accept", "IN-08")
    add("HN_05_IN06_named_as_internal", "IN-06", "hard_negative", sources["IN-06"].read_bytes(),
        "IN-06 content uploaded as internal_recon_records_2026-09.csv", "accept", "IN-06",
        filename="internal_recon_records_2026-09.csv", note="filename must not decide")
    r05, r06h = table(sources["IN-05"]), set(table(sources["IN-06"])[0])
    keep = [i for i, c in enumerate(r05[0]) if c in r06h]
    add("HN_06_IN05_reduced_to_IN06_shared", "IN-05", "hard_negative", dump(cols(r05, keep)),
        f"IN-05 reduced to the columns it shares with IN-06 ({', '.join(r05[0][i] for i in keep)})", "reject", None,
        note="must be neither IN-05 nor IN-06")

    fields = list(cases[0])
    with open(out / "manifest.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(cases)
    (out / "manifest.json").write_bytes((json.dumps(
        {"corpus": "UC-042 Smart Parser Phase 2 controlled-variation corpus",
         "source": SOURCE.relative_to(HERE).as_posix(),
         "rules": {PROD: "smartparser/mapping/rules/approved_aliases.json (no aliases approved)",
                   TEST: "tests/fixtures/mapping_rules/test_approved_aliases.json (PK-TITLE aliases, TEST approval)"},
         "expected": {"accept": "identified as expected_category", "reject": "not identified (unknown/ambiguous)"},
         "cases": cases}, indent=1) + "\n").encode("utf-8"))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "corpus" / "phase2_variations"))
    a = ap.parse_args()
    cases = build(Path(a.out))
    print(f"{len(cases)} cases written to {a.out}")


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
