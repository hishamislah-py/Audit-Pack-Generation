> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

# Scenario 2 — Settlement timing difference (SC2)

The firm recorded scheme settlement `SB-GBP-20260915` (debit 2,868.50) in its cash book and client balances at 15:00 on 15 Sep. The bank booked it at 08:00 on 16 Sep as `BE-GBP-0916-T01`, with the same reference and amount.

- The 15 Sep statement, 17:00 confirmation and external record show the bank balance 2,868.50 higher than the ledger.
- The 16 Sep figures agree again.
- The firm logged the difference as timing (`DL-0001`).

Unchanged: cash book, transactions, settlement batch and lines, client snapshots, internal records. Exact changes: `mutations.json`.

Engine limitation (E1): the validator detects the difference but cannot yet accept the clearing entry as timing evidence. See `answer_key.json` `target_outcome`.
