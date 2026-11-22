"""Ringfence closure runner: the UC-042 audit-pack, AI-investigation and final-pack LIBRARY (uc042lib.pack,
uc042lib.investigation, uc042lib.final_pack) executed in a SEPARATE Python process, in the same isolation pattern as
uc042_adapter.ENGINE_RUNNER.

Isolation (every operation):
  * interpreter: the server's --closure-python (it carries the library's dependencies: pydantic, langgraph, openai,
    reportlab, pypdf); without it every operation reports "UNAVAILABLE: no closure interpreter configured";
  * PYTHONPATH=<uc042_root> (the read-only engine copy), `-B` and PYTHONDONTWRITEBYTECODE=1, cwd = a scratch folder of the
    closure record; every root (packs, datasets, investigations, final packs) is passed explicitly and lies outside the
    engine tree, so nothing is ever written into it;
  * the parent's UC042_* / OPENAI* / ANTHROPIC* / GROQ* variables and PYTHONPATH / PYTHONHOME are never inherited;
  * the engine's optional local `.env` auto-loading (uc042lib.investigation.config.load_local_env via python-dotenv) is
    disabled inside the subprocess, so credentials come ONLY from the allowlist below;
  * JSON in / JSON out through two files (the library may print to stdout; nothing is parsed from it).

Credentials: read from --ai-env-file with an EXACT key allowlist (AI_ENV_KEYS; never a prefix match, so
UC042_LLM_FALLBACK_* is never passed) and handed only to the AI operations (`investigate`, `preview` with an AI closing
summary). The key is never logged, printed, returned or written; error text from the subprocess is redacted.

Usage: every AI request is recorded (model, resolved model, provider, prompt version, request / response IDs, token usage
including cached input and reasoning tokens, latency) from the library's own per-request telemetry. Nothing of the
request content is recorded here. Cost is computed by the caller only when a pricing file is configured.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# The ONLY variables ever read from the AI env file (exact names, no prefix matching).
AI_ENV_KEYS = ("OPENAI_API_KEY", "UC042_LLM_PROVIDER", "UC042_LLM_MODEL", "UC042_LLM_TIMEOUT_SECONDS",
               "UC042_LLM_MAX_TOKENS", "UC042_OPENAI_REASONING_EFFORT")
_INHERIT_BLOCK = ("UC042_", "OPENAI", "ANTHROPIC", "GROQ")
UNAVAILABLE_NO_PYTHON = "UNAVAILABLE: no closure interpreter configured"
DATA_NOTICE = ("AI investigations and the AI closing summary send this case's evidence records (raw evidence packets) to "
               "OpenAI with store:false. Approved for this proof of concept; outputs are labelled AI-generated and every "
               "finding needs an explicit analyst ACCEPT or REJECT.")

# ======================================================================================================== subprocess
RUNNER_DEFS = r'''
import json, sys, traceback, types
sys.dont_write_bytecode = True
# The engine's optional local .env loading is disabled: credentials come only from the parent's exact allowlist.
_dotenv = types.ModuleType("dotenv")
_dotenv.load_dotenv = lambda *a, **k: False
_dotenv.dotenv_values = lambda *a, **k: {}
sys.modules["dotenv"] = _dotenv
from pathlib import Path

INVESTIGATION_MODE = "tools"
CALLS = []          # per-request telemetry of AI requests made by this operation (no content)
SENT = []


def redact(text):
    try:
        from uc042lib.investigation.llm import redact as _r
        return _r(str(text))
    except Exception:
        return str(text)


def instrument(inv, cap):
    """Count every request (hard per-operation cap when configured) and keep the library's per-request telemetry."""
    from uc042lib.investigation.llm import LLMCallError
    orig_req, orig_tel, orig_fail = inv._request, inv._telemetry, inv._failed_request

    def _request(kwargs):
        if cap and len(SENT) >= cap:
            raise LLMCallError(f"request budget of {cap} AI request(s) per operation reached", "request_budget")
        SENT.append(1)
        return orig_req(kwargs)

    def _telemetry(*a, **k):
        r = orig_tel(*a, **k)
        CALLS.append(dict(r))
        return r

    def _failed(*a, **k):
        r = orig_fail(*a, **k)
        CALLS.append(dict(r))
        return r
    inv._request, inv._telemetry, inv._failed_request = _request, _telemetry, _failed
    return inv


