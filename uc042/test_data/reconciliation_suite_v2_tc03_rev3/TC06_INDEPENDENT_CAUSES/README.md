# TC06 - Independent causes: export amount error (A), client snapshot error (B), acquirer line error (C); A and B share date and 90.00

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

Three unrelated defects. A: C0007's bank load TX-0917-00002 shows 1,480.07 in the export against 1,390.07 at the bank. B: C0004's 17 Sep 17:00 client-ledger snapshot is overstated by 90.00 and the firm's internal reconciliation used it. C: line 2 of acquirer batch AQ-EUR-20260922 states 1,238.12 against 1,283.12. A and B deliberately share date (17 Sep), currency (GBP) and magnitude (90.00): a decoy coincidence that must not be treated as a link.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | not applicable (no correction in this scenario) |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
