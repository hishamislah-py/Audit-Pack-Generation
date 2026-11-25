"""Investigation case, scope and evidence packet construction (deterministic Python).

Retrieval is scoped: it starts from the evidence the engine cited for the exception and widens only through verified join
keys (references, batch IDs, transaction IDs, refund links, account+date). Each record keeps its origin (file, line,
file SHA-256) and the relationship by which it was reached. Negative lookups are recorded as citable SEARCH items.
The packet never contains dataset folder names, scenario names, answer keys or mutation descriptions.
"""
import hashlib
import json
from collections import OrderedDict

from ..pack.model import canonical
from . import config
from .routing import root_kind


# --------------------------------------------------------------------------------------------------------------
# Case and scope (from the deterministic pack only)
# --------------------------------------------------------------------------------------------------------------
def build_case(pack, exception_id):
    exc_by_id = {x["exception_id"]: x for x in pack["exception_register"]["exceptions"]}
    if exception_id not in exc_by_id:
        raise KeyError(f"exception {exception_id} not found in pack {pack['metadata']['pack_id']}")
    x = exc_by_id[exception_id]
    results = {r["result_id"]: r for c in pack["control_register"] for r in c["results"]}
    groups = {g["group_id"]: g for g in pack["investigation_group_register"]["groups"]}
    group = groups.get(x["investigation_group_id"]) if x["investigation_group_id"] else None
    candidates = [c for c in pack["investigation_group_register"]["candidate_relationships"]
                  if exception_id in c["exception_ids"].split("; ")]
    related_ids = set(group["exception_ids"].split("; ")) if group else set()
    for c in candidates:
        related_ids |= set(c["exception_ids"].split("; "))
    related_ids.discard(exception_id)
    missing = [m for m in pack["missing_evidence_register"]["items"]
               if m["related_exception_id"] in ({exception_id} | related_ids)]
    return {"pack_id": pack["metadata"]["pack_id"], "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"],
            "exception": x, "results": [results[i] for i in x["affected_result_ids"] if i in results],
            "group": group, "candidates": candidates,
            "related_exceptions": [exc_by_id[i] for i in sorted(related_ids) if i in exc_by_id],
            "related_results": {i: [results[r] for r in exc_by_id[i]["affected_result_ids"] if r in results]
                                for i in related_ids if i in exc_by_id},
            "missing_items": missing}


def parse_root(exception):
    """Structured keys from the engine's root-cause string."""
    parts = (exception.get("root_cause") or "").split("|")
    kind, keys = parts[0], {}
    if kind in ("BANK_LEDGER_DIFFERENCE", "MISSING_BANK_EVIDENCE") and len(parts) >= 3:
        keys = {"account_id": parts[1], "date": parts[2]}
    elif kind in ("C11-BATCH-ARITH", "C11-BATCH-BANK", "FUND-TOPUP") and len(parts) >= 2:
        keys = {"batch_id": parts[1]}
    elif kind == "CASH-BANK-LINK" and len(parts) >= 2:
        keys = {"ledger_entry_id": parts[1]}
    elif kind in ("UNMATCHED_BANK_ENTRY", "BANK-CASH-LINK", "C11-BANK-ENTRY") and len(parts) >= 2:
        keys = {"bank_entry_id": parts[1]}
    elif kind == "CBAL-ROLLFWD" and len(parts) >= 2 and "/" in parts[1] and " " in parts[1]:
        ccy, rest = parts[1].split("/", 1)
        client, d = rest.split(" ", 1)
        keys = {"currency": ccy, "client_id": client, "date": d}
    elif kind in ("INTERNAL_DIFFERENCE", "C04-REQUIREMENT") and len(parts) >= 2 and "/" in parts[1]:
        d, ccy = parts[1].split("/", 1)
        keys = {"date": d, "currency": ccy}
    elif kind == "MISSING_FILE" and len(parts) >= 2:
        keys = {"file_id": parts[1]}
    return kind, keys


