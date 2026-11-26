# TC01 - Duplicate transaction: cash-book interface re-run duplicates bank load E2E-GBP-0928-L01 (1,246.80)

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

The firm's cash-book interface re-ran at 09:25 on Mon 28 Sep 2026 and re-posted the 09:10 inbound transfer E2E-GBP-0928-L01 (client C0008, GBP 1,246.80) as a new ledger row. The cash-book extract supplied for audit holds both rows. The firm's reconciliation records (IN-05, IN-06) were prepared from the correct ledger.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | Replacement files, complete corrected case, correction record |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
