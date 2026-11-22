"""Investigation publication registry: new registrations, legacy baseline import, hash verification and detection of
changed artefacts (findings, packet, folder name, recomputed ID, wrong pack ID/hash), registry damage (fail closed) and
refusal of failed or simulated investigations. Real artefacts are only ever COPIED into temporary folders. Offline.
Run from uc042/: python -m unittest -v"""
import hashlib
import json
import unittest

from tests.api_support import ROOT, ApiCase, copy_published
from tests.final_pack_support import OFFLINE, PACK, sha_tree
from uc042app.services.registry import LEGACY_BASELINE_IMPORT, NEW_PUBLICATION, RegistrationRefused
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.persistence import investigation_id_from_findings, verify_published

REAL_S05_14 = next((ROOT / "investigations").glob("PACK-S05-*/EXC-S05-01/INV-EXC-S05-01-65bd05498b9e"))
REAL_S02_12 = next((ROOT / "investigations").glob("PACK-S02-*/EXC-S02-01/INV-EXC-S02-01-764aed67bb83"))


def rewrite_findings(d, mutate, reid=False):
    """Edit findings.json; with reid, also recompute the ID and rename the folder (a deliberate forgery)."""
    f = json.loads((d / "findings.json").read_text(encoding="utf-8"))
    mutate(f)
    if reid:
        f["investigation_id"] = investigation_id_from_findings(f, f["evidence_packet_sha256"])
    (d / "findings.json").write_text(json.dumps(f, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if reid:
        nd = d.parent / f["investigation_id"]
        d.rename(nd)
        return nd
    return d


class Registry(ApiCase):
    @classmethod
    def setUpClass(cls):
        cls.real_before = sha_tree(ROOT / "investigations")

    @classmethod
    def tearDownClass(cls):
        assert sha_tree(ROOT / "investigations") == cls.real_before, "a real investigation artefact changed"

    def registry_file(self):
        return self.settings.state_dir / "registry" / "investigation_registry.json"

    def eligible(self, scenario, exception_id, inv_id):
        rows = self.get(f"/api/v1/packs/{PACK[scenario]}/exceptions/{exception_id}/investigations").json()["published"]
        return next(r for r in rows if r["investigation_id"] == inv_id)

    def import_copy(self, src):
        d = copy_published(src, self.inv_root)
        entry, created = self.svc.registry.import_legacy(d, self.svc.packs.load(d.parent.parent.name), "analyst-1")
        return d, entry, created

    # ---------------------------------------------------------------- registration
    def test_new_investigation_is_registered_and_eligible(self):
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        self.assertEqual(job["status"], "COMPLETED", job)
        inv_id = job["result"]["investigation_id"]
        entry = self.svc.registry.entry_for(inv_id)
        self.assertEqual((entry["record_type"], entry["seq"], entry["recorded_by"]), (NEW_PUBLICATION, 1, "analyst-1"))
        d = next(self.inv_root.rglob(inv_id))
        self.assertEqual(entry["findings_sha256"], hashlib.sha256((d / "findings.json").read_bytes()).hexdigest())
        self.assertEqual(entry["evidence_packet_file_sha256"], hashlib.sha256((d / "evidence_packet.json").read_bytes()).hexdigest())
        self.assertEqual(entry["findings_schema_version"], "uc042-investigation-findings/1.4")
        self.assertTrue(entry["prompt_version"].endswith("-tools"))
        self.assertTrue(entry["recorded_at"])
        self.assertTrue(self.eligible("SC5A", "EXC-SC5A-01", inv_id)["eligible"])
        v = self.get(f"/api/v1/investigations/{inv_id}/verify").json()
        self.assertEqual((v["artefact_verified"], v["registry_verified"], v["eligible"]), (True, True, True))

    def test_unregistered_artefact_is_not_eligible_even_though_it_verifies(self):
        d = copy_published(REAL_S05_14, self.inv_root)
        self.assertEqual(verify_published(d), [])
        row = self.eligible("S05", "EXC-S05-01", d.name)
        self.assertEqual((row["library_eligible"], row["eligible"]), (True, False))
        self.assertIn("not in the investigation publication registry", " ".join(row["ineligible_reasons"]))

    def test_legacy_baseline_import_is_labelled_and_never_rewrites_the_artefact(self):
        for src in (REAL_S05_14, REAL_S02_12):
            copy_published(src, self.inv_root)
        copied = sha_tree(self.inv_root)
        for d in sorted(self.inv_root.glob("PACK-*/*/INV-*")):
            entry, created = self.svc.registry.import_legacy(d, self.svc.packs.load(d.parent.parent.name), "analyst-1")
            self.assertTrue(created)
            self.assertEqual(entry["record_type"], LEGACY_BASELINE_IMPORT)
            self.assertIn("does not prove the contents", entry["note"])
        self.assertEqual(sha_tree(self.inv_root), copied)  # nothing rewritten
        self.assertTrue(self.eligible("S05", "EXC-S05-01", REAL_S05_14.name)["eligible"])  # schema 1.4
        self.assertTrue(self.eligible("S02", "EXC-S02-01", REAL_S02_12.name)["eligible"])  # schema 1.2 (historical ID inputs)
        _, again = self.svc.registry.import_legacy(next(self.inv_root.rglob(REAL_S02_12.name)), self.svc.packs.load(PACK["S02"]), "analyst-1")
        self.assertFalse(again)  # idempotent: no duplicate entry
        self.assertEqual(len(self.svc.registry.entries()), 2)

    def test_legacy_import_keeps_current_rule_failures_ineligible(self):
        src = next((ROOT / "investigations").glob("PACK-SC5A-*/EXC-SC5A-01/INV-*"))
        d, _, _ = self.import_copy(src)
        row = self.eligible("SC5A", "EXC-SC5A-01", d.name)
        self.assertFalse(row["eligible"])
        self.assertIn("C-01", " ".join(row["ineligible_reasons"]))

    # ---------------------------------------------------------------- changed artefacts
    def test_changed_findings_file(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        rewrite_findings(d, lambda f: f.update(investigation_summary=f["investigation_summary"] + " (altered)"))
        row = self.eligible("S05", "EXC-S05-01", d.name)
        self.assertFalse(row["eligible"])
        self.assertIn("findings_sha256 differs", " ".join(row["ineligible_reasons"]))

    def test_changed_evidence_packet(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        p = d / "evidence_packet.json"
        p.write_bytes(p.read_bytes().replace(b"812.40", b"812.41", 1))
        self.assertIn("evidence_packet_file_sha256 differs", " ".join(self.eligible("S05", "EXC-S05-01", d.name)["ineligible_reasons"]))

    def test_recomputed_id_after_tampering_is_caught_by_the_registry(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        forged = rewrite_findings(d, lambda f: f.update(investigation_summary=f["investigation_summary"] + " (forged)"), reid=True)
        self.assertEqual(verify_published(forged), [])  # the limitation from report 07: internally consistent
        row = self.eligible("S05", "EXC-S05-01", forged.name)
        self.assertEqual((row["library_eligible"], row["eligible"]), (True, False))
        self.assertIn("not in the investigation publication registry", " ".join(row["ineligible_reasons"]))

    def test_modified_folder_name(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        renamed = d.parent / "INV-EXC-S05-01-0123456789ab"
        d.rename(renamed)
        v = self.get(f"/api/v1/investigations/{renamed.name}/verify").json()
        self.assertEqual((v["artefact_verified"], v["eligible"]), (False, False))

    def test_wrong_pack_id_or_hash(self):
        d = copy_published(REAL_S05_14, self.inv_root)
        with self.assertRaises(RegistrationRefused):
            self.svc.registry.import_legacy(d, self.svc.packs.load(PACK["S02"]), "analyst-1")
        d2, _, _ = self.import_copy(REAL_S02_12)
        forged = rewrite_findings(d2, lambda f: f.update(pack_content_sha256="0" * 64), reid=True)
        v = self.get(f"/api/v1/investigations/{forged.name}/verify").json()
        self.assertFalse(v["eligible"])
        self.assertTrue(any("different pack" in r for r in v["ineligible_reasons"]))

    def test_changed_registry_entry_no_longer_matches_the_files(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        data = json.loads(self.registry_file().read_text(encoding="utf-8"))
        data["entries"][0]["findings_sha256"] = "f" * 64
        self.registry_file().write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("findings_sha256 differs", " ".join(self.eligible("S05", "EXC-S05-01", d.name)["ineligible_reasons"]))

    def test_damaged_registry_fails_closed(self):
        d, _, _ = self.import_copy(REAL_S05_14)
        self.registry_file().write_text("{not json", encoding="utf-8")
        row = self.eligible("S05", "EXC-S05-01", d.name)
        self.assertFalse(row["eligible"])
        self.assertIn("registry is damaged", " ".join(row["ineligible_reasons"]))
        self.assertEqual(self.client.get("/health").json()["status"], "degraded")
        self.registry_file().write_text(json.dumps({"entries": [{"investigation_id": d.name}]}), encoding="utf-8")
        self.assertTrue(self.svc.registry.problems())  # malformed entry

    def test_registry_writes_are_atomic_whole_files(self):
        self.import_copy(REAL_S05_14)
        self.import_copy(REAL_S02_12)
        data = json.loads(self.registry_file().read_text(encoding="utf-8"))
        self.assertEqual([e["seq"] for e in data["entries"]], [1, 2])
        self.assertEqual(list(self.registry_file().parent.glob(".tmp-*")), [])  # no staging leftovers

    # ---------------------------------------------------------------- refusals
    def test_simulated_and_failed_investigations_are_never_registered(self):
        s = run_investigation(PACK["SC5A"], "EXC-SC5A-01", OFFLINE, investigations_root=self.inv_root)
        self.assertEqual(s["persist_outcome"], "PUBLISHED")  # the library publishes simulated output (marked simulated)
        with self.assertRaisesRegex(RegistrationRefused, "simulated"):
            self.svc.registry.register_new(s["artefact_path"], self.svc.packs.load(PACK["SC5A"]), "analyst-1")
        self.provider.error = RuntimeError("provider exploded")
        job = self.run_investigation_job("SC5A", "EXC-SC5A-02")
        self.assertEqual(job["status"], "FAILED")
        self.assertFalse(job["result"]["registered"])
        self.assertEqual(self.svc.registry.entries(), [])

    def test_registry_survives_restart(self):
        self.import_copy(REAL_S05_14)
        self.restart()
        self.assertEqual(len(self.svc.registry.entries()), 1)
        self.assertTrue(self.eligible("S05", "EXC-S05-01", REAL_S05_14.name)["eligible"])


if __name__ == "__main__":
    unittest.main()