def build_scope(case):
    x = case["exception"]
    kind, keys = parse_root(x)
    return {"root_cause_kind": kind, "root_cause": x["root_cause"], "category": x["category"], "severity": x["severity"],
            "account_id": x["account_id"], "currency": x["currency"], "first_date": x["first_date"], "last_date": x["last_date"],
            "amount": x["amount"], "control_codes": x["control_codes"],
            "check_ids": sorted({r["result_id"].split("|")[0] for r in case["results"]}),
            "affected_result_count": len(case["results"]), "evidence_status": x["evidence_status"],
            "investigation_group_id": x["investigation_group_id"], "group_size": case["group"]["size"] if case["group"] else 0,
            "candidate_relationship_ids": [c["candidate_id"] for c in case["candidates"]],
            "related_exception_ids": [r["exception_id"] for r in case["related_exceptions"]],
            "missing_evidence_item_ids": [m["item_id"] for m in case["missing_items"]], "keys": keys}


# --------------------------------------------------------------------------------------------------------------
# Retrieval plans
# --------------------------------------------------------------------------------------------------------------
class Collector:
    def __init__(self):
        self.records = OrderedDict()
        self.relationships = []
        self.searches = []
        self.truncated = False

    def add(self, items, rel_from=None, relationship=None):
        for it in items or []:
            if it is None:
                continue
            if it["evidence_id"] not in self.records:
                if len(self.records) >= config.MAX_RECORDS:
                    self.truncated = True
                    continue
                self.records[it["evidence_id"]] = it
            if rel_from:
                rel = {"from": rel_from, "to": it["evidence_id"], "relationship": relationship or it["retrieved_via"],
                       "join_key": it["join_key"]}
                if rel not in self.relationships:
                    self.relationships.append(rel)

    def search(self, description, query, found):
        for s in self.searches:  # identical searches are recorded once
            if s["description"] == description and s["query"] == query:
                return s["search_id"]
        sid = f"SEARCH-{len(self.searches) + 1:02d}"
        self.searches.append({"search_id": sid, "description": description, "query": query, "found": list(found),
                              "result": "FOUND" if found else "NOT_FOUND"})
        return sid


def plan_cited(store, results, col):
    for r in results:
        for eid in r.get("evidence_ids", []):
            if ":" in eid:
                col.add([store.get(eid, via=f"cited by control result {r['result_id']}")], r["result_id"], "cited_by_control_result")


def plan_bank_ledger(store, keys, results, col):
    acct, d0 = keys.get("account_id"), keys.get("date")
    if not acct or not d0:
        return
    days = [d for d in (d0, store.next_recon_day(d0)) if d]
    for d in days:
        erl = store.external_record(acct, d, "external reconciliation record for account and date")
        col.add(erl)
        col.add(store.confirmation(acct, d, "17:00 bank balance confirmation for account and date"))
        for s in store.statement(acct, d, "end-of-day bank statement for account and date"):
            col.add([s])
            col.add(store.entries_on_statement(s["fields"]["statement_id"], "bank entries on the statement"),
                    s["evidence_id"], "entry_on_statement")
        col.add(store.cashbook_on_date(acct, d, "cash-book entries posted on the date"))
    for r in results:
        for item in (r.get("structured") or {}).get("timing_items", []):
            le = store.get(f"IN-10:{item['ledger_entry_id']}", "cash-book entry named in engine timing evidence")
            be = store.get(f"IN-09:{item['bank_entry_id']}", "bank entry named in engine timing evidence") if item["bank_entry_id"] else None
            col.add([le], r["result_id"], "timing_item_ledger_side")
            col.add([be], le["evidence_id"] if le else r["result_id"], "timing_item_bank_side (same reference)")
            if le:  # the settlement batch carrying the same reference (verified join, not amount matching)
                ref = le["fields"]["payment_reference"]
                col.add(store.find("IN-12", "settlement batch whose expected bank reference equals the timing item reference",
                                   expected_bank_reference=ref), le["evidence_id"], "batch.expected_bank_reference = cashbook.payment_reference")
    erl_ids = {e["fields"]["ext_recon_id"] for e in col.records.values() if e["file_id"] == "IN-06"}
    logs = store.discrepancy_log_for(erl_ids, "discrepancy log entry referencing the reconciliation record")
    for lg in logs:
        col.add([lg], f"IN-06:{lg['fields']['recon_ref']}", "discrepancy_log.recon_ref")
    col.search("Discrepancy log entries referencing the external reconciliation records in scope",
               {"file": "IN-14", "recon_ref_in": sorted(erl_ids)}, [lg["evidence_id"] for lg in logs])


