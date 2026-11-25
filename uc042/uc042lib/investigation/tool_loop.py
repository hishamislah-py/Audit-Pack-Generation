"""V2 nested LangGraph subgraph: the bounded tool-calling investigation loop (UC042_INVESTIGATION_MODE=tools).

    START -> llm_step -> inspect_response --tool calls--> validate_tool_request -> execute_tools -> append_tool_results -> llm_step
                                          --final-------> extract_structured_findings -> END
                                          --retry-------> llm_step          (one correction for an invalid final answer)
                                          --error/limit-> controlled_failure -> END

The model only requests tools. Python validates each request (registry name, strict Pydantic arguments, budgets,
duplicates), executes it through the guarded EvidenceStore, adds the records to the evidence ledger through the
Collector, and returns a function_call_output with the original call_id. Message history, the tool transcript and
errors are append-only. Limits: tool calls, rounds, records per call, total records, estimated input tokens and an
overall wall-clock budget. When the tool budget is exhausted the model gets one opportunity to return findings.
"""
import json
import logging
import operator
import time
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from . import tools
from .llm import LLMCallError
from .models import LLMInvestigationOutput
from .packet import build_ledger, collector_from_packet
from .prompts import TOOLS_SYSTEM_PROMPT, tools_user_message

log = logging.getLogger("uc042.investigation")
_clock = time.monotonic  # patchable in tests without affecting LangGraph or other modules


class ToolLoopState(TypedDict, total=False):
    packet: dict                                       # initial evidence packet (read-only)
    case: dict                                         # investigation case from the pack (read-only)
    limits: dict
    started: float                                     # time.monotonic() when the loop started
    messages: Annotated[list, operator.add]            # Responses API input history (append-only)
    tool_calls: Annotated[list, operator.add]          # tool execution transcript (append-only)
    tool_errors: Annotated[list, operator.add]         # rejected / failed tool requests (append-only)
    provider_responses: Annotated[list, operator.add]  # response IDs, resolved model, status per model call
    usage: dict                                        # accumulated token usage
    llm_calls: int
    tool_call_count: int                               # every requested call counts, including rejected and duplicates
    tool_round: int
    ledger: dict                                       # accumulated evidence, packet-shaped, incl. allowed_citation_ids
    dedup: dict                                        # canonical (tool, arguments) -> first result
    pending: list                                      # function calls in the latest response
    planned: list                                      # validated requests for the latest response
    results: list                                      # function_call_output payloads for the latest response
    turn_kind: str                                     # tool_calls | final | invalid_final | retry | error
    candidate: dict                                    # parsed final output awaiting extraction
    budget_exhausted: bool                             # tools were refused; one final opportunity granted
    corrected: bool                                    # one correction already requested
    status: str                                        # RUNNING | COMPLETED | FAILED
    stop_reason: str
    error: str
    final_output: dict


def _cfg(config_, key):
    return (config_ or {}).get("configurable", {}).get(key)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _add_usage(total, usage):
    out = dict(total or {})
    for k, v in (usage or {}).items():
        if isinstance(v, (int, float)):
            out[k] = (out.get(k) or 0) + v
    return out


def _fail(reason, message):
    return {"status": "FAILED", "stop_reason": reason, "error": message, "turn_kind": "error"}


def estimate_input_tokens(messages, tool_defs):
    """Conservative pre-request estimate (about 3 characters per token) of instructions + history + tool schemas."""
    chars = len(TOOLS_SYSTEM_PROMPT) + len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tool_defs))
    return chars // 3


def canonical_key(name, arguments):
    return f"{name}:{json.dumps(arguments, sort_keys=True, separators=(',', ':'))}"


# --------------------------------------------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------------------------------------------
def llm_step(state, config=None):
    inv, tool_defs, lim = _cfg(config, "investigator"), _cfg(config, "tool_definitions"), state["limits"]
    remaining = lim["total_timeout"] - (_clock() - state["started"])
    if remaining <= 1:
        return _fail("timeout_budget", f"overall investigation time budget of {lim['total_timeout']:.0f}s exhausted")
    estimate = estimate_input_tokens(state["messages"], tool_defs)
    if estimate > lim["max_input_tokens"]:
        return _fail("input_token_budget", f"estimated request input of {estimate} tokens exceeds the limit of {lim['max_input_tokens']}")
    calls = state.get("llm_calls", 0) + 1
    try:
        turn = inv.tool_turn(state["messages"], tool_defs, timeout=min(inv.timeout, remaining))
    except LLMCallError as e:
        turn = getattr(e, "turn", None) or {}
        upd = {"llm_calls": calls, "usage": _add_usage(state.get("usage"), turn.get("usage")),
               "provider_responses": [turn["provider_response"]] if turn.get("provider_response") else []}
        if e.kind in ("invalid_output", "missing_output") and turn.get("output_items") is not None:
            return dict(upd, messages=turn["output_items"], turn_kind="invalid_final", error=str(e))
        return dict(upd, **_fail(e.kind, str(e)))
    upd = {"llm_calls": calls, "usage": _add_usage(state.get("usage"), turn["usage"]), "messages": turn["output_items"],
           "provider_responses": [turn["provider_response"]]}
    if turn["kind"] == "tool_calls":
        return dict(upd, turn_kind="tool_calls", pending=turn["function_calls"])
    return dict(upd, turn_kind="final", candidate=turn["parsed"].model_dump())


