# UC-042 Reconciliation Test Suite V2: Stage D and E combined report (TC03 revision 3)

Combines the TC03 revision-3 change record, the generation report, the validation report and the scenario catalogue (23 Nov 2026). Offline validation: PASS. Nothing has been executed by the UC-042 engine or application. The previous combined report is archived in archive/rev2_tc03_25_26_sep_20261123/.

---

## TC03 revision 3: change record (25/26 Sep → 24/25 Sep)

**Date:** 23 Nov 2026. This revision was decided by the user.

**Old version.** Revision 2 is preserved unchanged in `archive/rev2_tc03_25_26_sep_20261123/`: the dataset, ZIPs, reports and tools.

**Scope.** Only TC03 was regenerated (`generate_suite.py --only TC03`). A hash comparison against a snapshot taken beforehand shows `shared_baseline/` and TC01, TC02, TC04, TC05 and TC06 byte-identical.

### Decision

| Item | Revision 2 | Revision 3 |
|---|---|---|
| Item | AQ-GBP-20260925 | AQ-GBP-20260924 |
| Recorded | Fri 25 Sep 14:00 | Thu 24 Sep 14:00 |
| Bank credit | Sat 26 Sep 08:00 | Fri 25 Sep 08:00 (next business day) |
| Amount | 4,647.75 | **5,495.05** |
| Weekend records | 3 (IN-07, IN-08, IN-09 on 26 Sep) | none |

The amount changed because 4,647.75 is the net of the 25 Sep batch, whose card loads were made on 25 Sep. The user chose the 24 Sep batch, which keeps every record consistent, over re-dating or rewriting a batch.

### File-level comparison (initial submission)

| File | Revision 2 SHA-256 | Revision 3 SHA-256 | Baseline? |
|---|---|---|---|
| IN-06 `external_recon_records_2026-09.csv` | `f9816157b6856281` | `224885675830cf1b` | mutated |
| IN-07 `bank_balance_confirmations_2026-09.csv` | `6ed5b87da2a81e62` | `9bdef964d6ee6d36` | mutated |
| IN-08 `bank_statements_eod_2026-09.csv` | `c76d26add88a7dd3` | `87ca9cf00bf13f60` | mutated |
| IN-09 `bank_statement_entries_2026-09.csv` | `c9ec654b681625f8` | `86b4bd9af248b753` | mutated |
| IN-14 `discrepancy_log_2026-09.csv` | `13bfa63e575e58c9` | `51087db5e783a4ac` | mutated |

Files not listed are byte-identical to the baseline in both revisions.

### Record-level before/after (revision 2 → revision 3)

| File | Record | Field | Revision 2 | Revision 3 |
|---|---|---|---|---|
| IN-06 | `ERL-SGA-GBP-01-20260924` | bank_balance_reported | 370603.29 | 365108.24 |
| IN-06 | `ERL-SGA-GBP-01-20260924` | difference_reported | 0.00 | -5495.05 |
| IN-06 | `ERL-SGA-GBP-01-20260924` | timing_difference_claimed | false | true |
| IN-06 | `ERL-SGA-GBP-01-20260925` | bank_balance_reported | 370813.71 | 375461.46 |
| IN-06 | `ERL-SGA-GBP-01-20260925` | difference_reported | -4647.75 | 0.00 |
| IN-06 | `ERL-SGA-GBP-01-20260925` | timing_difference_claimed | true | false |
| IN-07 | `ST-SGA-GBP-01-20260924-1700` | balance_amount | 370603.29 | 365108.24 |
| IN-07 | `ST-SGA-GBP-01-20260925-1700` | balance_amount | 370813.71 | 375461.46 |
| IN-07 | `ST-SGA-GBP-01-20260926-1700` | (record) | present | **removed** |
| IN-08 | `ST-SGA-GBP-01-20260924-EOD` | closing_balance_amount | 370603.29 | 365108.24 |
| IN-08 | `ST-SGA-GBP-01-20260924-EOD` | entry_count | 6 | 5 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | closing_balance_amount | 370813.71 | 375461.46 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | entry_count | 4 | 6 |
| IN-08 | `ST-SGA-GBP-01-20260925-EOD` | opening_balance_amount | 370603.29 | 365108.24 |
| IN-08 | `ST-SGA-GBP-01-20260926-EOD` | (record) | present | **removed** |
| IN-09 | `BE-GBP-0924-AQ1` | (record) | present | **removed** |
| IN-09 | `BE-GBP-0925-AQ1` | (record) | absent | **added** after `BE-GBP-0925-L02`: ST-SGA-GBP-01-20260925-EOD, SGA-GBP-01, 2026-09-25, 2026-09-25T14:00:00+01:00, 2026-09-25, 4647.75, C, GBP, AQ-GBP-20260925, , Synthetic Acquirer Ltd, CARD LOAD SETTLEMENT AQ-GBP-20260925 |
| IN-09 | `BE-GBP-0925-T01` | (record) | absent | **added** after `BE-OWN-EUR-0924-TU1`: ST-SGA-GBP-01-20260925-EOD, SGA-GBP-01, 2026-09-25, 2026-09-25T08:00:00+01:00, 2026-09-25, 5495.05, C, GBP, AQ-GBP-20260924, , Synthetic Acquirer Ltd, CARD LOAD SETTLEMENT AQ-GBP-20260924 |
| IN-09 | `BE-GBP-0926-T01` | (record) | present | **removed** |
| IN-14 | `DL-0001` | amount | -4647.75 | -5495.05 |
| IN-14 | `DL-0001` | cause_evidence_ref | BE-GBP-0926-T01 | BE-GBP-0925-T01 |
| IN-14 | `DL-0001` | description | Acquirer settlement AQ-GBP-20260925 not credited by the bank by 17:00; expected next banking day | Acquirer settlement AQ-GBP-20260924 not credited by the bank by 17:00; expected next business day |
| IN-14 | `DL-0001` | logged_ts | 2026-09-25T18:05:00+01:00 | 2026-09-24T18:05:00+01:00 |
| IN-14 | `DL-0001` | recon_ref | ERL-SGA-GBP-01-20260925 | ERL-SGA-GBP-01-20260924 |
| IN-14 | `DL-0001` | resolved_ts | 2026-09-28T09:00:00+01:00 | 2026-09-25T09:00:00+01:00 |

**Revision-2 records restored to the baseline:**

- the 25 Sep acquirer entry BE-GBP-0925-AQ1;
- the 25 Sep statement and confirmation balances;
- ERL-SGA-GBP-01-20260925.

**Removed outright:** the Saturday statement, the Saturday confirmation and the Saturday clearing entry.

### Independent validator findings

| Revision 2 (7) | Revision 3 |
|---|---|
| `BATCH_LAG AQ-GBP-20260925 settlement=2026-09-25 booked=2026-09-26` | `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25` |
| `BL_DIFF 2026-09-25 SGA-GBP-01 -4647.75` | `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05` |
| `BL_DIFF_LOGGED 2026-09-25 SGA-GBP-01 DL-0001` | `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001` |
| `NON_RECON_DAY_RECORD IN-07 ST-SGA-GBP-01-20260926-1700 2026-09-26` | `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05` |
| `NON_RECON_DAY_RECORD IN-08 ST-SGA-GBP-01-20260926-EOD 2026-09-26` |  |
| `NON_RECON_DAY_RECORD IN-09 BE-GBP-0926-T01 2026-09-26` |  |
| `TIMING LE-GBP-0925-0003/BE-GBP-0926-T01 ref=AQ-GBP-20260925 recorded=2026-09-25 bank=2026-09-26 amount=4647.75` |  |

