"""Negative tests for tools/validate_suite.py: each deliberately broken temporary copy must be rejected.

Copies are made under _work/negative_tests/ and deleted afterwards. Generated scenario files are never modified.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_suite as V  # noqa: E402

SUITE = V.SUITE
TMP = SUITE / "_work" / "negative_tests"


def copy(src):
    dst = TMP / src.parent.name
    shutil.copytree(src, dst)
    return dst


def edit(case, fname, old, new):
    p = case / "source_data" / fname
    t = p.read_text(encoding="utf-8")
    assert old in t, (fname, old)
    p.write_text(t.replace(old, new, 1), encoding="utf-8", newline="\n")


def fin(sid):
    d = next(s["dir"] for s in V.SCENARIOS if s["scenario_id"] == sid)
    return json.loads((SUITE / d / "expected_results" / "financial_answer_key.json").read_text())


TESTS = [
    ("unrelated amount change (TC02: bank entry BE-GBP-0901-L01)", "TC02_AMOUNT_MISMATCH", "TC02",
     lambda c: edit(c, "bank_statement_entries_2026-09.csv", ",2926.33,C,", ",2926.34,C,"), ("fin_unexpected_findings",)),
    ("header renamed (TC02: IN-11 amount -> amt)", "TC02_AMOUNT_MISMATCH", "TC02",
     lambda c: edit(c, "transactions_2026-09.csv", "executed_ts,amount,direction", "executed_ts,amt,direction"), ("structure_errors",)),
    ("invalid enum (TC04: dc_indicator X)", "TC04_UNMATCHED_TRANSACTION", "TC04",
     lambda c: edit(c, "bank_statement_entries_2026-09.csv", ",650.00,C,EUR,", ",650.00,X,EUR,"), ("structure_errors",)),
    ("Saturday 17:00 confirmation removed (TC03)", "TC03_TIMING_DIFFERENCE", "TC03",
     lambda c: edit(c, "bank_balance_confirmations_2026-09.csv",
                    "ST-SGA-GBP-01-20260926-1700,SGA-GBP-01,2026-09-26T17:00:00+01:00,GBP,375461.46,C,BC/SGA-GBP-01/20260926\n", ""),
     ("fin_missing_findings", "fin_figure_mismatches")),
    ("duplicate posting removed (TC01 initial no longer shows the duplicate)", "TC01_DUPLICATE_TRANSACTION", "TC01",
     lambda c: edit(c, "sga_cashbook_entries_2026-09.csv",
                    "LE-GBP-0928-0007,SGA-GBP-01,2026-09-28T09:25:00+01:00,BANK_LOAD,1246.80,D,GBP,E2E-GBP-0928-L01\n", ""),
     ("fin_missing_findings",)),
    ("amount format 1,390.07 (TC06)", "TC06_INDEPENDENT_CAUSES", "TC06",
     lambda c: edit(c, "transactions_2026-09.csv", ",1480.07,CR,", ',"1,480.07",CR,'), ("structure_errors",)),
]


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    results = []
    for name, d, sid, mutate, must in TESTS:
        case = copy(SUITE / d / "initial_submission")
        mutate(case)
        r, _ = V.validate_case(case, fin(sid))
        caught = [k for k in must if r.get(k)]
        results.append({"test": name, "rejected": bool(caught), "detected_by": caught,
                        "sample": next((r[k][:2] for k in must if r.get(k)), [])})
        shutil.rmtree(case)
    shutil.rmtree(TMP)
    for x in results:
        print(("REJECTED (good)" if x["rejected"] else "NOT DETECTED  "), x["test"], x["detected_by"], x["sample"])
    (SUITE / "validation" / "negative_tests.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    sys.exit(0 if all(x["rejected"] for x in results) else 1)


if __name__ == "__main__":
    main()
