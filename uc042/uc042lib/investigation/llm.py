"""Model adapters. Live: OpenAI Responses API (default) and Anthropic Messages API (legacy); credentials come from the
environment. Offline: deterministic simulated investigator, for automated tests only, always labelled simulated.
There is no silent fallback from live to offline. Provider-specific parameters stay inside each adapter.

Telemetry and SDK retries (review DR-08). The OpenAI client is created with max_retries=SDK_MAX_RETRIES (2), unchanged:
the SDK itself retries a request that fails with a connection error, a timeout, 408/409/429 or a 5xx status, with backoff,
before returning or raising. Those SDK-internal HTTP retries are not separate application telemetry entries: each entry in
provider_response.responses is one application-level request (one client call), which may stand for up to
1 + SDK_MAX_RETRIES HTTP attempts. Every entry therefore records sdk_max_retries. Implications: request counts in
telemetry are a lower bound on HTTP requests; usage comes from the final response only (a failed HTTP attempt returns
no usage); latency_seconds includes any SDK backoff. Application-level retries (the corrective retry for invalid output)
ARE separate entries."""
import json
import os
import re
import time

from pydantic import ValidationError

SDK_MAX_RETRIES = 2  # OpenAI SDK-internal HTTP retries per client call (unchanged); see the module docstring (DR-08)

from . import config
from .models import LLMInvestigationOutput
from .prompts import SYSTEM_PROMPT, model_user_message, user_message


class LLMConfigurationError(Exception):
    """Provider not configured (for example missing credentials, package or malformed settings)."""


class LLMCallError(Exception):
    """The provider call failed or returned unusable output. `kind` classifies the failure, for example
    authentication, model_unavailable, rate_limit, timeout, refusal, max_output_tokens, incomplete, invalid_output."""

    def __init__(self, message, kind="provider_error"):
        self.kind = kind
        super().__init__(f"[{kind}] {redact(message)}")


# Anything that looks like a credential is masked before it can reach a message, log or persisted artefact.
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*]{4,}|sk_[A-Za-z0-9_\-*]{4,}|gsk_[A-Za-z0-9_\-*]{4,}|Bearer\s+[A-Za-z0-9._\-]+)")


def redact(text):
    text = _SECRET_RE.sub("[REDACTED]", str(text))
    for name in (config.ENV_OPENAI_KEY, config.ENV_ANTHROPIC_KEY):
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:
            text = text.replace(value, "[REDACTED]")
    return text


def _settings():
    try:
        return config.provider_settings()
    except ValueError as e:
        raise LLMConfigurationError(str(e)) from e