def make_investigator(req):
    """The live investigator from the allowlisted environment (OpenAI only; no fallback provider)."""
    from uc042lib.investigation import config as icfg
    from uc042lib.investigation.llm import LLMConfigurationError, OpenAIInvestigator
    provider = icfg.provider_settings()["provider"]
    if provider != "openai":
        raise LLMConfigurationError(f"UC042_LLM_PROVIDER={provider!r} is not supported here (OpenAI only)")
    inv = OpenAIInvestigator()
    return instrument(inv, req.get("max_requests"))


def op_info(req):
    from uc042lib.investigation import config as icfg
    from uc042lib.final_pack import model as fm
    return {"default_models": icfg.DEFAULT_MODELS, "tools_prompt_version": icfg.TOOLS_PROMPT_VERSION,
            "tools_workflow_version": icfg.TOOLS_WORKFLOW_VERSION, "findings_schema_version": icfg.FINDINGS_SCHEMA_VERSION,
            "summary_prompt_version": getattr(fm, "SUMMARY_PROMPT_VERSION", None),
            "acknowledgement_text": fm.ACKNOWLEDGEMENT_TEXT}


def op_generate_pack(req):
    from uc042lib.pack import generate as G
    from uc042lib.period import PeriodConfig
    rec = G.generate(Path(req["case_dir"]), Path(req["packs_root"]), PeriodConfig.from_id(req["period"]))
    return {"record": rec}


def op_investigate(req):
    from uc042lib.investigation import config as icfg
    from uc042lib.investigation.graph import run_investigation
    from uc042lib.final_pack.sources import check_eligibility, load_bundle, load_pack
    limits = icfg.tool_limits()
    limits.update(req.get("tool_limits") or {})
    inv = make_investigator(req)
    state = run_investigation(req["pack_id"], req["exception_id"], inv, packs_root=Path(req["packs_root"]),
                              datasets_root=Path(req["datasets_root"]), investigations_root=Path(req["investigations_root"]),
                              mode=INVESTIGATION_MODE, tool_limits=limits, execution=req.get("execution") or {})
    res = state.get("result") or {}
    meta = res.get("model_metadata") or {}
    out = {"persist_outcome": state.get("persist_outcome"), "investigation_status": res.get("investigation_status"),
           "validation_status": res.get("validation_status"),
           "failure_reason": redact(res.get("failure_reason") or "")[:800],
           "validation_findings": [redact(x)[:300] for x in (res.get("validation_findings") or [])[:10]],
           "tool_summary": {k: v for k, v in (res.get("tool_summary") or {}).items() if k != "limits"},
           "investigation_mode": INVESTIGATION_MODE,
           "model": {k: meta.get(k) for k in ("provider", "model", "prompt_version", "workflow_version",
                                               "findings_schema_version", "simulated")},
           "usage": meta.get("usage") or {}, "investigation_id": None, "artefact_path": state.get("artefact_path") or None,
           "persist_error": redact(state.get("persist_error") or "")[:800] or None}
    if out["persist_outcome"] in ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL") and state.get("artefact_path"):
        p = Path(state["artefact_path"])
        out["investigation_id"] = p.name
        bundle = load_bundle(p)
        out["findings_sha256"] = bundle["findings_sha256"]
        out["eligibility_reasons"] = check_eligibility(bundle, load_pack(req["pack_id"], Path(req["packs_root"])))
    elif state.get("artefact_path"):
        out["not_published_record"] = Path(state["artefact_path"]).name
    return out


def _snapshot(req):
    from uc042lib.final_pack import Selection, build_review_snapshot
    sels = [Selection(**s) for s in req["selections"]]
    return build_review_snapshot(req["pack_id"], sels, packs_root=Path(req["packs_root"]),
                                 investigations_root=Path(req["investigations_root"]),
                                 analyst_reviews=list(req.get("analyst_reviews") or []))  # always reviewed (schema 1.3)


