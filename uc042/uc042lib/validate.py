"""Validate a UC-042 case directory by recomputing checks from its evidence files.

Usage (from the uc042/ folder):
    python -m uc042lib.validate                                   # clean baseline
    python -m uc042lib.validate <case_dir>                        # any prepared case or dataset

Stages:
  1. Load: read each expected file. A file is MISSING, EMPTY (no data rows where rows are required),
     UNUSABLE (wrong header, not a PDF, unreadable, key details missing, or an invalid row in a
     scope-defining file) or AMBIGUOUS (case preparation found more than one candidate).
  2. Structure: every row is checked against uc042lib.structure. Invalid rows are excluded from all
     calculations and reported as DQ-FIELD findings (file, line, field, raw value, error).
  3. Evidence gate: a check whose required files (schema.DEPENDS) are not all available is not run;
     it returns one INSUFFICIENT_EVIDENCE result. Checks with sufficient evidence keep running.
  4. Controls: values are recomputed from source rows. Where an excluded row could have affected a
     scope, that scope returns INSUFFICIENT_EVIDENCE rather than a result computed on incomplete input.
  5. Exceptions: one per root cause.

Independence: this module reads only the case files. The manifest (if present) is case metadata used
to detect changed files; it is never treated as proof that a file is valid.
Outcomes: PASS, FAIL, INSUFFICIENT_EVIDENCE, NOT_APPLICABLE.
"""
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from . import schema
from .money import batch_net_signed, parse_signed, parse_unsigned, signed
from .period import MONTH_TOKEN, PeriodConfig, bank_holidays, resolve
from .period import business_day_after as _business_day_after
from .structure import check_period, check_rows, diagnose_header, parse_ts, read_csv, taint_scope

LON = ZoneInfo(schema.TZ)
PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_SET = PROJECT / "uc042_dataset" / "set_01_clean_baseline"
UK_BANK_HOLIDAYS = bank_holidays(2026)  # England and Wales, computed (uc042lib.period); kept for existing imports
ZERO = Decimal("0.00")
PASS, FAIL, INSUF, NA = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE"


@dataclass(frozen=True)
class EngineRules:
    """The explicit rule configuration of ONE engine run (passed to Validator; never a mutable module global, so runs with
    different configurations cannot affect each other).

    zero_difference_outcome: the outcome of a reconciled zero difference in C06-DIFFERENCE / C08-DIFFERENCE. Approved
    17 Nov 2026: PASS. Packs published before that date were generated with NOT_APPLICABLE; they are immutable, and the
    reproducibility tests rebuild them under PUBLISHED_RULES_BEFORE_17_NOV_2026."""
    zero_difference_outcome: str = PASS

    def __post_init__(self):
        if self.zero_difference_outcome not in (PASS, NA):
            raise ValueError(f"zero_difference_outcome must be {PASS} or {NA}")

    def recorded(self):
        """The rule configuration as recorded in a pack's configuration_fingerprint: every departure from the behaviour
        the published (pre-17-Nov-2026) packs were generated with. The published rules record nothing, so those packs'
        fingerprints stay byte-reproducible; a pack built under the approved rule records it."""
        return {} if self.zero_difference_outcome == NA else {"c06_c08_zero_difference": self.zero_difference_outcome}


APPROVED_RULES = EngineRules()
PUBLISHED_RULES_BEFORE_17_NOV_2026 = EngineRules(zero_difference_outcome=NA)
CONTROL_OF = {"C03-POLICY": "C03", "C03-POINT": "C03", "C01-COVER": "C01", "C07-COVER": "C07", "C14-COVER": "C14",
              "DQ23-STATEMENT": "DQ23", "DQ22-CONTINUITY": "DQ22", "BC-VS-EOD": "C07", "CASH-BANK-LINK": "C05/C07",
              "BANK-CASH-LINK": "C05/C07", "C04-REQUIREMENT": "C04", "C05-RESOURCE": "C05", "C06-DIFFERENCE": "C06",
              "C07-BANK-EVIDENCE": "C07", "RC2-LEDGER": "C07", "C08-DIFFERENCE": "C08", "C11-BATCH-ARITH": "C11",
              "C11-BATCH-BANK": "C11", "C11-TXN-LINE": "C11", "C11-BANK-ENTRY": "C11", "FUND-TOPUP": "C06",
              "RC4-DIRECT": "C09", "C09-ALLOCATION": "C09", "C12-REFUND": "C12", "CBAL-NONNEG": "C04",
              "CBAL-ROLLFWD": "C04", "C13-CURRENCY": "C13", "C10-DESIGNATION": "C10", "DISC-LOG": "C06/C08"}


def business_day_after(d, n=1):
    """The n-th England and Wales business day after d (any year; uc042lib.period)."""
    return _business_day_after(d, n)


def _date_or_none(text):
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def fname(fid, period=None):
    """Canonical file name of an evidence type for a period (the baseline period's name without one)."""
    return period.filename(fid) if period else (schema.CSV_FILES.get(fid) or schema.PDF_FILES.get(fid))[0]


