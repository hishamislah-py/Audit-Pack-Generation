"""Database unification and functional gap closure (report 19).

  * period-aware storage resolution (uc042lib.investigation.roots, uc042app.services.layout);
  * one backend over one database serving several storage profiles (packs, investigations, final packs read from the
    profile that holds them; nothing is copied or changed);
  * investigation authorisation decisions (an AUTHORIZATION_DISCREPANCY is kept but excluded from the approved set);
  * the unification migration (PostgreSQL only): identifiers, the approved September merge, renumbered activity with
    provenance, resume, dry run, and every stop condition (nothing written);
  * reconciliation, exception-investigation cases and AI investigation: explicit, per period / per case, never automatic;
  * the five Phase 7 outstanding issues (derived titles, registered-only investigation counts, reassessment, corrections
    and the upload target are in the API; the two UI ones are in the frontend tests).

Disposable state only: temporary roots with COPIES of real packs, investigations and the February final pack (originals
are hashed before and after), a temporary SQLite database or the disposable PostgreSQL test database, and a disposable
source database created and dropped by the migration tests. Offline: the provider is the test mock; a live provider is
refused (api_support guards). ILLUSTRATIVE SYNTHETIC DATA."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.engine import make_url

from tests import TEST_DATABASE_URL
from tests.api_support import AI_OK, ROOT, copy_published, reset_test_database
from tests.final_pack_support import sha_tree
from tests.test_api_monthly import S05_PACK, MonthlyCase, scenario_files
from uc042app.config import ConfigurationError
from uc042app.errors import IntegrityFailure, NotFound
from uc042app.services.layout import RootSet, StorageLayout
from uc042lib.final_pack.sources import load_pack
from uc042lib.investigation import roots as inv_roots

DEMO = ROOT / "demo_history"
FEB_PACK = "PACK-H202602-PER-2026-02-195df2e1f216"
FEB_FINAL = "FAP-H202602-PER-2026-02-v1-b8dd53bd2449"
FEB_EXC = "EXC-H202602-01"
FEB_INV_REGISTERED = "INV-EXC-H202602-01-6b1425b437f4"  # Phase 6B: published and registered
FEB_INV_UNREGISTERED = "INV-EXC-H202602-01-a3fd3fd2e9ed"  # Phase 6A: published, never registered
SC5A_PACK = next((ROOT / "packs").glob("PACK-SC5A-*")).name
SC5A_EXC = "EXC-SC5A-01"


def make_profile_roots(base):
    """A temporary storage profile holding COPIES of the February pack, its dataset, both published investigations and the
    final audit pack (the originals are only read)."""
    r = {k: base / k for k in ("packs", "datasets", "investigations", "final_packs")}
    shutil.copytree(DEMO / "packs" / FEB_PACK, r["packs"] / FEB_PACK)
    shutil.copytree(DEMO / "datasets" / "2026-02", r["datasets"] / "2026-02")
    for inv in (FEB_INV_REGISTERED, FEB_INV_UNREGISTERED):
        copy_published(DEMO / "investigations" / FEB_PACK / FEB_EXC / inv, r["investigations"])
    shutil.copytree(DEMO / "final_packs" / FEB_FINAL, r["final_packs"] / FEB_FINAL)
    return r


def test_profile(r, periods=("PER-2026-02",)):
    return inv_roots.Profile("test-history", r["packs"], r["datasets"], r["investigations"], frozenset(periods), r["final_packs"])


# ============================================================================================ storage resolution
class StorageResolution(unittest.TestCase):
    def test_period_and_pack_routing_in_the_library(self):
        self.assertEqual(inv_roots.period_of_pack(FEB_PACK), "PER-2026-02")
        self.assertIsNone(inv_roots.period_of_pack("PACK-without-a-period"))
        self.assertEqual(inv_roots.profile_for_period("PER-2026-02"), "historical-demo")
        self.assertEqual(inv_roots.profile_for_period("PER-2026-09"), "september")
        self.assertEqual(inv_roots.profile_for_pack(FEB_PACK), "historical-demo")
        with self.assertRaises(inv_roots.InvestigationRootsError):  # unchanged: no silent fallback without an explicit default
            inv_roots.profile_for_period("PER-2026-11")
        self.assertEqual(inv_roots.profile_for_period("PER-2026-11", default="september"), "september")
        with self.assertRaises(inv_roots.InvestigationRootsError):
            inv_roots.profile_for_period("PER-2026-11", default="nonexistent")
        p = inv_roots.storage_profile("historical-demo")
        self.assertEqual((p.final_packs_root, p.packs_root), (DEMO / "final_packs", (DEMO / "packs").resolve()))
        with self.assertRaises(inv_roots.InvestigationRootsError):
            inv_roots.storage_profile("nonexistent")
        self.assertEqual(inv_roots.resolve(period_id="PER-2026-02").profile, "historical-demo")  # existing behaviour kept

    def test_a_pack_is_found_in_exactly_one_root_set_of_its_period(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            r = make_profile_roots(tmp / "extra")
            primary = RootSet("primary", tmp / "packs", tmp / "ds", tmp / "inv", tmp / "fp")
            shutil.copytree(ROOT / "packs" / S05_PACK, primary.packs_root / S05_PACK)
            extra = RootSet("test-history", r["packs"], r["datasets"], r["investigations"], r["final_packs"], frozenset({"PER-2026-02"}))
            layout = StorageLayout(primary, [extra])
            self.assertEqual(layout.for_pack(S05_PACK).name, "primary")
            self.assertEqual(layout.for_pack(FEB_PACK).name, "test-history")
            self.assertEqual([s.name for s in layout.for_period("PER-2026-02")], ["primary", "test-history"])
            self.assertEqual([s.name for s in layout.for_period("PER-2026-09")], ["primary"])
            with self.assertRaises(NotFound):
                layout.for_pack(SC5A_PACK)
            wrong = StorageLayout(primary, [RootSet("x", r["packs"], r["datasets"], r["investigations"], r["final_packs"],
                                                    frozenset({"PER-2026-01"}))])
            with self.assertRaises(IntegrityFailure) as e:  # a pack outside its profile's periods is never served
                wrong.for_pack(FEB_PACK)
            self.assertEqual(e.exception.code, "PACK_OUTSIDE_PROFILE")
            shutil.copytree(r["packs"] / FEB_PACK, primary.packs_root / FEB_PACK)
            with self.assertRaises(IntegrityFailure) as e:  # two copies: an integrity failure, never a silent choice
                layout.for_pack(FEB_PACK)
            self.assertEqual(e.exception.code, "DUPLICATE_PACK")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_unknown_storage_profile_stops_the_backend(self):
        settings = mock.Mock(packs_root=ROOT / "packs", datasets_root=ROOT / "uc042_dataset", investigations_root=ROOT / "x",
                             final_packs_root=ROOT / "y")
        with self.assertRaises(ConfigurationError):
            StorageLayout.from_settings(settings, ["nonexistent"])


# ============================================================================================ one backend, several profiles
class UnifiedBackendCase(MonthlyCase):
    """Primary roots: temporary copies of two September scenario packs. Storage profile test-history: temporary copies of
    the February pack, its dataset, both published February investigations and the February final audit pack."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.demo_before = sha_tree(DEMO)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        assert sha_tree(DEMO) == cls.demo_before, "a demo_history file changed"

    def setUp(self):
        super().setUp()
        self.stop_app()
        self.profile_roots = make_profile_roots(self.tmp / "history")
        self._profiles = mock.patch.dict(inv_roots.PROFILES, {"test-history": test_profile(self.profile_roots)})
        self._profiles.start()
        self.settings = self.settings.with_(storage_profiles=("test-history",))
        self.start_app()
        self.history_before = sha_tree(self.tmp / "history")

    def tearDown(self):
        super().tearDown()
        self._profiles.stop()

    def assert_history_unchanged(self):
        self.assertEqual(sha_tree(self.tmp / "history"), self.history_before, "a file of the storage profile changed")

    def inv_dir(self, inv):
        return self.profile_roots["investigations"] / FEB_PACK / FEB_EXC / inv

    def register_feb(self):
        entry, created = self.svc.registry.import_legacy(self.inv_dir(FEB_INV_REGISTERED), self.svc.packs.load(FEB_PACK), "analyst-1")
        self.assertTrue(created)
        return entry


