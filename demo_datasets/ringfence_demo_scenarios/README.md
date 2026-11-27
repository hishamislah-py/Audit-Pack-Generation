# Ringfence demo test data (four synthetic evidence ZIPs)

All data is synthetic: illustrative, fictional firms and banks, not real financial records.

These four ZIPs exercise the Ringfence React frontend end to end against the real Smart Parser backend (`p10\smartparser_phase1`). They work with **AI disabled**: every CSV in every ZIP uses the canonical UC-042 layout, so no LLM mapping proposal is ever needed.

| # | Folder | Upload file | Customer | Period | Expected outcome |
|---|---|---|---|---|---|
| 1 | `scenario_1_clean` | `Halden_Pay_Ltd_2026-06.zip` | Halden Pay Ltd | 2026-06 | **CLEAN**: 0 FAIL, 0 exceptions |
| 2 | `scenario_2_exceptions` | `Marlow_Street_Payments_Ltd_2026-07.zip` | Marlow Street Payments Ltd | 2026-07 | **EXCEPTIONS_OPEN**: 12 FAIL, 7 exceptions, 3 investigation groups |
| 3 | `scenario_3_evidence_incomplete` | `Corvane_Money_Ltd_2026-10.zip` | Corvane Money Ltd | 2026-10 | **EVIDENCE_INCOMPLETE**: 15 INSUFFICIENT_EVIDENCE, 1 Critical exception |
| 4 | `scenario_4_technical_failure` | `Thornbury_Wallet_Ltd_2026-11.zip` | Thornbury Wallet Ltd | 2026-11 | Smart Parser run **FAILED** (technical); Retry fails again; 2 FAILED runs kept |

Each folder contains:
- the ZIP to upload;
- `scenario.json`: customer, period, sha256, ZIP entries, seed, planted discrepancies, and the byte comparison with the original bundle;
- `expected_outcome.json`: written before any run. For S1–S3 it embeds the frozen answer key unchanged. For S4 it is derived from the backend code.
- `verification_result.json`: what the real backend actually returned.

`VERIFICATION_REPORT.md` gives expected vs actual for every scenario.

## Where the data comes from

The data reuses `Downloads\UC042_RINGFENCE_DEMO_SCENARIOS\tools\build_scenarios.py`, imported read-only and unmodified. Its seeds, generator and planted discrepancies are the same, so the frozen answer keys in that bundle still apply.

The changes from that bundle's `customer_submission.zip` files:
- **S1:** IN-11 now uses the canonical layout. The original's novel layout needed the LLM.
- **S2:** the real IN-08 (end-of-day statements) is included under the scenario's IN-08 file name. The original ZIP had a mis-named copy of IN-07 there.
- **S3:** IN-12 now uses the canonical layout. The original's novel layout needed the LLM.
- **S4:** new. Every other member is byte-identical to the original ZIP's member.

Rebuild with:

```
py -3.11 -B tools/build_demo_zips.py --out <this folder>
```

The build is deterministic: a rebuild gives byte-identical ZIPs.

Verify with:

```
py -3.11 -B tools/verify_demo_zips.py --data <this folder>
```

This starts one fresh backend per scenario on ports 8791–8794, with workspaces at `C:\u42v\rfdata_ws_<n>`.

## Uploading through the React app (`/rf/`)

1. Start the backend from `p10\smartparser_phase1`:

   ```
   py -3.11 -B -m smartparser.webapp.server --root <workspace> --authority tests/fixtures/review/test_authority_policy.json --uc042-root "C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042" --reviewer-id analyst-1 --reviewer-role analyst --reviewer-kind TEST --port <port>
   ```

   Do not set any AI provider key.
2. Open `http://127.0.0.1:<port>/rf/#/queue`, or the new frontend proxying `/api`.
3. Click **New case**. Enter the customer name and period **exactly** as in the table above, and choose the ZIP. The case appears as **WAITING**.
4. Open the case and click **Start Smart Parsing**, then confirm.

**Only one case can be IN_PROGRESS at a time.** Complete a case (that is, reconcile it) or Defer it before starting the next. Scenario 4 never completes. Run it last, or Defer it before starting another case.

### What the analyst should see