def parse_json_object(text):
    """Extract one JSON object from model text (tolerates a fenced block). Raises LLMCallError."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise LLMCallError("model response contained no JSON object", "invalid_output")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMCallError(f"model response is not valid JSON: {e}", "invalid_output") from e


def _status_error(e, provider):
    """Map an SDK status error (both SDKs share the class names) to an LLMCallError kind."""
    status = getattr(e, "status_code", None)
    name = e.__class__.__name__
    detail = str(getattr(e, "message", "") or e)[:300]
    kind = {"AuthenticationError": "authentication", "PermissionDeniedError": "permission_denied",
            "NotFoundError": "model_unavailable", "RateLimitError": "rate_limit",
            "BadRequestError": "bad_request"}.get(name, "api_error")
    if kind == "api_error" and isinstance(status, int) and status >= 500:
        kind = "provider_unavailable"  # 5xx: a temporary provider failure (reported; never routed to another provider)
    if status == 413:
        kind = "request_too_large"  # the request exceeds the model's / plan's token limit
    if kind == "bad_request" and re.search(r"model", detail, re.I) and re.search(r"not exist|not found|does not have access|unsupported", detail, re.I):
        kind = "model_unavailable"
    code = getattr(e, "code", None)
    return LLMCallError(f"{provider} API error {status} ({name}{', code ' + str(code) if code else ''}): {detail}", kind)


class OpenAIInvestigator:
    """OpenAI Responses API with Pydantic structured output (`responses.parse(text_format=LLMInvestigationOutput)`)."""
    provider = "openai"
    PROVIDER_LABEL = "OpenAI"
    simulated = False
    uses_model_view = True  # phase 4: requests carry the lossless model view (model_view_version / sha256 recorded)
    last_structured_request = None  # telemetry of the latest structured_request (DR-09)
    RETRYABLE_KINDS = ("invalid_output", "missing_output")  # deterministic failures (refusal, truncation) are not retried

    def __init__(self, model=None, timeout=None, max_tokens=None, reasoning_effort=None, total_timeout=None,
                 investigation_max_tokens=None):
        s = _settings()
        self.model = model or (s["model"] if s["provider"] == "openai" else config.DEFAULT_MODELS["openai"])
        self.timeout = timeout or s["timeout"]
        self.total_timeout = total_timeout or s["total_timeout"]
        self.max_tokens = max_tokens or s["max_tokens"]  # closing summary / structured_request only
        # investigations (investigate() and every tool_turn()) use their own budget (UC042_INVESTIGATION_MAX_OUTPUT_TOKENS)
        self.investigation_max_tokens = investigation_max_tokens or s["investigation_max_tokens"]
        self.reasoning_effort = reasoning_effort if reasoning_effort is not None else s["reasoning_effort"]
        if self.reasoning_effort and self.reasoning_effort not in config.OPENAI_REASONING_EFFORTS:
            raise LLMConfigurationError(f"{config.ENV_REASONING_EFFORT} must be one of {config.OPENAI_REASONING_EFFORTS}")
        key = os.environ.get(config.ENV_OPENAI_KEY, "").strip()
        if not key:
            raise LLMConfigurationError(f"{config.ENV_OPENAI_KEY} is not set; live investigation cannot run")
        try:
            import openai
        except ImportError as e:
            raise LLMConfigurationError("the 'openai' package is not installed") from e
        self._openai = openai
        self._client = openai.OpenAI(api_key=key, timeout=self.timeout, max_retries=SDK_MAX_RETRIES)  # DR-08: see module doc

    def _request(self, kwargs):
        """Provider-specific request adjustments (none for OpenAI)."""
        return kwargs

    def _meta(self, body, raw):
        return {"response_id": body.get("id"), "resolved_model": body.get("model"), "status": body.get("status"),
                "request_id": raw.http_response.headers.get("x-request-id")}

    def _telemetry(self, body, raw, kwargs, started, turn):
        """Per-request record (phase 3): IDs, status, incomplete reason, this request's own usage and latency, and the size
        of what was sent (item count and characters; never the content). Kept in provider_response, which is excluded
        from the investigation identity. Fields the provider does not supply stay None."""
        items = kwargs.get("input") or []
        return dict(self._meta(body, raw), turn=turn, model=kwargs.get("model"),
                    incomplete_reason=(body.get("incomplete_details") or {}).get("reason"),
                    usage=self._usage(body), latency_seconds=round(time.perf_counter() - started, 3),
                    max_output_tokens=kwargs.get("max_output_tokens"), input_items=len(items),
                    input_chars=sum(len(json.dumps(i, ensure_ascii=False, default=str)) for i in items),
                    instructions_chars=len(kwargs.get("instructions") or ""), sdk_max_retries=SDK_MAX_RETRIES)

    @staticmethod
    def _failed_request(kwargs, started, turn, error):
        """A request that produced no response body (provider/transport error): what was sent, how long it took, why."""
        items = kwargs.get("input") or []
        return {"turn": turn, "model": kwargs.get("model"), "status": "error", "error_kind": getattr(error, "kind", "unexpected"),
                "usage": {}, "latency_seconds": round(time.perf_counter() - started, 3), "max_output_tokens": kwargs.get("max_output_tokens"),
                "input_items": len(items), "input_chars": sum(len(json.dumps(i, ensure_ascii=False, default=str)) for i in items),
                "instructions_chars": len(kwargs.get("instructions") or ""), "sdk_max_retries": SDK_MAX_RETRIES}

    @staticmethod
    def _attach(error, usage_total, responses, attempts):
        """Keep the billed usage and per-request records on a failure (the fixed mode and summary used to lose them)."""
        error.telemetry = {"usage": dict(usage_total), "attempts": attempts,
                           "provider_response": dict(responses[-1] if responses else {}, responses=list(responses))}
        return error

    def _map_error(self, e):
        o = self._openai
        if isinstance(e, o.APITimeoutError):
            return LLMCallError("provider call timed out", "timeout")
        if isinstance(e, o.APIConnectionError):
            return LLMCallError(f"could not connect to the provider: {e.__class__.__name__}", "connection")
        if isinstance(e, o.APIStatusError):
            return _status_error(e, self.PROVIDER_LABEL)  # the provider that actually answered
        if isinstance(e, o.APIError):
            return LLMCallError(f"provider API error: {e.__class__.__name__}: {str(e)[:300]}", "api_error")
        return LLMCallError(f"unexpected provider error: {e.__class__.__name__}: {str(e)[:200]}", "unexpected")

    def _request_kwargs(self, packet, timeout):
        kwargs = {"model": self.model, "instructions": SYSTEM_PROMPT,
                  "input": [{"role": "user", "content": model_user_message(packet)}],  # phase 4: lossless model view
                  "text_format": LLMInvestigationOutput, "max_output_tokens": self.investigation_max_tokens,
                  "store": False,  # no Responses API application-state storage; abuse-monitoring retention is separate (see report 02 §12)
                  "timeout": timeout}
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs  # no temperature/top_p: not sent to reasoning models

    @staticmethod
    def _check_body(body):
        """Classify an unsuccessful response from the raw body before any parsing is attempted."""
        status = body.get("status")
        if status == "failed":
            err = body.get("error") or {}
            raise LLMCallError(f"response failed: {err.get('code', '')}: {str(err.get('message', ''))[:300]}", "response_failed")
        if status == "incomplete":
            reason = (body.get("incomplete_details") or {}).get("reason") or "unknown"
            kind = "max_output_tokens" if reason == "max_output_tokens" else "incomplete"
            raise LLMCallError(f"response incomplete (reason: {reason}); output tokens "
                               f"{(body.get('usage') or {}).get('output_tokens')}", kind)
        refusals = [c.get("refusal", "") for o in body.get("output") or [] if o.get("type") == "message"
                    for c in o.get("content") or [] if c.get("type") == "refusal"]
        if refusals:
            raise LLMCallError(f"model refused: {' '.join(refusals)[:300]}", "refusal")
        if status != "completed":
            raise LLMCallError(f"unexpected response status {status!r}", "response_failed")

    @staticmethod
    def _usage(body):
        u = body.get("usage") or {}
        return {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
                "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens"),
                "total_tokens": u.get("total_tokens")}

    def investigate(self, packet):
        """Return (LLMInvestigationOutput, metadata). Invalid structured output is retried once within the time budget;
        refusals, truncation and provider errors fail immediately. Never fabricates output."""
        deadline = time.monotonic() + self.total_timeout
        usage_total, last_error, response_meta, responses = {}, None, {}, []
        for attempt in (1, 2):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise self._attach(LLMCallError(f"overall time budget of {self.total_timeout:.0f}s exhausted", "timeout_budget"),
                                   usage_total, responses, attempt - 1)
            started, req_t0 = time.monotonic(), time.perf_counter()
            kwargs = self._request(self._request_kwargs(packet, min(self.timeout, remaining)))
            try:
                raw = self._client.responses.with_raw_response.parse(**kwargs)
                body = raw.http_response.json()
            except Exception as e:  # mapped, never masked or fabricated
                err = self._map_error(e)
                responses.append(self._failed_request(kwargs, req_t0, attempt, err))
                raise self._attach(err, usage_total, responses, attempt) from e
            for k, v in self._usage(body).items():
                usage_total[k] = (usage_total.get(k) or 0) + v if v is not None else usage_total.get(k)
            responses.append(self._telemetry(body, raw, kwargs, req_t0, attempt))
            response_meta = dict(self._meta(body, raw), responses=list(responses))
            try:
                self._check_body(body)
                try:
                    parsed = raw.parse().output_parsed
                except ValidationError as e:
                    raise LLMCallError(f"structured output failed schema validation: {str(e)[:500]}", "invalid_output") from e
                if parsed is None:
                    raise LLMCallError("response contained no parsed structured output", "missing_output")
                out = LLMInvestigationOutput.model_validate(parsed.model_dump())
                return out, {"attempts": attempt, "provider_response": response_meta,
                             "usage": dict(usage_total, latency_seconds=round(time.monotonic() - started, 2))}
            except LLMCallError as e:
                if e.kind not in self.RETRYABLE_KINDS:
                    raise self._attach(e, usage_total, responses, attempt)
                last_error = e
        raise self._attach(LLMCallError(f"model output invalid after 2 attempts: {str(last_error)[:500]}", "invalid_output"),
                           usage_total, responses, 2)

    # -- V2 tools mode --------------------------------------------------------------------------------------------
    supports_tools = True

    def tool_definitions(self):
        """Strict Responses-API function tools generated from the registry's Pydantic argument models."""
        from .tools import REGISTRY
        defs = []
        for t in REGISTRY.values():
            f = self._openai.pydantic_function_tool(t.args_model, name=t.name, description=t.description)["function"]
            defs.append({"type": "function", "name": t.name, "description": t.description, "parameters": f["parameters"],
                         "strict": True})
        return defs

    def tool_turn(self, input_items, tools, timeout):
        """One Responses API request in the tool loop. Returns a dict:
        kind 'tool_calls' (function_calls: [{call_id, name, arguments}]) or 'final' (parsed LLMInvestigationOutput),
        plus output_items (to append to the history unchanged), usage and provider_response.
        Raises LLMCallError (refusal, incomplete, max_output_tokens, invalid_output, provider errors)."""
        from .prompts import TOOLS_SYSTEM_PROMPT
        kwargs = {"model": self.model, "instructions": TOOLS_SYSTEM_PROMPT, "input": input_items, "tools": tools,
                  "tool_choice": "auto", "parallel_tool_calls": True, "text_format": LLMInvestigationOutput,
                  "max_output_tokens": self.investigation_max_tokens, "store": False,
                  "include": ["reasoning.encrypted_content"],  # stateless (store=False) reasoning replay across rounds
                  "timeout": timeout}
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        kwargs["input"] = self._history(input_items)
        req_t0 = time.perf_counter()
        kwargs = self._request(kwargs)
        try:
            raw = self._client.responses.with_raw_response.parse(**kwargs)
            body = raw.http_response.json()
        except Exception as e:
            err = self._map_error(e)
            err.turn = {"usage": {}, "provider_response": self._failed_request(kwargs, req_t0, None, err)}
            raise err from e
        meta = self._telemetry(body, raw, kwargs, req_t0, None)
        turn = {"output_items": list(body.get("output") or []), "usage": self._usage(body), "provider_response": meta}
        try:
            self._check_body(body)
            calls = [{"call_id": o.get("call_id"), "name": o.get("name"), "arguments": o.get("arguments")}
                     for o in turn["output_items"] if o.get("type") == "function_call"]
            if calls:  # arguments are validated by our own Pydantic models, not by the SDK parser
                return dict(turn, kind="tool_calls", function_calls=calls)
            return dict(turn, kind="final", parsed=self._final_output(raw, body))
        except LLMCallError as e:  # the request was billed: keep its usage and the output for the transcript
            e.turn = turn
            raise

    @staticmethod
    def _history(input_items):
        """The tool-loop history as sent (OpenAI: unchanged, including its own reasoning items)."""
        return input_items

    @staticmethod
    def _final_output(raw, body):
        """The final answer of a tool-loop response: the SDK's parsed structured output (OpenAI: text_format)."""
        try:
            parsed = raw.parse().output_parsed
        except ValidationError as e:
            raise LLMCallError(f"structured output failed schema validation: {str(e)[:500]}", "invalid_output") from e
        if parsed is None:
            raise LLMCallError("response contained neither tool calls nor parsed structured output", "missing_output")
        return LLMInvestigationOutput.model_validate(parsed.model_dump())

    def structured_request(self, instructions, user_content, text_format):
        """One structured request (closing summary). Also keeps the request's telemetry on the investigator as
        last_structured_request (metadata on success, the error's telemetry on failure; reset at the start of every call),
        so a caller can store the billed usage of a call whose OUTPUT is later refused (review DR-09)."""
        self.last_structured_request = None
        try:
            out, meta = self._structured_request(instructions, user_content, text_format)
        except LLMCallError as e:
            self.last_structured_request = getattr(e, "telemetry", None)
            raise
        self.last_structured_request = meta
        return out, meta

    def _structured_request(self, instructions, user_content, text_format):
        """One structured-output request outside the investigation flow (used by the final-pack closing summary). Same
        client, configuration, error mapping and response checks as investigate(); one retry only for invalid output."""
        deadline = time.monotonic() + self.total_timeout
        usage_total, last_error, responses = {}, None, []
        for attempt in (1, 2):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise self._attach(LLMCallError(f"overall time budget of {self.total_timeout:.0f}s exhausted", "timeout_budget"),
                                   usage_total, responses, attempt - 1)
            started, req_t0 = time.monotonic(), time.perf_counter()
            kwargs = {"model": self.model, "instructions": instructions, "input": [{"role": "user", "content": user_content}],
                      "text_format": text_format, "max_output_tokens": self.max_tokens, "store": False,
                      "timeout": min(self.timeout, remaining)}
            if self.reasoning_effort:
                kwargs["reasoning"] = {"effort": self.reasoning_effort}
            kwargs = self._request(kwargs)
            try:
                raw = self._client.responses.with_raw_response.parse(**kwargs)
                body = raw.http_response.json()
            except Exception as e:
                err = self._map_error(e)
                responses.append(self._failed_request(kwargs, req_t0, attempt, err))
                raise self._attach(err, usage_total, responses, attempt) from e
            for k, v in self._usage(body).items():
                usage_total[k] = (usage_total.get(k) or 0) + v if v is not None else usage_total.get(k)
            responses.append(self._telemetry(body, raw, kwargs, req_t0, attempt))
            meta = dict(self._meta(body, raw), responses=list(responses))
            try:
                self._check_body(body)
                try:
                    parsed = raw.parse().output_parsed
                except ValidationError as e:
                    raise LLMCallError(f"structured output failed schema validation: {str(e)[:500]}", "invalid_output") from e
                if parsed is None:
                    raise LLMCallError("response contained no parsed structured output", "missing_output")
                return text_format.model_validate(parsed.model_dump()), {
                    "attempts": attempt, "provider_response": meta,
                    "usage": dict(usage_total, latency_seconds=round(time.monotonic() - started, 2))}
            except LLMCallError as e:
                if e.kind not in self.RETRYABLE_KINDS:
                    raise self._attach(e, usage_total, responses, attempt)
                last_error = e
        raise self._attach(LLMCallError(f"structured output invalid after 2 attempts: {str(last_error)[:500]}", "invalid_output"),
                           usage_total, responses, 2)

    def check_availability(self):
        """Smoke test without generating tokens: authenticate and look the configured model up."""
        try:
            m = self._client.models.retrieve(self.model)
        except Exception as e:
            raise self._map_error(e) from e
        return {"provider": self.provider, "model": self.model, "available": True, "model_id": getattr(m, "id", self.model)}


