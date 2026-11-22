"""January–August 2026 historical demonstration: package integrity, source data, dates, continuity, the period-aware
engine on eight months, scenario behaviour and interaction, the eight deterministic packs, and immutability of
September. ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.

The supplied package (UC042_JAN_AUG_HISTORICAL_DEMO) is read-only here. Its scenario_definition.json and mutations.json
are offline oracles for these tests only; the engine never reads them (it reads demo_history/datasets, which holds
only the source documents). Scenario variants are built in temporary folders. Offline: no provider is called.
"""
import csv
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from uc042lib import schema
from uc042lib.continuity import compare
from uc042lib.investigation import config as inv_config
from uc042lib.investigation.retrieval import EvidenceStore, RetrievalError, _inside, pack_policy_version
from uc042lib.pack import model as pack_model
from tests.rule_history import PUBLISHED_RULES
from uc042lib.pack.generate import build
from uc042lib.period import BASELINE, PeriodConfig, PeriodError, resolve
from uc042lib.validate import Validator, case_status

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "UC042_JAN_AUG_HISTORICAL_DEMO" / "UC042_JAN_AUG_HISTORICAL_DEMO"
DEMO = ROOT / "demo_history"
DATASETS = DEMO / "datasets"
SEPT_DATASETS = ROOT / "uc042_dataset"
SEPT_BASELINE = SEPT_DATASETS / "set_01_clean_baseline"
spec = importlib.util.spec_from_file_location("verify_demo_history", ROOT / "tools" / "verify_demo_history.py")
vh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vh)

MONTHS = [PeriodConfig(2026, m) for m in range(1, 9)]
TOKENS = [p.token for p in MONTHS]
LON = ZoneInfo("Europe/London")
SYNTHETIC = "ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS"
EXPECTED = {"2026-01": 0, "2026-02": 1, "2026-03": 3, "2026-04": 0, "2026-05": 4, "2026-06": 4, "2026-07": 5, "2026-08": 8}
RECON_DAYS = {"2026-01": 21, "2026-02": 20, "2026-03": 22, "2026-04": 20, "2026-05": 19, "2026-06": 22, "2026-07": 23, "2026-08": 20}
MISSING, GBP, REF = "MISSING_EUR_STATEMENT", "UNEXPLAINED_GBP_DIFFERENCE", "INCONSISTENT_SETTLEMENT_REFERENCE"

# The June investigation: run without the business owner's authorisation, preserved unchanged and recorded as an
# AUTHORIZATION_DISCREPANCY (report 19 §7). Its files are pinned here; the database records the decision.
JUNE_DISCREPANCY = Path("PACK-H202606-PER-2026-06-a07de266b389/EXC-H202606-01/INV-EXC-H202606-01-c7b353b53fb3")
JUNE_DISCREPANCY_FILES = {
    "evidence_ledger.json": "dcf01576e25c254660200666264cc7164b6ec758b0e2d5c735b6ba984fd79b29",
    "evidence_packet.json": "314c2a44508fbf22d50aaa2bbd33d0ea2133bb44ab077b21e49706ecf84a0071",
    "findings.json": "e97ea0831be4abd4505ba220fdaaf0ff4a288aae002658f61aba5099ad733fbc",
    "runs/0001.json": "16b0aa978f35fb20fc4ce6fee8da3848e0bd2af1d1b5b10b915b9177e95d7e55",
    "tool_calls.json": "b5286b3c05fe5abe04f16791f70d7f2c963e83231c88cc3ce9621a58ef292102",
}

# Protected-tree digests (sha256 over sorted "relative path NUL file sha256" lines), taken before this work began.
PROTECTED = {
    "uc042_dataset": ("b99dafac95d8ff8817499afa133a42e2fc261ddda75c0cdf837045c7ddb07945", 287),
    "packs": ("b77431dc9e3a28f2841abffdbbcce1f6bffc7f3d2496c236b9deef0bbf2f1560", 72),
    # tests/golden re-pinned 17 Nov 2026 (owner-approved C06/C08 rule: a reconciled zero difference is PASS, not
    # NOT_APPLICABLE). Previous pin 21fea1e6...42f9d. The only snapshot differences are those outcomes (tests/golden/README.md).
    "tests/golden": ("5d0ceefcdcc15234fb5035ecc1e9ec9de1c83679b142b5f21b75a389178cd42a", 10),
    "investigations": ("9f5081030697f144bfef2993bc28da1bd78948db8ee168a8f03329bb09480a55", 34),
    # The final-pack LIBRARY (code, not historical data) is re-pinned only for reviewed, intentional changes:
    #   af18244c...7d80f37 (12 files)  original pin.
    #   1a638662...c1bf107 (12 files)  Phase 8: publish_final_pack(..., expected=None) (report 20 §8; reconstructing the
    #                                  pre-Phase-8 persistence.py reproduces af18... exactly).
    #   b6509a20...89f38c (18 files)   Phase 10 analyst ACCEPT/REJECT review, UTC review timestamps, the Unicode PDF renderer
    #                                  (2.0-unicode, bundled DejaVu fonts) and primary final-pack storage outside the
    #                                  repository (UC042_P10_FINAL_INTEGRATION_READINESS_REPORT_V2.md, B1). Published packs
    #                                  re-render with the renderer they declare; the February pack verifies byte for byte.
    #   8b0d6aa8...9f7942 (18 files)   Clone E end-to-end workflow: the explicit REJECTED BY ANALYST disposition and the
    #                                  optional comment on a rejection (rendered only for packs that carry the new
    #                                  "disposition" field, so every earlier pack, including 4 with rejections, re-renders
    #                                  and verifies byte for byte), and the check that no rejected AI text appears anywhere
    #                                  in a final pack (END_TO_END_ANALYST_WORKFLOW.md). Owner approval required for P10/live.
    # 12 Nov 2026 (clone E, live verification): summary.py / model.py: the closing-summary prompt 1.1 tells the model to
    #                                  negate each disclaimer term separately (a live summary was refused for a long negated
    #                                  list); the validation is unchanged. Every published final pack re-verified before
    #                                  re-pinning (LIVE_VERIFICATION_REPORT.md). Owner approval required for P10/live.
    # 17 Nov 2026 (owner-approved PDF renderer correction): renderer 2.1-unicode lets a table row split inside the row, so a
    #                                  long finding flows across pages instead of failing GENERATE with a LayoutError (live
    #                                  walkthrough: a 7,918-character field). New packs declare 2.1; packs declaring 1.0 or 2.0
    #                                  render exactly as published (every published final pack re-verified byte for byte).
    #                                  Files: model.py, assemble.py, validate.py, render_pdf.py. Previous pin bf2dc23b...709cae.
    # 18 Nov 2026 (owner-approved renderer 3.0 + final-pack schema 1.3, UC042_RENDERER_3_IMPLEMENTATION_REPORT.md): the
    #                                  outcome-first report (new report_v3.py, outcome.py), a renderer dispatcher with the
    #                                  2.x builder frozen (report.py build_report_v2), closing summary NOT_REQUIRED for packs
    #                                  without exceptions and prompt 1.2 (summary.py, model.py), outcome checks (validate.py),
    #                                  assemble.py, render_pdf.py, render_html.py, __init__.py. 1.2 stays reserved for A1. Every
    #                                  published final pack re-verified byte for byte. Previous pin 58abb4a4...fc64d4 (18 files).
    # 22 Nov 2026 (Fix8 D5 / D-04, Agent B; needs owner approval like every re-pin): the rejected-content leak check compares
    #                                  sentences, normalised, and exempts a sentence that an ACCEPTED investigation, the
    #                                  deterministic pack, the closing-summary input or the fixed final-pack wording states
    #                                  (validate.py), and a closing-summary item whose own citation states the sentence
    #                                  (same words, any order, no negation dropped); FinalPackValidationError carries
    #                                  structured diagnostics (assemble.py).
    #                                  Published packs are unaffected (verify_final_pack does not re-run validation).
    #                                  Previous pin c2dc8804...0dda8 (20 files).
    "uc042lib/final_pack": ("92a91055b6c3fd33a43f6951c6cc9ad454974c62a7df7b5c61127416597071bf", 20),
}
SEPTEMBER_PACKS = {"PACK-S01-PER-2026-09-577b06a1d894", "PACK-S02-PER-2026-09-f3dfa52766bb", "PACK-S05-PER-2026-09-ddd0fdc8b731",
                   "PACK-SC2-PER-2026-09-aaca8a8b7194", "PACK-SC3B-PER-2026-09-137351796028", "PACK-SC3C-PER-2026-09-28bb49134f15",
                   "PACK-SC5A-PER-2026-09-ae391170b93a", "PACK-SC5C-PER-2026-09-eaac7e6b1444", "PACK-SC5D-PER-2026-09-2c5a7ae2e160"}


