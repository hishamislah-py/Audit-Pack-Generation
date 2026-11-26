# TC03 - Timing difference: acquirer settlement AQ-GBP-20260924 (5,495.05) recorded Thu 24 Sep, credited by the bank Fri 25 Sep

> ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from set_01_clean_baseline; all names, accounts, references and amounts are fictional.

The acquirer settlement for Thursday 24 Sep 2026 (AQ-GBP-20260924, net 5,495.05; settlement date 24 Sep per the acquirer report) was posted by the firm to its cash book at 14:00 on 24 Sep. The acquirer's funds reached the safeguarding account on Friday 25 Sep at 08:00, the next business day. At the 24 Sep 17:00 reconciliation point the bank is therefore 5,495.05 below the ledger. The firm reported the difference, claimed timing and logged it; the 25 Sep statement and 17:00 confirmation evidence the clearing, and at 25 Sep 17:00 bank and ledger agree.

| Path | Contents |
|---|---|
| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |
| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |
| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |
| `corrections/` | not applicable (no correction in this scenario) |
| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |

Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.