class AnthropicInvestigator:
    """Legacy adapter: Anthropic Messages API, JSON parsed from text, one corrective retry."""
    provider = "anthropic"
    simulated = False

    def __init__(self, model=None, timeout=None, max_tokens=None):
        s = _settings()
        self.model = model or (s["model"] if s["provider"] == "anthropic" else config.DEFAULT_MODELS["anthropic"])
        self.timeout = timeout or s["timeout"]
        self.max_tokens = max_tokens or s["max_tokens"]
        if not os.environ.get(config.ENV_ANTHROPIC_KEY, "").strip():
            raise LLMConfigurationError(f"{config.ENV_ANTHROPIC_KEY} is not set; live investigation cannot run")
        try:
            import anthropic
        except ImportError as e:
            raise LLMConfigurationError("the 'anthropic' package is not installed") from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(timeout=self.timeout, max_retries=2)

    def _call(self, messages):
        a = self._anthropic
        try:  # no sampling parameters: current models reject non-default values
            resp = self._client.messages.create(model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT, messages=messages)
        except a.APITimeoutError as e:
            raise LLMCallError("provider call timed out", "timeout") from e
        except a.APIStatusError as e:
            raise _status_error(e, "Anthropic") from e
        except a.APIError as e:
            raise LLMCallError(f"provider API error: {e.__class__.__name__}", "api_error") from e
        except Exception as e:  # any other SDK/transport failure is reported, never masked or fabricated
            raise LLMCallError(f"unexpected provider error: {e.__class__.__name__}: {str(e)[:200]}", "unexpected") from e
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise LLMCallError("model refused", "refusal")
        if stop == "max_tokens":
            raise LLMCallError("response truncated at max_tokens", "max_output_tokens")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = {"input_tokens": getattr(resp.usage, "input_tokens", None), "output_tokens": getattr(resp.usage, "output_tokens", None)}
        return text, usage

    def investigate(self, packet):
        """Return (LLMInvestigationOutput, metadata). One corrective retry on invalid output; never fabricates."""
        messages = [{"role": "user", "content": user_message(packet)}]
        usage_total, last_error = {}, None
        for attempt in (1, 2):
            started = time.monotonic()
            text, usage = self._call(messages)
            usage_total = {k: (usage_total.get(k) or 0) + (v or 0) for k, v in usage.items()}
            try:
                out = LLMInvestigationOutput.model_validate(parse_json_object(text))
                return out, {"attempts": attempt, "usage": dict(usage_total, latency_seconds=round(time.monotonic() - started, 2))}
            except (LLMCallError, ValidationError) as e:
                last_error = e
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": "Your response did not match the required JSON schema: "
                                                         f"{str(e)[:1500]}\nReturn ONLY the corrected JSON object."}]
        raise LLMCallError(f"model output invalid after 2 attempts: {str(last_error)[:500]}", "invalid_output")

    def check_availability(self):
        try:
            m = self._client.models.retrieve(self.model)
        except Exception as e:
            a = self._anthropic
            if isinstance(e, a.APIStatusError):
                raise _status_error(e, "Anthropic") from e
            raise LLMCallError(f"availability check failed: {e.__class__.__name__}", "unexpected") from e
        return {"provider": self.provider, "model": self.model, "available": True, "model_id": getattr(m, "id", self.model)}


