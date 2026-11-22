"""Registry maintenance CLI (uc042app.admin): legacy baseline import (dry run, real, idempotent; on copies only) and
registry verification; the CLI shares the backend's instance lock. Offline. Run from uc042/: python -m unittest -v"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.api_support import ROOT, copy_published
from tests.final_pack_support import sha_tree
from uc042app import admin
from uc042app.config import Settings
from uc042app.services import Services
from uc042app.storage import InstanceLockError


class AdminCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"UC042_APP_STATE_DIR": str(self.tmp / "state"),
                                                 "UC042_INVESTIGATIONS_ROOT": str(self.tmp / "investigations"),
                                                 "UC042_FINAL_PACKS_ROOT": str(self.tmp / "fp")})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out):
            try:
                admin.main(list(argv))
            except SystemExit as e:
                code = e.code or 0
        return out.getvalue(), code

    def test_legacy_import_and_verification(self):
        real = ROOT / "investigations"
        before = sha_tree(real)
        for src in real.glob("PACK-S0*/EXC-*/INV-*"):
            copy_published(src, self.tmp / "investigations")
        dry, _ = self.run_cli("import-legacy-investigations", "--dry-run")
        self.assertIn("would import", dry)
        out, _ = self.run_cli("import-legacy-investigations")
        self.assertEqual(out.count("imported as LEGACY_BASELINE_IMPORT"), 4)  # all four verify; current-rule failures stay ineligible
        again, _ = self.run_cli("import-legacy-investigations")
        self.assertEqual(again.count("already registered"), 4)
        report, code = self.run_cli("verify-registry")
        self.assertEqual(code, 0, report)
        self.assertIn("4 entries; all verified", report)
        changed = next((self.tmp / "investigations").rglob("findings.json"))
        changed.write_bytes(changed.read_bytes().replace(b"}", b"} ", 1))
        report, code = self.run_cli("verify-registry")
        self.assertEqual(code, 1)
        self.assertIn("findings_sha256 differs", report)
        self.assertEqual(sha_tree(real), before)

    def test_cli_refuses_while_the_backend_holds_the_state(self):
        svc = Services(Settings.from_env()).start()
        try:
            with self.assertRaises(InstanceLockError):
                self.run_cli("verify-registry")
        finally:
            svc.stop()


if __name__ == "__main__":
    unittest.main()
