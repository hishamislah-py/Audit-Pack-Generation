"""Phase B: GET /api/v1/packs/{pack_id}/controls – the control register as the engine recorded it (read-only, never
recalculated), with the exceptions each check's failures belong to. Offline."""
import unittest

from tests.api_support import ApiCase
from tests.final_pack_support import PACK
from uc042lib.final_pack.sources import load_pack


class PackControls(ApiCase):
    def test_counts_equal_the_packs_own_totals_and_failures_map_to_exceptions(self):
        for key in ("S05", "SC2", "S01"):
            r = self.get(f"/api/v1/packs/{PACK[key]}/controls")
            self.assertEqual(r.status_code, 200, key)
            body, pack = r.json(), load_pack(PACK[key])
            totals = {}
            for c in body["checks"]:
                for k, v in c["result_counts"].items():
                    totals[k] = totals.get(k, 0) + v
            self.assertEqual(totals, pack["executive_summary"]["control_outcomes"]["by_outcome"], key)
            self.assertEqual([c["check_id"] for c in body["checks"]], [c["check_id"] for c in pack["control_register"]], key)
            exc_ids = {x["exception_id"] for x in pack["exception_register"]["exceptions"]}
            for c in body["checks"]:
                self.assertTrue(set(c["exception_ids"]) <= exc_ids, key)
                if c["result_counts"].get("FAIL") and exc_ids:
                    self.assertTrue(c["exception_ids"], f"{key} {c['check_id']}: failures belong to an exception")

    def test_invalid_pack(self):
        self.assertEqual(self.get("/api/v1/packs/PACK-bad/controls").json()["code"], "INVALID_ID")


if __name__ == "__main__":
    unittest.main()
