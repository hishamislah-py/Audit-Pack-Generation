"""Deterministic routing from actual engine output (exception root-cause kind, controls, links). No planted answers."""

ROUTES = ("bank_ledger_mismatch", "settlement_discrepancy", "missing_bank_evidence", "customer_balance_discrepancy",
          "unmatched_bank_entry", "unverified_relationship", "insufficient_evidence", "generic")

# Root-cause kind (text before the first "|") as produced by uc042lib.validate._group_exceptions.
KIND_ROUTE = {
    "BANK_LEDGER_DIFFERENCE": "bank_ledger_mismatch",
    "C11-BATCH-ARITH": "settlement_discrepancy", "C11-BATCH-BANK": "settlement_discrepancy",
    "CASH-BANK-LINK": "settlement_discrepancy", "FUND-TOPUP": "settlement_discrepancy",
    "MISSING_BANK_EVIDENCE": "missing_bank_evidence", "MISSING_FILE": "missing_bank_evidence",
    "EMPTY_FILE": "missing_bank_evidence", "WRONG_PERIOD": "missing_bank_evidence", "INVALID_FILE": "missing_bank_evidence",
    "CBAL-ROLLFWD": "customer_balance_discrepancy", "INTERNAL_DIFFERENCE": "customer_balance_discrepancy",
    "C04-REQUIREMENT": "customer_balance_discrepancy",
    "UNMATCHED_BANK_ENTRY": "unmatched_bank_entry", "C11-BANK-ENTRY": "unmatched_bank_entry", "BANK-CASH-LINK": "unmatched_bank_entry",
}


def root_kind(exception):
    return (exception.get("root_cause") or "").split("|")[0]


def route_for(exception, candidates, results):
    """Route for one exception.

    1. An exception that appears in an unverified candidate relationship (and is not in a confirmed group with its
       counterpart) is investigated on the unverified-relationship path, so both sides are examined and the link is
       handled as unverified.
    2. Otherwise the root-cause kind decides.
    3. Exceptions whose results are only INSUFFICIENT_EVIDENCE (and not a missing-file kind) take the insufficient path.
    4. Anything else falls back to the generic path.
    """
    if candidates:
        return "unverified_relationship"
    route = KIND_ROUTE.get(root_kind(exception))
    if route:
        return route
    outcomes = {r["outcome"] for r in results}
    if outcomes == {"INSUFFICIENT_EVIDENCE"}:
        return "insufficient_evidence"
    return "generic"
