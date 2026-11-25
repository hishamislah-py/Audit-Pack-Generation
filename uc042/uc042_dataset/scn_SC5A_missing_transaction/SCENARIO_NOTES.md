> ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.

# Scenario 5a — Transaction missing (SC5A)

Spend `TX-0915-00009` (client C0002, 443.55, scheme batch `SB-GBP-20260915`) is removed from `transactions_2026-09.csv`. The settlement line that references it, the client snapshots and the bank records are unchanged.

C0002's 15 Sep roll-forward from transactions is therefore 443.55 above the snapshot. Engine limitation (E2): 2 exceptions for one cause.
