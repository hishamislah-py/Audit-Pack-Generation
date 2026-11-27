"""Deterministic retrieval (phase 6, token-optimisation copy): Python, not the model, gathers the evidence that tools mode
lets the model fetch, so an investigation can normally be ONE structured request (fixed mode) on a richer packet.

It starts from the existing route plans (packet.retrieve: engine-cited records + route plan + related exceptions) and
expands on the SAME Collector through the SAME tool functions (tools.execute), so every record keeps its file, line,
SHA-256, retrieved_via and join_key exactly as in tools mode. Depth policy (DET_RULE_VERSION):

  1. anchor reconciliation evidence: for every anchor (account, currency, date) of the primary exception and of related
     exceptions of a different kind, get_reconciliation_evidence (IN-06/07/08 + the IN-05 internal record that no route
     plan fetched); bank-ledger anchors include the next reconciliation day (fixes the SC3C EXC-02 09-09 IN-05 gap);
  2. batch expansion: a settlement batch header already in the evidence whose settlement date is an anchor date (same
     account) is expanded into its lines and transactions; batches of other days are not (avoids next-day over-fetch);
  3. missing bank evidence: for the missing (account, date), one bank search per expected counterparty reference (batch
     expected references of the day, IN-11 payment references and the own-funds top-up reference); no search repeats a
     reconciliation probe;
  4. de-duplication (1.3): a NOT_FOUND search is dropped only when an EARLIER NOT_FOUND search has the same COMPLETE
     normalised query (every key kept; only genuine date / reference synonyms folded; a None filter equals an absent one).
     A FOUND search never suppresses another search, and FOUND searches are never dropped. Each drop is recorded with the
     search it duplicates;
  5. record budget (1.3): an expansion never takes the packet past DET_MAX_RECORDS. Calls are refused once the budget is
     reached, and inside a call only the records that fit are added. Every record a call returned but did not add (record
     budget, per-call cap or the investigation-wide MAX_RECORDS) is listed by evidence ID in the pruning register. Nothing
     already collected is ever removed, and nothing is dropped silently.

Candidate relationships stay in the case exactly as before (hypotheses only); no amount/date rule becomes a join.
Routes without a deterministic plan (DET_UNSUPPORTED_ROUTES) are not handled here: the graph falls back to tools mode
and records why."""
import hashlib
import json

from . import config, tools
from .packet import canonical, parse_root, retrieve
from .routing import root_kind

DET_RULE_VERSION = "uc042-det-retrieval/1.3"  # 1.1: last persistence day, booking-date anchors, cash-book references, unmatched-entry search;
# 1.2: related-exception anchors for a different root-cause kind only (bounded large groups);
# 1.3 (review DR-01 / DR-03): NOT_FOUND de-duplication on the complete query only; record budget enforced inside a call and
# every record a call did not add registered by evidence ID
DET_PACKET_VERSION = "uc042-evidence-packet/2.0-det"
DET_SUPPORTED_ROUTES = ("bank_ledger_mismatch", "settlement_discrepancy", "missing_bank_evidence", "customer_balance_discrepancy",
                        "unmatched_bank_entry", "unverified_relationship")
DET_UNSUPPORTED_ROUTES = ("insufficient_evidence", "generic")  # no retrieval plan yet: tools-mode fallback
DET_MAX_RECORDS = 140  # below the 160-record investigation cap, leaving headroom


def supported(route):
    return route in DET_SUPPORTED_ROUTES


