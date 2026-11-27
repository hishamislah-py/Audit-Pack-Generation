"""Stage E: independent offline validation of the generated suite (never imports or runs UC-042 engine code).

Usage (from the suite root):  py -3.11 -I tools/validate_suite.py
Writes validation/validation_results.json and prints a summary; exit code 0 only if every check passes.

What it does, per case directory (each initial submission and each corrected case, plus the clean baseline as a control):
  S  structure   headers vs the schema contract snapshot; types, enums, mandatory and conditional fields; keys; period; references
  R  recon       its own recomputation: bank and ledger at 17:00, requirement and resource, reported-vs-recomputed, client
                 roll-forwards, statements and continuity, batches and lines, reference matching (incl. many-to-one claims),
                 timing items, register, refunds, currency, coverage. Output: a set of findings + key figures.
  M  mutations   file-level diff against the baseline (or the initial submission for corrections) == mutations.json exactly;
                 untouched files byte-identical; unchanged rows keep their exact text and order
  F  FIN key     findings == financial_answer_key expected_anomalies exactly; figures equal
  P  packaging   manifest hashes/counts, scenario.json, upload ZIP contents, expected-result JSON structure
"""
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as contract_mod  # noqa: E402
from scenario_specs import SCENARIOS  # noqa: E402

SUITE = Path(__file__).resolve().parent.parent
BASE = SUITE / "shared_baseline"
C = contract_mod.Contract(contract_mod.load())
LON = ZoneInfo("Europe/London")
PSTART, PEND, PERIOD_ID = date(2026, 9, 1), date(2026, 9, 30), "PER-2026-09"
Z = Decimal("0.00")
SIGN = {"bank": {"C": 1, "D": -1}, "cash": {"D": 1, "C": -1}, "client": {"CR": 1, "DR": -1}, "settle": {"C": 1, "D": -1}}
RX = {"id": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"), "amount": re.compile(r"^\d+\.\d{2}$"),
      "signed": re.compile(r"^-?\d+\.\d{2}$"), "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"), "int": re.compile(r"^\d+$")}
EW_HOLIDAYS_2026 = {date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31),
                    date(2026, 12, 25), date(2026, 12, 28)}  # England and Wales 2026 (public list); none fall in Sep-Oct 2026


def fmt(d):
    return f"{d.quantize(Decimal('0.01')):f}"


def ts(s):
    return datetime.fromisoformat(s)


def ldate(s):
    return ts(s).astimezone(LON).date()


def point(d):
    return datetime.combine(d, time(17, 0), tzinfo=LON)


def next_business_day(d):
    d += timedelta(days=1)
    while d.weekday() >= 5 or d in EW_HOLIDAYS_2026:
        d += timedelta(days=1)
    return d


def sgn(amount, ind, kind):
    return Decimal(amount) * SIGN[kind][ind]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ loading
def load(case):
    case = Path(case)
    data, raw, errors = {}, {}, []
    for fid in C.csv:
        p = case / "source_data" / C.filename(fid)
        if not p.exists():
            errors.append(f"{fid} missing file {p.name}")
            continue
        b = p.read_bytes()
        raw[fid] = b
        try:
            text = b.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{fid} not UTF-8")
            continue
        if text.startswith("﻿"):
            errors.append(f"{fid} has a BOM (baseline has none)")
        if "\r" in text:
            errors.append(f"{fid} contains CR line endings (baseline uses LF)")
        rd = csv.DictReader(io.StringIO(text, newline=""))
        rows = []
        for i, r in enumerate(rd, start=2):
            r["_line"] = i
            rows.append(r)
        data[fid] = (rd.fieldnames, rows)
    return data, raw, errors


# ------------------------------------------------------------------------------------------------ S: structure
def field_error(t, v, allowed):
    if allowed is not None:
        return None if v in allowed else f"not one of {sorted(allowed)}"
    try:
        if t in RX and not RX[t].match(v):
            return f"invalid {t}"
        if t == "date":
            date.fromisoformat(v)
        if t == "ts":
            if ts(v).tzinfo is None:
                return "timestamp without offset"
        if t == "bool" and v not in ("true", "false"):
            return "not true/false"
        if t == "ccy" and v not in ("GBP", "EUR"):
            return "unsupported currency"
    except ValueError:
        return f"invalid {t}"
    return None