**Saturday-related findings in revision 3:** 0 (none).
**Structure errors in revision 3:** 0.

### ENGINE-PREDICTED (source reading only; not executed)

| | Revision 2 | Revision 3 |
|---|---|---|
| Non-passing | [['C08-DIFFERENCE', '2026-09-25/SGA-GBP-01', 'FAIL']] | [['C08-DIFFERENCE', '2026-09-24/SGA-GBP-01', 'FAIL']] |
| Exceptions | ['BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-25|-4647.75'] | ['BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-24|-5495.05'] |
| Evidence status | {'EXC-TC03-01': 'TIMING_EVIDENCED'} | {'EXC-TC03-01': 'TIMING_EVIDENCED'} |
| Case status | EXCEPTIONS_OPEN | EXCEPTIONS_OPEN |

### Upload ZIP

- Revision 2 `TC03_initial_evidence_upload.zip`: `fbb372cc0c527fa33aa39901ed5837974ea08cc6550a281481e29979f0f1b029`
- Revision 3 `TC03_initial_evidence_upload.zip`: `93c4a11f7c3bbf5aafcf4ac1586142673c0a5e2c07ac92955aa751877d661146`

**Correction:** TC03 has no correction dataset in either revision, so there is nothing further to keep consistent.

---

## UC-042 Reconciliation Test Suite V2: Generation Report (Stage D)

**Date:** 23 Nov 2026. **Generator:** `tools/generate_suite.py`, Python 3.11, standard library only.
**Engine:** no UC-042 engine or application code was imported or executed.

### 1. Inputs

- Baseline: `shared_baseline/`, a copy of `set_01_clean_baseline`. Manifest SHA-256 `0360b4055aa6812f063b411c7ceacdb2f4f153df73fd76c2acc7da3df565b69e`; 19/19 file hashes are verified at every run.
- Schema contract: `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib\schema.py` (SHA-256 `03f76843a27d0de1da7a5f4602e0e6c9071e4f396e8786f5e8000a2b67b9690d`). It was read with `ast.literal_eval` and never executed. CONDITIONAL (lambdas) was transcribed. Snapshot: `tools/schema_contract_snapshot.json`.
- Specifications: `tools/scenario_specs.py`, written by hand from the approved `SCENARIO_CATALOGUE.md`, with TC03 at revision 3 (24/25 Sep).

### 2. Method and guards

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

### 3. Scenarios generated

| Scenario | Ops | Files mutated | Record-count change vs baseline | Correction | Upload ZIP(s) |
|---|---|---|---|---|---|
| TC01 Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80) | 1 | IN-10 | IN-10 224→225 | 1 op(s) on IN-10 | `TC01_corrected_evidence_upload.zip` sha256 `47e89ef23e6cfa6d…`<br>`TC01_initial_evidence_upload.zip` sha256 `9d3ea22dbac6d38e…` |
| TC02 Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02 | 1 | IN-11 | none | none | `TC02_initial_evidence_upload.zip` sha256 `bafcffad1672aa22…` |
| TC03 Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep | 11 | IN-06, IN-07, IN-08, IN-09, IN-14 | IN-14 0→1 | none | `TC03_initial_evidence_upload.zip` sha256 `93c4a11f7c3bbf5a…` |
| TC04 Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart | 6 | IN-06, IN-07, IN-08, IN-09 | IN-09 266→267 | 7 op(s) on IN-04, IN-05, IN-06, IN-10 | `TC04_corrected_evidence_upload.zip` sha256 `b178619684fed3f6…`<br>`TC04_initial_evidence_upload.zip` sha256 `e69043a48db448a0…` |
| TC05 Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export | 3 | IN-11 | IN-11 422→419 | 3 op(s) on IN-11 | `TC05_corrected_evidence_upload.zip` sha256 `47e89ef23e6cfa6d…`<br>`TC05_initial_evidence_upload.zip` sha256 `8d448174ecf39724…` |
| TC06 Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00 | 5 | IN-03, IN-05, IN-11, IN-13 | none | none | `TC06_initial_evidence_upload.zip` sha256 `169020dc23857b99…` |

Full per-operation detail, with old and new values, is in each scenario's `MUTATION_RECORD.md` and `mutations.json`, and in `corrections/CORRECTION_NOTE.md` and `correction_mutations.json`.

### 4. Changes after Stage C approval

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

### 5. Issues found during generation

- **Answer-key defect caught by validation (fixed).** In the first run, the hand-written TC01 FIN key stated the IN-05 `difference_reported` reported value as the ledger figure instead of `0.00` (three findings).
  - The independent validator reported a mismatch. The data was correct; the key text was wrong.
  - The key was corrected in `tools/scenario_specs.py`, the suite regenerated, and validation re-run: PASS.
- No other issue. Every guard in section 2 held.

### 6. Not done (by instruction)

- No UC-042 engine, application, Smart Parser or Ringfence run. ENGINE-PREDICTED values are unverified.
- No engine or source file, frozen scenario, baseline dataset or answer key was modified. The approved Stage B documents are archived unchanged.
- No future reconciliation capability was implemented.

---

## UC-042 Reconciliation Test Suite V2: Offline Validation Report (Stage E)

**Overall result: PASS.** Date: 23 Nov 2026. Validator: `tools/validate_suite.py`. Negative tests: `tools/negative_tests.py`.

> **Scope.** This validates the **generated datasets and answer keys** only. No UC-042 engine, application or AI was executed. Nothing here shows how the engine behaves: every ENGINE-PREDICTED outcome remains unverified.

### 1. Independence

- The validator imports no engine code.
- The schema contract comes from an `ast` read of the reference `schema.py`. Every reconciliation calculation, matching rule and period rule is a separate implementation written for this suite.
- The FIN answer keys were written by hand from the specification (`tools/scenario_specs.py`) and **not** derived from the generated files. The validator recomputes everything from the files and requires:
  - an **exact** set equality between its findings and the key's `expected_anomalies` (no missing and no extra finding);
  - exact equality of every key figure.
- **Control:** the clean baseline must produce zero structure errors and zero findings.

### 2. Checks performed