def _anchors(case, store):
    """(account, currency, date, why) anchors from engine keys of the primary exception and related exceptions."""
    out = []

    def add(acct, ccy, d, why):
        if acct and ccy and d and (acct, ccy, d) not in [(a, c, x) for a, c, x, _ in out]:
            out.append((acct, ccy, d, why))
    # related exceptions of a DIFFERENT kind only, as packet.retrieve() applies their plans (a large same-kind group such as
    # SC5C's 16 internal differences would otherwise add every member's day: measured 9 -> 72 records under rule 1.1)
    kinds, exceptions = {root_kind(case["exception"])}, [case["exception"]]
    for r in case["related_exceptions"]:
        if root_kind(r) not in kinds:
            kinds.add(root_kind(r))
            exceptions.append(r)
    for i, x in enumerate(exceptions):
        kind, keys = parse_root(x)
        who = "primary" if i == 0 else f"related {x['exception_id']}"
        acct, ccy = keys.get("account_id") or x.get("account_id"), keys.get("currency") or x.get("currency")
        if keys.get("batch_id"):
            b = store.get(f"IN-12:{keys['batch_id']}", "probe")
            if b:
                acct, ccy, d = b["fields"]["account_id"], b["fields"]["currency"], b["fields"]["settlement_date"]
                add(acct, ccy, d, f"{who}: batch {keys['batch_id']} settlement date")
            continue
        if keys.get("ledger_entry_id"):
            le = store.get(f"IN-10:{keys['ledger_entry_id']}", "probe")
            if le:
                add(le["fields"]["account_id"], le["fields"]["currency"], le["fields"]["posted_ts"][:10], f"{who}: cash-book entry date")
            continue
        if keys.get("bank_entry_id"):
            be = store.get(f"IN-09:{keys['bank_entry_id']}", "probe")
            if be:
                add(be["fields"]["account_id"], be["fields"]["currency"], be["fields"]["booking_date"], f"{who}: bank entry date")
            continue
        d = keys.get("date") or x.get("first_date")
        if acct and not ccy:
            a = store.get(f"IN-02:{acct}", "probe")
            ccy = a["fields"]["currency"] if a else None
        if not acct and ccy and kind in ("CBAL-ROLLFWD", "INTERNAL_DIFFERENCE", "C04-REQUIREMENT"):
            accts = sorted(r["account_id"] for _, _, r in store.by_fid.get("IN-02", [])
                           if r.get("currency") == ccy and r.get("account_id", "").startswith("SGA-"))
            acct = accts[0] if accts else None
        add(acct, ccy, d, f"{who}: {kind} date")
        if kind == "BANK_LEDGER_DIFFERENCE" and d:
            nxt = store.next_recon_day(d)
            if nxt:
                add(acct, ccy, nxt, f"{who}: next reconciliation day after the difference begins")
            if x.get("last_date") and x["last_date"] != d:  # 1.1: the last day of a persisting difference
                add(acct, ccy, x["last_date"], f"{who}: last day the difference persists")
    return out


class _BudgetedCall(tools.ToolCall):
    """tools.ToolCall with the deterministic record budget (DR-03). The per-call cap and the investigation-wide
    MAX_RECORDS behave exactly as in tools mode; in addition a record new to the packet is added only while the packet
    is below `budget`. Every record the call returned but did not add is kept by reason, for the pruning register. The
    value returned to the tool function (which becomes a search's `found` list) is exactly the tools-mode value, so a
    search whose records were cut for budget reasons stays FOUND: the cut never fabricates a NOT_FOUND."""

    def __init__(self, store, collector, name, max_records, budget):
        super().__init__(store, collector, name, max_records)
        self.budget, self.cut_per_call, self.cut_budget = budget, [], []
        self.cut_items = {}  # evidence_id -> record, for every record this call returned but did not add

    def add(self, items, rel_from=None, relationship=None):
        items = [i for i in items or [] if i]
        fresh = [i for i in items if i["evidence_id"] not in self.ids]
        room = self.max_records - len(self.ids)
        if len(fresh) > room:  # the per-call cap, as in ToolCall.add (which itself keeps no record of the cut IDs)
            self.truncated = True
            for i in fresh[max(room, 0):]:
                if i["evidence_id"] not in self.cut_per_call:
                    self.cut_per_call.append(i["evidence_id"])
                    self.cut_items[i["evidence_id"]] = i
            fresh = fresh[:max(room, 0)]
        allowed, n = set(), len(self.col.records)
        for i in fresh:
            eid = i["evidence_id"]
            if eid in self.col.records:
                allowed.add(eid)
            elif n < self.budget:
                allowed.add(eid)
                n += 1
            elif eid not in self.cut_budget:
                self.cut_budget.append(eid)
                self.cut_items[eid] = i
        super().add([i for i in fresh if i["evidence_id"] in allowed], rel_from, relationship)
        for i in fresh:  # the investigation-wide MAX_RECORDS cut (ToolCall.not_added): keep the record too
            if i["evidence_id"] in self.not_added:
                self.cut_items.setdefault(i["evidence_id"], i)
        return [i["evidence_id"] for i in fresh]

    def unfollowed(self):
        """Records the tool never retrieved because the record referencing them was cut: get_settlement_batch follows a
        settlement line to its transaction only when the line was added (tools.py, `ln["evidence_id"] not in call.ids`),
        the only traversal in the tool registry that depends on an earlier add. Returned as (evidence_id, via line)."""
        out = []
        for eid, it in self.cut_items.items():
            t = it.get("fields", {}).get("txn_id") if it.get("file_id") == "IN-13" else None
            tx = f"IN-11:{t}" if t else None
            if tx and tx not in self.col.records and tx not in self.cut_items and tx not in [x for x, _ in out] \
                    and self.store.get(tx, "probe"):
                out.append((tx, eid))
        return out