**Scenario 1: Halden Pay Ltd, 2026-06 (CLEAN)**
- The run completes with 19 categories processed: 14 CSV and 5 PDF, including optional IN-18 and IN-19.
- The proposals and review stages show `not_required`.
- **No mapping review** is needed: nothing is missing and nothing needs correction.
- Validation passes automatically. Tick the acknowledgement, then **Activate**, then **Run reconciliation**.
- Result: **CLEAN**, 1,965 controls, all PASS, no exceptions.

**Scenario 2: Marlow Street Payments Ltd, 2026-07 (EXCEPTIONS_OPEN)**
- The run completes with 19 categories. There is no review, and validation passes. Activate, then Reconcile.
- Result: **EXCEPTIONS_OPEN**, 2,068 controls (2,056 PASS, 12 FAIL), and **7 exceptions** (1 Critical, 6 High) in **3 investigation groups**:
  - **GRP-CASE-01:** an unexplained GBP difference of −1,284.60 on SGA-GBP-01, from 17 to 21 Jul 2026. It is made up of:
    - bank debit `CHG 77215` (BE-GBP-0717-X01);
    - its return on 22 Jul (BE-GBP-0722-X02);
    - the Critical `BANK_LEDGER_DIFFERENCE` exception: 3 C08-DIFFERENCE results plus DISC-LOG.
  - **GRP-CASE-02 and GRP-CASE-03:** an inconsistent settlement reference. Bank entry BE-GBP-0710-SB1 carries the reference of batch SB-GBP-20260701. As a result, batch SB-GBP-20260710 has no bank entry and SB-GBP-20260701 matches two. These results break: C11-BATCH-BANK, CASH-BANK-LINK and UNMATCHED_CASHBOOK_ENTRY.
- Open any exception to see its affected controls and evidence rows: file, line and source row.

**Scenario 3: Corvane Money Ltd, 2026-10 (EVIDENCE_INCOMPLETE)**
- The run completes with 18 categories: 14 CSV and 4 PDF. IN-19 is optional and not supplied.
- There is no review, and validation passes. **All required categories are present.** Activate, then Reconcile.
- Result: **EVIDENCE_INCOMPLETE**, 1,961 controls:
  - 1,944 PASS, 15 INSUFFICIENT_EVIDENCE and 2 NOT_APPLICABLE;
  - 1 Critical exception, `MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-10-15`, which affects 15 results.
- The bank evidence for the EUR safeguarding account on 15 Oct 2026 is missing:
  - the 17:00 confirmation, removed from IN-07;
  - the end-of-day statement, removed from IN-08;
  - that statement's entries, removed from IN-09.
- **Why evidence-incompleteness is modelled this way:** omitting a whole required category is blocked at activation, because package validation **PV-01** requires every category IN-01…IN-17. Such a case could never reach reconciliation. Incompleteness is therefore modelled by **missing records inside files that are present**.

**Scenario 4: Thornbury Wallet Ltd, 2026-11 (technical failure)**
- Registration succeeds (**WAITING**). The ZIP is structurally valid and lists 19 members.
- The member `Thornbury_Nov2026/09_bank_statement_lines.csv` (IN-09) has a deliberately wrong CRC-32 in its local and central headers. Its compressed data is untouched.
- On **Start**, the backend expands the ZIP. Reading that member raises `Bad CRC-32`, so the run is recorded as:
  - **FAILED** (code `RUN_FAILED`, stage `read`);
  - message: `Bad CRC-32 for file 'Thornbury_Nov2026/09_bank_statement_lines.csv'`.

  The Smart Parser step shows `failed`, and the outstanding list shows `RETRY_FROM_BEGINNING`.
- The only actions enabled are **Retry from Beginning** (with confirmation) and **Defer**. Activate, Reconcile and Upload are disabled.
- **Retry** creates run 2 from the **original ZIP**, per owner decision O1. Run 2 fails the same way. Both FAILED runs are kept and listed, and run 2 has `retry_of` = run 1. The activity log shows 2 × CASE_RUN_FAILED and CASE_RETRY_REQUESTED, and the audit chain is verified.
- This is the expected behaviour: a technical failure, not a business rejection. Nothing in the app or workspace is corrupted.
- The case remains IN_PROGRESS. **Defer** it to free the slot for other cases.

## Review steps

**None in any scenario.** Every CSV header is canonical, so mapping is deterministic. No file is ever listed under `outstanding.mapping_decisions`.

The analyst's only interactive steps are:
- Start (confirm);
- tick the acknowledgement and Activate;
- Run reconciliation;
- for S4: Retry (confirm), then Defer.
