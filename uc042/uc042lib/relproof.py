"""Evidence-bearing relationships (23 Nov 2026): the structured PROOF the engine keeps for every relationship it confirms.

Why: until now the engine recorded the evidence of a relationship check only when the check FAILED (a downgrade to
CANDIDATE or a REJECTED link). A successful confirmation left nothing behind except a one-line text, so downstream
consumers (the relationship register, investigations, the AI closing summary, the analyst) could not see WHY a link was
CONFIRMED - and the AI rejected a confirmed link it could not understand (TC06 01<->03, forensic report 23 Nov 2026).

A proof is plain data built from values the engine already computed; it never recalculates the reconciliation, never sets a
cause and never changes a status. It separates three things that must not be confused:
  faulty_record     the source record shown to be out of line (for example a client snapshot that fails its roll-forward)
  detection         where each exception was DETECTED (a different check, a different record) - different detection
                    records do NOT mean different causes
  not_established   what the relationship does not show, in particular WHY the faulty record is wrong (the underlying cause)

Fields (all present; empty when not applicable):
  rule                 the engine rule that confirmed the link
  relationship_type    see RELATIONSHIP_TYPES
  faulty_record        citation of the record shown to be out of line ("" when the rule does not identify one)
  quantities           [{name, value, record}] - the figures the confirmation rests on, as the engine computed them
  calculation          the comparison, written out with its figures
  result               EQUAL / SHARED_RECORD / SAME_REFERENCE / CONSECUTIVE_EQUAL ... (what the comparison found)
  chronology           [{date, event}] in date order
  requirement_effect   how the link affects the client-money requirement / resource (empty when it does not)
  corroboration        independent facts that point the same way (for example the next day's equal and opposite reversal)
  established          what the proof shows
  not_established      what it does not show (always includes the underlying cause when a faulty record is identified)
  missing_evidence     what would establish the rest
  limitations          caveats of the rule itself
  records              citations of every record the proof uses
"""

PROOF_VERSION = "uc042-relationship-proof/1.0"

RELATIONSHIP_TYPES = {
    "SHARED_REFERENCE": "the exceptions involve records carrying the same payment, batch or bank reference",
    "PERSISTENCE": "the same internal difference recurs on consecutive reconciliation days",
    "BALANCE_LINEAGE": "a record that fails one check sits inside the balance another failing check measures",
    "CAUSAL_PROPAGATION": "one faulty record produces both exceptions (its error propagates into a second result)",
    "SHARED_INPUT": "one recomputed result is a direct input to another failing result for the same scope",
    "TRANSACTION_LINEAGE": "a transaction-side discrepancy explains a client roll-forward failure exactly",
    "DUPLICATE_LINEAGE": "a duplicate record is inside the balance another check measures and equals its discrepancy",
    "TIMING_TRACE": "timing items behind a bank-ledger difference are shared with another exception",
    "SHARED_FAULTY_RECORD": "one record closes one failing result and opens the next, with equal and opposite errors",
    "AMOUNT_COMBINATION": "amounts of several records combine to another exception's difference (amounts only)",
    "COINCIDENCE": "same date, currency and amount with no shared record",
}

UNDERLYING_CAUSE_NOT_ESTABLISHED = ("why the faulty record is wrong (the underlying cause: for example a data-entry, system or "
                                    "process error) is not established by the records")


def make_proof(rule, relationship_type, *, faulty_record="", quantities=(), calculation="", result="", chronology=(),
               requirement_effect="", corroboration=(), established=(), not_established=(), missing_evidence=(),
               limitations=(), records=()):
    assert relationship_type in RELATIONSHIP_TYPES, relationship_type
    nots = list(not_established)
    if faulty_record and UNDERLYING_CAUSE_NOT_ESTABLISHED not in nots:
        nots.append(UNDERLYING_CAUSE_NOT_ESTABLISHED)
    return {"proof_version": PROOF_VERSION, "rule": rule, "relationship_type": relationship_type,
            "faulty_record": faulty_record or "",
            "quantities": [{"name": str(n), "value": str(v), "record": r or ""} for n, v, r in quantities],
            "calculation": calculation, "result": result,
            "chronology": [{"date": str(d), "event": e} for d, e in sorted(chronology, key=lambda t: str(t[0]))],
            "requirement_effect": requirement_effect, "corroboration": list(corroboration), "established": list(established),
            "not_established": nots, "missing_evidence": list(missing_evidence), "limitations": list(limitations),
            "records": [r for r in dict.fromkeys(records) if r]}


def has_proof(proof):
    """A CONFIRMED relationship is evidence-bearing only with a proof that names its comparison and at least one record."""
    return bool(proof) and bool(proof.get("result")) and bool(proof.get("records")) and bool(proof.get("established"))
