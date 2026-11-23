"""Reconciliation enrichment v1 (UC-042 Workstream 3).

Deterministic duplicate detection, amount comparison with outlier-source identification, transaction lineage, timing
traceability, common-cause candidates and stricter exception correlation.

Activation: only with EngineRules(enrichment_v1=True) (validate.ENRICHED_RULES). With the default (approved) rules
nothing in this module runs and every engine output is byte-identical to the 17 Nov 2026 rules.

Principles
  * Financial values are exact Decimal comparisons of source records. Nothing is estimated, rounded or tolerated.
  * A relationship is CONFIRMED (and may join an investigation group) only when a shared source record or reference
    connects the exceptions AND the amounts reconcile exactly. A record link whose amounts do not reconcile is a
    CANDIDATE (listed, never grouped). An equal date, currency and amount with no shared record is a REJECTED
    coincidence. A date, an amount or a currency alone never links anything.
  * Nothing here sets a cause, resolves or closes an exception, or changes an exception status. Timing evidence
    explains a difference; it never resolves it.
  * Every relationship carries the source-record citations it rests on.
"""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from itertools import combinations

from .money import batch_net_signed, parse_unsigned, signed
from .relproof import make_proof
from .structure import parse_ts

PASS, FAIL, INSUF = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
ZERO = Decimal("0.00")
SCHEMA = "uc042-recon-enrichment/1.0"
VERSION = "enrichment-v1"
CORRELATION_VERSION = "deterministic-v2-enrichment"
MAX_SUBSET_LINES = 12
DUP_CASH, DUP_TXN = "DUPLICATE_CASHBOOK_ENTRY", "DUPLICATE_TRANSACTION"
CONFIRMED, CANDIDATE, REJECTED = "CONFIRMED", "CANDIDATE", "REJECTED"
CATEGORY = {DUP_CASH: "Duplicate cash-book entry (its bank entry is already matched)",
            DUP_TXN: "Duplicate transaction record (its bank entry is already matched)"}
EVIDENCE_CLASS = {"IN_WINDOW": "EVIDENCED", "UNVERIFIABLE": "SUSPECTED", "OUTSIDE_WINDOW": "NOT_EVIDENCED"}


def new_state():
    return {"schema": SCHEMA, "version": VERSION, "duplicates": [], "suspected_duplicates": [], "amount_comparisons": [],
            "relationships": [], "timing_traces": [], "common_causes": [], "unmatched_credits": [],
            "rejected_coincidences": [], "exceptions": []}


# --- small helpers --------------------------------------------------------------------------------------------------
def _result(v, check, scope):
    return next((r for r in v.results if r["check_id"] == check and r["scope"] == scope), None)


def _set_structured(r, key, value):
    s = dict(r.get("structured") or {})
    s[key] = value
    r["structured"] = s


def _client_sign(t):
    return 1 if t["direction"] == "CR" else -1


def _local_date(ts):
    return parse_ts(ts).astimezone(_lon()).date()


def _lon():
    from .validate import LON
    return LON


def _direction(diff, greater, less, equal="EQUAL"):
    return greater if diff > 0 else less if diff < 0 else equal


def _outlier(values):
    """values: [{source, record, amount}]. IDENTIFIED when >= 3 sources hold a value and exactly one differs from a
    value that at least two others agree on; otherwise UNDETERMINED (pairwise disagreement cannot name a source)."""
    if len(values) < 3:
        return {"status": "UNDETERMINED", "reason": f"only {len(values)} independent source(s); a pairwise disagreement cannot "
                                                    "identify which source is wrong"}
    counts = Counter(x["amount"] for x in values)
    if len(counts) == 2:
        (major, n_major), (minor, n_minor) = counts.most_common()
        if n_minor == 1 and n_major >= 2:
            odd = next(x for x in values if x["amount"] == minor)
            agree = sorted({x["source"] for x in values if x["amount"] == major})
            return {"status": "IDENTIFIED", "source": odd["source"], "record": odd["record"], "outlier_value": odd["amount"],
                    "agreed_value": major, "corroborating_sources": agree,
                    "reason": f"{odd['source']} {odd['record']} holds {odd['amount']}; {', '.join(agree)} agree on {major}"}
    return {"status": "UNDETERMINED", "reason": "sources do not reduce to one dissenting source against an agreeing majority: "
                                                + ", ".join(f"{x['source']}={x['amount']}" for x in values)}


def _comparison(check, scope, subject, values, a, b, label_greater, label_less):
    """A vs B structured comparison. values carry Decimal amounts; output carries strings."""
    diff = a - b
    vals = [dict(x, amount=str(x["amount"])) for x in values]
    return {"check_id": check, "scope": scope, "subject": subject, "values": vals, "difference": str(diff),
            "difference_basis": f"{values[0]['source']} - {values[1]['source']}" if len(values) > 1 else "",
            "direction": _direction(diff, label_greater, label_less), "outlier": _outlier(vals), "exception_id": ""}


def _snap_index(v):
    snaps = defaultdict(dict)
    for r in v.rows("IN-03"):
        snaps[(r["currency"], r["client_id"])][date.fromisoformat(r["recon_date"])] = r
    return snaps


def _window_of(v, snaps, ccy, client, ts):
    """(prev_row, cur_row) of the roll-forward window (prev point, cur point] containing ts, or None."""
    by_day = snaps.get((ccy, client), {})
    days = sorted(by_day)
    for prev, cur in zip(days, days[1:]):
        if v.point(prev) < ts <= v.point(cur):
            return by_day[prev], by_day[cur]
    return None


def _implied_txn_amount(v, snaps, t):
    """The movement the client snapshots imply for a transaction: cur - prev - other moves in its window, expressed as an
    unsigned amount in the transaction's direction. None if not determinable from usable evidence."""
    ts = parse_ts(t["executed_ts"])
    w = _window_of(v, snaps, t["currency"], t["client_id"], ts)
    if w is None:
        return None
    prev, cur = w
    if v.tainted("IN-03", currency=t["currency"], client=t["client_id"]) or v.tainted("IN-11", client=t["client_id"]):
        return None
    lo, hi = v.point(date.fromisoformat(prev["recon_date"])), v.point(date.fromisoformat(cur["recon_date"]))
    others = sum((signed(x["amount"], x["direction"], "client") for x in v.rows("IN-11")
                  if x["txn_id"] != t["txn_id"] and x["currency"] == t["currency"] and x["client_id"] == t["client_id"]
                  and lo < parse_ts(x["executed_ts"]) <= hi), ZERO)
    implied = (Decimal(cur["balance"]) - Decimal(prev["balance"]) - others) * _client_sign(t)
    if implied <= 0:
        return None
    return implied, [v.ref("IN-03", prev), v.ref("IN-03", cur)], f"{t['client_id']} snapshots {prev['recon_date']}->{cur['recon_date']}"


# --- A. duplicates (before exceptions are grouped) ------------------------------------------------------------------
def apply_record_checks(v):
    """Record-level enrichment, run after every control and before exceptions are grouped."""
    v.enrichment = new_state()
    _cashbook_duplicates(v)
    _transaction_duplicates(v)
    _suspected_card_duplicates(v)
    _amount_comparisons(v)


def _cashbook_duplicates(v):
    """Many-to-one: two or more cash-book rows whose reference links to the same single safeguarding bank entry."""
    if not v.rows("IN-10"):
        return
    by_ref = defaultdict(list)
    for e in v.rows("IN-09"):
        if e["account_id"] in v.sga:
            for ref in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
                by_ref[(e["account_id"], ref)].append(e)
    claims, entry = defaultdict(list), {}
    for c in v.rows("IN-10"):
        if c["entry_type"] == "OPENING_BALANCE":
            continue
        m = by_ref.get((c["account_id"], c["payment_reference"]), [])
        if len(m) == 1:
            claims[m[0]["bank_entry_id"]].append(c)
            entry[m[0]["bank_entry_id"]] = m[0]
    for eid in sorted(claims):
        rows = sorted(claims[eid], key=lambda c: (parse_ts(c["posted_ts"]), c["_line"]))
        if len(rows) < 2:
            continue
        b = entry[eid]
        bank_amt = signed(b["amount"], b["dc_indicator"], "bank")
        eff = {c["ledger_entry_id"]: signed(c["amount"], c["dc_indicator"], "cashbook") for c in rows}
        equal = [c for c in rows if eff[c["ledger_entry_id"]] == bank_amt and c["currency"] == b["currency"]]
        if not equal:
            total = sum(eff.values(), ZERO)
            v.enrichment["duplicates"].append({
                "source": "IN-10", "bank_entry_id": eid, "claimants": [c["ledger_entry_id"] for c in rows],
                "classification": "SPLIT_POSTING" if total == bank_amt else "MULTIPLE_CLAIMS_NO_EXACT_MATCH",
                "bank_amount": str(bank_amt), "claimants_total": str(total), "outcome_changed": False,
                "note": "no claimant equals the bank amount: no original can be identified; existing amount checks apply",
                "evidence": [v.ref("IN-09", b)] + [v.ref("IN-10", c) for c in rows]})
            continue
        original = equal[0]
        keys = ("account_id", "payment_reference", "amount", "dc_indicator", "entry_type", "currency")
        claimants = []
        for c in rows:
            if c is original:
                continue
            same = all(c[k] == original[k] for k in keys)
            info = {"source": "IN-10", "duplicate_record": c["ledger_entry_id"], "duplicate_of": original["ledger_entry_id"],
                    "bank_entry_id": eid, "reference": c["payment_reference"], "account_id": c["account_id"],
                    "classification": "EXACT_DUPLICATE" if same else "CONFLICTING_CLAIM",
                    "matched_on": "account + payment_reference -> one bank entry" + ("; amount, dc, entry_type, currency identical" if same else ""),
                    "ledger_effect": str(eff[c["ledger_entry_id"]]), "posted_ts": c["posted_ts"],
                    "original_posted_ts": original["posted_ts"], "outcome_changed": True, "exception_id": "",
                    "evidence": [v.ref("IN-10", c), v.ref("IN-10", original), v.ref("IN-09", b)]}
            r = _result(v, "CASH-BANK-LINK", c["ledger_entry_id"])
            if r is not None:
                r["outcome"], r["root_cause"] = FAIL, f"{DUP_CASH}|{c['ledger_entry_id']}"
                r["computed"], r["reported"] = str(eff[c["ledger_entry_id"]]), str(bank_amt)
                r["evidence"] = "; ".join(info["evidence"])
                r["note"] = (f"bank entry {eid} is already matched to {original['ledger_entry_id']}; this row claims it again "
                             f"({info['classification'].lower().replace('_', ' ')}); not matched")
                _set_structured(r, "duplicate", {k: info[k] for k in ("duplicate_of", "bank_entry_id", "classification",
                                                                        "matched_on", "ledger_effect")})
            claimants.append(c["ledger_entry_id"])
            v.enrichment["duplicates"].append(info)
        r0 = _result(v, "CASH-BANK-LINK", original["ledger_entry_id"])
        if r0 is not None:
            _set_structured(r0, "duplicate_claimants", claimants)


