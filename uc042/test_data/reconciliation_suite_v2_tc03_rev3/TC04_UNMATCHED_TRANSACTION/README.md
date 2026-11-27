# TC04 - Unmatched transaction: EUR 650.00 bank credit BE-EUR-0930-U01 with no counterpart

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

At 16:20 on Wed 30 Sep 2026 the EUR safeguarding account received an inbound transfer of 650.00 (E2E-EUR-0930-U01) from an unidentified payer. The firm did not post it to the cash book, did not record it in the unallocated register and created no client transaction. Its external reconciliation reported the difference but no investigation was logged.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | Replacement files, complete corrected case, correction record |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
