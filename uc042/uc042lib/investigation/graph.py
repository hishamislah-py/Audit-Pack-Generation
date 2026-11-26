"""Fixed LangGraph investigation workflow (V1). LangGraph controls the sequence; the LLM is called in one node only.

Error handling: every node is guarded. Expected failures (invalid IDs, retrieval/integrity errors, provider errors) and
unexpected exceptions alike become a structured FAILED result through validate_findings; unexpected ones are also logged
with their traceback. Only an immutability violation on an existing published artefact is raised to the caller.
"""
import functools
import logging
import time
from . import det_retrieval
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import config as settings
from . import roots as input_roots
from .llm import LLMCallError, LLMConfigurationError, redact
from .models import InvestigationResult, LLMInvestigationOutput, ModelMetadata
from .packet import Collector, build_case, build_packet, build_scope, retrieve
from .persistence import investigation_id, persist
from .retrieval import EvidenceStore, RetrievalError, load_pack
from .routing import ROUTES, route_for
from .tool_loop import run_tool_loop
from .tools import TOOL_REGISTRY_VERSION
from .validation import classification_summary, normalise_supporting_records, validate_output

log = logging.getLogger("uc042.investigation")


class InvestigationState(TypedDict, total=False):
    pack_id: str
    exception_id: str
    pack: dict
    case: dict
    scope: dict
    route: str
    retrieval: dict
    packet: dict
    llm_output: dict
    llm_meta: dict
    result: dict
    error: str
    error_stage: str
    artefact_path: str
    persist_outcome: str
    persist_error: str
    trace: list
    # V2 tools mode (the loop's own message history, budgets and dedup state live in tool_loop.ToolLoopState)
    investigation_mode: str
    ledger: dict          # accumulated evidence: initial packet + tool results, with allowed_citation_ids and ledger_sha256
    tool_calls: list      # tool execution transcript
    tool_summary: dict    # calls, rounds, stop reason, status, tools used, token usage
    execution: dict       # the originating audit-run execution (submission, run, authorisation, job); empty otherwise


def _cfg(config_, key, default=None):
    return (config_ or {}).get("configurable", {}).get(key, default)


def _trace(state, node, started, **extra):
    return list(state.get("trace", [])) + [dict(node=node, seconds=round(time.monotonic() - started, 3), **extra)]


def _guarded(stage):
    """Turn any exception escaping a node into error state (routed to validate_findings) and log it with its traceback."""
    def wrap(fn):
        @functools.wraps(fn)
        def node(state, config=None):
            t = time.monotonic()
            try:
                return fn(state, config)
            except Exception as e:
                log.exception("unexpected error in %s (pack %s, exception %s)", stage, state.get("pack_id"), state.get("exception_id"))
                return {"error": redact(f"unexpected error: {e.__class__.__name__}: {str(e)[:300]}"), "error_stage": stage,
                        "trace": _trace(state, stage, t, ok=False, unexpected=True)}
        return node
    return wrap


# ---------------------------------------------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------------------------------------------
@_guarded("load_investigation_case")
def load_investigation_case(state, config=None):
    t = time.monotonic()
    try:
        if not config_ok_exception(state.get("exception_id")):
            raise RetrievalError(f"invalid exception_id format: {state.get('exception_id')!r}")
        pack = load_pack(state["pack_id"], _cfg(config, "packs_root"))
        case = build_case(pack, state["exception_id"])
        return {"pack": pack, "case": case, "trace": _trace(state, "load_investigation_case", t, ok=True)}
    except (RetrievalError, KeyError) as e:
        return {"error": str(e).strip("'\""), "error_stage": "load_investigation_case",
                "trace": _trace(state, "load_investigation_case", t, ok=False)}


def config_ok_exception(exception_id):
    return bool(settings.EXCEPTION_ID_RE.match(exception_id or ""))


@_guarded("identify_investigation_scope")
def identify_investigation_scope(state, config=None):
    t = time.monotonic()
    return {"scope": build_scope(state["case"]), "trace": _trace(state, "identify_investigation_scope", t)}