class Validator:
    def __init__(self, root, period=None, rules=None):
        """`period`: the reporting period (PeriodConfig or PER-YYYY-MM). Without it, the case must declare exactly one
        period itself (manifest, canonical file names or calendar): there is no default month (uc042lib.period.resolve).
        `rules`: the run's EngineRules (default: the approved rules)."""
        self.root = Path(root)
        self.period = resolve(self.root, period)
        self.rules = rules if rules is not None else APPROVED_RULES
        if not isinstance(self.rules, EngineRules):
            raise TypeError("rules must be an EngineRules instance")
        self.results = []
        self.data = {}        # file_id -> list of structurally valid row dicts (with _line)
        self.pdf = {}         # file_id -> {label: value}
        self.state = {}       # file_id -> (status, root_cause) for files that are not available
        self.taint = defaultdict(list)  # file_id -> [(scope of an excluded row, root_cause)]
        self._gate = {}
        self.exceptions = []
        self.groups = []
        self.candidates = []

    # --- result helpers -------------------------------------------------
    def ref(self, fid, row=None):
        return f"{fid}:{fname(fid, self.period)}" + (f"#L{row['_line']}" if row is not None else "")

    def add(self, check, control, scope, outcome, computed="", reported="", evidence=(), note="", root="", evidence_status="",
            structured=None):
        self.results.append({"check_id": check, "control": control, "scope": scope, "outcome": outcome,
                             "computed": computed, "reported": reported, "evidence": "; ".join(evidence), "note": note,
                             "root_cause": root, "evidence_status": evidence_status, "structured": structured or {}})

    # --- E1: timing evidence (D1: one business day; D-E1a: explains, never resolves) ---------------
    def timing_items(self, acct, d):
        """Cross-day items at reconciliation point d for one account, found through the existing reference links.

        An item is a cash-book entry and a bank entry linked by reference (same account, currency and signed amount)
        where one side is recorded by the point and the other after it. It counts as timing evidence only if the
        later side is booked no later than the next business day after d (D1) and the evidence for that day is usable.
        Returns a list of dicts: effect on (bank - ledger), status (IN_WINDOW / OUTSIDE_WINDOW / UNVERIFIABLE), rows."""
        pt = self.point(d)
        window_end = business_day_after(d)
        by_ref = defaultdict(list)
        for e in self.rows("IN-09"):
            if e["account_id"] == acct:
                for r in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
                    by_ref[r].append(e)
        items = []
        for c in self.rows("IN-10"):
            if c["account_id"] != acct or c["entry_type"] == "OPENING_BALANCE":
                continue
            hits = by_ref.get(c["payment_reference"], [])
            if not hits:
                posted = parse_ts(c["posted_ts"])
                if posted <= pt and posted.astimezone(LON).date() == d and \
                        (window_end > self.period.end or self.evidence_gap(acct, window_end)):
                    items.append({"effect": -signed(c["amount"], c["dc_indicator"], "cashbook"), "status": "UNVERIFIABLE",
                                  "ledger_row": c, "bank_row": None, "later": window_end})
                continue
            if len(hits) != 1:
                continue
            b = hits[0]
            ledger_amt, bank_amt = signed(c["amount"], c["dc_indicator"], "cashbook"), signed(b["amount"], b["dc_indicator"], "bank")
            if ledger_amt != bank_amt or b["currency"] != c["currency"]:
                continue  # reference link without equal amount is not timing evidence
            posted, booked = parse_ts(c["posted_ts"]), parse_ts(b["booking_ts"])
            if posted <= pt < booked:
                later, effect = booked.astimezone(LON).date(), -ledger_amt   # ledger has it, bank does not yet
            elif booked <= pt < posted:
                later, effect = posted.astimezone(LON).date(), bank_amt      # bank has it, ledger does not yet
            else:
                continue
            if later > window_end:
                status = "OUTSIDE_WINDOW"
            elif later > self.period.end or self.evidence_gap(acct, later):
                status = "UNVERIFIABLE"
            else:
                status = "IN_WINDOW"
            items.append({"effect": effect, "status": status, "ledger_row": c, "bank_row": b, "later": later})
        return items

    def timing_structured(self, acct, d, diff):
        """D3: the timing items behind a C08 evidence status, as structured data (no new calculation)."""
        items = self.timing_items(acct, d)
        good = [i for i in items if i["status"] == "IN_WINDOW"]
        explained = sum((i["effect"] for i in good), ZERO)
        return {"timing_items": [{"ledger_entry_id": i["ledger_row"]["ledger_entry_id"],
                                  "bank_entry_id": i["bank_row"]["bank_entry_id"] if i["bank_row"] else "",
                                  "reference": i["ledger_row"]["payment_reference"], "effect_on_difference": str(i["effect"]),
                                  "cleared_or_expected": str(i["later"]), "item_status": i["status"]} for i in items],
                "explained_by_timing": str(explained), "residual_unexplained": str(diff - explained)}

    def timing_assessment(self, acct, d, diff):
        """Evidence status of a non-zero bank-ledger difference. Never changes the outcome."""
        items = self.timing_items(acct, d)
        good = [i for i in items if i["status"] == "IN_WINDOW"]
        explained = sum((i["effect"] for i in good), ZERO)
        refs = [x for i in good for x in (self.ref("IN-10", i["ledger_row"]), self.ref("IN-09", i["bank_row"]))]
        desc = "; ".join(f"{i['ledger_row']['ledger_entry_id']} / {i['bank_row']['bank_entry_id']} "
                         f"(ref {i['ledger_row']['payment_reference']}, {i['effect']}, cleared {i['later']})" for i in good)
        if good and explained == diff:
            return "TIMING_EVIDENCED", (f"difference explained by timing: {desc}; cleared within one business day (D1); "
                                        "awaiting human confirmation; not resolved"), refs
        if good:
            return "TIMING_PARTIAL", (f"difference partly explained by timing ({explained} of {diff}): {desc}; "
                                      f"residual {diff - explained} unexplained; awaiting human review"), refs
        if any(i["status"] == "UNVERIFIABLE" for i in items):
            return "TIMING_UNVERIFIABLE", "possible timing item, but the clearing evidence is outside the period or unavailable", []
        if any(i["status"] == "OUTSIDE_WINDOW" for i in items):
            return "NOT_EVIDENCED", "cross-day item found but it cleared later than one business day (D1)", []
        return "NOT_EVIDENCED", "", []

    def unavailable(self, fid, status, note, check="V01-SCHEMA", outcome=FAIL, computed="", evidence=None):
        kind = {"MISSING": "MISSING_FILE", "EMPTY": "EMPTY_FILE", "UNUSABLE": "INVALID_FILE", "AMBIGUOUS": "AMBIGUOUS_FILE",
                "WRONG_PERIOD": "WRONG_PERIOD"}[status]
        root = f"{kind}|{fid}"
        self.state[fid] = (status, root)
        self.add(check, "INTEGRITY" if check == "V00-FILE" else "DQ", fid, outcome, computed,
                 evidence=evidence if evidence is not None else [self.ref(fid)], note=note, root=root)

    def gate(self, check):
        """True if every file the check depends on is available; otherwise one INSUFFICIENT_EVIDENCE result."""
        if check not in self._gate:
            bad = [f for f in schema.DEPENDS.get(check, []) if f in self.state]
            if bad:
                self.add(check, CONTROL_OF[check], "all scopes", INSUF, evidence=[self.ref(f) for f in bad],
                         note="not assessed: depends on " + ", ".join(f"{f} ({self.state[f][0].lower()})" for f in bad),
                         root=self.state[bad[0]][1])
            self._gate[check] = not bad
        return self._gate[check]

    def tainted(self, fid, account=None, currency=None, d=None, upto=None, batch=None, client=None, ref=None, pk=None,
                on_or_before=None):
        """Root cause if an excluded row of `fid` could belong to the given scope, else None.
        A scope key that was unreadable on the excluded row matches anything (conservative)."""
        for sc, root in self.taint.get(fid, []):
            if account is not None and sc["account"] not in (None, account):
                continue
            if currency is not None and sc["currency"] not in (None, currency):
                continue
            if d is not None and sc["date"] not in (None, d):
                continue
            if upto is not None and sc["date"] is not None and not self.period.start <= sc["date"] <= upto:
                continue  # rows before the period start are represented by the opening balance
            if on_or_before is not None and sc["date"] is not None and sc["date"] > on_or_before:
                continue
            if batch is not None and sc["batch"] not in (None, batch):
                continue
            if client is not None and sc["client"] not in (None, client):
                continue
            if ref is not None and sc["refs"] is not None and ref not in sc["refs"]:
                continue
            if pk is not None and sc["pk"] not in (None, pk):
                continue
            return root
        return None

    def evidence_gap(self, acct, d):
        """Root cause if bank evidence for an account and day is missing or invalid; None if usable."""
        for fid in ("IN-08", "IN-07", "IN-09"):
            r = self.tainted(fid, account=acct, d=d)
            if r:
                return r
        if (acct, d) not in self.eod_by or (acct in self.sga and (acct, d) not in self.bc_by):
            return f"MISSING_BANK_EVIDENCE|{acct}|{d}"
        return None

    # --- stage 1-2: loading and structure -------------------------------------
    def load(self):
        manifest = {}
        mpath = self.root / "manifest.csv"
        if mpath.exists():
            with open(mpath, encoding="utf-8") as f:
                listed = list(csv.DictReader(f))
            manifest = {r["file_id"]: r for r in listed}
            for r in listed:  # a file ID listed more than once (two policy versions): the row of the file this run reads
                if r.get("filename") == fname(r["file_id"], self.period):
                    manifest[r["file_id"]] = r
        intake, rejected_like = {}, {}
        ipath = self.root / "intake.csv"
        if ipath.exists():
            with open(ipath, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r["decision"] == "AMBIGUOUS":
                        for f_ in r["file_id"].split("/"):
                            intake.setdefault(f_, []).append(r["original_path"])
                    elif r["decision"] == "REJECTED" and r.get("probable_file_id") in schema.CSV_FILES:
                        rejected_like.setdefault(r["probable_file_id"], []).append(f"{r['original_path']} ({r['reason']})")
        for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES):
            m = manifest.get(fid)
            sub = "source_data" if fid in schema.CSV_FILES else "supporting_documents"
            path = self.root / sub / fname(fid, self.period)
            required = fid in schema.CSV_FILES or schema.PDF_FILES[fid][2] == "REQUIRED"
            if fid in intake and not path.exists():
                self.unavailable(fid, "AMBIGUOUS", "more than one candidate file at intake; none selected: " + ", ".join(intake[fid]),
                                 check="V00-FILE", outcome=INSUF if required else NA, evidence=[f"intake.csv ({len(intake[fid])} candidates)"])
                continue
            if not path.exists():
                if required:
                    hint = ("; rejected at intake: " + " | ".join(rejected_like[fid])) if fid in rejected_like else ""
                    self.unavailable(fid, "MISSING", f"required file not provided: {fname(fid, self.period)}{hint}", check="V00-FILE", outcome=INSUF,
                                     evidence=[f"intake.csv ({len(rejected_like[fid])} rejected candidate)"] if hint else [])
                else:
                    self.state[fid] = ("MISSING", "")
                    self.add("V00-FILE", "INTEGRITY", fid, NA, note=f"optional file not provided: {fname(fid, self.period)}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if manifest and m is None:
                self.add("V00-FILE", "INTEGRITY", fid, FAIL, evidence=[self.ref(fid)], note="file not listed in manifest")
            elif m is not None and m["sha256"] != digest:
                self.add("V00-FILE", "INTEGRITY", fid, FAIL, digest, m["sha256"], [self.ref(fid)], "SHA-256 differs from manifest")
            if fid in schema.CSV_FILES:
                self.load_csv(fid, path, m)
            else:
                self.load_pdf(fid, path, m)
        self.check_other_periods(manifest)

    def check_other_periods(self, manifest):
        """A canonical evidence file of another month in the case is never used (periods are never mixed)."""
        mine = {self.period.filename(fid) for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES)}
        for sub in ("source_data", "supporting_documents"):
            d = self.root / sub
            for f in sorted(d.iterdir()) if d.is_dir() else []:
                mt = MONTH_TOKEN.search(f.name)
                if f.name in mine or not mt:
                    continue
                other = PeriodConfig.from_id("PER-" + mt.group(1))
                fid = other.file_id_of(f.name)
                if fid and fid != "IN-19":
                    self.add("V00-FILE", "INTEGRITY", fid, FAIL, f.name, self.period.filename(fid), [f"{sub}/{f.name}"],
                             f"file for another reporting period ({other.period_id}) present; not used for {self.period.period_id}")

    def load_csv(self, fid, path, m):
        expected_cols = schema.columns(fid)
        try:
            header, rows = read_csv(path)
        except (UnicodeDecodeError, csv.Error) as e:
            self.unavailable(fid, "UNUSABLE", f"not readable as UTF-8 CSV ({type(e).__name__}); file not used")
            return
        if header != expected_cols:
            diag = diagnose_header(header)
            note = diag["message"] if diag["file_id"] == fid else \
                f"header does not match {fid}; " + (diag["message"] if diag["status"] != "UNKNOWN" else "it resembles no evidence type")
            self.add("V01-SCHEMA", "DQ", fid, FAIL, ",".join(header or []), ",".join(expected_cols),
                     [self.ref(fid)], note + "; file not used", root=f"INVALID_FILE|{fid}")
            self.state[fid] = ("UNUSABLE", f"INVALID_FILE|{fid}")
            return
        reported = m["record_count"] if m else ""
        if not rows and fid not in schema.EMPTY_ALLOWED:
            self.add("V01-SCHEMA", "DQ", fid, INSUF, "0 rows", reported, [self.ref(fid)],
                     "file present but contains no data rows", root=f"EMPTY_FILE|{fid}")
            self.state[fid] = ("EMPTY", f"EMPTY_FILE|{fid}")
            return
        valid, findings = check_rows(fid, rows)
        root = f"INVALID_ROWS|{fid}"
        for x in findings:
            self.add("DQ-FIELD", "DQ", f"{fid} L{x['line']} {x['field']}", FAIL, x["error"], x["raw"],
                     [self.ref(fid, x["row"])], f"row excluded from all calculations: {x['field']} {x['error']}", root=root)
        bad_lines = sorted({x["line"] for x in findings})
        for line in bad_lines:
            row = next(x["row"] for x in findings if x["line"] == line)
            self.taint[fid].append((taint_scope(row), root))
        problems = [f"{len(bad_lines)} invalid row(s) excluded: lines " + ", ".join(map(str, bad_lines[:20]))] if bad_lines else []
        if m is not None and m["record_count"] != str(len(rows)):
            problems.append(f"row count {len(rows)} differs from manifest {m['record_count']}")
        self.add("V01-SCHEMA", "DQ", fid, FAIL if problems else PASS, f"{len(rows)} rows", reported,
                 [self.ref(fid)], "; ".join(problems), root=root if problems else "")
        if bad_lines and fid in schema.SCOPE_FILES:
            self.state[fid] = ("UNUSABLE", root)
            return
        self.data[fid] = self.apply_period(fid, valid)

    def apply_period(self, fid, valid):
        """Reporting-period stage (the period's rules, uc042lib.period). Returns the rows usable for calculations."""
        refs = None
        rules = self.period.period_rules
        if "event_ref" in rules.get(fid, {}):
            ev = rules[fid]["event_ref"]
            refs = {r[key]: date.fromisoformat(r[ev["date_field"]]) for f, key in ev["sources"].items() for r in self.data.get(f, [])}
        kept, findings, counts = check_period(fid, valid, refs, self.period)
        if not findings:
            return kept
        if counts["applicable"] == 0:
            dates = sorted({x["raw"][:10] for x in findings})
            self.add("DQ-PERIOD", "DQ", fid, FAIL, f"0 of {len(valid)} rows in {self.period.start} to {self.period.end}",
                     f"dates found {dates[0]} to {dates[-1]}", [self.ref(fid)],
                     f"no row of this file falls in the reporting period ({counts['permitted']} permitted boundary row(s) do not count); "
                     "file not used", root=f"WRONG_PERIOD|{fid}")
            self.state[fid] = ("WRONG_PERIOD", f"WRONG_PERIOD|{fid}")
            return []
        root = f"OUT_OF_PERIOD_ROWS|{fid}"
        for x in findings:
            self.add("DQ-PERIOD", "DQ", f"{fid} L{x['line']} {x['field']}", FAIL, x["error"], x["raw"],
                     [self.ref(fid, x["row"])], f"row excluded from all calculations: {schema.CSV_FILES[fid][1]}, {x['field']} {x['raw']}",
                     root=root)
        for line in sorted({x["line"] for x in findings}):
            self.taint[fid].append((taint_scope(next(x["row"] for x in findings if x["line"] == line)), root))
        return kept

    def load_pdf(self, fid, path, m):
        from pypdf import PdfReader
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF-"):
            self.add("V01-PDF", "DQ", fid, FAIL, evidence=[self.ref(fid)], note="not a PDF file", root=f"INVALID_FILE|{fid}")
            self.state[fid] = ("UNUSABLE", f"INVALID_FILE|{fid}")
            return
        try:
            reader = PdfReader(str(path))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:  # pypdf raises several error types for damaged files
            self.add("V01-PDF", "DQ", fid, FAIL, evidence=[self.ref(fid)], note=f"PDF not readable ({type(e).__name__})",
                     root=f"INVALID_FILE|{fid}")
            self.state[fid] = ("UNUSABLE", f"INVALID_FILE|{fid}")
            return
        details = {}
        for label in schema.PDF_FILES[fid][3]:
            mt = re.search(rf"^{re.escape(label)}: (.+)$", text, re.M)
            if mt:
                details[label] = mt.group(1).strip()
        missing = [lbl for lbl in schema.PDF_FILES[fid][3] if lbl not in details]
        pages_ok = m is None or m["record_count"] == str(len(reader.pages))
        self.add("V01-PDF", "DQ", fid, PASS if not missing and pages_ok else FAIL, f"{len(reader.pages)} page(s)",
                 m["record_count"] if m else "", [self.ref(fid)],
                 ("missing key details: " + ", ".join(missing)) if missing else "genuine PDF; key details parsed",
                 root=f"INVALID_FILE|{fid}" if missing else "")
        if missing:
            self.state[fid] = ("UNUSABLE", f"INVALID_FILE|{fid}")
            return
        self.pdf[fid] = details

    # --- convenience --------------------------------------------------------
    def rows(self, fid):
        return self.data.get(fid, [])

    def point(self, d):
        return datetime.combine(d, self.point_time, tzinfo=LON)

    # --- stage 3-5 ------------------------------------------------------------
    def run(self):
        self.load()
        self.setup()
        self.check_policy_and_points()
        self.check_coverage()
        self.check_statements()
        self.check_cashbook_bank_links()
        self.check_internal()
        self.check_external()
        self.check_settlement()
        self.check_topups()
        self.check_direct_and_allocation()
        self.check_unmatched_bank_entries()
        self.check_refunds()
        self.check_client_rollforward()
        self.check_currency_isolation()
        self.check_designation()
        self.check_discrepancy_log()
        self.check_checklist()
        self.group_exceptions()
        self.correlate_exceptions()
        return self.results

    def setup(self):
        self.recon_days = [date.fromisoformat(r["calendar_date"]) for r in self.rows("IN-01") if r["is_recon_day"] == "true"]
        self.accounts = {r["account_id"]: r for r in self.rows("IN-02")}
        self.sga = sorted(a for a, r in self.accounts.items() if r["account_class"] == "RELEVANT_FUNDS_BANK")
        self.ccy_of = {a: r["currency"] for a, r in self.accounts.items()}
        self.eod = {r["statement_id"]: r for r in self.rows("IN-08")}
        self.eod_by = {(r["account_id"], date.fromisoformat(r["statement_date"])): r for r in self.rows("IN-08")}
        self.bc = {r["statement_id"]: r for r in self.rows("IN-07")}
        self.bc_by = {(r["account_id"], parse_ts(r["as_at_ts"]).date()): r for r in self.rows("IN-07")}
        self.entries_by_stmt = defaultdict(list)
        for e in self.rows("IN-09"):
            self.entries_by_stmt[e["statement_id"]].append(e)
        self.txn = {t["txn_id"]: t for t in self.rows("IN-11")}
        self.point_time = None
        pol = self.pdf.get("IN-17", {})
        mt = re.match(r"^(\d{2}):(\d{2}) Europe/London$", pol.get("Reconciliation point", ""))
        if mt:
            self.point_time = time(int(mt.group(1)), int(mt.group(2)))
        elif "IN-17" in self.pdf:
            self.state["IN-17"] = ("UNUSABLE", "INVALID_FILE|IN-17")
            self.add("V01-PDF", "DQ", "IN-17", FAIL, pol.get("Reconciliation point", ""), evidence=[self.ref("IN-17")],
                     note="reconciliation point not in the form HH:MM Europe/London", root="INVALID_FILE|IN-17")
        effective = _date_or_none(pol.get("Effective date", ""))
        if "IN-17" in self.pdf and "IN-17" not in self.state and effective is not None and effective > self.period.end:
            # a policy that takes effect after the period does not govern it; it is never applied to force a result
            del self.pdf["IN-17"]
            self.state["IN-17"] = ("UNUSABLE", "INVALID_FILE|IN-17")
            self.add("V01-PDF", "DQ", "IN-17", FAIL, f"effective {effective}", f"in force by {self.period.end}", [self.ref("IN-17")],
                     note=f"policy effective from {effective}, after the period end; not applicable to {self.period.period_id}",
                     root="INVALID_FILE|IN-17")

    def check_policy_and_points(self):
        """C03 / DQ21: every point-dependent record is taken at the policy reconciliation point."""
        if not self.gate("C03-POLICY"):
            self.gate("C03-POINT")
            return
        pol = self.pdf["IN-17"]
        self.add("C03-POLICY", "C03", "period", PASS if pol.get("Reconciliation method") == "STANDARD" and pol.get("Internal reconciliation basis") == "Per currency" else FAIL,
                 f"point {self.point_time:%H:%M}; method {pol.get('Reconciliation method')}; basis {pol.get('Internal reconciliation basis')}",
                 evidence=[self.ref("IN-17")], note="deterministic parse of synthetic key-details block; reviewer confirmation not modelled in milestone 1")
        self.gate("C03-POINT")
        for fid, col, datecol in (("IN-05", "reconciliation_point_ts", "recon_date"), ("IN-03", "as_at_ts", "recon_date")):
            if fid in self.state:
                self.add("C03-POINT", "C03", fid, INSUF, evidence=[self.ref(fid)], note=f"{fid} {self.state[fid][0].lower()}", root=self.state[fid][1])
                continue
            bad = [r for r in self.rows(fid) if parse_ts(r[col]) != self.point(date.fromisoformat(r[datecol]))]
            self.add("C03-POINT", "C03", fid, FAIL if bad else PASS, f"{len(bad)} off-point of {len(self.rows(fid))}",
                     evidence=[self.ref(fid, r) for r in bad[:5]] or [self.ref(fid)])
        if "IN-07" in self.state:
            self.add("C03-POINT", "C03", "IN-07", INSUF, evidence=[self.ref("IN-07")], note=f"IN-07 {self.state['IN-07'][0].lower()}", root=self.state["IN-07"][1])
            return
        bad = [r for r in self.rows("IN-07") if parse_ts(r["as_at_ts"]).timetz().replace(tzinfo=None) != self.point_time]
        self.add("C03-POINT", "C03", "IN-07", FAIL if bad else PASS, f"{len(bad)} off-point of {len(self.rows('IN-07'))}",
                 evidence=[self.ref("IN-07", r) for r in bad[:5]] or [self.ref("IN-07")])

    def check_coverage(self):
        """C01, C07, C14 (RC7): exactly one record per expected scope. Missing is never zero."""
        run01, run07, run14 = self.gate("C01-COVER"), self.gate("C07-COVER"), self.gate("C14-COVER")
        if not (run01 or run07 or run14):
            return
        def index(fid, keyfn):
            idx = defaultdict(list)
            for r in self.rows(fid):
                idx[keyfn(r)].append(r)
            return idx
        irr = index("IN-05", lambda r: (date.fromisoformat(r["recon_date"]), r["currency"]))
        erl = index("IN-06", lambda r: (date.fromisoformat(r["recon_date"]), r["account_id"]))
        bc = index("IN-07", lambda r: (parse_ts(r["as_at_ts"]).date(), r["account_id"]))
        eod = index("IN-08", lambda r: (date.fromisoformat(r["statement_date"]), r["account_id"]))
        sb = index("IN-12", lambda r: (date.fromisoformat(r["settlement_date"]), r["currency"], r["counterparty_type"]))
        clients = defaultdict(set)
        for r in self.rows("IN-03"):
            clients[r["currency"]].add(r["client_id"])
        snap = index("IN-03", lambda r: (date.fromisoformat(r["recon_date"]), r["currency"], r["client_id"]))
        cal = {r["calendar_date"]: r for r in self.rows("IN-01")}
        self._basis = lambda d, a=None: [self.ref("IN-01", cal[d.isoformat()])] + ([self.ref("IN-02", self.accounts[a])] if a else [])
        if run14:
            for fid in ("IN-03", "IN-12", "IN-07", "IN-08"):
                if fid in self.state:
                    self.add("C14-COVER", "C14", f"{fid} all scopes", INSUF, evidence=[self.ref(fid)],
                             note=f"{fid} {self.state[fid][0].lower()}; coverage not assessed", root=self.state[fid][1])
        c14 = lambda fid: run14 and fid not in self.state
        for d in self.recon_days:
            for ccy in sorted({self.ccy_of[a] for a in self.sga}):
                if run01:
                    self._cover("C01", "IN-05", irr.get((d, ccy), []), f"{d}/{ccy}", missing_outcome=FAIL, root=f"MISSING_RECON|{ccy}|{d}",
                                taint=self.tainted("IN-05", currency=ccy, d=d))
                if c14("IN-03"):
                    for c in sorted(clients[ccy]):
                        self._cover("C14", "IN-03", snap.get((d, ccy, c), []), f"{d}/{ccy}/{c}", root=f"MISSING_SNAPSHOT|{ccy}|{d}",
                                    taint=self.tainted("IN-03", currency=ccy, d=d, client=c))
                if c14("IN-12"):
                    for ctype in ("SCHEME", "ACQUIRER"):
                        self._cover("C14", "IN-12", sb.get((d, ccy, ctype), []), f"{d}/{ccy}/{ctype}", root=f"MISSING_BATCH|{ccy}|{d}",
                                    taint=self.tainted("IN-12", currency=ccy, d=d))
            for a in self.sga:
                if run07:
                    self._cover("C07", "IN-06", erl.get((d, a), []), f"{d}/{a}", missing_outcome=FAIL, root=f"MISSING_EXT_RECON|{a}|{d}",
                                taint=self.tainted("IN-06", account=a, d=d))
                if c14("IN-07"):
                    self._cover("C14", "IN-07", bc.get((d, a), []), f"{d}/{a}", root=f"MISSING_BANK_EVIDENCE|{a}|{d}",
                                taint=self.tainted("IN-07", account=a, d=d))
            if c14("IN-08"):
                for a in sorted(self.accounts):
                    self._cover("C14", "IN-08", eod.get((d, a), []), f"{d}/{a}", root=f"MISSING_BANK_EVIDENCE|{a}|{d}",
                                taint=self.tainted("IN-08", account=a, d=d))

    def _cover(self, control, fid, found, scope, missing_outcome=INSUF, root="", taint=None):
        if len(found) == 1:
            self.add(f"{control}-COVER", control, f"{fid} {scope}", PASS, evidence=[self.ref(fid, found[0])])
        elif not found:
            d, _, rest = scope.partition("/")
            acct = rest.split("/")[0] if rest.split("/")[0] in self.accounts else None
            if taint:
                self.add(f"{control}-COVER", control, f"{fid} {scope}", INSUF, evidence=self._basis(date.fromisoformat(d), acct),
                         note="expected record not usable: an invalid row in this file may be it", root=taint)
                return
            self.add(f"{control}-COVER", control, f"{fid} {scope}", missing_outcome, evidence=self._basis(date.fromisoformat(d), acct),
                     note="expected record absent (expected because of the cited calendar and account rows)", root=root)
        else:
            self.add(f"{control}-COVER", control, f"{fid} {scope}", FAIL, evidence=[self.ref(fid, r) for r in found], note="duplicate records")

    def check_statements(self):
        """DQ23 within-statement, DQ22 cross-day continuity, and 17:00 confirmation vs EOD entries."""
        if self.gate("DQ23-STATEMENT"):
            for sid, s in self.eod.items():
                ents = self.entries_by_stmt.get(sid, [])
                d = date.fromisoformat(s["statement_date"])
                t = self.tainted("IN-09", account=s["account_id"], d=d)
                if t:
                    self.add("DQ23-STATEMENT", "DQ23", sid, INSUF, evidence=[self.ref("IN-08", s)] + [self.ref("IN-09", e) for e in ents],
                             note="an invalid entry row may belong to this statement; arithmetic not assessed", root=t)
                    continue
                opening = signed(s["opening_balance_amount"], s["opening_balance_dc"], "bank")
                closing = signed(s["closing_balance_amount"], s["closing_balance_dc"], "bank")
                total = sum((signed(e["amount"], e["dc_indicator"], "bank") for e in ents), ZERO)
                issues = []
                if len(ents) != int(s["entry_count"]):
                    issues.append(f"entry_count {s['entry_count']} vs {len(ents)} entries")
                if opening + total != closing:
                    issues.append(f"opening {opening} + entries {total} != closing {closing}")
                for e in ents:
                    if e["account_id"] != s["account_id"] or e["currency"] != s["currency"] or e["booking_date"] != s["statement_date"]:
                        issues.append(f"entry {e['bank_entry_id']} account/currency/date mismatch")
                self.add("DQ23-STATEMENT", "DQ23", sid, FAIL if issues else PASS, f"{opening}+{total}={opening + total}", str(closing),
                         [self.ref("IN-08", s)] + [self.ref("IN-09", e) for e in ents], "; ".join(issues))
        if self.gate("DQ22-CONTINUITY"):
            opening_cash = {r["account_id"]: signed(r["amount"], r["dc_indicator"], "cashbook")
                            for r in self.rows("IN-10") if r["entry_type"] == "OPENING_BALANCE"}
            by_acct = defaultdict(list)
            for s in self.eod.values():
                by_acct[s["account_id"]].append(s)
            for acct, stmts in by_acct.items():
                stmts.sort(key=lambda s: s["statement_date"])
                first = stmts[0]
                first_open = signed(first["opening_balance_amount"], first["opening_balance_dc"], "bank")
                if acct in self.sga and "IN-10" in self.state:
                    self.add("DQ22-CONTINUITY", "DQ22", f"{acct} opening", INSUF, str(first_open), evidence=[self.ref("IN-08", first), self.ref("IN-10")],
                             note="cash-book opening position not available", root=self.state["IN-10"][1])
                elif acct in opening_cash:
                    ok = first_open == opening_cash[acct]
                    cash_row = next(r for r in self.rows("IN-10") if r["account_id"] == acct and r["entry_type"] == "OPENING_BALANCE")
                    self.add("DQ22-CONTINUITY", "DQ22", f"{acct} opening", PASS if ok else FAIL, str(first_open), str(opening_cash[acct]),
                             [self.ref("IN-08", first), self.ref("IN-10", cash_row)], "first bank opening vs cash-book opening position")
                elif acct in self.sga:
                    t = self.tainted("IN-10", account=acct)
                    self.add("DQ22-CONTINUITY", "DQ22", f"{acct} opening", INSUF if t else FAIL, str(first_open), evidence=[self.ref("IN-08", first)],
                             note="no usable cash-book opening balance row for this account", root=t or "")
                # Own-funds opening positions have no independent source: not assessed (listed in the report), no result emitted.
                for prev, cur in zip(stmts, stmts[1:]):
                    pd, cd = date.fromisoformat(prev["statement_date"]), date.fromisoformat(cur["statement_date"])
                    gap = [d for d in self.recon_days if pd < d < cd]
                    ev = [self.ref("IN-08", prev), self.ref("IN-08", cur)]
                    if gap:
                        self.add("DQ22-CONTINUITY", "DQ22", cur["statement_id"], INSUF, evidence=ev,
                                 note="statement gap: no statement for " + ", ".join(map(str, gap)),
                                 root=self.evidence_gap(acct, gap[0]) or f"MISSING_BANK_EVIDENCE|{acct}|{gap[0]}")
                        continue
                    pc = signed(prev["closing_balance_amount"], prev["closing_balance_dc"], "bank")
                    co = signed(cur["opening_balance_amount"], cur["opening_balance_dc"], "bank")
                    self.add("DQ22-CONTINUITY", "DQ22", cur["statement_id"], PASS if pc == co else FAIL, str(co), str(pc), ev)
        if self.gate("BC-VS-EOD"):
            for sid, b in self.bc.items():
                d = parse_ts(b["as_at_ts"]).date()
                s = self.eod_by.get((b["account_id"], d))
                gap = self.evidence_gap(b["account_id"], d)
                if s is None or (gap and gap.startswith("INVALID_ROWS")):
                    self.add("BC-VS-EOD", "C07", sid, INSUF, evidence=[self.ref("IN-07", b)],
                             note="no EOD statement for that day" if s is None else "statement or entries for that day include an invalid row",
                             root=gap or f"MISSING_BANK_EVIDENCE|{b['account_id']}|{d}")
                    continue
                asat = parse_ts(b["as_at_ts"])
                included = [e for e in self.entries_by_stmt.get(s["statement_id"], []) if parse_ts(e["booking_ts"]) <= asat]
                expected = signed(s["opening_balance_amount"], s["opening_balance_dc"], "bank") + \
                    sum((signed(e["amount"], e["dc_indicator"], "bank") for e in included), ZERO)
                got = signed(b["balance_amount"], b["balance_dc_indicator"], "bank")
                self.add("BC-VS-EOD", "C07", sid, PASS if got == expected else FAIL, str(expected), str(got),
                         [self.ref("IN-07", b), self.ref("IN-08", s)], f"opening + {len(included)} entries booked by 17:00")

    def check_cashbook_bank_links(self):
        """Cash book <-> bank by reference only; amounts compared after the link is made."""
        bank_sga = [e for e in self.rows("IN-09") if e["account_id"] in self.sga]
        by_ref = defaultdict(list)
        for e in bank_sga:
            for ref in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
                by_ref[(e["account_id"], ref)].append(e)
        cash_by_ref = defaultdict(list)
        for c in self.rows("IN-10"):
            if c["entry_type"] != "OPENING_BALANCE":
                cash_by_ref[(c["account_id"], c["payment_reference"])].append(c)
        if self.gate("CASH-BANK-LINK"):
            for c in self.rows("IN-10"):
                if c["entry_type"] == "OPENING_BALANCE":
                    continue
                matches = by_ref.get((c["account_id"], c["payment_reference"]), [])
                if len(matches) == 1:
                    b = matches[0]
                    ok = signed(b["amount"], b["dc_indicator"], "bank") == signed(c["amount"], c["dc_indicator"], "cashbook") and b["currency"] == c["currency"]
                    self.add("CASH-BANK-LINK", "C05/C07", c["ledger_entry_id"], PASS if ok else FAIL,
                             str(signed(c["amount"], c["dc_indicator"], "cashbook")), str(signed(b["amount"], b["dc_indicator"], "bank")),
                             [self.ref("IN-10", c), self.ref("IN-09", b)], "linked by reference; signed amounts compared")
                elif not matches:
                    d = parse_ts(c["posted_ts"]).date()
                    gap = self.evidence_gap(c["account_id"], d) or self.tainted("IN-09", account=c["account_id"], ref=c["payment_reference"])
                    self.add("CASH-BANK-LINK", "C05/C07", c["ledger_entry_id"], INSUF if gap else FAIL,
                             evidence=[self.ref("IN-10", c)],
                             note=("bank statement for that day not provided" if gap.startswith("MISSING") else
                                   "bank evidence for that day includes an excluded row (invalid or out of period)") if gap else "no bank entry carries this reference",
                             root=gap or f"UNMATCHED_CASHBOOK_ENTRY|{c['ledger_entry_id']}")
                else:
                    self.add("CASH-BANK-LINK", "C05/C07", c["ledger_entry_id"], FAIL, evidence=[self.ref("IN-10", c)] + [self.ref("IN-09", b) for b in matches],
                             note="reference matches more than one bank entry")
        if self.gate("BANK-CASH-LINK"):
            for b in bank_sga:
                refs = {b["bank_reference"], b["end_to_end_ref"]} - {""}
                if not any(cash_by_ref.get((b["account_id"], r)) for r in refs):
                    t = next((x for x in (self.tainted("IN-10", account=b["account_id"], ref=r) for r in refs) if x), None)
                    self.add("BANK-CASH-LINK", "C05/C07", b["bank_entry_id"], INSUF if t else FAIL, evidence=[self.ref("IN-09", b)],
                             note="an invalid cash-book row may be its counterpart" if t else "bank entry has no cash-book counterpart",
                             root=t or f"UNMATCHED_BANK_ENTRY|{b['bank_entry_id']}")

    def ledger_at(self, acct, when):
        """Item A: signed sum of cash-book entries posted at or before `when` (including the opening row).
        Returns (value or None, rows used, root cause if not computable)."""
        t = self.tainted("IN-10", account=acct, upto=when.date())
        if t:
            return None, [], t
        rows = [c for c in self.rows("IN-10") if c["account_id"] == acct and parse_ts(c["posted_ts"]) <= when]
        if not any(c["entry_type"] == "OPENING_BALANCE" for c in rows):
            excluded = [r for sc, r in self.taint.get("IN-10", []) if sc["account"] in (None, acct)]
            return None, rows, excluded[0] if excluded else ""
        return sum((signed(c["amount"], c["dc_indicator"], "cashbook") for c in rows), ZERO), rows, ""

    def check_internal(self):
        """C04 requirement, C05 resource, C06 difference (RC1), per day and currency."""
        run04, run05, run06 = self.gate("C04-REQUIREMENT"), self.gate("C05-RESOURCE"), self.gate("C06-DIFFERENCE")
        if not (run04 or run05):
            return
        snaps = defaultdict(list)
        for r in self.rows("IN-03"):
            snaps[(date.fromisoformat(r["recon_date"]), r["currency"])].append(r)
        acct_of_ccy = {self.ccy_of[a]: a for a in self.sga}
        for run in self.rows("IN-05"):
            d, ccy = date.fromisoformat(run["recon_date"]), run["currency"]
            scope = f"{d}/{ccy}"
            ev = [self.ref("IN-05", run)]
            pt = self.point(d)
            # C04 requirement
            req, res, roots = None, None, []
            if run04:
                s = snaps.get((d, ccy), [])
                t = self.tainted("IN-03", currency=ccy, d=d) or self.tainted("IN-04", currency=ccy, on_or_before=d)
                if t or not s:
                    roots.append(t or f"MISSING_SNAPSHOT|{ccy}|{d}")
                    self.add("C04-REQUIREMENT", "C04", scope, INSUF, reported=run["requirement_reported"], evidence=ev,
                             note="an invalid client-snapshot or unallocated-register row affects this scope" if t else "client snapshots not provided",
                             root=roots[-1])
                else:
                    open_u = [u for u in self.rows("IN-04") if u["currency"] == ccy and parse_ts(u["receipt_ts"]) <= pt
                              and (u["allocated_ts"] == "" or parse_ts(u["allocated_ts"]) > pt)]
                    req = sum((max(ZERO, parse_signed(r["balance"])) for r in s), ZERO) + \
                        sum((parse_unsigned(u["amount"]) for u in open_u), ZERO)
                    rep = parse_signed(run["requirement_reported"])
                    self.add("C04-REQUIREMENT", "C04", scope, PASS if req == rep else FAIL, str(req), str(rep),
                             ev + [f"{self.ref('IN-03')}#L{s[0]['_line']}-L{s[-1]['_line']}"] + [self.ref("IN-04", u) for u in open_u],
                             f"sum of {len(s)} non-negative client balances + {len(open_u)} open unallocated receipt(s)")
            # C05 resource
            if run05:
                acct = acct_of_ccy.get(ccy)
                item_a, used, t = self.ledger_at(acct, pt) if acct else (None, [], "")
                b_d = sum((parse_signed(run[k]) for k in ("item_b", "item_c", "item_d")), ZERO)
                if item_a is None:
                    roots.append(t or f"MISSING_FILE|IN-10")
                    self.add("C05-RESOURCE", "C05", scope, INSUF, reported=run["resource_reported"], evidence=ev,
                             note="an invalid cash-book row affects this balance" if t else
                             "cash book (IN-10) not provided or has no opening balance: item A cannot be recomputed", root=roots[-1])
                else:
                    res = item_a + b_d
                    ok = item_a == parse_signed(run["item_a"]) and res == parse_signed(run["resource_reported"])
                    self.add("C05-RESOURCE", "C05", scope, PASS if ok else FAIL, f"item A {item_a}; resource {res}",
                             f"item A {run['item_a']}; resource {run['resource_reported']}",
                             ev + [f"{self.ref('IN-10')} ({len(used)} entries to {pt:%H:%M})"],
                             "item A recomputed from cash book; items B-D taken as reported (0.00), not independently verified",
                             structured={"item_a": str(item_a), "items_b_to_d": str(b_d), "resource": str(res),
                                         "item_a_reported": run["item_a"], "resource_reported": run["resource_reported"]})
            # C06 difference
            if not run06:
                continue
            if req is None or res is None:
                self.add("C06-DIFFERENCE", "C06", scope, INSUF, reported=run["difference_reported"], evidence=ev, root=roots[0] if roots else "")
            else:
                diff, rep = res - req, parse_signed(run["difference_reported"])
                if diff != rep:
                    self.add("C06-DIFFERENCE", "C06", scope, FAIL, str(diff), str(rep), ev, "reported difference differs from recomputed")
                elif diff == ZERO:  # approved 17 Nov 2026: a reconciled zero difference is a PASS (was NOT_APPLICABLE)
                    self.add("C06-DIFFERENCE", "C06", scope, self.rules.zero_difference_outcome, str(diff), str(rep), ev, "no difference to resolve")
                else:
                    self.add("C06-DIFFERENCE", "C06", scope, FAIL, str(diff), str(rep), ev, "difference requires same-day resolution (CASS 15.8.50R)")

    def check_external(self):
        """C07 reported bank balance vs bank evidence; RC2 ledger recompute; C08 recomputed difference."""
        run07, run_rc2, run08 = self.gate("C07-BANK-EVIDENCE"), self.gate("RC2-LEDGER"), self.gate("C08-DIFFERENCE")
        if not (run07 or run_rc2 or run08):
            return
        for e in self.rows("IN-06"):
            d, acct = date.fromisoformat(e["recon_date"]), e["account_id"]
            scope, ev = f"{d}/{acct}", [self.ref("IN-06", e)]
            bank, ledger, broot, lroot, b = None, None, "", "", None
            if run07 or run08:
                b = self.bc.get(e["bank_statement_id"])
                if b is None:
                    broot = self.tainted("IN-07", account=acct, d=d) or self.tainted("IN-07", pk=e["bank_statement_id"]) or f"MISSING_BANK_EVIDENCE|{acct}|{d}"
                    if run07:
                        self.add("C07-BANK-EVIDENCE", "C07", scope, INSUF, reported=e["bank_balance_reported"], evidence=ev,
                                 note=(f"cited statement {e['bank_statement_id']} not provided; reported bank balance is unverified"
                                       if broot.startswith("MISSING") else
                                       f"cited statement {e['bank_statement_id']} is in an invalid row; reported bank balance is unverified"),
                                 root=broot)
                else:
                    bank = signed(b["balance_amount"], b["balance_dc_indicator"], "bank")
                    ok = (b["account_id"] == acct and b["currency"] == e["currency"] == self.ccy_of.get(acct)
                          and parse_ts(b["as_at_ts"]).date() == d and bank == parse_signed(e["bank_balance_reported"]))
                    if run07:
                        self.add("C07-BANK-EVIDENCE", "C07", scope, PASS if ok else FAIL, str(bank), e["bank_balance_reported"],
                                 ev + [self.ref("IN-07", b)])
            if run_rc2 or run08:
                ledger, used, lroot = self.ledger_at(acct, self.point(d))
                if run_rc2:
                    if ledger is None:
                        self.add("RC2-LEDGER", "C07", scope, INSUF, reported=e["ledger_balance_reported"], evidence=ev,
                                 note="an invalid cash-book row affects this balance" if lroot else "cash book not available",
                                 root=lroot or "MISSING_FILE|IN-10")
                    else:
                        self.add("RC2-LEDGER", "C07", scope, PASS if ledger == parse_signed(e["ledger_balance_reported"]) else FAIL,
                                 str(ledger), e["ledger_balance_reported"], ev + [f"{self.ref('IN-10')} ({len(used)} entries)"])
            if not run08:
                continue
            if bank is None or ledger is None:
                self.add("C08-DIFFERENCE", "C08", scope, INSUF, reported=e["difference_reported"], evidence=ev,
                         note="bank evidence not provided; difference not computed" if bank is None else "cash book not available",
                         root=broot if bank is None else (lroot or "MISSING_FILE|IN-10"))
                continue
            diff, rep = bank - ledger, parse_signed(e["difference_reported"])
            if diff != rep:
                status, detail, trefs = self.timing_assessment(acct, d, diff) if diff != ZERO else ("", "", [])
                self.add("C08-DIFFERENCE", "C08", scope, FAIL, str(diff), str(rep), ev + trefs,
                         "reported difference differs from recomputed" + (f"; {detail}" if detail else ""), evidence_status=status,
                         structured=self.timing_structured(acct, d, diff) if diff != ZERO else None)
            elif diff == ZERO:  # approved 17 Nov 2026: a reconciled zero difference is a PASS (was NOT_APPLICABLE)
                self.add("C08-DIFFERENCE", "C08", scope, self.rules.zero_difference_outcome, str(diff), str(rep), ev + [self.ref("IN-07", b)], "bank equals ledger")
            else:
                status, detail, trefs = self.timing_assessment(acct, d, diff)
                if status in ("TIMING_EVIDENCED", "TIMING_PARTIAL"):
                    note = f"bank-ledger difference; {detail}"
                else:
                    note = "unexplained bank-ledger difference" + (" (timing claimed, not evidenced)" if e["timing_difference_claimed"] == "true" else "")
                    if detail:
                        note += f"; {detail}"
                self.add("C08-DIFFERENCE", "C08", scope, FAIL, str(diff), str(rep), ev + [self.ref("IN-07", b)] + trefs, note,
                         evidence_status=status, structured=self.timing_structured(acct, d, diff))

    def check_settlement(self):
        """C11 (D04/D05): batch arithmetic, line<->transaction links, batch -> bank entry by reference."""
        lines = defaultdict(list)
        for ln in self.rows("IN-13"):
            lines[ln["batch_id"]].append(ln)
        batch_ids = {b["batch_id"] for b in self.rows("IN-12")}
        bank_by_ref = defaultdict(list)
        for e in self.rows("IN-09"):
            bank_by_ref[(e["account_id"], e["bank_reference"])].append(e)
        run_arith, run_bank = self.gate("C11-BATCH-ARITH"), self.gate("C11-BATCH-BANK")
        for b in self.rows("IN-12"):
            ls, issues = lines.get(b["batch_id"], []), []
            net_signed = batch_net_signed(b["net_amount_reported"], b["direction"])
            if run_arith:
                t = self.tainted("IN-13", batch=b["batch_id"]) or self.tainted("IN-11", batch=b["batch_id"])
                if t:
                    self.add("C11-BATCH-ARITH", "C11", b["batch_id"], INSUF, evidence=[self.ref("IN-12", b)],
                             note="an invalid line or transaction row may belong to this batch; arithmetic not assessed", root=t)
                else:
                    tot = lambda t: sum((parse_unsigned(x["amount"]) for x in ls if x["line_type"] == t), ZERO)
                    if tot("TXN") != parse_unsigned(b["gross_amount"]):
                        issues.append(f"TXN lines {tot('TXN')} != gross {b['gross_amount']}")
                    if tot("FEE") != parse_unsigned(b["total_fees"]):
                        issues.append(f"FEE lines {tot('FEE')} != fees {b['total_fees']}")
                    if tot("REFUND") != parse_unsigned(b["total_adjustments"]):
                        issues.append(f"REFUND lines {tot('REFUND')} != adjustments {b['total_adjustments']}")
                    line_sum = sum((signed(x["amount"], x["dc_indicator"], "settlement") for x in ls), ZERO)
                    if line_sum != net_signed:
                        issues.append(f"signed lines {line_sum} != signed net {net_signed}")
                    for x in ls:
                        if x["currency"] != b["currency"]:
                            issues.append(f"{x['line_id']} currency {x['currency']}")
                        if x["line_type"] in ("TXN", "REFUND"):
                            tx = self.txn.get(x["txn_id"])
                            if tx is None or tx["settlement_batch_id"] != b["batch_id"] or tx["amount"] != x["amount"]:
                                issues.append(f"{x['line_id']} does not match transaction {x['txn_id']}")
                    self.add("C11-BATCH-ARITH", "C11", b["batch_id"], FAIL if issues else PASS, str(line_sum), str(net_signed),
                             [self.ref("IN-12", b)] + [f"{self.ref('IN-13')}#L{ls[0]['_line']}-L{ls[-1]['_line']}"] if ls else [self.ref("IN-12", b)],
                             "; ".join(issues))
            if not run_bank:
                continue
            hits = bank_by_ref.get((b["account_id"], b["expected_bank_reference"]), [])
            sdate = date.fromisoformat(b["settlement_date"])
            if len(hits) == 1:
                e = hits[0]
                ok = signed(e["amount"], e["dc_indicator"], "bank") == net_signed and e["currency"] == b["currency"]
                note = "matched by reference, then amount compared"
                booked = date.fromisoformat(e["booking_date"])
                lag, cursor = 0, sdate
                while cursor < booked:
                    cursor, lag = business_day_after(cursor), lag + 1
                if booked != sdate:  # D-E1b: informational only; the outcome is not affected
                    note += (f"; booked {booked}, {lag} business day(s) after the settlement date "
                             f"({'within' if lag <= 1 else 'outside'} the one-business-day allowance; informational)")
                self.add("C11-BATCH-BANK", "C11", b["batch_id"], PASS if ok else FAIL, str(net_signed),
                         str(signed(e["amount"], e["dc_indicator"], "bank")), [self.ref("IN-12", b), self.ref("IN-09", e)], note,
                         structured={"bank_entry_id": e["bank_entry_id"], "settlement_date": b["settlement_date"],
                                     "booking_date": e["booking_date"], "booking_lag_business_days": lag,
                                     "within_one_business_day_allowance": lag <= 1, "timing_status": "INFORMATIONAL"})
            elif not hits:
                gap = self.evidence_gap(b["account_id"], sdate) or self.tainted("IN-09", account=b["account_id"], ref=b["expected_bank_reference"])
                self.add("C11-BATCH-BANK", "C11", b["batch_id"], INSUF if gap else FAIL, evidence=[self.ref("IN-12", b)],
                         note=("bank statement for settlement date not provided" if gap.startswith("MISSING") else
                               "bank evidence for that day includes an excluded row (invalid or out of period)") if gap else "no bank entry carries the batch reference",
                         root=gap or "")
            else:
                self.add("C11-BATCH-BANK", "C11", b["batch_id"], FAIL, evidence=[self.ref("IN-12", b)] + [self.ref("IN-09", e) for e in hits],
                         note="batch reference on more than one bank entry")
        if not self.gate("C11-TXN-LINE"):
            return
        failed = False
        for t in self.rows("IN-11"):
            if t["txn_type"] in ("LOAD_CARD", "SPEND", "REFUND"):
                found = [x for x in lines.get(t["settlement_batch_id"], []) if x["txn_id"] == t["txn_id"]]
                if t["settlement_batch_id"] not in batch_ids or len(found) != 1:
                    failed = True
                    tr = (self.tainted("IN-12", pk=t["settlement_batch_id"]) if t["settlement_batch_id"] not in batch_ids
                          else self.tainted("IN-13", batch=t["settlement_batch_id"]))
                    self.add("C11-TXN-LINE", "C11", t["txn_id"], INSUF if tr else FAIL, evidence=[self.ref("IN-11", t)],
                             note="an invalid batch or line row may hold this transaction" if tr else "transaction not in exactly one line of its batch",
                             root=tr or "")
        if not failed:  # summary only when nothing failed (no duplicates)
            self.add("C11-TXN-LINE", "C11", "all card transactions", PASS,
                     str(sum(1 for t in self.rows("IN-11") if t["txn_type"] in ("LOAD_CARD", "SPEND", "REFUND"))), evidence=[self.ref("IN-11")],
                     note="each card transaction appears in exactly one line of its batch")

    def check_topups(self):
        """Funding evidence: each acquirer fee deduction is topped up from own funds the same day."""
        if not self.gate("FUND-TOPUP"):
            return
        by_ref = defaultdict(list)
        for e in self.rows("IN-09"):
            by_ref[e["bank_reference"]].append(e)
        cash_refs = {c["payment_reference"]: c for c in self.rows("IN-10") if c["entry_type"] == "OWN_FUNDS_TOPUP"}
        for b in self.rows("IN-12"):
            fees = parse_unsigned(b["total_fees"])
            if fees == ZERO:
                continue
            ccy, ymd = b["currency"], b["settlement_date"].replace("-", "")
            ref = f"TOPUP-{ccy}-{ymd}"
            sga = [e for e in by_ref.get(ref, []) if e["account_id"] == b["account_id"] and e["dc_indicator"] == "C"]
            own = [e for e in by_ref.get(ref, []) if self.accounts.get(e["account_id"], {}).get("account_class") == "OWN_FUNDS" and e["dc_indicator"] == "D"]
            cash = cash_refs.get(ref)
            sdate = date.fromisoformat(b["settlement_date"])
            own_acct = next((a for a, r in self.accounts.items() if r["account_class"] == "OWN_FUNDS" and r["currency"] == ccy), None)
            gaps = [g for g in ((self.evidence_gap(a, sdate) if (not sga if a == b["account_id"] else not own) else None)
                                for a in (b["account_id"], own_acct) if a) if g]
            if not cash:
                t = self.tainted("IN-10", ref=ref)
                if t:
                    gaps.append(t)
            if gaps:
                self.add("FUND-TOPUP", "C06", b["batch_id"], INSUF, str(fees), evidence=[self.ref("IN-12", b)],
                         note=(f"bank statement for {gaps[0].split('|')[1]} on {sdate} not provided" if gaps[0].startswith("MISSING")
                               else "a required top-up record is in an invalid row"), root=gaps[0])
                continue
            ok = (len(sga) == 1 and len(own) == 1 and cash is not None and parse_unsigned(sga[0]["amount"]) == fees
                  and parse_unsigned(own[0]["amount"]) == fees and parse_unsigned(cash["amount"]) == fees
                  and sga[0]["booking_date"] == b["settlement_date"])
            ev = [self.ref("IN-12", b)] + [self.ref("IN-09", e) for e in sga + own] + ([self.ref("IN-10", cash)] if cash else [])
            self.add("FUND-TOPUP", "C06", b["batch_id"], PASS if ok else FAIL, str(fees), evidence=ev,
                     note="fees topped up: safeguarding credit, own-funds debit and cash-book entry all carry the same reference")

    def check_direct_and_allocation(self):
        """RC4 1:1 loads/redemptions by end-to-end reference; C09 allocation timeliness (CASS 15.2.5R)."""
        e2e = defaultdict(list)
        for e in self.rows("IN-09"):
            if e["end_to_end_ref"] and e["account_id"] in self.sga:
                e2e[e["end_to_end_ref"]].append(e)
        prior_refs = {u["bank_reference"]: [self.ref("IN-04", u)] for u in self.rows("IN-04")
                      if date.fromisoformat(u["receipt_date"]) < self.period.start}
        if self.gate("RC4-DIRECT"):
            for t in self.rows("IN-11"):
                if t["txn_type"] not in ("LOAD_BANK", "REDEMPTION"):
                    continue
                hits = e2e.get(t["payment_reference"], [])
                want = "C" if t["txn_type"] == "LOAD_BANK" else "D"
                if len(hits) == 1:
                    e = hits[0]
                    ok = e["amount"] == t["amount"] and e["currency"] == t["currency"] and e["dc_indicator"] == want
                    self.add("RC4-DIRECT", "C09", t["txn_id"], PASS if ok else FAIL, t["amount"], e["amount"],
                             [self.ref("IN-11", t), self.ref("IN-09", e)], "linked by end-to-end reference")
                elif hits:
                    self.add("RC4-DIRECT", "C09", t["txn_id"], FAIL, evidence=[self.ref("IN-11", t)] + [self.ref("IN-09", e) for e in hits],
                             note="reference matches more than one bank entry")
                elif t["payment_reference"] in prior_refs:
                    self.add("RC4-DIRECT", "C09", t["txn_id"], NA, evidence=[self.ref("IN-11", t)] + prior_refs[t["payment_reference"]],
                             note="allocation of a receipt received before the period start: its bank credit is outside the "
                                  f"{self.period.month_name} evidence (convention P1), so the 1:1 link is not assessed for this period")
                else:
                    acct = next((a for a in self.sga if self.ccy_of[a] == t["currency"]), None)
                    dates = {parse_ts(t["executed_ts"]).date()} | {date.fromisoformat(u["receipt_date"]) for u in self.rows("IN-04")
                                                                  if u["bank_reference"] == t["payment_reference"]}
                    gaps = [g for g in (self.evidence_gap(acct, d) for d in sorted(dates) if acct) if g]
                    if not gaps:
                        t9 = self.tainted("IN-09", ref=t["payment_reference"])
                        if t9:
                            gaps.append(t9)
                    self.add("RC4-DIRECT", "C09", t["txn_id"], INSUF if gaps else FAIL, evidence=[self.ref("IN-11", t)],
                             note=("bank statement for that day not provided" if gaps[0].startswith("MISSING") else
                                   "bank evidence includes an excluded row (invalid or out of period)") if gaps else "no bank entry with this end-to-end reference",
                             root=gaps[0] if gaps else "")
        if not self.gate("C09-ALLOCATION"):
            return
        for u in self.rows("IN-04"):
            hits = e2e.get(u["bank_reference"], [])
            issues, ev = [], [self.ref("IN-04", u)] + [self.ref("IN-09", e) for e in hits]
            insuf, conventions = "", []
            if not hits and date.fromisoformat(u["receipt_date"]) < self.period.start:
                conventions.append(f"received before the period start: the bank credit is outside the {self.period.month_name} evidence "
                                   "and is not matched (convention P1)")
            elif len(hits) != 1 or hits[0]["amount"] != u["amount"] or hits[0]["currency"] != u["currency"]:
                if not hits:
                    acct = next((a for a in self.sga if self.ccy_of.get(a) == u["currency"]), None)
                    insuf = (self.evidence_gap(acct, date.fromisoformat(u["receipt_date"])) if acct else "") or \
                        self.tainted("IN-09", ref=u["bank_reference"]) or ""
                issues.append("receipt does not match exactly one bank credit")
            if u["allocated_ts"]:
                deadline = business_day_after(date.fromisoformat(u["receipt_date"]))
                if parse_ts(u["allocated_ts"]).date() > deadline:
                    issues.append(f"allocated after {deadline}")
                if parse_ts(u["allocated_ts"]).astimezone(LON).date() > self.period.end:
                    conventions.append(f"allocated after the period end ({u['allocated_date']}): a subsequent event; timeliness is "
                                       "assessed from the register and the allocating transaction is not required (convention P1)")
                else:
                    # Approved 17 Nov 2026: the allocating LOAD_BANK transaction is matched by payment_reference (the primary
                    # key) and must be for the same client. Its execution time need not equal the register's allocated_ts:
                    # timing is assessed separately (the allocation deadline above, from allocated_ts).
                    # Matching is exact and case-sensitive (no normalisation); strip() only decides whether a reference is
                    # present at all (a whitespace-only reference is no payment reference).
                    ref = u["bank_reference"]
                    present = bool((ref or "").strip())
                    alloc = [t for t in self.rows("IN-11") if t["txn_type"] == "LOAD_BANK" and t["payment_reference"] == ref] if present else []
                    if not present:
                        issues.append("allocation transaction missing or inconsistent: the receipt has no payment reference")
                    elif not alloc:
                        issues.append("allocation transaction missing or inconsistent: no bank-load transaction carries the payment reference")
                        insuf = insuf or self.tainted("IN-11", ref=ref) or ""
                    elif len(alloc) > 1:
                        issues.append(f"allocation transaction missing or inconsistent: {len(alloc)} bank-load transactions carry the "
                                      "payment reference (ambiguous)")
                    elif alloc[0]["client_id"] != u["client_id"]:
                        issues.append(f"allocation transaction missing or inconsistent: the transaction is for client "
                                      f"{alloc[0]['client_id']}, the register allocates to {u['client_id']}")
                    if len(alloc) == 1:
                        # A single visible match is unambiguous only if no EXCLUDED IN-11 row could carry the same reference
                        # (a duplicate hidden by a data-quality exclusion): otherwise the evidence is insufficient, never PASS.
                        hidden = self.tainted("IN-11", ref=ref)
                        if hidden:
                            issues.append("allocation transaction possibly ambiguous: an excluded bank-load row may carry the "
                                          "same payment reference")
                            insuf = insuf or hidden
                    ev += [self.ref("IN-11", t) for t in alloc]
            if issues and insuf:
                self.add("C09-ALLOCATION", "C09", u["receipt_id"], INSUF, evidence=ev,
                         note="; ".join(issues + conventions) + " (evidence missing or invalid)", root=insuf)
                continue
            base = "allocated by the next business day (CASS 15.2.5R)"
            if not u["allocated_ts"]:
                due = business_day_after(date.fromisoformat(u["receipt_date"]))
                if due <= self.period.end:
                    issues.append(f"not allocated; allocation was due by {due}")
                else:
                    base = f"open at the period end; allocation due by {due}, after the period"
            note = "; ".join(issues + conventions) if issues else "; ".join([base] + conventions)
            self.add("C09-ALLOCATION", "C09", u["receipt_id"], FAIL if issues else PASS, evidence=ev, note=note)

    def check_unmatched_bank_entries(self):
        """Every safeguarding bank entry is explained by a batch, a direct transaction, a top-up or the unallocated register."""
        if not self.gate("C11-BANK-ENTRY"):
            return
        batch_refs = {(b["account_id"], b["expected_bank_reference"]) for b in self.rows("IN-12")}
        txn_refs = {t["payment_reference"] for t in self.rows("IN-11") if t["payment_reference"]}
        unalloc = {u["bank_reference"] for u in self.rows("IN-04")}
        topups = {c["payment_reference"] for c in self.rows("IN-10") if c["entry_type"] == "OWN_FUNDS_TOPUP"}
        unexplained = []
        for e in self.rows("IN-09"):
            if e["account_id"] not in self.sga:
                continue
            if not ((e["account_id"], e["bank_reference"]) in batch_refs or e["end_to_end_ref"] in txn_refs
                    or e["end_to_end_ref"] in unalloc or e["bank_reference"] in topups):
                unexplained.append(e)
                refs = {e["bank_reference"], e["end_to_end_ref"]} - {""}
                t = next((x for x in (self.tainted(fid, ref=r) for fid in ("IN-12", "IN-11", "IN-04", "IN-10") for r in refs) if x), None)
                self.add("C11-BANK-ENTRY", "C11", e["bank_entry_id"], INSUF if t else FAIL, evidence=[self.ref("IN-09", e)],
                         note="an excluded row (invalid or out of period) may be its counterpart" if t else "bank entry with no batch, transaction, top-up or register counterpart",
                         root=t or f"UNMATCHED_BANK_ENTRY|{e['bank_entry_id']}")
        if not unexplained:  # summary only when nothing failed (no duplicates)
            n = sum(1 for e in self.rows("IN-09") if e["account_id"] in self.sga)
            self.add("C11-BANK-ENTRY", "C11", "all safeguarding bank entries", PASS, f"{n} of {n} explained", evidence=[self.ref("IN-09")])

    def check_refunds(self):
        """C12 (D07): refunds reference an existing original in the same currency and client; total <= original."""
        if not self.gate("C12-REFUND"):
            return
        totals = defaultdict(Decimal)
        for t in self.rows("IN-11"):
            if t["txn_type"] != "REFUND":
                continue
            o = self.txn.get(t["original_txn_id"])
            if o is None or o["currency"] != t["currency"] or o["client_id"] != t["client_id"]:
                tr = self.tainted("IN-11", pk=t["original_txn_id"]) if o is None else None
                self.add("C12-REFUND", "C12", t["txn_id"], INSUF if tr else FAIL, evidence=[self.ref("IN-11", t)],
                         note="original is in an invalid row" if tr else "original missing or inconsistent", root=tr or "")
                continue
            totals[o["txn_id"]] += parse_unsigned(t["amount"])
            ok = totals[o["txn_id"]] <= parse_unsigned(o["amount"])
            self.add("C12-REFUND", "C12", t["txn_id"], PASS if ok else FAIL, str(totals[o["txn_id"]]), o["amount"],
                     [self.ref("IN-11", t), self.ref("IN-11", o)], "cumulative refunds vs original")

    def check_client_rollforward(self):
        """Client snapshots roll forward by transactions executed between reconciliation points."""
        if self.gate("CBAL-NONNEG"):
            neg = [r for r in self.rows("IN-03") if parse_signed(r["balance"]) < ZERO]
            self.add("CBAL-NONNEG", "C04", "all snapshots", FAIL if neg else PASS, f"{len(neg)} negative",
                     evidence=[self.ref("IN-03", r) for r in neg[:5]] or [self.ref("IN-03")], note="baseline invariant: client balances non-negative")
        if not self.gate("CBAL-ROLLFWD"):
            return
        snaps = defaultdict(dict)
        for r in self.rows("IN-03"):
            snaps[(r["currency"], r["client_id"])][date.fromisoformat(r["recon_date"])] = r
        moves = defaultdict(list)
        for t in self.rows("IN-11"):
            moves[(t["currency"], t["client_id"])].append((parse_ts(t["executed_ts"]), signed(t["amount"], t["direction"], "client"), t))
        for key, by_day in snaps.items():
            days = sorted(by_day)  # the first in-period snapshot is the starting point (not assessed; listed in the report)
            for prev, cur in zip(days, days[1:]):
                lo, hi = self.point(prev), self.point(cur)
                tr = (self.tainted("IN-03", currency=key[0], client=key[1], d=cur) or self.tainted("IN-03", currency=key[0], client=key[1], d=prev)
                      or next((r for r in (self.tainted("IN-11", client=key[1], currency=key[0], d=x) for x in
                                            {(lo + timedelta(days=i)).date() for i in range((hi.date() - lo.date()).days + 1)}) if r), None))
                if tr:
                    self.add("CBAL-ROLLFWD", "C04", f"{key[0]}/{key[1]} {cur}", INSUF, evidence=[self.ref("IN-03", by_day[prev]), self.ref("IN-03", by_day[cur])],
                             note="an invalid snapshot or transaction row affects this period", root=tr)
                    continue
                mv = [m for m in moves[key] if lo < m[0] <= hi]
                expected = parse_signed(by_day[prev]["balance"]) + sum((m[1] for m in mv), ZERO)
                got = parse_signed(by_day[cur]["balance"])
                self.add("CBAL-ROLLFWD", "C04", f"{key[0]}/{key[1]} {cur}", PASS if expected == got else FAIL, str(expected), str(got),
                         [self.ref("IN-03", by_day[prev]), self.ref("IN-03", by_day[cur])] + [self.ref("IN-11", m[2]) for m in mv],
                         f"previous balance + {len(mv)} transaction(s)")

    def check_currency_isolation(self):
        """C13: each record's currency equals its account's or batch's currency; no computation spans currencies."""
        if not self.gate("C13-CURRENCY"):
            return
        batch_ccy = {b["batch_id"]: b["currency"] for b in self.rows("IN-12")}
        bad = []
        for fid in ("IN-06", "IN-07", "IN-08", "IN-09", "IN-10", "IN-12"):
            bad += [(fid, r) for r in self.rows(fid) if r["currency"] != self.ccy_of.get(r["account_id"])]
        unknown = []  # records whose batch is in an excluded (invalid) row: currency cannot be compared
        for fid, r, b in [("IN-13", r, r["batch_id"]) for r in self.rows("IN-13")] + \
                [("IN-11", t, t["settlement_batch_id"]) for t in self.rows("IN-11") if t["settlement_batch_id"]]:
            if b not in batch_ccy and self.tainted("IN-12", pk=b):
                unknown.append((fid, r, self.tainted("IN-12", pk=b)))
            elif r["currency"] != batch_ccy.get(b):
                bad.append((fid, r))
        if bad:
            self.add("C13-CURRENCY", "C13", "all records", FAIL, f"{len(bad)} mismatches", evidence=[self.ref(f, r) for f, r in bad[:10]],
                     note="every comparison in this validator is keyed by currency; no FX conversion exists")
        elif unknown:
            self.add("C13-CURRENCY", "C13", "all records", INSUF, f"{len(unknown)} not comparable",
                     evidence=[self.ref(f, r) for f, r, _ in unknown[:10]], root=unknown[0][2],
                     note="records whose settlement batch is in an invalid row cannot be checked")
        else:
            self.add("C13-CURRENCY", "C13", "all records", PASS, "0 mismatches", evidence=["all CSV inputs"],
                     note="every comparison in this validator is keyed by currency; no FX conversion exists")

    def check_designation(self):
        """C10: each safeguarding account has an acknowledgement letter whose details match the inventory."""
        if not self.gate("C10-DESIGNATION"):
            return
        for acct in self.sga:
            fid, inv = schema.LETTER_SLOTS.get(acct), self.accounts[acct]
            if fid is None or fid not in self.pdf:
                st = self.state.get(fid, ("MISSING", f"MISSING_FILE|{fid}")) if fid else ("MISSING", "")
                self.add("C10-DESIGNATION", "C10", acct, FAIL, evidence=[self.ref("IN-02", inv)],
                         note="acknowledgement letter not provided" if st[0] == "MISSING" else f"acknowledgement letter {st[0].lower()}",
                         root=st[1])
                continue
            p = self.pdf[fid]
            ok = (p.get("Letter reference") == inv["acknowledgement_letter_ref"] and p.get("Account number") == inv["account_number_masked"]
                  and p.get("Currency") == inv["currency"] and p.get("Account name") == inv["designation_name"]
                  and "Safeguarding" in inv["designation_name"])
            note = "deterministic parse of synthetic key details; reviewer confirmation not modelled in milestone 1"
            issued = _date_or_none(p.get("Letter date", ""))
            if issued is not None and issued > self.period.end:  # a letter issued after the period does not evidence it
                ok = False
                note += f"; letter dated {issued}, after the period end {self.period.end}"
            self.add("C10-DESIGNATION", "C10", acct, PASS if ok else FAIL, p.get("Letter reference", ""), inv["acknowledgement_letter_ref"],
                     [self.ref("IN-02", inv), self.ref(fid)], note)

    def check_discrepancy_log(self):
        """The log is evaluated per difference in group_exceptions(); here only its availability."""
        self.gate("DISC-LOG")

    def check_checklist(self):
        """C16: governance and monthly return (optional supporting evidence)."""
        if "IN-18" in self.pdf:
            ok = bool(self.pdf["IN-18"].get("Accountable person"))
            since = _date_or_none(self.pdf["IN-18"].get("Allocated from", ""))
            if since is not None and since > self.period.end:  # responsibility allocated only after this period
                self.add("C16-GOVERNANCE", "C16", "period", FAIL, self.pdf["IN-18"].get("Accountable person", ""), evidence=[self.ref("IN-18")],
                         note=f"responsibility allocated from {since}, after the period end {self.period.end}")
            else:
                self.add("C16-GOVERNANCE", "C16", "period", PASS if ok else FAIL, self.pdf["IN-18"].get("Accountable person", ""), evidence=[self.ref("IN-18")])
        else:
            self.add("C16-GOVERNANCE", "C16", "period", NA, note="optional evidence not provided" if self.state.get("IN-18", ("MISSING",))[0] == "MISSING"
                     else "optional evidence not usable")
        if "IN-19" in self.pdf:
            p = self.pdf["IN-19"]
            due = business_day_after(self.period.previous_end, 15)  # the receipt is for the previous month's return
            try:
                submitted = parse_ts(p.get("Submitted at", "")).date()
            except ValueError:
                self.add("C16-RETURN", "C16", p.get("Period", ""), FAIL, evidence=[self.ref("IN-19")], note="submission timestamp not readable")
                return
            right_period = p.get("Period", "") == self.period.previous.token
            self.add("C16-RETURN", "C16", p.get("Period", ""),
                     PASS if right_period and submitted <= due and p.get("Due date") == due.isoformat() else FAIL,
                     f"due {due} (15 business days, SUP 16.14A.3R)", f"submitted {submitted}; stated due {p.get('Due date')}", [self.ref("IN-19")],
                     "" if right_period else f"receipt is for {p.get('Period') or 'an unstated period'}; the return due in this period is "
                                             f"for {self.period.previous.token}")
        else:
            self.add("C16-RETURN", "C16", "period", NA, note="optional evidence not provided" if self.state.get("IN-19", ("MISSING",))[0] == "MISSING"
                     else "optional evidence not usable")


