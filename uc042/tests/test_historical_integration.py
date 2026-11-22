"""Historical data integration readiness: period-aware policy recognition (register, intake, upload, processing), the
AI investigation input boundary (profiles, periods, verification exclusion), pack-reference integrity in the
application database, and the recorded decisions HD-1..HD-4.

Read-only on every protected asset: the demo packs, datasets and verification files, the September packs and datasets.
Variants are built in temporary folders. Offline: no provider is called; the only investigation run is the existing
September offline simulation (SIMULATED, not AI) into a temporary folder.
ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS."""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.rule_history import PUBLISHED_RULES

from tests.api_support import ROOT
from tests.final_pack_support import OFFLINE, sha_tree
from tests.test_api_monthly import MonthlyCase, S05_PACK, SC2_PACK, scenario_files
from uc042app.config import ConfigurationError, Settings
from uc042lib import policy, schema
from uc042lib.investigation import config as inv_config
from uc042lib.investigation import roots
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.retrieval import EvidenceStore, RetrievalError, load_pack
from uc042lib.pack.generate import build
from uc042lib.period import PeriodConfig, PeriodError, resolve
from uc042lib.prepare import identify, prepare_case, selected_policy

DEMO = ROOT / "demo_history"
DATASETS = DEMO / "datasets"
SEPT = ROOT / "uc042_dataset"
MANIFEST = {r["period_id"][4:]: r for r in json.loads((DEMO / "verification" / "run_manifest.json").read_text(encoding="utf-8"))["months"]}
V11, V12 = "safeguarding_reconciliation_policy_v1.1.pdf", "safeguarding_reconciliation_policy_v1.2.pdf"
KEYS = [("Safeguarding method", "SEGREGATION"), ("Reconciliation method", "STANDARD"),
        ("Reconciliation point", "17:00 Europe/London"), ("Frequency", "Each reconciliation day"),
        ("Internal reconciliation basis", "Per currency")]


def policy_pdf(path, version, effective, markings=()):
    """A minimal PDF carrying the policy key details (test fixture; never a project document)."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    y = 800
    for line in list(markings) + [f"Document version: {version}", f"Effective date: {effective}"] + [f"{k}: {v}" for k, v in KEYS]:
        c.drawString(56, y, line)
        y -= 16
    c.save()
    return path


def month_files(token, skip=()):
    """The demo month's source files as (name, path), from demo_history/datasets (read only)."""
    d = DATASETS / token
    return [(p.name, p) for sub in ("source_data", "supporting_documents") for p in sorted((d / sub).iterdir()) if p.name not in skip]


def pack(token):
    return json.loads((DEMO / "packs" / MANIFEST[token]["pack_id"] / "pack.json").read_text(encoding="utf-8"))


def roots_of(p):
    return sorted(x["root_cause"] for x in p["exception_register"]["exceptions"])


class Tmp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = {name: sha_tree(path) for name, path in (("demo", DEMO), ("sept", SEPT), ("packs", ROOT / "packs"))}

    @classmethod
    def tearDownClass(cls):
        for name, path in (("demo", DEMO), ("sept", SEPT), ("packs", ROOT / "packs")):
            assert sha_tree(path) == cls.before[name], f"protected tree changed: {name}"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def prep(self, period, files, name="case"):
        inp = self.tmp / f"in-{name}"
        inp.mkdir()
        for n, p in files:
            shutil.copyfile(p, inp / f"upload_{n}")
        case = self.tmp / name
        return prepare_case(inp, case, period), case

    @staticmethod
    def policy_rows(intake):
        return sorted((r["decision"], r["canonical_name"], r["reason"]) for r in intake if r["file_id"] == "IN-17")