def inspect_response(state, config=None):
    kind = state.get("turn_kind")
    if state.get("status") == "FAILED" or kind in ("final", None):
        return {}
    if kind == "invalid_final":
        if state.get("corrected"):
            return _fail("invalid_final_output", state.get("error", "final output invalid"))
        return {"messages": [{"role": "user", "content": "Your final answer did not match the required JSON schema: "
                              f"{state.get('error', '')[:800]}\nReturn the corrected final JSON object."}],
                "corrected": True, "turn_kind": "retry"}
    if kind == "tool_calls" and state.get("budget_exhausted"):
        return _fail("budget_exhausted_without_findings",
                     "the model requested more tools after the tool budget was exhausted instead of returning findings")
    return {}


def validate_tool_request(state, config=None):
    lim = state["limits"]
    count, rnd = state.get("tool_call_count", 0), state.get("tool_round", 0)
    planned, errors = [], []
    for c in state["pending"]:
        entry = {"call_id": c["call_id"], "tool": c["name"], "round": rnd + 1, "arguments": None,
                 "raw_arguments": str(c.get("arguments") or "")[:2000]}
        if rnd >= lim["max_rounds"] or count >= lim["max_tool_calls"]:
            which = "rounds" if rnd >= lim["max_rounds"] else "tool calls"
            planned.append(dict(entry, status="BUDGET_EXHAUSTED", error=f"tool budget exhausted (maximum {which} reached); not executed"))
            continue
        count += 1
        args, err = tools.parse_request(c["name"], c.get("arguments"))
        if err:
            planned.append(dict(entry, status="REJECTED", error=err))
            errors.append({"call_id": c["call_id"], "tool": c["name"], "error": err})
            continue
        planned.append(dict(entry, status="VALID", arguments=args.model_dump()))
    return {"planned": planned, "tool_call_count": count, "tool_errors": errors}


def execute_tools(state, config=None):
    store, lim = _cfg(config, "store"), state["limits"]
    col = collector_from_packet(state["ledger"])
    dedup = dict(state.get("dedup") or {})
    known_conflicts = {c["conflict_id"] for c in state["ledger"]["conflicts"]}
    transcript, results, errors = [], [], []
    for p in state["planned"]:
        started, at = _clock(), _now()
        rec = {"call_id": p["call_id"], "tool": p["tool"], "round": p["round"], "arguments": p["arguments"],
               "requested_at": at, "status": p["status"], "deduplicated": False, "evidence_ids": [], "new_evidence_ids": [],
               "search_ids": [], "records_returned": 0, "truncated": False, "error": p.get("error", "")}
        if p["status"] in ("REJECTED", "BUDGET_EXHAUSTED"):
            rec["raw_arguments"] = p["raw_arguments"]
            payload = {"status": p["status"], "error": p["error"]}
        else:
            key = canonical_key(p["tool"], p["arguments"])
            if key in dedup:
                prior = dedup[key]
                rec.update(status="DEDUPLICATED", deduplicated=True, evidence_ids=prior["evidence_ids"], search_ids=prior["search_ids"])
                payload = {"status": "DEDUPLICATED", "evidence_ids": prior["evidence_ids"], "search_ids": prior["search_ids"],
                           "note": f"Identical request already executed (call {prior['call_id']}); its records are already in the evidence."}
            else:
                args = tools.REGISTRY[p["tool"]].args_model.model_validate(p["arguments"])
                try:
                    payload = tools.execute(p["tool"], args, store, col, lim["max_records_per_call"])
                    rec.update(status=payload["status"], evidence_ids=payload["evidence_ids"], new_evidence_ids=payload["new_evidence_ids"],
                               search_ids=payload["search_ids"], records_returned=len(payload["evidence_ids"]), truncated=payload["truncated"])
                    dedup[key] = {"call_id": p["call_id"], "evidence_ids": payload["evidence_ids"], "search_ids": payload["search_ids"]}
                except tools.ToolInputError as e:
                    rec.update(status="REJECTED", error=str(e))
                    payload = {"status": "REJECTED", "error": str(e)}
                except Exception as e:  # a tool bug is reported to the model and the transcript, never hidden
                    log.exception("tool %s failed (call %s)", p["tool"], p["call_id"])
                    rec.update(status="ERROR", error=f"tool execution failed: {e.__class__.__name__}: {str(e)[:200]}")
                    payload = {"status": "ERROR", "error": "the tool failed to execute; try a different request"}
        if rec["status"] in ("REJECTED", "ERROR"):
            errors.append({"call_id": p["call_id"], "tool": p["tool"], "error": rec["error"]})
        rec["latency_ms"] = round((_clock() - started) * 1000, 1)
        transcript.append(rec)
        results.append({"call_id": p["call_id"], "payload": payload})
    ledger = build_ledger(state["packet"], state["case"], col)
    new_conflicts = [c for c in ledger["conflicts"] if c["conflict_id"] not in known_conflicts]
    if new_conflicts and results:  # deterministic conflicts found in the newly retrieved evidence
        results[-1]["payload"] = dict(results[-1]["payload"], new_conflicts=new_conflicts)
    # tool_errors from validation were already recorded; add only execution-time rejections and failures here
    validation_rejects = {e["call_id"] for e in state.get("tool_errors") or []}
    return {"ledger": ledger, "dedup": dedup, "results": results, "tool_calls": transcript,
            "tool_errors": [e for e in errors if e["call_id"] not in validation_rejects]}


