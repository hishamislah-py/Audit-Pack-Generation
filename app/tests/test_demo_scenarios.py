"""Demo scenarios (server --demo-scenarios): the catalogue, loading through the normal registration operation, sha256
integrity of the scenario ZIP, repeatable loads, and the read-only answer-key comparison. Built on a temporary
scenario folder made from the test ZIP (the real p10/RINGFENCE_DEMO_TEST_DATA folder is never written)."""
import hashlib
import json

from smartparser.webapp.demo import DemoScenarios
from smartparser.webapp.server import App

from .test_ringfence_cases import ctx_for, make_zip, settle


def H(app, method, path, body=None):
    s, ctype, data = app.handle(method, path, {"X-Smartparser-Client": "webapp"} if method == "POST" else {},
                                json.dumps(body or {}).encode() if method == "POST" else b"")
    return s, json.loads(data) if ctype.startswith("application/json") else data


def folder(tmp_path, data: bytes, sid="RF-DEMO-01", customer="Demo Clean Ltd", period="2026-09"):
    d = tmp_path / "demo" / "scenario_1_clean"
    d.mkdir(parents=True)
    (d / "Demo_Clean.zip").write_bytes(data)
    (d / "scenario.json").write_text(json.dumps({
        "scenario_id": sid, "customer_name": customer, "reporting_period": period,
        "zip": {"file": "Demo_Clean.zip", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        "expected_outcome": {"case_status": "CLEAN", "fail": 0, "insufficient_evidence": 0, "exceptions": 0}}))
    (d / "expected_outcome.json").write_text(json.dumps({"source": "test", "expected_case_status": "CLEAN",
                                                         "expected_counts": {"FAIL": 0}, "expected_exception_count": 0}))
    return tmp_path / "demo"


def test_disabled_without_flag(tmp_path):
    app = App(ctx_for(tmp_path / "ws"))
    s, b = H(app, "GET", "/api/demo/scenarios")
    assert (s, b["error"]) == (404, "DEMO_DISABLED")
    assert H(app, "GET", "/api/app")[1]["demo_scenarios"] is False


def test_catalogue_load_repeat_and_verification(tmp_path):
    data = make_zip()
    ctx = ctx_for(tmp_path / "ws")
    ctx.demo = DemoScenarios(folder(tmp_path, data))
    app = App(ctx)
    assert H(app, "GET", "/api/app")[1]["demo_scenarios"] is True
    s, cat = H(app, "GET", "/api/demo/scenarios")
    assert s == 200 and [x["scenario_id"] for x in cat["scenarios"]] == ["RF-DEMO-01"]
    sc = cat["scenarios"][0]
    assert (sc["customer_name"], sc["reporting_period"], sc["zip"]["present"], sc["cases"]) == ("Demo Clean Ltd", "2026-09", True, [])
    # load = the normal registration operation: a new WAITING case with the scenario ZIP, nothing processed
    s, c1 = H(app, "POST", "/api/demo/scenarios/RF-DEMO-01/load")
    assert s == 200 and c1["status"] == "WAITING" and c1["runs"] == []
    assert c1["zip"]["sha256"] == hashlib.sha256(data).hexdigest() and c1["customer_name"] == "Demo Clean Ltd"
    ev = [e for e in ctx.events() if e["event_type"] == "CASE_CREATED" and e["details"].get("case_ref") == c1["case_ref"]]
    assert len(ev) == 1
    # comparison before processing: PENDING (no result is assumed)
    s, v = H(app, "GET", f"/api/demo/scenarios/RF-DEMO-01/verification?case_ref={c1['case_ref']}")
    assert s == 200 and v["status"] == "PENDING" and v["checks"] == []
    # start through the normal operation: the run is the real Smart Parser
    H(app, "POST", f"/api/cases/{c1['case_ref']}/start", {"expected_revision": c1["revision"]})
    d = settle(ctx, c1["case_ref"])
    assert d["current_run"]["status"] == "COMPLETED"
    # repeat load: a second case, the first is untouched
    s, c2 = H(app, "POST", "/api/demo/scenarios/RF-DEMO-01/load")
    assert c2["case_ref"] != c1["case_ref"] and c2["status"] == "WAITING"
    assert H(app, "GET", f"/api/cases/{c1['case_ref']}")[1]["current_run"]["status"] == "COMPLETED"
    refs = [x["case_ref"] for x in H(app, "GET", "/api/demo/scenarios")[1]["scenarios"][0]["cases"]]
    assert sorted(refs) == sorted([c1["case_ref"], c2["case_ref"]])


def test_changed_zip_unknown_scenario_and_foreign_case_refused(tmp_path):
    data = make_zip()
    root = folder(tmp_path, data)
    (root / "scenario_1_clean" / "Demo_Clean.zip").write_bytes(data + b"x")       # differs from scenario.json sha256
    ctx = ctx_for(tmp_path / "ws")
    ctx.demo = DemoScenarios(root)
    app = App(ctx)
    s, b = H(app, "POST", "/api/demo/scenarios/RF-DEMO-01/load")
    assert (s, b["error"]) == (409, "DEMO_ZIP_CHANGED")
    assert ctx.cases.refs() == []                                                     # nothing registered
    assert H(app, "POST", "/api/demo/scenarios/RF-DEMO-99/load")[0] == 404
    other = ctx.cases.create("Other Ltd", "2026-09", "o.zip", make_zip(skip=("IN-03",)))
    s, b = H(app, "GET", f"/api/demo/scenarios/RF-DEMO-01/verification?case_ref={other['case_ref']}")
    assert (s, b["error"]) == (409, "NOT_THIS_SCENARIO")


# ---------------------------------------------------------------------------------------------- RF-DEMO-05 (additive)
import importlib.util  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

REAL = Path(r"C:\Users\artlptp263user\p10\RINGFENCE_DEMO_TEST_DATA")
S5 = REAL / "scenario_5_duplicate"


def _tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "build_duplicate_scenario.py"
    spec = importlib.util.spec_from_file_location("build_duplicate_scenario", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_generic_scenario_folder_is_listed_with_fallback_text(tmp_path):
    data = make_zip()
    root = folder(tmp_path, data)
    d = root / "scenario_9_other"
    d.mkdir()
    (d / "Other.zip").write_bytes(data)
    (d / "scenario.json").write_text(json.dumps({
        "scenario_id": "RF-DEMO-77", "customer_name": "Other Demo Ltd", "reporting_period": "2026-09",
        "zip": {"file": "Other.zip", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        "expected_outcome": {"case_status": "CLEAN"}}))
    (root / "not_a_scenario").mkdir()                                      # ignored: no scenario.json
    ctx = ctx_for(tmp_path / "ws")
    ctx.demo = DemoScenarios(root)
    app = App(ctx)
    cat = H(app, "GET", "/api/demo/scenarios")[1]["scenarios"]
    assert [x["scenario_id"] for x in cat] == ["RF-DEMO-01", "RF-DEMO-77"]
    assert (cat[1]["title"], cat[1]["expected_text"]) == ("RF-DEMO-77", "CLEAN")
    s, c = H(app, "POST", "/api/demo/scenarios/RF-DEMO-77/load")            # same registration as a manual upload
    assert s == 200 and c["status"] == "WAITING" and c["customer_name"] == "Other Demo Ltd"


@pytest.mark.skipif(not (S5 / "scenario.json").is_file(), reason="scenario_5_duplicate folder not present")
def test_rf_demo_05_catalogue_and_load_from_real_folder(tmp_path):
    ctx = ctx_for(tmp_path / "ws")
    ctx.demo = DemoScenarios(REAL)                                          # read-only use of the real folder
    app = App(ctx)
    cat = H(app, "GET", "/api/demo/scenarios")[1]["scenarios"]
    ids = [x["scenario_id"] for x in cat]
    assert ids[-1] == "RF-DEMO-05" and ids == sorted(ids)
    sc = cat[-1]
    assert (sc["order"], sc["title"]) == (5, "Duplicate refund (refund counted twice)")
    assert sc["zip"]["present"] and sc["expected"]["case_status"] == "EXCEPTIONS_OPEN"
    assert sc["expected"]["fail"] == 17 and sc["expected"]["exceptions"] == 17
    s, c = H(app, "POST", "/api/demo/scenarios/RF-DEMO-05/load")
    meta = json.loads((S5 / "scenario.json").read_text(encoding="utf-8"))
    assert s == 200 and c["status"] == "WAITING" and c["runs"] == []
    assert c["zip"]["sha256"] == meta["zip"]["sha256"] and c["customer_name"] == "Pellworth Card Services Ltd"
    ev = [e for e in ctx.events() if e["event_type"] == "CASE_CREATED" and e["details"].get("case_ref") == c["case_ref"]]
    assert len(ev) == 1


@pytest.mark.skipif(not (S5 / "scenario.json").is_file(), reason="scenario_5_duplicate folder not present")
def test_rf_demo_05_zip_and_expectation_come_from_the_canonical_dataset():
    meta = json.loads((S5 / "scenario.json").read_text(encoding="utf-8"))
    exp = json.loads((S5 / "expected_outcome.json").read_text(encoding="utf-8"))
    zb = (S5 / meta["zip"]["file"]).read_bytes()
    assert hashlib.sha256(zb).hexdigest() == meta["zip"]["sha256"]
    with zipfile.ZipFile(io.BytesIO(zb)) as z:
        assert z.testzip() is None
        assert sorted(z.namelist()) == sorted(m["zip_entry"] for m in meta["name_mapping"])
        for m in meta["name_mapping"]:
            assert hashlib.sha256(z.read(m["zip_entry"])).hexdigest() == m["sha256"] == \
                meta["source_dataset"]["files_sha256"][m["canonical_relative_path"]]
    assert [m["category"] for m in meta["name_mapping"]] == [f"IN-{i:02d}" for i in range(1, 20)]
    key = exp["frozen_key"]
    assert exp["expected_case_status"] == "EXCEPTIONS_OPEN"
    assert exp["expected_counts"] == {"FAIL": 17, "INSUFFICIENT_EVIDENCE": 0}
    assert exp["expected_non_passing_set"] == sorted(list(r) for r in key["non_passing_results"])
    assert {r[0] for r in key["non_passing_results"]} == {"C06-DIFFERENCE", "CBAL-ROLLFWD"}
    assert exp["expected_exception_root_causes"] == sorted(e["root_cause"] for e in key["exceptions"])
    assert exp["expected_investigation_group_count"] == len(key["investigation_groups"]) == 1
    kp = Path(meta["frozen_key"]["path"])
    if kp.is_file():                                                        # the frozen key is unchanged
        assert hashlib.sha256(kp.read_bytes()).hexdigest() == exp["source_sha256"] == meta["frozen_key"]["sha256"]
        assert json.loads(kp.read_text(encoding="utf-8")) == key
        assert _tool().expected_from_key(key, kp) == exp                    # expectation = pure function of the key