SEVERITY = {"MISSING_BANK_EVIDENCE": "Critical", "BANK_LEDGER_DIFFERENCE": "Critical", "INTERNAL_DIFFERENCE": "Critical",
            "MISSING_RECON": "Critical", "MISSING_EXT_RECON": "Critical", "MISSING_FILE": "Critical", "EMPTY_FILE": "Critical",
            "INVALID_FILE": "Critical", "AMBIGUOUS_FILE": "Critical", "INVALID_ROWS": "High",
            "WRONG_PERIOD": "Critical", "OUT_OF_PERIOD_ROWS": "High"}
CATEGORY = {"MISSING_BANK_EVIDENCE": "Missing bank evidence", "BANK_LEDGER_DIFFERENCE": "Unexplained bank-ledger difference",
            "INTERNAL_DIFFERENCE": "Internal reconciliation difference", "UNMATCHED_BANK_ENTRY": "Bank entry with no counterpart",
            "UNMATCHED_CASHBOOK_ENTRY": "Cash-book entry with no bank entry", "MISSING_RECON": "Missing internal reconciliation",
            "MISSING_EXT_RECON": "Missing external reconciliation", "MISSING_FILE": "Required file not provided",
            "EMPTY_FILE": "Required file present but empty", "INVALID_FILE": "Required file unusable",
            "AMBIGUOUS_FILE": "Ambiguous evidence file", "INVALID_ROWS": "Invalid rows excluded",
            "MISSING_SNAPSHOT": "Missing client snapshot", "MISSING_BATCH": "Missing settlement batch",
            "WRONG_PERIOD": "File for the wrong reporting period", "OUT_OF_PERIOD_ROWS": "Rows outside the reporting period excluded"}
