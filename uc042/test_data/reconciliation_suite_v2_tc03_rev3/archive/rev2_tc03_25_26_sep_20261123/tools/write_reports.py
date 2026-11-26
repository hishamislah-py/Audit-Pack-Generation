"""Write generation_report.md and VALIDATION_REPORT.md from the specs, the generated files and validation/*.json."""
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as contract_mod  # noqa: E402
from scenario_specs import SCENARIOS  # noqa: E402

SUITE = Path(__file__).resolve().parent.parent
C = contract_mod.Contract(contract_mod.load())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def counts(case):
    with open(Path(case) / "manifest.csv", encoding="utf-8", newline="") as f:
        return {m["file_id"]: int(m["record_count"]) for m in csv.DictReader(f) if m["format"] == "CSV"}


def generation_report():
    base = counts(SUITE / "shared_baseline")
    L = ["# UC-042 Reconciliation Test Suite V2: Generation Report (Stage D)", "",
         "**Date:** 23 Nov 2026. **Generator:** `tools/generate_suite.py`, Python 3.11, standard library only.",
         "**Engine:** no UC-042 engine or application code was imported or executed.", "",
         "## 1. Inputs", "",
         f"- Baseline: `shared_baseline/`, a copy of `set_01_clean_baseline`. Manifest SHA-256 `{sha(SUITE / 'shared_baseline' / 'manifest.csv')}`; 19/19 file hashes are verified at every run.",
         f"- Schema contract: `{C.snap['source']}` (SHA-256 `{C.snap['source_sha256']}`). It was read with `ast.literal_eval` and never executed. CONDITIONAL (lambdas) was transcribed. Snapshot: `tools/schema_contract_snapshot.json`.",
         "- Specifications: `tools/scenario_specs.py`, written by hand from the approved `SCENARIO_CATALOGUE.md`, with TC03 revised.", "",
         "## 2. Method and guards", "",
         "- Each scenario = a copy of the baseline + its listed operations, using the `scenarios.py` vocabulary: `delete_record`, `set_field` with the expected old value, `add_record` with exact header columns and a stated position.",
         "- Generation fails if any of these is false:",
         "  - a target record exists, or an added key is new;",
         "  - an old value matches;",
         "  - an added record's columns equal the canonical header;",
         "  - rewriting every baseline CSV with the generator's writer reproduces it byte for byte (so only operated rows change);",
         "  - the TC01 and TC05 corrected files are byte-identical to the baseline.",
         "- PDFs (IN-15 to IN-19) are copied unchanged in every case.",
         "- `manifest.csv` is regenerated per case (SHA-256 and record count) in the baseline's format. `scenario.json` carries `scenario_id` TC01 to TC06.",
         "- Upload ZIPs hold only the 19 canonical files, flat (UC042_ZIP_INPUT_SPECIFICATION section 4), with fixed timestamps (2026-10-02 09:00).", "",
         "## 3. Scenarios generated", "",
         "| Scenario | Ops | Files mutated | Record-count change vs baseline | Correction | Upload ZIP(s) |", "|---|---|---|---|---|---|"]
    for s in SCENARIOS:
        sd = SUITE / s["dir"]
        c = counts(sd / "initial_submission")
        delta = ", ".join(f"{f} {base[f]}→{c[f]}" for f in sorted(c) if c[f] != base[f]) or "none"
        corr = s.get("correction")
        cops = json.loads((sd / "corrections" / "correction_mutations.json").read_text())["operations"] if corr else []
        corr_txt = f"{len(cops)} op(s) on {', '.join(sorted({o['file_id'] for o in cops}))}" if corr else "none"
        zips = "<br>".join(f"`{z.name}` sha256 `{sha(z)[:16]}…`" for z in sorted((sd / "upload").iterdir()))
        L.append(f"| {s['scenario_id']} {s['title']} | {len(s['ops'])} | {', '.join(sorted({o['file_id'] for o in s['ops']}))} | {delta} | {corr_txt} | {zips} |")
    L += ["", "Full per-operation detail, with old and new values, is in each scenario's `MUTATION_RECORD.md` and `mutations.json`, and in `corrections/CORRECTION_NOTE.md` and `correction_mutations.json`.", "",
          "## 4. Changes after Stage C approval", "",
          "- **TC03 revised on the user's instruction.**",
          "  - The 30 Sep / 1 Oct period-end design and its supplementary October extract were dropped. No supplementary evidence mechanism exists in the suite.",
          "  - New design: acquirer settlement `AQ-GBP-20260925` (4,647.75) is posted to the cash book on 25 Sep 14:00 and credited by the bank on 26 Sep 08:00.",
          "  - The firm reports the −4,647.75 difference, claims timing and logs DL-0001.",
          "- **Weekend dependency.** 26 Sep 2026 is a Saturday (IN-01 WEEKEND). To evidence the clearing under the existing rules, the scenario adds a Saturday IN-08 statement (`ST-SGA-GBP-01-20260926-EOD`) and a Saturday IN-07 confirmation (`ST-SGA-GBP-01-20260926-1700`) for SGA-GBP-01. They use existing files and fields only, but the baseline otherwise has no weekend bank records.",
          "  - The engine's `evidence_gap` needs both for the clearing day to count. Without them the predicted status is TIMING_UNVERIFIABLE instead of TIMING_EVIDENCED.",
          "  - Alternative if weekend records are unwanted: use a weekday pair such as 24/25 Sep. **Owner decision.**",
          "- TC01, TC02, TC04, TC05 and TC06 follow the approved specifications without change.", "",
          "## 5. Issues found during generation", "",
          "- **Answer-key defect caught by validation (fixed).** In the first run, the hand-written TC01 FIN key stated the IN-05 `difference_reported` reported value as the ledger figure instead of `0.00` (three findings).",
          "  - The independent validator reported a mismatch. The data was correct; the key text was wrong.",
          "  - The key was corrected in `tools/scenario_specs.py`, the suite regenerated, and validation re-run: PASS.",
          "- No other issue. Every guard in section 2 held.", "",
          "## 6. Not done (by instruction)", "",
          "- No UC-042 engine, application, Smart Parser or Ringfence run. ENGINE-PREDICTED values are unverified.",
          "- No engine or source file, frozen scenario, baseline dataset or answer key was modified. The approved Stage B documents are archived unchanged.",
          "- No future reconciliation capability was implemented.", ""]
    (SUITE / "generation_report.md").write_text("\n".join(L), encoding="utf-8", newline="\n")