class OfflineSimulatedInvestigator:
    """Deterministic stand-in for tests. Builds output strictly from packet facts. Output is SIMULATED, not AI analysis."""
    provider = "offline-simulated"
    model = "deterministic-stub-v1"
    simulated = True

    def investigate(self, packet):
        x = packet["exception"]
        findings, cited = [], set()
        for r in packet["control_results"]:
            if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE") and len(findings) < 6:
                src = [e for e in r["evidence_ids"] if e in packet["allowed_citation_ids"]][:4]
                fid = f"F-{len(findings) + 1:02d}"
                findings.append({"finding_id": fid,
                                 "claim": f"Engine control result {r['result_id']} is {r['outcome']} "
                                          f"(computed {r['computed'] or 'not available'}, reported {r['reported'] or 'not available'}).",
                                 "explanation": "Quoted from the deterministic engine output; not recalculated.",
                                 "evidence_ids": [r["result_id"]] + src, "supporting_records": src,
                                 "title": f"Engine result {r['result_id'].split('|')[0]} is {r['outcome']}",
                                 "audit_relevance": "SIMULATED: the engine result is one of the exception's affected results.",
                                 "establishes": "SIMULATED: the engine reported this outcome with the quoted values.",
                                 "does_not_establish": "SIMULATED: the reason for the outcome is not established."})
                cited |= {r["result_id"], *src}
        hyps = []
        for c in packet["candidate_relationships"]:
            hyps.append({"hypothesis_id": f"H-{len(hyps) + 1:02d}",
                         "possible_explanation": f"The exceptions {c['exception_ids']} may be related ({c['basis']}).",
                         "supporting_evidence": [c["candidate_id"]], "contradictory_evidence": [],
                         "limitations": "Candidate relationship is unverified; no record links the two exceptions.",
                         "status": "HYPOTHESIS",
                         "rationale": "SIMULATED: the engine recorded an unverified candidate relationship."})
            cited.add(c["candidate_id"])
        missing = []
        for m in packet["missing_evidence"]:
            missing.append({"item_id": f"M-{len(missing) + 1:02d}", "description": f"{m['expected_evidence']} is not available.",
                            "expected_source": m["expected_evidence"], "impact": m["completeness_impact"],
                            "related_ids": [m["item_id"]]})
            cited.add(m["item_id"])
        for s in packet["searches"]:
            if s["result"] == "NOT_FOUND":
                missing.append({"item_id": f"M-{len(missing) + 1:02d}", "description": f"Not found: {s['description']}.",
                                "expected_source": json.dumps(s["query"], sort_keys=True)[:200], "impact": "Cannot be relied upon.",
                                "related_ids": [s["search_id"]]})
                cited.add(s["search_id"])
        contradictions = []
        for i, c in enumerate(packet["conflicts"][:10]):
            pair = c["evidence_ids"][:2] if len(set(c["evidence_ids"])) >= 2 else [c["conflict_id"], c["evidence_ids"][0]]
            contradictions.append({"item_id": f"C-{i + 1:02d}", "description": c["description"], "evidence_ids": c["evidence_ids"],
                                   "compared_evidence": pair,
                                   "same_measure_and_scope": f"Deterministic conflict {c['conflict_id']}: the engine compared these "
                                                             "items for the same subject and scope."})
        for c in contradictions:
            cited |= set(c["evidence_ids"])
        assessment = ("INSUFFICIENT_EVIDENCE" if missing else "CONFLICTING_EVIDENCE" if contradictions
                      else "PARTIALLY_SUFFICIENT")
        out = {"investigation_summary": f"SIMULATED OFFLINE OUTPUT (not AI analysis) for {x['exception_id']}: "
                                        f"{len(findings)} engine facts quoted, {len(missing)} missing items, "
                                        f"{len(hyps)} hypotheses.",
               "confirmed_findings": findings, "hypotheses": hyps, "contradictory_evidence": contradictions,
               "missing_evidence": missing, "open_questions": ["What evidence explains the difference?"],
               "recommended_next_steps": [{"step_id": "S-01", "action": "Human reviewer to examine the cited records.",
                                           "rationale": "Simulated output; no analysis performed.",
                                           "evidence_needed": "As listed under missing evidence."}],
               "overall_evidence_assessment": assessment, "evidence_references": sorted(cited)}
        return LLMInvestigationOutput.model_validate(out), {"attempts": 1, "usage": {}}


class ScriptedInvestigator:
    """Test double that returns a fixed raw response (dict or text) to exercise validation and error handling."""
    provider = "test-scripted"
    model = "scripted"
    simulated = True

    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def investigate(self, packet):
        if self.error:
            raise self.error
        raw = self.response(packet) if callable(self.response) else self.response
        data = parse_json_object(raw) if isinstance(raw, str) else raw
        try:
            return LLMInvestigationOutput.model_validate(data), {"attempts": 1, "usage": {}}
        except ValidationError as e:
            raise LLMCallError(f"model output failed schema validation: {str(e)[:500]}", "invalid_output") from e


def investigator_from_env():
    """The configured investigator. OpenAI is the only live provider of the application; there is no automatic fallback
    provider, so a failed OpenAI request is reported as it failed and never routed elsewhere."""
    s = _settings()
    if s["provider"] == "openai":
        return OpenAIInvestigator()
    if s["provider"] == "anthropic":
        return AnthropicInvestigator()
    if s["provider"] == "offline":
        return OfflineSimulatedInvestigator()
    raise LLMConfigurationError(f"unsupported provider {s['provider']!r} (supported: openai, anthropic, offline)")