@_guarded("route_investigation")
def route_investigation(state, config=None):
    t = time.monotonic()
    case = state["case"]
    route = route_for(case["exception"], case["candidates"], case["results"])
    if route not in ROUTES:
        raise ValueError(f"router returned unknown route {route!r}")
    if state.get("investigation_mode") == "deterministic" and not det_retrieval.supported(route):
        # phase 6: no deterministic retrieval plan for this route yet -> the bounded fallback is today's tools mode
        return {"route": route, "investigation_mode": "tools",
                "trace": _trace(state, "route_investigation", t, route=route,
                                fallback=f"route {route} has no deterministic retrieval plan; tools mode used")}
    return {"route": route, "trace": _trace(state, "route_investigation", t, route=route)}


def make_retrieval_node(route):
    def retrieve_relevant_evidence(state, config=None):
        t = time.monotonic()
        try:
            store = EvidenceStore(state["pack"], _cfg(config, "datasets_root"))
            col = retrieve(route, state["case"], store)
            register = None
            if state.get("investigation_mode") == "deterministic":  # phase 6: Python expands with the tool functions
                register = det_retrieval.expand(col, state["case"], route, store)
            return {"retrieval": {"records": list(col.records.values()), "relationships": col.relationships,
                                  "searches": col.searches, "truncated": col.truncated, "pruning_register": register},
                    "trace": _trace(state, f"retrieve_relevant_evidence[{route}]", t, records=len(col.records))}
        except RetrievalError as e:
            return {"error": str(e), "error_stage": "retrieve_relevant_evidence",
                    "trace": _trace(state, f"retrieve_relevant_evidence[{route}]", t, ok=False)}
    retrieve_relevant_evidence.__name__ = f"retrieve_{route}"
    return _guarded(f"retrieve_{route}")(retrieve_relevant_evidence)


@_guarded("build_evidence_packet")
def build_evidence_packet(state, config=None):
    t = time.monotonic()
    col = Collector()
    r = state["retrieval"]
    for item in r["records"]:
        col.records[item["evidence_id"]] = item
    col.relationships, col.searches, col.truncated = r["relationships"], r["searches"], r["truncated"]
    packet = build_packet(state["case"], state["scope"], state["route"], col)
    if r.get("pruning_register") is not None:  # deterministic packet: rule version + pruning register in the hash
        packet = det_retrieval.finalise_packet(packet, r["pruning_register"])
    return {"packet": packet, "trace": _trace(state, "build_evidence_packet", t, records=len(packet["source_records"]),
                                              citable_ids=len(packet["allowed_citation_ids"]))}


def _investigator_meta(investigator):
    return {"provider": getattr(investigator, "provider", "none"), "model": getattr(investigator, "model", "none"),
            "simulated": getattr(investigator, "simulated", False)}


def _single_request_guard(investigator, packet):
    """Estimated input of a single-request investigation (instructions + first message), checked before sending."""
    if not getattr(investigator, "uses_model_view", False):
        return None
    from .prompts import SYSTEM_PROMPT, model_user_message
    estimate = (len(SYSTEM_PROMPT) + len(model_user_message(packet))) // 3
    limit = settings.single_request_max_input_tokens()
    if estimate > limit:
        return f"input_token_budget: estimated request input of {estimate} tokens exceeds the limit of {limit}; no request was sent"
    return None


def _view_meta(investigator, packet):
    """Phase 4: the model view's version and SHA-256 when the adapter sends it (OpenAI); nothing otherwise."""
    if not getattr(investigator, "uses_model_view", False) or not packet:
        return {}
    from .packet_view import MODEL_VIEW_VERSION, model_view_sha256
    return {"model_view_version": MODEL_VIEW_VERSION, "model_view_sha256": model_view_sha256(packet)}