def append_tool_results(state, config=None):
    lim, rnd = state["limits"], state.get("tool_round", 0) + 1
    exhausted = state.get("budget_exhausted", False) or any(r["payload"]["status"] == "BUDGET_EXHAUSTED" for r in state["results"])
    last_round = rnd >= lim["max_rounds"] or state.get("tool_call_count", 0) >= lim["max_tool_calls"]
    outputs = []
    for r in state["results"]:
        payload = r["payload"]
        if exhausted or last_round:
            payload = dict(payload, budget="The tool budget is now exhausted. Do not call more tools; return your final JSON "
                                             "findings using the evidence already collected.")
        outputs.append({"type": "function_call_output", "call_id": r["call_id"], "output": json.dumps(payload, ensure_ascii=False)})
    # once the budget is used up the model has exactly one opportunity to return findings; another tool request fails
    return {"messages": outputs, "tool_round": rnd, "budget_exhausted": exhausted or last_round, "pending": [], "planned": [],
            "results": []}


def extract_structured_findings(state, config=None):
    try:
        out = LLMInvestigationOutput.model_validate(state["candidate"])
    except Exception as e:
        return _fail("invalid_final_output", f"final output failed validation: {str(e)[:300]}")
    return {"final_output": out.model_dump(), "status": "COMPLETED", "stop_reason": "final_answer"}


def controlled_failure(state, config=None):
    return {"status": "FAILED", "stop_reason": state.get("stop_reason") or "failed", "error": state.get("error") or "investigation failed"}


def _route(state):
    if state.get("status") == "FAILED":
        return "controlled_failure"
    return {"final": "extract_structured_findings", "retry": "llm_step", "tool_calls": "validate_tool_request"}.get(
        state.get("turn_kind"), "controlled_failure")


def build_tool_loop():
    g = StateGraph(ToolLoopState)
    for name, fn in (("llm_step", llm_step), ("inspect_response", inspect_response), ("validate_tool_request", validate_tool_request),
                     ("execute_tools", execute_tools), ("append_tool_results", append_tool_results),
                     ("extract_structured_findings", extract_structured_findings), ("controlled_failure", controlled_failure)):
        g.add_node(name, fn)
    g.add_edge(START, "llm_step")
    g.add_edge("llm_step", "inspect_response")
    g.add_conditional_edges("inspect_response", _route,
                            ["validate_tool_request", "extract_structured_findings", "llm_step", "controlled_failure"])
    g.add_edge("validate_tool_request", "execute_tools")
    g.add_edge("execute_tools", "append_tool_results")
    g.add_edge("append_tool_results", "llm_step")
    g.add_conditional_edges("extract_structured_findings", lambda s: "controlled_failure" if s.get("status") == "FAILED" else END,
                            ["controlled_failure", END])
    g.add_edge("controlled_failure", END)
    return g.compile()


TOOL_LOOP = None


def run_tool_loop(investigator, store, packet, case, limits):
    """Run the bounded loop for one exception. Returns the final ToolLoopState (status COMPLETED or FAILED)."""
    global TOOL_LOOP
    if TOOL_LOOP is None:
        TOOL_LOOP = build_tool_loop()
    state = {"packet": packet, "case": case, "limits": limits, "started": _clock(),
             "messages": [{"role": "user", "content": tools_user_message(packet, limits)}],
             "ledger": build_ledger(packet, case, collector_from_packet(packet)), "dedup": {}, "usage": {},
             "llm_calls": 0, "tool_call_count": 0, "tool_round": 0, "status": "RUNNING"}
    cfg = {"configurable": {"investigator": investigator, "store": store, "tool_definitions": investigator.tool_definitions()},
           "recursion_limit": 8 * (limits["max_rounds"] + 4)}
    return TOOL_LOOP.invoke(state, cfg)