def plan_settlement(store, keys, results, col):
    batch_ids = set()
    if keys.get("batch_id"):
        batch_ids.add(keys["batch_id"])
    if keys.get("ledger_entry_id"):
        le = store.get(f"IN-10:{keys['ledger_entry_id']}", "cash-book entry named by the exception")
        col.add([le])
        if le:
            for b in store.find("IN-12", "settlement batch whose expected bank reference equals the cash-book reference",
                                expected_bank_reference=le["fields"]["payment_reference"]):
                col.add([b], le["evidence_id"], "batch.expected_bank_reference = cashbook.payment_reference")
                batch_ids.add(b["fields"]["batch_id"])
    for bid in sorted(batch_ids):
        b = store.get(f"IN-12:{bid}", "settlement batch header")
        if not b:
            col.search(f"Settlement batch {bid}", {"file": "IN-12", "batch_id": bid}, [])
            continue
        col.add([b])
        f = b["fields"]
        lines = store.lines_of_batch(bid, "settlement lines of the batch")
        col.add(lines, b["evidence_id"], "line.batch_id")
        for ln in lines:
            t = ln["fields"]["txn_id"]
            if not t:
                continue
            tx = store.get(f"IN-11:{t}", "transaction referenced by a settlement line")
            if tx:
                col.add([tx], ln["evidence_id"], "line.txn_id = transaction.txn_id")
            else:
                col.search(f"Transaction {t} referenced by settlement line {ln['fields']['line_id']}",
                           {"file": "IN-11", "txn_id": t}, [])
        bank = store.bank_entries_by_reference(f["account_id"], f["expected_bank_reference"], "bank entry carrying the batch reference")
        col.add(bank, b["evidence_id"], "bank.bank_reference = batch.expected_bank_reference")
        col.search(f"Bank entries carrying batch reference {f['expected_bank_reference']}",
                   {"file": "IN-09", "account_id": f["account_id"], "reference": f["expected_bank_reference"]}, [x["evidence_id"] for x in bank])
        cash = store.cashbook_by_reference(f["account_id"], f["expected_bank_reference"], "cash-book entry carrying the batch reference")
        col.add(cash, b["evidence_id"], "cashbook.payment_reference = batch.expected_bank_reference")
        if f["counterparty_type"] == "ACQUIRER":
            tops = [c for c in store.cashbook_on_date(f["account_id"], f["settlement_date"], "own-funds top-up posted on the settlement date")
                    if c["fields"]["entry_type"] == "OWN_FUNDS_TOPUP"]
            col.add(tops, b["evidence_id"], "same account and settlement date, entry_type OWN_FUNDS_TOPUP")
            for c in tops:
                ref = c["fields"]["payment_reference"]
                legs = store.find_where("IN-09", "bank legs carrying the top-up reference", f"bank_reference={ref}",
                                        lambda r, ref=ref: ref in (r["bank_reference"], r["end_to_end_ref"]))
                col.add(legs, c["evidence_id"], "bank.bank_reference = cashbook.payment_reference")


