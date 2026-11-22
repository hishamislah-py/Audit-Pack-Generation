"""Backend basics: health, local-only access, ID and request validation, error mapping (problem details), CORS,
response serialisation without secrets or paths, configuration guards and the single-process instance lock. Offline.
Run from uc042/: python -m unittest -v"""
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from tests.api_support import ROOT, ApiCase
from tests.final_pack_support import PACK
from uc042app.config import ConfigurationError, Settings
from uc042app.services import Services
from uc042app.storage import InstanceLockError


class Health(ApiCase):
    def test_health_reports_status_without_secrets(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["status"], body["storage"], body["registry"], body["single_process"]), ("ok", True, True, True))
        self.assertEqual(body["analyst_id"], "analyst-1")
        self.assertIsInstance(body["provider_configured"], bool)
        self.assertNotIn("sk-", r.text)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")


class LocalOnly(ApiCase):
    def test_non_loopback_clients_are_refused(self):
        remote = TestClient(self.app, client=("192.168.1.20", 50000))
        r = remote.get("/api/v1/packs")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "LOCAL_ONLY"))
        local = TestClient(self.app, client=("127.0.0.1", 50000))
        self.assertEqual(local.get("/health").status_code, 200)

    def test_no_authentication_or_user_endpoints_exist(self):
        for url in ("/api/v1/auth/login", "/api/v1/users", "/api/v1/admin/investigation-registry/verify"):
            self.assertEqual(self.client.post(url, json={}).status_code, 404, url)
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertFalse([p for p in paths if "auth" in p or "admin" in p or "user" in p])


class ValidationAndErrors(ApiCase):
    def test_invalid_ids_are_rejected_before_storage(self):
        for url in ("/api/v1/packs/..%2F..%2Fetc", "/api/v1/packs/PACK-bad", f"/api/v1/packs/{PACK['S05']}/exceptions/EXC-..",
                    "/api/v1/investigations/INV-nope", "/api/v1/reviews/RS-x", "/api/v1/jobs/1", "/api/v1/final-packs/FAP-x"):
            r = self.get(url)
            self.assertIn(r.status_code, (404, 422), url)
            self.assertEqual(r.headers["content-type"], "application/problem+json", url)
        self.assertEqual(self.get("/api/v1/packs/PACK-bad").json()["code"], "INVALID_ID")

    def test_missing_resources_are_404(self):
        missing_pack = "PACK-ZZ9-PER-2026-09-000000000000"
        for url in (f"/api/v1/packs/{missing_pack}", f"/api/v1/packs/{PACK['S05']}/exceptions/EXC-S05-99",
                    "/api/v1/investigations/INV-EXC-S05-01-000000000000", "/api/v1/reviews/RS-" + "0" * 24,
                    "/api/v1/final-packs/FAP-S05-PER-2026-09-v1-000000000000"):
            r = self.get(url)
            self.assertEqual((r.status_code, r.json()["code"]), (404, "NOT_FOUND"), url)

    def test_request_body_validation(self):
        url = f"/api/v1/packs/{PACK['SC5A']}/exceptions/EXC-SC5A-01/investigations"
        r = self.post(url, {"mode": "fixed"})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "VALIDATION_ERROR"))
        self.assertTrue(r.json()["errors"])
        self.assertEqual(self.post(url, {"mode": "tools", "unexpected": 1}).status_code, 422)

    def test_unexpected_errors_are_generic_500_without_internals(self):
        with mock.patch.object(self.svc.packs, "pack_ids", side_effect=RuntimeError(r"boom at C:\secret\path sk-abcdefgh")):
            r = TestClient(self.app, raise_server_exceptions=False).get("/api/v1/packs")
        self.assertEqual((r.status_code, r.json()["code"]), (500, "INTERNAL_ERROR"))
        self.assertNotIn("secret", r.text)
        self.assertNotIn("sk-", r.text)
        self.assertNotIn("Traceback", r.text)


class PacksAndSerialisation(ApiCase):
    def test_packs_are_listed_verified_and_contain_no_paths(self):
        r = self.get("/api/v1/packs")
        self.assertEqual(r.status_code, 200)
        listed = {p["pack_id"]: p for p in r.json()}
        self.assertEqual(set(listed), set(PACK.values()))
        self.assertTrue(all(p["verified"] for p in listed.values()))
        detail = self.get(f"/api/v1/packs/{PACK['S05']}").json()
        self.assertEqual(detail["summary"]["exceptions"]["total"], 2)
        excs = self.get(f"/api/v1/packs/{PACK['S05']}/exceptions").json()
        self.assertEqual([x["exception_id"] for x in excs], ["EXC-S05-01", "EXC-S05-02"])
        self.assertTrue(all(x["resolution_status"] == "UNRESOLVED" for x in excs))
        one = self.get(f"/api/v1/packs/{PACK['S05']}/exceptions/EXC-S05-01").json()
        self.assertTrue(one["affected_results"])
        self.assertTrue(all(r["result_id"] in one["exception"]["affected_result_ids"] for r in one["affected_results"]))
        for text in (r.text, json.dumps(detail), json.dumps(one)):
            self.assertNotIn(str(ROOT), text)
            self.assertNotIn(str(self.tmp), text)

    def test_no_endpoint_changes_exception_status(self):
        for method in ("put", "patch", "delete"):
            r = getattr(self.client, method)(f"/api/v1/packs/{PACK['S05']}/exceptions/EXC-S05-01")
            self.assertEqual(r.status_code, 405, method)


class Cors(ApiCase):
    def test_only_the_configured_origin_is_allowed(self):
        ok = self.client.options("/api/v1/packs", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://localhost:5173")
        bad = self.client.options("/api/v1/packs", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
        self.assertNotIn("access-control-allow-origin", bad.headers)

    def test_wildcard_origin_is_refused(self):
        with self.assertRaises(ConfigurationError):
            self.settings.with_(cors_origins=("*",)).check()


class Configuration(unittest.TestCase):
    def test_state_dir_must_be_outside_controlled_folders(self):
        for inside in (ROOT / "investigations" / "state", ROOT / "packs" / "x", ROOT / "uc042_dataset" / "s"):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(state_dir=inside)

    def test_analyst_reference_is_configurable(self):
        with mock.patch.dict("os.environ", {"UC042_ANALYST_ID": "jdoe", "UC042_ANALYST_NAME": "J Doe"}):
            s = Settings.from_env()
        self.assertEqual(s.reviewer, {"user_id": "jdoe", "display_name": "J Doe"})
        with mock.patch.dict("os.environ", {"UC042_JOB_WORKERS": "0"}), self.assertRaises(ConfigurationError):
            Settings.from_env()


class SingleProcess(ApiCase):
    def test_a_second_backend_on_the_same_state_is_refused(self):
        other = Services(self.settings)
        with self.assertRaises(InstanceLockError):
            other.start()


if __name__ == "__main__":
    unittest.main()
