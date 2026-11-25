"""Financial continuity between two consecutive reporting periods: the previous period's closing positions against the
next period's opening positions, by account, currency, client and receipt.

    python -m uc042lib.continuity <previous_case_dir> <current_case_dir>

Read-only and deterministic. Each case is read through the engine's own loader (uc042lib.validate.Validator: the same
structure and reporting-period rules), and the cash-book position uses the engine's own ledger function. Nothing is
recalculated beyond the comparison itself, and nothing is changed: a DIFFERENCE stays a difference (it is never carried
forward as resolved), and different accounting views (bank, cash book, client ledger, unallocated register) are compared
only with their own previous-period view, never with each other.

Comparisons:
  BANK         per account (safeguarding and own funds): previous period's last end-of-day statement closing balance
               (IN-08) = this period's first statement opening balance.
  CASH_BOOK    per safeguarding account: previous period's cash-book position at the opening point (all entries posted
               by the previous month-end reconciliation point, engine ledger function) = this period's OPENING_BALANCE
               row (IN-10).
  CLIENT       per client and currency: previous period's snapshot at the previous month-end point (IN-03) = this
               period's opening snapshot at the same point.
  UNALLOCATED  per receipt: receipts open at the previous month-end in the previous register (IN-04) = receipts this
               period's register shows as received before the period and not allocated before it.
Status per comparison: MATCH, DIFFERENCE or NOT_VERIFIABLE (with the reason). Without a previous period the result is a
single NOT_VERIFIABLE item: an opening position is never invented.
"""
import json
import sys
from datetime import date

from .money import parse_signed, parse_unsigned, signed
from .period import PeriodConfig, PeriodError
from .structure import parse_ts

MATCH, DIFFERENCE, NOT_VERIFIABLE = "MATCH", "DIFFERENCE", "NOT_VERIFIABLE"


def _engine_view(case_dir, period):
    from .validate import Validator
    v = Validator(case_dir, period)
    v.load()
    v.setup()
    return v


def _bank_signed(amount, dc):
    """Bank-perspective balance: C (in credit to the holder) positive, D negative."""
    value = parse_unsigned(amount)
    return value if dc == "C" else -value


def _item(view, key, status, previous="", current="", note="", evidence=()):
    return {"view": view, "key": key, "status": status, "previous_closing": previous, "current_opening": current,
            "difference": "", "note": note, "evidence": list(evidence)}


def _compare(view, key, prev_value, cur_value, prev_ev, cur_ev, fmt=str):
    item = _item(view, key, MATCH if prev_value == cur_value else DIFFERENCE, fmt(prev_value), fmt(cur_value),
                 evidence=[prev_ev, cur_ev])
    if prev_value != cur_value:
        item["difference"] = f"{cur_value - prev_value:.2f}"
        item["note"] = "opening position differs from the previous period's closing position; not adjusted"
    return item


def bank(prev, cur):
    out = []
    last = {}
    for r in prev.rows("IN-08"):
        if r["statement_date"] > last.get(r["account_id"], ("", None))[0]:
            last[r["account_id"]] = (r["statement_date"], r)
    first = {}
    for r in cur.rows("IN-08"):
        if r["statement_date"] < first.get(r["account_id"], ("9999", None))[0]:
            first[r["account_id"]] = (r["statement_date"], r)
    for acct in sorted(set(last) | set(first) | set(cur.accounts)):
        cls = cur.accounts.get(acct, prev.accounts.get(acct, {})).get("account_class", "")
        key = f"{acct} ({cls or 'unknown class'})"
        if acct not in last or acct not in first:
            out.append(_item("BANK", key, NOT_VERIFIABLE, note="no end-of-day statement in the " +
                             ("previous" if acct not in last else "current") + " period for this account"))
            continue
        p, c = last[acct][1], first[acct][1]
        if p["currency"] != c["currency"]:
            out.append(_item("BANK", key, NOT_VERIFIABLE, note=f"currency differs ({p['currency']} / {c['currency']})"))
            continue
        out.append(_compare("BANK", f"{key} {c['currency']}", _bank_signed(p["closing_balance_amount"], p["closing_balance_dc"]),
                            _bank_signed(c["opening_balance_amount"], c["opening_balance_dc"]),
                            f"IN-08:{p['statement_id']} closing", f"IN-08:{c['statement_id']} opening", fmt=lambda x: f"{x:.2f}"))
    return out


