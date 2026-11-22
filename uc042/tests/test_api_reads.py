"""Read-only endpoints added for the React frontend (Phase 3): pack reconciliation tables, the source-file register and
the review-session list. They only read the pack or the review store; listing reviews never opens or changes a session.
Offline. Run from uc042/: python -m unittest -v"""
import json
import threading
import unittest

from tests.api_support import ROOT, ApiCase
from tests.final_pack_support import PACK
from uc042lib.final_pack.sources import load_pack


class PackReads(ApiCase):
    def test_reconciliation_tables_are_copied_from_the_pack(self):
        r = self.get(f"/api/v1/packs/{PACK['S05']}/reconciliation")
        self.assertEqual(r.status_code, 200)
        body, pack = r.json(), load_pack(PACK["S05"])
        self.assertEqual(body["internal_by_currency_day"], pack["reconciliation_summary"]["internal_by_currency_day"])
        self.assertEqual(body["external_by_account_day"], pack["reconciliation_summary"]["external_by_account_day"])
        self.assertEqual(body["currency_scope"], ["EUR", "GBP"])
        self.assertTrue(any(row["difference"] == "-812.40" for row in body["external_by_account_day"]))

    def test_sources_and_missing_evidence(self):
        s02 = self.get(f"/api/v1/packs/{PACK['S02']}/sources").json()
        self.assertTrue(all(f["source_file"].startswith("source_data/") or f["source_file"].startswith("supporting_documents/")
                            for f in s02["files"] if f.get("source_file")))
        self.assertEqual(s02["missing_evidence"]["items"][0]["item_id"], "MISS-01")
        self.assertNotIn(str(ROOT), json.dumps(s02))
        self.assertEqual(self.get("/api/v1/packs/PACK-bad/sources").json()["code"], "INVALID_ID")


class ReviewList(ApiCase):
    def test_listing_is_read_only_and_filters(self):
        self.assertEqual(self.get("/api/v1/reviews").json(), [])
        self.assertEqual(list((self.settings.state_dir / "reviews").glob("RS-*")), [])  # listing created nothing
        s = self.post(f"/api/v1/packs/{PACK['S01']}/reviews").json()
        rows = self.get("/api/v1/reviews").json()
        self.assertEqual([(r["review_id"], r["status"], r["has_preview"], r["last_decision"]) for r in rows],
                         [(s["review_id"], "OPEN", False, None)])
        self.assertEqual(self.get(f"/api/v1/reviews?pack_id={PACK['S05']}").json(), [])
        self.assertEqual(len(self.get("/api/v1/reviews?status=OPEN").json()), 1)
        self.assertEqual(self.get("/api/v1/reviews?status=BOGUS").status_code, 422)


class Caching(ApiCase):
    def test_cached_eligibility_is_invalidated_by_any_artefact_or_registry_change(self):
        from tests.api_support import copy_published
        src = next((ROOT / "investigations").glob("PACK-S05-*/EXC-S05-01/INV-EXC-S05-01-65bd05498b9e"))
        d = copy_published(src, self.inv_root)
        url = f"/api/v1/packs/{PACK['S05']}/exceptions/EXC-S05-01/investigations"
        row = lambda: next(r for r in self.get(url).json()["published"] if r["investigation_id"] == d.name)  # noqa: E731
        self.assertFalse(row()["eligible"])  # unregistered
        self.svc.registry.import_legacy(d, self.svc.packs.load(PACK["S05"]), "analyst-1")
        self.assertTrue(row()["eligible"])  # registry change seen
        self.assertTrue(row()["eligible"])  # cached
        f = d / "findings.json"
        f.write_bytes(f.read_bytes().replace(b"}", b"} ", 1))
        self.assertFalse(row()["eligible"])  # artefact change seen

    def test_cached_pack_is_a_private_copy(self):
        a = self.svc.packs.load(PACK["SC2"])
        a["metadata"]["pack_id"] = "mutated"
        self.assertEqual(self.svc.packs.load(PACK["SC2"])["metadata"]["pack_id"], PACK["SC2"])


class ConcurrentPolling(ApiCase):
    def test_polling_a_job_while_it_is_rewritten_never_fails(self):
        """Regression (found with the React frontend): on Windows, reading a job file while the runner os.replace()s it
        raised PermissionError and GET /jobs/{id} returned 500. Reads now share the repository lock."""
        job = self.svc.runner.create("INVESTIGATION", PACK["SC5A"], "analyst-1", "EXC-SC5A-01")
        stop = threading.Event()

        def writer():
            n = 0
            while not stop.is_set():
                n += 1
                self.svc.repos.jobs.update(job["job_id"], {"result": {"n": n}})
        t = threading.Thread(target=writer)
        t.start()
        try:
            codes = [self.get(f"/api/v1/jobs/{job['job_id']}").status_code for _ in range(150)]
        finally:
            stop.set()
            t.join()
        self.assertEqual(set(codes), {200})


if __name__ == "__main__":
    unittest.main()