def op_preview(req):
    from uc042lib.final_pack import (ClosingSummaryError, assemble_preview, closing_summary_required,
                                     generate_closing_summary, not_required_closing_summary, render_html, render_pdf,
                                     summary_sha256, unavailable_closing_summary)
    from uc042lib.final_pack.render_pdf import unsupported_characters
    from uc042lib.investigation.llm import LLMConfigurationError
    from uc042lib.pack.model import canonical
    snap = _snapshot(req)
    failure = None
    if not closing_summary_required(snap):
        summary = not_required_closing_summary(snap)
    elif req["summary"] == "AI":
        try:
            summary = generate_closing_summary(snap, make_investigator(req))
        except (ClosingSummaryError, LLMConfigurationError) as e:
            kind = getattr(e, "kind", "configuration")
            failure = {"kind": kind, "message": redact(str(e))[:500]}
            summary = unavailable_closing_summary(snap, f"closing summary generation failed ({kind})",
                                                  [redact(str(x)) for x in getattr(e, "findings", [])])
    else:
        summary = unavailable_closing_summary(snap, req.get("unavailable_reason") or "AI is not configured")
    preview = assemble_preview(snap, summary)
    glyphs = unsupported_characters(preview)
    if glyphs:
        raise ValueError(f"PDF_GLYPHS_UNSUPPORTED: the preview contains characters the PDF fonts cannot draw: {glyphs[:6]}")
    out = Path(req["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "preview.json").write_text(canonical(preview), encoding="utf-8")
    (out / "preview.pdf").write_bytes(render_pdf(preview))
    (out / "preview.html").write_text(render_html(preview), encoding="utf-8")
    (out / "closing_summary.json").write_text(json.dumps(summary.model_dump(), indent=1, sort_keys=True), encoding="utf-8")
    m = summary.model_metadata or {}
    return {"snapshot_sha256": snap.sha256, "accepted_ids": sorted(snap.accepted_ids),
            "preview_final_pack_id": preview["metadata"]["final_pack_id"],
            "preview_content_sha256": preview["final_content_sha256"],
            "closing_summary": {"status": summary.status, "sha256": summary_sha256(summary),
                                "unavailable_reason": summary.unavailable_reason, "failure": failure,
                                "provider": m.get("provider"), "model": m.get("model"),
                                "prompt_version": m.get("prompt_version"), "usage": m.get("usage") or {},
                                "created_at": summary.created_at}}


def op_render_preview(req):
    from uc042lib.final_pack import render_html, render_pdf
    preview = json.loads(Path(req["preview_json"]).read_text(encoding="utf-8"))
    data = render_pdf(preview) if req["fmt"] == "pdf" else render_html(preview).encode("utf-8")
    Path(req["out"]).write_bytes(data)
    return {"bytes": len(data)}


def op_generate_final(req):
    from uc042lib.final_pack import (ClosingSummary, GenerationInfo, PriorDecision, Reviewer, ReviewRecord,
                                     assemble_final_pack, next_version, publish_final_pack, summary_sha256,
                                     verify_final_pack)
    from uc042lib.final_pack.render_pdf import unsupported_in_text
    snap = _snapshot(req)
    if snap.sha256 != req["expected_snapshot_sha256"]:
        raise ValueError("PREVIEW_STALE: the review snapshot changed since the preview")
    summary = ClosingSummary.model_validate(json.loads(Path(req["closing_summary_path"]).read_text(encoding="utf-8")))
    r = req["review"]
    comment = r["comment"]
    if unsupported_in_text(comment):
        comment = r["comment_ascii"]
    review = ReviewRecord(review_decision_id=r["review_decision_id"], review_session_id=r["review_session_id"],
                          decision="GENERATE", reviewer=Reviewer(**r["reviewer"]), decided_at=r["decided_at"],
                          comment=comment, acknowledgement_accepted=True, snapshot_sha256=snap.sha256,
                          closing_summary_sha256=summary_sha256(summary),
                          acknowledged_summary_unavailable=bool(r.get("acknowledged_summary_unavailable")),
                          prior_decisions=[PriorDecision(**p) for p in r.get("prior_decisions") or []])
    root = Path(req["final_packs_root"])
    version, supersedes = next_version(req["pack_id"], root)
    final = assemble_final_pack(snap, summary, review, GenerationInfo(version=version, supersedes_final_pack_id=supersedes))
    path = publish_final_pack(final, root, expected=(version, supersedes))
    problems = verify_final_pack(path)
    return {"final_pack_id": final["metadata"]["final_pack_id"], "path": str(path), "verify_problems": problems,
            "version": version, "supersedes_final_pack_id": supersedes, "generated_at": final["metadata"]["generated_at"],
            "final_content_sha256": final["final_content_sha256"], "comment_used": comment,
            "files": sorted(p.name for p in Path(path).iterdir())}


def op_verify_final(req):
    from uc042lib.final_pack import verify_final_pack
    return {"verify_problems": verify_final_pack(Path(req["path"]))}


def op_provenance_pdf(req):
    """A small, plain PDF of the Ringfence provenance supplement (reportlab; the library's renderer is not involved)."""
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    doc = json.loads(Path(req["provenance_json"]).read_text(encoding="utf-8"))
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7, leading=8.5)
    P = lambda t, s=st["BodyText"]: Paragraph(escape(str(t)), s)  # noqa: E731
    flow = [P("Ringfence provenance supplement", st["Title"]),
            P(f"Final pack {doc['final_pack_id']} - case {doc['case_ref']} - reconciliation run {doc['recon_run_id']}"),
            P(f"Snapshot {doc['snapshot_id']}; package {doc['package_id']}; audit pack {doc['pack_id']}"),
            P(f"Original ZIP {doc['zip']['filename']} sha256 {doc['zip']['sha256']}"),
            P(f"Authorised by {doc['authorised_by']} (system reviewer {doc['system_reviewer_id']}) at {doc['generated_at']}"),
            Spacer(1, 4 * mm), P("Source files", st["Heading2"])]
    rows = [[P(h, small) for h in ("Category", "Canonical (engine) name", "Original filename", "File version", "SHA-256")]]
    rows += [[P(f.get(k) or "", small) for k in ("evidence_category", "canonical_name", "original_filename",
                                                  "file_version_id", "source_sha256")] for f in doc["source_files"]]
    t = Table(rows, colWidths=[16 * mm, 40 * mm, 40 * mm, 36 * mm, 48 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow += [t, Spacer(1, 4 * mm), P("Closure decisions", st["Heading2"])]
    for d in doc["decisions"]:
        flow.append(P(f"{d.get('at')} - {d.get('what')} - by {d.get('by')}", small))
    flow += [Spacer(1, 4 * mm), P(doc["statement"], small)]
    SimpleDocTemplate(req["out_pdf"], pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                      title="Ringfence provenance supplement").build(flow)
    return {"bytes": Path(req["out_pdf"]).stat().st_size}


OPS = {"info": op_info, "generate_pack": op_generate_pack, "investigate": op_investigate, "preview": op_preview,
       "render_preview": op_render_preview, "generate_final": op_generate_final, "verify_final": op_verify_final,
       "provenance_pdf": op_provenance_pdf}
'''

RUNNER_MAIN = r'''
def main():
    req_path, resp_path = sys.argv[1], sys.argv[2]
    req = json.loads(Path(req_path).read_text(encoding="utf-8"))
    sys.path.insert(0, req["uc042_root"])
    try:
        out = {"ok": True, "result": OPS[req["op"]](req)}
    except BaseException as e:
        out = {"ok": False, "error_type": type(e).__name__, "error": redact(f"{e}")[:2000],
               "trace": redact(traceback.format_exc())[-3000:]}
    out["ai_requests"] = CALLS
    out["ai_requests_sent"] = len(SENT)
    Path(resp_path).write_text(json.dumps(out, default=str), encoding="utf-8")


main()
'''
RUNNER_SCRIPT = RUNNER_DEFS + RUNNER_MAIN


class ClosureRunnerError(RuntimeError):
    """The subprocess failed (technical) or the library refused the operation. `kind` is the library exception type."""

    def __init__(self, message: str, kind: str = "error", ai_requests: list | None = None):
        super().__init__(message)
        self.kind, self.ai_requests = kind, ai_requests or []


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*]{4,}|sk_[A-Za-z0-9_\-*]{4,}|gsk_[A-Za-z0-9_\-*]{4,}|Bearer\s+[A-Za-z0-9._\-]+)")


def parse_env_file(path: str | Path | None) -> dict:
    """Only AI_ENV_KEYS, exactly; everything else in the file is ignored (never read into the process)."""
    out: dict = {}
    if not path:
        return out
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        if k not in AI_ENV_KEYS:
            continue
        v = v.strip()
        if v[:1] in ("'", '"') and len(v) >= 2 and v[-1] == v[0]:
            v = v[1:-1]
        else:
            v = v.split(" #", 1)[0].strip()
        out[k] = v
    return out


class ClosureRunner:
    """Runs closure operations in the isolated library subprocess. `SCRIPT` is the program executed (tests may subclass
    the runner with a clearly marked test double; production code never selects one)."""
    SCRIPT = RUNNER_SCRIPT

    def __init__(self, uc042_root: str | Path | None, python: str | Path | None, ai_env_file: str | Path | None = None,
                 pricing_file: str | Path | None = None, max_ai_requests: int | None = None, timeout: int = 1800):
        self.uc042_root = Path(uc042_root).resolve() if uc042_root else None
        self.python = str(python) if python else None
        self.ai_env_file = Path(ai_env_file) if ai_env_file else None
        self.max_ai_requests = max_ai_requests
        self.timeout = timeout
        self.pricing = {}
        if pricing_file:
            self.pricing = json.loads(Path(pricing_file).read_text(encoding="utf-8"))
        self._info = None

    # ------------------------------------------------------------------------------------------------ configuration
    def problem(self) -> str | None:
        if not self.python:
            return UNAVAILABLE_NO_PYTHON
        if not Path(self.python).is_file():
            return f"UNAVAILABLE: the closure interpreter {self.python} does not exist"
        if self.uc042_root is None or not (self.uc042_root / "uc042lib" / "final_pack").is_dir():
            return "UNAVAILABLE: no UC-042 library tree (--uc042-root) with uc042lib.final_pack"
        return None

    def ai_values(self) -> dict:
        return parse_env_file(self.ai_env_file)

    def info(self) -> dict:
        if self._info is None and self.problem() is None:
            try:
                self._info = self._call("info", {}, ai=False)["result"]
            except ClosureRunnerError:
                self._info = {}
        return self._info or {}

    def ai_configuration(self) -> dict:
        vals = self.ai_values()
        provider = (vals.get("UC042_LLM_PROVIDER") or "openai").strip().lower()
        problem = self.problem()
        if problem is None:
            if self.ai_env_file is None:
                problem = "AI is not configured: the server was started without --ai-env-file"
            elif not self.ai_env_file.is_file():
                problem = "AI is not configured: the AI env file does not exist"
            elif not vals.get("OPENAI_API_KEY", "").strip():
                problem = "AI is not configured: OPENAI_API_KEY is not set in the AI env file"
            elif provider != "openai":
                problem = f"AI provider {provider!r} is not supported (OpenAI only)"
        model = (vals.get("UC042_LLM_MODEL") or "").strip() or (self.info().get("default_models") or {}).get("openai")
        return {"available": problem is None, "provider": "openai" if provider == "openai" else provider, "model": model,
                "reasoning_effort": (vals.get("UC042_OPENAI_REASONING_EFFORT") or "").strip() or None,
                "problem": problem, "pricing_configured": bool(self.pricing), "store": False, "data_notice": DATA_NOTICE,
                "max_requests_per_operation": self.max_ai_requests}

    def cost(self, model: str | None, usage: dict) -> float | None:
        p = self.pricing.get(model or "")
        if not p:
            return None
        inp, cached, out = (int(usage.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        return round(((inp - cached) * p.get("input_per_m", 0) + cached * p.get("cached_input_per_m", p.get("input_per_m", 0))
                      + out * p.get("output_per_m", 0)) / 1_000_000, 6)

    # ------------------------------------------------------------------------------------------------ subprocess
    def _env(self, ai: bool) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(_INHERIT_BLOCK) and k.upper() not in ("PYTHONPATH", "PYTHONHOME")}
        env.update(PYTHONPATH=str(self.uc042_root), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
                   PYTHONUTF8="1")
        if ai:
            env.update({k: v for k, v in self.ai_values().items() if k in AI_ENV_KEYS})
        return env

    def _redact(self, text: str) -> str:
        text = _SECRET_RE.sub("[REDACTED]", str(text))
        key = self.ai_values().get("OPENAI_API_KEY", "")
        if len(key) >= 8:
            text = text.replace(key, "[REDACTED]")
        return text

    def _call(self, op: str, payload: dict, ai: bool, scratch: Path | None = None) -> dict:
        problem = self.problem()
        if problem:
            raise ClosureRunnerError(problem, "unavailable")
        scratch = Path(scratch) if scratch else Path(tempfile.gettempdir())
        scratch.mkdir(parents=True, exist_ok=True)
        tag = uuid.uuid4().hex[:12]
        req_p, resp_p = scratch / f"req-{op}-{tag}.json", scratch / f"resp-{op}-{tag}.json"
        req = dict(payload, op=op, uc042_root=str(self.uc042_root))
        if ai and self.max_ai_requests:
            req.setdefault("max_requests", self.max_ai_requests)
        req_p.write_text(json.dumps(req, default=str), encoding="utf-8")
        try:
            proc = subprocess.run([self.python, "-B", "-c", self.SCRIPT, str(req_p), str(resp_p)], cwd=str(scratch),
                                  env=self._env(ai), capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=self.timeout)
            if not resp_p.is_file():
                raise ClosureRunnerError(f"closure operation {op} produced no result (exit {proc.returncode}): "
                                         f"{self._redact(proc.stderr[-800:])}", "process")
            out = json.loads(resp_p.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            raise ClosureRunnerError(f"closure operation {op} timed out after {self.timeout}s", "timeout") from None
        finally:
            for p in (req_p, resp_p):
                try:
                    p.unlink()
                except OSError:
                    pass
        if not out.get("ok"):
            raise ClosureRunnerError(self._redact(out.get("error", "")), out.get("error_type", "error"),
                                     out.get("ai_requests"))
        return out

    # ------------------------------------------------------------------------------------------------ operations
    def generate_pack(self, case_dir: Path, packs_root: Path, period: str, scratch: Path) -> dict:
        return self._call("generate_pack", {"case_dir": str(case_dir), "packs_root": str(packs_root), "period": period},
                          ai=False, scratch=scratch)["result"]["record"]

    def investigate(self, *, pack_id: str, exception_id: str, packs_root: Path, datasets_root: Path,
                    investigations_root: Path, execution: dict, scratch: Path, tool_limits: dict | None = None) -> dict:
        """Returns the result dict plus `ai_requests` (per-request telemetry). Raises ClosureRunnerError with the
        telemetry of any billed requests attached."""
        out = self._call("investigate", {"pack_id": pack_id, "exception_id": exception_id, "packs_root": str(packs_root),
                                         "datasets_root": str(datasets_root),
                                         "investigations_root": str(investigations_root), "execution": execution,
                                         "tool_limits": tool_limits or {}}, ai=True, scratch=scratch)
        return dict(out["result"], ai_requests=out.get("ai_requests") or [])

    def preview(self, *, pack_id: str, packs_root: Path, investigations_root: Path, selections: list, analyst_reviews: list,
                summary: str, unavailable_reason: str, out_dir: Path, scratch: Path) -> dict:
        out = self._call("preview", {"pack_id": pack_id, "packs_root": str(packs_root),
                                     "investigations_root": str(investigations_root), "selections": selections,
                                     "analyst_reviews": analyst_reviews, "summary": summary,
                                     "unavailable_reason": unavailable_reason, "out_dir": str(out_dir)},
                         ai=summary == "AI", scratch=scratch)
        return dict(out["result"], ai_requests=out.get("ai_requests") or [])

    def render_preview(self, preview_json: Path, fmt: str, out: Path, scratch: Path) -> dict:
        return self._call("render_preview", {"preview_json": str(preview_json), "fmt": fmt, "out": str(out)},
                          ai=False, scratch=scratch)["result"]

    def generate_final(self, *, pack_id: str, packs_root: Path, investigations_root: Path, final_packs_root: Path,
                       selections: list, analyst_reviews: list, closing_summary_path: Path, review: dict,
                       expected_snapshot_sha256: str, scratch: Path) -> dict:
        return self._call("generate_final", {
            "pack_id": pack_id, "packs_root": str(packs_root), "investigations_root": str(investigations_root),
            "final_packs_root": str(final_packs_root), "selections": selections, "analyst_reviews": analyst_reviews,
            "closing_summary_path": str(closing_summary_path), "review": review,
            "expected_snapshot_sha256": expected_snapshot_sha256}, ai=False, scratch=scratch)["result"]

    def verify_final(self, path: Path, scratch: Path) -> list:
        return self._call("verify_final", {"path": str(path)}, ai=False, scratch=scratch)["result"]["verify_problems"]

    def provenance_pdf(self, provenance_json: Path, out_pdf: Path, scratch: Path) -> dict:
        return self._call("provenance_pdf", {"provenance_json": str(provenance_json), "out_pdf": str(out_pdf)},
                          ai=False, scratch=scratch)["result"]