def cash_book(prev, cur, period):
    out = []
    point = period.opening_point()
    for acct in sorted(cur.sga or prev.sga):
        opening = [r for r in cur.rows("IN-10") if r["account_id"] == acct and r["entry_type"] == "OPENING_BALANCE"]
        if len(opening) != 1:
            out.append(_item("CASH_BOOK", acct, NOT_VERIFIABLE, note=f"{len(opening)} OPENING_BALANCE row(s) in the current period"))
            continue
        cur_value = signed(opening[0]["amount"], opening[0]["dc_indicator"], "cashbook")
        if parse_ts(opening[0]["posted_ts"]) != point:
            out.append(_item("CASH_BOOK", acct, NOT_VERIFIABLE, current=f"{cur_value:.2f}",
                             note=f"opening row posted {opening[0]['posted_ts']}, not at the opening point {period.opening_point_iso()}"))
            continue
        prev_value, rows, root = prev.ledger_at(acct, point)
        if prev_value is None:
            out.append(_item("CASH_BOOK", acct, NOT_VERIFIABLE, current=f"{cur_value:.2f}",
                             note="previous period's cash-book position cannot be established" + (f" ({root})" if root else "")))
            continue
        out.append(_compare("CASH_BOOK", f"{acct} {opening[0]['currency']}", prev_value, cur_value,
                            f"IN-10 previous period, {len(rows)} entries to {period.opening_point_iso()}",
                            f"IN-10:{opening[0]['ledger_entry_id']}", fmt=lambda x: f"{x:.2f}"))
    return out


def clients(prev, cur, period):
    out = []
    when = period.previous_end.isoformat()
    prev_snap = {(r["client_id"], r["currency"]): r for r in prev.rows("IN-03") if r["recon_date"] == when}
    cur_snap = {(r["client_id"], r["currency"]): r for r in cur.rows("IN-03") if r["recon_date"] == when}
    if not cur_snap:
        return [_item("CLIENT", "all clients", NOT_VERIFIABLE, note=f"no opening client snapshot at {when} in the current period")]
    if not prev_snap:
        return [_item("CLIENT", "all clients", NOT_VERIFIABLE,
                      note=f"the previous period has no client snapshot at {when} (not a reconciliation day there, or not supplied)")]
    for key in sorted(set(prev_snap) | set(cur_snap)):
        p, c = prev_snap.get(key), cur_snap.get(key)
        label = f"{key[0]} {key[1]}"
        if p is None or c is None:
            out.append(_item("CLIENT", label, DIFFERENCE, p["balance"] if p else "", c["balance"] if c else "",
                             note="client present in only one of the two snapshots"))
            continue
        out.append(_compare("CLIENT", label, parse_signed(p["balance"]), parse_signed(c["balance"]), f"IN-03:{p['snapshot_id']}",
                            f"IN-03:{c['snapshot_id']}", fmt=lambda x: f"{x:.2f}"))
    return out


def unallocated(prev, cur, period):
    end = period.previous_end

    def open_at_end(r):
        received = date.fromisoformat(r["receipt_date"])
        alloc = date.fromisoformat(r["allocated_date"]) if r["allocated_date"] else None
        return received <= end and (alloc is None or alloc > end)
    prev_open = {r["receipt_id"]: r for r in prev.rows("IN-04") if open_at_end(r)}
    cur_open = {r["receipt_id"]: r for r in cur.rows("IN-04") if open_at_end(r)}
    if not prev_open and not cur_open:
        return [_item("UNALLOCATED", "all receipts", MATCH, "0 open", "0 open", note="no receipt open at the boundary in either register")]
    out = []
    for rid in sorted(set(prev_open) | set(cur_open)):
        p, c = prev_open.get(rid), cur_open.get(rid)
        if p is None or c is None:
            out.append(_item("UNALLOCATED", rid, DIFFERENCE, p["amount"] if p else "", c["amount"] if c else "",
                             note="receipt open at the boundary in only one of the two registers"))
            continue
        same = (p["amount"], p["currency"]) == (c["amount"], c["currency"])
        out.append(_item("UNALLOCATED", f"{rid} {c['currency']}", MATCH if same else DIFFERENCE, p["amount"], c["amount"],
                         "" if same else "amount or currency differs", [f"IN-04:{rid} previous", f"IN-04:{rid} current"]))
    return out


def compare(previous_case, current_case, current_period=None, previous_period=None):
    """Continuity report {current_period, previous_period, status, items}. `previous_case` None: NOT_VERIFIABLE."""
    cur = _engine_view(current_case, current_period)
    period = cur.period
    if previous_case is None:
        return {"current_period": period.period_id, "previous_period": period.previous.period_id, "status": NOT_VERIFIABLE,
                "items": [_item("ALL", period.previous.period_id, NOT_VERIFIABLE,
                                note="the previous period is not available; opening positions cannot be verified and are not assumed")]}
    prev = _engine_view(previous_case, previous_period)
    if prev.period != period.previous:
        raise PeriodError(f"{prev.period.period_id} is not the period before {period.period_id}")
    items = bank(prev, cur) + cash_book(prev, cur, period) + clients(prev, cur, period) + unallocated(prev, cur, period)
    status = DIFFERENCE if any(i["status"] == DIFFERENCE for i in items) else \
        NOT_VERIFIABLE if any(i["status"] == NOT_VERIFIABLE for i in items) else MATCH
    return {"current_period": period.period_id, "previous_period": prev.period.period_id, "status": status, "items": items}


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python -m uc042lib.continuity <previous_case_dir> <current_case_dir>")
    print(json.dumps(compare(sys.argv[1], sys.argv[2]), indent=1))


if __name__ == "__main__":
    main()
