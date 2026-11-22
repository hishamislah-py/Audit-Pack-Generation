"""Test package. Loads uc042/.env first (as the investigation layer does on import), then removes the operational
database URL so that no test can reach the analyst's PostgreSQL database by accident. Tests that exercise PostgreSQL use
UC042_TEST_DATABASE_URL (a separate, disposable database) explicitly.

Published final packs: the test run's primary final-packs root is a fresh temporary directory (set BEFORE the library
reads it, and overriding any deployment value from .env), so no test can write into the deployment's final-pack storage
or into the repository. It is removed when the test process ends."""
import atexit
import os
import shutil
import tempfile

TEST_FINAL_PACKS_ROOT = tempfile.mkdtemp(prefix="uc042_p10_test_final_packs-")
os.environ["UC042_FINAL_PACKS_ROOT"] = TEST_FINAL_PACKS_ROOT
atexit.register(shutil.rmtree, TEST_FINAL_PACKS_ROOT, True)

from uc042lib.investigation import config as _inv_config  # noqa: E402,F401  (loads uc042/.env without overriding)

TEST_DATABASE_URL = os.environ.get("UC042_TEST_DATABASE_URL", "").strip()
if TEST_DATABASE_URL and TEST_DATABASE_URL == os.environ.get("UC042_DATABASE_URL", "").strip():
    raise RuntimeError("UC042_TEST_DATABASE_URL must name a separate, disposable database, not UC042_DATABASE_URL")
os.environ["UC042_DATABASE_URL"] = ""