FILE_ROOTS = {"MISSING_FILE": "not provided", "EMPTY_FILE": "present but empty", "INVALID_FILE": "unusable",
              "AMBIGUOUS_FILE": "ambiguous at intake", "INVALID_ROWS": "has invalid rows",
              "WRONG_PERIOD": "is for the wrong reporting period", "OUT_OF_PERIOD_ROWS": "has rows outside the reporting period"}
RANK = {"Critical": 0, "High": 1}

def _group_exceptions(self):
    """One exception per root cause (decision D4). Every FAIL or INSUFFICIENT_EVIDENCE result belongs to exactly one."""
    # Bank-ledger differences: contiguous reconciliation days, same account, same difference = one root cause.
    c08 = sorted((r for r in self.results if r["check_id"] == "C08-DIFFERENCE" and r["outcome"] == FAIL),
                 key=lambda r: r["scope"])
    groups, prev = [], None
    for r in c08:
        d, acct = r["scope"].split("/")
        d = date.fromisoformat(d)
        if prev and prev[1] == acct and prev[2] == r["computed"] and \
                [x for x in self.recon_days if x > prev[0]][:1] == [d]:
            groups[-1].append(r)
        else:
            groups.append([r])
        prev = (d, acct, r["computed"])
    logged = {x["recon_ref"] for x in self.rows("IN-14")}
    subsequent = {x["recon_ref"] for x in self.rows("IN-14") if x.get("_subsequent")}
    self.diff_groups = []
    for g in groups:
        d0, acct = g[0]["scope"].split("/")
        root = f"BANK_LEDGER_DIFFERENCE|{acct}|{d0}|{g[0]['computed']}"
        erls = [f"ERL-{acct}-{x['scope'].split('/')[0].replace('-', '')}" for x in g]
        for r in g:
            r["root_cause"] = root
        if "IN-14" not in self.state:
            hit = sorted(logged & set(erls))
            late = sorted(subsequent & set(erls))
            excluded = None if hit else next((t for t in (self.tainted("IN-14", ref=e) for e in erls) if t), None)
            if excluded:  # a log entry about this difference exists but was excluded: evidence incomplete, not absent
                self.add("DISC-LOG", "C06/C08", f"{acct} from {d0}", INSUF, f"{len(g)} day(s) with difference", "0 usable log entries",
                         [self.ref("IN-14")] + [r["evidence"].split(";")[0].strip() for r in g],
                         "a discrepancy-log entry referring to this difference was excluded (invalid or out of period)", root=excluded)
                self.diff_groups.append((root, acct, g))
                continue
            note = "investigation logged" if hit else \
                "difference not recorded in the discrepancy log (CASS 15.8.56R investigation evidence absent)"
            if late:
                note += (f"; {len(late)} entr{'y' if len(late) == 1 else 'ies'} recorded after the period end "
                         "(subsequent-recorded, convention P2)")
            self.add("DISC-LOG", "C06/C08", f"{acct} from {d0}", PASS if hit else FAIL, f"{len(g)} day(s) with difference",
                     f"{len(hit)} log entries", [self.ref("IN-14")] + [r["evidence"].split(";")[0].strip() for r in g] +
                     [self.ref("IN-14", x) for x in self.rows("IN-14") if x["recon_ref"] in set(erls)], note, root=root)
        self.diff_groups.append((root, acct, g))
    if not groups and "IN-14" not in self.state:
        self.add("DISC-LOG", "C06/C08", "period", PASS, "0 recomputed differences", f"{len(self.rows('IN-14'))} log entries",
                 [self.ref("IN-14")], "header-only log is consistent with zero differences")
    for r in self.results:  # internal differences: one root cause per currency and day
        if r["check_id"] == "C06-DIFFERENCE" and r["outcome"] == FAIL and not r["root_cause"]:
            r["root_cause"] = f"INTERNAL_DIFFERENCE|{r['scope']}"
    for r in self.results:  # anything left gets its own root cause, so nothing is silently absorbed
        if r["outcome"] in (FAIL, INSUF) and not r["root_cause"]:
            r["root_cause"] = f"{r['check_id']}|{r['scope']}"
    by_root = defaultdict(list)
    for r in self.results:
        if r["outcome"] in (FAIL, INSUF):
            by_root[r["root_cause"]].append(r)
    unmatched = {k.split("|")[1] for k in by_root if k.startswith("UNMATCHED_BANK_ENTRY|")}
    entry = {e["bank_entry_id"]: e for e in self.rows("IN-09")}
    exceptions = []
    for root, rs in by_root.items():
        kind = root.split("|")[0]
        severity = SEVERITY.get(kind, "High")
        parts = root.split("|")
        acct = parts[1] if kind in ("MISSING_BANK_EVIDENCE", "BANK_LEDGER_DIFFERENCE") else ""
        dates = sorted({r["scope"].split("/")[0] for r in rs if re.match(r"^\d{4}-\d{2}-\d{2}/", r["scope"])})
        flags, related, amount = [], [], ""
        if kind == "MISSING_BANK_EVIDENCE":
            dates = [parts[2]]
        if kind == "BANK_LEDGER_DIFFERENCE":
            amount = parts[3]
            if Decimal(amount) < 0:
                flags.append("OWN_FUNDS_REQUIRED (CASS 15.8.57R: ledger shows a greater need than the bank holds)")
            if any(r["check_id"] == "DISC-LOG" for r in rs):
                flags.append("NO_INVESTIGATION_LOGGED")
            if any(r["check_id"] == "DISC-LOG" and r["root_cause"] == root and "subsequent-recorded" in r["note"] for r in self.results):
                flags.append("INVESTIGATION_RECORDED_AFTER_PERIOD_END")
            related = sorted(i for i in unmatched if i in entry and entry[i]["account_id"] == acct and entry[i]["booking_date"] == parts[2])
        if kind in FILE_ROOTS:
            flags.append(f"{parts[1]} {FILE_ROOTS[kind]}: dependent checks were not run on incomplete evidence")
        if kind == "UNMATCHED_BANK_ENTRY" and parts[1] in entry:
            e = entry[parts[1]]
            acct, dates = e["account_id"], [e["booking_date"]]
            amount = str(signed(e["amount"], e["dc_indicator"], "bank"))
        evidence = []
        for r in rs:
            for x in filter(None, (y.strip() for y in r["evidence"].split(";"))):
                if x not in evidence:
                    evidence.append(x)
        exceptions.append({
            "severity": severity, "status": "OPEN", "category": CATEGORY.get(kind, rs[0]["check_id"]), "root_cause": root,
            "account_id": acct, "currency": self.ccy_of.get(acct, ""), "first_date": dates[0] if dates else "",
            "last_date": dates[-1] if dates else "", "amount": amount, "affected_results": len(rs),
            "affected": "; ".join(f"{r['check_id']} {r['scope']} [{r['outcome']}]" for r in rs),
            "flags": "; ".join(flags),
            "related_records": "; ".join(f"{i} (unreconciled entry on the statement where the difference first appears; not linked by amount)" for i in related),
            "evidence": "; ".join(evidence[:40]), "cause_category": ""})
    for x in exceptions:
        c08 = [r for r in by_root[x["root_cause"]] if r["check_id"] == "C08-DIFFERENCE" and r["evidence_status"]]
        statuses = {r["evidence_status"] for r in c08}
        x["evidence_status"] = (statuses.pop() if len(statuses) == 1 else "TIMING_PARTIAL" if "TIMING_EVIDENCED" in statuses
                                else "NOT_EVIDENCED") if statuses else ""
        x["evidence_status_detail"] = "; ".join(sorted({r["note"] for r in c08 if r["evidence_status"].startswith("TIMING_")}))
        x["review_status"] = "AWAITING_HUMAN_REVIEW"
        if x["evidence_status"] == "TIMING_EVIDENCED":  # wording follows the evidence; status stays OPEN
            x["category"] = "Bank-ledger difference (explained by timing evidence, awaiting human confirmation)"
        elif x["evidence_status"] == "TIMING_PARTIAL":
            x["category"] = "Bank-ledger difference (partly explained by timing evidence)"
        x["investigation_group_id"] = ""
    exceptions.sort(key=lambda x: (RANK[x["severity"]], x["first_date"], x["root_cause"]))
    prefix = self.scenario_id()
    for n, x in enumerate(exceptions, 1):
        x["exception_id"] = f"EXC-{prefix}-{n:02d}"
    self.exceptions = exceptions