def plan_missing(store, keys, results, col, missing_items):
    acct, d = keys.get("account_id"), keys.get("date")
    if acct and d:
        col.add(store.external_record(acct, d, "external reconciliation record for the account and date (as reported by the firm)"))
        col.search(f"17:00 bank confirmation for {acct} on {d}", {"file": "IN-07", "account_id": acct, "date": d},
                   [x["evidence_id"] for x in store.confirmation(acct, d, "probe")])
        col.search(f"End-of-day statement for {acct} on {d}", {"file": "IN-08", "account_id": acct, "statement_date": d},
                   [x["evidence_id"] for x in store.statement(acct, d, "probe")])
        col.search(f"Bank entries booked on {acct} on {d}", {"file": "IN-09", "account_id": acct, "booking_date": d},
                   [x["evidence_id"] for x in store.find("IN-09", "probe", account_id=acct, booking_date=d)])
        prev = [x for x in store.recon_days() if x < d][-1:]
        nxt = store.next_recon_day(d)
        for day in prev + ([nxt] if nxt else []):
            col.add(store.statement(acct, day, "adjacent-day statement (context only; not a substitute for the missing day)"))
            col.add(store.confirmation(acct, day, "adjacent-day confirmation (context only; not a substitute)"))
        col.add(store.cashbook_on_date(acct, d, "cash-book entries posted on the date (firm's own record)"))
        col.add(store.batches_on_date(acct, d, "settlement batches due on the date"))
    if keys.get("file_id"):
        col.search(f"Source file {keys['file_id']}", {"file": keys["file_id"]}, [])


def plan_customer(store, keys, results, col):
    kind_cbal = keys.get("client_id")
    d, ccy = keys.get("date"), keys.get("currency")
    if not d or not ccy:
        return
    col.add(store.internal_record(ccy, d, "internal reconciliation record for the currency and date (as reported by the firm)"))
    if kind_cbal:
        client = keys["client_id"]
        prev = store.previous_snapshot_date(client, ccy, d)
        snaps = store.snapshots(client, ccy, {d} | ({prev} if prev else set()), "client balance snapshots either side of the roll-forward")
        col.add(snaps)
        if prev:
            txns = store.client_transactions(client, ccy, store.point(prev), store.point(d),
                                             "client transactions executed between the two snapshot points")
            col.add(txns)
            col.search(f"Transactions for {client} {ccy} executed after {prev} 17:00 and up to {d} 17:00",
                       {"file": "IN-11", "client_id": client, "currency": ccy, "window": [store.point(prev), store.point(d)]},
                       [t["evidence_id"] for t in txns])
            for t in txns:
                o = t["fields"].get("original_txn_id")
                if o:
                    col.add([store.get(f"IN-11:{o}", "original transaction of a refund")], t["evidence_id"], "refund.original_txn_id")
                lines = store.find("IN-13", "settlement line for the transaction", txn_id=t["fields"]["txn_id"])
                col.add(lines, t["evidence_id"], "line.txn_id = transaction.txn_id")
            refunds = store.find("IN-11", "refund transactions for the client", client_id=client, currency=ccy, txn_type="REFUND")
            col.search(f"All REFUND transactions for {client} {ccy} in the period", {"file": "IN-11", "client_id": client, "txn_type": "REFUND"},
                       [t["evidence_id"] for t in refunds])
            col.add(refunds)
        col.search(f"Posting-level client ledger for {client}", {"source": "client ledger postings"}, [])


def plan_unmatched(store, keys, results, col):
    be = store.get(f"IN-09:{keys['bank_entry_id']}", "bank entry named by the exception") if keys.get("bank_entry_id") else None
    if not be:
        return
    col.add([be])
    f = be["fields"]
    col.add([store.get(f"IN-08:{f['statement_id']}", "statement containing the entry")], be["evidence_id"], "entry.statement_id")
    col.add(store.confirmation(f["account_id"], f["booking_date"], "17:00 confirmation on the booking date"))
    col.add(store.external_record(f["account_id"], f["booking_date"], "external reconciliation record on the booking date"))
    col.add(store.cashbook_on_date(f["account_id"], f["booking_date"], "cash-book entries posted on the booking date"))
    col.add(store.batches_on_date(f["account_id"], f["booking_date"], "settlement batches due on the booking date"))
    hits = store.search_reference(f["account_id"], f["bank_reference"])
    found = [h for h in hits["found"] if h != be["evidence_id"]]
    col.search(f"Other records carrying reference '{f['bank_reference']}' (references, narratives, log)", hits["searched"], found)
    col.add([store.get(h, "record carrying the same reference") for h in found], be["evidence_id"], "same reference string")


