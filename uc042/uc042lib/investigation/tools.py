"""Read-only evidence tools for the V2 tool-calling investigation (UC042_INVESTIGATION_MODE=tools).

The model may only *request* these tools; Python validates every request against a strict Pydantic model and executes it
through the existing guarded EvidenceStore (hash-verified source files, forbidden files unreachable). Every returned
record is added through the existing Collector, so it carries the same provenance as packet records (evidence_id,
file, line, file SHA-256, retrieved_via, join_key). Empty results become SEARCH-nn items; nothing is ever defaulted to
zero. There are no write tools, no free-text predicates, no paths and no arbitrary joins: EvidenceStore.find/find_where
are used only inside fixed, typed tool functions and are never exposed.
"""
import json
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .. import schema
from ..structure import CURRENCIES, ID_RE
from . import config

TOOL_REGISTRY_VERSION = "uc042-evidence-tools/1.0"

_ID = ID_RE.pattern  # the engine's own identifier rule
_REF = r"^[A-Za-z0-9][A-Za-z0-9 ._:/#-]{0,63}$"
_DATE = r"^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"
_EVIDENCE_ID = r"^IN-(0[1-9]|1[0-4]):[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"  # CSV source records only (IN-01..IN-14)
Currency = Literal[tuple(sorted(CURRENCIES))]
TxnType = Literal[tuple(sorted(schema.ENUMS[("IN-11", "txn_type")]))]


class ToolInputError(ValueError):
    """Well-formed arguments that are not acceptable for this dataset (unknown account, wrong source file, ...)."""


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _span(date_from, date_to, max_days, required=False):
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from and date_to must be given together")
    if date_from is None:
        if required:
            raise ValueError("date_from and date_to are required")
        return
    try:
        a, b = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as e:
        raise ValueError(f"invalid date: {e}") from None
    if b < a:
        raise ValueError("date_to is before date_from")
    if (b - a).days + 1 > max_days:
        raise ValueError(f"date range longer than {max_days} days; narrow the search")


class GetSourceRecordArgs(_Args):
    evidence_id: str = Field(pattern=_EVIDENCE_ID, description="Evidence ID 'IN-xx:<primary key>' of a CSV source record")


