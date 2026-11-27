"""SUPERSEDED (19 Nov 2026) by tools/seed_analyst_demo.py, the only active preload and startup tool. Kept for
reference; do not use it for the demo.

Preload the four Ringfence demo cases into a workspace, so they appear in the analyst's Work Queue after login.

    py -3.11 -B tools/preload_demo_cases.py --root C:\\u42v\\ringfence_demo_ws ^
        --scenarios C:\\Users\\artlptp263user\\p10\\RINGFENCE_DEMO_TEST_DATA --reviewer-id analyst-1

Run it while no server is using the workspace.

Each scenario's original ZIP is registered through the normal registration operation, `CaseService.create`, the same
call as POST /api/cases. The ZIP's sha256 must equal its scenario.json first, so this goes through
`DemoScenarios.load`. The case is then WAITING and nothing is processed: the analyst runs Start, validation,
activation, reconciliation and Retry in the UI, and every result comes from the real pipeline.

The tool is additive and idempotent. A scenario whose ZIP is already the original ZIP of a case in the workspace is
skipped, and existing cases, runs and audit history are never changed. No answer key is read."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from smartparser.review.authority import Reviewer  # noqa: E402
from smartparser.webapp.context import AppContext  # noqa: E402
from smartparser.webapp.demo import TEXT, DemoScenarios  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--reviewer-id", default="analyst-1")
    ap.add_argument("--assign-to", default=None, help="sign-in username recorded as assigned_to (Work Queue: My cases)")
    a = ap.parse_args()
    ctx = AppContext(root=Path(a.root), authority_path=None,
                     reviewer=Reviewer(reviewer_id=a.reviewer_id, role="analyst", kind="TEST"), uc042_root=None)
    demo = DemoScenarios(Path(a.scenarios))
    out = []
    for sid, it in sorted(demo.items.items(), key=lambda kv: TEXT[kv[0]]["order"]):
        sha = it["meta"]["zip"]["sha256"]
        existing = [r for r in ctx.cases.refs() if (ctx.cases.detail(r).get("zip") or {}).get("sha256") == sha]
        if existing:
            out.append({"scenario": sid, "action": "skipped (already present)", "case_refs": existing})
            continue
        c = demo.load(ctx, sid, assigned_to=a.assign_to)
        out.append({"scenario": sid, "action": "registered", "case_ref": c["case_ref"], "status": c["status"],
                    "customer": c["customer_name"], "period": c["reporting_period"], "assigned_to": c.get("assigned_to"),
                    "zip": c["zip"]["filename"],
                    "zip_sha256": c["zip"]["sha256"]})
    print(json.dumps({"workspace": str(ctx.root), "results": out}, indent=1))


if __name__ == "__main__":
    main()
