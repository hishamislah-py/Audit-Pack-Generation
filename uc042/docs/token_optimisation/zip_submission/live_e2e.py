"""Live end-to-end run of the independent ZIP submission workflow against a RUNNING isolated backend (offline provider).
Usage: python -I live_e2e.py <api base> <dataset dir> <final packs root> <out json>
Read-only on the dataset; every write goes through the API. Prints a step log and writes the evidence JSON."""
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import httpx

BASE, DATASET, FP_ROOT, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
c = httpx.Client(base_url=BASE, timeout=120)
log, evidence = [], {}


def step(msg, **kw):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}" + (f" {json.dumps(kw, default=str)}" if kw else "")
    print(line, flush=True)
    log.append(line)


def ok(r, *codes):
    if r.status_code not in (codes or (200, 201, 202)):
        raise SystemExit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:800]}")
    return r.json()


def wait_job(job_id, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        j = ok(c.get(f"/api/v1/jobs/{job_id}"))
        if j["status"] not in ("QUEUED", "RUNNING"):
            return j
        time.sleep(1)
    raise SystemExit(f"job {job_id} did not finish")


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def make_zip(extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((DATASET / "source_data").glob("*.csv")) + sorted((DATASET / "supporting_documents").glob("*.pdf")):
            z.writestr(p.name, p.read_bytes())
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


def upload(data, name):
    return ok(c.post("/api/v1/periods/PER-2026-09/packages", files={"file": (name, data, "application/zip")}), 201)


def runs_count():
    return len(ok(c.get("/api/v1/periods/PER-2026-09"))["runs"])


health = ok(c.get("/health"))
cfg = ok(c.get("/api/v1/ai/configuration"))
step("health", status=health["status"], database=health.get("database"), provider=cfg.get("provider"), model=cfg.get("model"))
assert cfg["provider_configured"], cfg.get("configuration_problem")  # the mocked OpenAI client (launch_backend.py): no network call
auth = {"confirmed": True, "provider": cfg["provider"], "model": cfg["model"]}

# 0. ZIP-only operation: the retired individual-document entry points refuse
r = c.post("/api/v1/periods/PER-2026-09/uploads", files={"files": ("transactions_2026-09.csv", b"x", "text/csv")})
r2 = c.post("/api/v1/periods/PER-2026-09/reconciliation", json={"purpose": "INITIAL"})
step("retired legacy entry points", upload=(r.status_code, r.json().get("code")), reconcile=(r2.status_code, r2.json().get("code")))
assert (r.status_code, r.json().get("code")) == (410, "LEGACY_WORKFLOW_RETIRED") and r2.status_code == 410
evidence["legacy_refused"] = {"upload": r.status_code, "reconcile": r2.status_code}

# 1. a failing package: no run is created
before = runs_count()
bad = upload(make_zip({"notes.txt": b"not part of the schema", "../evil.csv": b"x"}), "september_bad.zip")
g = bad["batch"]["summary"]["package"]["gate"]
r = c.post(f"/api/v1/uploads/{bad['batch']['batch_id']}/submit", json={"ai_authorization": auth})
step("rejected package", batch=bad["batch"]["batch_id"], status=bad["batch"]["status"], unsafe=g["unsafe"], unexpected=g["unexpected"],
     submit_http=r.status_code, submit_code=r.json().get("code"), runs_before=before, runs_after=runs_count())
assert bad["batch"]["status"] == "PACKAGE_REJECTED" and r.status_code == 409 and runs_count() == before
data = make_zip()
miss = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(miss, "w") as dst:
    for i in src.infolist():
        if not i.filename.startswith("transactions_"):
            dst.writestr(i.filename, src.read(i))
inc = upload(miss.getvalue(), "september_missing_in11.zip")
step("incomplete package", batch=inc["batch"]["batch_id"], status=inc["batch"]["status"],
     missing=inc["batch"]["summary"]["package"]["gate"]["missing_required"])
assert inc["batch"]["summary"]["package"]["gate"]["missing_required"] == ["IN-11"]
evidence["rejected"] = {"batch": bad["batch"]["batch_id"], "gate": g, "submit_http": r.status_code}
evidence["incomplete"] = {"batch": inc["batch"]["batch_id"], "missing": inc["batch"]["summary"]["package"]["gate"]["missing_required"]}


def submission(name, zip_bytes):
    d = upload(zip_bytes, name)
    gate = d["batch"]["summary"]["package"]["gate"]
    step("upload + validate", batch=d["batch"]["batch_id"], status=d["batch"]["status"], passed=gate["passed"],
         present_required=len(gate["present_required"]), present_optional=gate["present_optional"], zip_sha256=d["batch"]["summary"]["package"]["zip_sha256"][:16])
    assert gate["passed"]
    run = ok(c.post(f"/api/v1/uploads/{d['batch']['batch_id']}/submit", json={"ai_authorization": auth}), 202)
    step("submit for audit", submission=run["result"]["submission_id"], run=run["run_id"])
    wait_job(run["job_id"])
    run = ok(c.get(f"/api/v1/processing-runs/{run['run_id']}"))
    items = (run["result"].get("auto_investigation") or {}).get("items") or []
    jobs = [wait_job(i["job_id"]) for i in items if i.get("job_id")]
    step("audit result", status=run["status"], pack=run["result"].get("pack_id"), outcome=run["result"].get("outcome"),
         investigations=[(j["exception_id"], j["status"], (j.get("result") or {}).get("persist_outcome"), (j.get("result") or {}).get("investigation_id"),
                          j.get("error_summary", "")[:120]) for j in jobs])
    return d, run, jobs


def review(run, jobs):
    sub, pack = run["result"]["submission_id"], run["result"]["pack_id"]
    s = ok(c.post(f"/api/v1/packs/{pack}/reviews", json={"submission_id": sub}), 201)
    step("review opened", review=s["review_id"], submission=s["submission_id"], run=s["run_id"], batch=s["batch_id"],
         selections=[(x["exception_id"], x["inclusion"], x["investigation_id"]) for x in s["selections"]],
         blockers=[b["code"] for b in s["readiness"]["blockers"]])
    for x in s["selections"]:
        if x["inclusion"] == "INCLUDED":
            a = ok(c.post(f"/api/v1/investigations/{x['investigation_id']}/analyst-review",
                          json={"decision": "ACCEPT", "comment": f"Accepted in {sub}", "expected_revision": 0, "submission_id": sub}), 201)
            step("analyst ACCEPT (submission-scoped)", investigation=x["investigation_id"], revision=a["revision"], submission=a["submission_id"])
    s = ok(c.get(f"/api/v1/reviews/{s['review_id']}"))
    failed = [x for x in s["readiness"]["checklist"]["exceptions"] if x["disposition"] in ("FAILED_ACTION_NEEDED", "SELECTION_NEEDED")]
    if failed:  # an exception whose investigation did not complete for this submission: exclude it with a documented reason
        sel = [x if x["exception_id"] not in {f["exception_id"] for f in failed} else
               {"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST", "reason": "Investigation did not complete for this submission (live E2E)."}
               for x in s["selections"]]
        s = ok(c.patch(f"/api/v1/reviews/{s['review_id']}/selections", json={"selections": sel, "expected_revision": s["revision"]}))
        step("excluded with reason", exceptions=[f["exception_id"] for f in failed])
    p = ok(c.post(f"/api/v1/reviews/{s['review_id']}/preview", json={"authorization": auth}), 202)
    wait_job(p["job_id"])
    s = ok(c.get(f"/api/v1/reviews/{s['review_id']}"))
    step("preview", ready=s["readiness"]["ready"], blockers=[b["code"] for b in s["readiness"]["blockers"]],
         closing_summary=s["current_preview"]["closing_summary"]["status"] if s["current_preview"] else None)
    body = {"decision": "GENERATE", "acknowledgement_accepted": True, "snapshot_sha256": s["current_preview"]["snapshot_sha256"], "comment": f"Live E2E {sub}"}
    if s["current_preview"]["closing_summary"]["status"] == "UNAVAILABLE":
        body["acknowledged_summary_unavailable"] = True
    g = ok(c.post(f"/api/v1/reviews/{s['review_id']}/decision", json=body), 201)
    fp = g["final_pack"]["final_pack_id"]
    step("GENERATE", final_pack=fp)
    return s, fp


d1, run1, jobs1 = submission("september.zip", data)
s1, fp1 = review(run1, jobs1)
fp1_dir = next(p for p in FP_ROOT.rglob(fp1) if p.is_dir())
fp1_tree = tree(fp1_dir)

INV_ROOT = FP_ROOT.parent / "investigations"
inv_dirs1 = {j["result"]["investigation_id"]: next(p for p in INV_ROOT.rglob(j["result"]["investigation_id"]) if p.is_dir())
             for j in jobs1 if (j.get("result") or {}).get("investigation_id")}
inv_trees1 = {k: tree(v) for k, v in inv_dirs1.items()}
d2, run2, jobs2 = submission("september.zip", data)  # the identical ZIP, uploaded and submitted again
ids2 = [(j.get("result") or {}).get("investigation_id") for j in jobs2]
exec2 = {}
for inv in ids2:
    if inv:
        f = json.loads((next(p for p in INV_ROOT.rglob(inv) if p.is_dir()) / "findings.json").read_text(encoding="utf-8"))
        exec2[inv] = {"execution": f.get("execution"), "usage": (f.get("model_metadata") or {}).get("usage"), "investigated_at": f.get("investigated_at")}
step("submission 2 investigations persisted independently", all_published=all(j["status"] == "COMPLETED" and j["result"]["persist_outcome"] == "PUBLISHED" for j in jobs2),
     disjoint_from_submission_1=set(ids2).isdisjoint(inv_dirs1), executions={k: v["execution"] for k, v in exec2.items()},
     submission_1_artefacts_unchanged={k: tree(v) for k, v in inv_dirs1.items()} == inv_trees1)
assert all(j["status"] == "COMPLETED" and j["result"]["persist_outcome"] == "PUBLISHED" for j in jobs2)
assert set(ids2).isdisjoint(inv_dirs1) and all(v["execution"]["submission_id"] == run2["result"]["submission_id"] for v in exec2.values())
evidence["submission_2_executions"] = exec2
s2, fp2 = review(run2, jobs2)
fp1_after = tree(fp1_dir)
assert {k: tree(v) for k, v in inv_dirs1.items()} == inv_trees1, "a submission 1 investigation artefact changed"
evidence["submission_1_investigations_unchanged_at_end"] = True

listing = {f["final_pack_id"]: f for f in ok(c.get("/api/v1/final-packs"))}
hist = ok(c.get("/api/v1/periods/PER-2026-09/submissions"))
verify = {fp: ok(c.get(f"/api/v1/final-packs/{fp}/verify")) for fp in (fp1, fp2)}
step("final packs", fp1={k: listing[fp1].get(k) for k in ("submission_id", "run_id", "batch_id", "generated_at")},
     fp2={k: listing[fp2].get(k) for k in ("submission_id", "run_id", "batch_id", "generated_at")},
     fp1_unchanged=fp1_tree == fp1_after, verified={k: v["verified"] for k, v in verify.items()})
step("history", packages=[(p["batch_id"], p["status"], [(s["submission_id"], s["status"], s["pack_id"], [f["final_pack_id"] for f in s.get("final_packs") or []])
                                                       for s in p["submissions"]]) for p in hist])
assert run1["result"]["submission_id"] != run2["result"]["submission_id"] and run1["run_id"] != run2["run_id"]
assert run1["result"]["pack_id"] == run2["result"]["pack_id"]
assert fp1 != fp2 and fp1_tree == fp1_after
# no cross-submission Version / Supersedes chain and no other submission's investigations in a final pack
docs = {fp: ok(c.get(f"/api/v1/final-packs/{fp}/json")) for fp in (fp1, fp2)}
ids1 = {j["result"]["investigation_id"] for j in jobs1 if (j.get("result") or {}).get("investigation_id")}
ids2 = {j["result"]["investigation_id"] for j in jobs2 if (j.get("result") or {}).get("investigation_id")}
chain = {fp: (d["metadata"]["version"], d["metadata"]["supersedes_final_pack_id"]) for fp, d in docs.items()}
cross = {fp1: [i for i in ids2 if i in json.dumps(docs[fp1])], fp2: [i for i in ids1 if i in json.dumps(docs[fp2])]}
step("final-pack isolation", version_supersedes=chain, other_submission_investigations_referenced=cross)
assert chain == {fp1: (1, None), fp2: (1, None)} and cross == {fp1: [], fp2: []}
evidence["final_pack_isolation"] = {"version_supersedes": chain, "cross_references": cross}
assert listing[fp1]["submission_id"] == run1["result"]["submission_id"] and listing[fp2]["submission_id"] == run2["result"]["submission_id"]
assert all(v["verified"] for v in verify.values())
evidence.update({"submission_1": {"batch": d1["batch"]["batch_id"], "submission_id": run1["result"]["submission_id"], "run_id": run1["run_id"],
                                  "pack_id": run1["result"]["pack_id"], "outcome": run1["result"]["outcome"], "review_id": s1["review_id"], "final_pack": fp1},
                 "submission_2": {"batch": d2["batch"]["batch_id"], "submission_id": run2["result"]["submission_id"], "run_id": run2["run_id"],
                                  "pack_id": run2["result"]["pack_id"], "outcome": run2["result"]["outcome"], "review_id": s2["review_id"], "final_pack": fp2},
                 "jobs_1": [(j["exception_id"], j["status"], (j.get("result") or {}).get("persist_outcome"), (j.get("result") or {}).get("investigation_id")) for j in jobs1],
                 "jobs_2": [(j["exception_id"], j["status"], (j.get("result") or {}).get("persist_outcome"), (j.get("result") or {}).get("investigation_id"),
                             j.get("error_summary", "")[:200]) for j in jobs2],
                 "final_pack_listing": {k: listing[k] for k in (fp1, fp2)}, "fp1_unchanged_after_second": fp1_tree == fp1_after,
                 "verify": verify, "history": hist, "log": log})
OUT.write_text(json.dumps(evidence, indent=1, default=str), encoding="utf-8")
step("PASS: live end-to-end completed")
