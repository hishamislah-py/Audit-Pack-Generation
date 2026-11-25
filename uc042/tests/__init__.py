"""Test package. Loads uc042/.env first (as the investigation layer does on import), then removes the operational
database URL so that no test can reach the analyst's PostgreSQL database by accident. Tests that exercise PostgreSQL use
UC042_TEST_DATABASE_URL (a separate, disposable database) explicitly."""
import os

from uc042lib.investigation import config as _inv_config  # noqa: F401  (loads uc042/.env without overriding)

TEST_DATABASE_URL = os.environ.get("UC042_TEST_DATABASE_URL", "").strip()
if TEST_DATABASE_URL and TEST_DATABASE_URL == os.environ.get("UC042_DATABASE_URL", "").strip():
    raise RuntimeError("UC042_TEST_DATABASE_URL must name a separate, disposable database, not UC042_DATABASE_URL")
os.environ["UC042_DATABASE_URL"] = ""