def _transaction_duplicates(v):
    """Many-to-one on the transaction side: LOAD_BANK / REDEMPTION rows sharing an end-to-end reference that matches
    exactly one safeguarding bank entry."""
    e2e = defaultdict(list)
    for e in v.rows("IN-09"):
        if e["end_to_end_ref"] and e["account_id"] in v.sga:
            e2e[e["end_to_end_ref"]].append(e)
    claims = defaultdict(list)
    for t in v.rows("IN-11"):
        if t["txn_type"] in ("LOAD_BANK", "REDEMPTION") and len(e2e.get(t["payment_reference"], [])) == 1:
            claims[t["payment_reference"]].append(t)
    for ref in sorted(claims):
        rows = sorted(claims[ref], key=lambda t: (parse_ts(t["executed_ts"]), t["_line"]))
        if len(rows) < 2:
            continue
        e = e2e[ref][0]
        want = lambda t: "C" if t["txn_type"] == "LOAD_BANK" else "D"
        equal = [t for t in rows if t["amount"] == e["amount"] and t["currency"] == e["currency"] and e["dc_indicator"] == want(t)]
        if not equal:
            v.enrichment["duplicates"].append({
                "source": "IN-11", "bank_entry_id": e["bank_entry_id"], "claimants": [t["txn_id"] for t in rows],
                "classification": "MULTIPLE_CLAIMS_NO_EXACT_MATCH", "outcome_changed": False,
                "note": "no transaction equals the bank entry: no original can be identified; existing checks apply",
                "evidence": [v.ref("IN-09", e)] + [v.ref("IN-11", t) for t in rows]})
            continue
        original = equal[0]
        keys = ("client_id", "txn_type", "amount", "currency", "direction", "payment_reference")
        for t in rows:
            if t is original:
                continue
            same = all(t[k] == original[k] for k in keys)
            info = {"source": "IN-11", "duplicate_record": t["txn_id"], "duplicate_of": original["txn_id"],
                    "bank_entry_id": e["bank_entry_id"], "reference": ref, "client_id": t["client_id"],
                    "classification": "EXACT_DUPLICATE" if same else "CONFLICTING_CLAIM",
                    "matched_on": "end-to-end reference -> one bank entry" + ("; client, type, amount, currency identical" if same else ""),
                    "client_effect": str(signed(t["amount"], t["direction"], "client")), "executed_ts": t["executed_ts"],
                    "outcome_changed": True, "exception_id": "",
                    "evidence": [v.ref("IN-11", t), v.ref("IN-11", original), v.ref("IN-09", e)]}
            r = _result(v, "RC4-DIRECT", t["txn_id"])
            if r is not None:
                r["outcome"], r["root_cause"] = FAIL, f"{DUP_TXN}|{t['txn_id']}"
                r["computed"], r["reported"] = t["amount"], e["amount"]
                r["evidence"] = "; ".join(info["evidence"])
                r["note"] = (f"bank entry {e['bank_entry_id']} is already matched to {original['txn_id']}; this transaction claims "
                             f"it again ({info['classification'].lower().replace('_', ' ')}); not matched")
                _set_structured(r, "duplicate", {k: info[k] for k in ("duplicate_of", "bank_entry_id", "classification",
                                                                        "matched_on", "client_effect")})
            v.enrichment["duplicates"].append(info)


def _suspected_card_duplicates(v):
    """A card transaction that is in no batch line, identical in every attribute to one that is: annotated only."""
    lines = defaultdict(list)
    for ln in v.rows("IN-13"):
        lines[ln["batch_id"]].append(ln)
    keys = ("client_id", "txn_type", "amount", "currency", "executed_ts", "settlement_batch_id", "direction")
    for r in v.results:
        if r["check_id"] != "C11-TXN-LINE" or r["outcome"] != FAIL or r["scope"] not in v.txn:
            continue
        t = v.txn[r["scope"]]
        twins = [o for o in v.rows("IN-11") if o["txn_id"] != t["txn_id"] and all(o[k] == t[k] for k in keys)
                 and sum(1 for x in lines.get(o["settlement_batch_id"], []) if x["txn_id"] == o["txn_id"]) == 1]
        if not twins:
            continue
        info = {"source": "IN-11", "record": t["txn_id"], "suspected_duplicate_of": twins[0]["txn_id"],
                "classification": "SUSPECTED_DUPLICATE",
                "basis": "identical client, type, amount, currency, execution time and batch; only the other transaction "
                         "appears in the batch lines. No shared reference exists, so this is not confirmed.",
                "evidence": [v.ref("IN-11", t), v.ref("IN-11", twins[0])], "exception_id": ""}
        _set_structured(r, "suspected_duplicate", {k: info[k] for k in ("suspected_duplicate_of", "classification", "basis")})
        v.enrichment["suspected_duplicates"].append(info)