def _tools_investigation(state, config, investigator, t):
    """V2: run the nested tool-calling subgraph and map its final state into the outer state."""
    if not getattr(investigator, "supports_tools", False):
        raise LLMConfigurationError(f"provider {getattr(investigator, 'provider', '?')!r} does not support "
                                    "UC042_INVESTIGATION_MODE=tools; use UC042_LLM_PROVIDER=openai or mode 'fixed'")
    store = EvidenceStore(state["pack"], _cfg(config, "datasets_root"))
    limits = _cfg(config, "tool_limits") or settings.tool_limits()
    loop = run_tool_loop(investigator, store, state["packet"], state["case"], limits)
    calls = loop.get("tool_calls", [])
    summary = {"status": loop.get("status"), "stop_reason": loop.get("stop_reason"), "llm_calls": loop.get("llm_calls", 0),
               "tool_calls_requested": loop.get("tool_call_count", 0), "tool_rounds": loop.get("tool_round", 0),
               "tools_executed": sum(c["status"] in ("OK", "NOT_FOUND") for c in calls),
               "tools_deduplicated": sum(c["deduplicated"] for c in calls),
               "tools_rejected_or_failed": sum(c["status"] in ("REJECTED", "ERROR") for c in calls),
               "tools_refused_budget": sum(c["status"] == "BUDGET_EXHAUSTED" for c in calls),
               "tools_used": [c["tool"] for c in calls],
               "records_initial": len(state["packet"]["source_records"]), "records_final": len(loop["ledger"]["source_records"]),
               "limits": limits}
    meta = dict(_investigator_meta(investigator), **_view_meta(investigator, state["packet"]), attempts=loop.get("llm_calls", 0),
                usage=dict(loop.get("usage", {}), latency_seconds=round(time.monotonic() - t, 2)),
                provider_response={"responses": loop.get("provider_responses", [])})
    upd = {"ledger": loop["ledger"], "tool_calls": calls, "tool_summary": summary, "llm_meta": meta,
           "trace": _trace(state, "ai_investigation[tools]", t, ok=loop.get("status") == "COMPLETED", llm_calls=summary["llm_calls"],
                           tool_calls=summary["tool_calls_requested"], rounds=summary["tool_rounds"], stop=summary["stop_reason"])}
    if loop.get("status") == "COMPLETED":
        return dict(upd, llm_output=loop["final_output"])
    log.warning("tool-calling investigation of %s failed: %s", state.get("exception_id"), loop.get("error"))
    return dict(upd, error=f"ToolLoop[{loop.get('stop_reason')}]: {redact(loop.get('error', ''))}", error_stage="ai_investigation")


@_guarded("ai_investigation")
def ai_investigation(state, config=None):
    t = time.monotonic()
    investigator = _cfg(config, "investigator")
    try:
        if investigator is None:
            raise LLMConfigurationError("no investigator configured")
        if state.get("investigation_mode") == "tools":
            return _tools_investigation(state, config, investigator, t)
        guard = _single_request_guard(investigator, state["packet"])
        if guard:  # phase 6: no request is sent when the evidence would exceed the input budget
            return {"error": guard, "error_stage": "ai_investigation", "llm_meta": _investigator_meta(investigator),
                    "trace": _trace(state, "ai_investigation", t, ok=False, kind="input_token_budget")}
        out, meta = investigator.investigate(state["packet"])
        meta = dict(meta, **_investigator_meta(investigator), **_view_meta(investigator, state["packet"]))
        return {"llm_output": out.model_dump(), "llm_meta": meta, "trace": _trace(state, "ai_investigation", t, ok=True)}
    except RetrievalError as e:
        return {"error": f"RetrievalError: {e}", "error_stage": "ai_investigation", "llm_meta": _investigator_meta(investigator),
                "trace": _trace(state, "ai_investigation", t, ok=False)}
    except (LLMConfigurationError, LLMCallError) as e:
        log.warning("investigation model call failed for %s: %s", state.get("exception_id"), e)
        return {"error": f"{e.__class__.__name__}: {e}", "error_stage": "ai_investigation",
                # phase 3: a failed fixed-mode request keeps its billed usage and per-request records
                "llm_meta": dict(getattr(e, "telemetry", None) or {}, **_investigator_meta(investigator)),
                "trace": _trace(state, "ai_investigation", t, ok=False, kind=getattr(e, "kind", "configuration"))}


def _base_fields(state):
    case, packet = state.get("case") or {}, state.get("packet") or {}
    x = case.get("exception", {})
    return dict(investigation_id="", pack_id=state.get("pack_id", ""), pack_content_sha256=case.get("pack_content_sha256", ""),
                exception_id=state.get("exception_id", ""), original_exception_status=x.get("status", ""),
                original_review_status=x.get("review_status", ""), original_evidence_status=x.get("evidence_status", ""),
                investigation_scope=state.get("scope", {}), investigation_route=state.get("route", ""),
                evidence_packet_sha256=packet.get("packet_sha256", ""), investigation_mode=_mode(state),
                evidence_ledger_sha256=(state.get("ledger") or {}).get("ledger_sha256", ""),
                tool_summary={k: v for k, v in (state.get("tool_summary") or {}).items()},
                investigated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                execution=dict(state.get("execution") or {}))


