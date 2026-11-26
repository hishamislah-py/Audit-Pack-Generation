# TC02 - Amount mismatch: transaction export 3,053.61 vs bank 3,035.61 for E2E-GBP-0908-L02

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

Client C0006's bank-transfer load of Tue 8 Sep 2026 (E2E-GBP-0908-L02) was received by the bank, posted to the cash book and reflected in the client snapshot at 3,035.61. The transaction export (IN-11) shows 3,053.61: a transposition.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | not applicable (no correction in this scenario) |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