# --- B. amount comparison and outlier source --------------------------------------------------------------------------
def _amount_comparisons(v):
    snaps = _snap_index(v)
    e2e = defaultdict(list)
    for e in v.rows("IN-09"):
        if e["end_to_end_ref"] and e["account_id"] in v.sga:
            e2e[e["end_to_end_ref"]].append(e)
    bank_by_ref = defaultdict(list)
    for e in v.rows("IN-09"):
        for ref in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
            bank_by_ref[(e["account_id"], ref)].append(e)
    cash_by_ref = defaultdict(list)
    for c in v.rows("IN-10"):
        if c["entry_type"] != "OPENING_BALANCE":
            cash_by_ref[(c["account_id"], c["payment_reference"])].append(c)
    txn_by_ref = defaultdict(list)
    for t in v.rows("IN-11"):
        if t["payment_reference"] and t["txn_type"] in ("LOAD_BANK", "REDEMPTION"):
            txn_by_ref[t["payment_reference"]].append(t)
    batches = {b["batch_id"]: b for b in v.rows("IN-12")}
    batch_by_ref = defaultdict(list)
    for b in v.rows("IN-12"):
        batch_by_ref[(b["account_id"], b["expected_bank_reference"])].append(b)
    lines = defaultdict(list)
    for ln in v.rows("IN-13"):
        lines[ln["batch_id"]].append(ln)
    cash = {c["ledger_entry_id"]: c for c in v.rows("IN-10")}
    out = v.enrichment["amount_comparisons"]

    def keep(r, comp):
        _set_structured(r, "comparison", comp)
        out.append(comp)

    for r in v.results:
        if r["outcome"] != FAIL or r["root_cause"].startswith((DUP_CASH, DUP_TXN)):
            continue
        check = r["check_id"]
        if check == "RC4-DIRECT" and r["scope"] in v.txn:
            t = v.txn[r["scope"]]
            hits = e2e.get(t["payment_reference"], [])
            if len(hits) != 1 or hits[0]["currency"] != t["currency"] or hits[0]["amount"] == t["amount"]:
                continue
            e = hits[0]
            vals = [{"source": "IN-11", "record": t["txn_id"], "amount": parse_unsigned(t["amount"]), "citation": v.ref("IN-11", t)},
                    {"source": "IN-09", "record": e["bank_entry_id"], "amount": parse_unsigned(e["amount"]), "citation": v.ref("IN-09", e)}]
            vals += [{"source": "IN-10", "record": c["ledger_entry_id"], "amount": parse_unsigned(c["amount"]), "citation": v.ref("IN-10", c)}
                     for c in cash_by_ref.get((e["account_id"], t["payment_reference"]), [])]
            imp = _implied_txn_amount(v, snaps, t)
            if imp:
                vals.append({"source": "IN-03", "record": imp[2], "amount": imp[0], "citation": "; ".join(imp[1])})
            keep(r, _comparison(check, r["scope"], {"txn_id": t["txn_id"], "reference": t["payment_reference"],
                                                    "client_id": t["client_id"], "currency": t["currency"],
                                                    "bank_entry_id": e["bank_entry_id"]},
                                vals, vals[0]["amount"], vals[1]["amount"], "TRANSACTION_GREATER_THAN_BANK",
                                "TRANSACTION_LESS_THAN_BANK"))
        elif check == "CASH-BANK-LINK" and r["scope"] in cash and r["reported"]:
            c = cash[r["scope"]]
            hits = bank_by_ref.get((c["account_id"], c["payment_reference"]), [])
            if len(hits) != 1:
                continue
            e = hits[0]
            vals = [{"source": "IN-10", "record": c["ledger_entry_id"], "amount": signed(c["amount"], c["dc_indicator"], "cashbook"),
                     "citation": v.ref("IN-10", c)},
                    {"source": "IN-09", "record": e["bank_entry_id"], "amount": signed(e["amount"], e["dc_indicator"], "bank"),
                     "citation": v.ref("IN-09", e)}]
            vals += [{"source": "IN-11", "record": t["txn_id"], "amount": signed(t["amount"], t["direction"], "client"),
                      "citation": v.ref("IN-11", t)} for t in txn_by_ref.get(c["payment_reference"], []) if t["currency"] == c["currency"]]
            vals += [{"source": "IN-12", "record": b["batch_id"], "amount": batch_net_signed(b["net_amount_reported"], b["direction"]),
                      "citation": v.ref("IN-12", b)} for b in batch_by_ref.get((c["account_id"], c["payment_reference"]), [])]
            keep(r, _comparison(check, r["scope"], {"ledger_entry_id": c["ledger_entry_id"], "reference": c["payment_reference"],
                                                    "account_id": c["account_id"], "bank_entry_id": e["bank_entry_id"]},
                                vals, vals[0]["amount"], vals[1]["amount"], "LEDGER_GREATER_THAN_BANK", "LEDGER_LESS_THAN_BANK"))
        elif check == "C11-BATCH-BANK" and r["scope"] in batches and r["reported"]:
            b = batches[r["scope"]]
            hits = bank_by_ref.get((b["account_id"], b["expected_bank_reference"]), [])
            if len(hits) != 1:
                continue
            e, ls = hits[0], lines.get(b["batch_id"], [])
            vals = [{"source": "IN-12", "record": b["batch_id"], "amount": batch_net_signed(b["net_amount_reported"], b["direction"]),
                     "citation": v.ref("IN-12", b)},
                    {"source": "IN-09", "record": e["bank_entry_id"], "amount": signed(e["amount"], e["dc_indicator"], "bank"),
                     "citation": v.ref("IN-09", e)}]
            if ls:
                vals.append({"source": "IN-13", "record": f"{len(ls)} lines of {b['batch_id']}",
                             "amount": sum((signed(x["amount"], x["dc_indicator"], "settlement") for x in ls), ZERO),
                             "citation": f"{v.ref('IN-13')}#L{ls[0]['_line']}-L{ls[-1]['_line']}"})
            vals += [{"source": "IN-10", "record": c["ledger_entry_id"], "amount": signed(c["amount"], c["dc_indicator"], "cashbook"),
                      "citation": v.ref("IN-10", c)} for c in cash_by_ref.get((b["account_id"], b["expected_bank_reference"]), [])]
            keep(r, _comparison(check, r["scope"], {"batch_id": b["batch_id"], "reference": b["expected_bank_reference"],
                                                    "account_id": b["account_id"], "bank_entry_id": e["bank_entry_id"]},
                                vals, vals[0]["amount"], vals[1]["amount"], "BATCH_GREATER_THAN_BANK", "BATCH_LESS_THAN_BANK"))
        elif check == "C11-BATCH-ARITH" and r["scope"] in batches:
            b, ls = batches[r["scope"]], lines.get(r["scope"], [])
            mism, missing = [], []
            for x in ls:
                if x["line_type"] not in ("TXN", "REFUND"):
                    continue
                t = v.txn.get(x["txn_id"])
                if t is None:
                    missing.append({"line_id": x["line_id"], "txn_id": x["txn_id"], "amount": x["amount"], "dc_indicator": x["dc_indicator"],
                                    "client_effect": str(signed(x["amount"], x["dc_indicator"], "settlement")),
                                    "citation": v.ref("IN-13", x)})
                    continue
                if t["amount"] == x["amount"]:
                    continue
                header_total = parse_unsigned(b["gross_amount"] if x["line_type"] == "TXN" else b["total_adjustments"])
                others = sum((parse_unsigned(y["amount"]) for y in ls if y["line_type"] == x["line_type"] and y is not x), ZERO)
                vals = [{"source": "IN-13", "record": x["line_id"], "amount": parse_unsigned(x["amount"]), "citation": v.ref("IN-13", x)},
                        {"source": "IN-11", "record": t["txn_id"], "amount": parse_unsigned(t["amount"]), "citation": v.ref("IN-11", t)},
                        {"source": "IN-12", "record": f"{b['batch_id']} header implied", "amount": header_total - others,
                         "citation": v.ref("IN-12", b)}]
                comp = _comparison(check, r["scope"], {"batch_id": b["batch_id"], "line_id": x["line_id"], "txn_id": t["txn_id"],
                                                       "client_id": t["client_id"], "currency": b["currency"]},
                                   vals, vals[0]["amount"], vals[1]["amount"], "LINE_GREATER_THAN_TRANSACTION",
                                   "LINE_LESS_THAN_TRANSACTION")
                mism.append(comp)
                out.append(comp)
            if mism or missing:
                _set_structured(r, "line_comparison", {"line_mismatches": mism, "missing_transactions": missing})
        elif check == "CBAL-ROLLFWD" and r["computed"] and r["reported"]:
            diff = Decimal(r["computed"]) - Decimal(r["reported"])
            comp = {"check_id": check, "scope": r["scope"], "subject": {"scope": r["scope"]},
                    "values": [{"source": "IN-03+IN-11", "record": "roll-forward", "amount": r["computed"]},
                               {"source": "IN-03", "record": "snapshot", "amount": r["reported"]}],
                    "difference": str(diff), "difference_basis": "roll-forward - snapshot",
                    "direction": _direction(diff, "ROLL_FORWARD_GREATER_THAN_SNAPSHOT", "ROLL_FORWARD_LESS_THAN_SNAPSHOT"),
                    "outlier": {"status": "UNDETERMINED", "reason": "a roll-forward failure alone cannot say whether the snapshot or a "
                                                                    "transaction is wrong; see relationships"}, "exception_id": ""}
            keep(r, comp)
        elif check in ("C04-REQUIREMENT", "C06-DIFFERENCE", "RC2-LEDGER", "C07-BANK-EVIDENCE", "C08-DIFFERENCE") \
                and _is_amount(r["computed"]) and _is_amount(r["reported"]):
            diff = Decimal(r["computed"]) - Decimal(r["reported"])
            keep(r, {"check_id": check, "scope": r["scope"], "subject": {"scope": r["scope"]},
                     "values": [{"source": "recomputed", "record": check, "amount": r["computed"]},
                                {"source": "reported", "record": check, "amount": r["reported"]}],
                     "difference": str(diff), "difference_basis": "recomputed - reported",
                     "direction": _direction(diff, "RECOMPUTED_GREATER_THAN_REPORTED", "RECOMPUTED_LESS_THAN_REPORTED",
                                             "RECOMPUTED_EQUALS_REPORTED_NON_ZERO"),
                     "outlier": {"status": "UNDETERMINED", "reason": "recomputed vs reported comparison"}, "exception_id": ""})
        elif check == "C05-RESOURCE" and r.get("structured", {}).get("item_a_reported"):
            s = r["structured"]
            diff = Decimal(s["item_a"]) - Decimal(s["item_a_reported"])
            keep(r, {"check_id": check, "scope": r["scope"], "subject": {"scope": r["scope"]},
                     "values": [{"source": "IN-10", "record": "item A recomputed", "amount": s["item_a"]},
                                {"source": "IN-05", "record": "item A reported", "amount": s["item_a_reported"]}],
                     "difference": str(diff), "difference_basis": "item A recomputed - item A reported",
                     "direction": _direction(diff, "RECOMPUTED_GREATER_THAN_REPORTED", "RECOMPUTED_LESS_THAN_REPORTED"),
                     "outlier": {"status": "UNDETERMINED", "reason": "recomputed vs reported comparison"}, "exception_id": ""})


def _is_amount(text):
    try:
        Decimal(text)
        return bool(text) and text.replace("-", "").replace(".", "").isdigit()
    except Exception:
        return False


# --- exception-level annotations (after grouping, before correlation) ---------------------------------------------
def duplicate_exception_scope(v, kind, key):
    """(account, [date], amount) for a duplicate root cause, or None."""
    if kind == DUP_CASH:
        c = next((c for c in v.rows("IN-10") if c["ledger_entry_id"] == key), None)
        if c:
            return c["account_id"], [_local_date(c["posted_ts"]).isoformat()], str(signed(c["amount"], c["dc_indicator"], "cashbook"))
    if kind == DUP_TXN:
        t = v.txn.get(key)
        if t:
            acct = next((a for a in v.sga if v.ccy_of.get(a) == t["currency"]), "")
            return acct, [_local_date(t["executed_ts"]).isoformat()], str(signed(t["amount"], t["direction"], "client"))
    return None