class UnifiedBackend(UnifiedBackendCase):
    def test_every_period_is_served_from_the_profile_that_holds_its_files(self):
        env = self.get("/health").json()["environment"]
        self.assertEqual(env["storage_profiles"], ["primary", "test-history"])
        packs = {p["pack_id"] for p in self.get("/api/v1/packs").json()}
        self.assertTrue({FEB_PACK, S05_PACK} <= packs)
        periods = {p["period_id"]: p for p in self.get("/api/v1/periods").json()}
        self.assertEqual([x["pack_id"] for x in periods["PER-2026-02"]["packs"]], [FEB_PACK])
        self.assertEqual(periods["PER-2026-09"]["pack_count"], 2)
        self.assertEqual([f["final_pack_id"] for f in self.get("/api/v1/final-packs").json()], [FEB_FINAL])
        self.assertTrue(self.get(f"/api/v1/final-packs/{FEB_FINAL}/verify").json()["verified"])
        pdf = self.get(f"/api/v1/final-packs/{FEB_FINAL}/pdf")
        self.assertEqual(pdf.content, (self.profile_roots["final_packs"] / FEB_FINAL / "report.pdf").read_bytes())
        inv = self.get(f"/api/v1/packs/{FEB_PACK}/exceptions/{FEB_EXC}/investigations").json()
        self.assertEqual(sorted(i["investigation_id"] for i in inv["published"]), sorted([FEB_INV_UNREGISTERED, FEB_INV_REGISTERED]))
        self.assertEqual(self.get(f"/api/v1/investigations/{FEB_INV_REGISTERED}").json()["pack_id"], FEB_PACK)
        self.assert_history_unchanged()

    def test_the_database_records_which_profile_a_period_uses(self):
        self.svc.monthly.repos.periods.update("PER-2026-02", {"storage_profile": "test-history"})
        self.stop_app()
        self.settings = self.settings.with_(storage_profiles=())  # nothing configured: the database alone names the profile
        self.start_app()
        self.assertEqual(self.svc.layout.names, ["primary", "test-history"])
        self.assertEqual(self.get(f"/api/v1/packs/{FEB_PACK}").status_code, 200)
        self.assertEqual(self.get("/api/v1/periods/PER-2026-02").json()["period"]["storage_profile"], "test-history")

    def test_only_registered_authorised_investigations_count_as_published(self):
        feb = lambda: self.get("/api/v1/periods/PER-2026-02").json()["period"]  # noqa: E731
        p = feb()  # neither is registered yet: both are listed, neither is counted as published
        self.assertEqual((p["published_investigations"], p["excluded_investigations"], p["eligible_investigations"]), (0, 2, 0))
        self.register_feb()
        p = feb()  # Phase 7 issue 3: the unregistered Phase 6A artefact is no longer counted
        self.assertEqual((p["published_investigations"], p["excluded_investigations"], p["eligible_investigations"]), (1, 1, 1))
        self.assertEqual(p["reporting_status"], "FINAL_PACK_PUBLISHED")
        self.assert_history_unchanged()

    def test_an_authorisation_discrepancy_is_kept_but_excluded_from_the_approved_set(self):
        entry = self.register_feb()
        before = self.svc.registry.entries()
        self.svc.repos.authorizations.record(FEB_INV_REGISTERED, "AUTHORIZATION_DISCREPANCY", "not explicitly authorised (test)",
                                             "analyst-1")
        detail = self.get(f"/api/v1/investigations/{FEB_INV_REGISTERED}").json()
        self.assertFalse(detail["eligible"])
        self.assertEqual(detail["authorization"]["status"], "AUTHORIZATION_DISCREPANCY")
        self.assertTrue(any(r.startswith("authorisation: AUTHORIZATION_DISCREPANCY") for r in detail["ineligible_reasons"]))
        v = self.get(f"/api/v1/investigations/{FEB_INV_REGISTERED}/verify").json()
        self.assertEqual((v["artefact_verified"], v["registry_verified"], v["eligible"]), (True, True, False))
        p = self.get("/api/v1/periods/PER-2026-02").json()["period"]
        self.assertEqual((p["published_investigations"], p["excluded_investigations"]), (0, 2))
        self.assertEqual(self.svc.registry.entries(), before)  # the registry entry is never changed or removed
        self.assertEqual(entry["investigation_id"], FEB_INV_REGISTERED)
        # it cannot be put into a final audit pack: not selected by default, refused when selected explicitly
        review = self.post(f"/api/v1/packs/{FEB_PACK}/reviews").json()
        default = next(s for s in review["selections"] if s["exception_id"] == FEB_EXC)
        self.assertNotEqual(default.get("investigation_id"), FEB_INV_REGISTERED)
        r = self.patch(f"/api/v1/reviews/{review['review_id']}/selections",
                       {"selections": [{"exception_id": FEB_EXC, "inclusion": "INCLUDED", "investigation_id": FEB_INV_REGISTERED}]})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INELIGIBLE_SELECTION"))
        self.assertIn("AUTHORIZATION_DISCREPANCY", r.json()["detail"])
        self.svc.repos.authorizations.record(FEB_INV_REGISTERED, "APPROVED", "approved after review (test)", "analyst-1")
        self.assertTrue(self.get(f"/api/v1/investigations/{FEB_INV_REGISTERED}").json()["eligible"])  # the latest decision is in force
        self.assert_history_unchanged()

    def test_the_period_views_load_each_pack_once(self):
        # found in the report 19 end-to-end validation: every exception reloaded (and deep-copied) its pack, so the
        # unified September view took ~20 s and the period list timed out in the browser
        real = self.svc.packs.load
        with mock.patch.object(self.svc.packs, "load", side_effect=real) as load:
            p = self.get("/api/v1/periods/PER-2026-09").json()["period"]
            self.assertLessEqual(load.call_count, p["pack_count"])
            load.reset_mock()
            periods = self.get("/api/v1/periods").json()
            self.assertLessEqual(load.call_count, sum(x["pack_count"] for x in periods))

    def test_titles_are_derived_until_one_is_stored(self):
        p = self.get("/api/v1/periods/PER-2026-02").json()["period"]  # Phase 7 issue 2
        self.assertEqual((p["title"], p["title_source"]), ("February 2026 Reconciliation Audit", "DERIVED"))
        self.assertEqual(self.svc.monthly.repos.periods.get("PER-2026-02")["title"], "")  # the record itself is not rewritten
        r = self.patch("/api/v1/periods/PER-2026-02", {"title": "February 2026 Safeguarding Audit"})
        self.assertEqual((r.json()["title"], r.json()["title_source"]), ("February 2026 Safeguarding Audit", "STORED"))