def validation_report():
    vr = json.loads((SUITE / "validation" / "validation_results.json").read_text())
    nt = json.loads((SUITE / "validation" / "negative_tests.json").read_text())
    L = ["# UC-042 Reconciliation Test Suite V2: Offline Validation Report (Stage E)", "",
         f"**Overall result: {vr['overall']}.** Date: 23 Nov 2026. Validator: `tools/validate_suite.py`. Negative tests: `tools/negative_tests.py`.", "",
         "> **Scope.** This validates the **generated datasets and answer keys** only. No UC-042 engine, application or AI was executed. Nothing here shows how the engine behaves: every ENGINE-PREDICTED outcome remains unverified.", "",
         "## 1. Independence", "",
         "- The validator imports no engine code.",
         "- The schema contract comes from an `ast` read of the reference `schema.py`. Every reconciliation calculation, matching rule and period rule is a separate implementation written for this suite.",
         "- The FIN answer keys were written by hand from the specification (`tools/scenario_specs.py`) and **not** derived from the generated files. The validator recomputes everything from the files and requires:",
         "  - an **exact** set equality between its findings and the key's `expected_anomalies` (no missing and no extra finding);",
         "  - exact equality of every key figure.",
         "- **Control:** the clean baseline must produce zero structure errors and zero findings.", "",
         "## 2. Checks performed", "",
         "| Group | Checks |", "|---|---|",
         "| Structure | Exact canonical headers; UTF-8, no BOM, LF; row width; mandatory fields; type formats (amount, signed, date, ts with offset, bool, int, ccy, id); 20 enum sets; 11 conditional rules; unique primary keys; empty-file rule |",
         "| Period | September membership per evidence type; permitted 31 Aug boundary rows; IN-04 open during period; IN-14 event reference and not logged before its reconciliation |",
         "| References | Accounts, statements, bank_statement_id, batches, pools, IN-14 recon_ref |",
         "| Recomputation | Bank (IN-07) vs ledger at 17:00 per account and day; requirement (Σ non-negative snapshots + open register) and resource; every IN-05/IN-06 reported value; client roll-forward for every consecutive snapshot pair; statement arithmetic, entry counts, parent consistency and continuity; 17:00 confirmation vs statement; batch arithmetic (TXN, FEE, REFUND, signed NET); line ↔ transaction; card transaction in exactly one line; batch ↔ bank (count, amount, booking lag); own-funds top-ups; cash book ↔ bank by reference (missing, multiple, amount, cross-day timing); **many-to-one claims** (duplicates); bank entries without counterpart; direct loads and redemptions ↔ bank; register matching and allocation deadline; refunds; currency; daily coverage; discrepancy-log coverage of every bank-ledger difference; records on non-reconciliation days |",
         "| Mutations | Row-level diff against the baseline (corrections: against the initial submission) must equal `mutations.json` exactly; files not named in any operation are byte-identical; unchanged rows keep their exact text and order; PDFs identical to the baseline; corrected TC01 and TC05 files byte-identical to the baseline |",
         "| Packaging | `manifest.csv` SHA-256 and record counts; `scenario.json` identity; no `answer_key.json` in case roots; upload ZIP = exactly the 19 canonical names with bytes identical to the case, CRC-clean; ENGINE-PREDICTED JSON consistency (sequential IDs, Σ affected_results = non-passing results, groups and candidates reference existing exceptions, CLEAN ⇔ no non-passing results, label NOT EXECUTED); FUTURE and AI files present and labelled |", "",
         "## 3. Results by case", "",
         "| Case | Status | Structure errors | Findings (= FIN key) | FIN figures checked | Changes verified | Manifest / ZIP / JSON |", "|---|---|---|---|---|---|---|"]
    for r in vr["cases"]:
        fin_ok = not r.get("fin_unexpected_findings") and not r.get("fin_missing_findings") and not r.get("fin_figure_mismatches")
        pk = "OK" if not (r.get("manifest_issues") or r.get("zip_issues") or r.get("json_issues")) else "ISSUES"
        L.append(f"| {r['role']} | **{r['status']}** | {len(r['structure_errors'])} | {len(r['findings'])} ({'exact match' if fin_ok else 'MISMATCH'}) | "
                 f"{r.get('fin_figures_checked', 0)} | {r.get('mutation_changes_verified', '-')} | {pk if 'manifest_issues' in r else '-'} |")
    L += ["", "## 4. Findings recomputed from the generated data (each equals the FIN key exactly)", ""]
    for r in vr["cases"][1:]:
        L.append(f"**{r['role']}**")
        L.append("")
        L += [f"- `{f}`" for f in r["findings"]] or ["- none (consistent dataset)"]
        L.append("")
    L += ["## 5. Negative tests (the validator must reject deliberately broken copies)", "",
          "| Test | Rejected | Detected by | Sample |", "|---|---|---|---|"]
    L += [f"| {t['test']} | {'yes' if t['rejected'] else '**NO**'} | {', '.join(t['detected_by'])} | `{t['sample'][0] if t['sample'] else ''}` |" for t in nt]
    L += ["", "## 6. Financial differences confirmed", "",
          "| Scenario | Confirmed from the data |", "|---|---|",
          "| TC01 | bank − ledger −1,246.80 and resource − requirement +1,246.80 on 28, 29 and 30 Sep; bank entry BE-GBP-0928-L01 claimed by two cash-book rows; reported IN-05/IN-06 values match the bank, not the extract |",
          "| TC02 | TX-0908-00002 3,053.61 vs bank 3,035.61 (+18.00); C0006 8 Sep roll-forward +18.00; 9 Sep reconciles |",
          "| TC03 | 25 Sep 17:00 bank 370,813.71 vs ledger 375,461.46 (−4,647.75, reported and logged); timing pair LE-GBP-0925-0003 / BE-GBP-0926-T01 (25 → 26 Sep); 26 and 28 Sep bank = ledger; batch lag 1 day |",
          "| TC04 | bank − ledger +650.00 on 30 Sep EUR; BE-EUR-0930-U01 has no counterpart; no log entry. Corrected: consistent, requirement and resource 119,205.00 |",
          "| TC05 | C0101 +625.27 and C0104 +222.18 roll-forward gaps; 3 lines reference missing transactions. Corrected: byte-identical to the baseline IN-11 |",
          "| TC06 | A: +90.00 (TX-0917-00002, C0007); B: C0004 −90.00 on 17 Sep and +90.00 on 18 Sep, internal −90.00; C: AQ-EUR-20260922 TXN −45.00 and NET −45.00, line vs transaction |", "",
          "## 7. Unresolved issues and assumptions", "",
          "1. **ENGINE-PREDICTED outcomes are unverified** for all six scenarios. Above all, TC06's predicted over-grouping (G-18) and the predicted exception counts must be confirmed by an engine run.",
          "2. **TC03 weekend records.** 26 Sep is a Saturday, so the scenario adds a Saturday statement and 17:00 confirmation. The validator lists them as intended `NON_RECON_DAY_RECORD` findings. The owner should confirm this is acceptable; the alternative is a weekday pair.",
          "3. **The validator's own rules are an independent re-implementation**, not the engine. Agreement with the engine is not claimed.",
          "4. **Ringfence acceptance** of canonical-name upload ZIPs, and its exception identifiers, are not verified (G-20).",
          "5. **Business-day calculation** uses England and Wales 2026 holidays; none fall in the affected dates.", ""]
    (SUITE / "VALIDATION_REPORT.md").write_text("\n".join(L), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generation_report()
    validation_report()
    print("reports written")
