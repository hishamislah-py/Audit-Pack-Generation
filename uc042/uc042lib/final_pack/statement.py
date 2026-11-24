"""Reconciliation statement: a deterministic, plain-English attestation of what the engine's checks found (owner, 24 Nov
2026: "say all the checks match out ... it shouldn't be AI, it can be deterministic").

Input is only the stored per-check result counts; nothing is recalculated and no AI is involved. The same table and
wording are used by the Ringfence app (smartparser/webapp/statement.py, an identical copy) so the reconciliation page and
the analyst-edition PDF say the same thing.
"""
from __future__ import annotations

STATEMENT_VERSION = "reconciliation-statement/1.0"

# (key, area, checks, sentence when every result passed; {n} = result count of the counting check, the last element)
LINES = [
    ("evidence", "Evidence", ["V01-SCHEMA", "V01-PDF", "C14-COVER", "C01-COVER", "C07-COVER", "DQ23-STATEMENT", "DQ22-CONTINUITY"],
     "Every evidence file was readable and covered each reconciliation day.", None),
    ("internal", "Internal reconciliation", ["C04-REQUIREMENT", "C05-RESOURCE", "C06-DIFFERENCE"],
     "The safeguarding requirement and resource agreed on all {n} currency-days.", "C06-DIFFERENCE"),
    ("external", "External reconciliation", ["C07-BANK-EVIDENCE", "RC2-LEDGER", "C08-DIFFERENCE", "BC-VS-EOD"],
     "The firm's ledger agreed with the bank on all {n} account-days.", "C08-DIFFERENCE"),
    ("cashbank", "Cash book and bank", ["CASH-BANK-LINK", "BANK-CASH-LINK"],
     "Every cash-book entry matched a bank entry, and every bank entry matched the cash book.", None),
    ("settlement", "Settlement", ["C11-BATCH-ARITH", "C11-BATCH-BANK", "C11-TXN-LINE", "C11-BANK-ENTRY", "FUND-TOPUP"],
     "All {n} settlement batches agreed with their lines and with the bank.", "C11-BATCH-ARITH"),
    ("clients", "Client balances and transactions", ["CBAL-NONNEG", "CBAL-ROLLFWD", "RC4-DIRECT", "C09-ALLOCATION", "C12-REFUND",
                                                     "C13-CURRENCY"],
     "Client balances rolled forward correctly and every client transaction matched the bank.", None),
    ("governance", "Governance and records", ["C03-POLICY", "C03-POINT", "C10-DESIGNATION", "C16-GOVERNANCE", "C16-RETURN",
                                              "DISC-LOG"],
     "Account designation, policy, governance records and the discrepancy log were in order.", None),
]

TITLES = {
    "V01-SCHEMA": "file layout", "V01-PDF": "document readability", "C14-COVER": "client balance coverage",
    "C01-COVER": "internal reconciliation coverage", "C07-COVER": "external reconciliation coverage",
    "DQ23-STATEMENT": "bank statement completeness", "DQ22-CONTINUITY": "bank statement continuity",
    "C04-REQUIREMENT": "safeguarding requirement", "C05-RESOURCE": "safeguarding resource",
    "C06-DIFFERENCE": "internal reconciliation difference", "C07-BANK-EVIDENCE": "bank evidence",
    "RC2-LEDGER": "firm ledger balance", "C08-DIFFERENCE": "bank and ledger difference",
    "BC-VS-EOD": "bank confirmation against statement", "CASH-BANK-LINK": "cash-book entry without a bank entry",
    "BANK-CASH-LINK": "bank entry without a cash-book entry", "C11-BATCH-ARITH": "settlement batch arithmetic",
    "C11-BATCH-BANK": "settlement batch against bank", "C11-TXN-LINE": "settlement line against transaction",
    "C11-BANK-ENTRY": "unexplained bank entry", "FUND-TOPUP": "funding top-up", "CBAL-NONNEG": "negative client balance",
    "CBAL-ROLLFWD": "client balance roll-forward", "RC4-DIRECT": "client transaction against bank",
    "C09-ALLOCATION": "unallocated receipts", "C12-REFUND": "refunds", "C13-CURRENCY": "currency",
    "C03-POLICY": "reconciliation policy", "C03-POINT": "reconciliation point", "C10-DESIGNATION": "account designation",
    "C16-GOVERNANCE": "governance record", "C16-RETURN": "regulatory return", "DISC-LOG": "discrepancy log",
}