def _mode(state):
    m = state.get("investigation_mode")
    return m if m in ("tools", "deterministic") else "fixed"


def _workflow_version(mode):
    return {"tools": settings.TOOLS_WORKFLOW_VERSION, "deterministic": settings.DET_WORKFLOW_VERSION}.get(mode, settings.WORKFLOW_VERSION)


def _model_metadata(state):
    meta = state.get("llm_meta")
    if not meta:
        return None
    tools_mode = _mode(state) == "tools"
    return ModelMetadata(provider=meta.get("provider", ""), model=meta.get("model", ""), simulated=meta.get("simulated", False),
                         prompt_version=settings.TOOLS_PROMPT_VERSION if tools_mode else settings.PROMPT_VERSION,
                         workflow_version=_workflow_version(_mode(state)),
                         findings_schema_version=settings.FINDINGS_SCHEMA_VERSION, attempts=meta.get("attempts", 0),
                         usage=meta.get("usage", {}), provider_response=meta.get("provider_response", {}),
                         investigation_mode=_mode(state), tool_registry_version=TOOL_REGISTRY_VERSION if tools_mode else "",
                         model_view_version=meta.get("model_view_version", ""), model_view_sha256=meta.get("model_view_sha256", ""),
                         retrieval_rule_version=(state.get("packet") or {}).get("retrieval_rule_version", ""))


def validate_findings(state, config=None):
    """Deterministic validation; also builds FAILED results for errors from earlier nodes. Never raises for bad data."""
    t = time.monotonic()
    try:
        base, model_meta = _base_fields(state), _model_metadata(state)
        if state.get("error"):
            res = InvestigationResult(**base, investigation_status="FAILED", validation_status="NOT_VALIDATED",
                                      failure_reason=f"{state.get('error_stage')}: {state['error']}", model_metadata=model_meta)
            return {"result": res.model_dump(), "trace": _trace(state, "validate_findings", t, status="FAILED")}
        packet = state["packet"]
        evidence = state.get("ledger") or packet  # tools mode: citations are checked against the accumulated ledger
        out = LLMInvestigationOutput.model_validate(state["llm_output"])
        out, norm_notes = normalise_supporting_records(out, evidence)   # recorded; never widens support (validation.py)
        errors, notes, refs = validate_output(out, evidence, state["case"])
        notes = norm_notes + notes
        body = out.model_dump()
        body["evidence_references"] = refs
        res = InvestigationResult(**base, **body, investigation_status="COMPLETED",
                                  validation_status="REJECTED" if errors else "VALID",
                                  validation_findings=errors + notes, model_metadata=model_meta,
                                  classification_summary=classification_summary(out, evidence))
        if not errors:
            res.investigation_id = investigation_id(res, packet)
        return {"result": res.model_dump(), "trace": _trace(state, "validate_findings", t,
                                                            status=res.validation_status, errors=len(errors))}
    except Exception as e:
        log.exception("unexpected error in validate_findings (exception %s)", state.get("exception_id"))
        res = InvestigationResult(**_base_fields(state), investigation_status="FAILED", validation_status="NOT_VALIDATED",
                                  failure_reason=redact(f"validate_findings: unexpected error: {e.__class__.__name__}: {str(e)[:300]}"))
        return {"result": res.model_dump(), "trace": _trace(state, "validate_findings", t, status="FAILED", unexpected=True)}