def _correlate_exceptions(self):
    """E2: deterministic investigation groups above unchanged exceptions.

    Exceptions are linked only through evidence:
      L1 REFERENCE    the exceptions involve records carrying the same batch or payment/bank reference (same account)
      L2 PERSISTENCE  the same internal difference on consecutive reconciliation days (same currency, same value),
                      the rule already used for bank-ledger differences
      L3 LINEAGE      a record that fails one check is a direct input to another failing check for the same account or
                      currency and date: a bank entry inside the 17:00 balance where a bank-ledger difference begins; a
                      client snapshot inside the requirement where an internal difference or requirement failure occurs;
                      the requirement result consumed by the internal difference for the same scope
    Groups never set a cause, change a status, merge exceptions or close anything. Relationships that rest only on
    matching dates and amounts are recorded separately as unverified candidates (D-E2a), never as groups."""
    exc = self.exceptions
    if len(exc) < 2:
        return
    by_root = {x["root_cause"]: x for x in exc}
    rows_of = defaultdict(list)
    for r in self.results:
        if r["outcome"] in (FAIL, INSUF) and r["root_cause"] in by_root:
            rows_of[by_root[r["root_cause"]]["exception_id"]].append(r)
    batches = {b["batch_id"]: b for b in self.rows("IN-12")}
    cash = {c["ledger_entry_id"]: c for c in self.rows("IN-10")}
    entries = {e["bank_entry_id"]: e for e in self.rows("IN-09")}
    by_bank_ref = defaultdict(list)
    for e in self.rows("IN-09"):
        for rf in {e["bank_reference"], e["end_to_end_ref"]} - {""}:
            by_bank_ref[(e["account_id"], rf)].append(e)

    def refs_and_entries(results):
        """(account, reference) keys and bank entries an exception's results involve, from source records only."""
        keys, ents, cites = set(), {}, []
        for r in results:
            if r["check_id"] in ("C11-BATCH-BANK", "C11-BATCH-ARITH") and r["scope"] in batches:
                b = batches[r["scope"]]
                keys.add((b["account_id"], b["expected_bank_reference"]))
                cites.append(self.ref("IN-12", b))
                for e in by_bank_ref.get((b["account_id"], b["expected_bank_reference"]), []):
                    ents[e["bank_entry_id"]] = e
            elif r["check_id"] == "CASH-BANK-LINK" and r["scope"] in cash:
                c = cash[r["scope"]]
                keys.add((c["account_id"], c["payment_reference"]))
                cites.append(self.ref("IN-10", c))
                for e in by_bank_ref.get((c["account_id"], c["payment_reference"]), []):
                    ents[e["bank_entry_id"]] = e
            elif r["check_id"] in ("C11-BANK-ENTRY", "BANK-CASH-LINK") and r["scope"] in entries:
                e = entries[r["scope"]]
                keys |= {(e["account_id"], rf) for rf in {e["bank_reference"], e["end_to_end_ref"]} - {""}}
                ents[e["bank_entry_id"]] = e
                cites.append(self.ref("IN-09", e))
        return keys, ents, cites

    info = {x["exception_id"]: refs_and_entries(rows_of[x["exception_id"]]) for x in exc}
    links = []

    def link(a, b, kind, basis, cites):
        if a != b:
            links.append((min(a, b), max(a, b), kind, basis, cites))

    ids = [x["exception_id"] for x in exc]
    kind_of = {x["exception_id"]: x["root_cause"].split("|")[0] for x in exc}
    # L1 reference
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = info[a][0] & info[b][0]
            if shared:
                acct, rf = sorted(shared)[0]
                link(a, b, "L1 REFERENCE", f"both involve reference {rf} on {acct}", info[a][2][:1] + info[b][2][:1])
    # L2 persistence of internal differences
    internal = sorted(((date.fromisoformat(x["root_cause"].split("|")[1].split("/")[0]), x["root_cause"].split("/")[-1], x["exception_id"])
                       for x in exc if kind_of[x["exception_id"]] == "INTERNAL_DIFFERENCE"))
    value = {x["exception_id"]: next((r["computed"] for r in rows_of[x["exception_id"]] if r["check_id"] == "C06-DIFFERENCE"), None) for x in exc}
    for (d1, c1, a), (d2, c2, b) in zip(internal, internal[1:]):
        nxt = [x for x in self.recon_days if x > d1][:1]
        if c1 == c2 and nxt == [d2] and value[a] == value[b] and value[a] is not None:
            link(a, b, "L2 PERSISTENCE", f"same internal difference {value[a]} on consecutive reconciliation days ({c1})",
                 [rows_of[a][0]["evidence"].split(";")[0], rows_of[b][0]["evidence"].split(";")[0]])
    # L3 lineage
    for x in exc:
        kind, parts = kind_of[x["exception_id"]], x["root_cause"].split("|")
        if kind == "BANK_LEDGER_DIFFERENCE":
            acct, d0 = parts[1], date.fromisoformat(parts[2])
            for y in exc:
                for e in info[y["exception_id"]][1].values():
                    if e["account_id"] == acct and date.fromisoformat(e["booking_date"]) == d0 and parse_ts(e["booking_ts"]) <= self.point(d0):
                        b = self.bc_by.get((acct, d0))
                        link(x["exception_id"], y["exception_id"], "L3 LINEAGE",
                             f"bank entry {e['bank_entry_id']} is inside the {d0} 17:00 balance of {acct}, where the difference begins",
                             [self.ref("IN-09", e)] + ([self.ref("IN-07", b)] if b else []))
        if kind in ("INTERNAL_DIFFERENCE", "C04-REQUIREMENT"):
            d, ccy = parts[1].split("/")
            for y in exc:
                if kind_of[y["exception_id"]] == "CBAL-ROLLFWD":
                    sc = y["root_cause"].split("|")[1]          # "<ccy>/<client> <date>"
                    yccy, rest = sc.split("/")
                    client, yd = rest.split(" ")
                    if yccy == ccy and yd == d:
                        snap = next((r for r in self.rows("IN-03") if r["recon_date"] == d and r["currency"] == ccy and r["client_id"] == client), None)
                        link(x["exception_id"], y["exception_id"], "L3 LINEAGE",
                             f"snapshot of {client} on {d} fails the roll-forward and is an input to the {ccy} requirement on {d}",
                             [self.ref("IN-03", snap)] if snap else [])
            if kind == "INTERNAL_DIFFERENCE":
                for y in exc:
                    if y["root_cause"] == f"C04-REQUIREMENT|{d}/{ccy}":
                        link(x["exception_id"], y["exception_id"], "L3 LINEAGE",
                             f"the internal difference for {d}/{ccy} uses the recomputed requirement for the same scope",
                             [rows_of[y["exception_id"]][0]["evidence"].split(";")[0]])
    # connected components (deterministic)
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b, *_ in links:
        parent[find(a)] = find(b)
    members = defaultdict(list)
    for i in ids:
        members[find(i)].append(i)
    prefix = self.scenario_id()
    order = {i: n for n, i in enumerate(ids)}
    comps = sorted((m for m in members.values() if len(m) > 1), key=lambda m: min(order[i] for i in m))
    uniq = sorted(set((a, b, k, basis, tuple(c)) for a, b, k, basis, c in links), key=lambda t: (order[t[0]], order[t[1]], t[2], t[3]))
    for n, m in enumerate(comps, 1):
        gid = f"GRP-{prefix}-{n:02d}"
        m = sorted(m, key=lambda i: order[i])
        for x in exc:
            if x["exception_id"] in m:
                x["investigation_group_id"] = gid
        glinks = [t for t in uniq if t[0] in m]
        self.groups.append({
            "group_id": gid, "exception_ids": "; ".join(m), "primary_exception_id": m[0], "size": len(m),
            "link_types": "; ".join(sorted({t[2] for t in glinks})),
            "links": " | ".join(f"{a}—{b} {k}: {basis} [{', '.join(c)}]" for a, b, k, basis, c in glinks),
            "status": "OPEN", "review_status": "AWAITING_HUMAN_REVIEW", "cause": "", "correlation_version": "deterministic-v1"})
    # D-E2a: unverified candidates (dates and amounts only), never grouped
    txn_ids = {t["txn_id"] for t in self.rows("IN-11")}
    lines = defaultdict(list)
    for ln in self.rows("IN-13"):
        lines[ln["batch_id"]].append(ln)
    for x in exc:
        if kind_of[x["exception_id"]] != "C11-BATCH-ARITH":
            continue
        b = batches.get(x["root_cause"].split("|")[1])
        if not b:
            continue
        for ln in lines[b["batch_id"]]:
            if ln["line_type"] in ("TXN", "REFUND") and ln["txn_id"] not in txn_ids:
                for y in exc:
                    if kind_of[y["exception_id"]] != "CBAL-ROLLFWD" or y["investigation_group_id"] and y["investigation_group_id"] == x["investigation_group_id"]:
                        continue
                    r = rows_of[y["exception_id"]][0]
                    sc = y["root_cause"].split("|")[1]
                    yccy, rest = sc.split("/")
                    if yccy == b["currency"] and rest.split(" ")[1] == b["settlement_date"] and \
                            abs(Decimal(r["reported"]) - Decimal(r["computed"])) == Decimal(ln["amount"]):
                        self.candidates.append({
                            "candidate_id": f"CAND-{prefix}-{len(self.candidates) + 1:02d}",
                            "exception_ids": f"{x['exception_id']}; {y['exception_id']}",
                            "basis": "DATE_AND_AMOUNT_COINCIDENCE",
                            "detail": (f"line {ln['line_id']} references {ln['txn_id']} ({ln['amount']}), absent from the transaction export; "
                                       f"{rest.split(' ')[0]}'s roll-forward on {b['settlement_date']} differs by the same amount. "
                                       "No record links the transaction to this client."),
                            "label": "UNVERIFIED — NOT EVIDENCE-BACKED; not an investigation group",
                            "evidence": f"{self.ref('IN-13', ln)}; {r['evidence'].split(';')[0]}"})