def annotate_exceptions(v):
    """G-15: an unmatched safeguarding CREDIT is a potential unrecorded receipt (possible requirement understatement)."""
    entry = {e["bank_entry_id"]: e for e in v.rows("IN-09")}
    for x in v.exceptions:
        kind, _, key = x["root_cause"].partition("|")
        if kind != "UNMATCHED_BANK_ENTRY" or key not in entry:
            continue
        e = entry[key]
        if e["account_id"] not in v.sga or e["dc_indicator"] != "C":
            continue
        flag = (f"POTENTIAL_UNRECORDED_RECEIPT: possible requirement understatement up to {e['amount']} {e['currency']} "
                "(credit absent from the unallocated register and client records; C04 sees IN-03 and IN-04 only); not allocated")
        x["flags"] = "; ".join(filter(None, [x["flags"], flag]))
        v.enrichment["unmatched_credits"].append({
            "exception_id": x["exception_id"], "bank_entry_id": key, "account_id": e["account_id"], "currency": e["currency"],
            "amount": e["amount"], "booking_ts": e["booking_ts"], "reference": e["end_to_end_ref"] or e["bank_reference"],
            "classification": "POTENTIAL_UNIDENTIFIED_RECEIPT", "potential_requirement_understatement": e["amount"],
            "requirement_basis": "C04 recomputes the requirement from IN-03 snapshots and open IN-04 receipts only; a receipt of "
                                 "relevant funds recorded in neither cannot raise it",
            "searched_sources": ["IN-10.payment_reference", "IN-11.payment_reference", "IN-04.bank_reference",
                                 "IN-12.expected_bank_reference", "TOPUP reference"],
            "must_not": "allocate the receipt to a client without evidence", "evidence": [v.ref("IN-09", e)]})