def _run(col, store, name, args, register, step):
    if len(col.records) >= DET_MAX_RECORDS:
        register.append({"step": step, "tool": name, "arguments": args, "reason": f"record budget {DET_MAX_RECORDS} reached; not fetched"})
        return None
    a, err = tools.parse_request(name, json.dumps(args))
    if err:
        register.append({"step": step, "tool": name, "arguments": args, "reason": f"request rejected: {err}"})
        return None
    call = _BudgetedCall(store, col, name, config.TOOL_MAX_RECORDS_PER_CALL, DET_MAX_RECORDS)
    try:
        tools.REGISTRY[name].fn(a, call)  # what tools.execute does, with the budgeted call
    except tools.ToolInputError as e:
        register.append({"step": step, "tool": name, "arguments": args, "reason": f"not applicable: {e}"})
        return None
    for ids, reason in ((call.cut_budget, f"record budget {DET_MAX_RECORDS} reached during the call; not added"),
                        (call.cut_per_call, f"per-call cap of {config.TOOL_MAX_RECORDS_PER_CALL} records reached; not added"),
                        (call.not_added, f"investigation-wide MAX_RECORDS {config.MAX_RECORDS} reached; not added")):
        if ids:
            register.append({"step": step, "tool": name, "arguments": args, "reason": reason, "omitted_evidence_ids": list(ids)})
    unfollowed = call.unfollowed()
    if unfollowed:
        register.append({"step": step, "tool": name, "arguments": args, "omitted_evidence_ids": [x for x, _ in unfollowed],
                         "not_retrieved_via": {x: line for x, line in unfollowed},
                         "reason": "not retrieved: the settlement line referencing each transaction was not added (see the "
                                   "entries above), so the tool did not follow it"})
    return call.result()


# Genuine synonyms only: the same filter under another key name in different tools. Every other key is kept as it is.
_SYNONYMS = {"statement_date": "date", "booking_date": "date", "recon_date": "date", "bank_reference": "reference"}


def _norm(query):
    """The complete normalised query of a search (1.3). Every key is kept (txn_id, batch_id, client_id, txn_type,
    payment_reference, window, date_from, date_to, currency, ...); a key whose value is None is no filter and is left out;
    date and reference synonyms are folded only when that does not conflict with a value already present."""
    out = {}
    for k, v in sorted((query or {}).items()):
        if v is None:
            continue
        ck = _SYNONYMS.get(k, k)
        if ck in out and out[ck] != v:
            ck = k  # two different values under synonym names: keep both, never merge them
        out[ck] = v
    return json.dumps(out, sort_keys=True, ensure_ascii=False)


def dedupe_not_found(searches):
    """(kept, register entries). A NOT_FOUND search is dropped only when an EARLIER NOT_FOUND search has the same complete
    normalised query; FOUND searches are never dropped and never cause a drop. Order is preserved."""
    first_nf, kept, register = {}, [], []
    for s in searches:
        if s["result"] == "NOT_FOUND":
            key = _norm(s["query"])
            if key in first_nf:
                register.append({"step": "de-duplication", "search_id": s["search_id"], "duplicate_of": first_nf[key],
                                 "query": s["query"],
                                 "reason": f"identical NOT_FOUND query already recorded as {first_nf[key]}"})
                continue
            first_nf[key] = s["search_id"]
        kept.append(s)
    return kept, register