def _scenario_id(self):
    import json
    p = self.root / "scenario.json"
    return json.loads(p.read_text())["scenario_id"] if p.exists() else "CASE"


Validator.group_exceptions = _group_exceptions
Validator.correlate_exceptions = _correlate_exceptions
Validator.scenario_id = _scenario_id

EXC_COLS = ["exception_id", "severity", "status", "category", "root_cause", "account_id", "currency", "first_date", "last_date",
            "amount", "affected_results", "affected", "flags", "related_records", "cause_category", "evidence",
            "evidence_status", "evidence_status_detail", "review_status", "investigation_group_id"]
GROUP_COLS = ["group_id", "exception_ids", "primary_exception_id", "size", "link_types", "links", "status", "review_status",
              "cause", "correlation_version"]
CANDIDATE_COLS = ["candidate_id", "exception_ids", "basis", "detail", "label", "evidence"]


def case_status(v):
    """CLEAN: all evidence available and every check passed or was not applicable.
    EVIDENCE_INCOMPLETE: a required file is missing, empty, unusable or ambiguous, or any check lacks evidence.
    EXCEPTIONS_OPEN: evidence complete, at least one check failed."""
    required_bad = [f for f, (st, _) in v.state.items() if f in schema.CSV_FILES or schema.PDF_FILES[f][2] == "REQUIRED"]
    if required_bad or any(r["outcome"] == INSUF for r in v.results):
        return "EVIDENCE_INCOMPLETE"
    if any(r["outcome"] == FAIL for r in v.results):
        return "EXCEPTIONS_OPEN"
    return "CLEAN"


