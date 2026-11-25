> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

# Scenario 5c — Refund counted twice (SC5C)

Refund `TX-0909-0R001` (C0002, 60.00, of spend `TX-0902-00044`) appears once in the transactions. The client ledger counted it twice, so C0002's snapshots are 60.00 higher from 9 Sep (16 days).

The firm's internal reconciliation used that ledger: the reported requirement is +60.00 and the reported difference is −60.00 (a shortfall) each day. Transactions, cash book and bank are unchanged.

Engine limitation (E2): 17 exceptions for one cause.
