"""Orchestrator and CLI for the AI investigation layer.

Usage (from the uc042/ folder; settings come from the environment or a local, uncommitted .env):
    python -m uc042lib.investigation.run --check-provider                 # authenticate + model lookup; no tokens used
    python -m uc042lib.investigation.run <pack_id> [<exception_id>]       # live investigation (UC042_LLM_PROVIDER=openai)
    UC042_LLM_PROVIDER=offline python -m uc042lib.investigation.run <pack_id>   # simulated output, for testing only
    python -m uc042lib.investigation.run --period PER-2026-03 <pack_id>   # historical demonstration roots (demo_history)

Input roots (uc042lib.investigation.roots): --profile / --period, else UC042_INVESTIGATION_PROFILE or
UC042_INVESTIGATION_PERIOD, else the September profile. They are validated before anything runs.

Without an exception ID every exception in the pack is investigated, each independently: a failure in one is recorded
and the others continue. A pack without exceptions is reported as such and no investigation is created.
"""
import argparse
import json
import logging
import sys

from . import config
from . import roots as input_roots
from .graph import run_investigation
from .llm import LLMCallError, LLMConfigurationError, investigator_from_env, redact
from .retrieval import RetrievalError, load_pack

log = logging.getLogger("uc042.investigation")
OK_PERSIST = ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL")


def _isolated_failure(eid, original, e):
    return {"exception_id": eid, "route": "", "investigation_status": "FAILED", "validation_status": "NOT_VALIDATED",
            "assessment": None, "investigation_id": "", "persist_outcome": "NOT_PERSISTED", "artefact": "",
            "original_exception_status": original.get("status", ""), "original_review_status": original.get("review_status", ""),
            "failure_reason": redact(f"unhandled: {e.__class__.__name__}: {str(e)[:300]}"), "validation_findings": []}


def investigate_pack(pack_id, investigator, exception_ids=None, mode="fixed", tool_limits=None, profile=None, period_id=None,
                     **roots):
    approved = input_roots.resolve(profile, period_id, roots.get("packs_root"), roots.get("datasets_root"),
                                   roots.get("investigations_root"))
    approved.check_pack_id(pack_id)
    roots = approved.as_kwargs()
    pack = load_pack(pack_id, approved.packs_root)
    by_id = {x["exception_id"]: x for x in pack["exception_register"]["exceptions"]}
    if not by_id and not exception_ids:
        return {"pack_id": pack_id, "status": "NO_EXCEPTIONS",
                "message": "The pack contains no exceptions; no investigation was created.", "investigations": []}
    runs = []
    for eid in exception_ids or list(by_id):
        original = by_id.get(eid, {})
        try:
            s = run_investigation(pack_id, eid, investigator, mode=mode, tool_limits=tool_limits, **roots)
        except Exception as e:  # recorded per exception; the remaining exceptions still run
            log.exception("investigation of %s aborted", eid)
            runs.append(_isolated_failure(eid, original, e))
            continue
        r = s["result"]
        runs.append({"exception_id": eid, "route": s.get("route", ""), "investigation_status": r["investigation_status"],
                     "validation_status": r["validation_status"], "assessment": r.get("overall_evidence_assessment"),
                     "investigation_id": r["investigation_id"], "persist_outcome": s.get("persist_outcome"),
                     "artefact": s.get("artefact_path"), "original_exception_status": r["original_exception_status"],
                     "original_review_status": r["original_review_status"],
                     "failure_reason": r["failure_reason"] or s.get("persist_error", ""),
                     "validation_findings": r["validation_findings"],
                     "simulated": (r.get("model_metadata") or {}).get("simulated"),
                     "investigation_mode": r.get("investigation_mode"),
                     "tool_summary": {k: v for k, v in r.get("tool_summary", {}).items() if k != "limits"},
                     "usage": (r.get("model_metadata") or {}).get("usage", {})})
    return {"pack_id": pack_id, "status": "INVESTIGATED", "mode": mode, "investigations": runs}


def main():
    ap = argparse.ArgumentParser(description="UC-042 AI investigation (LangGraph V1)")
    ap.add_argument("pack_id", nargs="?")
    ap.add_argument("exception_id", nargs="?")
    ap.add_argument("--check-provider", action="store_true",
                    help="verify credentials and model availability without running an investigation")
    ap.add_argument("--mode", choices=config.MODES,
                    help="fixed (V1) or tools (V2 bounded tool calling); default from UC042_INVESTIGATION_MODE, else fixed")
    ap.add_argument("--profile", choices=sorted(input_roots.PROFILES),
                    help="input roots profile (default: from --period, UC042_INVESTIGATION_PROFILE/PERIOD, else september)")
    ap.add_argument("--period", help="reporting period PER-YYYY-MM; selects the profile that covers it")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not a.check_provider and not a.pack_id:
        ap.error("pack_id is required unless --check-provider is given")
    if not a.check_provider:
        try:  # the input boundary is validated before any provider is configured
            approved = input_roots.resolve(a.profile, a.period)
            approved.check_pack_id(a.pack_id)
        except input_roots.InvestigationRootsError as e:
            print(f"INPUT ROOTS ERROR: {e}", file=sys.stderr)
            sys.exit(2)
    try:
        mode = a.mode or config.investigation_mode()
        limits = config.tool_limits() if mode == "tools" else None
        investigator = investigator_from_env()
        if mode == "tools" and not getattr(investigator, "supports_tools", False):
            raise LLMConfigurationError(f"provider {investigator.provider!r} does not support tools mode; "
                                        "use UC042_LLM_PROVIDER=openai or UC042_INVESTIGATION_MODE=fixed")
    except (LLMConfigurationError, ValueError) as e:
        print(f"CONFIGURATION ERROR: {redact(e)}", file=sys.stderr)
        print(f"OPENAI_API_KEY configured: {'yes' if config.api_key_configured() else 'no'}", file=sys.stderr)
        sys.exit(2)
    if a.check_provider:
        if investigator.simulated:
            print(json.dumps({"provider": investigator.provider, "simulated": True, "available": True}))
            sys.exit(0)
        try:
            print(json.dumps(investigator.check_availability(), indent=1))
        except LLMCallError as e:
            print(f"PROVIDER CHECK FAILED: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    if investigator.simulated:
        print(f"NOTE: offline simulated investigator in use ({mode} mode); output is NOT AI analysis.", file=sys.stderr)
    else:
        print(f"NOTE: live investigation with {investigator.provider} model {investigator.model}, {mode} mode"
              + (f" (limits: {limits})" if limits else "") + ".", file=sys.stderr)
    try:
        summary = investigate_pack(a.pack_id, investigator, [a.exception_id] if a.exception_id else None,
                                   mode=mode, tool_limits=limits, **approved.as_kwargs())
    except RetrievalError as e:
        print(f"RETRIEVAL ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(summary, indent=1))
    ok = all(r["validation_status"] == "VALID" and r["persist_outcome"] in OK_PERSIST for r in summary["investigations"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