def compare_answer_key(root, results, exceptions, candidates=None):
    """Compare validator output with the scenario's answer key, if one exists. Returns (matched, lines)."""
    import json
    p = Path(root) / "answer_key.json"
    if not p.exists():
        return None, []
    key = json.loads(p.read_text())
    got = sorted([r["check_id"], r["scope"], r["outcome"]] for r in results if r["outcome"] in (FAIL, INSUF))
    want = sorted(key["non_passing_results"])
    lines = []
    if got != want:
        lines += [f"unexpected: {x}" for x in got if x not in want] + [f"missing: {x}" for x in want if x not in got]
    gx = [{k: x[k] for k in ("exception_id", "severity", "root_cause", "affected_results")} for x in exceptions]
    if gx != key["exceptions"]:
        lines.append(f"exceptions differ: got {gx} want {key['exceptions']}")
    if "evidence_statuses" in key:
        got_es = {x["exception_id"]: x.get("evidence_status", "") for x in exceptions if x.get("evidence_status")}
        if got_es != key["evidence_statuses"]:
            lines.append(f"evidence statuses differ: got {got_es} want {key['evidence_statuses']}")
    if "investigation_groups" in key:
        got_g = sorted(sorted(x["exception_id"] for x in exceptions if x.get("investigation_group_id") == g)
                       for g in {x.get("investigation_group_id") for x in exceptions} - {"", None})
        if got_g != sorted(sorted(g) for g in key["investigation_groups"]):
            lines.append(f"investigation groups differ: got {got_g} want {key['investigation_groups']}")
    if "candidate_relationships" in key and candidates is not None:
        got_c = sorted(sorted(c["exception_ids"].split("; ")) for c in candidates)
        if got_c != sorted(sorted(c) for c in key["candidate_relationships"]):
            lines.append(f"candidate relationships differ: got {got_c} want {key['candidate_relationships']}")
    return not lines, lines