def structure(data):
    errs = []
    for fid, (header, rows) in data.items():
        if header != C.columns(fid):
            errs.append(f"{fid} header differs from the canonical schema")
            continue
        if not rows and fid not in C.empty_allowed:
            errs.append(f"{fid} has no data rows")
        types, mand, pk, seen = C.types(fid), set(C.mandatory(fid)), C.pk(fid), {}
        for r in rows:
            if None in r or any(r.get(c) is None for c in types):
                errs.append(f"{fid} L{r['_line']} wrong number of fields")
                continue
            for c, t in types.items():
                v = r[c]
                if v == "":
                    if c in mand:
                        errs.append(f"{fid} L{r['_line']} {c} required value missing")
                    continue
                e = field_error(t, v, C.enums.get((fid, c)))
                if e:
                    errs.append(f"{fid} L{r['_line']} {c}={v!r}: {e}")
            for f, c, cond, desc in contract_mod.CONDITIONAL:
                if f == fid and r[c] == "" and cond(r):
                    errs.append(f"{fid} L{r['_line']} {c} missing ({desc})")
            if r[pk] in seen:
                errs.append(f"{fid} L{r['_line']} duplicate key {r[pk]} (first L{seen[r[pk]]})")
            seen[r[pk]] = r["_line"]
    if errs:
        return errs
    R = {fid: rows for fid, (h, rows) in data.items()}
    inp = lambda d: PSTART <= d <= PEND
    # period rules (schema.PERIOD_RULES, re-implemented)
    cal = [date.fromisoformat(r["calendar_date"]) for r in R["IN-01"]]
    if sorted(cal) != [PSTART + timedelta(days=i) for i in range(30)]:
        errs.append("IN-01 does not hold every September date exactly once")
    errs += [f"IN-01 {r['calendar_date']} period_id {r['period_id']}" for r in R["IN-01"] if r["period_id"] != PERIOD_ID]
    for r in R["IN-03"]:
        d = date.fromisoformat(r["recon_date"])
        if not inp(d) and not (r["recon_date"] == "2026-08-31" and r["as_at_ts"] == "2026-08-31T17:00:00+01:00"):
            errs.append(f"IN-03 {r['snapshot_id']} out of period")
    for r in R["IN-04"]:
        if ldate(r["receipt_ts"]) > PEND or date.fromisoformat(r["receipt_date"]) > PEND or (r["allocated_ts"] and ldate(r["allocated_ts"]) < PSTART):
            errs.append(f"IN-04 {r['receipt_id']} not open during the period")
    simple = {"IN-05": ("recon_date", False), "IN-06": ("recon_date", False), "IN-07": ("as_at_ts", True), "IN-08": ("statement_date", False),
              "IN-09": ("booking_date", False), "IN-11": ("executed_ts", True), "IN-12": ("settlement_date", False)}
    for fid, (fld, is_ts) in simple.items():
        for r in R[fid]:
            d = ldate(r[fld]) if is_ts else date.fromisoformat(r[fld])
            if not inp(d):
                errs.append(f"{fid} {r[C.pk(fid)]} {fld} {r[fld]} out of period")
    errs += [f"IN-09 {r['bank_entry_id']} booking_ts out of period" for r in R["IN-09"] if not inp(ldate(r["booking_ts"]))]
    for r in R["IN-10"]:
        if not inp(ldate(r["posted_ts"])) and not (r["entry_type"] == "OPENING_BALANCE" and r["posted_ts"] == "2026-08-31T17:00:00+01:00"):
            errs.append(f"IN-10 {r['ledger_entry_id']} out of period")
    events = {r["recon_run_id"]: r["recon_date"] for r in R["IN-05"]} | {r["ext_recon_id"]: r["recon_date"] for r in R["IN-06"]}
    for r in R["IN-14"]:
        if r["recon_ref"] not in events:
            errs.append(f"IN-14 {r['discrepancy_id']} recon_ref {r['recon_ref']} not an IN-05/IN-06 record")
        elif ldate(r["logged_ts"]) < date.fromisoformat(events[r["recon_ref"]]):
            errs.append(f"IN-14 {r['discrepancy_id']} logged before its reconciliation")
    # references
    accts = {r["account_id"] for r in R["IN-02"]}
    for fid in ("IN-06", "IN-07", "IN-08", "IN-09", "IN-10", "IN-12", "IN-14"):
        errs += [f"{fid} {r[C.pk(fid)]} unknown account {r['account_id']}" for r in R[fid] if r["account_id"] not in accts]
    eod = {r["statement_id"]: r for r in R["IN-08"]}
    errs += [f"IN-09 {r['bank_entry_id']} unknown statement {r['statement_id']}" for r in R["IN-09"] if r["statement_id"] not in eod]
    bc = {r["statement_id"] for r in R["IN-07"]}
    errs += [f"IN-06 {r['ext_recon_id']} unknown bank_statement_id" for r in R["IN-06"] if r["bank_statement_id"] not in bc]
    batches = {r["batch_id"] for r in R["IN-12"]}
    errs += [f"IN-13 {r['line_id']} unknown batch" for r in R["IN-13"] if r["batch_id"] not in batches]
    errs += [f"IN-11 {r['txn_id']} unknown batch" for r in R["IN-11"] if r["settlement_batch_id"] and r["settlement_batch_id"] not in batches]
    pools = {r["asset_pool_id"] for r in R["IN-02"] if r["asset_pool_id"]}
    errs += [f"{fid} {r[C.pk(fid)]} unknown pool" for fid in ("IN-03", "IN-05") for r in R[fid] if r["asset_pool_id"] not in pools]
    return errs