# --- D/E/F. correlation ---------------------------------------------------------------------------------------------
class CorrelationContext:
    """Evidence-backed relationships between exceptions, computed once before validate links them."""

    def __init__(self, v, exc, rows_of):
        self.v, self.exc, self.rows_of = v, exc, rows_of
        self.ids = [x["exception_id"] for x in exc]
        self.by_id = {x["exception_id"]: x for x in exc}
        self.kind = {x["exception_id"]: x["root_cause"].split("|")[0] for x in exc}
        self.eid_of_root = {x["root_cause"]: x["exception_id"] for x in exc}
        self.relationships, self._links, self.timing_traces = [], [], []
        self.txn_explained = set()
        self._snapshot_proofs = {}
        self.snaps = _snap_index(v)
        self.batches = {b["batch_id"]: b for b in v.rows("IN-12")}
        self.lines = defaultdict(list)
        for ln in v.rows("IN-13"):
            self.lines[ln["batch_id"]].append(ln)
        self.cash = {c["ledger_entry_id"]: c for c in v.rows("IN-10")}
        self.entries = {e["bank_entry_id"]: e for e in v.rows("IN-09")}
        self.cbal = {i: self._cbal_info(i) for i in self.ids if self.kind[i] == "CBAL-ROLLFWD"}
        self.cbal = {i: c for i, c in self.cbal.items() if c}
        self.records = {i: self._records(i) for i in self.ids}
        self._transaction_lineage()
        self._duplicate_lineage()
        self._timing_lineage()
        self._snapshot_lineage()

    # helpers
    def _rel(self, a, b, link_type, strength, basis, cites, amounts=None, shared=(), rtype=None, proof=None):
        # rtype / proof (evidence-bearing relationships, 23 Nov 2026): the relationship type and, for a CONFIRMED link, the
        # structured proof of the confirmation (uc042lib.relproof); for CANDIDATE / REJECTED, the comparison that failed
        self.relationships.append({"exception_ids": sorted([a, b]), "link_type": link_type, "strength": strength,
                                   "basis": basis, "shared_records": list(shared), "amounts": amounts or {},
                                   "evidence": [c for c in cites if c], "relationship_type": rtype, "proof": proof})
        if strength == CONFIRMED and a != b:
            self._links.append((a, b, link_type, basis, [c for c in cites if c]))

    def _first(self, i, check):
        return next((r for r in self.rows_of[i] if r["check_id"] == check and r["outcome"] == FAIL), None)

    def _cbal_info(self, i):
        r = self._first(i, "CBAL-ROLLFWD")
        if r is None or not r["computed"] or not r["reported"]:
            return None
        ccy, rest = r["scope"].split("/")
        client, cur = rest.split(" ")
        cur = date.fromisoformat(cur)
        days = sorted(self.snaps.get((ccy, client), {}))
        prev = max((d for d in days if d < cur), default=None)
        if prev is None:
            return None
        return {"ccy": ccy, "client": client, "cur": cur, "prev": prev, "lo": self.v.point(prev), "hi": self.v.point(cur),
                "diff": Decimal(r["computed"]) - Decimal(r["reported"]),
                "cites": [self.v.ref("IN-03", self.snaps[(ccy, client)][prev]), self.v.ref("IN-03", self.snaps[(ccy, client)][cur])]}

    def _records(self, i):
        recs = set()
        for r in self.rows_of[i]:
            c, s = r["check_id"], r["scope"]
            if c in ("CASH-BANK-LINK",) and s in self.cash:
                recs.add(("IN-10", s))
            elif c in ("BANK-CASH-LINK", "C11-BANK-ENTRY") and s in self.entries:
                recs.add(("IN-09", s))
            elif c in ("C11-BATCH-BANK", "C11-BATCH-ARITH", "FUND-TOPUP") and s in self.batches:
                recs.add(("IN-12", s))
            elif c in ("RC4-DIRECT", "C11-TXN-LINE", "C12-REFUND") and s in self.v.txn:
                recs.add(("IN-11", s))
        if i in self.cbal:
            ci = self.cbal[i]
            recs |= {("IN-03", self.snaps[(ci["ccy"], ci["client"])][d]["snapshot_id"]) for d in (ci["prev"], ci["cur"])}
        return recs

    # L4 transaction lineage (G-08)
    def _transaction_lineage(self):
        discs = []
        for i in self.ids:
            kind, _, key = self.by_id[i]["root_cause"].partition("|")
            if kind == DUP_TXN and key in self.v.txn:
                t = self.v.txn[key]
                discs.append((i, t, signed(t["amount"], t["direction"], "client"), f"duplicate transaction {key}"))
            for r in self.rows_of[i]:
                comp = (r.get("structured") or {}).get("comparison")
                if r["check_id"] == "RC4-DIRECT" and comp and comp.get("subject", {}).get("txn_id") in self.v.txn:
                    t = self.v.txn[comp["subject"]["txn_id"]]
                    discs.append((i, t, _client_sign(t) * Decimal(comp["difference"]),
                                  f"transaction {t['txn_id']} differs from bank entry {comp['subject']['bank_entry_id']} by {comp['difference']}"))
                lc = (r.get("structured") or {}).get("line_comparison")
                if r["check_id"] == "C11-BATCH-ARITH" and lc:
                    for m in lc["line_mismatches"]:
                        t = self.v.txn.get(m["subject"]["txn_id"])
                        if t:
                            discs.append((i, t, _client_sign(t) * -Decimal(m["difference"]),
                                          f"transaction {t['txn_id']} differs from settlement line {m['subject']['line_id']} by "
                                          f"{-Decimal(m['difference'])}"))
        targets = defaultdict(list)
        for d in discs:
            t, ts = d[1], parse_ts(d[1]["executed_ts"])
            for y, ci in self.cbal.items():
                if (ci["ccy"], ci["client"]) == (t["currency"], t["client_id"]) and ci["lo"] < ts <= ci["hi"]:
                    targets[y].append(d)
        for y in sorted(targets, key=self.ids.index):
            ds, ci = targets[y], self.cbal[y]
            total = sum((d[2] for d in ds), ZERO)
            ok = total == ci["diff"]
            if ok:
                self.txn_explained.add(y)
            for i, t, delta, what in ds:
                basis = (f"{what}; {t['txn_id']} is in {ci['client']}'s roll-forward {ci['prev']}->{ci['cur']}, whose difference "
                         f"(roll-forward - snapshot) is {ci['diff']}" +
                         (" — equal: the transaction-side discrepancy explains the roll-forward failure" if ok else
                          f" — not equal to the transaction-side discrepancy ({total}): unreconciled"))
                tref = self.v.ref("IN-11", t)
                proof = make_proof(
                    "L4 TRANSACTION LINEAGE (G-08)", "TRANSACTION_LINEAGE", faulty_record=tref if ok else "",
                    result="EQUAL" if ok else "NOT_EQUAL",
                    quantities=[(f"transaction-side discrepancy ({what})", delta, tref)]
                    + ([("transaction-side discrepancies in the window, total", total, "")] if len(ds) > 1 else [])
                    + [(f"{ci['client']} roll-forward difference {ci['prev']}->{ci['cur']} (roll-forward - snapshot)", ci["diff"], ci["cites"][1])],
                    calculation=(f"{t['txn_id']} (executed {t['executed_ts']}) is inside {ci['client']}'s roll-forward window "
                                 f"{ci['prev']} 17:00 -> {ci['cur']} 17:00; transaction-side discrepancy {total} vs roll-forward "
                                 f"difference {ci['diff']}: " + ("equal" if ok else "not equal")),
                    chronology=[(t["executed_ts"][:10], f"{t['txn_id']} executed ({i})"),
                                (ci["cur"], f"{ci['client']} roll-forward fails by {ci['diff']} ({y})")],
                    established=[f"{t['txn_id']} is the record behind both {i} and {y}"] + (
                        [f"its discrepancy ({total}) equals {ci['client']}'s roll-forward difference ({ci['diff']}), so "
                         f"{ci['client']}'s snapshot is consistent with the bank and the transaction record is the one out of line"]
                        if ok else []),
                    not_established=[] if ok else ["that the transaction accounts for the whole roll-forward difference"],
                    missing_evidence=["the corrected transaction amount from the transaction system"] if ok else
                    ["the other movements in the roll-forward window"],
                    records=[tref] + ci["cites"])
                self._rel(i, y, "L4 TRANSACTION LINEAGE", CONFIRMED if ok else CANDIDATE, basis,
                          [tref] + ci["cites"], {"transaction_side": str(total), "roll_forward_difference": str(ci["diff"])},
                          [("IN-11", t["txn_id"])], "TRANSACTION_LINEAGE", proof)

    # L6 duplicate lineage (G-05)
    def _duplicate_lineage(self):
        dups = defaultdict(list)
        for d in self.v.enrichment["duplicates"]:
            if d["source"] == "IN-10" and d.get("outcome_changed") and d["duplicate_record"] in self.cash:
                c = self.cash[d["duplicate_record"]]
                dups[c["account_id"]].append((parse_ts(c["posted_ts"]), Decimal(d["ledger_effect"]), c))
        if not dups:
            return
        acct_of_ccy = {self.v.ccy_of[a]: a for a in self.v.sga}
        for i in self.ids:
            kind, _, key = self.by_id[i]["root_cause"].partition("|")
            if kind != DUP_CASH or key not in self.cash:
                continue
            c = self.cash[key]
            acct, posted = c["account_id"], parse_ts(c["posted_ts"])
            for y in self.ids:
                if y == i:
                    continue
                ky, parts = self.kind[y], self.by_id[y]["root_cause"].split("|")
                measure, d = None, None
                if ky == "BANK_LEDGER_DIFFERENCE" and parts[1] == acct:
                    d = date.fromisoformat(parts[2])
                    measures = [-Decimal(parts[3])]
                elif ky == "INTERNAL_DIFFERENCE" and acct_of_ccy.get(parts[1].split("/")[1]) == acct:
                    d = date.fromisoformat(parts[1].split("/")[0])
                    r = self._first(y, "C06-DIFFERENCE")
                    measures = [Decimal(r["computed"]) - Decimal(r["reported"]), Decimal(r["computed"])] if r else []
                elif ky == "C05-RESOURCE" and acct_of_ccy.get(parts[1].split("/")[1]) == acct:
                    d = date.fromisoformat(parts[1].split("/")[0])
                    r = self._first(y, "C05-RESOURCE")
                    s = (r or {}).get("structured") or {}
                    measures = [Decimal(s["item_a"]) - Decimal(s["item_a_reported"])] if s.get("item_a_reported") else []
                elif ky == "RC2-LEDGER" and parts[1].split("/")[1] == acct:
                    d = date.fromisoformat(parts[1].split("/")[0])
                    r = self._first(y, "RC2-LEDGER")
                    measures = [Decimal(r["computed"]) - Decimal(r["reported"])] if r else []
                else:
                    continue
                pt = self.v.point(d)
                if posted > pt or not measures:
                    continue
                total = sum((e for ts, e, _ in dups[acct] if ts <= pt), ZERO)
                ok = total in measures
                cref, yref = self.v.ref("IN-10", c), (self.rows_of[y][0]["evidence"].split(";")[0]).strip()
                proof = make_proof(
                    "L6 DUPLICATE LINEAGE (G-05)", "DUPLICATE_LINEAGE", faulty_record=cref if ok else "",
                    result="EQUAL" if ok else "NOT_EQUAL",
                    quantities=[(f"ledger effect of duplicate rows on {acct} up to {d} 17:00", total, cref)]
                    + [(f"{ky} discrepancy measured by {y}", m, yref) for m in measures],
                    calculation=(f"duplicate {key} posted {c['posted_ts']} (before the {d} 17:00 point); duplicate effect {total} vs "
                                 f"{y}'s discrepancy {' or '.join(map(str, measures))}: " + ("equal" if ok else "not equal")),
                    chronology=[(c["posted_ts"][:10], f"duplicate cash-book row {key} posted ({i})"),
                                (d, f"{ky} on {acct} measures a discrepancy ({y})")],
                    requirement_effect=(f"the duplicate inflates the {acct} cash-book balance (item A of the resource)"
                                        if ky in ("INTERNAL_DIFFERENCE", "C05-RESOURCE") else ""),
                    established=[f"duplicate cash-book row {key} is inside the {acct} ledger balance {y} measures"]
                    + ([f"its effect ({total}) equals {y}'s discrepancy"] if ok else []),
                    not_established=["why the row was posted twice"] if ok else ["that the duplicate accounts for the discrepancy"],
                    missing_evidence=["the cash-book posting log for the duplicated row"],
                    records=[cref, yref])
                self._rel(i, y, "L6 DUPLICATE LINEAGE", CONFIRMED if ok else CANDIDATE,
                          f"duplicate cash-book row {key} (ledger effect {total if len(dups[acct]) > 1 else Decimal(dups[acct][0][1])}) is "
                          f"inside the {acct} ledger at the {d} point used by this check; its discrepancy "
                          + ("equals the duplicate's effect" if ok else f"({', '.join(map(str, measures))}) does not equal it ({total})"),
                          [cref, yref],
                          {"duplicate_effect": str(total), "check_discrepancy": [str(m) for m in measures]}, [("IN-10", key)],
                          "DUPLICATE_LINEAGE", proof)

    # L5 timing trace (G-12) and traceability record
    def _timing_lineage(self):
        v = self.v
        batch_by_ref = defaultdict(list)
        for b in v.rows("IN-12"):
            batch_by_ref[(b["account_id"], b["expected_bank_reference"])].append(b)
        for i in self.ids:
            if self.kind[i] != "BANK_LEDGER_DIFFERENCE":
                continue
            _, acct, d0, amount = self.by_id[i]["root_cause"].split("|")
            d0, amount = date.fromisoformat(d0), Decimal(amount)
            items = v.timing_items(acct, d0)
            erl = f"ERL-{acct}-{d0:%Y%m%d}"
            claimed = any(e["recon_date"] == str(d0) and e["account_id"] == acct and e["timing_difference_claimed"] == "true"
                          for e in v.rows("IN-06"))
            logged_timing = [x["discrepancy_id"] for x in v.rows("IN-14") if x["recon_ref"] == erl and x.get("cause_category", "") == "TIMING"]
            relevant = [it for it in items if it["status"] in ("IN_WINDOW", "UNVERIFIABLE")]
            explained = sum((it["effect"] for it in relevant), ZERO)
            covers = bool(relevant) and explained == amount
            trace_items = []
            for it in items:
                c, b = it["ledger_row"], it["bank_row"]
                ref = c["payment_reference"]
                batch = (batch_by_ref.get((acct, ref)) or [None])[0]
                bline = self.lines.get(batch["batch_id"], []) if batch else []
                bank_res = _result(v, "C11-BATCH-BANK", batch["batch_id"]) if batch else None
                trace_items.append({
                    "ledger_entry_id": c["ledger_entry_id"], "posted_ts": c["posted_ts"], "bank_entry_id": b["bank_entry_id"] if b else "",
                    "booked_ts": b["booking_ts"] if b else "", "reference": ref, "effect_on_difference": str(it["effect"]),
                    "cleared_or_expected": str(it["later"]), "item_status": it["status"],
                    "evidence_class": EVIDENCE_CLASS[it["status"]],
                    "batch": ({"batch_id": batch["batch_id"], "cycle_date": batch["cycle_date"], "settlement_date": batch["settlement_date"],
                               "net": str(batch_net_signed(batch["net_amount_reported"], batch["direction"])),
                               "lines": len(bline), "txn_ids": [x["txn_id"] for x in bline if x["txn_id"]][:50],
                               "bank_booking_lag": ((bank_res or {}).get("structured") or {}).get("booking_lag_business_days")}
                              if batch else None),
                    "evidence": [v.ref("IN-10", c)] + ([v.ref("IN-09", b)] if b else []) + ([v.ref("IN-12", batch)] if batch else [])})
            klass = ("EVIDENCED" if any(t["evidence_class"] == "EVIDENCED" for t in trace_items) and covers else
                     "PARTIALLY_EVIDENCED" if any(t["evidence_class"] == "EVIDENCED" for t in trace_items) else
                     "SUSPECTED" if any(t["evidence_class"] == "SUSPECTED" for t in trace_items) else
                     "CLAIMED_ONLY" if (claimed or logged_timing) else "NONE")
            if klass == "NONE":
                continue  # no timing item and no timing claim: nothing to trace
            related = []
            for it in relevant:
                c, b = it["ledger_row"], it["bank_row"]
                keys = {("IN-10", c["ledger_entry_id"])} | ({("IN-09", b["bank_entry_id"])} if b else set()) | \
                    {("IN-12", bb["batch_id"]) for bb in batch_by_ref.get((acct, c["payment_reference"]), [])}
                for y in self.ids:
                    shared = sorted(self.records[y] & keys)
                    if y != i and shared:
                        related.append(y)
                        tcites = [v.ref("IN-10", c)] + ([v.ref("IN-09", b)] if b else [])
                        proof = make_proof(
                            "L5 TIMING TRACE (G-12)", "TIMING_TRACE", result="EQUAL" if covers else "PARTIAL",
                            quantities=[(f"bank-ledger difference {acct} {d0}", amount, ""),
                                        ("explained by timing items in window", explained, tcites[0])],
                            calculation=f"timing items in window explain {explained} of the {d0} difference {amount}: "
                                        + ("the whole difference" if covers else "part of it"),
                            chronology=[(c["posted_ts"][:10], f"ledger entry {c['ledger_entry_id']} posted")]
                            + ([(b["booking_ts"][:10], f"bank entry {b['bank_entry_id']} booked")] if b else []),
                            established=[f"{i} and {y} share the timing record(s) {', '.join(f'{s}:{k}' for s, k in shared)}"],
                            not_established=["timing evidence explains a difference; it never resolves it"],
                            records=tcites)
                        self._rel(i, y, "L5 TIMING TRACE", CONFIRMED if covers else CANDIDATE,
                                  f"timing item {c['ledger_entry_id']}" + (f" / {b['bank_entry_id']}" if b else "") +
                                  f" (ref {c['payment_reference']}, {EVIDENCE_CLASS[it['status']].lower()}) is behind the {d0} "
                                  f"difference of {acct}" + ("; the timing items account for the whole difference" if covers else
                                                             f"; timing items account for {explained} of {amount}"),
                                  [v.ref("IN-10", c)] + ([v.ref("IN-09", b)] if b else []),
                                  {"difference": str(amount), "explained_by_items": str(explained)}, shared)
            self.timing_traces.append({
                "exception_id": i, "account_id": acct, "date": str(d0), "difference": str(amount), "evidence_class": klass,
                "explained_by_items": str(explained), "residual": str(amount - explained), "items": trace_items,
                "timing_claimed_by_preparer": claimed, "discrepancy_log_timing_entries": logged_timing,
                "claim_is_not_evidence": True, "related_exception_ids": sorted(set(related), key=self.ids.index),
                "exception_status": self.by_id[i]["status"], "evidence_status": self.by_id[i].get("evidence_status", ""),
                "resolves_exception": False,
                "note": "timing evidence explains; it never resolves or closes the exception (awaiting human review)"})

    # L7 snapshot lineage
    def _snapshot_lineage(self):
        for y1, a in self.cbal.items():
            for y2, b in self.cbal.items():
                if (a["ccy"], a["client"]) != (b["ccy"], b["client"]) or b["prev"] != a["cur"]:
                    continue
                snap = self.snaps[(a["ccy"], a["client"])][a["cur"]]
                if y1 in self.txn_explained or y2 in self.txn_explained:
                    continue
                ok = a["diff"] != ZERO and b["diff"] == -a["diff"]
                sref = self.v.ref("IN-03", snap)
                proof = make_proof(
                    "L7 SNAPSHOT LINEAGE", "SHARED_FAULTY_RECORD", faulty_record=sref if ok else "",
                    result="EQUAL_AND_OPPOSITE" if ok else "NOT_REVERSED",
                    quantities=[(f"{a['client']} roll-forward difference {a['prev']}->{a['cur']} (roll-forward - snapshot)", a["diff"], sref),
                                (f"{a['client']} roll-forward difference {b['prev']}->{b['cur']} (roll-forward - snapshot)", b["diff"], sref),
                                (f"snapshot {snap['snapshot_id']} balance", snap["balance"], sref)],
                    calculation=(f"snapshot {snap['snapshot_id']} closes the {a['prev']}->{a['cur']} roll-forward (difference {a['diff']}) "
                                 f"and opens the {b['prev']}->{b['cur']} roll-forward (difference {b['diff']}); "
                                 + (f"{a['diff']} + {b['diff']} = 0.00: equal and opposite" if ok else "they do not reverse")),
                    chronology=[(a["cur"], f"{a['client']}'s snapshot does not match its roll-forward ({y1})"),
                                (b["cur"], f"the next roll-forward, opened from that snapshot, reverses by {b['diff']} ({y2})")],
                    established=([f"snapshot {snap['snapshot_id']} is out of line by {-a['diff']} (snapshot - roll-forward): the "
                                  "surrounding snapshots and movements agree, only this snapshot does not"] if ok else
                                 [f"snapshot {snap['snapshot_id']} is shared by both roll-forwards"]),
                    not_established=[] if ok else ["that the snapshot is the faulty record"],
                    missing_evidence=["the client-balance system's record of how the snapshot was produced"],
                    records=[sref])
                self._rel(y1, y2, "L7 SNAPSHOT LINEAGE", CONFIRMED if ok else CANDIDATE,
                          f"snapshot {snap['snapshot_id']} closes one roll-forward ({a['diff']}) and opens the next ({b['diff']})"
                          + ("; equal and opposite: the snapshot is the common input" if ok else "; the differences do not reverse"),
                          [sref], {"first": str(a["diff"]), "second": str(b["diff"])},
                          [("IN-03", snap["snapshot_id"])], "SHARED_FAULTY_RECORD", proof)

    # F. L3(b) restriction
    def allow_snapshot_lineage(self, x, y):
        """Whether validate's L3(b) link (requirement-side exception x <-> roll-forward failure y) is evidence-backed."""
        if y not in self.cbal:
            return True
        ci = self.cbal[y]
        if y in self.txn_explained:
            self._rel(x, y, "L3 LINEAGE (b)", REJECTED,
                      f"{ci['client']}'s roll-forward failure on {ci['cur']} is explained by a transaction-side discrepancy, so its "
                      "snapshot is not shown to be a faulty input to the requirement", ci["cites"], rtype="CAUSAL_PROPAGATION")
            return False
        kind, parts = self.kind[x], self.by_id[x]["root_cause"].split("|")
        if kind == "INTERNAL_DIFFERENCE":
            r = self._first(x, "C06-DIFFERENCE")
            target = -Decimal(r["computed"]) if r else None
        else:
            r = self._first(x, "C04-REQUIREMENT")
            target = Decimal(r["computed"]) - Decimal(r["reported"]) if r and r["computed"] else None
        if target is None:
            return True
        err = -ci["diff"]   # snapshot - roll-forward
        pool = sum((-c["diff"] for j, c in self.cbal.items() if j not in self.txn_explained and c["ccy"] == ci["ccy"]
                    and c["cur"] == ci["cur"]), ZERO)
        if err == target or pool == target:
            # evidence-bearing relationships (23 Nov 2026): keep the proof of the SUCCESSFUL check, which was discarded before
            self._snapshot_proofs[(x, y)] = self._snapshot_requirement_proof(x, y, kind, r, target, err, pool)
            return True
        self._rel(x, y, "L3 LINEAGE (b)", CANDIDATE,
                  f"{ci['client']}'s {ci['cur']} snapshot is an input to the {ci['ccy']} requirement, but its error ({err}) does not "
                  f"reconcile with the {kind} amount ({target})", ci["cites"], {"snapshot_error": str(err), "target": str(target)},
                  rtype="CAUSAL_PROPAGATION")
        return False

    def snapshot_lineage_proof(self, x, y):
        """The proof recorded when allow_snapshot_lineage(x, y) confirmed the link; None when no quantitative check ran."""
        return self._snapshot_proofs.get((x, y))

    def _snapshot_requirement_proof(self, x, y, kind, r, target, err, pool):
        """G-18 confirmation: the client snapshot behind roll-forward failure y is out of line by exactly the amount of the
        requirement-side exception x, and no transaction-side discrepancy explains it. Figures are the engine's own results."""
        v, ci = self.v, self.cbal[y]
        ccy, d, client = ci["ccy"], ci["cur"], ci["client"]
        scope = f"{d}/{ccy}"
        snap = self.snaps[(ccy, client)][d]
        sref = v.ref("IN-03", snap)
        rf = self._first(y, "CBAL-ROLLFWD")
        r04, r05, r06 = _result(v, "C04-REQUIREMENT", scope), _result(v, "C05-RESOURCE", scope), _result(v, "C06-DIFFERENCE", scope)
        run = next((row for row in v.rows("IN-05") if row["recon_date"] == str(d) and row["currency"] == ccy), None)
        rref = v.ref("IN-05", run) if run else ""
        resource = ((r05 or {}).get("structured") or {}).get("resource")
        exact = err == target
        peers = [(j, c) for j, c in self.cbal.items() if j != y and c["ccy"] == ccy and c["cur"] == d]
        q = [(f"{client} snapshot balance {d} (reported)", rf["reported"] if rf else snap["balance"], sref),
             (f"{client} roll-forward balance {d} (previous snapshot + movements)", rf["computed"] if rf else "", ci["cites"][0]),
             (f"snapshot error (snapshot - roll-forward)", err, sref)]
        if r04 and r04.get("computed"):
            q.append((f"{ccy} requirement {d} (recomputed from the snapshots)", r04["computed"], rref))
            q.append((f"{ccy} requirement {d} (reported)", r04["reported"], rref))
        if resource:
            q.append((f"{ccy} resource {d}", resource, rref))
        if r06 and r06.get("computed"):
            q.append((f"internal difference {d} (resource - requirement)", r06["computed"], rref))
        what = ("requirement in excess of the resource (= - internal difference)" if kind == "INTERNAL_DIFFERENCE"
                else "requirement recomputed - reported")
        q.append((f"{what}: the amount the snapshot error must explain", target, rref))
        if not exact:
            q.append((f"pooled error of unexplained {ccy} snapshots on {d}", pool, ""))
        effect = ""
        try:
            bal, rfb = Decimal(rf["reported"]), Decimal(rf["computed"])
            if kind == "INTERNAL_DIFFERENCE" and r04 and r04.get("computed") and resource and bal >= ZERO and rfb >= ZERO:
                req = Decimal(r04["computed"])
                effect = (f"the {ccy} requirement on {d} ({req}) is the sum of the client snapshots and includes {client}'s "
                          f"snapshot balance {bal}; with {client}'s roll-forward balance {rfb} instead it would be {req - err}, "
                          f"against a resource of {resource}: the snapshot error {err} is " +
                          ("the whole internal difference" if exact else "part of the pooled snapshot error"))
        except (TypeError, ValueError, ArithmeticError, KeyError):
            effect = ""
        if not effect:
            effect = f"{client}'s {d} snapshot is an input to the {ccy} requirement for {d}"
        reversal = [rel for rel in self.relationships if rel["link_type"] == "L7 SNAPSHOT LINEAGE" and rel["strength"] == CONFIRMED
                    and y in rel["exception_ids"]]
        reversed_by = [o for rel in reversal for o in rel["exception_ids"]
                       if o != y and o in self.cbal and self.cbal[o]["prev"] == ci["cur"]]
        corroboration = [f"{o}: the next roll-forward ({self.cbal[o]['prev']}->{self.cbal[o]['cur']}), opened from the same snapshot, "
                         f"reverses by {self.cbal[o]['diff']} (equal and opposite, engine L7 CONFIRMED)" for o in reversed_by]
        excluded = [f"{c['client']} ({j}) has a roll-forward difference on {d} too, but it is explained transaction-side, so its "
                    "snapshot is excluded" for j, c in peers if j in self.txn_explained]
        others = [f"{c['client']} ({j}) snapshot error {-c['diff']}" for j, c in peers if j not in self.txn_explained]
        established = [f"{client}'s {d} snapshot {snap['snapshot_id']} is overstated by {err} against its roll-forward"
                       if err > ZERO else f"{client}'s {d} snapshot {snap['snapshot_id']} is understated by {-err} against its roll-forward",
                       (f"the snapshot error {err} equals the {what} ({target}) exactly" if exact else
                        f"the pooled error of the unexplained {ccy} snapshots ({pool}) equals the {what} ({target})"),
                       f"no transaction-side discrepancy explains {client}'s roll-forward failure",
                       f"{y} is the failed roll-forward of this snapshot and {x} is the {ccy} result that includes it: one faulty "
                       "record behind both exceptions (they were detected by different checks on different records)"]
        if reversed_by:
            established.append("the next day's equal and opposite reversal shows the snapshot itself is the faulty record")
        return make_proof(
            "L3 LINEAGE (b) snapshot in requirement (G-18)", "CAUSAL_PROPAGATION", faulty_record=sref,
            result="EQUAL" if exact else "POOL_EQUAL", quantities=q,
            calculation=(f"snapshot error = {rf['reported'] if rf else '?'} - {rf['computed'] if rf else '?'} = {err}; "
                         + (f"{what} = {target}; equal" if exact else f"pooled snapshot error {pool} = {what} {target}")),
            chronology=[(ci["prev"], f"{client}'s previous snapshot (opening of the roll-forward)"),
                        (d, f"{client}'s snapshot fails its roll-forward by {ci['diff']} ({y})"),
                        (d, f"the {ccy} requirement includes that snapshot; {kind} {target} ({x})")]
            + [(self.cbal[o]["cur"], f"the next roll-forward reverses by {self.cbal[o]['diff']} ({o})") for o in reversed_by],
            requirement_effect=effect, corroboration=corroboration + excluded,
            established=established,
            not_established=([] if exact else [f"how the pooled error divides between {client} and: {'; '.join(others)}"]),
            missing_evidence=[f"how {client}'s {d} snapshot was produced (client-balance system extract or adjustment log)"],
            limitations=(["exclusivity: transaction-explained snapshots are excluded; " + "; ".join(excluded)] if excluded else []),
            records=[sref, ci["cites"][0]] + ([rref] if rref else []))

    def links(self):
        return list(self._links)

    # --- after groups are assigned -----------------------------------------------------------------------------------
    def finish(self):
        v, st = self.v, self.v.enrichment
        self._line_sum_candidates()
        prefix = v.scenario_id()
        have = {tuple(sorted(c["exception_ids"].split("; "))) for c in v.candidates}
        for rel in self.relationships:
            if rel["strength"] != CANDIDATE:
                continue
            pair = tuple(rel["exception_ids"])
            if pair in have:
                continue
            have.add(pair)
            v.candidates.append({"candidate_id": f"CAND-{prefix}-{len(v.candidates) + 1:02d}", "exception_ids": "; ".join(pair),
                                 "basis": rel.get("candidate_basis", "RECORD_LINK_AMOUNT_UNRECONCILED"),
                                 "detail": f"{rel['link_type']}: {rel['basis']}",
                                 "label": "UNVERIFIED — NOT EVIDENCE-BACKED; not an investigation group",
                                 "evidence": "; ".join(rel["evidence"][:4])})
        self._rejected_coincidences()
        root_eid = self.eid_of_root
        for coll in ("amount_comparisons",):
            for c in st[coll]:
                r = _result(v, c["check_id"], c["scope"])
                c["exception_id"] = root_eid.get(r["root_cause"], "") if r else ""
        for d in st["duplicates"]:
            if d.get("outcome_changed"):
                d["exception_id"] = root_eid.get(f"{DUP_CASH if d['source'] == 'IN-10' else DUP_TXN}|{d['duplicate_record']}", "")
        for d in st["suspected_duplicates"]:
            r = _result(v, "C11-TXN-LINE", d["record"])
            d["exception_id"] = root_eid.get(r["root_cause"], "") if r else ""
        st["relationships"] = self.relationships
        st["timing_traces"] = self.timing_traces
        st["exceptions"] = [self._summary(x) for x in self.exc]

    def _line_sum_candidates(self):
        v = self.v
        for i in self.ids:
            if self.kind[i] != "C11-BATCH-ARITH":
                continue
            b = self.batches.get(self.by_id[i]["root_cause"].split("|")[1])
            if not b:
                continue
            missing = [ln for ln in self.lines[b["batch_id"]] if ln["line_type"] in ("TXN", "REFUND") and ln["txn_id"] not in v.txn]
            if not missing:
                continue
            need = {ln["line_id"]: -signed(ln["amount"], ln["dc_indicator"], "settlement") for ln in missing}
            days = {b["cycle_date"], b["settlement_date"]}
            targets = [y for y, c in self.cbal.items() if c["ccy"] == b["currency"] and str(c["cur"]) in days
                       and y not in self.txn_explained]
            facts = [f"{len(missing)} line(s) of {b['batch_id']} reference transaction IDs absent from the transaction export: "
                     + ", ".join(f"{ln['txn_id']} ({ln['amount']})" for ln in missing)]
            matches, note = {}, ""
            if len(missing) > MAX_SUBSET_LINES:
                note = f"{len(missing)} missing lines exceed the enumeration limit ({MAX_SUBSET_LINES}); no line-sum matching attempted"
            else:
                for y in sorted(targets, key=self.ids.index):
                    want = self.cbal[y]["diff"]
                    subsets = [s for k in range(1, len(missing) + 1) for s in combinations(missing, k)
                               if sum((need[ln["line_id"]] for ln in s), ZERO) == want]
                    if subsets:
                        matches[y] = subsets
            for y, subsets in matches.items():
                ci = self.cbal[y]
                s = subsets[0]
                unique = len(subsets) == 1
                desc = (" + ".join(f"{ln['line_id']} ({ln['amount']})" for ln in s) if unique
                        else f"{len(subsets)} different line combinations")
                rel_basis = (f"{desc} of {b['batch_id']} {'sum' if len(s) > 1 else 'equals'} to {ci['client']}'s roll-forward difference "
                             f"{ci['diff']} on {ci['cur']}" + ("" if unique else " (ambiguous)") +
                             ". Settlement lines carry no client: the attribution rests on amounts only.")
                self._rel(i, y, "LINE-SUM MATCH", CANDIDATE, rel_basis, [v.ref("IN-13", ln) for ln in s] + ci["cites"],
                          {"lines_total": str(sum((need[ln["line_id"]] for ln in s), ZERO)), "roll_forward_difference": str(ci["diff"]),
                           "combinations": len(subsets)}, rtype="AMOUNT_COMBINATION", proof=make_proof(
                    "LINE-SUM MATCH", "AMOUNT_COMBINATION", result="SUM_EQUAL" if unique else "SUM_EQUAL_AMBIGUOUS",
                    quantities=[(f"settlement line {ln['line_id']} ({ln['txn_id']}, absent from the transaction export)",
                                 need[ln["line_id"]], v.ref("IN-13", ln)) for ln in s]
                    + [(f"{ci['client']} roll-forward difference {ci['prev']}->{ci['cur']}", ci["diff"], ci["cites"][1])],
                    calculation=f"{' + '.join(str(need[ln['line_id']]) for ln in s)} = {ci['diff']}"
                    + ("" if unique else f" ({len(subsets)} different combinations match)"),
                    established=[f"the amounts of {desc} sum to {ci['client']}'s roll-forward difference"],
                    not_established=["that the missing transactions belong to this client (settlement lines carry no client)"],
                    missing_evidence=["the client of each missing transaction"],
                    limitations=["amounts only: a candidate, never a confirmed relationship"],
                    records=[v.ref("IN-13", ln) for ln in s] + ci["cites"]))
                self.relationships[-1]["candidate_basis"] = "LINE_SUM_MATCH" if unique else "LINE_SUM_MATCH_AMBIGUOUS"
            unique = {y: ss[0] for y, ss in matches.items() if len(ss) == 1}
            used = [ln["line_id"] for s in unique.values() for ln in s]
            disjoint = len(used) == len(set(used))
            accounted = disjoint and set(used) == set(need)
            members = [i] + sorted(unique, key=self.ids.index)
            self.v.enrichment["common_causes"].append({
                "common_cause_id": f"CC-{v.scenario_id()}-{len(self.v.enrichment['common_causes']) + 1:02d}",
                "exception_ids": members, "status": "SUSPECTED" if len(members) > 1 and disjoint else "NOT_ESTABLISHED",
                "proposed_common_cause": f"transactions of settlement batch {b['batch_id']} missing from the transaction export",
                "confirmed_facts": facts + [f"batch {b['batch_id']} header, lines and bank entry are compared by C11 (see its result)"],
                "unverified_inferences": [r["basis"] for r in self.relationships if r["link_type"] == "LINE-SUM MATCH" and i in r["exception_ids"]],
                "all_missing_lines_accounted_for": accounted,
                "unaccounted_lines": sorted(set(need) - set(used)),
                "missing_evidence": ["the client of each missing transaction (settlement lines carry no client_id)",
                                     "a complete transaction export or the export job log"],
                "note": note or ("line combinations are disjoint" if disjoint else "line combinations overlap: no common attribution"),
                "evidence": [v.ref("IN-12", b)] + [v.ref("IN-13", ln) for ln in missing]})

    def _signature(self, i):
        """(date, currency, |discrepancy|) of an exception, from its own structured comparisons; None if not numeric."""
        x, kind, parts = self.by_id[i], self.kind[i], self.by_id[i]["root_cause"].split("|")
        if i in self.cbal:
            c = self.cbal[i]
            return str(c["cur"]), c["ccy"], abs(c["diff"])
        if kind == "BANK_LEDGER_DIFFERENCE":
            return parts[2], self.v.ccy_of.get(parts[1], ""), abs(Decimal(parts[3]))
        if kind == "INTERNAL_DIFFERENCE":
            r = self._first(i, "C06-DIFFERENCE")
            d, ccy = parts[1].split("/")
            return (d, ccy, abs(Decimal(r["computed"]))) if r else None
        for r in self.rows_of[i]:
            comp = (r.get("structured") or {}).get("comparison")
            if comp and r["check_id"] == "RC4-DIRECT":
                t = self.v.txn[comp["subject"]["txn_id"]]
                return _local_date(t["executed_ts"]).isoformat(), t["currency"], abs(Decimal(comp["difference"]))
            if comp and r["check_id"] in ("C04-REQUIREMENT", "RC2-LEDGER", "C05-RESOURCE"):
                d = r["scope"].split("/")[0]
                ccy = r["scope"].split("/")[1]
                return d, self.v.ccy_of.get(ccy, ccy), abs(Decimal(comp["difference"]))
        return None

    def _rejected_coincidences(self):
        sig = {i: self._signature(i) for i in self.ids}
        related = {tuple(r["exception_ids"]) for r in self.relationships if r["strength"] in (CONFIRMED, CANDIDATE)}
        related |= {tuple(sorted(c["exception_ids"].split("; "))) for c in self.v.candidates}
        group = {i: self.by_id[i].get("investigation_group_id", "") for i in self.ids}
        for a, b in combinations(self.ids, 2):
            sa, sb = sig[a], sig[b]
            if not sa or not sb or sa != sb or sa[2] == ZERO:
                continue
            if (group[a] and group[a] == group[b]) or tuple(sorted([a, b])) in related:
                continue
            self.v.enrichment["rejected_coincidences"].append({
                "exception_ids": [a, b], "date": sa[0], "currency": sa[1], "amount": str(sa[2]), "strength": REJECTED,
                "basis": "same date, currency and amount, but no shared source record or reference: not linked"})

    def _summary(self, x):
        i = x["exception_id"]
        comps = [c for c in self.v.enrichment["amount_comparisons"] if c["exception_id"] == i]
        rels = [r for r in self.relationships if i in r["exception_ids"]]
        lineage = [self._txn_lineage(k) for s, k in sorted(self.records[i]) if s == "IN-11"][:20]
        for c in comps:
            tid = c.get("subject", {}).get("txn_id")
            if tid and tid in self.v.txn and all(l["txn_id"] != tid for l in lineage):
                lineage.append(self._txn_lineage(tid))
        return {"exception_id": i, "root_cause": x["root_cause"], "investigation_group_id": x.get("investigation_group_id", ""),
                "discrepancies": [{k: c[k] for k in ("check_id", "scope", "difference", "difference_basis", "direction")} for c in comps][:20],
                "outlier_sources": [c["outlier"] for c in comps if c["outlier"]["status"] == "IDENTIFIED"],
                "records": [f"{s}:{k}" for s, k in sorted(self.records[i])][:50], "lineage": lineage[:20],
                "relationships": {s: sum(1 for r in rels if r["strength"] == s) for s in (CONFIRMED, CANDIDATE, REJECTED)}}

    def _txn_lineage(self, tid):
        v, t = self.v, self.v.txn.get(tid)
        if t is None:
            return {"txn_id": tid, "present_in_IN-11": False}
        lines = [ln for ln in self.lines.get(t["settlement_batch_id"], []) if ln["txn_id"] == tid]
        b = self.batches.get(t["settlement_batch_id"])
        bank = [e["bank_entry_id"] for e in v.rows("IN-09") if (b and e["account_id"] == b["account_id"] and
                                                                  e["bank_reference"] == b["expected_bank_reference"])
                or (t["payment_reference"] and e["end_to_end_ref"] == t["payment_reference"])]
        ref = b["expected_bank_reference"] if b else t["payment_reference"]
        cash = [c["ledger_entry_id"] for c in v.rows("IN-10") if ref and c["payment_reference"] == ref]
        return {"txn_id": tid, "present_in_IN-11": True, "client_id": t["client_id"], "txn_type": t["txn_type"], "amount": t["amount"],
                "executed_ts": t["executed_ts"], "settlement_lines": [ln["line_id"] for ln in lines],
                "settlement_batch_id": t["settlement_batch_id"], "bank_entries": bank, "cashbook_entries": cash,
                "link_basis": "batch expected_bank_reference" if b else "end-to-end reference"}


