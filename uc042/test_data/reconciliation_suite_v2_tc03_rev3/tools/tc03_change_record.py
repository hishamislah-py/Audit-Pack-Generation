"""Write TC03_REVISION_3_CHANGE_RECORD.md: record-level before/after between TC03 revision 2 (archived) and revision 3 (current)."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_suite as V  # noqa: E402

SUITE = V.SUITE
OLD = SUITE / "archive" / "rev2_tc03_25_26_sep_20261123" / "TC03_TIMING_DIFFERENCE"
NEW = SUITE / "TC03_TIMING_DIFFERENCE"
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    _, old_raw, _ = V.load(OLD / "initial_submission")
    _, new_raw, _ = V.load(NEW / "initial_submission")
    _, base_raw, _ = V.load(SUITE / "shared_baseline")
    changes, issues = V.diff_cases(old_raw, new_raw)
    old_res, _ = V.validate_case(OLD / "initial_submission")
    new_res, _ = V.validate_case(NEW / "initial_submission")
    old_p = json.loads((OLD / "expected_results" / "engine_predicted_initial.json").read_text())
    new_p = json.loads((NEW / "expected_results" / "engine_predicted_initial.json").read_text())
    L = ["# TC03 revision 3: change record (25/26 Sep → 24/25 Sep)", "",
         "**Date:** 23 Nov 2026. This revision was decided by the user.",
         "",
         "**Old version.** Revision 2 is preserved unchanged in `archive/rev2_tc03_25_26_sep_20261123/`: the dataset, ZIPs, reports and tools.",
         "",
         "**Scope.** Only TC03 was regenerated (`generate_suite.py --only TC03`). A hash comparison against a snapshot taken beforehand shows `shared_baseline/` and TC01, TC02, TC04, TC05 and TC06 byte-identical.", "",
         "## Decision", "",
         "| Item | Revision 2 | Revision 3 |", "|---|---|---|",
         "| Item | AQ-GBP-20260925 | AQ-GBP-20260924 |",
         "| Recorded | Fri 25 Sep 14:00 | Thu 24 Sep 14:00 |",
         "| Bank credit | Sat 26 Sep 08:00 | Fri 25 Sep 08:00 (next business day) |",
         "| Amount | 4,647.75 | **5,495.05** |",
         "| Weekend records | 3 (IN-07, IN-08, IN-09 on 26 Sep) | none |", "",
         "The amount changed because 4,647.75 is the net of the 25 Sep batch, whose card loads were made on 25 Sep. The user chose the 24 Sep batch, which keeps every record consistent, over re-dating or rewriting a batch.", "",
         "## File-level comparison (initial submission)", "", "| File | Revision 2 SHA-256 | Revision 3 SHA-256 | Baseline? |", "|---|---|---|---|"]
    for fid in V.C.csv:
        o, n = hashlib.sha256(old_raw[fid]).hexdigest(), hashlib.sha256(new_raw[fid]).hexdigest()
        if o != n or n != hashlib.sha256(base_raw[fid]).hexdigest():
            L.append(f"| {fid} `{V.C.filename(fid)}` | `{o[:16]}` | `{n[:16]}` | {'identical' if new_raw[fid] == base_raw[fid] else 'mutated'} |")
    L += ["", "Files not listed are byte-identical to the baseline in both revisions.", "",
          "## Record-level before/after (revision 2 → revision 3)", "", "| File | Record | Field | Revision 2 | Revision 3 |", "|---|---|---|---|---|"]
    for c in sorted(changes, key=lambda x: (x[0], x[1], str(x[2]))):
        if c[2] == "DELETED":
            L.append(f"| {c[0]} | `{c[1]}` | (record) | present | **removed** |")
        elif c[2] == "ADDED":
            L.append(f"| {c[0]} | `{c[1]}` | (record) | absent | **added** after `{c[3]}`: {', '.join(c[4][1:])} |")
        else:
            L.append(f"| {c[0]} | `{c[1]}` | {c[2]} | {c[3]} | {c[4]} |")
    if issues:
        L += ["", "Diff issues: " + "; ".join(issues)]
    L += ["", "**Revision-2 records restored to the baseline:**",
          "",
          "- the 25 Sep acquirer entry BE-GBP-0925-AQ1;",
          "- the 25 Sep statement and confirmation balances;",
          "- ERL-SGA-GBP-01-20260925.",
          "",
          "**Removed outright:** the Saturday statement, the Saturday confirmation and the Saturday clearing entry.", "",
          "## Independent validator findings", "", "| Revision 2 (7) | Revision 3 |", "|---|---|"]
    o, n = sorted(old_res["findings"]), sorted(new_res["findings"])
    for i in range(max(len(o), len(n))):
        L.append(f"| {('`' + o[i] + '`') if i < len(o) else ''} | {('`' + n[i] + '`') if i < len(n) else ''} |")
    sat = [f for f in n if "NON_RECON_DAY" in f or "2026-09-26" in f]
    L += ["", f"**Saturday-related findings in revision 3:** {len(sat)} ({'none' if not sat else sat}).",
          f"**Structure errors in revision 3:** {len(new_res['structure_errors'])}.", "",
          "## ENGINE-PREDICTED (source reading only; not executed)", "",
          "| | Revision 2 | Revision 3 |", "|---|---|---|",
          f"| Non-passing | {old_p['non_passing_results']} | {new_p['non_passing_results']} |",
          f"| Exceptions | {[x['root_cause'] for x in old_p['exceptions']]} | {[x['root_cause'] for x in new_p['exceptions']]} |",
          f"| Evidence status | {old_p['evidence_statuses']} | {new_p['evidence_statuses']} |",
          f"| Case status | {old_p['expected_case_status']} | {new_p['expected_case_status']} |", "",
          "## Upload ZIP", "",
          f"- Revision 2 `TC03_initial_evidence_upload.zip`: `{sha(OLD / 'upload' / 'TC03_initial_evidence_upload.zip')}`",
          f"- Revision 3 `TC03_initial_evidence_upload.zip`: `{sha(NEW / 'upload' / 'TC03_initial_evidence_upload.zip')}`", "",
          "**Correction:** TC03 has no correction dataset in either revision, so there is nothing further to keep consistent.", ""]
    (SUITE / "TC03_REVISION_3_CHANGE_RECORD.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
    print(f"{len(changes)} record changes; revision 3 findings {len(n)}; Saturday findings {len(sat)}")


if __name__ == "__main__":
    main()