# ------------------------------------------------------------------------------------------------ R: recomputation
def recon(data):
    R = {fid: rows for fid, (h, rows) in data.items()}
    out, fig = set(), {}
    add = out.add
    cal = {date.fromisoformat(r["calendar_date"]): r["is_recon_day"] == "true" for r in R["IN-01"]}
    recon_days = sorted(d for d, v in cal.items() if v)
    accounts = {r["account_id"]: r for r in R["IN-02"]}
    sga = sorted(a for a, r in accounts.items() if r["account_class"] == "RELEVANT_FUNDS_BANK")
    ccy_of = {a: r["currency"] for a, r in accounts.items()}
    acct_of_ccy = {ccy_of[a]: a for a in sga}
    eod = {r["statement_id"]: r for r in R["IN-08"]}
    ents = defaultdict(list)
    for e in R["IN-09"]:
        ents[e["statement_id"]].append(e)
    bc = {r["statement_id"]: r for r in R["IN-07"]}
    bc_by = {(r["account_id"], ldate(r["as_at_ts"])): r for r in R["IN-07"]}
    eod_by = {(r["account_id"], date.fromisoformat(r["statement_date"])): r for r in R["IN-08"]}
    cash = R["IN-10"]
    txn = {t["txn_id"]: t for t in R["IN-11"]}

    # records on non-reconciliation days (informational, but must be intended)
    for fid, fld, f in (("IN-07", "as_at_ts", ldate), ("IN-08", "statement_date", date.fromisoformat), ("IN-09", "booking_date", date.fromisoformat)):
        for r in R[fid]:
            d = f(r[fld])
            if not cal.get(d, False):
                add(f"NON_RECON_DAY_RECORD {fid} {r[C.pk(fid)]} {d}")
    # statements, continuity, confirmations
    for sid, s in eod.items():
        es = ents[sid]
        tot = sum((sgn(e["amount"], e["dc_indicator"], "bank") for e in es), Z)
        o, c = sgn(s["opening_balance_amount"], s["opening_balance_dc"], "bank"), sgn(s["closing_balance_amount"], s["closing_balance_dc"], "bank")
        if len(es) != int(s["entry_count"]):
            add(f"STATEMENT {sid} entry_count={s['entry_count']} entries={len(es)}")
        if o + tot != c:
            add(f"STATEMENT {sid} arithmetic opening={fmt(o)} entries={fmt(tot)} closing={fmt(c)}")
        for e in es:
            if (e["account_id"], e["currency"], e["booking_date"]) != (s["account_id"], s["currency"], s["statement_date"]) or ldate(e["booking_ts"]) != date.fromisoformat(s["statement_date"]):
                add(f"STATEMENT {sid} entry {e['bank_entry_id']} parent mismatch")
    by_acct = defaultdict(list)
    for s in eod.values():
        by_acct[s["account_id"]].append(s)
    opening_cash = {c["account_id"]: sgn(c["amount"], c["dc_indicator"], "cash") for c in cash if c["entry_type"] == "OPENING_BALANCE"}
    for a, ss in by_acct.items():
        ss.sort(key=lambda s: s["statement_date"])
        if a in sga and sgn(ss[0]["opening_balance_amount"], ss[0]["opening_balance_dc"], "bank") != opening_cash.get(a):
            add(f"OPENING {a} bank/cash-book opening differ")
        for p, c in zip(ss, ss[1:]):
            pc, co = sgn(p["closing_balance_amount"], p["closing_balance_dc"], "bank"), sgn(c["opening_balance_amount"], c["opening_balance_dc"], "bank")
            if pc != co:
                add(f"CONTINUITY {a} {p['statement_id']}->{c['statement_id']} closing={fmt(pc)} opening={fmt(co)}")
    for sid, b in bc.items():
        s = eod_by.get((b["account_id"], ldate(b["as_at_ts"])))
        if s is None:
            add(f"CONFIRMATION {sid} no statement for its day")
            continue
        derived = sgn(s["opening_balance_amount"], s["opening_balance_dc"], "bank") + sum(
            (sgn(e["amount"], e["dc_indicator"], "bank") for e in ents[s["statement_id"]] if ts(e["booking_ts"]) <= ts(b["as_at_ts"])), Z)
        got = sgn(b["balance_amount"], b["balance_dc_indicator"], "bank")
        if got != derived:
            add(f"CONFIRMATION {sid} confirmed={fmt(got)} derived={fmt(derived)}")
        if ts(b["as_at_ts"]).astimezone(LON).time() != time(17, 0):
            add(f"CONFIRMATION {sid} not at 17:00")

    def ledger(a, when):
        return sum((sgn(c["amount"], c["dc_indicator"], "cash") for c in cash if c["account_id"] == a and ts(c["posted_ts"]) <= when), Z)

    # bank vs ledger, discrepancy log
    logs = defaultdict(list)
    for x in R["IN-14"]:
        logs[x["recon_ref"]].append(x["discrepancy_id"])
    diff_refs = set()
    for a in sga:
        for d in sorted(set(recon_days) | {d for (aa, d) in bc_by if aa == a}):
            b = bc_by.get((a, d))
            led = ledger(a, point(d))
            fig[f"ledger_1700|{d}/{a}"] = fmt(led)
            if b is None:
                if d in recon_days:
                    add(f"COVERAGE IN-07 {d} {a} missing")
                continue
            bank = sgn(b["balance_amount"], b["balance_dc_indicator"], "bank")
            fig[f"bank_1700|{d}/{a}"] = fmt(bank)
            if bank != led:
                add(f"BL_DIFF {d} {a} {fmt(bank - led)}")
                ref = f"ERL-{a}-{d:%Y%m%d}"
                diff_refs.add(ref)
                add(f"BL_DIFF_LOGGED {d} {a} {','.join(sorted(logs[ref]))}" if logs.get(ref) else f"BL_DIFF_NOT_LOGGED {d} {a}")
    for ref, ids in logs.items():
        if ref not in diff_refs:
            add(f"LOG_WITHOUT_DIFFERENCE {','.join(sorted(ids))} {ref}")
    # IN-06 reported values
    for e in R["IN-06"]:
        d, a = date.fromisoformat(e["recon_date"]), e["account_id"]
        led = ledger(a, point(d))
        b = bc.get(e["bank_statement_id"])
        if b is None or b["account_id"] != a or ldate(b["as_at_ts"]) != d:
            add(f"REPORTED IN-06 {e['ext_recon_id']} bank_statement_id does not match account/day")
            continue
        bank = sgn(b["balance_amount"], b["balance_dc_indicator"], "bank")
        for fld, val in (("ledger_balance_reported", led), ("bank_balance_reported", bank), ("difference_reported", bank - led)):
            if Decimal(e[fld]) != val:
                add(f"REPORTED IN-06 {e['ext_recon_id']} {fld} reported={e[fld]} recomputed={fmt(val)}")
    # requirement and resource (IN-05)
    snaps = defaultdict(list)
    for r in R["IN-03"]:
        snaps[(date.fromisoformat(r["recon_date"]), r["currency"])].append(r)
    for run in R["IN-05"]:
        d, ccy = date.fromisoformat(run["recon_date"]), run["currency"]
        pt = point(d)
        req = sum((max(Z, Decimal(r["balance"])) for r in snaps[(d, ccy)]), Z) + sum(
            (Decimal(u["amount"]) for u in R["IN-04"] if u["currency"] == ccy and ts(u["receipt_ts"]) <= pt
             and (u["allocated_ts"] == "" or ts(u["allocated_ts"]) > pt)), Z)
        item_a = ledger(acct_of_ccy[ccy], pt)
        res = item_a + sum((Decimal(run[k]) for k in ("item_b", "item_c", "item_d")), Z)
        fig[f"requirement_1700|{d}/{ccy}"], fig[f"resource_1700|{d}/{ccy}"] = fmt(req), fmt(res)
        if res != req:
            add(f"RR_DIFF {d} {ccy} {fmt(res - req)}")
        for fld, val in (("requirement_reported", req), ("item_a", item_a), ("resource_reported", res), ("difference_reported", res - req)):
            if Decimal(run[fld]) != val:
                add(f"REPORTED IN-05 {run['recon_run_id']} {fld} reported={run[fld]} recomputed={fmt(val)}")
    # client roll-forward
    by_client = defaultdict(dict)
    for r in R["IN-03"]:
        by_client[(r["currency"], r["client_id"])][date.fromisoformat(r["recon_date"])] = Decimal(r["balance"])
        if Decimal(r["balance"]) < Z:
            add(f"NEGATIVE_SNAPSHOT {r['snapshot_id']}")
    moves = defaultdict(list)
    for t in R["IN-11"]:
        moves[(t["currency"], t["client_id"])].append((ts(t["executed_ts"]), sgn(t["amount"], t["direction"], "client")))
    for key, days in by_client.items():
        ds = sorted(days)
        for p, c in zip(ds, ds[1:]):
            rf = days[p] + sum((m for when, m in moves[key] if point(p) < when <= point(c)), Z)
            sc = f"{key[0]}/{key[1]} {c}"
            fig[f"rollforward|{sc}"], fig[f"snapshot|{sc}"] = fmt(rf), fmt(days[c])
            if rf != days[c]:
                add(f"ROLLFWD {sc} {fmt(rf - days[c])}")
    # batches, lines, batch to bank, top-ups
    lines = defaultdict(list)
    for ln in R["IN-13"]:
        lines[ln["batch_id"]].append(ln)
    bank_sga = [e for e in R["IN-09"] if e["account_id"] in sga]
    for b in R["IN-12"]:
        ls = lines[b["batch_id"]]
        tot = lambda t: sum((Decimal(x["amount"]) for x in ls if x["line_type"] == t), Z)
        net = Decimal(b["net_amount_reported"]) * (1 if b["direction"] == "TO_FIRM" else -1)
        for comp, val, hdr in (("TXN", tot("TXN"), Decimal(b["gross_amount"])), ("FEE", tot("FEE"), Decimal(b["total_fees"])),
                               ("REFUND", tot("REFUND"), Decimal(b["total_adjustments"])),
                               ("NET", sum((sgn(x["amount"], x["dc_indicator"], "settle") for x in ls), Z), net)):
            if val != hdr:
                add(f"BATCH_ARITH {b['batch_id']} {comp} lines={fmt(val)} header={fmt(hdr)}")
        for x in ls:
            if x["currency"] != b["currency"]:
                add(f"CURRENCY IN-13 {x['line_id']}")
            if x["line_type"] in ("TXN", "REFUND"):
                t = txn.get(x["txn_id"])
                if t is None:
                    add(f"LINE_TXN {x['line_id']} {x['txn_id']} missing")
                elif t["settlement_batch_id"] != b["batch_id"]:
                    add(f"LINE_TXN {x['line_id']} {x['txn_id']} batch line={b['batch_id']} txn={t['settlement_batch_id']}")
                elif t["amount"] != x["amount"]:
                    add(f"LINE_TXN {x['line_id']} {x['txn_id']} amount line={x['amount']} txn={t['amount']}")
        hits = [e for e in bank_sga if e["account_id"] == b["account_id"] and e["bank_reference"] == b["expected_bank_reference"]]
        if len(hits) != 1:
            add(f"BATCH_BANK {b['batch_id']} matches={len(hits)}")
        else:
            e = hits[0]
            if sgn(e["amount"], e["dc_indicator"], "bank") != net:
                add(f"BATCH_BANK_AMOUNT {b['batch_id']} net={fmt(net)} bank={fmt(sgn(e['amount'], e['dc_indicator'], 'bank'))}")
            if e["booking_date"] != b["settlement_date"]:
                add(f"BATCH_LAG {b['batch_id']} settlement={b['settlement_date']} booked={e['booking_date']}")
        if Decimal(b["total_fees"]) > Z:
            ref = f"TOPUP-{b['currency']}-{b['settlement_date'].replace('-', '')}"
            s_cr = [e for e in R["IN-09"] if e["bank_reference"] == ref and e["account_id"] == b["account_id"] and e["dc_indicator"] == "C"]
            o_db = [e for e in R["IN-09"] if e["bank_reference"] == ref and accounts.get(e["account_id"], {}).get("account_class") == "OWN_FUNDS" and e["dc_indicator"] == "D"]
            cb = [c for c in cash if c["payment_reference"] == ref and c["entry_type"] == "OWN_FUNDS_TOPUP"]
            fees = Decimal(b["total_fees"])
            if not (len(s_cr) == len(o_db) == len(cb) == 1 and all(Decimal(x["amount"]) == fees for x in s_cr + o_db + cb)
                    and s_cr[0]["booking_date"] == b["settlement_date"]):
                add(f"TOPUP {b['batch_id']} incomplete")
    batch_of = {b["batch_id"]: b for b in R["IN-12"]}
    for t in R["IN-11"]:
        if t["txn_type"] in ("LOAD_CARD", "SPEND", "REFUND"):
            n = sum(1 for x in lines[t["settlement_batch_id"]] if x["txn_id"] == t["txn_id"])
            if n != 1:
                add(f"TXN_LINE {t['txn_id']} lines={n}")
            if t["currency"] != batch_of.get(t["settlement_batch_id"], {}).get("currency"):
                add(f"CURRENCY IN-11 {t['txn_id']}")
    # cash book <-> bank by reference; many-to-one claims; timing items
    by_ref = defaultdict(list)
    for e in bank_sga:
        for rf in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
            by_ref[(e["account_id"], rf)].append(e)
    claims = defaultdict(list)
    for c in cash:
        if c["entry_type"] == "OPENING_BALANCE":
            continue
        hits = {e["bank_entry_id"]: e for e in by_ref.get((c["account_id"], c["payment_reference"]), [])}
        if not hits:
            add(f"CASH_NO_BANK {c['ledger_entry_id']} ref={c['payment_reference']}")
            continue
        if len(hits) > 1:
            add(f"CASH_MULTI_BANK {c['ledger_entry_id']} ref={c['payment_reference']} banks={','.join(sorted(hits))}")
            continue
        e = next(iter(hits.values()))
        claims[e["bank_entry_id"]].append(c["ledger_entry_id"])
        la, ba = sgn(c["amount"], c["dc_indicator"], "cash"), sgn(e["amount"], e["dc_indicator"], "bank")
        if la != ba or c["currency"] != e["currency"]:
            add(f"CASH_BANK_AMOUNT {c['ledger_entry_id']}/{e['bank_entry_id']} ledger={fmt(la)} bank={fmt(ba)}")
        pd_, bd = ldate(c["posted_ts"]), ldate(e["booking_ts"])
        if pd_ != bd:
            add(f"TIMING {c['ledger_entry_id']}/{e['bank_entry_id']} ref={c['payment_reference']} recorded={pd_} bank={bd} amount={fmt(la)}")
    for be, ids in claims.items():
        if len(ids) > 1:
            add(f"BANK_MULTI_CLAIM {be} IN-10={','.join(sorted(ids))}")
    batch_refs = {(b["account_id"], b["expected_bank_reference"]) for b in R["IN-12"]}
    txn_refs = {t["payment_reference"] for t in R["IN-11"] if t["payment_reference"]}
    reg_refs = {u["bank_reference"] for u in R["IN-04"]}
    topups = {c["payment_reference"] for c in cash if c["entry_type"] == "OWN_FUNDS_TOPUP"}
    for e in bank_sga:
        refs = sorted({e["bank_reference"], e["end_to_end_ref"]} - {""})
        has_cash = e["bank_entry_id"] in claims
        explained = ((e["account_id"], e["bank_reference"]) in batch_refs or e["end_to_end_ref"] in txn_refs
                     or e["end_to_end_ref"] in reg_refs or e["bank_reference"] in topups)
        if not has_cash and not explained:
            add(f"BANK_NO_COUNTERPART {e['bank_entry_id']} ref={'/'.join(refs)}")
        elif not has_cash:
            add(f"BANK_NO_CASHBOOK {e['bank_entry_id']} ref={'/'.join(refs)}")
        elif not explained:
            add(f"BANK_UNEXPLAINED {e['bank_entry_id']} ref={'/'.join(refs)}")
    # direct transactions (loads, redemptions)
    e2e = defaultdict(list)
    for e in bank_sga:
        if e["end_to_end_ref"]:
            e2e[e["end_to_end_ref"]].append(e)
    tclaims = defaultdict(list)
    for t in R["IN-11"]:
        if t["txn_type"] not in ("LOAD_BANK", "REDEMPTION"):
            continue
        hits = e2e.get(t["payment_reference"], [])
        if not hits:
            add(f"TXN_NO_BANK {t['txn_id']} ref={t['payment_reference']}")
        elif len(hits) > 1:
            add(f"TXN_MULTI_BANK {t['txn_id']} ref={t['payment_reference']}")
        else:
            e = hits[0]
            tclaims[e["bank_entry_id"]].append(t["txn_id"])
            if e["amount"] != t["amount"] or e["currency"] != t["currency"]:
                add(f"TXN_BANK_AMOUNT {t['txn_id']} ref={t['payment_reference']} txn={t['amount']} bank={e['amount']}")
            if e["dc_indicator"] != ("C" if t["txn_type"] == "LOAD_BANK" else "D"):
                add(f"TXN_BANK_DIRECTION {t['txn_id']}")
    for be, ids in tclaims.items():
        if len(ids) > 1:
            add(f"BANK_MULTI_CLAIM {be} IN-11={','.join(sorted(ids))}")
    # unallocated register
    for u in R["IN-04"]:
        hits = e2e.get(u["bank_reference"], [])
        if len(hits) != 1 or hits[0]["amount"] != u["amount"] or hits[0]["currency"] != u["currency"]:
            add(f"REGISTER_BANK {u['receipt_id']} matches={len(hits)}")
        due = next_business_day(date.fromisoformat(u["receipt_date"]))
        if u["allocated_ts"]:
            if ldate(u["allocated_ts"]) > due:
                add(f"REGISTER_LATE {u['receipt_id']} due={due}")
            al = [t for t in R["IN-11"] if t["txn_type"] == "LOAD_BANK" and t["payment_reference"] == u["bank_reference"]]
            if len(al) != 1 or al[0]["client_id"] != u["client_id"]:
                add(f"REGISTER_ALLOCATION {u['receipt_id']}")
        elif due <= PEND:
            add(f"REGISTER_OVERDUE {u['receipt_id']} due={due}")
    # refunds, currency, coverage
    totals = defaultdict(Decimal)
    for t in R["IN-11"]:
        if t["txn_type"] == "REFUND":
            o = txn.get(t["original_txn_id"])
            if o is None or o["client_id"] != t["client_id"] or o["currency"] != t["currency"]:
                add(f"REFUND_ORIGINAL {t['txn_id']}")
                continue
            totals[o["txn_id"]] += Decimal(t["amount"])
            if totals[o["txn_id"]] > Decimal(o["amount"]):
                add(f"REFUND_EXCEEDS {t['txn_id']}")
    for fid in ("IN-06", "IN-07", "IN-08", "IN-09", "IN-10", "IN-12"):
        for r in R[fid]:
            if r["currency"] != ccy_of.get(r["account_id"]):
                add(f"CURRENCY {fid} {r[C.pk(fid)]}")
    count = lambda fid, keyf: defaultdict(int, {k: n for k, n in _counts(R[fid], keyf).items()})
    irr = count("IN-05", lambda r: (r["recon_date"], r["currency"]))
    erl = count("IN-06", lambda r: (r["recon_date"], r["account_id"]))
    st = count("IN-08", lambda r: (r["statement_date"], r["account_id"]))
    sb = count("IN-12", lambda r: (r["settlement_date"], r["currency"], r["counterparty_type"]))
    sn = count("IN-03", lambda r: (r["recon_date"], r["currency"], r["client_id"]))
    clients = defaultdict(set)
    for r in R["IN-03"]:
        clients[r["currency"]].add(r["client_id"])
    for d in map(str, recon_days):
        for ccy in sorted({ccy_of[a] for a in sga}):
            for k, n in ((("IN-05", d, ccy), irr[(d, ccy)]), *((("IN-12", d, ccy, t), sb[(d, ccy, t)]) for t in ("SCHEME", "ACQUIRER")),
                         *((("IN-03", d, ccy, c), sn[(d, ccy, c)]) for c in sorted(clients[ccy]))):
                if n != 1:
                    add(f"COVERAGE {' '.join(k)} count={n}")
        for a in sga:
            if erl[(d, a)] != 1:
                add(f"COVERAGE IN-06 {d} {a} count={erl[(d, a)]}")
        for a in accounts:
            if st[(d, a)] != 1:
                add(f"COVERAGE IN-08 {d} {a} count={st[(d, a)]}")
    return out, fig


