"""Primary final-pack storage outside the source repository (B6): the default location, the backend's refusal of a root
inside the repository, publication and verification from the configured external directory, and the historical-demo
profile keeping its own location. Offline. Run from uc042/: python -m unittest tests.test_runtime_storage -v"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import TEST_FINAL_PACKS_ROOT
from tests.api_support import ROOT
from uc042app.config import ConfigurationError, Settings
from uc042lib import runtime_paths
from uc042lib.investigation import roots


class DefaultLocation(unittest.TestCase):
    def test_default_is_the_per_user_data_directory_without_a_hard_coded_user(self):
        with mock.patch.dict(os.environ, {"UC042_FINAL_PACKS_ROOT": "", "LOCALAPPDATA": r"D:\Data\Local"}):
            self.assertEqual(runtime_paths.default_final_packs_root(), Path(r"D:\Data\Local\UC042\final_packs").resolve())
        with mock.patch.dict(os.environ, {"UC042_FINAL_PACKS_ROOT": "", "LOCALAPPDATA": "", "XDG_DATA_HOME": "/srv/data"}):
            self.assertEqual(runtime_paths.default_final_packs_root(), Path("/srv/data/uc042/final_packs").resolve())
        self.assertNotIn("artlptp263user", Path(runtime_paths.__file__).read_text(encoding="utf-8"))

    def test_configured_value_wins_and_the_test_run_uses_a_temporary_directory(self):
        self.assertEqual(runtime_paths.default_final_packs_root(), Path(TEST_FINAL_PACKS_ROOT).resolve())
        self.assertFalse(runtime_paths.inside_project(TEST_FINAL_PACKS_ROOT))
        self.assertEqual(roots.PROFILES["september"].final_packs_root, Path(TEST_FINAL_PACKS_ROOT).resolve())
        self.assertEqual(roots.PROFILES["historical-demo"].final_packs_root, ROOT / "demo_history" / "final_packs")  # unchanged


class BackendConfiguration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_default_to_the_configured_external_root(self):
        s = Settings.from_env(state_dir=self.tmp / "state")
        self.assertEqual(s.final_packs_root, Path(TEST_FINAL_PACKS_ROOT).resolve())

    def test_a_root_inside_the_repository_stops_the_backend(self):
        for inside in (ROOT / "final_packs", ROOT / "docs" / "packs_out"):
            with self.assertRaises(ConfigurationError) as e:
                Settings.from_env(state_dir=self.tmp / "state", final_packs_root=inside)
            self.assertIn("outside the source repository", str(e.exception))
        with mock.patch.dict(os.environ, {"UC042_FINAL_PACKS_ROOT": str(ROOT / "final_packs")}):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(state_dir=self.tmp / "state")


class PublishAndVerifyExternally(unittest.TestCase):
    def test_library_default_publishes_outside_the_repository_and_verifies(self):
        from tests.final_pack_support import PACK, make_investigation, review_for, summary_investigator
        from uc042lib.final_pack import (GenerationInfo, assemble_final_pack, build_review_snapshot, default_selections,
                                         generate_closing_summary, list_final_packs, load_pack, publish_final_pack,
                                         verify_final_pack)
        tmp = Path(tempfile.mkdtemp())
        external = tmp / "external_final_packs"
        try:
            with mock.patch.dict(os.environ, {"UC042_FINAL_PACKS_ROOT": str(external)}):
                inv_root = tmp / "investigations"
                make_investigation("SC5A", "EXC-SC5A-01", inv_root)
                snap = build_review_snapshot(PACK["SC5A"], default_selections(load_pack(PACK["SC5A"]), inv_root), investigations_root=inv_root)
                summary = generate_closing_summary(snap, summary_investigator(snap)[0])
                final = assemble_final_pack(snap, summary, review_for(snap, summary), GenerationInfo())
                path = publish_final_pack(final)  # no root: the configured external location (created when needed)
                self.assertEqual(path.parent, external.resolve())
                self.assertEqual(verify_final_pack(path), [])
                self.assertEqual([m["final_pack_id"] for m in list_final_packs()], [final["metadata"]["final_pack_id"]])
            self.assertFalse((ROOT / "final_packs").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