| Group | Checks |
|---|---|
| Structure | Exact canonical headers; UTF-8, no BOM, LF; row width; mandatory fields; type formats (amount, signed, date, ts with offset, bool, int, ccy, id); 20 enum sets; 11 conditional rules; unique primary keys; empty-file rule |
| Period | September membership per evidence type; permitted 31 Aug boundary rows; IN-04 open during period; IN-14 event reference and not logged before its reconciliation |
| References | Accounts, statements, bank_statement_id, batches, pools, IN-14 recon_ref |
| Recomputation | Bank (IN-07) vs ledger at 17:00 per account and day; requirement (Σ non-negative snapshots + open register) and resource; every IN-05/IN-06 reported value; client roll-forward for every consecutive snapshot pair; statement arithmetic, entry counts, parent consistency and continuity; 17:00 confirmation vs statement; batch arithmetic (TXN, FEE, REFUND, signed NET); line ↔ transaction; card transaction in exactly one line; batch ↔ bank (count, amount, booking lag); own-funds top-ups; cash book ↔ bank by reference (missing, multiple, amount, cross-day timing); **many-to-one claims** (duplicates); bank entries without counterpart; direct loads and redemptions ↔ bank; register matching and allocation deadline; refunds; currency; daily coverage; discrepancy-log coverage of every bank-ledger difference; records on non-reconciliation days |
| Mutations | Row-level diff against the baseline (corrections: against the initial submission) must equal `mutations.json` exactly; files not named in any operation are byte-identical; unchanged rows keep their exact text and order; PDFs identical to the baseline; corrected TC01 and TC05 files byte-identical to the baseline |
| Packaging | `manifest.csv` SHA-256 and record counts; `scenario.json` identity; no `answer_key.json` in case roots; upload ZIP = exactly the 19 canonical names with bytes identical to the case, CRC-clean; ENGINE-PREDICTED JSON consistency (sequential IDs, Σ affected_results = non-passing results, groups and candidates reference existing exceptions, CLEAN ⇔ no non-passing results, label NOT EXECUTED); FUTURE and AI files present and labelled |

### 3. Results by case

| Case | Status | Structure errors | Findings (= FIN key) | FIN figures checked | Changes verified | Manifest / ZIP / JSON |
|---|---|---|---|---|---|---|
| CONTROL: clean baseline must produce no structure errors and no findings | **PASS** | 0 | 0 (exact match) | 0 | - | - |
| TC01 initial submission | **PASS** | 0 | 25 (exact match) | 12 | 1 | OK |
| TC01 corrected case | **PASS** | 0 | 0 (exact match) | 3 | 1 | OK |
| TC02 initial submission | **PASS** | 0 | 2 (exact match) | 4 | 1 | OK |
| TC03 initial submission | **PASS** | 0 | 4 (exact match) | 8 | 11 | OK |
| TC04 initial submission | **PASS** | 0 | 3 (exact match) | 4 | 6 | OK |
| TC04 corrected case | **PASS** | 0 | 0 (exact match) | 4 | 7 | OK |
| TC05 initial submission | **PASS** | 0 | 5 (exact match) | 6 | 3 | OK |
| TC05 corrected case | **PASS** | 0 | 0 (exact match) | 2 | 3 | OK |
| TC06 initial submission | **PASS** | 0 | 8 (exact match) | 8 | 5 | OK |

### 4. Findings recomputed from the generated data (each equals the FIN key exactly)

**TC01 initial submission**

- `BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007`
- `BL_DIFF 2026-09-28 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-29 SGA-GBP-01 -1246.80`
- `BL_DIFF 2026-09-30 SGA-GBP-01 -1246.80`
- `BL_DIFF_NOT_LOGGED 2026-09-28 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-29 SGA-GBP-01`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-GBP-01`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 item_a reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260928 resource_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 item_a reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260929 resource_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 difference_reported reported=0.00 recomputed=1246.80`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 item_a reported=395844.86 recomputed=397091.66`
- `REPORTED IN-05 IRR-EMONEY-GBP-20260930 resource_reported reported=395844.86 recomputed=397091.66`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260928 ledger_balance_reported reported=378706.65 recomputed=379953.45`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260929 ledger_balance_reported reported=388744.47 recomputed=389991.27`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 difference_reported reported=0.00 recomputed=-1246.80`
- `REPORTED IN-06 ERL-SGA-GBP-01-20260930 ledger_balance_reported reported=395844.86 recomputed=397091.66`
- `RR_DIFF 2026-09-28 GBP 1246.80`
- `RR_DIFF 2026-09-29 GBP 1246.80`
- `RR_DIFF 2026-09-30 GBP 1246.80`

**TC01 corrected case**

- none (consistent dataset)

**TC02 initial submission**

- `ROLLFWD GBP/C0006 2026-09-08 18.00`
- `TXN_BANK_AMOUNT TX-0908-00002 ref=E2E-GBP-0908-L02 txn=3053.61 bank=3035.61`

**TC03 initial submission**

- `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25`
- `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05`
- `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001`
- `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05`

**TC04 initial submission**

- `BANK_NO_COUNTERPART BE-EUR-0930-U01 ref=E2E-EUR-0930-U01`
- `BL_DIFF 2026-09-30 SGA-EUR-01 650.00`
- `BL_DIFF_NOT_LOGGED 2026-09-30 SGA-EUR-01`

**TC04 corrected case**

- none (consistent dataset)

**TC05 initial submission**

- `LINE_TXN SL-SB-EUR-20260924-0001 TX-0924-00018 missing`
- `LINE_TXN SL-SB-EUR-20260924-0002 TX-0924-00019 missing`
- `LINE_TXN SL-SB-EUR-20260924-0003 TX-0924-00020 missing`
- `ROLLFWD EUR/C0101 2026-09-24 625.27`
- `ROLLFWD EUR/C0104 2026-09-24 222.18`

**TC05 corrected case**

- none (consistent dataset)

**TC06 initial submission**

- `BATCH_ARITH AQ-EUR-20260922 NET lines=2059.53 header=2104.53`
- `BATCH_ARITH AQ-EUR-20260922 TXN lines=2069.15 header=2114.15`
- `LINE_TXN SL-AQ-EUR-20260922-0002 TX-0922-00016 amount line=1238.12 txn=1283.12`
- `ROLLFWD GBP/C0004 2026-09-17 -90.00`
- `ROLLFWD GBP/C0004 2026-09-18 90.00`
- `ROLLFWD GBP/C0007 2026-09-17 90.00`
- `RR_DIFF 2026-09-17 GBP -90.00`
- `TXN_BANK_AMOUNT TX-0917-00002 ref=E2E-GBP-0917-L02 txn=1480.07 bank=1390.07`

### 5. Negative tests (the validator must reject deliberately broken copies)

| Test | Rejected | Detected by | Sample |
|---|---|---|---|
| unrelated amount change (TC02: bank entry BE-GBP-0901-L01) | yes | fin_unexpected_findings | `CASH_BANK_AMOUNT LE-GBP-0901-0001/BE-GBP-0901-L01 ledger=2926.33 bank=2926.34` |
| header renamed (TC02: IN-11 amount -> amt) | yes | structure_errors | `IN-11 header differs from the canonical schema` |
| invalid enum (TC04: dc_indicator X) | yes | structure_errors | `IN-09 L266 dc_indicator='X': not one of ['C', 'D']` |
| 25 Sep clearing entry removed (TC03) | yes | fin_unexpected_findings, fin_missing_findings | `BATCH_BANK AQ-GBP-20260924 matches=0` |
| duplicate posting removed (TC01 initial no longer shows the duplicate) | yes | fin_missing_findings | `BANK_MULTI_CLAIM BE-GBP-0928-L01 IN-10=LE-GBP-0928-0001,LE-GBP-0928-0007` |
| amount format 1,390.07 (TC06) | yes | structure_errors | `IN-11 L241 amount='1,480.07': invalid amount` |

### 6. Financial differences confirmed

