"""Independent verification of the January–August 2026 historical demonstration (package, source data, continuity, packs).

ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

Read-only. The engine's calculation code is not imported: values are parsed here (Decimal, zoneinfo Europe/London) and
checked against the file contract (uc042lib.schema column lists) and the canonical names (uc042lib.period). Packs are
checked with the pack layer's own content-hash function only. The scenario oracles (scenario_definition.json,
mutations.json) are read from the supplied package for the expected-versus-actual comparison; they never enter
demo_history/datasets or any AI context.

Usage (from the uc042/ folder, after tools/build_demo_history.py):
    python tools/verify_demo_history.py [--package DIR] [--demo DIR] [--write]
--write stores the results in demo_history/verification/ (JSON, CSV and VERIFICATION_REPORT.md).
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from uc042lib import schema  # noqa: E402  (file contract: column names, types, requiredness)
from uc042lib.pack import model as pack_model  # noqa: E402  (content-hash function only)
from uc042lib.period import PeriodConfig  # noqa: E402  (canonical file names)

PACKAGE = PROJECT / "UC042_JAN_AUG_HISTORICAL_DEMO" / "UC042_JAN_AUG_HISTORICAL_DEMO"
DEMO = PROJECT / "demo_history"
SEPTEMBER = PROJECT / "uc042_dataset" / "set_01_clean_baseline"
LON = ZoneInfo("Europe/London")
MONTHS = [PeriodConfig(2026, m) for m in range(1, 9)]
SEPT = PeriodConfig(2026, 9)
SYNTHETIC = "ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS"
CURRENCIES = {"GBP", "EUR"}
POINT = time(17, 0)

# England and Wales bank holidays, written out (not computed) so the calendar check is independent of uc042lib.period.
BANK_HOLIDAYS = {date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
                 date(2026, 5, 4), date(2026, 5, 25), date(2026, 8, 31)}
# GMT -> BST at 01:00 UTC on Sunday 29 March 2026 (and back at 01:00 UTC on 25 October 2026).
DST_START_UTC = datetime(2026, 3, 29, 1, 0, tzinfo=ZoneInfo("UTC"))

# --- value types (independent of uc042lib.structure) ------------------------------------------------------------
TYPE_RE = {
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "ts": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"),
    "amount": re.compile(r"^\d+\.\d{2}$"),
    "signed": re.compile(r"^-?\d+\.\d{2}$"),
    "int": re.compile(r"^\d+$"),
    "bool": re.compile(r"^(true|false)$"),
    "ccy": re.compile(r"^(GBP|EUR)$"),
    "id": re.compile(r"^[A-Z0-9][A-Za-z0-9_./-]*$"),
}
# Identifier conventions of the project (the September baseline follows the same patterns; tested).
ID_RE = {
    "IN-02": re.compile(r"^(SGA|OWN)-(GBP|EUR)-\d{2}$"),
    "IN-03": re.compile(r"^CBS-(\d{8})-C\d{4}-(GBP|EUR)$"),
    # September: UR-nnnn. The historical months embed the month (UR-YYYYMM-<G|E>nn) so receipts stay unique across periods.
    "IN-04": re.compile(r"^UR-(\d{4}|\d{6}-[GE]\d{2})$"),
    "IN-05": re.compile(r"^IRR-EMONEY-(GBP|EUR)-(\d{8})$"),
    "IN-06": re.compile(r"^ERL-SGA-(GBP|EUR)-\d{2}-(\d{8})$"),
    "IN-07": re.compile(r"^ST-(SGA|OWN)-(GBP|EUR)-\d{2}-(\d{8})-1700$"),
    "IN-08": re.compile(r"^ST-(SGA|OWN)-(GBP|EUR)-\d{2}-(\d{8})-EOD$"),
    "IN-09": re.compile(r"^BE-(?:OWN-)?(GBP|EUR)-(\d{4})-[A-Z0-9]+$"),
    "IN-10": re.compile(r"^LE-(GBP|EUR)-(\d{4})-\d{4}$"),
    "IN-11": re.compile(r"^TX-(\d{4})-(\d{5}|0R\d{3})$"),  # 0Rnnn: refunds
    "IN-12": re.compile(r"^(AQ|SB)-(GBP|EUR)-(\d{8})$"),
    "IN-13": re.compile(r"^SL-(AQ|SB)-(GBP|EUR)-(\d{8})-\d{4}$"),
}


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_csv(p):
    with open(p, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def ts(s):
    return datetime.fromisoformat(s)


def money(s):
    return Decimal(s)


def london_ok(s):
    """The timestamp's offset is Europe/London's offset at that instant, and its wall time exists in London."""
    dt = ts(s)
    local = dt.astimezone(LON)
    return local.utcoffset() == dt.utcoffset() and local.replace(tzinfo=None) == dt.replace(tzinfo=None)


def point_at(d):
    return datetime.combine(d, POINT, tzinfo=LON)


class Case:
    """One month's case folder, read with plain csv (rows keyed by file ID)."""

    def __init__(self, case_dir, period):
        self.dir, self.period = Path(case_dir), period
        self.headers, self.rows = {}, {}
        for fid in schema.CSV_FILES:
            self.headers[fid], self.rows[fid] = read_csv(self.dir / "source_data" / period.filename(fid))

    def by(self, fid, col):
        return {r[col]: r for r in self.rows[fid]}


