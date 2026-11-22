"""Live walkthrough part 2 (real provider): the state after submission 1's failed generation, then the identical ZIP as
submission 2 (independent run, investigations, decisions and review), and a generation attempt. Read-only on the dataset."""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import httpx

BASE, DATASET, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
c = httpx.Client(base_url=BASE, timeout=120)
log = []


def step(msg, **kw):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}" + (f" {json.dumps(kw, default=str)}" if kw else "")
    print(line, flush=True)
    log.append(line)


def ok(r, *codes):
    if r.status_code not in (codes or (200, 201, 202)):
        raise SystemExit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:600]}")
    return r.json()


def wait_job(job_id, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        j = ok(c.get(f"/api/v1/jobs/{job_id}"))
        if j["status"] not in ("QUEUED", "RUNNING"):
            return j
        time.sleep(2)
    raise SystemExit(f"job {job_id} did not finish")


cfg = ok(c.get("/api/v1/ai/configuration"))
auth = {"confirmed": True, "provider": cfg["provider"], "model": cfg["model"]}
hist = ok(c.get("/api/v1/periods/PER-2026-09/submissions"))
first = next(s for p in hist for s in p["submissions"])
reviews = ok(c.get("/api/v1/reviews"))
records = ok(c.get("/api/v1/final-packs"))
step("submission 1 after the failed generation", submission=first["submission_id"], run_status=first["status"],
     reviews=[(r["review_id"], r["status"], r.get("submission_id")) for r in reviews], published_final_packs=len(records))

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted((DATASET / "source_data").glob("*.csv")) + sorted((DATASET / "supporting_documents").glob("*.pdf")):
        z.writestr(p.name, p.read_bytes())
d = ok(c.post("/api/v1/periods/PER-2026-09/packages", files={"file": ("september.zip", buf.getvalue(), "application/zip")}), 201)
run = ok(c.post(f"/api/v1/uploads/{d['batch']['batch_id']}/submit", json={"ai_authorization": auth}), 202)
step("submission 2 (identical ZIP)", batch=d["batch"]["batch_id"], gate_passed=d["batch"]["summary"]["package"]["gate"]["passed"],
     submission=run["result"]["submission_id"], run=run["run_id"])
wait_job(run["job_id"])
run = ok(c.get(f"/api/v1/processing-runs/{run['run_id']}"))
jobs = [wait_job(i["job_id"]) for i in run["result"]["auto_investigation"]["items"] if i.get("job_id")]
step("submission 2 audit result", status=run["status"], pack=run["result"]["pack_id"], outcome=run["result"]["outcome"],
     same_pack_as_submission_1=run["result"]["pack_id"] == first["pack_id"],
     investigations=[(j["exception_id"], j["status"], (j.get("result") or {}).get("persist_outcome"),
                      (j.get("result") or {}).get("investigation_id"), (j.get("error_summary") or "")[:160]) for j in jobs])
sub = run["result"]["submission_id"]
s = ok(c.post(f"/api/v1/packs/{run['result']['pack_id']}/reviews", json={"submission_id": sub}), 201)
step("submission 2 review opened (submission 1's review is GENERATION_FAILED and does not block it)", review=s["review_id"],
     selections=[(x["exception_id"], x["inclusion"], x["investigation_id"]) for x in s["selections"]],
     blockers=[b["code"] for b in s["readiness"]["blockers"]])
for x in s["selections"]:
    if x["inclusion"] == "INCLUDED":
        a = ok(c.post(f"/api/v1/investigations/{x['investigation_id']}/analyst-review",
                      json={"decision": "ACCEPT", "comment": f"Accepted in {sub}", "expected_revision": 0, "submission_id": sub}), 201)
        step("submission 2 ACCEPT", investigation=x["investigation_id"], revision=a["revision"], submission=a["submission_id"])
s = ok(c.get(f"/api/v1/reviews/{s['review_id']}"))
failed = [x["exception_id"] for x in s["readiness"]["checklist"]["exceptions"] if x["disposition"] in ("FAILED_ACTION_NEEDED", "SELECTION_NEEDED")]
if failed:
    sel = [x if x["exception_id"] not in failed else {"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST",
                                                      "reason": "Investigation did not produce a usable result for this submission (live walkthrough)."}
           for x in s["selections"]]
    s = ok(c.patch(f"/api/v1/reviews/{s['review_id']}/selections", json={"selections": sel, "expected_revision": s["revision"]}))
    step("submission 2 excluded with reason", exceptions=failed)
p = ok(c.post(f"/api/v1/reviews/{s['review_id']}/preview", json={"authorization": auth}), 202)
wait_job(p["job_id"])
s = ok(c.get(f"/api/v1/reviews/{s['review_id']}"))
step("submission 2 preview", ready=s["readiness"]["ready"], blockers=[b["code"] for b in s["readiness"]["blockers"]],
     closing_summary=(s["current_preview"] or {}).get("closing_summary", {}).get("status"))
g = c.post(f"/api/v1/reviews/{s['review_id']}/decision", json={"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                "snapshot_sha256": s["current_preview"]["snapshot_sha256"]})
step("submission 2 GENERATE", http=g.status_code, body=g.text[:400])
fps = ok(c.get("/api/v1/final-packs"))
for f in fps:
    v = ok(c.get(f"/api/v1/final-packs/{f['final_pack_id']}/verify"))
    final = ok(c.get(f"/api/v1/final-packs/{f['final_pack_id']}/json"))
    step("final pack", id=f["final_pack_id"], submission=f.get("submission_id"), run=f.get("run_id"), verified=v["verified"],
         version=final["metadata"]["version"], supersedes=final["metadata"]["supersedes_final_pack_id"])
hist = ok(c.get("/api/v1/periods/PER-2026-09/submissions"))
step("history", packages=[(p["batch_id"], p["status"], [(x["submission_id"], x["status"], [f["final_pack_id"] for f in x.get("final_packs") or []])
                                                      for x in p["submissions"]]) for p in hist])
OUT.write_text("\n".join(log), encoding="utf-8")
