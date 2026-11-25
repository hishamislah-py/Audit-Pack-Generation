"""Capture the frontend's mock data set from the REAL backend (read-only). Run from uc042/ with the project venv:

    .venv/Scripts/python.exe -B frontend/scripts/capture_mock_data.py [--s05-live-preview <preview final-pack JSON>]

The FastAPI app runs in-process (TestClient) on a TEMPORARY state directory and a TEMPORARY final-packs folder, with the
offline provider, so no OpenAI call is made and nothing in packs/, investigations/ or final_packs/ is written. The
existing published investigations are registered as a legacy baseline in that temporary state only.

Every response the UI reads is written to frontend/dev-fixtures/mock-data/<url path>.json, exactly as the API returned it, plus
one real Phase 1 report preview per pack (backend renderer; closing summary UNAVAILABLE because the provider is offline).
With --s05-live-preview, the S05 preview is replaced by the live gpt-6-luna preview captured on 3 Nov 2026, re-rendered
with the current library (HTML and PDF are produced from that canonical JSON).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["UC042_LLM_PROVIDER"] = "offline"  # never a live call

from fastapi.testclient import TestClient  # noqa: E402

from uc042app.api.main import create_app  # noqa: E402
from uc042app.config import Settings  # noqa: E402
from uc042lib.final_pack import render_html, render_pdf  # noqa: E402
from uc042lib.pack.model import canonical  # noqa: E402

OUT = ROOT / "frontend" / "dev-fixtures" / "mock-data"


def save(path, data):
    target = OUT / (path.strip("/") + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s05-live-preview", help="canonical JSON of the live S05 preview (optional)")
    args = ap.parse_args()
    if OUT.exists():
        shutil.rmtree(OUT)
    tmp = Path(tempfile.mkdtemp(prefix="u42cap-"))
    try:
        settings = Settings.from_env(state_dir=tmp / "s", final_packs_root=tmp / "fp", analyst_id="mock-analyst", database_url=None,
                                     analyst_name="Mock Analyst")
        app = create_app(settings)
        with TestClient(app) as c:
            svc = app.state.services
            for pack_id in svc.packs.pack_ids():  # legacy baseline in the TEMPORARY registry only
                pack = svc.packs.load(pack_id)
                for d in sorted((settings.investigations_root / pack_id).glob("EXC-*/INV-*")):
                    svc.registry.import_legacy(d, pack, "mock-capture")

            def get(path, **kw):
                r = c.get(path, **kw)
                assert r.status_code == 200, (path, r.status_code, r.text[:300])
                return r

            save("health", get("/health").json())
            packs = get("/api/v1/packs").json()
            save("api/v1/packs", packs)
            investigations, previews = set(), []
            for p in packs:
                pid = p["pack_id"]
                for sub in ("", "/reconciliation", "/sources", "/exceptions", "/investigations"):
                    save(f"api/v1/packs/{pid}{sub}", get(f"/api/v1/packs/{pid}{sub}").json())
                for x in get(f"/api/v1/packs/{pid}/exceptions").json():
                    detail = get(f"/api/v1/packs/{pid}/exceptions/{x['exception_id']}").json()
                    save(f"api/v1/packs/{pid}/exceptions/{x['exception_id']}", detail)
                    investigations.update(i["investigation_id"] for i in detail["investigations"]["published"])
                # one real preview per pack (default selections), through the real review workflow
                session = c.post(f"/api/v1/packs/{pid}/reviews").json()
                job = c.post(f"/api/v1/reviews/{session['review_id']}/preview").json()
                svc.runner.wait(job["job_id"], 120)
                session = get(f"/api/v1/reviews/{session['review_id']}").json()
                meta = session["current_preview"]
                if meta is None:
                    print(f"  {pid}: no preview ({session['readiness']['blockers']})")
                    continue
                snap = meta["snapshot_sha256"]
                base = f"/api/v1/reviews/{session['review_id']}/preview"
                doc = get(f"{base}/json", params={"snapshot": snap}).json()
                prev = OUT / "previews"
                prev.mkdir(parents=True, exist_ok=True)
                (prev / f"{pid}.html").write_text(get(f"{base}/html", params={"snapshot": snap}).text, encoding="utf-8")
                (prev / f"{pid}.pdf").write_bytes(get(f"{base}/pdf", params={"snapshot": snap}).content)
                save(f"previews/{pid}", doc)
                save(f"previews/{pid}.meta", {"preview": meta, "selections": session["selections"],
                                              "readiness": session["readiness"], "acknowledgement_text": session["acknowledgement_text"]})
                previews.append(pid)
            for inv in sorted(investigations):
                for sub in ("", "/findings", "/verify"):
                    save(f"api/v1/investigations/{inv}{sub}", get(f"/api/v1/investigations/{inv}{sub}").json())
                save(f"api/v1/investigations/{inv}/evidence", get(f"/api/v1/investigations/{inv}/evidence", params={"limit": 200}).json())

        live = None
        if args.s05_live_preview:
            doc = json.loads(Path(args.s05_live_preview).read_text(encoding="utf-8"))
            pid = doc["metadata"]["source_pack"]["pack_id"]
            (OUT / "previews" / f"{pid}.html").write_text(render_html(doc), encoding="utf-8")
            (OUT / "previews" / f"{pid}.pdf").write_bytes(render_pdf(doc))
            save(f"previews/{pid}", doc)
            meta_path = OUT / "previews" / f"{pid}.meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cs = doc["closing_summary"]
            meta["preview"].update(snapshot_sha256=cs["snapshot_sha256"], preview_final_pack_id=doc["metadata"]["final_pack_id"],
                                   preview_content_sha256=doc["final_content_sha256"],
                                   closing_summary={"status": cs["status"], "sha256": "", "unavailable_reason": cs["unavailable_reason"],
                                                    "failure": None, "model": cs["model_metadata"].get("model"),
                                                    "provider": cs["model_metadata"].get("provider"), "created_at": cs["created_at"]},
                                   created_at=doc["metadata"]["generated_at"])
            meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
            live = pid

        save("manifest", {
            "captured_at": json.loads(canonical({"t": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")}))["t"],
            "source": "Real UC-042 FastAPI responses (September 2026 synthetic scenario packs), captured read-only with the offline provider.",
            "packs": [p["pack_id"] for p in packs], "investigations": sorted(investigations), "previews": previews,
            "live_closing_summary_preview": live,
            "notes": ["Nine packs are nine TEST SCENARIOS for September 2026, not nine months.",
                      "Previews other than the live one carry an UNAVAILABLE closing summary (offline provider).",
                      "Investigation eligibility reflects a legacy baseline import into a temporary registry."]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"wrote {sum(1 for f in OUT.rglob('*') if f.is_file())} files, {total / 1e6:.1f} MB to {OUT}")


if __name__ == "__main__":
    main()
