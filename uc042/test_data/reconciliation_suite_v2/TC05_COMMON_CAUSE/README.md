# TC05 - Common possible cause: all three spends of scheme batch SB-EUR-20260924 missing from the transaction export

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

The client transaction export (IN-11) omits the three EUR card spends of scheme batch SB-EUR-20260924 (total 847.45), consistent with the export being taken before the batch's clearing was processed. The scheme report, bank debit and client snapshots are complete.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | Replacement files, complete corrected case, correction record |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