| Scenario | Confirmed from the data |
|---|---|
| TC01 | bank − ledger −1,246.80 and resource − requirement +1,246.80 on 28, 29 and 30 Sep; bank entry BE-GBP-0928-L01 claimed by two cash-book rows; reported IN-05/IN-06 values match the bank, not the extract |
| TC02 | TX-0908-00002 3,053.61 vs bank 3,035.61 (+18.00); C0006 8 Sep roll-forward +18.00; 9 Sep reconciles |
| TC03 (revision 3) | 24 Sep 17:00 bank 365,108.24 vs ledger 370,603.29 (−5,495.05, reported and logged); timing pair LE-GBP-0924-0003 / BE-GBP-0925-T01 (24 → 25 Sep); 25 Sep bank = ledger = 375,461.46; batch lag 1 business day; no records on non-reconciliation days; no other finding |
| TC04 | bank − ledger +650.00 on 30 Sep EUR; BE-EUR-0930-U01 has no counterpart; no log entry. Corrected: consistent, requirement and resource 119,205.00 |
| TC05 | C0101 +625.27 and C0104 +222.18 roll-forward gaps; 3 lines reference missing transactions. Corrected: byte-identical to the baseline IN-11 |
| TC06 | A: +90.00 (TX-0917-00002, C0007); B: C0004 −90.00 on 17 Sep and +90.00 on 18 Sep, internal −90.00; C: AQ-EUR-20260922 TXN −45.00 and NET −45.00, line vs transaction |

### 7. Unresolved issues and assumptions

1. **ENGINE-PREDICTED outcomes are unverified** for all six scenarios. Above all, TC06's predicted over-grouping (G-18) and the predicted exception counts must be confirmed by an engine run.
2. **TC03 amount.** Revision 3 uses 5,495.05 (the AQ-GBP-20260924 net), not the originally stated 4,647.75; the user chose this. The weekend-record issue of revision 2 no longer applies: revision 3 has 0 `NON_RECON_DAY_RECORD` findings.
3. **The validator's own rules are an independent re-implementation**, not the engine. Agreement with the engine is not claimed.
4. **Ringfence acceptance** of canonical-name upload ZIPs, and its exception identifiers, are not verified (G-20).
5. **Business-day calculation** uses England and Wales 2026 holidays; none fall in the affected dates.

---

## UC-042 Reconciliation Test Suite V2: Scenario Catalogue (Stage B specifications)

**Status:** Stage C APPROVED 23 Nov 2026. TC03 was revised twice on the user's instruction after approval; current revision 3 = 24/25 Sep. Datasets were generated (Stage D) and validated offline (Stage E). **Nothing has been executed by the UC-042 engine or application.** The approved Stage B text is preserved in `archive/stage_b_approved_20261123/`.

### Common basis

| Item | Value |
|---|---|
| Baseline | `shared_baseline/`, a byte-verified copy of `set_01_clean_baseline` (19/19 SHA-256 match). Every scenario is that baseline plus the mutations listed below and nothing else. |
| Period | PER-2026-09 (1–30 Sep 2026); 22 reconciliation days; reconciliation point 17:00 Europe/London |
| Evidence entity | SYN-EMI-001 / "Synthetic EMI Ltd", accounts at the fictional "Example Bank plc" (inherited from the baseline) |
| Customer label | Each scenario has a distinct fictional case label starting `SYNTHETIC TEST`. Distinct labels avoid case collisions if the scenarios are loaded into Ringfence. |
| Mutation format | The R1 `scenarios.py` operation vocabulary: `delete_record`, `set_field` (with the expected old value), `add_record`. Each op carries a `why`. |
| Reference engine | `C:\u42v\e2e_20261122\engine_base\uc042\uc042lib` (17 Nov 2026 rules) |

#### How expectations are labelled

| Label | Meaning |
|---|---|
| **FIN** | A deterministic financial expectation, calculated independently from the synthetic data. Engine-independent. |
| **ENGINE-PREDICTED** | What the current engine is expected to output, from reading its source only. Not executed. Exception IDs assume `scenario.json` `scenario_id` = TCnn. |
| **FUTURE (PROPOSED)** | The desired behaviour of the enriched engine. Category names are `PENDING:<label>`. They are not control or exception IDs. |
| **AI** | Expectations for the AI investigation, kept separate from FIN |

### Summary

| ID | Behaviour | Customer label | Mutated files | Correction | ENGINE-PREDICTED status / exceptions / groups |
|---|---|---|---|---|---|
| TC01 | Duplicate transaction (cash-book double posting) | SYNTHETIC TEST Ashcombe Pay Ltd | IN-10 | **Yes**: corrected IN-10 | EXCEPTIONS_OPEN / 10 / 1 |
| TC02 | Amount mismatch (transaction export vs bank) | SYNTHETIC TEST Brindle Wallet Ltd | IN-11 | No | EXCEPTIONS_OPEN / 2 / 0 |
| TC03 | Timing difference (24 Sep recorded, 25 Sep cleared; revision 3) | SYNTHETIC TEST Cresswell Money Ltd | IN-06, IN-07, IN-08, IN-09, IN-14 | No | EXCEPTIONS_OPEN / 1 / 0 (TIMING_EVIDENCED) |
| TC04 | Unmatched transaction (unrecorded bank credit) | SYNTHETIC TEST Dunmore Payments Ltd | IN-06, IN-07, IN-08, IN-09 | **Yes**: IN-04, IN-05, IN-06, IN-10 | Initial EXCEPTIONS_OPEN / 2 / 1; corrected CLEAN |
| TC05 | Several discrepancies, one possible cause (batch omitted from export) | SYNTHETIC TEST Elmstead Card Services Ltd | IN-11 | **Yes**: corrected IN-11 | Initial EXCEPTIONS_OPEN / 3 / 0 (+1 candidate); corrected CLEAN |
| TC06 | Independent discrepancies (with a same-day, same-amount decoy) | SYNTHETIC TEST Farrowdale E-Money Ltd | IN-03, IN-05, IN-11, IN-13 | No | EXCEPTIONS_OPEN / 6 / 1 (predicted over-grouping) |

---

### TC01: Duplicate transaction

**Business situation.** The firm's cash-book interface was re-run at 09:25 on Mon 28 Sep 2026. It re-posted the 09:10 inbound bank transfer `E2E-GBP-0928-L01` (client C0008, £1,246.80) as a new ledger row. The cash-book extract supplied for the audit contains both rows. The firm's own reconciliation records (IN-05, IN-06) were prepared from the correct ledger and do not contain the duplicate. The defect is in the extract supplied as evidence.

**Evidence compared:**

| File | Record | Content |
|---|---|---|
| IN-10 cash book | `LE-GBP-0928-0001` (original), `LE-GBP-0928-0007` (duplicate) | |
| IN-09 bank | `BE-GBP-0928-L01` | The only bank entry carrying `E2E-GBP-0928-L01` |
| IN-11 transactions | `TX-0928-00001` | The only LOAD_BANK carrying that reference |
| IN-03 snapshots | C0008 | Rises by £1,246.80 once |
| IN-05, IN-06 | | Reported 28–30 Sep values |

**Mutation (1 op):**

| Op | File | Record | Change | Why |
|---|---|---|---|---|
| add_record, inserted after `LE-GBP-0928-0001` | IN-10 | `LE-GBP-0928-0007` | `SGA-GBP-01, 2026-09-28T09:25:00+01:00, BANK_LOAD, 1246.80, D, GBP, E2E-GBP-0928-L01` | Interface re-run re-posted the 09:10 receipt |

**Unchanged on purpose:** IN-09, IN-11, IN-03, IN-05, IN-06 and IN-14 (header only).