PLANS = {"bank_ledger_mismatch": "bank", "settlement_discrepancy": "settlement", "missing_bank_evidence": "missing",
         "customer_balance_discrepancy": "customer", "unmatched_bank_entry": "unmatched"}


def apply_plan_for(exception, results, store, col, missing_items):
    from .routing import KIND_ROUTE
    kind, keys = parse_root(exception)
    route = KIND_ROUTE.get(kind)
    plan_cited(store, results, col)
    if route == "bank_ledger_mismatch":
        plan_bank_ledger(store, keys, results, col)
    elif route == "settlement_discrepancy":
        plan_settlement(store, keys, results, col)
    elif route == "missing_bank_evidence":
        plan_missing(store, keys, results, col, missing_items)
    elif route == "customer_balance_discrepancy":
        plan_customer(store, keys, results, col)
    elif route == "unmatched_bank_entry":
        plan_unmatched(store, keys, results, col)


def retrieve(route, case, store):
    """Run the plan for the route on the primary exception, then on related exceptions of a different kind."""
    col = Collector()
    x = case["exception"]
    apply_plan_for(x, case["results"], store, col, case["missing_items"])
    seen_kinds = {root_kind(x)}
    for rx in case["related_exceptions"]:
        k = root_kind(rx)
        if k not in seen_kinds or route == "unverified_relationship":
            seen_kinds.add(k)
            apply_plan_for(rx, case["related_results"].get(rx["exception_id"], []), store, col, case["missing_items"])
    return col


# --------------------------------------------------------------------------------------------------------------
# Packet
# --------------------------------------------------------------------------------------------------------------
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def detect_conflicts(case, col, control_results):
    conflicts = []

    def add(desc, ids):
        conflicts.append({"conflict_id": f"CONF-{len(conflicts) + 1:02d}", "description": desc, "evidence_ids": ids})
    for r in control_results:
        c, p = _num(r["computed"]), _num(r["reported"])
        if r["outcome"] == "FAIL" and c is not None and p is not None and c != p:
            add(f"Engine recomputed {r['computed']} but the firm's record reports {r['reported']} ({r['result_id']}).", [r["result_id"]])
        if len(conflicts) >= 20:
            break
    x = case["exception"]
    for e in col.records.values():
        f = e["fields"]
        if e["file_id"] == "IN-06" and f.get("timing_difference_claimed") == "true" and x["evidence_status"] == "NOT_EVIDENCED":
            add(f"External record {f['ext_recon_id']} claims a timing difference; the engine found no timing evidence.", [e["evidence_id"]])
        if e["file_id"] == "IN-14" and f.get("status") == "RESOLVED" and x["status"] == "OPEN":
            add(f"Discrepancy log {f['discrepancy_id']} is marked RESOLVED by the firm; the engine exception {x['exception_id']} "
                f"remains OPEN pending human review.", [e["evidence_id"], x["exception_id"]])
    return conflicts


def _result_view(r, exception_id):
    return {"result_id": r["result_id"], "for_exception": exception_id, "outcome": r["outcome"], "computed": r["computed"],
            "reported": r["reported"], "evidence_status": r["evidence_status"], "structured": r["structured"],
            "note": r["note"], "evidence_ids": r["evidence_ids"]}


