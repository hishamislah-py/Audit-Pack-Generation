"""Browser application API (smartparser.webapp): thin layer over the EXISTING services.

Pins: uploads are staged (ZIP expanded, unsafe / hidden entries skipped); intake jobs call the real PackageService and
progress never claims a stage before the service result / audit event exists; activation needs an explicit confirmation
and is refused by the real validation when the package is not ready; the review view carries source sample values and
financial flags; resubmission only for categories that await a corrected file; the HTTP layer requires the client header
for POSTs and serves only allow-listed static files; reconciliation runs through the real adapter."""
import base64
import io
import json
import time
import zipfile

import pytest

from smartparser.review.authority import Reviewer
from smartparser.webapp import api
from smartparser.webapp.context import AppContext
from smartparser.webapp.server import App

from .phase3b_support import TEST_POLICY, dump, tbl
from .uc042_support import SEP, UC042_ROOT, needs_uc042, read

ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
REQUIRED = ["IN-01", "IN-02", "IN-03", "IN-04", "IN-05", "IN-06", "IN-07", "IN-08", "IN-09", "IN-10", "IN-11", "IN-12",
            "IN-13", "IN-14", "IN-15", "IN-16", "IN-17"]


def ctx_for(tmp_path, engine=False) -> AppContext:
    return AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST,
                      uc042_root=UC042_ROOT if engine else None)


def R(ctx, method, path, body=None, q=None):
    return api.route(ctx, method, [p for p in path.split("/") if p], q or {}, body or {})


def stage(ctx, name, data):
    return R(ctx, "POST", "staging", {"name": name, "data_b64": base64.b64encode(data).decode()})["entries"]


def wait_job(ctx, jid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        v = R(ctx, "GET", f"jobs/{jid}")
        if v["state"] not in ("queued", "running"):
            return v
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def fixture_name(fid):
    return f"f_{fid}" + (".pdf" if fid in ("IN-15", "IN-16", "IN-17") else ".csv")


def test_zip_staging_expands_files_and_skips_hidden_entries(tmp_path):
    ctx = ctx_for(tmp_path)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("pack/a.csv", read(SEP, "IN-01"))
        z.writestr("__MACOSX/._a.csv", b"junk")
        z.writestr("pack/.hidden", b"x")
    ents = stage(ctx, "pack.zip", b.getvalue())
    assert [e["name"] for e in ents if e["staging_id"]] == ["a.csv"]
    assert sum(1 for e in ents if e.get("skipped")) == 2
    with pytest.raises(api.HttpError):
        R(ctx, "POST", "staging", {"name": "x.csv", "data_b64": "@@not base64@@"})
    with pytest.raises(ValueError, match="INVALID_ZIP"):
        stage(ctx, "broken.zip", b"PK\x03\x04garbage")


def test_intake_job_uses_the_service_and_progress_is_evidence_based(tmp_path):
    ctx = ctx_for(tmp_path)
    pkg = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})
    pid = pkg["package_id"]
    items = [{"staging_id": stage(ctx, fixture_name(f), read(SEP, f))[0]["staging_id"]} for f in REQUIRED]
    items.append({"staging_id": stage(ctx, "mystery.csv", b"a,b\n1,2\n")[0]["staging_id"]})
    j = wait_job(ctx, R(ctx, "POST", f"packages/{pid}/intake", {"items": items})["job_id"])
    assert j["state"] == "completed" and j["progress"] == {"files_total": 18, "files_processed": 18}
    st = {s["key"]: s["status"] for s in j["stages"]}
    assert st["identify"] == "requires_attention"                    # the unknown CSV was refused
    assert st["validation"] == "completed" and j["validation"]["passed"] is True
    assert all(s["evidence"] for s in j["stages"] if s["status"] == "completed" and s["key"] != "proposals")
    pkg = R(ctx, "GET", f"packages/{pid}")
    assert pkg["counts"]["validated_or_active"] == 17 and pkg["counts"]["refused_uploads"] == 1
    # a job that has not run yet never shows a completed per-file stage
    fake = dict(j, state="running", audit_seq_start=10 ** 9, audit_seq_end=None, validation=None,
                files=[dict(f, state="queued", started_at=None, finished_at=None, outcome=None) for f in j["files"]])
    stages = {s["key"]: s["status"] for s in api.job_view(ctx, fake)["stages"]}
    assert stages["identify"] == stages["mapping"] == stages["previews"] == "pending"
    assert stages["validation"] == "pending"


def test_activation_requires_confirmation_and_respects_validation(tmp_path):
    ctx = ctx_for(tmp_path)
    pid = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]
    with pytest.raises(api.HttpError) as e:
        R(ctx, "POST", f"packages/{pid}/activate", {})
    assert e.value.code == "CONFIRMATION_REQUIRED"
    out = R(ctx, "POST", f"packages/{pid}/activate", {"confirm": True})           # empty package: the service refuses
    assert out["activated"] is False and out["snapshot_id"] is None
    v = out["validation"]
    assert v["activation_permitted"] is False and "PV-01" in [c["check_id"] for c in v["result"]["checks"] if not c["passed"]]
    assert all(c["action"] for c in v["result"]["checks"] if not c["passed"])