def report_lines(e):
    """Markdown section for VALIDATION_REPORT.md."""
    out = ["", "## Reconciliation enrichment (enrichment-v1; deterministic; never sets a cause or resolves anything)", ""]
    out.append(f"- Duplicates: {sum(1 for d in e['duplicates'] if d.get('outcome_changed'))} confirmed; "
               f"{len(e['suspected_duplicates'])} suspected")
    for d in e["duplicates"]:
        if d.get("outcome_changed"):
            out.append(f"  - {d['duplicate_record']} duplicates {d['duplicate_of']} ({d['classification']}; bank entry {d['bank_entry_id']})")
    out.append(f"- Amount comparisons: {len(e['amount_comparisons'])}; outlier source identified in "
               f"{sum(1 for c in e['amount_comparisons'] if c['outlier']['status'] == 'IDENTIFIED')}")
    for c in e["amount_comparisons"]:
        if c["outlier"]["status"] == "IDENTIFIED":
            out.append(f"  - {c['check_id']} {c['scope']}: difference {c['difference']} ({c['direction']}); outlier {c['outlier']['source']} "
                       f"{c['outlier']['record']}")
    for s in (CONFIRMED, CANDIDATE, REJECTED):
        rs = [r for r in e["relationships"] if r["strength"] == s]
        out.append(f"- Relationships {s}: {len(rs)}")
        out += [f"  - {' / '.join(r['exception_ids'])} {r['link_type']}: {r['basis']}" for r in rs]
    for t in e["timing_traces"]:
        out.append(f"- Timing trace {t['exception_id']} ({t['account_id']} {t['date']}): {t['evidence_class']}; explained "
                   f"{t['explained_by_items']} of {t['difference']}; not resolved")
    for c in e["common_causes"]:
        out.append(f"- Common cause {c['common_cause_id']} ({c['status']}): {', '.join(c['exception_ids'])} — {c['proposed_common_cause']}; "
                   f"all missing lines accounted for: {c['all_missing_lines_accounted_for']}")
    for u in e["unmatched_credits"]:
        out.append(f"- Unmatched credit {u['bank_entry_id']} ({u['exception_id']}): potential requirement understatement up to "
                   f"{u['amount']} {u['currency']}")
    for r in e["rejected_coincidences"]:
        out.append(f"- Rejected coincidence {' / '.join(r['exception_ids'])}: {r['date']} {r['currency']} {r['amount']} — {r['basis']}")
    return out