#### Duplicate classification

**Exact duplicate of one business event, with a distinct ledger key.** Same account, amount, type and end-to-end reference.

Evidence that the two rows are **not** a legitimate repeated payment:

- The end-to-end reference is unique per payment.
- The bank shows one credit.
- The client ledger shows one LOAD_BANK.
- C0008's snapshot rises by £1,246.80 only once.

**Legitimate-repeat controls (baseline, unchanged).** These must **not** be flagged as duplicates:

- Four LOAD_CARD of £2,500.00 on 8 Sep (`TX-0908-00003`…`-00006`) for four different clients, each on its own line of AQ-GBP-20260908.
- Refunds equal to their originals: `TX-0909-0R001` (60.00) and `TX-0916-0R001` (284.02).

#### FIN

| Day | Ledger at 17:00 (recomputed, with duplicate) | Bank 17:00 (IN-07) | Bank − ledger | Requirement (IN-03) | Resource − requirement |
|---|---|---|---|---|---|
| 28 Sep | 379,953.45 | 378,706.65 | **−1,246.80** | 378,706.65 | **+1,246.80** |
| 29 Sep | 389,991.27 | 388,744.47 | **−1,246.80** | 388,744.47 | **+1,246.80** |
| 30 Sep | 397,091.66 | 395,844.86 | **−1,246.80** | 395,844.86 | **+1,246.80** |

The reported figures (IN-05 item_a and resource, IN-06 ledger) are unchanged and equal the bank figures.

- Overstatement of the extract's ledger: £1,246.80 from 28 Sep to the period end.
- Real safeguarding position: unaffected (bank = client requirement).

#### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (13) | C08-DIFFERENCE ×3 (28/29/30 Sep SGA-GBP-01), DISC-LOG ×1, C06-DIFFERENCE ×3, C05-RESOURCE ×3, RC2-LEDGER ×3 |
| Exceptions (10) | EXC-TC01-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-28\|-1246.80` (4 results; flags OWN_FUNDS_REQUIRED, NO_INVESTIGATION_LOGGED; evidence status NOT_EVIDENCED) |
| | EXC-TC01-02/03/04 Critical `INTERNAL_DIFFERENCE\|2026-09-2{8,9}/GBP` and `…\|2026-09-30/GBP` |
| | EXC-TC01-05/07/09 High `C05-RESOURCE\|<day>/GBP` |
| | EXC-TC01-06/08/10 High `RC2-LEDGER\|<day>/SGA-GBP-01` |
| Groups | 1: GRP-TC01-01 = the 3 INTERNAL_DIFFERENCE exceptions (L2 PERSISTENCE). No candidates. |
| Must hold | CASH-BANK-LINK **PASS** for both `LE-GBP-0928-0001` and `LE-GBP-0928-0007` (gap G-04). RC4-DIRECT `TX-0928-00001` PASS. C04 PASS. CBAL-ROLLFWD PASS. |

#### FUTURE (PROPOSED)

- One root `PENDING:DUPLICATE_TRANSACTION`: `LE-GBP-0928-0007` duplicates `LE-GBP-0928-0001`, matched on account + payment_reference + amount + entry_type, with one bank counterpart.
- All ledger-derived failures for 28–30 Sep are linked to it as consequences (G-05).
- Financial impact: +1,246.80 ledger overstatement.
- The legitimate-repeat controls are not flagged.

#### AI

The investigation should find all of the following:

- (a) Two IN-10 rows share `E2E-GBP-0928-L01`, while IN-09 and IN-11 each have one, so this is a duplicate posting, not two receipts.
- (b) The −1,246.80 bank-ledger difference and the +1,246.80 internal differences from 28 Sep onward equal the duplicate exactly.
- (c) The firm's reported figures do not include the duplicate, which points to the evidence extract rather than the firm's reconciliation.

**Missing evidence:** the interface run log.

**Confidence:** high for the duplicate; medium for "extract defect versus ledger defect".

**Cited evidence:** IN-10 L(original, duplicate), IN-09 `BE-GBP-0928-L01`, IN-11 `TX-0928-00001`, IN-05 and IN-06 for 28–30 Sep.

**Expected analyst action:** reject the submitted cash-book extract and request a corrected one. No own-funds top-up is needed: the real position is unaffected.

#### Correction

| Item | Detail |
|---|---|
| Correction file | `corrections/source_data/sga_cashbook_entries_2026-09.csv` with `LE-GBP-0928-0007` removed. It is byte-identical to the baseline IN-10. |
| What was wrong | Duplicate interface posting |
| What changed | One row removed |
| Expected after correction | **CLEAN**, identical to the baseline frozen key (0 exceptions) |

---

### TC02: Amount mismatch

**Business situation.** Client C0006's bank-transfer load on Tue 8 Sep 2026 (end-to-end reference `E2E-GBP-0908-L02`) was received by the bank, posted to the cash book and reflected in the client ledger snapshot at £3,035.61. The client transaction export (IN-11) shows £3,053.61, a two-digit transposition in the export.

**Evidence compared:**

| File | Record | Amount |
|---|---|---|
| IN-11 | `TX-0908-00002` | 3,053.61 |
| IN-09 | `BE-GBP-0908-L02` | 3,035.61 (C) |
| IN-10 | `LE-GBP-0908-0002` | 3,035.61 (D) |
| IN-03 | C0006 snapshots 7 and 8 Sep | |

**Mutation (1 op):**

| Op | File | Record | Field | Old → new | Why |
|---|---|---|---|---|---|
| set_field | IN-11 | `TX-0908-00002` | amount | 3035.61 → 3053.61 | Transposition in the platform export |

#### FIN

- Transaction − bank = **+18.00**: the export overstates the receipt. The difference is a multiple of 9, the usual transposition signature.
- C0006 roll-forward for 8 Sep: 36,356.73 + 2,769.64 = 39,126.37, against a snapshot of 39,108.37, so roll-forward − snapshot = **+18.00**.
- The 9 Sep pair reconciles (0.00).
- Majority evidence:

| Value | Sources |
|---|---|
| 3,035.61 | IN-09, IN-10, IN-03 |
| 3,053.61 | IN-11 only |

- No balance impact on the bank, the ledger or the requirement.

#### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (2) | RC4-DIRECT `TX-0908-00002` FAIL (computed 3053.61, reported 3035.61); CBAL-ROLLFWD `GBP/C0006 2026-09-08` FAIL (computed 39126.37, reported 39108.37) |
| Exceptions (2, High) | EXC-TC02-01 `CBAL-ROLLFWD\|GBP/C0006 2026-09-08`; EXC-TC02-02 `RC4-DIRECT\|TX-0908-00002` |
| Groups | 0 (gap G-08) |
| Must hold | CASH-BANK-LINK `LE-GBP-0908-0002` PASS; C08 and C06 for 8 Sep PASS; CBAL 9 Sep PASS |

#### FUTURE (PROPOSED)

- One root `PENDING:AMOUNT_MISMATCH` on reference `E2E-GBP-0908-L02`: IN-11 3,053.61 vs IN-09 3,035.61, difference +18.00 (transaction > bank).
- The CBAL failure is linked by `txn_id` lineage.
- The outlier source is IN-11 (G-07, G-08, G-09).

#### AI

The investigation should:

- Identify both exceptions as one mismatch on `TX-0908-00002`.
- State the direction.
- Name IN-11 as the outlier, corroborated by three sources.
- Note that the difference is divisible by 9, as a possible transposition. That is a **hypothesis**, not evidence.

**Missing evidence:** the platform's audit trail for the export.

**Must not:** recommend changing the bank or the cash book.

**Expected analyst action:** accept the finding and request a corrected transaction export. The client balance is correct, so no client-money shortfall arises.

**Correction:** none. This scenario stays as an investigation demonstration.

---

### TC03: Timing difference, 24 Sep recorded / 25 Sep cleared (REVISION 3, 23 Nov 2026)

> **Revision history.**
>
> | Revision | Design | Where it is kept |
> |---|---|---|
> | 1 | 30 Sep / 1 Oct, as approved at Stage C | `archive/stage_b_approved_20261123/` |
> | 2 | 25 Sep / Sat 26 Sep, needing weekend records | `archive/rev2_tc03_25_26_sep_20261123/` |
> | 3 (current) | Thu 24 Sep / Fri 25 Sep, using the existing batch AQ-GBP-20260924 | this section |
>
> - The user chose revision 3, including its amount of **5,495.05**. The previously stated 4,647.75 is the net of the 25 Sep batch, whose card loads were made on 25 Sep.
> - Before/after detail: `TC03_REVISION_3_CHANGE_RECORD.md`.

**Business situation.** The acquirer settlement for Thursday 24 Sep 2026 is `AQ-GBP-20260924`.

| Stage | Detail |
|---|---|
| Card loads | Authorised and executed on 24 Sep |
| Settlement | Net £5,495.05; cycle date and settlement date 24 Sep |
| Firm's cash book | Posted at 14:00 on 24 Sep as `LE-GBP-0924-0003` |
| Bank | Credited on **Friday 25 Sep 08:00**, the next business day (`BE-GBP-0925-T01`, same reference and amount) |

At the 24 Sep 17:00 cut-off the bank is £5,495.05 below the ledger. The firm reported the difference, claimed timing and logged it as `DL-0001` (cause TIMING, evidence BE-GBP-0925-T01, RESOLVED 25 Sep). At 25 Sep 17:00 bank and ledger agree.

There are no weekend or non-reconciliation-day records.

**Mutations (11 ops):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | delete_record | IN-09 | `BE-GBP-0924-AQ1` | The 24 Sep 14:00 credit of 5,495.05 is not on the 24 Sep statement |
| 2 | add_record | IN-09 | `BE-GBP-0925-T01` | `ST-SGA-GBP-01-20260925-EOD`, 2026-09-25T08:00, value 2026-09-25, 5495.05 C, reference AQ-GBP-20260924 |
| 3–4 | set_field | IN-08 | `ST-SGA-GBP-01-20260924-EOD` | closing 370603.29 → 365108.24; entry_count 6 → 5 |
| 5–6 | set_field | IN-08 | `ST-SGA-GBP-01-20260925-EOD` | opening 370603.29 → 365108.24; entry_count 5 → 6. The closing is unchanged at 375461.46. |
| 7 | set_field | IN-07 | `ST-SGA-GBP-01-20260924-1700` | 370603.29 → 365108.24 |
| 8–10 | set_field | IN-06 | `ERL-SGA-GBP-01-20260924` | bank_balance_reported → 365108.24; difference_reported 0.00 → -5495.05; timing_difference_claimed false → true |
| 11 | add_record | IN-14 | `DL-0001` | Logged 2026-09-24T18:05 against ERL-SGA-GBP-01-20260924, -5495.05, TIMING, evidence BE-GBP-0925-T01, RESOLVED 2026-09-25T09:00, approver U-04 |

**Unchanged on purpose:**

- IN-10 cash book, IN-11, IN-12 and IN-13 for the batch.
- IN-03, IN-05 and IN-01.
- The 25 Sep 17:00 confirmation and the 25 Sep closing balance, both 375,461.46: the clearing is booked before 17:00.
- The own-funds top-up TOPUP-GBP-20260924, still on 24 Sep.

#### FIN

| Item | Value |
|---|---|
| Transaction date | 24 Sep |
| Processing | Cash book 24 Sep 14:00 |
| Settlement date | 24 Sep |
| Bank clearing | Fri 25 Sep 08:00 |
| Cut-off | 24 Sep 17:00 |

| Point | Bank | Ledger | Bank − ledger |
|---|---|---|---|
| 24 Sep 17:00 | 365,108.24 | 370,603.29 | **−5,495.05** (reported and logged) |
| 25 Sep 17:00 | 375,461.46 | 375,461.46 | 0.00 |

- Requirement = resource on both days (370,603.29 and 375,461.46).
- Under the existing D1 rule, the clearing window is the next business day after 24 Sep, i.e. Fri 25 Sep. The clearing is inside it.
- **Expected treatment:** an explainable timing item. Under existing rules the 24 Sep difference is still a C08 exception, OPEN and awaiting human confirmation. It is never auto-resolved.

**Validator findings (exact set):**

- `BL_DIFF 2026-09-24 SGA-GBP-01 -5495.05`
- `BL_DIFF_LOGGED 2026-09-24 SGA-GBP-01 DL-0001`
- `TIMING LE-GBP-0924-0003/BE-GBP-0925-T01 ref=AQ-GBP-20260924 recorded=2026-09-24 bank=2026-09-25 amount=5495.05`
- `BATCH_LAG AQ-GBP-20260924 settlement=2026-09-24 booked=2026-09-25`

#### ENGINE-PREDICTED (not executed)

| Item | Prediction |
|---|---|
| Non-passing results (1) | C08-DIFFERENCE `2026-09-24/SGA-GBP-01` FAIL, evidence status **TIMING_EVIDENCED** |
| Exception | EXC-TC03-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-GBP-01\|2026-09-24\|-5495.05`. Category "explained by timing evidence, awaiting human confirmation". Flag OWN_FUNDS_REQUIRED. Status OPEN. |
| Groups | 0 |
| Must hold | DISC-LOG PASS. C11-BATCH-BANK `AQ-GBP-20260924` PASS, with the informational note of a 1-business-day lag. CASH-BANK-LINK and FUND-TOPUP PASS. C08 25 Sep PASS. DQ22, DQ23 and BC-VS-EOD PASS. |

#### FUTURE (PROPOSED)

`PENDING:TIMING_ITEM`: one traceable item covering transaction → posting → settlement date → bank credit. It stays OPEN until a human confirms it.

#### AI

The investigation should find:

- The −5,495.05 equals the AQ-GBP-20260924 net.
- It was recorded at 14:00 on 24 Sep and credited at 08:00 on 25 Sep.
- It cleared on the next business day.
- The timing claim is corroborated by the 25 Sep statement, not by the claim or the log label.

**Must not:** mark the exception resolved.

**Analyst action:** confirm the timing item, and confirm whether the firm's policy required an own-funds top-up at the 24 Sep point.

**Correction:** none.

---

### TC04: Unmatched transaction

**Business situation.** At 16:20 on Wed 30 Sep 2026 the EUR safeguarding account received an inbound transfer of €650.00:

| Field | Value |
|---|---|
| Bank reference / end-to-end reference | `E2E-EUR-0930-U01` |
| Payer | Unidentified |
| Cash book | Not posted |
| Unallocated register | Not recorded |
| Client transaction | None |