def _counts(rows, keyf):
    c = defaultdict(int)
    for r in rows:
        c[keyf(r)] += 1
    return c


# ------------------------------------------------------------------------------------------------ M: mutation diff
def row_map(raw, fid):
    text = raw.decode("utf-8")
    lines = text.split("\n")
    out = []
    for ln in lines[1:]:
        if ln == "":
            continue
        out.append((next(csv.reader([ln]))[0], ln))
    return lines[0], out


def diff_cases(old_raw, new_raw):
    """Changes between two cases at row level: (fid, key, field, old, new) / (fid, key, DELETED) / (fid, key, ADDED, after)."""
    changes, issues = set(), []
    for fid in C.csv:
        if old_raw[fid] == new_raw[fid]:
            continue
        h0, r0 = row_map(old_raw[fid], fid)
        h1, r1 = row_map(new_raw[fid], fid)
        if h0 != h1:
            issues.append(f"{fid} header text changed")
        m0, m1 = dict(r0), dict(r1)
        cols = C.columns(fid)
        for k in m0.keys() - m1.keys():
            changes.add((fid, k, "DELETED"))
        order1 = [k for k, _ in r1]
        for k in m1.keys() - m0.keys():
            i = order1.index(k)
            changes.add((fid, k, "ADDED", order1[i - 1] if i else None, tuple(next(csv.reader([m1[k]])))))
        for k in m0.keys() & m1.keys():
            if m0[k] != m1[k]:
                a, b = next(csv.reader([m0[k]])), next(csv.reader([m1[k]]))
                for c, x, y in zip(cols, a, b):
                    if x != y:
                        changes.add((fid, k, c, x, y))
        kept0 = [k for k, _ in r0 if k in m1]
        kept1 = [k for k, _ in r1 if k in m0]
        if kept0 != kept1:
            issues.append(f"{fid} order of unchanged rows differs")
    return changes, issues