def write_outputs(root, results, exceptions=(), status="", groups=(), candidates=(), documents=None, period=None, rules=None):
    root = Path(root)
    period = period or resolve(root)
    (root / "validation").mkdir(exist_ok=True)
    cols = ["check_id", "control", "scope", "outcome", "computed", "reported", "evidence", "note", "root_cause", "evidence_status",
            "structured"]
    with open(root / "validation" / "control_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(dict(r, structured=json.dumps(r["structured"], sort_keys=True) if r.get("structured") else "") for r in results)
    with open(root / "validation" / "document_details.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["file_id", "label", "value"])  # D3: key details as extracted from the PDFs; nothing added
        for fid in sorted(documents or {}):
            for label in sorted(documents[fid]):
                w.writerow([fid, label, documents[fid][label]])
    with open(root / "validation" / "exceptions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXC_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(exceptions)
    for fname_, cols_, rows_ in (("investigation_groups.csv", GROUP_COLS, groups), ("candidate_relationships.csv", CANDIDATE_COLS, candidates)):
        with open(root / "validation" / fname_, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols_, lineterminator="\n")
            w.writeheader()
            w.writerows(rows_)
    summary = defaultdict(lambda: defaultdict(int))
    for r in results:
        summary[r["check_id"]][r["outcome"]] += 1
    totals = defaultdict(int)
    for r in results:
        totals[r["outcome"]] += 1
    manifest = []
    if (root / "manifest.csv").exists():
        with open(root / "manifest.csv", encoding="utf-8") as f:
            manifest = list(csv.DictReader(f))
    lines = ["# Validation report — " + root.name, "",
             "Produced by `python -m uc042lib.validate`. Every value below was recomputed from the source files; "
             "reported reconciliation values were compared, never copied. Synthetic data only; this is not a compliance conclusion.", "",
             f"**Overall:** {len(results)} check results — " + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())), "",
             f"**Case status:** {status}", "",
             "## Files and row counts", "",
             "Counting convention: CSV counts are **data rows, header excluded**; PDF counts are pages.", "",
             "| File | Requirement | Count | Unit |", "| --- | --- | ---: | --- |"]
    lines += [f"| {m['file_id']} `{m['filename']}` | {m['requirement']} | {m['record_count']} | {m['record_unit']} |" for m in manifest]
    if not manifest:
        lines.append("| (no manifest: file integrity against recorded hashes not checked; run `python -m uc042lib.prepare`) | | | |")
    csv_rows = sum(int(m["record_count"]) for m in manifest if m["format"] == "CSV")
    lines += ["", f"Total: {sum(1 for m in manifest if m['format'] == 'CSV')} CSV files, {csv_rows} data rows; "
              f"{sum(1 for m in manifest if m['format'] == 'PDF')} PDF files."]
    lines += ["", "## Results by check", "", "| Check | PASS | FAIL | INSUFFICIENT_EVIDENCE | NOT_APPLICABLE |", "| --- | ---: | ---: | ---: | ---: |"]
    for check in sorted(summary):
        s = summary[check]
        lines.append(f"| {check} | {s[PASS]} | {s[FAIL]} | {s[INSUF]} | {s[NA]} |")
    lines += ["", "## Exceptions (one per root cause)", ""]
    for x in exceptions:
        lines += [f"### {x['exception_id']} — {x['severity']} — {x['category']} ({x['status']})", "",
                  f"- Root cause: `{x['root_cause']}`", f"- Scope: {x['account_id']} {x['currency']} {x['first_date']} to {x['last_date']}"
                  + (f"; amount {x['amount']}" if x["amount"] else ""),
                  f"- Affected results ({x['affected_results']}): {x['affected']}"]
        if x["flags"]:
            lines.append(f"- Flags: {x['flags']}")
        if x["related_records"]:
            lines.append(f"- Related records: {x['related_records']}")
        if x.get("evidence_status"):
            lines.append(f"- Evidence status: **{x['evidence_status']}**" + (f" — {x['evidence_status_detail']}" if x.get("evidence_status_detail") else ""))
        if x.get("investigation_group_id"):
            lines.append(f"- Investigation group: `{x['investigation_group_id']}`")
        lines += [f"- Evidence: {x['evidence']}", f"- Status: {x['status']}; review: {x.get('review_status', '')}",
                  "- Cause: not established (no cause is set without evidence)", ""]
    if not exceptions:
        lines.append("None.")
    lines += ["", "## Investigation groups (evidence-linked; never set a cause or close an exception)", ""]
    for g in groups:
        lines += [f"### {g['group_id']} — {g['size']} exceptions ({g['status']}; review: {g['review_status']})", "",
                  f"- Exceptions: {g['exception_ids']}", f"- Link types: {g['link_types']}", f"- Links: {g['links']}", ""]
    if not groups:
        lines.append("None.")
    lines += ["", "## Candidate relationships (UNVERIFIED — not evidence-backed; not groups)", ""]
    lines += [f"- {c['candidate_id']}: {c['exception_ids']} — {c['basis']}: {c['detail']} [{c['evidence']}]" for c in candidates] or ["None."]
    matched, diffs = compare_answer_key(root, results, exceptions, candidates)
    if matched is not None:
        lines += ["", "## Answer key", "", "MATCH: results and exceptions are exactly as expected." if matched else "MISMATCH:"]
        lines += [f"- {d}" for d in diffs]
    lines += ["", "## Not independently verified in milestone 1", "",
              "- Resource items B–D: taken as reported (all 0.00). No independent source exists (gap G-S04).",
              "- D+1 comparison: not performed; blank by synthetic convention (gap G-R05).",
              "- Own-funds account opening balances: synthetic, no independent source. Not assessed; no result is emitted.",
              f"- Client balance roll-forward is assessed from the earliest snapshot provided; with the {period.previous_end.day} "
              f"{period.previous_end:%b} opening snapshot (D4), every {period.month_name} day-pair is assessed.",
              "- Reported values (IN-05, IN-06) and source records come from the same synthetic simulation: validation proves mutual consistency, not operational truth.",
              *(["- A zero recomputed difference that equals the reported difference is a PASS (C06, C08).",
                 "- NOT_APPLICABLE is used only for: optional evidence not provided (V00-FILE, C16); "
                 "allocation of a receipt received before the period start, whose bank credit is outside the period (RC4, convention P1)."]
                if (rules or APPROVED_RULES).zero_difference_outcome == PASS else
                ["- NOT_APPLICABLE is used only for: no difference to resolve (C06, C08); optional evidence not provided (V00-FILE, C16); "
                 "allocation of a receipt received before the period start, whose bank credit is outside the period (RC4, convention P1)."]),
              "- PDF key details are parsed deterministically from a fixed synthetic layout. Reviewer confirmation (DQ17) is not modelled.",
              "- Not in scope for milestone 1: pack statements (C15), exception workflow, timing-difference evidence (no differences exist).",
              "- Invalid rows are excluded and reported (DQ-FIELD). A scope an excluded row could have affected returns INSUFFICIENT_EVIDENCE; "
              "where an excluded row's own account, date or reference is unreadable, every scope it might touch is treated as affected."]
    (root / "VALIDATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return totals


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SET
    v = Validator(root, sys.argv[2] if len(sys.argv) > 2 else None)  # optional PER-YYYY-MM
    results = v.run()
    status = case_status(v)
    totals = write_outputs(root, results, v.exceptions, status, v.groups, v.candidates, v.pdf, v.period, v.rules)
    print(f"{root.name}: {len(results)} check results: " + ", ".join(f"{k} {v_}" for k, v_ in sorted(totals.items())))
    print(f"Case status: {status}")
    for x in v.exceptions:
        print(f"  {x['exception_id']} {x['severity']:<8} {x['category']}: {x['account_id']} {x['first_date']}..{x['last_date']} "
              f"{x['amount']} ({x['affected_results']} results)")
    for g in v.groups:
        print(f"  {g['group_id']} investigation group of {g['size']}: {g['exception_ids']} ({g['link_types']})")
    for c in v.candidates:
        print(f"  {c['candidate_id']} candidate (UNVERIFIED, not a group): {c['exception_ids']}")
    matched, diffs = compare_answer_key(root, results, v.exceptions, v.candidates)
    if matched is not None:
        print("Answer key: " + ("MATCH" if matched else "MISMATCH"))
        for d in diffs[:20]:
            print("  " + d)
    print(f"Report: {root / 'VALIDATION_REPORT.md'}")
    sys.exit(0 if matched or (matched is None and not v.exceptions) else 1)


if __name__ == "__main__":
    main()