# ----------------------------------------------------------------------------------------------- policy register
class PolicyRegister(Tmp):
    def test_versions_classification_and_approved_selection(self):
        v11, v12 = policy.POLICY_VERSIONS["1.1"], policy.POLICY_VERSIONS["1.2"]
        self.assertEqual((v11.classification, v11.decision, str(v11.effective)), ("ILLUSTRATIVE_SYNTHETIC", "HD-1", "2025-10-01"))
        self.assertIn("Not an actual or historical Moorwand policy", v11.description)
        self.assertEqual((v12.classification, str(v12.effective)), ("SYNTHETIC_PROJECT_DOCUMENT", "2026-05-07"))
        sel = policy.APPROVED_SELECTIONS["PER-2026-05"]
        self.assertEqual((sel.version, sel.decision), ("1.2", "HD-2"))
        self.assertIn("identical apart from the cited file name", sel.basis)
        self.assertEqual(list(policy.APPROVED_SELECTIONS), ["PER-2026-05"])

    def test_applicable_version_by_month(self):
        want = {1: ["1.1"], 2: ["1.1"], 3: ["1.1"], 4: ["1.1"], 5: ["1.1", "1.2"], 6: ["1.2"], 7: ["1.2"], 8: ["1.2"],
                9: ["1.2"], 10: ["1.2"], 11: ["1.2"], 12: ["1.2"]}
        for m, versions in want.items():
            self.assertEqual(policy.applicable_versions(PeriodConfig(2026, m)), versions, m)
        self.assertEqual(policy.applicable_versions(PeriodConfig(2025, 9)), [])
        self.assertIn("superseded by v1.2", policy.applicability("1.1", PeriodConfig(2026, 6))[1])
        self.assertIn("after April 2026", policy.applicability("1.2", PeriodConfig(2026, 4))[1])

    def test_the_supplied_policy_documents_are_recognised_with_their_watermarks(self):
        from uc042lib.prepare import _pdf_details
        docs = [(DATASETS / t / "supporting_documents" / V11, "1.1") for t in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05")]
        docs += [(DATASETS / t / "supporting_documents" / V12, "1.2") for t in ("2026-05", "2026-06", "2026-07", "2026-08")]
        docs.append((SEPT / "set_01_clean_baseline" / "supporting_documents" / V12, "1.2"))
        for path, version in docs:
            details, _ = _pdf_details(path)
            self.assertEqual(policy.recognise(details, policy.document_text(path)), (version, []), path)
        self.assertIn("ILLUSTRATIVE SYNTHETIC DOCUMENT", policy.document_text(docs[0][0]))

    def test_an_arbitrary_or_unmarked_pdf_is_never_a_policy(self):
        cases = {"1.3": policy_pdf(self.tmp / "a.pdf", "1.3", "2026-01-01", ["SYNTHETIC DOCUMENT - UC-042 POC"]),
                 "unmarked v1.1": policy_pdf(self.tmp / "b.pdf", "1.1", "2025-10-01"),
                 "v1.2 wrong date": policy_pdf(self.tmp / "c.pdf", "1.2", "2026-01-01", ["SYNTHETIC DOCUMENT - UC-042 POC"])}
        from uc042lib.prepare import _pdf_details
        for label, path in cases.items():
            kind, cands, _ = identify(path)
            self.assertEqual((kind, cands), ("PDF", ["IN-17"]), label)  # it looks like a policy...
            details, _ = _pdf_details(path)
            version, problems = policy.recognise(details, policy.document_text(path))
            self.assertTrue(problems, label)  # ...but is not accepted as one
        letter = DATASETS / "2026-01" / "supporting_documents" / "ack_letter_SGA-GBP-01.pdf"
        self.assertNotIn("IN-17", identify(letter)[1])
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(self.tmp / "d.pdf"))
        c.drawString(56, 800, "An ordinary PDF")
        c.save()
        self.assertEqual(identify(self.tmp / "d.pdf")[0], "REJECT")

    def test_build_tool_uses_the_register_and_the_run_manifest_records_it(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import build_demo_history
        finally:
            sys.path.remove(str(ROOT / "tools"))
        self.assertEqual(build_demo_history.POLICY_SELECTION["2026-05"][0], policy.APPROVED_SELECTIONS["PER-2026-05"].version)
        self.assertEqual({t: r["policy_version"] for t, r in MANIFEST.items()},
                         {"2026-01": "1.1", "2026-02": "1.1", "2026-03": "1.1", "2026-04": "1.1", "2026-05": "1.2",
                          "2026-06": "1.2", "2026-07": "1.2", "2026-08": "1.2"})
        self.assertEqual(MANIFEST["2026-05"]["policy_files_supplied"],
                         [f"supporting_documents/{V11}", f"supporting_documents/{V12}"])


# --------------------------------------------------------------------------------------------- intake (prepare)
class Intake(Tmp):
    def test_january_to_april_select_the_illustrative_v11(self):
        for m in range(1, 5):
            p = PeriodConfig(2026, m)
            intake, case = self.prep(p, month_files(p.token), p.token)
            self.assertEqual(selected_policy(case), "1.1", p.token)
            rows = self.policy_rows(intake)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][:2], ("ACCEPTED", V11))
            self.assertIn("policy v1.1 (ILLUSTRATIVE_SYNTHETIC) SELECTED", rows[0][2])
            # the document is copied byte for byte (watermarks and metadata preserved) under its own version
            self.assertEqual((case / "supporting_documents" / V11).read_bytes(),
                             (DATASETS / p.token / "supporting_documents" / V11).read_bytes())
            self.assertFalse((case / "supporting_documents" / V12).exists())
            sel = json.loads((case / "policy_selection.json").read_text(encoding="utf-8"))
            self.assertEqual([d["classification"] for d in sel["documents"]], ["ILLUSTRATIVE_SYNTHETIC"])
            self.assertEqual(resolve(case).policy, "1.1")

    def test_may_keeps_both_policies_and_selects_v12(self):
        p = PeriodConfig(2026, 5)
        intake, case = self.prep(p, month_files("2026-05"))
        rows = self.policy_rows(intake)
        self.assertEqual([(r[0], r[1]) for r in rows], [("ACCEPTED", V11), ("ACCEPTED", V12)])
        self.assertIn("v1.1 (ILLUSTRATIVE_SYNTHETIC) SUPPLIED_NOT_SELECTED", rows[0][2])
        self.assertIn("v1.2 (SYNTHETIC_PROJECT_DOCUMENT) SELECTED", rows[1][2])
        self.assertIn("approved selection HD-2", rows[1][2])
        with open(case / "manifest.csv", encoding="utf-8", newline="") as f:
            self.assertEqual(sorted(r["filename"] for r in csv.DictReader(f) if r["file_id"] == "IN-17"), [V11, V12])
        self.assertEqual(selected_policy(case), "1.2")
        with self.assertRaises(PeriodError):  # the engine itself never chooses between the two
            resolve(case)

    def test_selection_reaches_the_pack_audit_trail_and_results_equal_the_stored_pack(self):
        for token in ("2026-01", "2026-05", "2026-08"):
            p = PeriodConfig.from_id(f"PER-{token}")
            _, case = self.prep(p, month_files(token), token)
            version = selected_policy(case)
            # compared with a stored pack: built under the rules that pack was published with (explicit, nothing patched)
            status, built, _, _, _ = build(case, PeriodConfig(p.year, p.month, version), rules=PUBLISHED_RULES)
            self.assertEqual(status, "GENERATED", token)
            stored = pack(token)
            self.assertEqual(roots_of(built), roots_of(stored), token)
            self.assertEqual(built["executive_summary"]["control_outcomes"]["by_outcome"],
                             stored["executive_summary"]["control_outcomes"]["by_outcome"], token)
            self.assertEqual(sorted(i["relative_path"] for i in built["audit_trail"]["inputs"] if i["file_id"] == "IN-17"),
                             sorted(i["relative_path"] for i in stored["audit_trail"]["inputs"] if i["file_id"] == "IN-17"))
            c03 = [r["evidence_refs"] for c in built["control_register"] if c["check_id"] == "C03-POLICY" for r in c["results"]]
            self.assertIn(f"_v{version}.pdf", c03[0])
            self.assertTrue(any("SELECTED for reconciliation" in r["reason"] and r["file_id"] == "IN-17"
                                for r in built["audit_trail"]["intake"]))

    def test_later_months_and_september_are_unchanged(self):
        for token in ("2026-06", "2026-07", "2026-08"):
            p = PeriodConfig.from_id(f"PER-{token}")
            _, case = self.prep(p, month_files(token), token)
            self.assertEqual(selected_policy(case), "1.2")
        s05 = SEPT / "scn_S05_unexplained_gbp_difference"
        intake, case = self.prep(PeriodConfig(2026, 9), [(p.name, p) for sub in ("source_data", "supporting_documents")
                                                         for p in sorted((s05 / sub).iterdir())], "sept")
        with open(case / "manifest.csv", encoding="utf-8", newline="") as f:
            names = {r["file_id"]: r["filename"] for r in csv.DictReader(f)}
        self.assertEqual(names, {fid: v[0] for fid, v in {**schema.CSV_FILES, **schema.PDF_FILES}.items() if fid in names})
        self.assertEqual(selected_policy(case), "1.2")
        status, built, _, _, _ = build(case, PeriodConfig(2026, 9))
        stored = json.loads((ROOT / "packs" / S05_PACK / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual((status, roots_of(built)), ("GENERATED", roots_of(stored)))

    def test_explicit_selection_overrides_the_register(self):
        intake, case = self.prep(PeriodConfig(2026, 5, "1.1"), month_files("2026-05"))
        self.assertEqual(selected_policy(case), "1.1")
        self.assertIn("selected explicitly", self.policy_rows(intake)[0][2])

    def test_a_policy_that_does_not_apply_is_rejected_and_never_used(self):
        files = month_files("2026-04", skip=(V11,)) + [(V12, DATASETS / "2026-05" / "supporting_documents" / V12)]
        intake, case = self.prep(PeriodConfig(2026, 4), files, "apr")
        rows = self.policy_rows(intake)
        self.assertEqual([r[0] for r in rows], ["MISSING", "REJECTED"])
        self.assertIn("takes effect on 2026-05-07, after April 2026", rows[1][2])
        self.assertFalse(list((case / "supporting_documents").glob("safeguarding*")))
        files = month_files("2026-06", skip=(V12,)) + [(V11, DATASETS / "2026-05" / "supporting_documents" / V11)]
        intake, _ = self.prep(PeriodConfig(2026, 6), files, "jun")
        self.assertIn("superseded by v1.2", [r for r in self.policy_rows(intake) if r[0] == "REJECTED"][0][2])

    def test_may_without_its_approved_version_is_missing_not_substituted(self):
        intake, case = self.prep(PeriodConfig(2026, 5), month_files("2026-05", skip=(V12,)))
        rows = self.policy_rows(intake)
        self.assertEqual(sorted(r[0] for r in rows), ["ACCEPTED", "MISSING"])
        self.assertIn("approved selection for PER-2026-05 is policy v1.2", next(r[2] for r in rows if r[0] == "MISSING"))
        self.assertIsNone(selected_policy(case))

    def test_two_different_documents_of_one_version_are_ambiguous(self):
        other = policy_pdf(self.tmp / "other.pdf", "1.2", "2026-05-07", ["SYNTHETIC DOCUMENT - UC-042 POC"])
        intake, case = self.prep(PeriodConfig(2026, 6), month_files("2026-06") + [("other_policy.pdf", other)])
        self.assertEqual(sorted(r[0] for r in self.policy_rows(intake)), ["AMBIGUOUS", "AMBIGUOUS", "MISSING"])
        self.assertIsNone(selected_policy(case))
        # an identical second copy is a duplicate, not a second policy
        intake, case = self.prep(PeriodConfig(2026, 6), month_files("2026-06") + [("copy.pdf", DATASETS / "2026-06" / "supporting_documents" / V12)], "dup")
        self.assertEqual(selected_policy(case), "1.2")
        self.assertIn("DUPLICATE", [r["decision"] for r in intake])

    def test_unsupported_or_unmarked_policy_is_rejected_at_intake(self):
        for label, pdf in (("1.3", policy_pdf(self.tmp / "u.pdf", "1.3", "2026-01-01", ["SYNTHETIC DOCUMENT - UC-042 POC"])),
                           ("unmarked", policy_pdf(self.tmp / "m.pdf", "1.1", "2025-10-01"))):
            intake, case = self.prep(PeriodConfig(2026, 2), month_files("2026-02", skip=(V11,)) + [("policy.pdf", pdf)], label)
            rows = self.policy_rows(intake)
            self.assertEqual(sorted(r[0] for r in rows), ["MISSING", "REJECTED"], label)
            self.assertRegex(next(r[2] for r in rows if r[0] == "REJECTED"), "unsupported policy version|lacks the required marking")


# --------------------------------------------------------------------------------------------- application upload
class HistoricalUpload(MonthlyCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.demo_before = sha_tree(DEMO)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        assert sha_tree(DEMO) == cls.demo_before, "a demo_history file changed"

    def month(self, token, skip=(), extra=()):
        y, m = map(int, token.split("-"))
        self.open_period(y, m)
        return self.upload(f"PER-{token}", [(n, p.read_bytes()) for n, p in month_files(token, skip)] + list(extra))

    def policy_docs(self, batch):
        return [d for d in batch["documents"] if d["evidence_id"] == "IN-17"]

    def test_january_upload_identifies_the_illustrative_policy(self):
        b = self.month("2026-01")
        (doc,) = self.policy_docs(b)
        self.assertEqual((doc["checks"]["policy"]["version"], doc["checks"]["policy"]["classification"], doc["validation_status"]),
                         ("1.1", "ILLUSTRATIVE_SYNTHETIC", "VALID"))
        self.assertTrue({"POLICY_VERSION", "ILLUSTRATIVE_SYNTHETIC_POLICY"} <= self.codes(doc))
        self.assertIn("not an actual or historical Moorwand policy",
                      next(m["message"] for m in doc["checks"]["messages"] if m["code"] == "ILLUSTRATIVE_SYNTHETIC_POLICY"))
        s = b["batch"]["summary"]
        self.assertEqual((s["missing_required"], s["policy_selection"]["selected_version"], b["batch"]["validation_status"]),
                         ([], "1.1", "VALID"))

    def test_may_upload_keeps_both_policies_and_processes_with_v12(self):
        b = self.month("2026-05")
        docs = {d["checks"]["policy"]["version"]: d for d in self.policy_docs(b)}
        self.assertEqual(sorted(docs), ["1.1", "1.2"])
        self.assertIn("POLICY_SUPPLIED_NOT_SELECTED", self.codes(docs["1.1"]))
        self.assertIn("POLICY_SELECTED", self.codes(docs["1.2"]))
        self.assertFalse(any("AMBIGUOUS_EVIDENCE_TYPE" in self.codes(d) for d in b["documents"]))
        s = b["batch"]["summary"]
        self.assertEqual(s["policy_selection"], {"selected_version": "1.2", "selected_document": docs["1.2"]["document_id"],
                                                 "approved_selection": "HD-2", "supplied_not_selected": ["1.1"]})
        self.assertEqual((s["processing_set"]["IN-17"], s["processing_set"]["IN-17@v1.1"]),
                         (docs["1.2"]["document_id"], docs["1.1"]["document_id"]))
        self.assertEqual(self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm").status_code, 200)
        run = self.process(b["batch"]["batch_id"])
        self.assertEqual((run["status"], run["result"]["policy_version"]), ("SUCCEEDED", "1.2"), run)
        built = json.loads((self.packs_root / run["result"]["pack_id"] / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(i["relative_path"] for i in built["audit_trail"]["inputs"] if i["file_id"] == "IN-17"),
                         [f"supporting_documents/{V11}", f"supporting_documents/{V12}"])
        c03 = [r["evidence_refs"] for c in built["control_register"] if c["check_id"] == "C03-POLICY" for r in c["results"]]
        self.assertIn(V12, c03[0])
        self.assertEqual(roots_of(built), roots_of(pack("2026-05")))
        self.assertTrue(all(x["status"] == "OPEN" for x in built["exception_register"]["exceptions"]))

    def test_a_policy_that_does_not_govern_the_month_is_an_error_document(self):
        b = self.month("2026-04", skip=(V11,), extra=[(V12, (DATASETS / "2026-05" / "supporting_documents" / V12).read_bytes())])
        (doc,) = self.policy_docs(b)
        self.assertEqual(doc["validation_status"], "ERROR")
        self.assertIn("POLICY_NOT_APPLICABLE", self.codes(doc))
        self.assertIn("IN-17", b["batch"]["summary"]["missing_required"])

    def test_an_unsupported_policy_pdf_is_an_error_document(self):
        pdf = policy_pdf(self.tmp / "p13.pdf", "1.3", "2026-01-01", ["SYNTHETIC DOCUMENT - UC-042 POC"])
        b = self.month("2026-02", skip=(V11,), extra=[("policy_v1.3.pdf", pdf.read_bytes())])
        (doc,) = self.policy_docs(b)
        self.assertEqual((doc["validation_status"], "POLICY_NOT_RECOGNISED" in self.codes(doc)), ("ERROR", True))
        self.assertIn("IN-17", b["batch"]["summary"]["missing_required"])

    def test_september_upload_behaviour_is_unchanged(self):
        b = self.upload("PER-2026-09", scenario_files())
        s = b["batch"]["summary"]
        self.assertEqual((s["missing_required"], s["policy_selection"]["selected_version"]), ([], "1.2"))
        self.assertFalse([k for k in s["processing_set"] if k.startswith("IN-17@")])

    def test_pack_references_are_consistent_and_stale_ones_are_reported(self):
        rep = self.svc.monthly.pack_references()
        self.assertEqual(rep["problems"], [])
        self.assertEqual(sorted(rep["periods"]["PER-2026-09"]), sorted([S05_PACK, SC2_PACK]))
        before = sha_tree(self.packs_root)
        self.svc.repos.periods.ensure("PER-2026-10", 2026, 10)
        self.svc.repos.periods.add_pack({"period_id": "PER-2026-09", "pack_id": "PACK-S01-PER-2026-09-000000000000",
                                         "origin": "POC_SCENARIO", "scenario_id": "S01", "dataset": "x", "processing_run_id": None,
                                         "pack_content_sha256": "0" * 64, "registered_at": "2026-11-04T00:00:00+00:00"})
        self.svc.repos.periods.add_pack({"period_id": "PER-2026-10", "pack_id": S05_PACK, "origin": "POC_SCENARIO",
                                         "scenario_id": "S05", "dataset": "x", "processing_run_id": None,
                                         "pack_content_sha256": "0" * 64, "registered_at": "2026-11-04T00:00:00+00:00"})
        problems = self.svc.monthly.pack_references()["problems"]
        self.assertEqual(sorted((p["pack_id"], p["problem"][:20]) for p in problems),
                         sorted([("PACK-S01-PER-2026-09-000000000000", "pack does not load: "),
                                 (S05_PACK, "registered content h"), (S05_PACK, "registered under PER")]))
        self.assertEqual(sha_tree(self.packs_root), before)  # reported only: nothing repaired or rewritten


# ------------------------------------------------------------------------------------- investigation input roots
class NeverCalled:
    provider, model, simulated, supports_tools = "never", "never", True, False

    def __getattr__(self, name):
        raise AssertionError("the investigator must not be reached")


class InvestigationRoots(Tmp):
    def test_historical_packs_and_datasets_load_from_the_approved_roots(self):
        for token, rec in MANIFEST.items():
            r = roots.resolve(period_id=rec["period_id"])
            self.assertEqual((r.profile, r.packs_root, r.datasets_root), ("historical-demo", (DEMO / "packs").resolve(),
                                                                         (DATASETS).resolve()))
            r.check_pack_id(rec["pack_id"])
            p = load_pack(rec["pack_id"], r.packs_root)
            store = EvidenceStore(p, r.datasets_root)
            self.assertEqual(store.dir, (DATASETS / token).resolve())
            files = {fname for rows in store.by_fid.values() for fname, _, _ in rows}
            self.assertTrue(files and all(token in f or f == "account_inventory.csv" for f in files), token)

    def test_september_configuration_still_works(self):
        r = roots.resolve()
        self.assertEqual((r.profile, r.packs_root, r.datasets_root, r.investigations_root),
                         ("september", inv_config.PACKS_ROOT.resolve(), inv_config.DATASETS_ROOT.resolve(),
                          inv_config.INVESTIGATIONS_ROOT.resolve()))
        for pid in (S05_PACK, SC2_PACK):
            EvidenceStore(load_pack(pid), None)
        # the existing offline simulation (SIMULATED, not AI) still runs end to end into a temporary folder
        s = run_investigation(SC2_PACK, "EXC-SC2-01", OFFLINE, investigations_root=self.tmp / "inv")
        self.assertEqual((s["result"]["validation_status"], s["result"]["model_metadata"]["simulated"]), ("VALID", True))

    def test_the_selected_period_selects_the_roots(self):
        self.assertEqual(roots.resolve(period_id="PER-2026-03").packs_root, (DEMO / "packs").resolve())
        self.assertEqual(roots.resolve(period_id="PER-2026-09").packs_root, inv_config.PACKS_ROOT.resolve())
        self.assertEqual(roots.resolve(environ={roots.ENV_PERIOD: "PER-2026-07"}).profile, "historical-demo")
        self.assertEqual(roots.resolve(environ={roots.ENV_PROFILE: "historical-demo"}).datasets_root, DATASETS.resolve())
        self.assertEqual(roots.resolve(period_id="PER-2026-03").periods, frozenset({"PER-2026-03"}))
        with self.assertRaises(roots.InvestigationRootsError):
            roots.resolve(period_id="PER-2026-03").check_pack_id(MANIFEST["2026-04"]["pack_id"])
        with self.assertRaises(roots.InvestigationRootsError):  # a historical pack is never read under September's roots
            roots.resolve().check_pack_id(MANIFEST["2026-03"]["pack_id"])
        with self.assertRaises(roots.InvestigationRootsError):
            roots.resolve(profile="historical-demo").check_pack_id(S05_PACK)
        with self.assertRaises(roots.InvestigationRootsError):  # refused before the investigator is reached
            run_investigation(MANIFEST["2026-03"]["pack_id"], "EXC-H202603-01", NeverCalled(), investigations_root=self.tmp / "i")

    def test_missing_or_invalid_roots_fail_without_falling_back_to_september(self):
        bad = [dict(packs_root=self.tmp / "nope", datasets_root=DATASETS), dict(packs_root="", datasets_root=DATASETS),
               dict(packs_root=DEMO / "packs"), dict(profile="october"), dict(period_id="PER-2026-12"),
               dict(profile="september", period_id="PER-2026-03"), dict(environ={roots.ENV_PROFILE: " "})]
        for kw in bad:
            with self.assertRaises(roots.InvestigationRootsError, msg=str(kw)):
                roots.resolve(**kw)
        pid = MANIFEST["2026-03"]["pack_id"]
        with self.assertRaises(RetrievalError):
            load_pack(pid, "")
        with self.assertRaises(RetrievalError):
            load_pack(pid, self.tmp / "missing")
        with self.assertRaises(RetrievalError):
            EvidenceStore(pack("2026-03"), "")
        with self.assertRaises(ConfigurationError):
            Settings.from_env(state_dir=self.tmp / "s", document_store=self.tmp / "d", datasets_root=DEMO)
        with mock.patch.dict(os.environ, {"UC042_DATASETS_ROOT": str(self.tmp / "missing")}):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(state_dir=self.tmp / "s", document_store=self.tmp / "d")
        with mock.patch.dict(os.environ, {"UC042_DATASETS_ROOT": str(DATASETS), "UC042_PACKS_ROOT": str(DEMO / "packs")}):
            s = Settings.from_env(state_dir=self.tmp / "s", document_store=self.tmp / "d")
            self.assertEqual((s.datasets_root, s.packs_root), (DATASETS.resolve(), (DEMO / "packs").resolve()))

    def test_the_verification_directory_cannot_be_an_input_root(self):
        for kw in (dict(packs_root=DEMO / "packs", datasets_root=DEMO), dict(packs_root=DEMO, datasets_root=DATASETS),
                   dict(packs_root=DEMO / "packs", datasets_root=DEMO / "verification"),
                   dict(packs_root=DEMO / "packs", datasets_root=ROOT / "UC042_JAN_AUG_HISTORICAL_DEMO")):
            with self.assertRaises(roots.InvestigationRootsError, msg=str(kw)):
                roots.resolve(**kw)
        with self.assertRaises(RetrievalError):
            EvidenceStore(pack("2026-03"), DEMO / "verification")

    def test_files_in_a_verification_directory_never_enter_the_evidence_set(self):
        """A mirror of the demo layout with planted material: a verification/ beside the datasets, a verification/ inside
        a dataset, and pack inputs that point at them. Nothing planted is read or found."""
        token, rec = "2026-03", MANIFEST["2026-03"]
        demo = self.tmp / "demo"
        shutil.copytree(DEMO / "packs" / rec["pack_id"], demo / "packs" / rec["pack_id"])
        shutil.copytree(DATASETS / token, demo / "datasets" / token)
        planted = "PLANTED-ANSWER-REF"
        (demo / "verification").mkdir()
        (demo / "verification" / "expected.csv").write_text(f"txn_id,bank_reference\nTX-9999,{planted}\n", encoding="utf-8")
        r = roots.resolve(packs_root=demo / "packs", datasets_root=demo / "datasets")
        p = load_pack(rec["pack_id"], r.packs_root)
        store = EvidenceStore(p, r.datasets_root)
        self.assertEqual(store.search_reference("SGA-GBP-01", planted)["found"], [])
        self.assertTrue(store.search_reference("SGA-GBP-01", "SETTLE 0263")["found"])  # real evidence still found
        self.assertFalse(any("verification" in f for rows in store.by_fid.values() for f, _, _ in rows))
        # a pack input pointing outside the dataset, or into a verification folder inside it, is refused
        for rel in ("../../verification/expected.csv", "verification/expected.csv"):
            (demo / "datasets" / token / "verification").mkdir(exist_ok=True)
            shutil.copyfile(demo / "verification" / "expected.csv", demo / "datasets" / token / "verification" / "expected.csv")
            tampered = json.loads(json.dumps(p))
            tampered["audit_trail"]["inputs"].append({"file_id": "IN-11", "relative_path": rel, "sha256_actual": "0" * 64,
                                                      "sha256_manifest": "0" * 64, "matches": True})
            with self.assertRaises(RetrievalError, msg=rel):
                EvidenceStore(tampered, demo / "datasets")
        # once a verification folder sits inside the datasets root, the root itself is refused
        with self.assertRaises(roots.InvestigationRootsError):
            roots.resolve(packs_root=demo / "packs", datasets_root=demo / "datasets")

    def test_cli_refuses_bad_roots_before_any_provider_is_configured(self):
        env = dict(os.environ, UC042_LLM_PROVIDER="never-a-provider", OPENAI_API_KEY="")
        for args, text in (([MANIFEST["2026-03"]["pack_id"], "--period", "PER-2026-12"], "no investigation profile covers"),
                           ([MANIFEST["2026-03"]["pack_id"], "--profile", "september"], "is not in the september profile")):
            p = subprocess.run([sys.executable, "-m", "uc042lib.investigation.run", *args], capture_output=True, text=True,
                               cwd=ROOT, env=env, timeout=120)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("INPUT ROOTS ERROR", p.stderr)
            self.assertIn(text, p.stderr)


# ------------------------------------------------------------------------------------------- recorded decisions
class Decisions(unittest.TestCase):
    def test_decisions_are_recorded(self):
        text = (ROOT / "docs" / "UC042_HISTORICAL_DEMO_DECISIONS.md").read_text(encoding="utf-8")
        for d in ("HD-1", "HD-2", "HD-3", "HD-4"):
            self.assertIn(f"## {d}", text)
        self.assertIn("not** an actual or historical Moorwand policy", text)

    def test_hd3_gbp_exceptions_stay_open_without_a_cause(self):
        for token in ("2026-03", "2026-05", "2026-08"):
            exc = pack(token)["exception_register"]["exceptions"]
            gbp = [x for x in exc if x["root_cause"].startswith(("BANK_LEDGER_DIFFERENCE", "UNMATCHED_BANK_ENTRY"))]
            self.assertEqual(len(gbp), 3, token)
            self.assertTrue(all((x["status"], x["review_status"], x["cause_category"]) == ("OPEN", "AWAITING_HUMAN_REVIEW", "")
                                for x in gbp), token)

    def test_hd4_reference_only_mutation(self):
        package = ROOT / "UC042_JAN_AUG_HISTORICAL_DEMO" / "UC042_JAN_AUG_HISTORICAL_DEMO"
        for token in ("2026-06", "2026-07", "2026-08"):
            ops = json.loads((package / token / "mutations.json").read_text(encoding="utf-8"))
            ref = [o for o in ops if o["file_id"] == "IN-09" and o["op"] == "set_field" and o["key"].endswith("-SB1")]
            self.assertEqual([o["field"] for o in ref], ["bank_reference"], token)
            self.assertFalse([o for o in ops if o.get("field") == "narrative_text"], token)
            with open(DATASETS / token / "source_data" / f"bank_statement_entries_{token}.csv", encoding="utf-8", newline="") as f:
                entry = next(r for r in csv.DictReader(f) if r["bank_entry_id"] == ref[0]["key"])
            self.assertEqual(entry["bank_reference"], ref[0]["new"])
            self.assertIn(ref[0]["old"], entry["narrative_text"])  # the narrative still names the correct batch


if __name__ == "__main__":
    unittest.main()