def expected_changes(ops):
    exp, net = set(), {}
    for op in ops:
        fid = op["file_id"]
        if op["op"] == "set_field":
            exp.add((fid, op["key"], op["field"], op["old"], op["new"]))
        elif op["op"] == "delete_record":
            exp.add((fid, op["key"], "DELETED"))
        else:
            rec = op["record"]
            exp.add((fid, rec[C.pk(fid)], "ADDED", op.get("insert_after"), tuple(rec[c] for c in C.columns(fid))))
    # a delete followed by an add of the same key would net out; not used by this suite
    return exp


# ------------------------------------------------------------------------------------------------ P: packaging checks
def check_manifest(case):
    issues = []
    with open(Path(case) / "manifest.csv", encoding="utf-8", newline="") as f:
        man = list(csv.DictReader(f))
    if len(man) != 19:
        issues.append(f"manifest has {len(man)} rows")
    for m in man:
        p = Path(case) / m["relative_path"]
        if not p.exists():
            issues.append(f"manifest lists missing {m['relative_path']}")
            continue
        if sha(p) != m["sha256"]:
            issues.append(f"sha256 mismatch {m['relative_path']}")
        if m["format"] == "CSV":
            with open(p, encoding="utf-8", newline="") as f:
                n = sum(1 for _ in csv.DictReader(f))
            if str(n) != m["record_count"]:
                issues.append(f"record_count mismatch {m['relative_path']}")
    return issues