class SearchBankEntriesArgs(_Args):
    account_id: str = Field(pattern=_ID, description="Bank account ID, for example SGA-GBP-01")
    bank_reference: Optional[str] = Field(pattern=_REF, description="Exact bank_reference or end_to_end_ref")
    date_from: Optional[str] = Field(pattern=_DATE, description="First booking date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(pattern=_DATE, description="Last booking date (YYYY-MM-DD)")

    @model_validator(mode="after")
    def _constrained(self):
        _span(self.date_from, self.date_to, config.TOOL_MAX_DATE_SPAN_DAYS, required=self.bank_reference is None)
        return self


class GetCashbookEntriesArgs(_Args):
    account_id: str = Field(pattern=_ID, description="Safeguarding account ID")
    payment_reference: Optional[str] = Field(pattern=_REF, description="Exact cash-book payment_reference")
    date_from: Optional[str] = Field(pattern=_DATE, description="First posting date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(pattern=_DATE, description="Last posting date (YYYY-MM-DD)")

    @model_validator(mode="after")
    def _constrained(self):
        _span(self.date_from, self.date_to, config.TOOL_MAX_DATE_SPAN_DAYS, required=self.payment_reference is None)
        return self


class GetSettlementBatchArgs(_Args):
    batch_id: str = Field(pattern=_ID, description="Settlement batch ID, for example SB-GBP-20260915")


class SearchCustomerTransactionsArgs(_Args):
    client_id: Optional[str] = Field(pattern=_ID, description="Client ID (requires date_from and date_to)")
    txn_id: Optional[str] = Field(pattern=_ID, description="Exact transaction ID (use alone)")
    date_from: Optional[str] = Field(pattern=_DATE, description="First execution date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(pattern=_DATE, description="Last execution date (YYYY-MM-DD)")
    transaction_type: Optional[TxnType] = Field(description="Optional txn_type filter")

    @model_validator(mode="after")
    def _constrained(self):
        if self.txn_id is not None:
            if any(v is not None for v in (self.client_id, self.date_from, self.date_to, self.transaction_type)):
                raise ValueError("txn_id must be used on its own")
            return self
        if self.client_id is None:
            raise ValueError("give txn_id, or client_id with date_from and date_to")
        _span(self.date_from, self.date_to, config.TOOL_MAX_CLIENT_SPAN_DAYS, required=True)
        return self


class GetCustomerBalanceSnapshotsArgs(_Args):
    client_id: str = Field(pattern=_ID, description="Client ID")
    currency: Currency = Field(description="One currency; GBP and EUR balances are never combined")
    date_from: str = Field(pattern=_DATE, description="First snapshot date (YYYY-MM-DD)")
    date_to: str = Field(pattern=_DATE, description="Last snapshot date (YYYY-MM-DD)")

    @model_validator(mode="after")
    def _constrained(self):
        _span(self.date_from, self.date_to, config.TOOL_MAX_CLIENT_SPAN_DAYS, required=True)
        return self


class GetReconciliationEvidenceArgs(_Args):
    account_id: str = Field(pattern=_ID, description="Safeguarding bank account ID")
    currency: Currency = Field(description="The account's currency")
    date: str = Field(pattern=_DATE, description="Reconciliation date (YYYY-MM-DD)")

    @model_validator(mode="after")
    def _constrained(self):
        _span(self.date, self.date, 1, required=True)
        return self


# relationship -> (source file, source field, target file, how the target is found, relationship label)
RELATIONSHIPS = {
    "settlement_line_to_transaction": ("IN-13", "txn_id", "IN-11", "pk", "line.txn_id = transaction.txn_id"),
    "settlement_line_to_batch": ("IN-13", "batch_id", "IN-12", "pk", "line.batch_id = batch.batch_id"),
    "transaction_to_batch": ("IN-11", "settlement_batch_id", "IN-12", "pk", "transaction.settlement_batch_id = batch.batch_id"),
    "refund_to_original_transaction": ("IN-11", "original_txn_id", "IN-11", "pk", "refund.original_txn_id = transaction.txn_id"),
    "settlement_batch_to_bank_entry": ("IN-12", "expected_bank_reference", "IN-09", "bank_ref",
                                       "bank.bank_reference|end_to_end_ref = batch.expected_bank_reference (same account)"),
    "cashbook_to_bank_entry": ("IN-10", "payment_reference", "IN-09", "bank_ref",
                               "bank.bank_reference|end_to_end_ref = cashbook.payment_reference (same account)"),
    "bank_entry_to_statement": ("IN-09", "statement_id", "IN-08", "pk", "entry.statement_id = statement.statement_id"),
    "external_recon_to_confirmation": ("IN-06", "bank_statement_id", "IN-07", "pk",
                                       "external_recon.bank_statement_id = confirmation.statement_id"),
}
Relationship = Literal[tuple(RELATIONSHIPS)]


class FollowRelationshipArgs(_Args):
    evidence_id: str = Field(pattern=_EVIDENCE_ID, description="A record already in the evidence (packet or earlier tool result)")
    relationship: Relationship = Field(description="One of the supported, verified relationship types")


# --------------------------------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------------------------------
class ToolCall:
    """Collects one tool call's records through the shared Collector, enforcing the per-call record limit."""

    def __init__(self, store, collector, name, max_records):
        self.store, self.col, self.name, self.max_records = store, collector, name, max_records
        self.ids, self.new_ids, self.search_ids, self.not_added = [], [], [], []
        self.truncated = False

    def via(self, what):
        return f"tool {self.name}: {what}"

    def add(self, items, rel_from=None, relationship=None):
        items = [i for i in items or [] if i]
        fresh = [i for i in items if i["evidence_id"] not in self.ids]
        room = self.max_records - len(self.ids)
        if len(fresh) > room:
            self.truncated = True
            fresh = fresh[:max(room, 0)]
        known = set(self.col.records)
        self.col.add(fresh, rel_from, relationship)
        for it in fresh:
            eid = it["evidence_id"]
            if eid not in self.col.records:  # the investigation-wide record cap was reached
                self.not_added.append(eid)
                continue
            self.ids.append(eid)
            if eid not in known:
                self.new_ids.append(eid)
        return [i["evidence_id"] for i in fresh]

    def search(self, description, query, found):
        sid = self.col.search(description, query, found)
        self.search_ids.append(sid)
        return sid

    def result(self, note=""):
        records = [{k: self.col.records[e][k] for k in ("evidence_id", "record_type", "source_file", "source_line",
                                                        "retrieved_via", "join_key", "fields")} for e in self.new_ids]
        return {"status": "OK" if self.ids else "NOT_FOUND", "evidence_ids": list(self.ids),
                "new_evidence_ids": list(self.new_ids), "already_in_evidence": [e for e in self.ids if e not in self.new_ids],
                "search_ids": list(self.search_ids), "truncated": self.truncated,
                "not_added_evidence_limit": list(self.not_added), "records": records, "note": note}


def _account(store, account_id, currency=None):
    hit = store.by_pk.get("IN-02", {}).get(account_id)
    if not hit:
        raise ToolInputError(f"unknown account_id {account_id!r}")
    row = hit[2]
    if currency and row["currency"] != currency:
        raise ToolInputError(f"account {account_id} is a {row['currency']} account, not {currency}")
    return row


def _in(d, a, b):
    return a is None or (d and a <= d <= b)


def get_source_record(a, call):
    it = call.store.get(a.evidence_id, call.via("record by evidence ID"))
    if it:
        call.add([it])
    else:
        call.search(f"Source record {a.evidence_id}", {"evidence_id": a.evidence_id}, [])


def search_bank_entries(a, call):
    _account(call.store, a.account_id)
    join = f"account_id={a.account_id}" + (f", reference={a.bank_reference}" if a.bank_reference else "") + \
           (f", booking_date {a.date_from}..{a.date_to}" if a.date_from else "")
    items = call.store.find_where("IN-09", call.via("bank statement entries"), join, lambda r: r["account_id"] == a.account_id and (
        a.bank_reference is None or a.bank_reference in (r["bank_reference"], r["end_to_end_ref"])) and _in(r["booking_date"], a.date_from, a.date_to))
    call.search(f"Bank entries on {a.account_id}" + (f" with reference '{a.bank_reference}'" if a.bank_reference else "") +
                (f" booked {a.date_from} to {a.date_to}" if a.date_from else ""), {"file": "IN-09", **a.model_dump()},
                call.add(items))


def get_cashbook_entries(a, call):
    _account(call.store, a.account_id)
    join = f"account_id={a.account_id}" + (f", payment_reference={a.payment_reference}" if a.payment_reference else "") + \
           (f", posted date {a.date_from}..{a.date_to}" if a.date_from else "")
    items = call.store.find_where("IN-10", call.via("cash-book entries"), join, lambda r: r["account_id"] == a.account_id and (
        a.payment_reference is None or r["payment_reference"] == a.payment_reference) and _in(r["posted_ts"][:10], a.date_from, a.date_to))
    call.search(f"Cash-book entries on {a.account_id}" + (f" with reference '{a.payment_reference}'" if a.payment_reference else "") +
                (f" posted {a.date_from} to {a.date_to}" if a.date_from else ""), {"file": "IN-10", **a.model_dump()},
                call.add(items))


def get_settlement_batch(a, call):
    b = call.store.get(f"IN-12:{a.batch_id}", call.via("settlement batch header"))
    if not b:
        call.search(f"Settlement batch {a.batch_id}", {"file": "IN-12", "batch_id": a.batch_id}, [])
        return
    call.add([b])
    lines = call.store.lines_of_batch(a.batch_id, call.via("settlement lines of the batch"))
    call.add(lines, b["evidence_id"], "line.batch_id")
    for ln in lines:
        t = ln["fields"]["txn_id"]
        if not t or ln["evidence_id"] not in call.ids:
            continue
        tx = call.store.get(f"IN-11:{t}", call.via("transaction referenced by a settlement line"))
        if tx:
            call.add([tx], ln["evidence_id"], "line.txn_id = transaction.txn_id")
        else:
            call.search(f"Transaction {t} referenced by settlement line {ln['fields']['line_id']}", {"file": "IN-11", "txn_id": t}, [])


def search_customer_transactions(a, call):
    if a.txn_id:
        tx = call.store.get(f"IN-11:{a.txn_id}", call.via("transaction by ID"))
        call.search(f"Transaction {a.txn_id}", {"file": "IN-11", "txn_id": a.txn_id}, call.add([tx]) if tx else [])
        return
    join = f"client_id={a.client_id}, executed date {a.date_from}..{a.date_to}" + (f", txn_type={a.transaction_type}" if a.transaction_type else "")
    items = call.store.find_where("IN-11", call.via("client transactions"), join, lambda r: r["client_id"] == a.client_id and (
        a.transaction_type is None or r["txn_type"] == a.transaction_type) and _in(r["executed_ts"][:10], a.date_from, a.date_to))
    call.search(f"Transactions for {a.client_id} executed {a.date_from} to {a.date_to}" +
                (f" of type {a.transaction_type}" if a.transaction_type else ""), {"file": "IN-11", **a.model_dump()}, call.add(items))


def get_customer_balance_snapshots(a, call):
    join = f"client_id={a.client_id}, currency={a.currency}, recon_date {a.date_from}..{a.date_to}"
    items = call.store.find_where("IN-03", call.via("client balance snapshots"), join, lambda r: r["client_id"] == a.client_id and
                                  r["currency"] == a.currency and _in(r["recon_date"], a.date_from, a.date_to))
    call.search(f"{a.currency} balance snapshots for {a.client_id} from {a.date_from} to {a.date_to}",
                {"file": "IN-03", **a.model_dump()}, call.add(items))


def get_reconciliation_evidence(a, call):
    _account(call.store, a.account_id, a.currency)
    s, acct, d = call.store, a.account_id, a.date
    parts = [("IN-06", f"External reconciliation record for {acct} on {d}", s.external_record(acct, d, call.via("external reconciliation record"))),
             ("IN-07", f"17:00 bank balance confirmation for {acct} on {d}", s.confirmation(acct, d, call.via("17:00 bank balance confirmation"))),
             ("IN-08", f"End-of-day bank statement for {acct} on {d}", s.statement(acct, d, call.via("end-of-day bank statement"))),
             ("IN-05", f"Internal {a.currency} reconciliation record on {d}", s.internal_record(a.currency, d, call.via("internal reconciliation record")))]
    for fid, desc, items in parts:
        call.search(desc, {"file": fid, "account_id": acct if fid != "IN-05" else None, "currency": a.currency, "date": d}, call.add(items))
    erl_ids = {i["fields"]["ext_recon_id"] for i in parts[0][2]}
    logs = s.discrepancy_log_for(erl_ids, call.via("discrepancy log entry referencing the reconciliation record"))
    for lg in logs:
        call.add([lg], f"IN-06:{lg['fields']['recon_ref']}", "discrepancy_log.recon_ref")


def follow_relationship(a, call):
    src_file, field, target, how, label = RELATIONSHIPS[a.relationship]
    source = call.col.records.get(a.evidence_id)
    if source is None:
        raise ToolInputError(f"{a.evidence_id} is not in the evidence yet; relationships start from a record already retrieved")
    if source["file_id"] != src_file:
        raise ToolInputError(f"{a.relationship} starts from a {src_file} record, not {source['file_id']}")
    value = source["fields"].get(field, "")
    desc = f"{a.relationship} from {a.evidence_id}"
    if not value:
        call.search(f"{desc}: the source record has no {field}", {"evidence_id": a.evidence_id, "relationship": a.relationship}, [])
        return
    if how == "pk":
        found = call.store.get(f"{target}:{value}", call.via(f"{a.relationship} from {a.evidence_id}"))
        items = [found] if found else []
    else:
        items = call.store.bank_entries_by_reference(source["fields"]["account_id"], value, call.via(f"{a.relationship} from {a.evidence_id}"))
    call.search(f"{desc} ({field}={value})", {"evidence_id": a.evidence_id, "relationship": a.relationship, "value": value},
                call.add(items, a.evidence_id, label))


class Tool:
    def __init__(self, name, description, args_model, fn):
        self.name, self.description, self.args_model, self.fn = name, description, args_model, fn


REGISTRY = {t.name: t for t in (
    Tool("get_source_record", "Retrieve one CSV source record (IN-01..IN-14) by its evidence ID 'IN-xx:<primary key>'.",
         GetSourceRecordArgs, get_source_record),
    Tool("search_bank_entries", "Find bank statement entries (IN-09) on one account by exact bank/end-to-end reference and/or a "
         f"booking-date range of at most {config.TOOL_MAX_DATE_SPAN_DAYS} days. A reference or a date range is required.",
         SearchBankEntriesArgs, search_bank_entries),
    Tool("get_cashbook_entries", "Retrieve the firm's safeguarding cash-book entries (IN-10) on one account by exact payment "
         f"reference and/or a posting-date range of at most {config.TOOL_MAX_DATE_SPAN_DAYS} days.",
         GetCashbookEntriesArgs, get_cashbook_entries),
    Tool("get_settlement_batch", "Retrieve a settlement batch header (IN-12), its settlement lines (IN-13) and the client "
         "transactions (IN-11) the lines reference. Referenced transactions that are not in the data are reported as not found.",
         GetSettlementBatchArgs, get_settlement_batch),
    Tool("search_customer_transactions", "Retrieve client transactions (IN-11): either one exact txn_id on its own, or one client's "
         f"transactions executed within a date range of at most {config.TOOL_MAX_CLIENT_SPAN_DAYS} days (optional txn_type filter).",
         SearchCustomerTransactionsArgs, search_customer_transactions),
    Tool("get_customer_balance_snapshots", "Retrieve one client's 17:00 balance snapshots (IN-03) in one currency over a date range.",
         GetCustomerBalanceSnapshotsArgs, get_customer_balance_snapshots),
    Tool("get_reconciliation_evidence", "Retrieve, for one account, currency and date: the firm's external reconciliation record "
         "(IN-06), the 17:00 bank balance confirmation (IN-07), the end-of-day statement header (IN-08), the internal "
         "reconciliation record for the currency (IN-05) and discrepancy-log entries referencing the external record (IN-14).",
         GetReconciliationEvidenceArgs, get_reconciliation_evidence),
    Tool("follow_relationship", "Follow one supported, verified relationship from a record already in the evidence: "
         + ", ".join(RELATIONSHIPS) + ". No other joins are possible.", FollowRelationshipArgs, follow_relationship),
)}


def parse_request(name, raw_arguments):
    """Validate a model's tool request. Returns (args_model, None) or (None, error message). Never executes anything."""
    tool = REGISTRY.get(name)
    if tool is None:
        return None, f"unknown tool {str(name)[:80]!r}; available tools: {sorted(REGISTRY)}"
    try:
        data = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except (TypeError, json.JSONDecodeError) as e:
        return None, f"arguments are not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, "arguments must be a JSON object"
    try:
        return tool.args_model.model_validate(data), None
    except ValidationError as e:
        return None, "invalid arguments: " + "; ".join(f"{'.'.join(map(str, err['loc'])) or 'arguments'}: {err['msg']}"
                                                         for err in e.errors()[:6])


def execute(name, args, store, collector, max_records=None):
    """Run a validated tool. Returns the result dict; raises ToolInputError for dataset-level rejections."""
    call = ToolCall(store, collector, name, max_records or config.TOOL_MAX_RECORDS_PER_CALL)
    REGISTRY[name].fn(args, call)
    note = "Results truncated at the per-call record limit; narrow the request." if call.truncated else ""
    if call.not_added:
        note = (note + " " if note else "") + "The investigation's evidence limit was reached; some records were not added."
    return call.result(note)
