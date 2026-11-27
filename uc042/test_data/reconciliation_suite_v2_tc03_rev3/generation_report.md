# UC-042 Reconciliation Test Suite V2: Generation Report (Stage D)

**Date:** 23 Nov 2026. **Generator:** `tools/generate_suite.py`, Python 3.11, standard library only.
**Engine:** no UC-042 engine or application code was imported or executed.

## 1. Inputs

- Baseline: `shared_baseline/`, a copy of `set_01_clean_baseline`. Manifest SHA-256 `0360b4055aa6812f063b411c7ceacdb2f4f153df73fd76c2acc7da3df565b69e`; 19/19 file hashes are verified at every run.
- Schema contract: `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib\schema.py` (SHA-256 `03f76843a27d0de1da7a5f4602e0e6c9071e4f396e8786f5e8000a2b67b9690d`). It was read with `ast.literal_eval` and never executed. CONDITIONAL (lambdas) was transcribed. Snapshot: `tools/schema_contract_snapshot.json`.
- Specifications: `tools/scenario_specs.py`, written by hand from the approved `SCENARIO_CATALOGUE.md`, with TC03 at revision 3 (24/25 Sep).

## 2. Method and guards

- Each scenario = a copy of the baseline + its listed operations, using the `scenarios.py` vocabulary: `delete_record`, `set_field` with the expected old value, `add_record` with exact header columns and a stated position.
- Generation fails if any of these is false:
  - a target record exists, or an added key is new;
  - an old value matches;
  - an added record's columns equal the canonical header;
  - rewriting every baseline CSV with the generator's writer reproduces it byte for byte (so only operated rows change);
  - the TC01 and TC05 corrected files are byte-identical to the baseline.
- PDFs (IN-15 to IN-19) are copied unchanged in every case.
- `manifest.csv` is regenerated per case (SHA-256 and record count) in the baseline's format. `scenario.json` carries `scenario_id` TC01 to TC06.
- Upload ZIPs hold only the 19 canonical files, flat (UC042_ZIP_INPUT_SPECIFICATION section 4), with fixed timestamps (2026-10-02 09:00).

## 3. Scenarios generated

| Scenario | Ops | Files mutated | Record-count change vs baseline | Correction | Upload ZIP(s) |
|---|---|---|---|---|---|
| TC01 Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80) | 1 | IN-10 | IN-10 224→225 | 1 op(s) on IN-10 | `TC01_corrected_evidence_upload.zip` sha256 `47e89ef23e6cfa6d…`<br>`TC01_initial_evidence_upload.zip` sha256 `9d3ea22dbac6d38e…` |
| TC02 Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02 | 1 | IN-11 | none | none | `TC02_initial_evidence_upload.zip` sha256 `bafcffad1672aa22…` |
| TC03 Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep | 11 | IN-06, IN-07, IN-08, IN-09, IN-14 | IN-14 0→1 | none | `TC03_initial_evidence_upload.zip` sha256 `93c4a11f7c3bbf5a…` |
| TC04 Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart | 6 | IN-06, IN-07, IN-08, IN-09 | IN-09 266→267 | 7 op(s) on IN-04, IN-05, IN-06, IN-10 | `TC04_corrected_evidence_upload.zip` sha256 `b178619684fed3f6…`<br>`TC04_initial_evidence_upload.zip` sha256 `e69043a48db448a0…` |
| TC05 Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export | 3 | IN-11 | IN-11 422→419 | 3 op(s) on IN-11 | `TC05_corrected_evidence_upload.zip` sha256 `47e89ef23e6cfa6d…`<br>`TC05_initial_evidence_upload.zip` sha256 `8d448174ecf39724…` |
| TC06 Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00 | 5 | IN-03, IN-05, IN-11, IN-13 | none | none | `TC06_initial_evidence_upload.zip` sha256 `169020dc23857b99…` |

Full per-operation detail, with old and new values, is in each scenario's `MUTATION_RECORD.md` and `mutations.json`, and in `corrections/CORRECTION_NOTE.md` and `correction_mutations.json`.

## 4. Changes after Stage C approval

TC03 was revised twice on the user's instruction:

| Revision | Design | Kept in |
|---|---|---|
| 1 | 30 Sep / 1 Oct, with a supplementary October extract (approved at Stage C) | `archive/stage_b_approved_20261123/`; never generated |
| 2 | `AQ-GBP-20260925` (4,647.75) posted Fri 25 Sep, credited Sat 26 Sep; needed a Saturday IN-08 statement and IN-07 confirmation | `archive/rev2_tc03_25_26_sep_20261123/` (dataset, ZIPs, reports, tools) |
| **3 (current)** | `AQ-GBP-20260924` (**5,495.05**) posted Thu 24 Sep 14:00, credited Fri 25 Sep 08:00 (next business day) | this suite |

- **Revision 3, amount.** The user asked to keep 4,647.75, but that is the net of the 25 Sep batch, whose card loads were made on 25 Sep. Given the choice, the user picked the existing 24 Sep batch (5,495.05). That keeps every record consistent without re-dating or fabricating amounts.
- **Revision 3, weekend records.** None. The Saturday records of revision 2 are gone.
- **Revision 3, scope.** Only TC03 was regenerated (`generate_suite.py --only TC03`). A hash comparison against a snapshot taken beforehand shows `shared_baseline/` and TC01, TC02, TC04, TC05 and TC06 byte-identical. Record-level before/after: `TC03_REVISION_3_CHANGE_RECORD.md`.
- TC01, TC02, TC04, TC05 and TC06 follow the approved specifications without change.

## 5. Issues found during generation

- **Answer-key defect caught by validation (fixed).** In the first run, the hand-written TC01 FIN key stated the IN-05 `difference_reported` reported value as the ledger figure instead of `0.00` (three findings).
  - The independent validator reported a mismatch. The data was correct; the key text was wrong.
  - The key was corrected in `tools/scenario_specs.py`, the suite regenerated, and validation re-run: PASS.
- No other issue. Every guard in section 2 held.

## 6. Not done (by instruction)

- No UC-042 engine, application, Smart Parser or Ringfence run. ENGINE-PREDICTED values are unverified.
- No engine or source file, frozen scenario, baseline dataset or answer key was modified. The approved Stage B documents are archived unchanged.
- No future reconciliation capability was implemented.