def check_zip(zpath, case):
    issues = []
    with zipfile.ZipFile(zpath) as z:
        if z.testzip() is not None:
            issues.append("CRC error")
        names = z.namelist()
        canon = sorted(C.filename(f) for f in list(C.csv) + list(C.pdf))
        if sorted(names) != canon:
            issues.append(f"entries differ from the 19 canonical names: {sorted(set(names) ^ set(canon))}")
        for n in names:
            sub = "source_data" if n.endswith(".csv") else "supporting_documents"
            if z.read(n) != (Path(case) / sub / n).read_bytes():
                issues.append(f"{n} differs from the case file")
    return issues


def check_predicted(p, sid):
    issues = []
    if "NOT EXECUTED" not in p.get("label", ""):
        issues.append("label does not state NOT EXECUTED")
    ids = [x["exception_id"] for x in p["exceptions"]]
    if ids != [f"EXC-{sid}-{n:02d}" for n in range(1, len(ids) + 1)]:
        issues.append("exception ids not sequential")
    if sum(x["affected_results"] for x in p["exceptions"]) != len(p["non_passing_results"]):
        issues.append("sum of affected_results != number of non-passing results (each result belongs to exactly one exception)")
    if p["non_passing_results"] != sorted(p["non_passing_results"]) or any(len(r) != 3 or r[2] not in ("FAIL", "INSUFFICIENT_EVIDENCE") for r in p["non_passing_results"]):
        issues.append("non_passing_results malformed")
    for g in p["investigation_groups"] + p["candidate_relationships"]:
        if not set(g) <= set(ids):
            issues.append(f"group/candidate references unknown exception {g}")
    if set(p["evidence_statuses"]) - set(ids):
        issues.append("evidence status for unknown exception")
    status = p["expected_case_status"]
    if (status == "CLEAN") != (not p["non_passing_results"]):
        issues.append("CLEAN status inconsistent with non-passing results")
    if status == "EXCEPTIONS_OPEN" and any(r[2] != "FAIL" for r in p["non_passing_results"]):
        issues.append("EXCEPTIONS_OPEN with INSUFFICIENT_EVIDENCE results")
    return issues


