"""Shared helpers for the backend (uc042app) tests (not a test module). Every test app runs on temporary state,
investigations and final-pack folders; the real packs/ folder is only read. The AI provider is the real
OpenAIInvestigator with its HTTP layer mocked (tests/final_pack_support.py), so no live call is possible:
investigator_from_env is patched to fail if anything reaches it."""
import json
import logging
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tests import TEST_DATABASE_URL
from tests.final_pack_support import PACK, investigation_output, openai_investigator, raw, summary_output
from uc042app.api.main import create_app
from uc042app.config import Settings
from uc042lib.final_pack.model import ClosingSummaryOutput

ROOT = Path(__file__).resolve().parent.parent
_log = logging.getLogger("uc042app")  # expected failures are logged by the backend; keep test output clean
_log.addHandler(logging.NullHandler())
_log.propagate = False


# The analyst's explicit authorisation of a paid AI operation (phase 8): every request that would start a model call
# carries it. Tests of the authorisation gate itself use other values.
AI_OK = {"confirmed": True}


class MockProvider:
    """Answers investigation requests with `output` (or raises `error`) and closing-summary requests with a valid summary
    derived from the request's own structured input (or raises `summary_error`). `gate`, when set, blocks investigation
    calls until released (to hold a job RUNNING)."""

    def __init__(self):
        self.output, self.error, self.summary_error, self.gate = None, None, None, None
        self.calls = {"investigation": 0, "summary": 0}

    def respond(self, kw):
        if kw.get("text_format") is ClosingSummaryOutput:
            self.calls["summary"] += 1
            if self.summary_error:
                raise self.summary_error
            content = kw["input"][0]["content"]
            data = json.loads(content.split("<audit_pack_input>\n", 1)[1].rsplit("\n</audit_pack_input>", 1)[0])
            return raw(summary_output(data))
        self.calls["investigation"] += 1
        if self.gate is not None:
            self.gate.wait(30)
        if self.error:
            raise self.error
        return raw(self.output)

    def factory(self):
        return openai_investigator(self.respond)

    def investigate(self, scenario, exception_id, edit=None):
        self.output = investigation_output(scenario, exception_id, edit)


# Application-state backend for the API tests: "file" (default), "sqlite" (a temporary SQLite file) or "postgres"
# (UC042_TEST_DATABASE_URL, emptied before every test). The same tests then cover every repository implementation.
TEST_REPOSITORIES = os.environ.get("UC042_TEST_REPOSITORIES", "file").strip().lower() or "file"
_PG_READY = []


def test_database_url(tmp):
    if TEST_REPOSITORIES == "file":
        return None
    if TEST_REPOSITORIES == "sqlite":
        return f"sqlite:///{(Path(tmp) / 'state.db').as_posix()}"
    if TEST_REPOSITORIES == "postgres":
        if not TEST_DATABASE_URL:
            raise unittest.SkipTest("UC042_TEST_DATABASE_URL is not set")
        reset_test_database(TEST_DATABASE_URL)
        return TEST_DATABASE_URL
    raise ValueError(f"UC042_TEST_REPOSITORIES={TEST_REPOSITORIES!r}: use file, sqlite or postgres")


def reset_test_database(url):
    """Migrate the disposable test database once per process, then empty every table (never the operational one)."""
    from sqlalchemy import text
    from uc042app.db import make_engine, upgrade
    from uc042app.db.models import Base
    if not _PG_READY:
        upgrade(url)
        _PG_READY.append(True)
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE " + ", ".join(t.fullname for t in Base.metadata.sorted_tables) + " CASCADE"))
    finally:
        engine.dispose()


def no_live_provider():
    raise AssertionError("investigator_from_env must not be reached in offline tests")


class ApiCase(unittest.TestCase):
    """A fresh backend per test on temporary folders (no authentication in this local POC)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inv_root = self.tmp / "investigations"
        self.inv_root.mkdir()
        self.provider = MockProvider()
        self._live_guards = [mock.patch(f"{m}.investigator_from_env", side_effect=no_live_provider)
                             for m in ("uc042lib.investigation.llm", "uc042lib.final_pack.summary", "uc042app.services")]
        for g in self._live_guards:
            g.start()
        self.settings = Settings.from_env(state_dir=self.tmp / "state", investigations_root=self.inv_root,
                                          final_packs_root=self.tmp / "final_packs", packs_root=ROOT / "packs",
                                          cors_origins=("http://localhost:5173",), analyst_id="analyst-1",
                                          analyst_name="Test Analyst", database_url=test_database_url(self.tmp))
        self.start_app()

    def start_app(self):
        self.app = create_app(self.settings, investigator_factory=self.provider.factory)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.svc = self.app.state.services

    def stop_app(self):
        self.client.__exit__(None, None, None)

    def restart(self):
        self.stop_app()
        self.start_app()

    def tearDown(self):
        if self.provider.gate is not None:
            self.provider.gate.set()
        self.stop_app()
        for g in self._live_guards:
            g.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def post(self, url, body=None):
        return self.client.post(url, json=body if body is not None else {})

    def patch(self, url, body):
        return self.client.patch(url, json=body)

    def get(self, url):
        return self.client.get(url)

    def wait_job(self, job_id, timeout=60):
        self.svc.runner.wait(job_id, timeout)
        return self.get(f"/api/v1/jobs/{job_id}").json()

    def run_investigation_job(self, scenario, exception_id, edit=None):
        """Start a V2 tools-mode job through the API and wait for it; returns the finished job."""
        self.provider.investigate(scenario, exception_id, edit)
        r = self.post(f"/api/v1/packs/{PACK[scenario]}/exceptions/{exception_id}/investigations", {"mode": "tools", "authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        return self.wait_job(r.json()["job_id"])

    def preview(self, review_id):
        r = self.post(f"/api/v1/reviews/{review_id}/preview", {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        job = self.wait_job(r.json()["job_id"])
        self.assertEqual(job["status"], "COMPLETED", job)
        return self.get(f"/api/v1/reviews/{review_id}").json()


def copy_published(src_dir, dst_root):
    """Copy a real published investigation into a temporary investigations root (never touching the original)."""
    src = Path(src_dir)
    dst = Path(dst_root) / src.parent.parent.name / src.parent.name / src.name
    shutil.copytree(src, dst)
    return dst


def gate():
    return threading.Event()