# ------------------------------------------------------------------------------------------------------- helpers
CODE_IDENTIFIERS = {"engine_fingerprint", "pack_layer_fingerprint", "processing_run_id", "pack_content_sha256", "pack_id"}


def code_values(d, out=None):
    """Every value of a code-derived identifier in a pack (they change whenever engine or pack-layer code changes)."""
    out = set() if out is None else out
    if isinstance(d, dict):
        for k, v in d.items():
            if k in CODE_IDENTIFIERS and isinstance(v, str):
                out.add(v)
            code_values(v, out)
    elif isinstance(d, list):
        for v in d:
            code_values(v, out)
    return out


def code_masked(p, text=None, extra=()):
    """`text` (default: the pack's canonical JSON) with every code-derived identifier of `p` (and of `extra` packs) masked."""
    text = pack_model.canonical(p) if text is None else text
    values = code_values(p)
    for e in extra:
        code_values(e, values)
    for v in sorted(values, key=len, reverse=True):
        text = text.replace(v, "<CODE>")
    return text


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree_digest(root):
    root = Path(root)
    items = sorted((p.relative_to(root).as_posix(), sha256(p)) for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return hashlib.sha256("".join(f"{p}\0{h}\n" for p, h in items).encode()).hexdigest(), len(items)


def oracle(token):
    d = PACKAGE / token
    return (json.loads((d / "scenario_definition.json").read_text(encoding="utf-8")),
            json.loads((d / "mutations.json").read_text(encoding="utf-8")))


def scenario_of(op):
    """The planted scenario an operation belongs to (mutations.json carries operations, not scenario labels)."""
    if op["op"] == "delete_record":
        return MISSING
    if op["op"] == "set_field" and op["file_id"] == "IN-09" and op["field"] == "bank_reference":
        return REF
    return GBP


_RUNS = {}


def engine(case_dir, period):
    """The real engine, run once per (case, period, policy) in this test process."""
    key = (str(case_dir), period.token, period.policy_version)
    if key not in _RUNS:
        v = Validator(case_dir, period)
        v.run()
        _RUNS[key] = v
    return _RUNS[key]


def month_run(token):
    rec = MANIFEST[token]
    return engine(DATASETS / token, PeriodConfig.from_id(rec["period_id"], rec["policy_version"]))


def nonpass(v):
    return {(r["check_id"], r["scope"], r["outcome"], r["root_cause"]) for r in v.results if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")}


def results(v, check, scope=None):
    return [r for r in v.results if r["check_id"] == check and (scope is None or r["scope"] == scope)]


def copy_case(token, tmp):
    dst = Path(tmp) / token
    shutil.copytree(DATASETS / token, dst)
    return dst


def rewrite(case, fid, fn, period):
    """Rewrite one source CSV with fn(rows) and keep manifest.csv consistent (hash and record count)."""
    name = period.filename(fid)
    path = case / "source_data" / name
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows = fn(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=schema.columns(fid), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with open(case / "manifest.csv", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        cols, man = r.fieldnames, list(r)
    for m in man:
        if m["filename"] == name:
            m["sha256"], m["record_count"] = sha256(path), str(len(rows))
    with open(case / "manifest.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(man)


def revert(case, token, scenarios):
    """Undo the planted operations of the given scenarios (set_field -> old value; add_record -> removed). Deleted
    records cannot be restored from the oracle, so MISSING_EUR_STATEMENT is never reverted."""
    assert MISSING not in scenarios
    period = PeriodConfig.from_id(f"PER-{token}")
    _, ops = oracle(token)
    by_fid = {}
    for op in ops:
        if scenario_of(op) in scenarios:
            by_fid.setdefault(op["file_id"], []).append(op)
    for fid, fops in by_fid.items():
        pk = schema.columns(fid)[0]

        def fn(rows, fops=fops, pk=pk):
            for op in fops:
                if op["op"] == "set_field":
                    hit = [r for r in rows if r[pk] == op["key"]]
                    assert len(hit) == 1 and hit[0][op["field"]] == op["new"], op
                    hit[0][op["field"]] = op["old"]
                else:
                    assert op["op"] == "add_record", op
                    before = len(rows)
                    rows = [r for r in rows if r[pk] != op["record"][pk]]
                    assert len(rows) == before - 1, op
            return rows
        rewrite(case, fid, fn, period)
    return case


MANIFEST = {r["period_id"][4:]: r for r in json.loads((DEMO / "verification" / "run_manifest.json").read_text(encoding="utf-8"))["months"]}
CASES = vh.load_months(DEMO)


# ---------------------------------------------------------------------------------------------- package integrity
class PackageIntegrity(unittest.TestCase):
    def test_184_files_exact_set_manifests_and_hashes(self):
        inv = vh.inventory(PACKAGE)
        self.assertEqual(len(inv), 184)
        self.assertEqual(vh.package_integrity(PACKAGE), [])
        self.assertEqual(len({i["file"] for i in inv}), 184)

    def test_eight_months_each_with_fourteen_csv_categories(self):
        inv = vh.inventory(PACKAGE)
        for token in TOKENS:
            with self.subTest(token):
                csvs = [i for i in inv if i["month"] == token and i["category"] == "SOURCE_CSV"]
                self.assertEqual(sorted(Path(i["file"]).name for i in csvs),
                                 sorted(PeriodConfig.from_id(f"PER-{token}").filename(f) for f in schema.CSV_FILES))
                pdfs = [Path(i["file"]).name for i in inv if i["month"] == token and i["category"] == "SUPPORTING_PDF"]
                self.assertEqual(len(pdfs), 4 if token == "2026-05" else 3)
                self.assertEqual(Counter(i["category"] for i in inv if i["month"] == token)["SCENARIO_ORACLE (test-only)"], 2)

    def test_manifest_record_counts_equal_the_files(self):
        for token in TOKENS:
            with open(PACKAGE / token / "source_documents" / "manifest.csv", encoding="utf-8", newline="") as f:
                for m in csv.DictReader(f):
                    if m["format"] == "CSV":
                        n = len(CASES[token].rows[m["file_id"]])
                        self.assertEqual(str(n), m["record_count"], (token, m["filename"]))

    def test_package_is_not_modified_and_demo_copies_are_byte_identical(self):
        for token in TOKENS:
            src, dst = PACKAGE / token / "source_documents", DATASETS / token
            listed = {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()}
            copied = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
            self.assertEqual(copied, listed | {"scenario.json"}, token)
            for rel in listed:
                self.assertEqual((src / rel).read_bytes(), (dst / rel).read_bytes(), (token, rel))

    def test_no_answer_material_in_the_demo_datasets(self):
        for p in DATASETS.rglob("*"):
            self.assertNotIn(p.name, {"scenario_definition.json", "mutations.json", "answer_key.json", "SCENARIO_NOTES.md"})
        for token in TOKENS:
            sc = json.loads((DATASETS / token / "scenario.json").read_text(encoding="utf-8"))
            self.assertEqual(sc, {"scenario_id": "H" + token.replace("-", ""), "name": f"Historical demonstration month, "
                                  f"{PeriodConfig.from_id('PER-' + token).label}", "synthetic_notice": SYNTHETIC})

    def test_september_reference_hash_recorded_by_the_package(self):
        top = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sha256(ROOT / top["september_reference"]["baseline_manifest"]), top["september_reference"]["sha256_at_generation"])

    def test_upload_content_hashes(self):
        """CSV contents are unique across the eight months and September (the standing account inventory and the
        header-only discrepancy logs aside); the recurring PDFs are the same standing documents."""
        seen = {}
        header_only = {sha256(DATASETS / t / "source_data" / f"discrepancy_log_{t}.csv") for t in TOKENS}
        self.assertEqual(len(header_only), 1)
        self.assertEqual(all(CASES[t].rows["IN-14"] == [] for t in TOKENS), True)
        for token in TOKENS:
            for p in (DATASETS / token / "source_data").iterdir():
                if p.name != "account_inventory.csv" and not p.name.startswith("discrepancy_log_"):
                    self.assertNotIn(sha256(p), seen, (token, p.name, seen.get(sha256(p))))
                    seen[sha256(p)] = (token, p.name)
        for ds in SEPT_DATASETS.iterdir():
            for p in (ds / "source_data").glob("*.csv") if ds.is_dir() else []:
                self.assertNotIn(sha256(p), seen, (ds.name, p.name))
        inventories = {sha256(DATASETS / t / "source_data" / "account_inventory.csv") for t in TOKENS}
        self.assertEqual(inventories, {sha256(SEPT_BASELINE / "source_data" / "account_inventory.csv")})
        for name in ("ack_letter_SGA-GBP-01.pdf", "ack_letter_SGA-EUR-01.pdf"):
            self.assertEqual({sha256(DATASETS / t / "supporting_documents" / name) for t in TOKENS},
                             {sha256(SEPT_BASELINE / "supporting_documents" / name)})
        v12 = {sha256(DATASETS / t / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf") for t in TOKENS[4:]}
        self.assertEqual(v12, {sha256(SEPT_BASELINE / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf")})
        self.assertEqual(len({sha256(DATASETS / t / "supporting_documents" / "safeguarding_reconciliation_policy_v1.1.pdf") for t in TOKENS[:5]}), 1)

    def test_regeneration_is_reproducible(self):
        """The supplied generator, run into a temporary copy, reproduces every source file byte for byte (metadata JSON
        and Markdown are compared without line-ending differences: Windows text-mode writes CRLF)."""
        tmp = Path(tempfile.mkdtemp())
        try:
            out = tmp / "pkg"
            shutil.copytree(PACKAGE / "generator", out / "generator")
            p = subprocess.run([sys.executable, "-I", str(out / "generator" / "generate_history.py"), "--project", str(ROOT), "--out", str(out)],
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            for token in TOKENS:
                for f in (PACKAGE / token / "source_documents").rglob("*"):
                    if f.is_file():
                        g = out / token / "source_documents" / f.relative_to(PACKAGE / token / "source_documents")
                        self.assertEqual(f.read_bytes(), g.read_bytes(), (token, f.name))
                self.assertEqual((PACKAGE / token / "mutations.json").read_bytes().replace(b"\r\n", b"\n"),
                                 (out / token / "mutations.json").read_bytes().replace(b"\r\n", b"\n"), token)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------------------------------- source data
class SourceData(unittest.TestCase):
    def test_schema_types_and_requiredness(self):
        for token, case in CASES.items():
            with self.subTest(token):
                self.assertEqual(vh.schema_problems(case), [])

    def test_identifier_conventions_also_hold_for_september(self):
        self.assertEqual([p for p in vh.schema_problems(vh.Case(SEPT_BASELINE, BASELINE)) if "identifier" in p], [])

    def test_identifiers_embed_their_own_dates(self):
        for token, case in CASES.items():
            with self.subTest(token):
                self.assertEqual(vh.id_date_problems(case), [])

    def test_keys_unique_and_no_duplicate_rows(self):
        for token, case in CASES.items():
            with self.subTest(token):
                self.assertEqual(vh.key_problems(case), [])

    def test_money_is_exact_two_decimal_text(self):
        for token, case in CASES.items():
            for fid, (_, _, cols) in schema.CSV_FILES.items():
                for name in [c[0] for c in cols if c[1] in ("amount", "signed")]:
                    for r in case.rows[fid]:
                        if r[name]:
                            self.assertEqual(f"{Decimal(r[name]):.2f}", r[name], (token, fid, name))
        for p in ["uc042lib/money.py", "uc042lib/validate.py", "uc042lib/continuity.py", "uc042lib/period.py", "tools/verify_demo_history.py"]:
            self.assertNotIn("float(", (ROOT / p).read_text(encoding="utf-8"), p)

    def test_clean_months_have_no_relationship_or_arithmetic_finding(self):
        for token in ("2026-01", "2026-04"):
            self.assertEqual(vh.relationship_findings(CASES[token]), {}, token)
            self.assertEqual(vh.arithmetic_findings(CASES[token]), {}, token)
            self.assertEqual(vh.duplicate_bank_references(CASES[token]), {}, token)

    def test_planted_mutations_are_present_exactly(self):
        for token, case in CASES.items():
            definition, ops = oracle(token)
            self.assertEqual({scenario_of(o) for o in ops}, {p["scenario"] for p in definition["planted"]}, token)
            for op in ops:
                pk = schema.columns(op["file_id"])[0]
                rows = {r[pk]: r for r in case.rows[op["file_id"]]}
                if op["op"] == "delete_record":
                    self.assertNotIn(op["key"], rows, (token, op))
                elif op["op"] == "add_record":
                    self.assertEqual(rows[op["record"][pk]], op["record"], (token, op))
                else:
                    self.assertEqual(rows[op["key"]][op["field"]], op["new"], (token, op))

    def test_every_relationship_finding_is_explained_by_a_planted_scenario(self):
        """Missing statement: only EUR records of that day. GBP difference: only the two added bank entries. Inconsistent
        reference: only the batches, bank entry and cash-book entries carrying the two references. Nothing else."""
        for token, case in CASES.items():
            definition, ops = oracle(token)
            allowed = set()
            for p in definition["planted"]:
                if p["scenario"] == MISSING:
                    d = date.fromisoformat(p["date"])
                    allowed |= {f"ERL-SGA-EUR-01-{d:%Y%m%d} -> ST-SGA-EUR-01-{d:%Y%m%d}-1700", f"AQ-EUR-{d:%Y%m%d}", f"SB-EUR-{d:%Y%m%d}"}
                    allowed |= {r["ledger_entry_id"] for r in case.rows["IN-10"] if r["account_id"] == "SGA-EUR-01" and r["posted_ts"][:10] == p["date"]}
                    allowed |= {t["txn_id"] for t in case.rows["IN-11"] if t["currency"] == "EUR" and t["executed_ts"][:10] == p["date"] and t["payment_reference"]}
                    nxt = min(s["statement_date"] for s in case.rows["IN-08"] if s["account_id"] == "SGA-EUR-01" and s["statement_date"] > p["date"])
                    prv = max(s["statement_date"] for s in case.rows["IN-08"] if s["account_id"] == "SGA-EUR-01" and s["statement_date"] < p["date"])
                    allowed.add(f"ST-SGA-EUR-01-{prv.replace('-', '')}-EOD -> ST-SGA-EUR-01-{nxt.replace('-', '')}-EOD")
                elif p["scenario"] == GBP:
                    allowed |= {p["debit_entry"], p["return_entry"]}
                else:
                    refs = {p["batch_without_bank_reference"], p["batch_with_two_bank_entries"]}
                    allowed |= refs | {p["bank_entry"], f"BE-GBP-{p['batch_with_two_bank_entries'][-4:]}-SB1"}
                    allowed |= {r["ledger_entry_id"] for r in case.rows["IN-10"] if r["payment_reference"] in refs}
            findings = {**vh.relationship_findings(case), **vh.arithmetic_findings(case)}
            for kind, items in findings.items():
                for item in items:
                    head = item.split(":")[0].split(" (")[0]
                    self.assertTrue(item in allowed or head in allowed, (token, kind, item))
            dup = vh.duplicate_bank_references(case)
            want = {}
            for p in definition["planted"]:
                if p["scenario"] == GBP:
                    want[("SGA-GBP-01", p["bank_reference"])] = [p["debit_entry"], p["return_entry"]]
                if p["scenario"] == REF:
                    first = p["batch_with_two_bank_entries"]
                    want[("SGA-GBP-01", first)] = sorted([f"BE-GBP-{first[-4:]}-SB1", p["bank_entry"]])
            self.assertEqual({k: sorted(v) for k, v in dup.items()}, {k: sorted(v) for k, v in want.items()}, token)

    def test_relationship_checks_detect_broken_links(self):
        """Negative cases: a dangling transaction reference, a duplicate primary key and a wrong reference are reported."""
        case = vh.Case(DATASETS / "2026-01", PeriodConfig(2026, 1))
        case.rows["IN-13"][0] = dict(case.rows["IN-13"][0], txn_id="TX-0101-99999")
        case.rows["IN-11"].append(dict(case.rows["IN-11"][0]))
        b = next(e for e in case.rows["IN-09"] if e["bank_entry_id"].endswith("-SB1") and e["account_id"] == "SGA-GBP-01")
        b["bank_reference"] = "SB-GBP-20260102" if "0102" not in b["bank_entry_id"] else "SB-GBP-20260105"
        rel = vh.relationship_findings(case)
        self.assertIn("LINE_WITHOUT_TRANSACTION", rel)
        self.assertTrue(rel.get("BATCH_WITHOUT_BANK_ENTRY") or rel.get("BATCH_WITH_SEVERAL_BANK_ENTRIES"))
        self.assertTrue(any("primary key" in p for p in vh.key_problems(case)))

    def test_identifiers_unique_across_months_except_documented_carry_forwards(self):
        """Only the standing account inventory and carried-forward boundary snapshots (byte-identical rows at the
        previous month's last day, when that day is a reconciliation day) share an ID between months."""
        chain = [CASES[t] for t in TOKENS] + [vh.Case(SEPT_BASELINE, BASELINE)]
        shared = Counter()
        for fid in schema.CSV_FILES:
            if fid == "IN-02":
                continue
            pk = schema.columns(fid)[0]
            owner = {}
            for case in chain:
                for r in case.rows[fid]:
                    if r[pk] in owner:
                        prev = owner[r[pk]]
                        self.assertEqual(fid, "IN-03", (fid, r[pk]))
                        self.assertEqual(prev[1], r, r[pk])
                        self.assertEqual(r["recon_date"], case.period.previous_end.isoformat(), r[pk])
                        shared[case.period.token] += 1
                    else:
                        owner[r[pk]] = (case.period.token, r)
        # months whose previous month ended on a reconciliation day: Apr (Tue 31 Mar), May (Thu 30 Apr), Jul (Tue 30 Jun),
        # Aug (Fri 31 Jul); not Feb, Mar, Jun (weekend month ends) or September (31 Aug bank holiday)
        ended_on_recon_day = [c.period.token for c in chain[1:] if c.period.previous_end.weekday() < 5
                              and c.period.previous_end not in vh.BANK_HOLIDAYS]
        self.assertEqual(sorted(shared), sorted(ended_on_recon_day))
        self.assertEqual(sum(shared.values()), 12 * len(ended_on_recon_day))


# ------------------------------------------------------------------------------------------------- dates and time
class DatesAndTime(unittest.TestCase):
    def test_all_dates_and_timestamps(self):
        for token, case in CASES.items():
            with self.subTest(token):
                self.assertEqual(vh.date_findings(case)[0], [])

    def test_offsets_follow_gmt_and_bst(self):
        offsets = {t: vh.date_findings(CASES[t])[1] for t in TOKENS}
        for t in ("2026-01", "2026-02"):
            self.assertEqual(set(offsets[t]), {"+0000"}, t)
        self.assertEqual(set(offsets["2026-03"]), {"+0000", "+0100"})
        for t in TOKENS[3:]:
            self.assertEqual(set(offsets[t]), {"+0100"}, t)

    def test_march_switches_at_the_transition_instant(self):
        case = CASES["2026-03"]
        stamps = [vh.ts(r[c]) for fid, (_, _, cols) in schema.CSV_FILES.items() for c in [x[0] for x in cols if x[1] == "ts"]
                  for r in case.rows[fid] if r[c]]
        for s in stamps:
            self.assertEqual(s.strftime("%z"), "+0000" if s < vh.DST_START_UTC else "+0100", s.isoformat())
        self.assertTrue(any(s < vh.DST_START_UTC for s in stamps) and any(s >= vh.DST_START_UTC for s in stamps))
        self.assertFalse(any(s.astimezone(LON).date() == date(2026, 3, 29) for s in stamps))  # Sunday: no activity

    def test_transition_is_judged_per_instant_not_per_day(self):
        self.assertTrue(vh.london_ok("2026-03-29T00:59:59+00:00"))
        self.assertTrue(vh.london_ok("2026-03-29T02:00:00+01:00"))
        self.assertFalse(vh.london_ok("2026-03-29T01:30:00+00:00"))  # does not exist in London
        self.assertFalse(vh.london_ok("2026-03-29T01:30:00+01:00"))
        self.assertFalse(vh.london_ok("2026-03-27T17:00:00+01:00"))  # BST offset before the change
        self.assertFalse(vh.london_ok("2026-03-30T17:00:00+00:00"))  # GMT offset after the change
        self.assertTrue(vh.london_ok("2026-10-25T01:30:00+01:00") and vh.london_ok("2026-10-25T01:30:00+00:00"))  # repeated hour
        self.assertEqual(PeriodConfig(2026, 4).opening_point_iso(), "2026-03-31T17:00:00+01:00")
        self.assertEqual(PeriodConfig(2026, 3).opening_point_iso(), "2026-02-28T17:00:00+00:00")
        self.assertEqual(PeriodConfig(2026, 1).opening_point_iso(), "2025-12-31T17:00:00+00:00")

    def test_calendars_weekends_and_bank_holidays(self):
        for token, case in CASES.items():
            rows = {r["calendar_date"]: r for r in case.rows["IN-01"]}
            self.assertEqual(sum(r["is_recon_day"] == "true" for r in rows.values()), RECON_DAYS[token], token)
            engine_days = [d for d, bd, _ in case.period.expected_calendar() if bd]
            self.assertEqual(sorted(date.fromisoformat(d) for d, r in rows.items() if r["is_recon_day"] == "true"), engine_days, token)
        for d in ("2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31"):
            r = next(r for r in CASES[d[:7]].rows["IN-01"] if r["calendar_date"] == d)
            self.assertEqual((r["is_recon_day"], r["non_recon_reason"]), ("false", "UK_BANK_HOLIDAY"), d)

    def test_date_checks_detect_bad_values(self):
        case = vh.Case(DATASETS / "2026-03", PeriodConfig(2026, 3))
        e = case.rows["IN-09"][0]
        e["booking_ts"] = e["booking_ts"][:-6] + "+01:00"  # 2 Mar with a BST offset
        case.rows["IN-11"][0]["executed_ts"] = "2026-04-01T10:00:00+01:00"  # outside the period
        case.rows["IN-12"][0]["settlement_date"] = "2026-03-28"  # Saturday
        found = " ".join(vh.date_findings(case)[0])
        self.assertIn("not a valid Europe/London time", found)
        self.assertIn("executed outside the period", found)
        self.assertIn("not a business day", found)
        case.rows["IN-08"][0]["statement_date"] = "2026-02-30"
        case.rows["IN-10"][1]["posted_ts"] = "2026-03-02 09:00"
        probs = " ".join(vh.schema_problems(case))
        self.assertIn("impossible date", probs)
        self.assertIn("not a valid ts", probs)

    def test_september_opening_rows_are_not_august_activity(self):
        """31 Aug is a bank holiday: August holds no record dated 31 Aug, and September's 31 Aug rows are only its
        opening boundary records (permitted by the engine, not period activity)."""
        aug = CASES["2026-08"]
        for fid, (_, _, cols) in schema.CSV_FILES.items():
            for r in aug.rows[fid]:
                for name, typ, _, _ in cols:
                    if typ in ("date", "ts") and r[name][:10] == "2026-08-31" and fid != "IN-01":
                        self.fail(f"August record dated 31 Aug: {fid} {r[schema.columns(fid)[0]]}")
        sept = vh.Case(SEPT_BASELINE, BASELINE)
        on_31 = [(fid, r) for fid in ("IN-03", "IN-10") for r in sept.rows[fid] if (r.get("recon_date") or r.get("posted_ts", ""))[:10] == "2026-08-31"]
        self.assertEqual(len(on_31), 14)
        self.assertTrue(all(fid == "IN-03" or r["entry_type"] == "OPENING_BALANCE" for fid, r in on_31))
        v = engine(SEPT_BASELINE, BASELINE)
        self.assertEqual([r for r in v.results if r["check_id"] == "DQ-PERIOD" and r["outcome"] != "PASS"], [])


# --------------------------------------------------------------------------------------------- financial continuity
class Continuity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain = [CASES[t] for t in TOKENS] + [vh.Case(SEPT_BASELINE, BASELINE)]
        cls.items = {(a.period.token, b.period.token): vh.continuity(a, b) for a, b in zip(chain, chain[1:])}

    def test_every_month_end_carries_forward_exactly(self):
        self.assertEqual(len(self.items), 8)
        for k, items in self.items.items():
            self.assertEqual(Counter(i["view"] for i in items), {"CLIENT": 12, "CASH_BOOK": 2, "BANK": 4}, k)
            self.assertEqual([i for i in items if i["status"] != "MATCH" or i["difference"] != "0.00"], [], k)

    def test_august_closing_equals_the_september_opening_18_positions(self):
        items = self.items[("2026-08", "2026-09")]
        self.assertEqual(len(items), 18)
        keys = {(i["view"], i["record_key"]) for i in items}
        self.assertEqual(keys, {("CLIENT", f"C{n:04d}/GBP") for n in range(1, 9)} | {("CLIENT", f"C{n:04d}/EUR") for n in range(101, 105)}
                         | {("CASH_BOOK", "SGA-GBP-01"), ("CASH_BOOK", "SGA-EUR-01")}
                         | {("BANK", a) for a in ("SGA-GBP-01", "SGA-EUR-01", "OWN-GBP-01", "OWN-EUR-01")})
        got = {(i["view"], i["record_key"]): i["current_opening"] for i in items}
        self.assertEqual(got[("CASH_BOOK", "SGA-GBP-01")], "250000.00")
        self.assertEqual(got[("BANK", "OWN-EUR-01")], "150000.00")
        self.assertEqual(got[("CLIENT", "C0001/GBP")], "40000.00")
        # August's last reconciliation day is Fri 28 Aug; nothing moves between then and the 31 Aug opening point
        self.assertTrue(all("txns" not in i["previous_evidence"] for i in items if i["view"] == "CLIENT"))
        self.assertTrue(all("20260828" in i["previous_evidence"] for i in items if i["view"] in ("CLIENT", "BANK")))

    def test_engine_continuity_module_finds_no_difference(self):
        chain = [(DATASETS / t, PeriodConfig.from_id(MANIFEST[t]["period_id"], MANIFEST[t]["policy_version"])) for t in TOKENS]
        chain.append((SEPT_BASELINE, BASELINE))
        for (pd, pp), (cd, cp) in zip(chain, chain[1:]):
            rep = compare(pd, cd, cp, pp)
            with self.subTest(cp.token):
                self.assertEqual([i for i in rep["items"] if i["status"] == "DIFFERENCE"], [])
                self.assertTrue(all(i["status"] == "MATCH" for i in rep["items"] if i["view"] in ("BANK", "CASH_BOOK")))

    def test_january_opening_is_the_documented_synthetic_position(self):
        o = vh.january_opening(CASES["2026-01"])
        total = lambda ccy: sum(Decimal(v[0]) for k, v in o.items() if k.startswith("CLIENT") and v[1] == ccy)
        self.assertEqual((total("GBP"), total("EUR")), (Decimal("223400.00"), Decimal("71100.00")))
        self.assertEqual(o["CASH_BOOK SGA-GBP-01"][0], "223400.00")
        self.assertEqual(o["CASH_BOOK SGA-EUR-01"][0], "71100.00")
        self.assertEqual((o["BANK OWN-GBP-01"][0], o["BANK OWN-EUR-01"][0]), ("504136.00", "151082.84"))
        self.assertEqual((o["BANK SGA-GBP-01"][0], o["BANK SGA-EUR-01"][0]), ("223400.00", "71100.00"))
        jan = CASES["2026-01"]
        self.assertTrue(all(r["as_at_ts"] == "2025-12-31T17:00:00+00:00" for r in jan.rows["IN-03"] if r["recon_date"] == "2025-12-31"))
        self.assertTrue(all("20251231" in r["snapshot_id"] for r in jan.rows["IN-03"] if r["recon_date"] == "2025-12-31"))
        report = (PACKAGE / "continuity_report.md").read_text(encoding="utf-8")
        self.assertIn("documented synthetic demonstration opening position", report)
        self.assertIn("not derived from any real or earlier record", report)
        self.assertTrue(all(r["calendar_basis"].startswith("SYNTHETIC") for r in jan.rows["IN-01"]))
        self.assertEqual(compare(None, DATASETS / "2026-01", PeriodConfig(2026, 1))["status"], "NOT_VERIFIABLE")

    def test_a_carry_forward_break_is_reported_not_adjusted(self):
        case = vh.Case(DATASETS / "2026-02", PeriodConfig(2026, 2))
        snap = next(r for r in case.rows["IN-03"] if r["recon_date"] == "2026-01-31" and r["client_id"] == "C0003")
        snap["balance"] = f"{Decimal(snap['balance']) + Decimal('0.01'):.2f}"
        items = vh.continuity(CASES["2026-01"], case)
        bad = [i for i in items if i["status"] != "MATCH"]
        self.assertEqual([(i["record_key"], i["difference"]) for i in bad], [("C0003/GBP", "0.01")])


# --------------------------------------------------------------------------------------------- period-aware engine
class PeriodAwareEngine(unittest.TestCase):
    def test_policy_version_is_a_period_document_selection(self):
        self.assertEqual(PeriodConfig(2026, 1, "1.1").filename("IN-17"), "safeguarding_reconciliation_policy_v1.1.pdf")
        self.assertEqual(PeriodConfig(2026, 1).filename("IN-17"), "safeguarding_reconciliation_policy_v1.2.pdf")
        self.assertEqual(PeriodConfig(2026, 9, "1.2"), BASELINE)
        self.assertEqual(PeriodConfig(2026, 9).pdf_files, schema.PDF_FILES)
        self.assertEqual(PeriodConfig(2026, 5, "1.1").pdf_files["IN-17"][1], "Safeguarding reconciliation policy v1.1")
        for bad in ("1", "v1.1", "1.1.1", ""):
            with self.assertRaises(PeriodError):
                PeriodConfig(2026, 1, bad)
        with self.assertRaises(PeriodError):
            PeriodConfig.from_id("PER-2026-01", "x")

    def test_resolve_uses_the_policy_the_case_supplies(self):
        for t in TOKENS:
            if t != "2026-05":
                self.assertEqual(resolve(DATASETS / t).policy, "1.1" if t < "2026-05" else "1.2", t)
        for ds in sorted(p for p in SEPT_DATASETS.iterdir() if p.is_dir()):
            p = resolve(ds)
            self.assertEqual((p, p.policy, p.csv_files, p.pdf_files), (BASELINE, "1.2", schema.CSV_FILES, schema.PDF_FILES), ds.name)

    def test_two_supplied_policies_need_an_explicit_selection(self):
        with self.assertRaises(PeriodError) as cm:
            resolve(DATASETS / "2026-05")
        self.assertIn("1.1, 1.2", str(cm.exception))
        with self.assertRaises(PeriodError):
            Validator(DATASETS / "2026-05", "PER-2026-05")
        self.assertEqual(resolve(DATASETS / "2026-05", PeriodConfig(2026, 5, "1.1")).policy, "1.1")

    def test_may_policy_comparison_is_identical_apart_from_the_file_cited(self):
        a = engine(DATASETS / "2026-05", PeriodConfig(2026, 5, "1.1"))
        b = engine(DATASETS / "2026-05", PeriodConfig(2026, 5, "1.2"))
        norm = lambda s: re.sub(r"_v1\.[12]\.pdf", "_vX.pdf", str(s))
        cols = ("check_id", "scope", "outcome", "computed", "reported", "evidence", "note", "root_cause", "evidence_status")
        self.assertEqual([{k: norm(r[k]) for k in cols} for r in a.results], [{k: norm(r[k]) for k in cols} for r in b.results])
        self.assertEqual([{k: norm(v) for k, v in x.items()} for x in a.exceptions], [{k: norm(v) for k, v in x.items()} for x in b.exceptions])
        self.assertEqual(case_status(a), case_status(b))
        self.assertEqual(results(a, "V00-FILE", "IN-17"), [])  # the manifest row of the file actually read is used
        self.assertIn("v1.1.pdf", results(a, "C03-POLICY")[0]["evidence"])
        self.assertIn("v1.2.pdf", results(b, "C03-POLICY")[0]["evidence"])

    def test_policy_effective_after_the_period_is_never_applied(self):
        """April supplied with v1.2 only (effective 7 May): the policy-dependent checks are not run; nothing is forced."""
        tmp = Path(tempfile.mkdtemp())
        try:
            case = copy_case("2026-04", tmp)
            (case / "supporting_documents" / "safeguarding_reconciliation_policy_v1.1.pdf").unlink()
            shutil.copyfile(SEPT_BASELINE / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf",
                            case / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf")
            with open(case / "manifest.csv", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                cols, man = r.fieldnames, list(r)
            for m in man:
                if m["file_id"] == "IN-17":
                    m.update(filename="safeguarding_reconciliation_policy_v1.2.pdf",
                             relative_path="supporting_documents/safeguarding_reconciliation_policy_v1.2.pdf",
                             sha256=sha256(case / "supporting_documents" / "safeguarding_reconciliation_policy_v1.2.pdf"))
            with open(case / "manifest.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
                w.writeheader()
                w.writerows(man)
            v = Validator(case, PeriodConfig(2026, 4))
            v.run()
            self.assertEqual(v.period.policy, "1.2")
            self.assertIn("FAIL", {r["outcome"] for r in results(v, "V01-PDF", "IN-17")})
            self.assertEqual(case_status(v), "EVIDENCE_INCOMPLETE")
            self.assertTrue(all(r["outcome"] == "INSUFFICIENT_EVIDENCE" for r in results(v, "C03-POLICY")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_without_the_illustrative_policy_january_to_april_cannot_be_clean(self):
        """Decision A1 alternative, run in isolation: without v1.1 the month is evidence-incomplete (IN-17 missing)."""
        tmp = Path(tempfile.mkdtemp())
        try:
            case = copy_case("2026-01", tmp)
            (case / "supporting_documents" / "safeguarding_reconciliation_policy_v1.1.pdf").unlink()
            v = Validator(case, PeriodConfig(2026, 1))
            v.run()
            self.assertEqual(case_status(v), "EVIDENCE_INCOMPLETE")
            self.assertEqual([x["root_cause"] for x in v.exceptions], ["MISSING_FILE|IN-17"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_eight_runs_period_specific_files_calendars_and_unique_ids(self):
        ids = Counter()
        for t in TOKENS:
            rec, pack = MANIFEST[t], json.loads((DEMO / "packs" / MANIFEST[t]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
            p = PeriodConfig.from_id(rec["period_id"])
            self.assertEqual(pack["metadata"]["reporting_period"], {"period_id": p.period_id, "start": str(p.start), "end": str(p.end)})
            self.assertTrue(pack["metadata"]["pack_id"].startswith(f"PACK-H{p.year}{p.month:02d}-{p.period_id}-"))
            for i in pack["audit_trail"]["inputs"]:
                name = Path(i["relative_path"]).name
                self.assertTrue(p.token in name or name in ("account_inventory.csv", "ack_letter_SGA-GBP-01.pdf",
                                "ack_letter_SGA-EUR-01.pdf") or name.startswith("safeguarding_reconciliation_policy_v"), name)
            v = month_run(t)
            self.assertEqual(len(v.recon_days), RECON_DAYS[t])
            ids.update([pack["metadata"]["pack_id"], pack["metadata"]["processing_run_id"]])
            ids.update(x["exception_id"] for x in pack["exception_register"]["exceptions"])
            ids.update(g["group_id"] for g in pack["investigation_group_register"]["groups"])
        self.assertEqual([k for k, n in ids.items() if n > 1], [])

    def test_september_packs_rebuild_identically_apart_from_code_identifiers(self):
        masked = code_masked
        for pdir in sorted((ROOT / "packs").iterdir()):
            stored = json.loads((pdir / "pack.json").read_text(encoding="utf-8"))
            # rebuilt under the rules the stored pack was published with (passed explicitly to the engine)
            status, pack, _, outputs, _ = build(SEPT_DATASETS / stored["metadata"]["source_dataset"]["dataset"], rules=PUBLISHED_RULES)
            self.assertEqual(status, "GENERATED", pdir.name)
            self.assertEqual(masked(stored), masked(pack), pdir.name)
            for name, content in outputs.items():
                self.assertEqual((pdir / "processing" / name).read_text(encoding="utf-8"), content, (pdir.name, name))

    def test_evidence_store_reads_the_policy_the_pack_was_generated_with(self):
        for t, version in (("2026-01", "1.1"), ("2026-05", "1.2"), ("2026-08", "1.2")):
            pack = json.loads((DEMO / "packs" / MANIFEST[t]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
            self.assertEqual(pack_policy_version(pack), version)
            store = EvidenceStore(pack, datasets_root=DATASETS)
            self.assertEqual(store.fid_of.get(f"safeguarding_reconciliation_policy_v{version}.pdf"), "IN-17", t)
        with self.assertRaises(RetrievalError):
            _inside(PACKAGE / "2026-03" / "scenario_definition.json", PACKAGE)
        self.assertIn("scenario_definition.json", inv_config.FORBIDDEN_NAMES)

    def test_pack_cli_requires_a_period_for_a_policy_version(self):
        p = subprocess.run([sys.executable, "-m", "uc042lib.pack.generate", str(DATASETS / "2026-05"), "--packs-root",
                            str(Path(tempfile.gettempdir()) / "uc042-never-written"), "--policy-version", "1.2"],
                           capture_output=True, text=True, cwd=ROOT, timeout=120)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--policy-version needs --period", p.stderr)


# ----------------------------------------------------------------------------------------------- scenario behaviour
class ScenarioBehaviour(unittest.TestCase):
    def test_clean_months_are_genuinely_clean(self):
        for t in ("2026-01", "2026-04"):
            v = month_run(t)
            self.assertEqual((case_status(v), len(v.exceptions), nonpass(v)), ("CLEAN", 0, set()), t)

    def test_expected_exception_counts(self):
        for t in TOKENS:
            self.assertEqual(len(month_run(t).exceptions), EXPECTED[t], t)

    def test_missing_eur_statement_february(self):
        v = month_run("2026-02")
        self.assertEqual([(x["root_cause"], x["severity"], x["status"]) for x in v.exceptions],
                         [("MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16", "Critical", "OPEN")])
        insuf = [r for r in v.results if r["outcome"] == "INSUFFICIENT_EVIDENCE"]
        self.assertEqual(len(insuf), 15)
        self.assertTrue(all(r["root_cause"] == "MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-02-16" for r in insuf))
        self.assertTrue(all(r["computed"] == "" for r in insuf if r["check_id"] in ("C08-DIFFERENCE", "C07-BANK-EVIDENCE")))  # no balance substituted
        self.assertFalse(any("GBP" in r["scope"] or "GBP" in r["root_cause"] for r in v.results if r["outcome"] != "PASS" and r["outcome"] != "NOT_APPLICABLE"))
        pack = json.loads((DEMO / "packs" / MANIFEST["2026-02"]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(len(pack["missing_evidence_register"]["items"]), 1)
        self.assertEqual(pack["executive_summary"]["evidence_completeness"], "INCOMPLETE")

    def test_unexplained_gbp_difference_march(self):
        v, case = month_run("2026-03"), CASES["2026-03"]
        exc = {x["root_cause"]: x for x in v.exceptions}
        x = exc["BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-03-17|-517.30"]
        self.assertEqual((x["amount"], x["first_date"], x["last_date"], x["evidence_status"], x["status"], x["cause_category"]),
                         ("-517.30", "2026-03-17", "2026-03-19", "NOT_EVIDENCED", "OPEN", ""))
        self.assertEqual(sorted(exc), sorted(["BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-03-17|-517.30",
                                              "UNMATCHED_BANK_ENTRY|BE-GBP-0317-X01", "UNMATCHED_BANK_ENTRY|BE-GBP-0320-X02"]))
        fails = {r["scope"]: r["computed"] for r in results(v, "C08-DIFFERENCE") if r["outcome"] == "FAIL"}
        self.assertEqual(fails, {f"2026-03-{d}/SGA-GBP-01": "-517.30" for d in (17, 18, 19)})
        entries = {e["bank_entry_id"]: e for e in case.rows["IN-09"]}
        d1, d2 = entries["BE-GBP-0317-X01"], entries["BE-GBP-0320-X02"]
        self.assertEqual((d1["amount"], d1["dc_indicator"], d1["bank_reference"], d1["counterparty_name"], d1["booking_date"]),
                         ("517.30", "D", "SETTLE 0263", "", "2026-03-17"))
        self.assertEqual((d2["amount"], d2["dc_indicator"], d2["bank_reference"], d2["narrative_text"], d2["booking_date"]),
                         ("517.30", "C", "SETTLE 0263", "RETURN SETTLE 0263", "2026-03-20"))
        self.assertEqual([le for le in case.rows["IN-10"] if "0263" in le["payment_reference"]], [])  # no cash-book movement
        # independent daily view: bank (17:00 confirmation) minus cash book (entries to 17:00)
        diffs = {}
        for c in case.rows["IN-07"]:
            if c["account_id"] == "SGA-GBP-01":
                at = vh.ts(c["as_at_ts"])
                ledger = sum((Decimal(le["amount"]) if le["dc_indicator"] == "D" else -Decimal(le["amount"])
                              for le in case.rows["IN-10"] if le["account_id"] == "SGA-GBP-01" and vh.ts(le["posted_ts"]) <= at), Decimal(0))
                diffs[c["as_at_ts"][:10]] = Decimal(c["balance_amount"]) - ledger
        self.assertEqual({d: f"{x:.2f}" for d, x in diffs.items() if x}, {f"2026-03-{d}": "-517.30" for d in (17, 18, 19)})
        self.assertEqual(diffs["2026-03-31"], 0)  # brought back into agreement by the month end
        # internal view (requirement vs resource) unaffected, on the difference days too
        self.assertEqual({r["outcome"] for r in results(v, "C06-DIFFERENCE")}, {"PASS"})  # zero difference: PASS (17 Nov 2026)
        self.assertEqual({r["outcome"] for r in results(v, "C04-REQUIREMENT") + results(v, "C05-RESOURCE")}, {"PASS"})
        self.assertEqual(results(v, "DISC-LOG")[0]["outcome"], "FAIL")
        self.assertEqual(len(v.groups), 1)
        self.assertEqual(v.groups[0]["link_types"], "L1 REFERENCE; L3 LINEAGE")
        self.assertEqual(sorted(i.strip() for i in v.groups[0]["exception_ids"].split(";")), sorted(x["exception_id"] for x in v.exceptions))

    def test_unexplained_difference_is_not_described_as_resolved(self):
        for t in ("2026-03", "2026-05", "2026-08"):
            pack = json.loads((DEMO / "packs" / MANIFEST[t]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
            for x in pack["exception_register"]["exceptions"]:
                self.assertEqual((x["status"], x["review_status"], x["cause_category"]), ("OPEN", "AWAITING_HUMAN_REVIEW", ""))
                self.assertNotRegex(json.dumps(x), r"(?i)\b(resolved|reversed|corrected|returned by the bank)\b")

    def test_inconsistent_reference_june_is_never_matched_on_amount(self):
        v, case = month_run("2026-06"), CASES["2026-06"]
        self.assertEqual(sorted(x["root_cause"] for x in v.exceptions),
                         sorted(["C11-BATCH-BANK|SB-GBP-20260601", "C11-BATCH-BANK|SB-GBP-20260610",
                                 "CASH-BANK-LINK|LE-GBP-0601-0005", "UNMATCHED_CASHBOOK_ENTRY|LE-GBP-0610-0005"]))
        batch = next(b for b in case.rows["IN-12"] if b["batch_id"] == "SB-GBP-20260610")
        entry = next(e for e in case.rows["IN-09"] if e["bank_entry_id"] == "BE-GBP-0610-SB1")
        # the same amount on the same day exists, yet the batch is not linked to it
        self.assertEqual((entry["amount"], entry["booking_date"], entry["account_id"]),
                         (batch["net_amount_reported"], batch["settlement_date"], batch["account_id"]))
        self.assertEqual(entry["bank_reference"], "SB-GBP-20260601")
        self.assertEqual(results(v, "C11-BATCH-BANK", "SB-GBP-20260610")[0]["outcome"], "FAIL")
        self.assertEqual(results(v, "C11-BATCH-BANK", "SB-GBP-20260601")[0]["outcome"], "FAIL")
        self.assertEqual([r for r in results(v, "C08-DIFFERENCE") if r["outcome"] == "FAIL"], [])  # balances unaffected
        self.assertEqual(sorted(g["link_types"] for g in v.groups), ["L1 REFERENCE", "L1 REFERENCE"])

    def test_inconsistent_reference_with_the_narrative_also_changed(self):
        """Variant 2 (not in the package): narrative carries the wrong reference too. The engine never reads
        narrative_text, so the outcome is identical to variant 1 (reference only)."""
        self.assertNotIn("narrative_text", (ROOT / "uc042lib" / "validate.py").read_text(encoding="utf-8"))
        tmp = Path(tempfile.mkdtemp())
        try:
            case = copy_case("2026-06", tmp)
            p = PeriodConfig(2026, 6)
            rewrite(case, "IN-09", lambda rows: [dict(r, narrative_text=r["narrative_text"].replace("SB-GBP-20260610", "SB-GBP-20260601"))
                                                 if r["bank_entry_id"] == "BE-GBP-0610-SB1" else r for r in rows], p)
            changed = next(r for r in vh.Case(case, p).rows["IN-09"] if r["bank_entry_id"] == "BE-GBP-0610-SB1")
            original = next(r for r in CASES["2026-06"].rows["IN-09"] if r["bank_entry_id"] == "BE-GBP-0610-SB1")
            self.assertIn("SB-GBP-20260610", original["narrative_text"])
            self.assertNotIn("SB-GBP-20260610", changed["narrative_text"])
            v1, v2 = month_run("2026-06"), engine(case, p)
            self.assertEqual([x["root_cause"] for x in v1.exceptions], [x["root_cause"] for x in v2.exceptions])
            self.assertEqual(nonpass(v1), nonpass(v2))
            self.assertEqual(Counter(r["outcome"] for r in v1.results), Counter(r["outcome"] for r in v2.results))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ScenarioInteraction(unittest.TestCase):
    """Combined months against the same month with individual scenarios reverted (temporary copies)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.variants = {}
        for t, removed in (("2026-03", {GBP}), ("2026-06", {REF}), ("2026-05", {GBP}), ("2026-07", {REF}),
                           ("2026-08", {GBP}), ("2026-08", {REF}), ("2026-08", {GBP, REF})):
            case = revert(copy_case(t, cls.tmp / "-".join(sorted(removed))), t, removed)
            cls.variants[(t, frozenset(removed))] = engine(case, PeriodConfig.from_id(MANIFEST[t]["period_id"], MANIFEST[t]["policy_version"]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def roots(self, v):
        return sorted(x["root_cause"] for x in v.exceptions)

    def test_reverting_the_only_scenario_leaves_a_clean_month(self):
        for t, s in (("2026-03", GBP), ("2026-06", REF)):
            v = self.variants[(t, frozenset({s}))]
            self.assertEqual((case_status(v), self.roots(v), nonpass(v)), ("CLEAN", [], set()), t)

    def test_missing_evidence_is_independent_of_the_other_scenarios(self):
        for t, s in (("2026-05", GBP), ("2026-07", REF)):
            v = self.variants[(t, frozenset({s}))]
            self.assertEqual(self.roots(v), [f"MISSING_BANK_EVIDENCE|SGA-EUR-01|{oracle(t)[0]['planted'][0]['date']}"], t)
        v = self.variants[("2026-08", frozenset({GBP, REF}))]
        self.assertEqual(self.roots(v), ["MISSING_BANK_EVIDENCE|SGA-EUR-01|2026-08-17"])
        self.assertTrue(all("EUR" in r[1] or "EUR" in r[3] for r in nonpass(v)))  # no GBP effect from missing EUR evidence

    def families(self, roots):
        return sorted(r.split("|")[0] for r in roots)

    def test_two_scenario_months_add_the_single_scenario_contribution(self):
        """May (missing EUR + GBP) and July (missing EUR + reference): the month minus its reversible scenario keeps
        every one of its exceptions, and what the scenario adds has exactly the shape of the single-scenario month
        (March for GBP, June for the reference)."""
        for t, removed, single in (("2026-05", GBP, "2026-03"), ("2026-07", REF, "2026-06")):
            combined, base = month_run(t), self.variants[(t, frozenset({removed}))]
            self.assertTrue(set(self.roots(base)) <= set(self.roots(combined)), t)
            self.assertTrue(nonpass(base) <= nonpass(combined), t)
            added = set(self.roots(combined)) - set(self.roots(base))
            self.assertEqual(self.families(added), self.families(self.roots(month_run(single))), t)
            self.assertEqual(len(added), EXPECTED[single], t)

    def test_three_scenario_month_is_the_union_of_its_parts(self):
        combined = month_run("2026-08")
        only_missing = self.variants[("2026-08", frozenset({GBP, REF}))]
        no_gbp, no_ref = self.variants[("2026-08", frozenset({GBP}))], self.variants[("2026-08", frozenset({REF}))]
        self.assertEqual(set(self.roots(no_gbp)) | set(self.roots(no_ref)), set(self.roots(combined)))
        self.assertEqual(nonpass(no_gbp) | nonpass(no_ref), nonpass(combined))
        self.assertEqual(set(self.roots(no_gbp)) & set(self.roots(no_ref)), set(self.roots(only_missing)))
        self.assertEqual(self.families(set(self.roots(no_ref)) - set(self.roots(only_missing))), self.families(self.roots(month_run("2026-03"))))
        self.assertEqual(self.families(set(self.roots(no_gbp)) - set(self.roots(only_missing))), self.families(self.roots(month_run("2026-06"))))

    def test_august_contributions_add_up_to_eight(self):
        both = self.variants[("2026-08", frozenset({GBP, REF}))]
        no_gbp = self.variants[("2026-08", frozenset({GBP}))]
        no_ref = self.variants[("2026-08", frozenset({REF}))]
        self.assertEqual((len(both.exceptions), len(no_ref.exceptions) - len(both.exceptions),
                          len(no_gbp.exceptions) - len(both.exceptions)), (1, 3, 4))
        self.assertEqual(len(month_run("2026-08").exceptions), 1 + 3 + 4)

    def test_scenarios_do_not_break_customer_balance_continuity(self):
        runs = [(k, v) for k, v in self.variants.items()] + [(t, month_run(t)) for t in TOKENS]
        for k, v in runs:
            outcomes = Counter(r["outcome"] for r in results(v, "CBAL-ROLLFWD") + results(v, "CBAL-NONNEG"))
            self.assertTrue(outcomes["PASS"] > 0 and set(outcomes) <= {"PASS", "NOT_APPLICABLE"}, (k, outcomes))


# ------------------------------------------------------------------------------------------------- output packs
class OutputPacks(unittest.TestCase):
    def test_all_eight_packs_load_verify_and_resolve_citations(self):
        self.assertEqual(sorted(MANIFEST), TOKENS)
        for t in TOKENS:
            rec = MANIFEST[t]
            pack = json.loads((DEMO / "packs" / rec["pack_id"] / "pack.json").read_text(encoding="utf-8"))
            with self.subTest(t):
                self.assertEqual(vh.pack_findings(pack, DEMO / rec["dataset"]), [])
                self.assertEqual(pack["audit_trail"]["pack_content_sha256"], rec["pack_content_sha256"])
                self.assertEqual(sha256(DEMO / rec["dataset"] / "manifest.csv"), rec["dataset_manifest_sha256"])
                self.assertTrue((DEMO / "packs" / rec["pack_id"] / "pack.html").is_file())

    def test_each_pack_is_reproduced_exactly_by_the_current_code(self):
        for t in TOKENS:
            rec = MANIFEST[t]
            # Rebuilt under the rule the stored pack was published with (C06/C08 zero difference NOT_APPLICABLE before
            # 17 Nov 2026). The engine changed since, so code-derived identifiers (engine fingerprint, run ID, pack ID,
            # content hash) differ by design; everything else must match byte for byte.
            status, pack, html, outputs, _ = build(DATASETS / t, PeriodConfig.from_id(rec["period_id"], rec["policy_version"]),
                                                   rules=PUBLISHED_RULES)
            stored = DEMO / "packs" / rec["pack_id"]
            stored_pack = json.loads((stored / "pack.json").read_text(encoding="utf-8"))
            self.assertEqual(status, "GENERATED", t)
            self.assertEqual((stored / "pack.json").read_text(encoding="utf-8"), pack_model.canonical(stored_pack), t)  # stored as published
            self.assertEqual(code_masked(pack), code_masked(stored_pack), t)
            self.assertEqual(code_masked(pack, html, extra=[stored_pack]),
                             code_masked(pack, (stored / "pack.html").read_text(encoding="utf-8"), extra=[stored_pack]), t)
            for name, content in outputs.items():
                self.assertEqual(code_masked(pack, (stored / "processing" / name).read_text(encoding="utf-8"), extra=[stored_pack]),
                                 code_masked(pack, content, extra=[stored_pack]), (t, name))

    def test_engine_never_opens_the_scenario_oracles(self):
        """Run on the package's own case folder, which sits next to scenario_definition.json and mutations.json: every
        file the engine opens is inside the case folder."""
        import builtins
        import io
        case = PACKAGE / "2026-08" / "source_documents"
        opened, real_open, real_io_open = [], builtins.open, io.open

        def spy(file, *a, **k):
            opened.append(Path(file).resolve() if isinstance(file, (str, Path)) else file)
            return real_open(file, *a, **k)
        builtins.open = io.open = spy
        try:
            Validator(case, PeriodConfig(2026, 8)).run()
        finally:
            builtins.open, io.open = real_open, real_io_open
        paths = [p for p in opened if isinstance(p, Path)]
        self.assertTrue(paths)
        self.assertEqual([p for p in paths if case.resolve() not in p.parents], [])

    def test_expected_versus_actual_for_every_month(self):
        rows = vh.expected_vs_actual(PACKAGE, DEMO)
        self.assertEqual([(r["month"], r["expected_exceptions"], r["actual_exceptions"], r["result"]) for r in rows],
                         [(t, EXPECTED[t], EXPECTED[t], "MATCH") for t in TOKENS])
        for r in rows:
            self.assertEqual(r["engine_results_by_outcome"], dict(sorted(r["pre_validation_results_by_outcome"].items())), r["month"])

    def test_exception_evidence_includes_the_planted_records(self):
        for t in TOKENS:
            pack = json.loads((DEMO / "packs" / MANIFEST[t]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
            definition, _ = oracle(t)
            cited = {e for x in pack["exception_register"]["exceptions"] for e in x["evidence_ids"]}
            cited |= {e for g in pack["investigation_group_register"]["groups"] for e in g["evidence_ids"]}
            for p in definition["planted"]:
                if p["scenario"] == GBP:
                    self.assertIn(f"IN-09:{p['debit_entry']}", cited, t)
                    self.assertIn(f"IN-09:{p['return_entry']}", cited, t)
                if p["scenario"] == REF:
                    self.assertIn(f"IN-12:{p['batch_without_bank_reference']}", cited, t)
                    self.assertIn(f"IN-09:{p['bank_entry']}", cited, t)
                if p["scenario"] == MISSING:
                    self.assertIn(f"IN-06:ERL-SGA-EUR-01-{p['date'].replace('-', '')}", cited, t)

    def test_demo_output_is_isolated_and_deterministic_only(self):
        """Deterministic packs plus only the authorised February AI artefacts: the Phase 6A CLI investigation (report 16)
        and the Phase 6B end-to-end run (report 17): one rejected attempt (kept unpublished), one published and registered
        investigation, and one final audit pack. The only other AI artefact is the June investigation, which the business
        owner did not authorise (report 19 §7): it is preserved byte for byte as an AUTHORIZATION_DISCREPANCY and is in no
        final pack. Any other investigation or final pack in the demo fails this test."""
        from uc042lib.final_pack.persistence import verify_final_pack
        from uc042lib.investigation.persistence import verify_published
        self.assertEqual(sorted(p.name for p in DEMO.iterdir() if p.is_dir()),
                         ["datasets", "final_packs", "investigations", "packs", "verification"])
        self.assertEqual(sorted(p.name for p in (DEMO / "packs").iterdir()), sorted(r["pack_id"] for r in MANIFEST.values()))
        exc_dir = DEMO / "investigations" / MANIFEST["2026-02"]["pack_id"] / "EXC-H202602-01"
        authorised = [exc_dir / "INV-EXC-H202602-01-a3fd3fd2e9ed", exc_dir / "INV-EXC-H202602-01-6b1425b437f4"]
        self.assertEqual(sorted(p.name for p in (DEMO / "investigations").iterdir()),
                         ["PACK-H202602-PER-2026-02-195df2e1f216", JUNE_DISCREPANCY.parts[0], "_not_published"])
        self.assertEqual(sorted(p.name for p in exc_dir.iterdir()), sorted(a.name for a in authorised))
        june = DEMO / "investigations" / JUNE_DISCREPANCY
        self.assertEqual(sorted(p.relative_to(DEMO / "investigations" / JUNE_DISCREPANCY.parts[0]).as_posix()
                                for p in (DEMO / "investigations" / JUNE_DISCREPANCY.parts[0]).rglob("*") if p.is_file()),
                         sorted(f"{JUNE_DISCREPANCY.parts[1]}/{JUNE_DISCREPANCY.name}/{n}" for n in JUNE_DISCREPANCY_FILES))
        self.assertEqual({n: sha256(june / n) for n in JUNE_DISCREPANCY_FILES}, JUNE_DISCREPANCY_FILES)  # preserved unchanged
        self.assertEqual(verify_published(june), [])
        self.assertFalse(any(JUNE_DISCREPANCY.name in p.read_text(encoding="utf-8")
                             for p in (DEMO / "final_packs").rglob("*.json")))  # never in a final audit pack
        rejected = list((DEMO / "investigations" / "_not_published").rglob("*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(json.loads(rejected[0].read_text(encoding="utf-8"))["result"]["validation_status"], "REJECTED")
        for a in authorised:
            self.assertEqual(verify_published(a), [], a.name)
            findings = json.loads((a / "findings.json").read_text(encoding="utf-8"))
            self.assertEqual((findings["model_metadata"]["simulated"], findings["exception_resolution"]), (False, "NOT_RESOLVED_BY_INVESTIGATION"))
        for name in ("findings.json", "evidence_packet.json"):
            self.assertEqual(sorted(DEMO.rglob(name)), sorted(a / name for a in authorised + [june]), name)
        final = DEMO / "final_packs" / "FAP-H202602-PER-2026-02-v1-b8dd53bd2449"
        self.assertEqual([p.name for p in (DEMO / "final_packs").iterdir()], [final.name])
        self.assertEqual(verify_final_pack(final), [])
        fp = json.loads((final / "final_pack.json").read_text(encoding="utf-8"))
        self.assertEqual((fp["metadata"]["source_pack"]["pack_id"], [x["resolution_status"] for x in fp["exception_register"]]),
                         (MANIFEST["2026-02"]["pack_id"], ["UNRESOLVED"]))
        self.assertEqual(list(DEMO.rglob("closing_summary.json")), [])
        self.assertFalse(any("H2026" in p.name for root in ("packs", "investigations", "uc042_dataset") for p in (ROOT / root).rglob("*")))


# --------------------------------------------------------------------------------------------------- immutability
class Immutability(unittest.TestCase):
    def test_protected_trees_unchanged(self):
        for rel, want in PROTECTED.items():
            self.assertEqual(tree_digest(ROOT / rel), want, rel)

    def test_september_packs_and_datasets_verify(self):
        self.assertEqual({p.name for p in (ROOT / "packs").iterdir()}, SEPTEMBER_PACKS)
        for pid in SEPTEMBER_PACKS:
            pack = json.loads((ROOT / "packs" / pid / "pack.json").read_text(encoding="utf-8"))
            self.assertEqual(pack_model.content_hash(pack), pack["audit_trail"]["pack_content_sha256"], pid)
        for ds in (p for p in SEPT_DATASETS.iterdir() if p.is_dir()):
            with open(ds / "manifest.csv", encoding="utf-8", newline="") as f:
                for m in csv.DictReader(f):
                    self.assertEqual(sha256(ds / m["relative_path"]), m["sha256"], (ds.name, m["relative_path"]))


if __name__ == "__main__":
    unittest.main()