The firm's external reconciliation reported the €650.00 bank-over-ledger difference but logged no investigation. Its internal reconciliation omitted the receipt.

**Mutations, initial submission (6 ops):**

| # | Op | File | Record | Change |
|---|---|---|---|---|
| 1 | add_record, after `BE-EUR-0930-R01` | IN-09 | `BE-EUR-0930-U01` | `ST-SGA-EUR-01-20260930-EOD, SGA-EUR-01, 2026-09-30, 2026-09-30T16:20:00+01:00, 2026-09-30, 650.00, C, EUR, E2E-EUR-0930-U01, E2E-EUR-0930-U01, Synthetic payer (unidentified), INBOUND TRANSFER` |
| 2–3 | set_field | IN-08 | `ST-SGA-EUR-01-20260930-EOD` | closing 118555.00 → 119205.00; entry_count 5 → 6 |
| 4 | set_field | IN-07 | `ST-SGA-EUR-01-20260930-1700` | balance 118555.00 → 119205.00 |
| 5–6 | set_field | IN-06 | `ERL-SGA-EUR-01-20260930` | bank_balance_reported 118555.00 → 119205.00; difference_reported 0.00 → 650.00 (timing claim stays false) |

**Matching references checked** (the engine's C11-BANK-ENTRY / BANK-CASH-LINK set) for `E2E-EUR-0930-U01`, all absent:

- IN-10.payment_reference
- IN-11.payment_reference
- IN-04.bank_reference
- IN-12.expected_bank_reference
- the `TOPUP-EUR-20260930` reference

#### FIN

- 30 Sep 17:00: bank 119,205.00 vs ledger 118,555.00, so bank − ledger = **+650.00**.
- The recomputed requirement (118,555.00) is **potentially understated by up to €650.00**: if the receipt is relevant funds, it belongs in the register at receipt.
- The net safeguarding position is unaffected if it is recorded on both sides.

#### ENGINE-PREDICTED (initial)

This mirrors the executed S05 pattern.

| Item | Prediction |
|---|---|
| Non-passing results (4) | C08-DIFFERENCE `2026-09-30/SGA-EUR-01` FAIL (NOT_EVIDENCED); DISC-LOG `SGA-EUR-01 from 2026-09-30` FAIL; BANK-CASH-LINK `BE-EUR-0930-U01` FAIL; C11-BANK-ENTRY `BE-EUR-0930-U01` FAIL |
| Exceptions (2) | EXC-TC04-01 Critical `BANK_LEDGER_DIFFERENCE\|SGA-EUR-01\|2026-09-30\|650.00` (flag NO_INVESTIGATION_LOGGED; related record BE-EUR-0930-U01) |
| | EXC-TC04-02 High `UNMATCHED_BANK_ENTRY\|BE-EUR-0930-U01` (2 results) |
| Groups | GRP-TC04-01 = {01, 02} (L3 LINEAGE: entry booked 16:20, inside the 17:00 balance) |
| Must hold | C04, C05, C06 EUR 30 Sep PASS. The engine cannot see the requirement understatement (G-15). |

#### FUTURE (PROPOSED)

- `PENDING:UNMATCHED_TRANSACTION` (bank-side, credit).
- Classified as a potential unidentified receipt, with a possible requirement understatement of €650.00 (G-15).

#### AI

The investigation should find:

- The credit has no counterpart in any of the five reference sources.
- It is a **credit** of client-type form (end-to-end reference pattern, "INBOUND TRANSFER").
- It probably belongs in the unallocated register as UNIDENTIFIED. That is a hypothesis.

**Missing evidence:** payer details and remittance information.

**Must not:** allocate the receipt to any client.

**Expected analyst action:** require the firm to record the receipt (register and cash book) and correct its reconciliations, then resubmit.

#### Correction

The firm completes its records. There are 4 corrected files in `corrections/source_data/`:

| File | Change |
|---|---|
| IN-04 | Add `UR-0003`: `E2E-EUR-0930-U01, 2026-09-30, 2026-09-30T16:20:00+01:00, 650.00, EUR, UNIDENTIFIED`, identified/allocated fields blank |
| IN-10 | Add `LE-EUR-0930-0006`: `SGA-EUR-01, 2026-09-30T16:20:00+01:00, UNALLOCATED_RECEIPT, 650.00, D, EUR, E2E-EUR-0930-U01` |
| IN-05 | `IRR-EMONEY-EUR-20260930`: requirement_reported, resource_reported and item_a 118555.00 → 119205.00; difference stays 0.00 |
| IN-06 | `ERL-SGA-EUR-01-20260930`: ledger_balance_reported 118555.00 → 119205.00; difference_reported 650.00 → 0.00 |

**What was wrong:** the receipt was not recorded. **What changed:** it is now recorded as unidentified, with the reconciliations updated.

**Expected after correction (ENGINE-PREDICTED): CLEAN.**

- C04 includes UR-0003 (open at 17:00).
- CASH-BANK-LINK `LE-EUR-0930-0006` PASS.
- C11-BANK-ENTRY passes (register reference).
- C09-ALLOCATION `UR-0003` PASS: still open at the period end, with the allocation due 1 Oct, after the period.

---

### TC05: Several discrepancies with one possible cause

**Business situation.** The client transaction export (IN-11) omits all three EUR card spends of scheme batch `SB-EUR-20260924`. That is consistent with the export having been taken before that batch's clearing was processed. The scheme's own settlement report (IN-12, IN-13), the bank debit and the client ledger snapshots are complete.

| Missing transaction | Client | Amount |
|---|---|---|
| `TX-0924-00018` | C0104 | 222.18 |
| `TX-0924-00019` | C0101 | 431.57 |
| `TX-0924-00020` | C0101 | 193.70 |

Total €847.45 = batch gross = batch net.

**Mutations (3 ops):** `delete_record` IN-11 `TX-0924-00018`, `TX-0924-00019`, `TX-0924-00020`. Reason: the export omitted the batch's spends.

**Unchanged on purpose:** IN-12 `SB-EUR-20260924`, its lines `SL-SB-EUR-20260924-*`, IN-09 bank debit, IN-10, and IN-03.

#### FIN

| Client | Roll-forward (24 Sep) | Snapshot | Roll-forward − snapshot |
|---|---|---|---|
| C0101 | 29,803.31 + 812.37 = 30,615.68 | 29,990.41 | **+625.27** (= 431.57 + 193.70) |
| C0104 | 26,002.58 + 2,052.70 = 28,055.28 | 27,833.10 | **+222.18** |
| C0102 (control) | | | 0.00 |

- Batch lines reference 3 transaction IDs absent from IN-11: TXN lines total 847.45 against 0.00 of matching transactions.
- No bank, ledger or requirement impact.

#### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (3) | C11-BATCH-ARITH `SB-EUR-20260924` FAIL (3 lines do not match a transaction); CBAL-ROLLFWD `EUR/C0101 2026-09-24` FAIL; CBAL-ROLLFWD `EUR/C0104 2026-09-24` FAIL |
| Exceptions (3, High) | EXC-TC05-01 `C11-BATCH-ARITH\|SB-EUR-20260924`; EXC-TC05-02 `CBAL-ROLLFWD\|EUR/C0101 2026-09-24`; EXC-TC05-03 `CBAL-ROLLFWD\|EUR/C0104 2026-09-24` |
| Groups | 0 |
| Candidates | **1**: CAND-TC05-01 = {01, 03} (line TX-0924-00018 = 222.18). **No candidate for C0101**: its difference is the sum of two lines (G-16). |

#### FUTURE (PROPOSED)

- The three exceptions are presented together as one suspected common cause, still UNVERIFIED: missing transactions of batch SB-EUR-20260924.
- The basis is the batch scope plus a line-sum match per client.
- No cause is set deterministically (G-16, G-17).

#### AI (group-level)

| Element | Expectation |
|---|---|
| Individual discrepancies | (1) batch lines reference 3 IDs absent from the export; (2) C0101 is short 625.27 against its roll-forward; (3) C0104 is short 222.18 against its roll-forward |
| Possible common cause | The transaction export is incomplete for SB-EUR-20260924 |
| Connecting evidence | All 3 missing IDs belong to one batch. 222.18 equals one line exactly. 625.27 equals the sum of the other two lines. No other batch or day is affected. The header, lines and bank debit agree with each other. |
| Evidence still missing | The client of each missing transaction (settlement lines carry no client_id), and the export job log or a complete export |
| Confidence | Medium-high that the export is incomplete. Low-medium for the client attribution, which rests on amounts only. |

**Must not:** state the client attribution as confirmed.

**Expected analyst action:** request a complete transaction export.

#### Correction

| Item | Detail |
|---|---|
| Correction file | `corrections/source_data/transactions_2026-09.csv` with the 3 rows restored. It is byte-identical to the baseline IN-11. |
| Expected after correction | **CLEAN** (the baseline frozen key) |

---

### TC06: Independent discrepancies

**Business situation.** Three unrelated defects. A and B deliberately share **date (17 Sep), currency (GBP) and magnitude (£90.00)**. That coincidence is a decoy: a date-and-amount grouping would wrongly merge them.

| Cause | Situation | Mutation |
|---|---|---|
| A: export amount error | C0007 bank load `TX-0917-00002` (E2E-GBP-0917-L02): bank, cash book and snapshot show 1,390.07; the export shows 1,480.07 | set_field IN-11 `TX-0917-00002` amount 1390.07 → 1480.07 |
| B: client-ledger snapshot error | C0004's 17 Sep 17:00 snapshot is overstated by 90.00. The firm's internal reconciliation used that ledger, so it reports a 90.00 shortfall. | set_field IN-03 `CBS-20260917-C0004-GBP` balance 40592.24 → 40682.24; set_field IN-05 `IRR-EMONEY-GBP-20260917` requirement_reported 341484.46 → 341574.46 and difference_reported 0.00 → -90.00 |
| C: acquirer report line error (EUR, 22 Sep) | Line 2 of `AQ-EUR-20260922` states 1,238.12; its header, the transaction and the bank credit imply 1,283.12 | set_field IN-13 `SL-AQ-EUR-20260922-0002` amount 1283.12 → 1238.12 |

#### FIN

**Cause A:**

- Transaction − bank = **+90.00**.
- C0007 roll-forward for 17 Sep: 35,913.63 + 817.48 = 36,731.11 vs snapshot 36,641.11, so **+90.00**.
- The 18 Sep pair reconciles.

**Cause B:**

- C0004 17 Sep: roll-forward 40,592.24 vs snapshot 40,682.24, so **−90.00**.
- C0004 18 Sep: 40,682.24 + 1,492.89 = 42,175.13 vs snapshot 42,085.13, so **+90.00**.
- Recomputed requirement 17 Sep = 341,574.46 (as reported). Resource = 341,484.46. Difference = **−90.00** (apparent shortfall, as reported).

**Cause C:**

- TXN lines 2,069.15 vs gross 2,114.15, so **−45.00**.
- Signed lines 2,059.53 vs net 2,104.53, so **−45.00**.
- The line differs from `TX-0922-00016` by −45.00.
- The bank credit equals the header net, so there is no balance impact.

#### ENGINE-PREDICTED

| Item | Prediction |
|---|---|
| Non-passing results (6) | RC4-DIRECT `TX-0917-00002`; CBAL-ROLLFWD `GBP/C0007 2026-09-17`; C06-DIFFERENCE `2026-09-17/GBP` (C04 PASS); CBAL-ROLLFWD `GBP/C0004 2026-09-17`; CBAL-ROLLFWD `GBP/C0004 2026-09-18`; C11-BATCH-ARITH `AQ-EUR-20260922` |
| Exceptions (6) | EXC-TC06-01 Critical `INTERNAL_DIFFERENCE\|2026-09-17/GBP` |
| | EXC-TC06-02 `C11-BATCH-ARITH\|AQ-EUR-20260922` |
| | EXC-TC06-03 `CBAL-ROLLFWD\|GBP/C0004 2026-09-17` |
| | EXC-TC06-04 `CBAL-ROLLFWD\|GBP/C0004 2026-09-18` |
| | EXC-TC06-05 `CBAL-ROLLFWD\|GBP/C0007 2026-09-17` |
| | EXC-TC06-06 `RC4-DIRECT\|TX-0917-00002` (02–06 all High) |
| Groups | **Predicted over-grouping (G-18):** GRP-TC06-01 = {01, 03, **05**}. L3 lineage (b) links the internal difference to every same-day GBP roll-forward failure, including C0007's, whose snapshot is correct. EXC-04 (C0004's next day) and EXC-06 (C0007's RC4) stay ungrouped. No candidates. |

**Correct clustering (FUTURE, PROPOSED):**

| Cluster | Exceptions | Root |
|---|---|---|
| A | {06, 05} | `PENDING:AMOUNT_MISMATCH` on TX-0917-00002 |
| B | {01, 03, 04} | Snapshot error, C0004 17 Sep |
| C | {02} | Acquirer report line inconsistency |

The A/B coincidence must be recorded as **rejected** (no shared record or reference).

#### AI

The investigation should:

- Keep three separate causes.
- Explain that A is transaction-side (IN-11 is the outlier against IN-09, IN-10 and IN-03).
- Explain that B is snapshot-side (C0004's 17 Sep snapshot fails the roll-forward in both directions and drives the reported shortfall).
- Explain that C is internal to the acquirer report.
- Explicitly reject a link between A and B based on equal date and amount.

**Missing evidence:**

- A: the export audit trail.
- B: the client-ledger postings behind C0004's 17 Sep balance.
- C: the corrected acquirer report.

**Expected analyst actions:**

| Cause | Action |
|---|---|
| A | Request a corrected export |
| B | Investigate the client-ledger posting. The reported 17 Sep shortfall is not supported by the transactions. |
| C | Request a corrected acquirer report |

**Correction:** none (investigation demonstration).

---

### Stage C decisions (23 Nov 2026)

1. TC03: revision 3, 24/25 Sep, using AQ-GBP-20260924 (5,495.05). No supplementary or weekend evidence is used. Revision 2 (25/26 Sep) is archived.
2. TC06: retained. The predicted over-grouping (G-18) is documented as UNVERIFIED.
3. Packaging: engine-layout case directories, plus flat upload ZIPs of the 19 canonical files (per UC042_ZIP_INPUT_SPECIFICATION section 4), per-scenario packages and a master ZIP.
4. All ENGINE-PREDICTED values remain unexecuted.