def test_review_view_shows_source_values_flags_and_uses_the_review_workflow(tmp_path):
    ctx = ctx_for(tmp_path)
    pid = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]
    r = tbl("IN-07")
    sid = stage(ctx, "bank.csv", dump([r[0] + ["memo"]] + [x + ["m"] for x in r[1:]]))[0]["staging_id"]
    j = wait_job(ctx, R(ctx, "POST", f"packages/{pid}/intake", {"items": [{"staging_id": sid, "declared_category": "IN-07"}]})["job_id"])
    vid = j["files"][0]["outcome"]["file_version_id"]
    assert R(ctx, "GET", "reviews")[0]["extra_headers"] == ["memo"]
    d = R(ctx, "GET", f"review/{pid}/{vid}")
    bal = next(x for x in d["rows"] if x["source_header"] == "balance_amount")
    assert bal["profile"]["samples"] == [x[r[0].index("balance_amount")] for x in r[1:7]] and bal["financial"]
    assert d["profile"]["rows"] == len(r) - 1 and d["reviewer"]["kind"] == "TEST"
    with pytest.raises(review_api_error()):
        R(ctx, "POST", f"review/{pid}/{vid}/decision", {"action": "IGNORE_COLUMN", "source_index": len(r[0]), "reason": " "})
    d = R(ctx, "POST", f"review/{pid}/{vid}/decision", {"action": "IGNORE_COLUMN", "source_index": len(r[0]),
                                                        "reason": "working note"})
    assert next(x for x in d["rows"] if x["source_header"] == "memo")["decision"]["action"] == "IGNORE_COLUMN"


def review_api_error():
    from smartparser.packages.review_api import ApiError
    return ApiError


def test_resubmission_only_for_pending_categories(tmp_path):
    ctx = ctx_for(tmp_path)
    pid = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]
    sid = stage(ctx, "a.csv", read(SEP, "IN-01"))[0]["staging_id"]
    wait_job(ctx, R(ctx, "POST", f"packages/{pid}/intake", {"items": [{"staging_id": sid}]})["job_id"])
    with pytest.raises(api.HttpError) as e:
        R(ctx, "POST", f"packages/{pid}/resubmit", {"category": "IN-01", "staging_id": sid, "reason": "again"})
    assert e.value.code == "PACKAGE_STATE"                                        # VALIDATED: never voluntarily replaced
    with pytest.raises(api.HttpError) as e:
        R(ctx, "POST", f"packages/{pid}/resubmit", {"category": "IN-01", "staging_id": sid, "reason": ""})
    assert e.value.code == "REASON_REQUIRED"


def test_http_layer_requires_client_header_and_serves_only_known_static_files(tmp_path):
    app = App(ctx_for(tmp_path))
    s, _, body = app.handle("POST", "/api/packages", {}, b'{"reporting_period": "2026-09"}')
    assert s == 403
    s, _, body = app.handle("POST", "/api/packages", {"X-Smartparser-Client": "webapp"}, b'{"reporting_period": "2026-09"}')
    assert s == 200 and json.loads(body)["package_status"] == "RECEIVED"
    assert app.handle("GET", "/", {}, b"")[0] == 200 and app.handle("GET", "/design.html", {}, b"")[0] == 200
    for bad in ("/../pyproject.toml", "/server.py", "/static/app.js", "/api/runs/..%2F..%2Fx"):
        assert app.handle("GET", bad, {}, b"")[0] == 404, bad
    s, _, body = app.handle("POST", "/api/packages", {"X-Smartparser-Client": "webapp"}, b"not json")
    assert s == 400


@needs_uc042
def test_reconciliation_through_the_real_adapter_and_results_views(tmp_path):
    ctx = ctx_for(tmp_path, engine=True)
    pid = R(ctx, "POST", "packages", {"reporting_period": "2026-09"})["package_id"]
    items = [{"staging_id": stage(ctx, fixture_name(f), read(SEP, f))[0]["staging_id"]} for f in REQUIRED]
    wait_job(ctx, R(ctx, "POST", f"packages/{pid}/intake", {"items": items})["job_id"])
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        R(ctx, "POST", f"packages/{pid}/reconcile", {"snapshot_id": "SNAP-001-x"})
    a = R(ctx, "POST", f"packages/{pid}/activate", {"confirm": True})
    assert a["activated"]
    j = wait_job(ctx, R(ctx, "POST", f"packages/{pid}/reconcile", {"snapshot_id": a["snapshot_id"]})["job_id"], 600)
    assert j["state"] == "completed" and [s["status"] for s in j["stages"]] == ["completed"] * 4
    run = R(ctx, "GET", f"runs/{j['run_id']}")
    assert run["case_status"] == "CLEAN" and run["exception_count"] == 0 and run["total_results"] == sum(run["outcomes"].values())
    assert all(run["integrity_checks"].values())
    c = R(ctx, "GET", f"runs/{j['run_id']}/controls", q={"outcome": "PASS"})
    assert c["total"] == run["outcomes"]["PASS"]
    act = R(ctx, "GET", "activity", q={"package_id": pid})
    assert act["chain"]["verified"] and act["events"][0]["event_type"] == "RECONCILIATION_EXECUTED"