# ------------------------------------------------------------------------------------------------ main
def validate_case(case, fin=None):
    data, raw, load_errs = load(case)
    res = {"case": str(Path(case).relative_to(SUITE)), "load": load_errs}
    res["structure_errors"] = structure(data) if not load_errs else ["not run (load errors)"]
    findings, figures = recon(data) if not res["structure_errors"] else (set(), {})
    res["findings"] = sorted(findings)
    pdf_diff = [p.name for p in (Path(case) / "supporting_documents").iterdir()
                if p.read_bytes() != (BASE / "supporting_documents" / p.name).read_bytes()]
    res["pdf_not_identical_to_baseline"] = pdf_diff
    if fin is not None:
        exp = set(fin["expected_anomalies"])
        res["fin_unexpected_findings"] = sorted(findings - exp)
        res["fin_missing_findings"] = sorted(exp - findings)
        res["fin_figure_mismatches"] = [f"{k}: key {v} recomputed {figures.get(k)}" for k, v in sorted(fin["figures"].items()) if figures.get(k) != v]
        res["fin_figures_checked"] = len(fin["figures"])
    return res, raw


def ok(res):
    keys = ("load", "structure_errors", "pdf_not_identical_to_baseline", "fin_unexpected_findings", "fin_missing_findings",
            "fin_figure_mismatches", "mutation_unexpected", "mutation_missing", "mutation_issues", "untouched_not_identical",
            "manifest_issues", "zip_issues", "json_issues", "baseline_equality_issues")
    return not any(res.get(k) for k in keys)


