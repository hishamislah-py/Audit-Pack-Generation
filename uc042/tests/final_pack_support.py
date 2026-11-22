"""Shared helpers for the final-pack tests (not a test module). Investigations are produced by the real OpenAIInvestigator,
graph, validation and persistence with only the HTTP layer mocked, so they are genuinely published and eligible (not
simulated) without network access. Everything is written to temporary folders."""
import copy
import glob
import hashlib
import json
import os
from pathlib import Path
from unittest import mock

from uc042lib.final_pack.model import ClosingSummaryOutput, Reviewer, ReviewRecord, SummaryItem, UnresolvedItem
from uc042lib.final_pack.summary import closing_summary_input, summary_sha256
from uc042lib.investigation import config
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import OfflineSimulatedInvestigator, OpenAIInvestigator
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()
USAGE = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200, "output_tokens_details": {"reasoning_tokens": 50},
         "input_tokens_details": {"cached_tokens": 0}}


def packet_for(scenario, exception_id):
    pack = load_pack(PACK[scenario])
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    return build_packet(case, build_scope(case), route, retrieve(route, case, EvidenceStore(pack)))


def investigation_output(scenario, exception_id, edit=None):
    """A schema-1.4 investigation output derived from the packet (the offline stub's content, with realistic text)."""
    out = OFFLINE.investigate(packet_for(scenario, exception_id))[0].model_dump()
    out["investigation_summary"] = (f"The records for {exception_id} show the engine's reported difference; the evidence examined "
                                    "does not establish why it arose.")
    for f in out["confirmed_findings"]:
        f.update(audit_relevance="The engine result is one of the results that make up this exception.",
                 establishes="The engine reported this outcome with the quoted computed and reported values.",
                 does_not_establish="Why the difference arose or how it will be resolved is not established.")
    for h in out["hypotheses"]:
        h["rationale"] = "The engine recorded a date-and-amount coincidence between the exceptions."
    if edit:
        edit(out)
    return LLMInvestigationOutput.model_validate(out)


def raw(parsed, status="completed"):
    r = mock.Mock()
    msg = {"type": "message", "id": "msg_1", "role": "assistant", "content": [{"type": "output_text", "text": parsed.model_dump_json()}]}
    r.http_response.json.return_value = {"id": "resp_t", "model": "gpt-6-luna", "status": status, "output": [msg], "usage": USAGE}
    r.http_response.headers = {"x-request-id": "req_t"}
    r.parse.return_value = mock.Mock(output_parsed=parsed)
    return r


def openai_investigator(responder):
    """A real OpenAIInvestigator whose HTTP client is mocked; responder(kwargs) returns the raw response (or raises)."""
    with mock.patch.dict(os.environ, {config.ENV_OPENAI_KEY: "sk-test-NOT-REAL-0000"}, clear=True), mock.patch("openai.OpenAI") as cls:
        inv = OpenAIInvestigator(model="gpt-6-luna", reasoning_effort="")
    inv._client = cls.return_value
    inv._client.responses.with_raw_response.parse.side_effect = lambda **kw: responder(kw)
    return inv


def make_investigation(scenario, exception_id, root, edit=None):
    """Publish a VALID, non-simulated fixed-mode investigation in `root`; returns its investigation ID."""
    out = investigation_output(scenario, exception_id, edit)
    inv = openai_investigator(lambda kw: raw(out))
    s = run_investigation(PACK[scenario], exception_id, inv, investigations_root=root, mode="fixed")
    assert s["persist_outcome"] == "PUBLISHED", s["result"]["failure_reason"] or s["result"]["validation_findings"]
    return s["result"]["investigation_id"]


def summary_output(summary_input, edit=None):
    """A valid closing-summary output that cites only allowed references."""
    finding = [f["ref"] for i in summary_input["investigations"] for f in i["confirmed_findings"]]
    hyps = [h["ref"] for i in summary_input["investigations"] for h in i["hypotheses"]]
    gaps = [g["ref"] for i in summary_input["investigations"] for g in i["evidence_gaps"]]
    steps = [s["ref"] for i in summary_input["investigations"] for s in i["next_steps"]]
    exc = [x["exception_id"] for x in summary_input["exceptions"]]
    rec = summary_input["reconciliation"]
    data = {
        "overall_position": f"The deterministic engine reports case status {rec['engine_case_status']} with {len(exc)} exception(s).",
        "summary_text": "This closing summary restates the supplied reconciliation and investigation records for the reviewer. "
                        + ("Every exception remains unresolved and is reported in full." if exc else "No exceptions were raised."),
        "key_observations": [{"text": "The investigation reports the engine's results for the exception.", "source_refs": (finding or exc)[:2]}]
                            if (finding or exc) else [],
        "unresolved_items": [{"exception_id": e, "text": "Remains unresolved and awaits human review."} for e in exc],
        "unverified_hypotheses": [{"text": "A possible relationship between exceptions remains unverified.", "source_refs": hyps[:1]}] if hyps else [],
        "evidence_gaps": [{"text": "Evidence gaps are listed by the investigation.", "source_refs": gaps[:2]}] if gaps else [],
        "suggested_next_steps": [{"text": "Obtain the evidence the investigation lists as needed.", "source_refs": steps[:1]}] if steps else [],
        "limitations": ["Synthetic data; investigations examine one exception at a time."]}
    if edit:
        edit(data)
    return ClosingSummaryOutput.model_validate(data)


def summary_investigator(snapshot, edit=None):
    out = summary_output(closing_summary_input(snapshot), edit)
    return openai_investigator(lambda kw: raw(out)), out


def review_for(snapshot, summary, **overrides):
    data = dict(review_decision_id="RD-0001", review_session_id="RS-0001", decision="GENERATE",
                reviewer=Reviewer(user_id="analyst-1", display_name="Test Analyst"), decided_at="2026-11-03T10:00:00+00:00",
                comment="Reviewed the preview.", acknowledgement_accepted=True, snapshot_sha256=snapshot.sha256,
                closing_summary_sha256=summary_sha256(summary))
    data.update(overrides)
    return ReviewRecord(**data)


def sha_tree(*roots):
    out = {}
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def resealed(final, mutate):
    """A copy of a final pack changed by `mutate`, with the content hash recomputed (tests validation, not hashing)."""
    from uc042lib.final_pack.assemble import content_sha256
    f = copy.deepcopy(final)
    mutate(f)
    f["final_content_sha256"] = content_sha256(f)
    return f


def canonical_json(obj):
    return json.loads(json.dumps(obj))