def persist_findings(state, config=None):
    """Write-once persistence. Storage I/O failures are recorded as PERSIST_FAILED (nothing partial is left behind);
    an ImmutabilityError (existing artefact differs) is raised, because it signals tampering or an ID collision."""
    t = time.monotonic()
    res = InvestigationResult.model_validate(state["result"])
    tools_mode = _mode(state) == "tools"
    run = {"investigation_mode": _mode(state),
           "workflow_version": _workflow_version(_mode(state)),
           "prompt_version": settings.TOOLS_PROMPT_VERSION if tools_mode else settings.PROMPT_VERSION,
           "trace": state.get("trace", []), "route": state.get("route", "")}
    extra = None
    if state.get("ledger") is not None:
        extra = {"evidence_ledger.json": state["ledger"],
                 "tool_calls.json": {"tool_registry_version": TOOL_REGISTRY_VERSION, "exception_id": res.exception_id,
                                     "pack_id": res.pack_id, "summary": state.get("tool_summary", {}),
                                     "tool_calls": state.get("tool_calls", [])}}
    try:
        path, outcome = persist(res, state.get("packet"), run, _cfg(config, "investigations_root"), extra=extra)
    except OSError as e:
        log.error("persisting the investigation of %s failed: %s", res.exception_id, e)
        return {"artefact_path": "", "persist_outcome": "PERSIST_FAILED",
                "persist_error": f"{e.__class__.__name__}: {str(e)[:300]}",
                "trace": _trace(state, "persist_findings", t, outcome="PERSIST_FAILED")}
    return {"artefact_path": path, "persist_outcome": outcome, "trace": _trace(state, "persist_findings", t, outcome=outcome)}


# ---------------------------------------------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------------------------------------------
def _after(node_ok):
    def edge(state):
        return "validate_findings" if state.get("error") else node_ok
    return edge


def _after_route(state):
    return "validate_findings" if state.get("error") else f"retrieve_{state['route']}"


def build_graph():
    g = StateGraph(InvestigationState)
    g.add_node("load_investigation_case", load_investigation_case)
    g.add_node("identify_investigation_scope", identify_investigation_scope)
    g.add_node("route_investigation", route_investigation)
    for r in ROUTES:
        g.add_node(f"retrieve_{r}", make_retrieval_node(r))
    g.add_node("build_evidence_packet", build_evidence_packet)
    g.add_node("ai_investigation", ai_investigation)
    g.add_node("validate_findings", validate_findings)
    g.add_node("persist_findings", persist_findings)

    g.add_edge(START, "load_investigation_case")
    g.add_conditional_edges("load_investigation_case", _after("identify_investigation_scope"),
                            ["identify_investigation_scope", "validate_findings"])
    g.add_conditional_edges("identify_investigation_scope", _after("route_investigation"),
                            ["route_investigation", "validate_findings"])
    g.add_conditional_edges("route_investigation", _after_route, [f"retrieve_{r}" for r in ROUTES] + ["validate_findings"])
    for r in ROUTES:
        g.add_conditional_edges(f"retrieve_{r}", _after("build_evidence_packet"), ["build_evidence_packet", "validate_findings"])
    g.add_conditional_edges("build_evidence_packet", _after("ai_investigation"), ["ai_investigation", "validate_findings"])
    g.add_edge("ai_investigation", "validate_findings")
    g.add_edge("validate_findings", "persist_findings")
    g.add_edge("persist_findings", END)
    return g.compile()


GRAPH = None


def run_investigation(pack_id, exception_id, investigator, packs_root=None, datasets_root=None, investigations_root=None,
                      mode="fixed", tool_limits=None, profile=None, period_id=None, execution=None):
    """Invoke the graph for one exception. mode 'fixed' (V1, default) or 'tools' (V2 nested tool-calling subgraph); the
    CLI passes the UC042_INVESTIGATION_MODE setting explicitly. Input roots: explicit packs and datasets roots, or a
    profile / period (uc042lib.investigation.roots); they are validated before anything is read, and a pack outside the
    profile's periods is refused (InvestigationRootsError). execution: the originating audit-run execution (submission,
    run, authorisation, job); it is stored with the result and makes that execution's artefact its own. Returns the final state."""
    global GRAPH
    if mode not in settings.MODES:
        raise ValueError(f"unknown investigation mode {mode!r}")
    approved = input_roots.resolve(profile, period_id, packs_root, datasets_root, investigations_root)
    approved.check_pack_id(pack_id)
    if GRAPH is None:
        GRAPH = build_graph()
    cfg = {"configurable": {"investigator": investigator, **approved.as_kwargs(), "tool_limits": tool_limits}}
    return GRAPH.invoke({"pack_id": pack_id, "exception_id": exception_id, "trace": [], "investigation_mode": mode,
                         "execution": dict(execution or {})}, config=cfg)