# ============================================================================================ explicit reconciliation
class ExplicitReconciliation(UnifiedBackendCase):
    def runs(self):
        return [r for p in self.svc.monthly.repos.periods.list() for r in self.svc.monthly.repos.runs.list(period_id=p["period_id"])]

    def test_nothing_reconciles_or_investigates_on_its_own(self):
        self.assertEqual((self.runs(), self.svc.runner.repo.list()), ([], []))  # start-up registers packs only
        b = self.upload("PER-2026-09", scenario_files())
        self.get("/api/v1/periods")
        self.get("/api/v1/periods/PER-2026-09")
        self.get(f"/api/v1/packs/{S05_PACK}/exceptions")
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        self.restart()
        self.assertEqual((self.runs(), self.svc.runner.repo.list()), ([], []))  # upload, reads, confirmation, restart: nothing ran
        self.assertEqual(self.get("/api/v1/cases").json(), [])  # and no case was opened

    def test_reconciliation_is_started_explicitly_for_one_period(self):
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "INITIAL"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NO_CONFIRMED_DOCUMENTS"))
        b = self.upload("PER-2026-09", scenario_files())
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "INITIAL"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NO_CONFIRMED_DOCUMENTS"))  # validated is not confirmed
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "INITIAL"})
        self.assertEqual(r.status_code, 202, r.text)
        self.svc.runner.wait(r.json()["job_id"], timeout=180)
        run = self.get(f"/api/v1/processing-runs/{r.json()['run_id']}").json()
        self.assertEqual((run["status"], run["result"]["purpose"]), ("SUCCEEDED", "INITIAL"))
        self.assertTrue((self.packs_root / run["result"]["pack_id"] / "pack.json").is_file())  # a new pack, written once
        self.assertTrue((self.packs_root / S05_PACK / "pack.json").is_file())
        exc = self.get(f"/api/v1/packs/{run['result']['pack_id']}/exceptions").json()
        self.assertTrue(exc and all(x["status"] != "RESOLVED" for x in exc))
        self.assertEqual(len(self.runs()), 1)

    def test_reassessment_needs_evidence_received_after_publication_and_a_reason(self):
        r = self.post("/api/v1/periods/PER-2026-09/reconciliation", {"purpose": "REASSESSMENT", "reason": "new evidence"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NOTHING_TO_REASSESS"))  # September has no final pack
        before = sha_tree(self.profile_roots["final_packs"])
        extra = self.send_additional("PER-2026-02")
        self.assertTrue(self.get("/api/v1/periods/PER-2026-02").json()["period"]["pending_reassessment"])
        r = self.post("/api/v1/periods/PER-2026-02/reconciliation", {"purpose": "REASSESSMENT"})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "REASON_REQUIRED"))
        self.post(f"/api/v1/uploads/{extra['batch']['batch_id']}/confirm")
        # The normal processing action never substitutes for a reassessment of a published period.
        r = self.post(f"/api/v1/uploads/{extra['batch']['batch_id']}/process")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "REASSESSMENT_REQUIRED"))
        r = self.post("/api/v1/periods/PER-2026-02/reconciliation", {"purpose": "INITIAL"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "REASSESSMENT_REQUIRED"))
        # Phase 8: February's original source documents are reused from its verified dataset (each file checked against
        # the pack's recorded SHA-256), combined with the confirmed new evidence; nothing has to be uploaded again.
        plan = self.get("/api/v1/periods/PER-2026-02/reassessment").json()
        self.assertTrue(plan["can_reassess"], plan["blockers"])
        self.assertEqual((plan["target_pack_id"], plan["baseline"]["pack_id"], plan["missing_required"]), (FEB_PACK, FEB_PACK, []))
        r = self.post("/api/v1/periods/PER-2026-02/reconciliation", {"purpose": "REASSESSMENT", "reason": "bank letter received"})
        self.assertEqual(r.status_code, 202, r.text)
        self.svc.runner.wait(r.json()["job_id"], timeout=180)
        run = self.get(f"/api/v1/processing-runs/{r.json()['run_id']}").json()
        self.assertEqual((run["status"], run["result"]["purpose"], run["result"]["predecessor_pack_id"]),
                         ("SUCCEEDED", "REASSESSMENT", FEB_PACK), run)
        self.assertEqual(run["result"]["baseline"]["pack_id"], FEB_PACK)
        self.assertTrue(set(run["result"]["baseline_files"]) >= {"IN-01", "IN-02", "IN-09", "IN-17"})
        new_pack = run["result"]["pack_id"]
        self.assertNotEqual(new_pack, FEB_PACK)
        lineage = self.get("/api/v1/periods/PER-2026-02/lineage").json()
        self.assertEqual([(x["pack_id"], x["predecessor_pack_id"], x["lineage_root_pack_id"]) for x in lineage],
                         [(new_pack, FEB_PACK, FEB_PACK)])
        self.assertEqual(lineage[0]["change_summary"]["exceptions"]["before"], lineage[0]["change_summary"]["exceptions"]["after"])
        p = self.get("/api/v1/periods/PER-2026-02").json()["period"]
        self.assertEqual((p["reassessment_runs"], p["latest_reassessment_status"]), (1, "SUCCEEDED"))
        self.assertIn("REASSESSMENT_STARTED", [a["action"] for a in self.svc.repos.activity.recent(entity_type="period",
                                                                                                    entity_id="PER-2026-02")])
        # Published and historical material is never changed by a reassessment.
        self.assertEqual(sha_tree(self.profile_roots["final_packs"]), before)
        self.assert_history_unchanged()

    def test_a_reassessment_needs_a_published_final_pack(self):
        b = self.upload("PER-2026-09", scenario_files())
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        from uc042app.errors import Conflict
        with self.assertRaises(Conflict) as cm:  # even when the caller claims new evidence: September has no final pack
            self.svc.monthly.reconcile("PER-2026-09", "REASSESSMENT", "late bank confirmation", pending_reassessment=True)
        self.assertEqual(cm.exception.code, "NOTHING_TO_REASSESS")
        self.assertEqual(self.runs(), [])

    def send_additional(self, period_id):
        import io
        r = self.client.post(f"/api/v1/periods/{period_id}/uploads",
                             data={"submission_kind": "ADDITIONAL_EVIDENCE", "reason": "bank letter received after publication"},
                             files=[("files", ("bank_letter.pdf", io.BytesIO(b"%PDF-1.4 synthetic letter"), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()


# ============================================================================================ cases and AI
class CaseWorkflow(MonthlyCase):
    """Cases on a temporary copy of the SC5A scenario pack (AI jobs use the test mock provider)."""

    def setUp(self):
        super().setUp()
        self.stop_app()
        shutil.copytree(ROOT / "packs" / SC5A_PACK, self.packs_root / SC5A_PACK)
        self.start_app()
        self.pack_before = sha_tree(self.packs_root / SC5A_PACK)
        self.exceptions_before = self.get(f"/api/v1/packs/{SC5A_PACK}/exceptions").json()

    def assert_pack_unchanged(self):
        self.assertEqual(sha_tree(self.packs_root / SC5A_PACK), self.pack_before)
        self.assertEqual(self.get(f"/api/v1/packs/{SC5A_PACK}/exceptions").json(), self.exceptions_before)

    def open_case(self, expect=201):
        r = self.post(f"/api/v1/packs/{SC5A_PACK}/exceptions/{SC5A_EXC}/case")
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def entry(self, case, kind, text, refs=(), expect=201, **extra):
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind=kind, text=text, evidence_refs=list(refs),
                                                                       expected_revision=case["revision"], **extra))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def reload(self, case):
        return self.get(f"/api/v1/cases/{case['case_id']}").json()

    def pack_ref(self):
        return self.svc.packs.load(SC5A_PACK)["evidence_register"]["records"][0]["evidence_id"]

    def test_a_case_is_opened_explicitly_once_per_exception(self):
        self.assertEqual(self.get("/api/v1/cases").json(), [])
        case = self.open_case()
        self.assertEqual((case["status"], case["human_resolution"], case["revision"], case["period_id"]),
                         ("OPEN", "UNRESOLVED", 0, "PER-2026-09"))
        self.assertEqual(case["exception"]["exception_id"], SC5A_EXC)
        again = self.open_case(expect=200)
        self.assertEqual(again["case_id"], case["case_id"])
        self.assertEqual(len(self.get(f"/api/v1/cases?pack_id={SC5A_PACK}").json()), 1)
        self.assertEqual(self.svc.runner.repo.list(), [])  # opening a case starts no AI investigation
        self.assert_pack_unchanged()

    def test_observations_cite_evidence_and_hypotheses_stay_hypotheses(self):
        case = self.open_case()
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="OBSERVATION", text="Bank and ledger differ.",
                                                                       evidence_refs=[], expected_revision=0))
        self.assertEqual((r.status_code, r.json()["code"]), (422, "EVIDENCE_REQUIRED"))
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="OBSERVATION", text="Bank and ledger differ.",
                                                                       evidence_refs=["IN-99:INVENTED"], expected_revision=0))
        self.assertEqual((r.status_code, r.json()["code"]), (422, "INVALID_EVIDENCE_REF"))  # no fabricated evidence
        ref = self.pack_ref()
        obs = self.entry(case, "OBSERVATION", "The bank statement shows the recorded balance.", [ref])
        self.assertEqual((obs["seq"], obs["evidence_refs"]), (1, [ref]))
        case = self.reload(case)
        self.entry(case, "HYPOTHESIS", "A timing difference could explain the gap (not established).")
        case = self.reload(case)
        self.entry(case, "EVIDENCE_GAP", "No bank confirmation for the day after.")
        case = self.reload(case)
        self.entry(case, "EVIDENCE", "Ledger entry for the transfer.", ["IN-08"] if any(
            f["evidence_id"] == "IN-08" for f in self.svc.packs.load(SC5A_PACK)["evidence_register"]["files"]) else [ref])
        case = self.reload(case)
        self.assertEqual([len(case[k]) for k in ("confirmed_observations", "hypotheses", "evidence_gaps", "supporting_evidence")],
                         [1, 1, 1, 1])
        self.assertEqual((case["human_resolution"], case["status"], case["revision"]), ("UNRESOLVED", "OPEN", 4))
        self.assert_pack_unchanged()

    def test_only_an_explicit_human_decision_resolves_or_closes_a_case(self):
        case = self.open_case()
        self.entry(case, "NOTE", "Reviewed the bank statement.")
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="NOTE", text="stale", expected_revision=0))
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CASE_CHANGED"))  # optimistic concurrency
        case = self.reload(case)
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="NOTE", text="Resolve it", expected_revision=1,
                                                                       resolution="EXPLAINED_BY_ANALYST"))
        self.assertEqual((r.status_code, r.json()["code"]), (422, "DECISION_ONLY"))
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="DECISION", text="Decide", expected_revision=1))
        self.assertEqual((r.status_code, r.json()["code"]), (422, "RESOLUTION_REQUIRED"))
        d = self.entry(case, "DECISION", "Explained by the analyst after reviewing the statement.", resolution="EXPLAINED_BY_ANALYST",
                       close=True)
        self.assertEqual(d["details"], {"resolution": "EXPLAINED_BY_ANALYST", "previous_resolution": "UNRESOLVED", "close": True,
                                        "previous_status": "OPEN"})
        case = self.reload(case)
        self.assertEqual((case["status"], case["human_resolution"]), ("CLOSED", "EXPLAINED_BY_ANALYST"))
        r = self.post(f"/api/v1/cases/{case['case_id']}/entries", dict(kind="NOTE", text="late note", expected_revision=case["revision"]))
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CASE_CLOSED"))
        self.entry(case, "DECISION", "Reopened: new evidence expected.", resolution="UNRESOLVED", close=False)
        self.assertEqual(self.reload(case)["status"], "OPEN")
        actions = [a["action"] for a in self.svc.repos.activity.recent(entity_type="case", entity_id=case["case_id"])]
        self.assertEqual(actions.count("CASE_DECISION_RECORDED"), 2)
        self.assert_pack_unchanged()  # the deterministic exception is never changed by the case

    def test_ai_assistance_is_requested_per_case_and_changes_no_status(self):
        case = self.open_case()
        self.provider.investigate("SC5A", SC5A_EXC)
        r = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"note": "please examine", "authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual((job["status"], job["exception_id"]), ("COMPLETED", SC5A_EXC), job)
        case = self.reload(case)
        self.assertEqual(len(case["ai_requests"]), 1)
        self.assertEqual(case["ai_requests"][0]["details"]["job_id"], job["job_id"])
        self.assertEqual([j["job_id"] for j in case["ai_jobs"]], [job["job_id"]])
        published = case["ai_investigations"]["published"]
        self.assertEqual((len(published), published[0]["eligible"]), (1, True))
        findings = self.get(f"/api/v1/investigations/{published[0]['investigation_id']}/findings").json()
        self.assertEqual(findings["exception_resolution"], "NOT_RESOLVED_BY_INVESTIGATION")
        self.assertEqual((case["status"], case["human_resolution"]), ("OPEN", "UNRESOLVED"))  # the AI never resolves
        self.assertEqual(len(self.svc.runner.repo.list()), 1)  # only the requested case was investigated
        self.assert_pack_unchanged()

    def test_duplicate_submission_is_refused_and_a_retry_is_explicit(self):
        case = self.open_case()
        self.provider.investigate("SC5A", SC5A_EXC)
        self.provider.gate = threading.Event()  # hold the first job RUNNING
        first = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"authorization": AI_OK}).json()
        r = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "INVESTIGATION_ACTIVE"))
        self.provider.error = RuntimeError("provider unavailable (test)")
        self.provider.gate.set()
        self.assertEqual(self.wait_job(first["job_id"])["status"], "FAILED")
        self.provider.error, self.provider.gate = None, None
        retry = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"retry_of": first["job_id"], "authorization": AI_OK})
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(self.wait_job(retry.json()["job_id"])["retry_of"], first["job_id"])
        requests = self.reload(case)["ai_requests"]
        self.assertEqual([e["details"]["retry_of"] for e in requests], [None, first["job_id"]])

    def test_ai_needs_a_configured_provider_and_an_open_case(self):
        case = self.open_case()
        from uc042lib.investigation.llm import LLMConfigurationError
        self.svc.investigations.investigator_factory = mock.Mock(side_effect=LLMConfigurationError("not configured (test)"))
        r = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (503, "PROVIDER_NOT_CONFIGURED"))
        self.assertEqual((self.reload(case)["ai_requests"], self.svc.runner.repo.list()), ([], []))
        self.entry(self.reload(case), "DECISION", "Escalated to the safeguarding officer.", resolution="ESCALATED", close=True)
        r = self.post(f"/api/v1/cases/{case['case_id']}/ai-investigation", {"authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "CASE_CLOSED"))


# ============================================================================================ migration (PostgreSQL)
SOURCE_DB = "uc042_test_unify_source"
# The migration target is the configured disposable test database, whatever its name (UC042_TEST_DATABASE_URL).
TARGET_DB = make_url(TEST_DATABASE_URL).database if TEST_DATABASE_URL else None


@unittest.skipUnless(TEST_DATABASE_URL, "UC042_TEST_DATABASE_URL is not set")
class Unification(unittest.TestCase):
    """unify() from a disposable source database (revision 0002, tables in public) into the disposable test database."""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.pool import NullPool
        base = make_url(TEST_DATABASE_URL)
        # CREATE / DROP DATABASE cannot run in a transaction: a separate, unpooled autocommit engine on the same server
        cls.admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
        try:
            with cls.admin.connect() as c:
                c.execute(text(f"DROP DATABASE IF EXISTS {SOURCE_DB}"))
                c.execute(text(f"CREATE DATABASE {SOURCE_DB}"))
        except Exception as e:  # no CREATEDB right: the migration tests cannot run here
            cls.admin.dispose()
            raise unittest.SkipTest(f"cannot create the disposable source database: {type(e).__name__}")
        cls.source_url = base.set(database=SOURCE_DB).render_as_string(hide_password=False)
        cls.demo_before = sha_tree(DEMO)

    @classmethod
    def tearDownClass(cls):
        from sqlalchemy import text
        with cls.admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {SOURCE_DB} WITH (FORCE)"))
        cls.admin.dispose()
        assert sha_tree(DEMO) == cls.demo_before, "a demo_history file changed"

    def setUp(self):
        from alembic import command
        from sqlalchemy import text
        from uc042app.db import alembic_config, make_engine, upgrade
        self.tmp = Path(tempfile.mkdtemp())
        self.roots = make_profile_roots(self.tmp)
        self._profiles = mock.patch.dict(inv_roots.PROFILES, {"test-history": test_profile(self.roots)})
        self._profiles.start()
        # source: revision 0002, emptied
        src = make_engine(self.source_url)
        with src.begin() as c:
            c.execute(text("DROP SCHEMA IF EXISTS audit CASCADE"))
            c.execute(text("DROP SCHEMA IF EXISTS operations CASCADE"))
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        src.dispose()
        command.upgrade(alembic_config(self.source_url), "0002_title_submissions")
        self.src = make_engine(self.source_url)
        self.seed_source()
        # target: the test database at head, emptied, with the operational September
        reset_test_database(TEST_DATABASE_URL)
        upgrade(TEST_DATABASE_URL)
        self.target = make_engine(TEST_DATABASE_URL)
        self.seed_target()
        self.source_before = self.dump(self.src, "public")

    def tearDown(self):
        self.src.dispose()
        reset_test_database(TEST_DATABASE_URL)
        self.target.dispose()
        self._profiles.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- fixtures
    def seed_source(self):
        from sqlalchemy import text
        from uc042app.services.registry import PINNED, fingerprint
        pack = load_pack(FEB_PACK, self.roots["packs"])
        fp = fingerprint(self.roots["investigations"] / FEB_PACK / FEB_EXC / FEB_INV_REGISTERED)
        entry = {"seq": 1, "record_type": "NEW_PUBLICATION", "investigation_id": FEB_INV_REGISTERED, "exception_id": FEB_EXC,
                 "investigation_mode": "tools", **{k: fp[k] for k in PINNED}, "recorded_at": "2026-11-04T05:46:02+00:00",
                 "recorded_by": "demo-reviewer", "verify_published": "OK", "note": ""}
        final = json.loads((self.roots["final_packs"] / FEB_FINAL / "final_pack.json").read_text(encoding="utf-8"))
        rd = final["human_review"]["review_decision_id"]
        rs = "RS-" + "a" * 24
        with self.src.begin() as c:
            ins = lambda sql, **kw: c.execute(text(sql), kw)  # noqa: E731
            ins("INSERT INTO reconciliation_periods VALUES ('PER-2026-02','UC-042',2026,2,'PROCESSED','2026-11-04T11:11:45+05:30',NULL,'','')")
            ins("INSERT INTO reconciliation_periods VALUES ('PER-2026-09','UC-042',2026,9,'EMPTY','2026-11-04T12:38:21+05:30',NULL,'',"
                "'September 2026 Reconciliation Audit')")
            ins("INSERT INTO period_packs VALUES ('PER-2026-02',:p,'POC_SCENARIO','H202602','2026-02',NULL,:h,'2026-11-04T11:11:45+05:30')",
                p=FEB_PACK, h=pack["audit_trail"]["pack_content_sha256"])
            ins("INSERT INTO jobs VALUES ('JOB-" + "b" * 24 + "','INVESTIGATION',:p,:e,'COMPLETED','2026-11-04T05:44:58+00:00',"
                "CAST(:d AS JSONB))", p=FEB_PACK, e=FEB_EXC, d=json.dumps({"job_id": "JOB-" + "b" * 24, "status": "COMPLETED"}))
            ins("INSERT INTO review_sessions VALUES (:r,:p,'GENERATED',5,'2026-11-04T05:46:39+00:00',CAST(:d AS JSONB))",
                r=rs, p=FEB_PACK, d=json.dumps({"review_id": rs}))
            ins("INSERT INTO review_decisions VALUES (:d,:r,1,'2026-11-04T05:47:40+00:00',CAST(:x AS JSONB))", d=rd, r=rs,
                x=json.dumps({"review_decision_id": rd}))
            ins("INSERT INTO previews VALUES ('PV-" + "c" * 24 + "',:r,CAST('{}' AS JSONB),CAST('{}' AS JSONB))", r=rs)
            ins("INSERT INTO final_pack_records VALUES (:d,:r,:p,'GENERATED','2026-11-04T05:47:45+00:00',CAST(:x AS JSONB))", d=rd, r=rs,
                p=FEB_PACK, x=json.dumps({"status": "GENERATED", "final_pack_id": FEB_FINAL, "review_decision_id": rd}))
            ins("INSERT INTO investigation_registry VALUES (1,:i,'NEW_PUBLICATION','2026-11-04T05:46:02+00:00',CAST(:x AS JSONB))",
                i=FEB_INV_REGISTERED, x=json.dumps(entry))
            ins("INSERT INTO activity_events (id,at,actor,action,entity_type,entity_id,details) VALUES "
                "(1,'2026-11-04T11:11:45+05:30','demo-reviewer','PERIOD_REGISTERED_FROM_PACKS','period','PER-2026-02',CAST('{}' AS JSONB)),"
                "(2,'2026-11-04T12:38:21+05:30','demo-reviewer','PERIOD_OPENED','period','PER-2026-09',"
                "CAST('{\"title\": \"September 2026 Reconciliation Audit\"}' AS JSONB))")

    def seed_target(self):
        from sqlalchemy import text
        with self.target.begin() as c:
            c.execute(text("INSERT INTO audit.reconciliation_periods VALUES ('PER-2026-09','UC-042',2026,9,'PROCESSED',"
                           "'2026-11-03T16:14:51+05:30',NULL,'','','')"))
            c.execute(text("INSERT INTO audit.period_packs VALUES ('PER-2026-09',:p,'POC_SCENARIO','S05','scn',NULL,'x',"
                           "'2026-11-03T16:14:51+05:30')"), {"p": S05_PACK})
            c.execute(text("INSERT INTO operations.activity_events (at,actor,action,entity_type,entity_id,details) VALUES "
                           "('2026-11-03T16:14:51+05:30','local-analyst','PERIOD_REGISTERED_FROM_PACKS','period','PER-2026-09',"
                           "CAST('{}' AS JSONB))"))

    @staticmethod
    def dump(engine, schema):
        from sqlalchemy import inspect, text
        with engine.connect() as c:
            names = [t for t in inspect(c).get_table_names(schema=schema) if t != "alembic_version"]
            return {t: sorted(json.dumps(dict(r._mapping), default=str, sort_keys=True)
                              for r in c.execute(text(f"SELECT * FROM {schema}.{t}"))) for t in names}

    def target_state(self):
        return {**self.dump(self.target, "audit"), **self.dump(self.target, "operations")}

    def unify(self, **kw):
        from uc042app.db.unify import unify
        return unify(self.target, SOURCE_DB, "test-history", **kw)

    # ---------------------------------------------------------------- tests
    def test_unification_preserves_identifiers_merges_september_and_keeps_provenance(self):
        from sqlalchemy import text
        report = self.unify(approved_merges=("PER-2026-09",))
        self.assertEqual(report.actions["reconciliation_periods"], {"COPIED": 1, "MERGED": 1})
        self.assertEqual(report.actions["activity_events"], {"RENUMBERED": 2})
        with self.target.connect() as c:
            q = lambda sql: [tuple(r) for r in c.execute(text(sql))]  # noqa: E731
            self.assertEqual(q("SELECT period_id, status, title, storage_profile FROM audit.reconciliation_periods ORDER BY 1"),
                             [("PER-2026-02", "PROCESSED", "", "test-history"),
                              ("PER-2026-09", "PROCESSED", "September 2026 Reconciliation Audit", "")])
            self.assertEqual(q("SELECT period_id, pack_id FROM audit.period_packs ORDER BY 1"),
                             [("PER-2026-02", FEB_PACK), ("PER-2026-09", S05_PACK)])  # both months' pack references kept
            self.assertEqual(q("SELECT seq, investigation_id FROM audit.investigation_registry"), [(1, FEB_INV_REGISTERED)])
            self.assertEqual(q("SELECT job_id FROM operations.jobs"), [("JOB-" + "b" * 24,)])  # identifiers preserved
            acts = q("SELECT id, action, entity_id FROM operations.activity_events ORDER BY id")
            self.assertEqual([a[1:] for a in acts],
                             [("PERIOD_REGISTERED_FROM_PACKS", "PER-2026-09"), ("PERIOD_REGISTERED_FROM_PACKS", "PER-2026-02"),
                              ("PERIOD_OPENED", "PER-2026-09"), ("DATABASE_UNIFIED", report.migration_id)])  # both trails
            prov = q("SELECT source_database, source_table, source_key, target_key, action FROM audit.record_provenance "
                     "WHERE source_table = 'activity_events' ORDER BY source_key")
            self.assertEqual([(p[2], p[4]) for p in prov], [("1", "RENUMBERED"), ("2", "RENUMBERED")])
            self.assertEqual(sorted(p[3] for p in prov), sorted(str(a[0]) for a in acts[1:3]))
            merged = q("SELECT source_database, action, source_row->>'status', source_row->>'title' FROM audit.record_provenance "
                       "WHERE source_table = 'reconciliation_periods' AND target_key = 'PER-2026-09' ORDER BY action")
            self.assertEqual(merged, [(SOURCE_DB, "MERGED", "EMPTY", "September 2026 Reconciliation Audit"),
                                      (TARGET_DB, "MERGE_TARGET", "PROCESSED", "")])
            n = q("SELECT count(*) FROM audit.record_provenance WHERE source_database = :s".replace(":s", f"'{SOURCE_DB}'"))[0][0]
            self.assertEqual(n, 11)  # every source row exactly once (2 periods, 1 pack ref, 6 records, 2 events)
        self.assertEqual(self.dump(self.src, "public"), self.source_before)  # the source is only read

    def test_a_rerun_copies_nothing_twice_and_a_dry_run_writes_nothing(self):
        before = self.target_state()
        dry = self.unify(approved_merges=("PER-2026-09",), dry_run=True)
        self.assertIn("dry run: rolled back, nothing written", dry.notes)
        self.assertEqual(self.target_state(), before)
        self.unify(approved_merges=("PER-2026-09",))
        after = self.target_state()
        again = self.unify(approved_merges=("PER-2026-09",))
        self.assertTrue(all(set(v) == {"ALREADY_MIGRATED"} for v in again.actions.values()), again.actions)
        state = self.target_state()
        self.assertEqual({k: v for k, v in state.items() if k != "activity_events"},
                         {k: v for k, v in after.items() if k != "activity_events"})
        self.assertEqual(len(state["activity_events"]), len(after["activity_events"]) + 1)  # only the second DATABASE_UNIFIED event

    def assert_stopped(self, fragment, **kw):
        from uc042app.db.unify import UnificationStopped
        before = self.target_state()
        with self.assertRaises(UnificationStopped) as e:
            self.unify(**kw)
        self.assertIn(fragment, str(e.exception))
        self.assertEqual(self.target_state(), before)  # nothing written

    def test_an_unapproved_september_collision_stops_the_run(self):
        self.assert_stopped("identifier collision in reconciliation_periods: PER-2026-09")

    def test_an_identifier_collision_with_different_values_stops_the_run(self):
        from sqlalchemy import text
        with self.target.begin() as c:
            c.execute(text("INSERT INTO operations.jobs VALUES ('JOB-" + "b" * 24 + "','PREVIEW','PACK-X','','COMPLETED','x',"
                           "CAST('{}' AS JSONB))"))
        self.assert_stopped("identifier collision in jobs", approved_merges=("PER-2026-09",))

    def test_a_changed_artefact_stops_the_run(self):
        path = self.roots["final_packs"] / FEB_FINAL / "report.html"
        path.write_bytes(path.read_bytes() + b" ")
        self.assert_stopped("artefact verification failed", approved_merges=("PER-2026-09",))

    def test_a_registry_entry_that_no_longer_matches_its_files_stops_the_run(self):
        f = self.roots["investigations"] / FEB_PACK / FEB_EXC / FEB_INV_REGISTERED / "findings.json"
        f.write_bytes(f.read_bytes() + b"\n")
        self.assert_stopped("differs from its registered hashes", approved_merges=("PER-2026-09",))

    def test_a_source_at_another_revision_stops_the_run(self):
        from alembic import command
        from uc042app.db import alembic_config
        command.upgrade(alembic_config(self.source_url), "head")
        self.assert_stopped("expected 0002_title_submissions", approved_merges=("PER-2026-09",))

    def test_foreign_keys_hold_after_the_migration(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        self.unify(approved_merges=("PER-2026-09",))
        for sql in ("INSERT INTO audit.period_packs VALUES ('PER-2031-01','PACK-X','POC_SCENARIO','','',NULL,'x',now())",
                    "INSERT INTO audit.review_decisions VALUES ('RD-x','RS-missing',1,'x',CAST('{}' AS JSONB))",
                    "INSERT INTO operations.exception_cases VALUES ('CASE-x','PER-2031-01','PACK-X','EXC-1','OPEN','UNRESOLVED',0,"
                    "now(),'a',now())"):
            with self.assertRaises(DBAPIError) as e, self.target.begin() as c:
                c.execute(text(sql))
            self.assertIn("23503", str(e.exception))  # foreign_key_violation

    def test_a_rerun_copies_new_source_rows_and_stops_on_a_changed_one(self):
        from sqlalchemy import text
        from uc042app.db.unify import UnificationStopped
        self.unify(approved_merges=("PER-2026-09",))
        with self.src.begin() as c:  # the legacy backend kept running and logged one more event
            c.execute(text("INSERT INTO activity_events (id,at,actor,action,entity_type,entity_id,details) VALUES "
                           "(3,'2026-11-04T13:00:00+05:30','demo-reviewer','PERIOD_RETITLED','period','PER-2026-02',CAST('{}' AS JSONB))"))
        again = self.unify(approved_merges=("PER-2026-09",))
        self.assertEqual(again.actions["activity_events"], {"ALREADY_MIGRATED": 2, "RENUMBERED": 1})
        with self.src.begin() as c:  # an already migrated record changes in the source: never applied silently
            c.execute(text("UPDATE reconciliation_periods SET title = 'Changed later' WHERE period_id = 'PER-2026-02'"))
        before = self.target_state()
        with self.assertRaises(UnificationStopped) as e:
            self.unify(approved_merges=("PER-2026-09",))
        self.assertIn("changed in the source after it was migrated", str(e.exception))
        self.assertEqual(self.target_state(), before)