def _plural(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def build_statement(check_counts: dict, period_label: str, exceptions_total: int) -> dict:
    """check_counts: {check_id: {"PASS": n, "FAIL": n, "INSUFFICIENT_EVIDENCE": n, "NOT_APPLICABLE": n}} (stored counts).
    Returns {"version", "state": ALL_PASSED|FAILURES|INCOMPLETE, "headline", "summary", "lines": [{"key", "area",
    "state": PASS|FAIL|INCOMPLETE, "text"}], "note"}."""
    placed, lines = set(), []
    tot = {"PASS": 0, "FAIL": 0, "INSUFFICIENT_EVIDENCE": 0, "NOT_APPLICABLE": 0}
    for cc in check_counts.values():
        for k, v in cc.items():
            tot[k] = tot.get(k, 0) + int(v or 0)
    groups = [(k, area, ids, ok, cnt) for k, area, ids, ok, cnt in LINES]
    others = sorted(c for c in check_counts if not any(c in g[2] for g in groups))
    if others:
        groups.append(("other", "Other checks", others, "All other checks passed.", None))
    for key, area, ids, ok, counting in groups:
        present = [i for i in ids if i in check_counts]
        if not present:
            continue
        placed.update(present)
        fail = [i for i in present if int(check_counts[i].get("FAIL") or 0)]
        ins = [i for i in present if int(check_counts[i].get("INSUFFICIENT_EVIDENCE") or 0)]
        if not fail and not ins:
            n = sum(int(v or 0) for v in check_counts.get(counting, {}).values()) if counting else 0
            text = ok.format(n=f"{n:,}") if counting and n else ok.replace("all {n} ", "all ")
            lines.append({"key": key, "area": area, "state": "PASS", "text": text})
            continue
        parts = []
        if fail:
            nf = sum(int(check_counts[i]["FAIL"]) for i in fail)
            parts.append(f"{_plural(nf, 'result')} failed: " + ", ".join(f"{TITLES.get(i, i)} ({i})" for i in fail))
        if ins:
            ni = sum(int(check_counts[i]["INSUFFICIENT_EVIDENCE"]) for i in ins)
            parts.append(f"{_plural(ni, 'result')} could not be evaluated for lack of evidence: "
                         + ", ".join(f"{TITLES.get(i, i)} ({i})" for i in ins))
        lines.append({"key": key, "area": area, "state": "FAIL" if fail else "INCOMPLETE", "text": "; ".join(parts) + "."})
    n_checks, n_results = len(check_counts), sum(tot.values())
    passed_areas = sum(1 for x in lines if x["state"] == "PASS")
    if not lines:
        state, headline, summary = "INCOMPLETE", "No checks recorded", "The engine recorded no control results for this run."
    elif tot["FAIL"] == 0 and tot["INSUFFICIENT_EVIDENCE"] == 0 and not exceptions_total:
        state, headline = "ALL_PASSED", "Everything checks out"
        summary = (f"All {n_checks} checks passed across {n_results:,} control results. On the evidence submitted, the "
                   f"safeguarding position for {period_label} reconciles in full: no differences and no exceptions.")
    elif tot["FAIL"]:
        state, headline = "FAILURES", "Not everything checks out"
        summary = (f"{passed_areas} of {len(lines)} areas passed in full; {_plural(tot['FAIL'], 'control result')} failed "
                   f"out of {n_results:,}. {_plural(exceptions_total, 'exception')} " + ("needs" if exceptions_total == 1 else "need")
                   + " review.")
    else:
        state, headline = "INCOMPLETE", "Not everything could be checked"
        summary = (f"{passed_areas} of {len(lines)} areas passed in full; {_plural(tot['INSUFFICIENT_EVIDENCE'], 'control result')} "
                   "could not be evaluated with the evidence submitted.")
    return {"version": STATEMENT_VERSION, "state": state, "headline": headline, "summary": summary, "lines": lines,
            "note": "Generated from the engine's stored check results, not by AI. It covers the checks the engine ran on the "
                    "evidence submitted and is not an independent audit opinion."}