def build_packet(case, scope, route, col):
    x = case["exception"]
    control_results = [_result_view(r, x["exception_id"]) for r in case["results"]]
    for eid, rs in sorted(case["related_results"].items()):
        control_results += [_result_view(r, eid) for r in rs]
    conflicts = detect_conflicts(case, col, control_results)
    exc_view = lambda e: {k: e[k] for k in ("exception_id", "severity", "status", "category", "root_cause", "account_id",
                                             "currency", "first_date", "last_date", "amount", "affected_results",
                                             "control_codes", "flags", "related_records", "cause_category", "evidence_status",
                                             "evidence_status_detail", "review_status", "investigation_group_id")}
    packet = {
        "packet_version": config.PACKET_VERSION,
        "pack_id": case["pack_id"], "pack_content_sha256": case["pack_content_sha256"],
        "investigation_route": route, "investigation_scope": scope,
        "exception": exc_view(x),
        "related_exceptions": [exc_view(e) for e in case["related_exceptions"]],
        "investigation_group": case["group"],
        "candidate_relationships": [dict(c, note="UNVERIFIED — NOT EVIDENCE-BACKED. Not a confirmed relationship.")
                                    for c in case["candidates"]],
        "control_results": control_results,
        "source_records": list(col.records.values()),
        "relationships": col.relationships,
        "searches": col.searches,
        "missing_evidence": case["missing_items"],
        "conflicts": conflicts,
        "retrieval_truncated": col.truncated,
        "conventions": {"bank_dc": "C = money into the account, D = money out (bank perspective)",
                        "cashbook_dc": "D = money in, C = money out (firm asset-ledger perspective)",
                        "transaction_direction": "CR increases the client balance, DR decreases it",
                        "difference_sign": "bank minus ledger (C08); resource minus requirement (C06)",
                        "reconciliation_point": "17:00 Europe/London each reconciliation day"},
    }
    packet["allowed_citation_ids"] = _citation_ids(case, packet["source_records"], control_results, col.searches, conflicts)
    packet["packet_sha256"] = hashlib.sha256(canonical(packet).encode("utf-8")).hexdigest()
    return packet


def _citation_ids(case, records, control_results, searches, conflicts):
    x = case["exception"]
    ids = {r["evidence_id"] for r in records} | {r["result_id"] for r in control_results}
    ids |= {x["exception_id"]} | {e["exception_id"] for e in case["related_exceptions"]}
    ids |= {s["search_id"] for s in searches} | {m["item_id"] for m in case["missing_items"]}
    ids |= {c["conflict_id"] for c in conflicts} | {c["candidate_id"] for c in case["candidates"]}
    if case["group"]:
        ids.add(case["group"]["group_id"])
    return sorted(ids)


def packet_json(packet):
    return json.dumps(packet, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------------------------------------------
# Evidence ledger (V2 tools mode): the initial packet plus everything retrieved by tools
# --------------------------------------------------------------------------------------------------------------
def collector_from_packet(ledger_or_packet):
    """A Collector holding a packet's (or ledger's) records, relationships and searches, for incremental retrieval.
    New SEARCH-nn IDs continue the existing numbering; the MAX_RECORDS cap applies to the accumulated total."""
    col = Collector()
    for r in ledger_or_packet["source_records"]:
        col.records[r["evidence_id"]] = r
    col.relationships = [dict(r) for r in ledger_or_packet["relationships"]]
    col.searches = [dict(s) for s in ledger_or_packet["searches"]]
    col.truncated = ledger_or_packet.get("retrieval_truncated", False)
    return col


def build_ledger(packet, case, col):
    """The accumulated evidence in packet form (so the V1 validator applies unchanged), with conflict detection re-run
    over all records and the citation set recomputed. Identified by its own SHA-256 and by the initial packet's hash."""
    conflicts = detect_conflicts(case, col, packet["control_results"])
    ledger = {k: v for k, v in packet.items() if k not in ("packet_sha256", "packet_version")}
    ledger.update({"ledger_version": config.LEDGER_VERSION, "initial_packet_sha256": packet["packet_sha256"],
                   "source_records": list(col.records.values()), "relationships": list(col.relationships),
                   "searches": list(col.searches), "conflicts": conflicts, "retrieval_truncated": col.truncated})
    ledger["allowed_citation_ids"] = _citation_ids(case, ledger["source_records"], packet["control_results"], col.searches, conflicts)
    ledger["ledger_sha256"] = hashlib.sha256(canonical(ledger).encode("utf-8")).hexdigest()
    return ledger