def expand(col, case, route, store):
    """Apply the depth policy to the collector built by packet.retrieve. Returns the pruning register (list)."""
    register = []
    anchors = _anchors(case, store)
    # 1.1: a batch whose bank entry (same reference, already retrieved) is booked on another day: that day is an anchor
    for b in [r for r in list(col.records.values()) if r["file_id"] == "IN-12"]:
        f = b["fields"]
        if (f["account_id"], f["settlement_date"]) not in {(a, d) for a, _, d, _ in anchors}:
            continue
        for e in [r for r in col.records.values() if r["file_id"] == "IN-09" and r["fields"].get("account_id") == f["account_id"]
                  and f["expected_bank_reference"] in (r["fields"].get("bank_reference"), r["fields"].get("end_to_end_ref"))]:
            bd = e["fields"]["booking_date"]
            if bd != f["settlement_date"] and (f["account_id"], f["currency"], bd) not in [(a, c, x) for a, c, x, _ in anchors]:
                anchors.append((f["account_id"], f["currency"], bd, f"bank entry of batch {f['batch_id']} booked on {bd}"))
    for acct, ccy, d, why in anchors:                                                     # 1
        _run(col, store, "get_reconciliation_evidence", {"account_id": acct, "currency": ccy, "date": d}, register, f"anchor {why}")
    dates = {(a, d) for a, _, d, _ in anchors}
    for eid in [e for e in list(col.records) if e.startswith("IN-12:")]:                  # 2
        f = col.records[eid]["fields"]
        if (f["account_id"], f["settlement_date"]) in dates:
            has_lines = any(r["file_id"] == "IN-13" and r["fields"].get("batch_id") == f["batch_id"] for r in col.records.values())
            if not has_lines:
                _run(col, store, "get_settlement_batch", {"batch_id": f["batch_id"]}, register, f"anchor-day batch {f['batch_id']}")
    if route == "missing_bank_evidence":                                                  # 3
        kind, keys = parse_root(case["exception"])
        acct, d = keys.get("account_id"), keys.get("date")
        if acct and d:
            ccy = next((c for a, c, x, _ in anchors if a == acct and x == d), None)
            refs = []
            for r in list(col.records.values()):
                f = r["fields"]
                if r["file_id"] == "IN-12" and f.get("account_id") == acct and f.get("settlement_date") == d:
                    refs.append(f["expected_bank_reference"])
                if r["file_id"] == "IN-11" and (f.get("clearing_date") == d) and f.get("payment_reference"):
                    refs.append(f["payment_reference"])
                if r["file_id"] == "IN-10" and f.get("account_id") == acct and (f.get("posted_ts") or "")[:10] == d \
                        and f.get("entry_type") != "OPENING_BALANCE" and f.get("payment_reference"):
                    refs.append(f["payment_reference"])  # 1.1: the firm's own cash-book references of the day
            if ccy:
                refs.append(f"TOPUP-{ccy}-{d.replace('-', '')}")
            for ref in dict.fromkeys(x for x in refs if x):
                _run(col, store, "search_bank_entries", {"account_id": acct, "bank_reference": ref, "date_from": None, "date_to": None},
                     register, f"expected counterparty reference {ref}")
    # 3b (1.1): a bank entry the engine cites as unmatched -> the firm's cash book searched by that entry's reference
    unmatched_kinds = ("C11-BANK-ENTRY", "BANK-CASH-LINK", "UNMATCHED_BANK_ENTRY")
    for x in [case["exception"]] + list(case["related_exceptions"]):
        kind, keys = parse_root(x)
        if kind in unmatched_kinds and keys.get("bank_entry_id"):
            be = col.records.get(f"IN-09:{keys['bank_entry_id']}") or store.get(f"IN-09:{keys['bank_entry_id']}", "probe")
            if be and be["fields"].get("bank_reference"):
                _run(col, store, "get_cashbook_entries", {"account_id": be["fields"]["account_id"], "date_from": None, "date_to": None,
                                                          "payment_reference": be["fields"]["bank_reference"]},
                     register, f"cash book for unmatched bank entry {keys['bank_entry_id']}")
    col.searches, dropped = dedupe_not_found(col.searches)                                # 4
    register += dropped
    return register


def finalise_packet(packet, register):
    """Mark a deterministic packet: version, rule version, pruning register; the packet hash covers them."""
    packet = dict(packet)
    packet.pop("packet_sha256", None)
    packet["packet_version"] = DET_PACKET_VERSION
    packet["retrieval_rule_version"] = DET_RULE_VERSION
    packet["pruning_register"] = register
    packet["packet_sha256"] = hashlib.sha256(canonical(packet).encode("utf-8")).hexdigest()
    return packet