def main():
    results = {"validator": "tools/validate_suite.py (independent; no engine code imported or executed)",
               "contract": {"source": C.snap["source"], "source_sha256": C.snap["source_sha256"]}, "cases": []}
    base_res, base_raw = validate_case(BASE, {"expected_anomalies": [], "figures": {}})
    base_res["role"] = "CONTROL: clean baseline must produce no structure errors and no findings"
    results["cases"].append(base_res)
    for s in SCENARIOS:
        sd = SUITE / s["dir"]
        er = sd / "expected_results"
        fin = json.loads((er / "financial_answer_key.json").read_text(encoding="utf-8"))
        res, raw = validate_case(sd / "initial_submission", fin)
        res["role"] = f"{s['scenario_id']} initial submission"
        ops = json.loads((sd / "mutations.json").read_text(encoding="utf-8"))["operations"]
        got, issues = diff_cases(base_raw, raw)
        exp = expected_changes(ops)
        res["mutation_unexpected"] = sorted(map(str, got - exp))
        res["mutation_missing"] = sorted(map(str, exp - got))
        res["mutation_issues"] = issues
        res["mutation_changes_verified"] = len(got & exp)
        touched = {op["file_id"] for op in ops}
        res["untouched_not_identical"] = [f for f in C.csv if f not in touched and raw[f] != base_raw[f]]
        res["manifest_issues"] = check_manifest(sd / "initial_submission")
        res["zip_issues"] = check_zip(sd / "upload" / f"{s['scenario_id']}_initial_evidence_upload.zip", sd / "initial_submission")
        js = []
        sc = json.loads((sd / "initial_submission" / "scenario.json").read_text(encoding="utf-8"))
        if sc["scenario_id"] != s["scenario_id"] or sc["submission"] != "initial":
            js.append("scenario.json identity")
        if (sd / "initial_submission" / "answer_key.json").exists():
            js.append("answer_key.json present in the case root (would be auto-compared by the engine)")
        js += [f"engine_predicted_initial: {x}" for x in check_predicted(json.loads((er / "engine_predicted_initial.json").read_text()), s["scenario_id"])]
        fut = json.loads((er / "future_behaviour_proposed.json").read_text())
        ai = json.loads((er / "ai_investigation_expectations.json").read_text())
        if "PROPOSED" not in fut["label"] or not fut["root"]:
            js.append("future label")
        if not ai["findings"] or not ai["analyst_action"] or "FIN" not in ai["label"]:
            js.append("ai expectations incomplete")
        res["json_issues"] = js
        results["cases"].append(res)
        if s.get("correction"):
            cd = sd / "corrections" / "corrected_case"
            finc = json.loads((er / "financial_answer_key_after_correction.json").read_text(encoding="utf-8"))
            r2, raw2 = validate_case(cd, finc)
            r2["role"] = f"{s['scenario_id']} corrected case"
            cops = json.loads((sd / "corrections" / "correction_mutations.json").read_text(encoding="utf-8"))["operations"]
            got2, iss2 = diff_cases(raw, raw2)
            exp2 = expected_changes(cops)
            r2["mutation_unexpected"] = sorted(map(str, got2 - exp2))
            r2["mutation_missing"] = sorted(map(str, exp2 - got2))
            r2["mutation_issues"] = iss2
            r2["mutation_changes_verified"] = len(got2 & exp2)
            ctouched = {op["file_id"] for op in cops}
            r2["untouched_not_identical"] = [f for f in C.csv if f not in ctouched and raw2[f] != raw[f]]
            rep = sorted(p.name for p in (sd / "corrections" / "replacement_files" / "source_data").iterdir())
            r2["baseline_equality_issues"] = [f"{f} not byte-identical to baseline" for f in s["correction"]["must_equal_baseline"] if raw2[f] != base_raw[f]]
            if rep != sorted(C.filename(f) for f in ctouched):
                r2["baseline_equality_issues"].append(f"replacement_files {rep} != changed files")
            r2["baseline_equality_issues"] += [f"replacement {n} differs from corrected_case" for n in rep
                                              if (sd / "corrections" / "replacement_files" / "source_data" / n).read_bytes() != (cd / "source_data" / n).read_bytes()]
            r2["manifest_issues"] = check_manifest(cd)
            r2["zip_issues"] = check_zip(sd / "upload" / f"{s['scenario_id']}_corrected_evidence_upload.zip", cd)
            r2["json_issues"] = [f"engine_predicted_after_correction: {x}" for x in
                                 check_predicted(json.loads((er / "engine_predicted_after_correction.json").read_text()), s["scenario_id"])]
            results["cases"].append(r2)
    for r in results["cases"]:
        r["status"] = "PASS" if ok(r) else "FAIL"
    results["overall"] = "PASS" if all(r["status"] == "PASS" for r in results["cases"]) else "FAIL"
    (SUITE / "validation").mkdir(exist_ok=True)
    (SUITE / "validation" / "validation_results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    for r in results["cases"]:
        extra = ""
        if "fin_figures_checked" in r:
            extra = f"; findings {len(r['findings'])} (expected set matched: {not r['fin_unexpected_findings'] and not r['fin_missing_findings']}); figures {r['fin_figures_checked']}"
        if "mutation_changes_verified" in r:
            extra += f"; changes verified {r['mutation_changes_verified']}"
        print(f"{r['status']:4} {r['role']}{extra}")
        for k, v in r.items():
            if isinstance(v, list) and v and k not in ("findings",):
                print(f"      {k}: {v[:8]}")
    print("OVERALL", results["overall"])
    sys.exit(0 if results["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