# ------------------------------------------------------------------------------------------------- package level
def categorise(rel):
    parts = rel.split("/")
    if len(parts) >= 3 and parts[1] == "source_documents":
        if parts[2] == "source_data":
            return "SOURCE_CSV"
        if parts[2] == "supporting_documents":
            return "SUPPORTING_PDF"
        if parts[2] == "manifest.csv":
            return "ENGINE_MANIFEST"
    name = parts[-1]
    if name in ("scenario_definition.json", "mutations.json"):
        return "SCENARIO_ORACLE (test-only)"
    if name == "manifest.json":
        return "MONTH_MANIFEST" if len(parts) == 2 else "PACKAGE_MANIFEST"
    if parts[0] == "generator":
        return "GENERATOR"
    if parts[0] == "verification":
        return "VERIFICATION"
    return "PACKAGE_DOCUMENT"


def record_count(p):
    if p.suffix == ".csv":
        with open(p, encoding="utf-8", newline="") as f:
            return sum(1 for _ in csv.DictReader(f))
    if p.suffix == ".pdf":
        from pypdf import PdfReader
        return len(PdfReader(str(p)).pages)
    return ""


def inventory(package=PACKAGE):
    package = Path(package)
    out = []
    for p in sorted(package.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(package).as_posix()
        month = rel[:7] if re.match(r"^2026-0[1-8]/", rel) else ""
        out.append({"month": month, "file": rel, "category": categorise(rel), "size_bytes": p.stat().st_size,
                    "record_count": record_count(p), "sha256": sha256(p), "reporting_period": f"PER-{month}" if month else ""})
    return out


def package_integrity(package=PACKAGE):
    """Problems with the package as delivered: file set, paths, manifests and hashes."""
    package = Path(package).resolve()
    problems = []
    files = [p for p in package.rglob("*") if p.is_file() or p.is_symlink()]
    for p in files:
        if p.is_symlink():
            problems.append(f"symbolic link: {p}")
        if package not in p.resolve().parents:
            problems.append(f"path outside the package: {p}")
    top = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if [m["period"] for m in top["months"]] != [p.token for p in MONTHS]:
        problems.append("package manifest months are not 2026-01..2026-08")
    expected = {"README.md", "claude_code_handoff.md", "continuity_report.md", "date_quality_report.md",
                "historical_coverage_report.md", "manifest.json", "scenario_matrix.csv",
                "generator/_last_run.json", "generator/build_docs.py", "generator/build_reports.py", "generator/generate_history.py",
                "verification/data_quality_results.json", "verification/engine_prevalidation_results.json",
                "verification/prevalidate_engine.py", "verification/verify_history.py"}
    for m in top["months"]:
        period = PeriodConfig.from_id(f"PER-{m['period']}")
        mdir = package / m["period"]
        if sha256(package / m["manifest"]) != m["manifest_sha256"]:
            problems.append(f"{m['manifest']}: hash differs from the package manifest")
        if sha256(mdir / "scenario_definition.json") != m["scenario_definition_sha256"]:
            problems.append(f"{m['period']}/scenario_definition.json: hash differs")
        expected |= {f"{m['period']}/{n}" for n in ("manifest.json", "scenario_definition.json", "mutations.json",
                                                     "source_documents/manifest.csv")}
        for fid in schema.CSV_FILES:
            expected.add(f"{m['period']}/source_documents/source_data/{period.filename(fid)}")
        _, rows = read_csv(mdir / "source_documents" / "manifest.csv")
        for r in rows:
            p = mdir / "source_documents" / r["relative_path"]
            if r["format"] == "PDF":
                expected.add(f"{m['period']}/source_documents/{r['relative_path']}")
            if not p.is_file():
                problems.append(f"{m['period']}: listed file missing: {r['relative_path']}")
            elif sha256(p) != r["sha256"]:
                problems.append(f"{m['period']}: {r['relative_path']}: SHA-256 differs from manifest.csv")
            elif str(record_count(p)) != r["record_count"]:
                problems.append(f"{m['period']}: {r['relative_path']}: record count {record_count(p)} != manifest {r['record_count']}")
        mj = json.loads((mdir / "manifest.json").read_text(encoding="utf-8"))
        for f in mj["files"]:
            p = mdir / "source_documents" / f["relative_path"]
            if not p.is_file() or sha256(p) != f["sha256"]:
                problems.append(f"{m['period']}/manifest.json: {f['relative_path']} hash or presence differs")
        if mj["period_id"] != period.period_id:
            problems.append(f"{m['period']}/manifest.json: period_id {mj['period_id']}")
    present = {p.relative_to(package).as_posix() for p in files}
    problems += [f"unexpected file: {x}" for x in sorted(present - expected)]
    problems += [f"expected file missing: {x}" for x in sorted(expected - present)]
    return problems


# ------------------------------------------------------------------------------------------- source-data checks
def schema_problems(case):
    """Headers in contract order; every value of its type; mandatory and conditional fields populated; enums."""
    out = []
    for fid, (_, _, cols) in schema.CSV_FILES.items():
        names = [c[0] for c in cols]
        if case.headers[fid] != names:
            out.append(f"{fid}: header {case.headers[fid]} != contract {names}")
            continue
        for i, r in enumerate(case.rows[fid], start=2):
            if None in r or any(v is None for v in r.values()):
                out.append(f"{fid} L{i}: wrong number of fields")
                continue
            for name, typ, req, _ in cols:
                v = r[name]
                if v == "":
                    if req == "M":
                        out.append(f"{fid} L{i} {name}: mandatory field blank")
                    continue
                rx = TYPE_RE.get(typ)
                if rx and not rx.match(v):
                    out.append(f"{fid} L{i} {name}: {v!r} is not a valid {typ}")
                elif typ == "date":
                    try:
                        date.fromisoformat(v)
                    except ValueError:
                        out.append(f"{fid} L{i} {name}: impossible date {v!r}")
                elif typ == "ts":
                    try:
                        ts(v)
                    except ValueError:
                        out.append(f"{fid} L{i} {name}: impossible timestamp {v!r}")
                elif typ == "enum" and (fid, name) in schema.ENUMS and v not in schema.ENUMS[(fid, name)]:
                    out.append(f"{fid} L{i} {name}: {v!r} not an allowed value")
            for cfid, cname, cond, desc in schema.CONDITIONAL:
                if cfid == fid and cond(r) and r[cname] == "":
                    out.append(f"{fid} L{i} {cname}: {desc}")
            if fid in ID_RE and not ID_RE[fid].match(r[names[0]]):
                out.append(f"{fid} L{i}: identifier {r[names[0]]!r} does not follow the project convention")
    for fid in schema.CSV_FILES:
        if not case.rows[fid] and fid not in schema.EMPTY_ALLOWED:
            out.append(f"{fid}: no data rows")
    return out


def id_date_problems(case):
    """Identifiers embed their record's date (YYYYMMDD or MMDD); the embedded date must equal the record's own date."""
    out = []
    checks = {"IN-03": ("recon_date", "%Y%m%d", 1), "IN-05": ("recon_date", "%Y%m%d", 2), "IN-06": ("recon_date", "%Y%m%d", 2),
              "IN-07": ("as_at_ts", "%Y%m%d", 3), "IN-08": ("statement_date", "%Y%m%d", 3), "IN-09": ("booking_date", "%m%d", 2),
              "IN-10": ("posted_ts", "%m%d", 2), "IN-11": ("executed_ts", "%m%d", 1), "IN-12": ("settlement_date", "%Y%m%d", 3)}
    for fid, (col, fmt, grp) in checks.items():
        pk = schema.columns(fid)[0]
        for r in case.rows[fid]:
            m = ID_RE[fid].match(r[pk])
            if not m:
                continue
            d = ts(r[col]).astimezone(LON).date() if "T" in r[col] else date.fromisoformat(r[col])
            if m.group(grp) != d.strftime(fmt):
                out.append(f"{fid} {r[pk]}: embedded date {m.group(grp)} != {col} {r[col]}")
    return out


def key_problems(case):
    """Primary keys unique; exact duplicate rows; natural-key duplicates (one statement per account-day, one snapshot per
    client-day, one reconciliation record per day and currency or account, one calendar row per date)."""
    out = []
    for fid in schema.CSV_FILES:
        pk = schema.columns(fid)[0]
        for k, n in Counter(r[pk] for r in case.rows[fid]).items():
            if n > 1:
                out.append(f"{fid}: primary key {k} appears {n} times")
        for k, n in Counter(tuple(sorted(r.items())) for r in case.rows[fid]).items():
            if n > 1:
                out.append(f"{fid}: exact duplicate row ({n}x) {dict(k).get(pk)}")
    natural = {"IN-01": ("calendar_date",), "IN-03": ("recon_date", "client_id", "currency"), "IN-05": ("recon_date", "currency"),
               "IN-06": ("recon_date", "account_id"), "IN-07": ("account_id", "as_at_ts"), "IN-08": ("account_id", "statement_date"),
               "IN-09": ("account_id", "booking_ts", "amount", "dc_indicator", "bank_reference", "end_to_end_ref"),
               "IN-11": ("client_id", "txn_type", "executed_ts", "amount", "payment_reference", "settlement_batch_id"),
               "IN-13": ("batch_id", "line_type", "txn_id", "fee_code")}
    for fid, cols in natural.items():
        for k, n in Counter(tuple(r[c] for c in cols) for r in case.rows[fid]).items():
            if n > 1:
                out.append(f"{fid}: natural key {dict(zip(cols, k))} appears {n} times")
    return out


def duplicate_bank_references(case):
    """{(account, bank_reference): [bank_entry_id, ...]} where a reference occurs more than once in one account."""
    seen = defaultdict(list)
    for e in case.rows["IN-09"]:
        seen[(e["account_id"], e["bank_reference"])].append(e["bank_entry_id"])
    return {k: v for k, v in seen.items() if len(v) > 1}


def relationship_findings(case):
    """Foreign keys and matching links. Returns {kind: [detail, ...]}: an empty dict means every link resolves."""
    f = defaultdict(list)
    acc = case.by("IN-02", "account_id")
    sga = {a for a, r in acc.items() if r["account_class"] == "RELEVANT_FUNDS_BANK"}
    stmts = case.by("IN-08", "statement_id")
    conf = case.by("IN-07", "statement_id")
    txns = case.by("IN-11", "txn_id")
    batches = case.by("IN-12", "batch_id")
    entries = case.rows["IN-09"]
    for fid, col in (("IN-07", "account_id"), ("IN-08", "account_id"), ("IN-09", "account_id"), ("IN-10", "account_id"),
                     ("IN-06", "account_id"), ("IN-12", "account_id")):
        for r in case.rows[fid]:
            if r[col] not in acc:
                f["UNKNOWN_ACCOUNT"].append(f"{fid} {r[schema.columns(fid)[0]]}: {r[col]}")
            elif r.get("currency") and r["currency"] != acc[r[col]]["currency"]:
                f["CURRENCY_MISMATCH"].append(f"{fid} {r[schema.columns(fid)[0]]}: {r['currency']} on {r[col]}")
    for e in entries:
        s = stmts.get(e["statement_id"])
        if s is None:
            f["ENTRY_WITHOUT_STATEMENT"].append(e["bank_entry_id"])
        elif (s["account_id"], s["statement_date"]) != (e["account_id"], e["booking_date"]):
            f["ENTRY_STATEMENT_MISMATCH"].append(e["bank_entry_id"])
    for x in case.rows["IN-06"]:
        if x["bank_statement_id"] not in conf:
            f["EXTERNAL_RECORD_WITHOUT_CONFIRMATION"].append(f"{x['ext_recon_id']} -> {x['bank_statement_id']}")
    # cash book <-> bank, one to one by reference within the account (a reference on several bank entries is ambiguous:
    # the amount never chooses), then equal amount and opposite perspective
    by_ref = defaultdict(list)
    for e in entries:
        for ref in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
            by_ref[(e["account_id"], ref)].append(e)
    used = set()
    for le in case.rows["IN-10"]:
        if le["entry_type"] == "OPENING_BALANCE":
            continue
        hits = by_ref.get((le["account_id"], le["payment_reference"]), [])
        if not hits:
            f["CASHBOOK_WITHOUT_BANK_ENTRY"].append(le["ledger_entry_id"])
        elif len(hits) > 1:
            f["CASHBOOK_REFERENCE_AMBIGUOUS"].append(f"{le['ledger_entry_id']}: {sorted(e['bank_entry_id'] for e in hits)}")
        elif (hits[0]["amount"], hits[0]["dc_indicator"]) == (le["amount"], le["dc_indicator"]) or hits[0]["amount"] != le["amount"]:
            f["CASHBOOK_BANK_AMOUNT_OR_DIRECTION_DIFFERS"].append(le["ledger_entry_id"])
        else:
            used.add(hits[0]["bank_entry_id"])
    for e in entries:
        if e["account_id"] in sga and e["bank_entry_id"] not in used:
            f["SGA_BANK_ENTRY_WITHOUT_CASHBOOK"].append(e["bank_entry_id"])
    # settlement batch -> its bank entry by expected reference (never by amount), net equal
    for b in batches.values():
        hits = [e for e in entries if e["account_id"] == b["account_id"] and e["bank_reference"] == b["expected_bank_reference"]]
        if not hits:
            f["BATCH_WITHOUT_BANK_ENTRY"].append(b["batch_id"])
        elif len(hits) > 1:
            f["BATCH_WITH_SEVERAL_BANK_ENTRIES"].append(f"{b['batch_id']}: {sorted(e['bank_entry_id'] for e in hits)}")
        elif hits[0]["amount"] != b["net_amount_reported"]:
            f["BATCH_NET_DIFFERS_FROM_BANK"].append(b["batch_id"])
    # lines -> batch and transaction; transaction -> batch; refund -> original
    for ln in case.rows["IN-13"]:
        if ln["batch_id"] not in batches:
            f["LINE_WITHOUT_BATCH"].append(ln["line_id"])
        if ln["txn_id"] and ln["txn_id"] not in txns:
            f["LINE_WITHOUT_TRANSACTION"].append(ln["line_id"])
        elif ln["txn_id"] and txns[ln["txn_id"]]["settlement_batch_id"] != ln["batch_id"]:
            f["LINE_TRANSACTION_BATCH_MISMATCH"].append(ln["line_id"])
    lined = {ln["txn_id"] for ln in case.rows["IN-13"]}
    for t in txns.values():
        if t["settlement_batch_id"] and t["settlement_batch_id"] not in batches:
            f["TRANSACTION_WITHOUT_BATCH"].append(t["txn_id"])
        if t["settlement_batch_id"] and t["txn_id"] not in lined:
            f["CARD_TRANSACTION_WITHOUT_LINE"].append(t["txn_id"])
        if t["original_txn_id"] and t["original_txn_id"] not in txns:
            f["REFUND_WITHOUT_ORIGINAL"].append(t["txn_id"])
        if t["payment_reference"] and not any(e["end_to_end_ref"] == t["payment_reference"] for e in entries):
            f["BANK_TRANSACTION_WITHOUT_BANK_ENTRY"].append(t["txn_id"])
    for u in case.rows["IN-04"]:
        if not any(e["end_to_end_ref"] == u["bank_reference"] for e in entries):
            f["RECEIPT_WITHOUT_BANK_ENTRY"].append(u["receipt_id"])
    clients = {r["client_id"] for r in case.rows["IN-03"]}
    for fid, col in (("IN-11", "client_id"), ("IN-04", "client_id")):
        for r in case.rows[fid]:
            if r[col] and r[col] not in clients:
                f["UNKNOWN_CLIENT"].append(f"{fid} {r[schema.columns(fid)[0]]}: {r[col]}")
    for d in case.rows["IN-14"]:
        if d["recon_ref"] not in case.by("IN-05", "recon_run_id") and d["recon_ref"] not in case.by("IN-06", "ext_recon_id"):
            f["LOG_WITHOUT_RECON_RECORD"].append(d["discrepancy_id"])
    return dict(f)


def arithmetic_findings(case):
    """Decimal arithmetic: statements, confirmations, batches and lines, reported reconciliation differences."""
    f = defaultdict(list)
    signed_bank = lambda amt, dc: money(amt) if dc == "C" else -money(amt)
    entries_by_stmt = defaultdict(list)
    for e in case.rows["IN-09"]:
        entries_by_stmt[e["statement_id"]].append(e)
    by_acct = defaultdict(list)
    for s in case.rows["IN-08"]:
        es = entries_by_stmt[s["statement_id"]]
        opening, closing = signed_bank(s["opening_balance_amount"], s["opening_balance_dc"]), signed_bank(s["closing_balance_amount"], s["closing_balance_dc"])
        if opening + sum((signed_bank(e["amount"], e["dc_indicator"]) for e in es), Decimal("0")) != closing:
            f["STATEMENT_DOES_NOT_ADD_UP"].append(s["statement_id"])
        if int(s["entry_count"]) != len(es):
            f["ENTRY_COUNT_DIFFERS"].append(s["statement_id"])
        by_acct[s["account_id"]].append(s)
    for acct, ss in by_acct.items():
        ss.sort(key=lambda s: s["statement_date"])
        for a, b in zip(ss, ss[1:]):
            if signed_bank(a["closing_balance_amount"], a["closing_balance_dc"]) != signed_bank(b["opening_balance_amount"], b["opening_balance_dc"]):
                f["STATEMENT_CHAIN_BREAK"].append(f"{a['statement_id']} -> {b['statement_id']}")
    eod = {(s["account_id"], s["statement_date"]): s for s in case.rows["IN-08"]}
    for c in case.rows["IN-07"]:
        at = ts(c["as_at_ts"])
        s = eod.get((c["account_id"], at.astimezone(LON).date().isoformat()))
        if s is None:
            f["CONFIRMATION_WITHOUT_STATEMENT"].append(c["statement_id"])
            continue
        upto = signed_bank(s["opening_balance_amount"], s["opening_balance_dc"]) + sum(
            (signed_bank(e["amount"], e["dc_indicator"]) for e in entries_by_stmt[s["statement_id"]] if ts(e["booking_ts"]) <= at), Decimal("0"))
        if upto != signed_bank(c["balance_amount"], c["balance_dc_indicator"]):
            f["CONFIRMATION_DIFFERS_FROM_ENTRIES"].append(c["statement_id"])
    lines = defaultdict(list)
    for ln in case.rows["IN-13"]:
        lines[ln["batch_id"]].append(ln)
    for b in case.rows["IN-12"]:
        gross, fees, adj, net = (money(b[k]) for k in ("gross_amount", "total_fees", "total_adjustments", "net_amount_reported"))
        if gross - fees - adj != net:
            f["BATCH_NET_ARITHMETIC"].append(b["batch_id"])
        ls = lines[b["batch_id"]]
        if sum((money(x["amount"]) for x in ls if x["line_type"] == "TXN"), Decimal("0")) != gross:
            f["BATCH_GROSS_DIFFERS_FROM_LINES"].append(b["batch_id"])
        if sum((money(x["amount"]) for x in ls if x["line_type"] == "FEE"), Decimal("0")) != fees:
            f["BATCH_FEES_DIFFER_FROM_LINES"].append(b["batch_id"])
        if sum((money(x["amount"]) for x in ls if x["line_type"] == "REFUND"), Decimal("0")) != adj:
            f["BATCH_REFUNDS_DIFFER_FROM_LINES"].append(b["batch_id"])
        for x in ls:
            if x["currency"] != b["currency"]:
                f["LINE_CURRENCY_DIFFERS"].append(x["line_id"])
    for r in case.rows["IN-05"]:
        if money(r["resource_reported"]) - money(r["requirement_reported"]) != money(r["difference_reported"]):
            f["INTERNAL_DIFFERENCE_ARITHMETIC"].append(r["recon_run_id"])
    for r in case.rows["IN-06"]:
        if money(r["bank_balance_reported"]) - money(r["ledger_balance_reported"]) != money(r["difference_reported"]):
            f["EXTERNAL_DIFFERENCE_ARITHMETIC"].append(r["ext_recon_id"])
    return dict(f)


def date_findings(case):
    """Each date field judged on its own: format, Europe/London offset (DST per instant), period membership, points at
    17:00, booking date = booking timestamp's London date, calendar = England and Wales business days. Returns
    (problems, offsets) where offsets counts the timestamps by UTC offset."""
    p, period = [], case.period
    offsets = Counter()
    ts_cols = [(fid, c[0]) for fid, (_, _, cols) in schema.CSV_FILES.items() for c in cols if c[1] == "ts"]
    for fid, col in ts_cols:
        for r in case.rows[fid]:
            if r[col]:
                offsets[ts(r[col]).strftime("%z")] += 1
                if not london_ok(r[col]):
                    p.append(f"{fid} {r[schema.columns(fid)[0]]} {col}: {r[col]} is not a valid Europe/London time")
    opening = point_at(period.previous_end)
    in_period = lambda d: period.start <= d <= period.end
    london_date = lambda s: ts(s).astimezone(LON).date()
    # calendar
    cal = {date.fromisoformat(r["calendar_date"]): r for r in case.rows["IN-01"]}
    if sorted(cal) != period.dates():
        p.append("IN-01: calendar dates are not exactly the month")
    for d, r in cal.items():
        business = d.weekday() < 5 and d not in BANK_HOLIDAYS
        want = ("true", "") if business else ("false", "WEEKEND" if d.weekday() >= 5 else "UK_BANK_HOLIDAY")
        if (r["is_recon_day"], r["non_recon_reason"]) != want or r["period_id"] != period.period_id:
            p.append(f"IN-01 {d}: {r['is_recon_day']}/{r['non_recon_reason']} expected {want[0]}/{want[1]}")
    recon_days = {d for d, r in cal.items() if r["is_recon_day"] == "true"}
    # opening boundary rows are the only rows outside the month, and they sit exactly at the opening point
    for s in case.rows["IN-03"]:
        d = date.fromisoformat(s["recon_date"])
        if ts(s["as_at_ts"]) != point_at(d) or london_date(s["as_at_ts"]) != d:
            p.append(f"IN-03 {s['snapshot_id']}: as_at_ts is not 17:00 London on its recon_date")
        if d == period.previous_end:
            continue
        if d not in recon_days:
            p.append(f"IN-03 {s['snapshot_id']}: snapshot on a non-reconciliation day {d}")
    for le in case.rows["IN-10"]:
        if le["entry_type"] == "OPENING_BALANCE":
            if ts(le["posted_ts"]) != opening:
                p.append(f"IN-10 {le['ledger_entry_id']}: opening row not at the opening point {opening.isoformat()}")
        elif not in_period(london_date(le["posted_ts"])):
            p.append(f"IN-10 {le['ledger_entry_id']}: posted outside the period")
    for fid, col in (("IN-05", "recon_date"), ("IN-06", "recon_date")):
        for r in case.rows[fid]:
            if date.fromisoformat(r[col]) not in recon_days:
                p.append(f"{fid} {r[schema.columns(fid)[0]]}: {col} {r[col]} is not a reconciliation day in the period")
    for r in case.rows["IN-05"]:
        if ts(r["reconciliation_point_ts"]) != point_at(date.fromisoformat(r["recon_date"])):
            p.append(f"IN-05 {r['recon_run_id']}: reconciliation point is not 17:00 London")
        if ts(r["performed_at_ts"]) < ts(r["reconciliation_point_ts"]):
            p.append(f"IN-05 {r['recon_run_id']}: performed before the reconciliation point")
    for r in case.rows["IN-07"]:
        at = ts(r["as_at_ts"])
        if at != point_at(london_date(r["as_at_ts"])) or london_date(r["as_at_ts"]) not in recon_days:
            p.append(f"IN-07 {r['statement_id']}: confirmation not at 17:00 on a reconciliation day")
    for r in case.rows["IN-08"]:
        if not in_period(date.fromisoformat(r["statement_date"])) or london_date(r["as_at_ts"]) != date.fromisoformat(r["statement_date"]):
            p.append(f"IN-08 {r['statement_id']}: statement date outside the period or inconsistent with as_at_ts")
    for e in case.rows["IN-09"]:
        bd = date.fromisoformat(e["booking_date"])
        if not in_period(bd) or london_date(e["booking_ts"]) != bd:
            p.append(f"IN-09 {e['bank_entry_id']}: booking date outside the period or inconsistent with booking_ts")
        if date.fromisoformat(e["value_date"]) < bd:
            p.append(f"IN-09 {e['bank_entry_id']}: value date before booking date")
    for t in case.rows["IN-11"]:
        ex = london_date(t["executed_ts"])
        if not in_period(ex):
            p.append(f"IN-11 {t['txn_id']}: executed outside the period")
        if t["auth_ts"] and ts(t["auth_ts"]) > ts(t["executed_ts"]):
            p.append(f"IN-11 {t['txn_id']}: authorised after execution")
        if t["clearing_date"] and date.fromisoformat(t["clearing_date"]) < london_date(t["auth_ts"] or t["executed_ts"]):
            p.append(f"IN-11 {t['txn_id']}: cleared before authorisation")
    for b in case.rows["IN-12"]:
        sd = date.fromisoformat(b["settlement_date"])
        if not in_period(sd) or sd not in recon_days or date.fromisoformat(b["cycle_date"]) > sd:
            p.append(f"IN-12 {b['batch_id']}: settlement date outside the period, not a business day, or before the cycle date")
    for u in case.rows["IN-04"]:
        if london_date(u["receipt_ts"]) != date.fromisoformat(u["receipt_date"]):
            p.append(f"IN-04 {u['receipt_id']}: receipt date inconsistent with receipt_ts")
        if u["allocated_ts"] and (ts(u["allocated_ts"]) < ts(u["receipt_ts"]) or london_date(u["allocated_ts"]) != date.fromisoformat(u["allocated_date"])):
            p.append(f"IN-04 {u['receipt_id']}: allocation before receipt or inconsistent allocation date")
    # no bank booking, statement or settlement on a weekend or bank holiday
    for fid, col in (("IN-08", "statement_date"), ("IN-09", "booking_date")):
        for r in case.rows[fid]:
            d = date.fromisoformat(r[col])
            if d.weekday() >= 5 or d in BANK_HOLIDAYS:
                p.append(f"{fid} {r[schema.columns(fid)[0]]}: {col} {d} is a weekend or bank holiday")
    return p, dict(offsets)


# ------------------------------------------------------------------------------------------- financial continuity
def bank_signed(amt, dc):
    return money(amt) if dc == "C" else -money(amt)


def closing_positions(case, at):
    """Positions of a month at instant `at` (the next month's opening point), each with the records used.
    Clients: the last snapshot at or before `at`, rolled forward with transactions executed after it up to `at`.
    Cash book: every entry posted by `at`, D in / C out. Bank: each account's last end-of-day statement closing.
    Unallocated: receipts received by `at` and not allocated by it."""
    out = {}
    last = {}
    for s in case.rows["IN-03"]:
        k = (s["client_id"], s["currency"])
        if ts(s["as_at_ts"]) <= at and (k not in last or ts(s["as_at_ts"]) > ts(last[k]["as_at_ts"])):
            last[k] = s
    for k, s in last.items():
        moved = [t for t in case.rows["IN-11"] if (t["client_id"], t["currency"]) == k and ts(s["as_at_ts"]) < ts(t["executed_ts"]) <= at]
        bal = money(s["balance"]) + sum((money(t["amount"]) if t["direction"] == "CR" else -money(t["amount"]) for t in moved), Decimal("0"))
        out[("CLIENT", f"{k[0]}/{k[1]}")] = (bal, k[1], f"IN-03:{s['snapshot_id']}" + (f" + {len(moved)} IN-11 txns" if moved else ""))
    for acct in sorted({le["account_id"] for le in case.rows["IN-10"]}):
        rows = [le for le in case.rows["IN-10"] if le["account_id"] == acct and ts(le["posted_ts"]) <= at]
        bal = sum((money(le["amount"]) if le["dc_indicator"] == "D" else -money(le["amount"]) for le in rows), Decimal("0"))
        out[("CASH_BOOK", acct)] = (bal, rows[0]["currency"] if rows else "", f"IN-10: {len(rows)} entries to {at.isoformat()}")
    for acct in sorted({s["account_id"] for s in case.rows["IN-08"]}):
        s = max((s for s in case.rows["IN-08"] if s["account_id"] == acct), key=lambda s: s["statement_date"])
        out[("BANK", acct)] = (bank_signed(s["closing_balance_amount"], s["closing_balance_dc"]), s["currency"], f"IN-08:{s['statement_id']} closing")
    for u in case.rows["IN-04"]:
        if ts(u["receipt_ts"]) <= at and (not u["allocated_ts"] or ts(u["allocated_ts"]) > at):
            out[("UNALLOCATED", u["receipt_id"])] = (money(u["amount"]), u["currency"], f"IN-04:{u['receipt_id']}")
    return out


def opening_positions(case):
    """Positions a month opens with: snapshots and cash-book OPENING_BALANCE rows at the opening point, each account's
    first statement opening, and receipts received before the month and not allocated before it."""
    period, out = case.period, {}
    at = point_at(period.previous_end)
    for s in case.rows["IN-03"]:
        if s["recon_date"] == period.previous_end.isoformat():
            out[("CLIENT", f"{s['client_id']}/{s['currency']}")] = (money(s["balance"]), s["currency"], f"IN-03:{s['snapshot_id']}")
    for le in case.rows["IN-10"]:
        if le["entry_type"] == "OPENING_BALANCE":
            out[("CASH_BOOK", le["account_id"])] = (money(le["amount"]) if le["dc_indicator"] == "D" else -money(le["amount"]),
                                                    le["currency"], f"IN-10:{le['ledger_entry_id']}")
    for acct in sorted({s["account_id"] for s in case.rows["IN-08"]}):
        s = min((s for s in case.rows["IN-08"] if s["account_id"] == acct), key=lambda s: s["statement_date"])
        out[("BANK", acct)] = (bank_signed(s["opening_balance_amount"], s["opening_balance_dc"]), s["currency"], f"IN-08:{s['statement_id']} opening")
    for u in case.rows["IN-04"]:
        if ts(u["receipt_ts"]) <= at and (not u["allocated_ts"] or ts(u["allocated_ts"]) > at):
            out[("UNALLOCATED", u["receipt_id"])] = (money(u["amount"]), u["currency"], f"IN-04:{u['receipt_id']}")
    return out


def continuity(prev, cur):
    """Item per position key: previous closing vs current opening, compared only within the same view."""
    closing, opening = closing_positions(prev, point_at(cur.period.previous_end)), opening_positions(cur)
    items = []
    for key in sorted(set(closing) | set(opening)):
        c, o = closing.get(key), opening.get(key)
        items.append({"from": prev.period.token, "to": cur.period.token, "view": key[0], "record_key": key[1],
                      "currency": (c or o)[1], "previous_closing": f"{c[0]:.2f}" if c else "", "current_opening": f"{o[0]:.2f}" if o else "",
                      "difference": f"{o[0] - c[0]:.2f}" if c and o else "", "status": "MATCH" if c and o and c[0] == o[0] else "DIFFERENCE",
                      "previous_evidence": c[2] if c else "absent", "current_evidence": o[2] if o else "absent"})
    return items


def january_opening(case):
    """January's opening rows: all at 31 Dec 2025 17:00 GMT, identified by the 20251231 / 1231 date in their IDs."""
    o = opening_positions(case)
    return {f"{k[0]} {k[1]}": (f"{v[0]:.2f}", v[1], v[2]) for k, v in sorted(o.items())}


# ----------------------------------------------------------------------------------------------- packs and oracles
def load_months(demo=DEMO):
    return {p.token: Case(Path(demo) / "datasets" / p.token, p) for p in MONTHS}


def run_manifest(demo=DEMO):
    return json.loads((Path(demo) / "verification" / "run_manifest.json").read_text(encoding="utf-8"))


def load_pack(demo, pack_id):
    return json.loads((Path(demo) / "packs" / pack_id / "pack.json").read_text(encoding="utf-8"))


def pack_findings(pack, case_dir):
    """Content hash and identity; synthetic notice; evidence register hashes = dataset files; every cited evidence ID
    resolves to a register record whose file and line hold that primary key; exceptions OPEN and awaiting review."""
    out = []
    rec = pack["audit_trail"]["pack_content_sha256"]
    if pack_model.content_hash(pack) != rec or not pack["metadata"]["pack_id"].endswith(rec[:12]):
        out.append("pack content hash or identity does not verify")
    if pack["metadata"]["synthetic_notice"] != SYNTHETIC or pack["statements"]["synthetic_notice"] != SYNTHETIC:
        out.append("synthetic notice missing")
    case_dir = Path(case_dir)
    for i in pack["audit_trail"]["inputs"]:
        p = case_dir / i["relative_path"]
        if not p.is_file() or sha256(p) != i["sha256_actual"] or not i["matches"]:
            out.append(f"input {i['relative_path']}: hash differs or missing")
    records = {r["evidence_id"]: r for r in pack["evidence_register"]["records"]}
    files = {f["evidence_id"] for f in pack["evidence_register"]["files"]}
    cache = {}
    for eid, r in records.items():
        key = (r["source_file"])
        if key not in cache:
            _, rows = read_csv(case_dir / r["source_file"])
            cache[key] = rows
        rows = cache[key]
        if not 2 <= r["source_line"] <= len(rows) + 1 or rows[r["source_line"] - 2][schema.columns(r["file_id"])[0]] != r["primary_key"]:
            out.append(f"evidence record {eid} does not resolve to {r['source_file']}#L{r['source_line']}")
    cited = [e for c in pack["control_register"] for r in c["results"] for e in r["evidence_ids"]]
    cited += [e for x in pack["exception_register"]["exceptions"] for e in x["evidence_ids"]]
    cited += [e for g in pack["investigation_group_register"]["groups"] for e in g["evidence_ids"]]
    for e in set(cited):
        if e not in records and e not in files:
            out.append(f"cited evidence {e} does not resolve")
    for x in pack["exception_register"]["exceptions"]:
        if (x["status"], x["review_status"]) != ("OPEN", "AWAITING_HUMAN_REVIEW") or x["cause_category"]:
            out.append(f"{x['exception_id']}: not OPEN / awaiting review, or a cause is recorded")
    return out


def expected_vs_actual(package=PACKAGE, demo=DEMO):
    """Per month: the oracle's expected outcome against the generated pack (root causes, groups as sets of root causes)."""
    out = []
    for rec in run_manifest(demo)["months"]:
        token = rec["period_id"][4:]
        oracle = json.loads((Path(package) / token / "scenario_definition.json").read_text(encoding="utf-8"))
        exp = oracle["expected_reconciliation_outcome"]
        pack = load_pack(demo, rec["pack_id"])
        actual = sorted(x["root_cause"] for x in pack["exception_register"]["exceptions"])
        rc_of = {x["exception_id"]: x["root_cause"] for x in pack["exception_register"]["exceptions"]}
        actual_groups = sorted(sorted(rc_of[i.strip()] for i in g["exception_ids"].split(";")) for g in pack["investigation_group_register"]["groups"])
        pre = {x["exception_id"]: x["root_cause"] for x in oracle["pre_validation_observed"]["exceptions"]}
        expected_groups = sorted(sorted(pre[i.strip()] for i in g.split(";")) for g in exp["investigation_groups"])
        by_outcome = pack["executive_summary"]["control_outcomes"]["by_outcome"]
        out.append({"month": token, "scenario_types": oracle["scenario_types"], "expected_exceptions": exp["exceptions"],
                    "actual_exceptions": len(actual), "difference": len(actual) - exp["exceptions"],
                    "expected_case_status": exp["case_status"], "actual_case_status": pack["executive_summary"]["engine_case_status"],
                    "expected_root_causes": sorted(exp["exception_root_causes"]), "actual_root_causes": actual,
                    "root_causes_match": actual == sorted(exp["exception_root_causes"]),
                    "groups_match": actual_groups == expected_groups,
                    "engine_results_by_outcome": rec["engine_results_by_outcome"],
                    "pre_validation_results_by_outcome": oracle["pre_validation_observed"]["results_by_outcome"],
                    "pack_results_by_outcome": by_outcome,
                    "result": "MATCH" if actual == sorted(exp["exception_root_causes"]) and actual_groups == expected_groups
                    and pack["executive_summary"]["engine_case_status"] == exp["case_status"] else "DIFFERENCE"})
    return out


# ------------------------------------------------------------------------------------------------------- report
def run(package=PACKAGE, demo=DEMO):
    months = load_months(demo)
    sept = Case(SEPTEMBER, SEPT)
    res = {"synthetic_notice": SYNTHETIC, "package_integrity": package_integrity(package), "months": {}}
    for token, case in months.items():
        dp, offsets = date_findings(case)
        res["months"][token] = {"schema": schema_problems(case), "id_dates": id_date_problems(case), "keys": key_problems(case),
                                "duplicate_bank_references": {f"{a} {r}": v for (a, r), v in duplicate_bank_references(case).items()},
                                "relationships": relationship_findings(case), "arithmetic": arithmetic_findings(case),
                                "dates": dp, "timestamp_offsets": offsets,
                                "rows": {fid: len(case.rows[fid]) for fid in schema.CSV_FILES}}
    chain = [months[p.token] for p in MONTHS] + [sept]
    res["continuity"] = [i for a, b in zip(chain, chain[1:]) for i in continuity(a, b)]
    res["january_opening"] = january_opening(months["2026-01"])
    res["expected_vs_actual"] = expected_vs_actual(package, demo)
    rm = run_manifest(demo)
    res["packs"] = {r["pack_id"]: pack_findings(load_pack(demo, r["pack_id"]), Path(demo) / r["dataset"]) for r in rm["months"]}
    return res


def write(res, package=PACKAGE, demo=DEMO):
    d = Path(demo) / "verification"
    d.mkdir(parents=True, exist_ok=True)
    (d / "verification_results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8", newline="\n")
    inv = inventory(package)
    with open(d / "package_inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(inv[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(inv)
    with open(d / "continuity.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res["continuity"][0]), lineterminator="\n")
        w.writeheader()
        w.writerows(res["continuity"])


def main():
    ap = argparse.ArgumentParser(description="Verify the Jan-Aug 2026 historical demonstration (read-only)")
    ap.add_argument("--package", default=str(PACKAGE))
    ap.add_argument("--demo", default=str(DEMO))
    ap.add_argument("--write", action="store_true", help="store results in demo_history/verification/")
    a = ap.parse_args()
    res = run(a.package, a.demo)
    if a.write:
        write(res, a.package, a.demo)
    print("package integrity:", res["package_integrity"] or "OK")
    for token, m in res["months"].items():
        bad = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in m.items()
               if k not in ("rows", "timestamp_offsets", "duplicate_bank_references") and v}
        print(f"{token}: offsets {m['timestamp_offsets']}  findings {bad or 'none'}  duplicate bank refs {m['duplicate_bank_references'] or 'none'}")
    cont = Counter((i["from"], i["to"], i["status"]) for i in res["continuity"])
    for k, n in sorted(cont.items()):
        print("continuity", k, n)
    for x in res["expected_vs_actual"]:
        print(f"{x['month']}: expected {x['expected_exceptions']} actual {x['actual_exceptions']} -> {x['result']}")
    print("packs:", {k: v or "OK" for k, v in res["packs"].items()})


if __name__ == "__main__":
    main()
