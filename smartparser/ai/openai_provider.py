"""Phase 3B-10 - live OpenAI mapping proposer (an implementation of the existing MappingProposer interface).

Nothing new is decided here: the request is the existing versioned prompt (ai/prompts/mapping_prompt_v1.md) + the
existing DATA block (`prompting.render`, value shapes NEVER included unless AIConfig.send_value_shapes, which stays off)
+ the existing strict category-specific response schema (`prompting.response_schema`). The response TEXT is returned to
`run_proposal`, which parses it as untrusted input and runs the deterministic validator - the validator, not the model,
decides every class. The gateway (feature flag, budget gate, timeout, retry, audit) is unchanged and wraps this class.

Safety:
  * the API key is passed in by the caller and kept only on the client object; it is never logged, returned or stored;
  * provider errors are re-raised as `ProviderCallError(kind, http_status)` WITHOUT the provider's message text (which
    may echo a masked key fragment or request content);
  * `store=False` (no Responses API application-state storage);
  * token usage is recorded exactly as reported (`last_usage`); OpenAI does not report cost, so no cost is recorded.
The `openai` SDK is imported lazily, only when an adapter is constructed (the package imports no network library).
"""
from __future__ import annotations

import copy
import json

from ..mapping.proposals import ProposalRequest
from .prompting import instructions, render, response_schema


class ProviderCallError(RuntimeError):
    def __init__(self, kind: str, http_status: int | None = None):
        super().__init__(f"{kind}" + (f" (HTTP {http_status})" if http_status else ""))
        self.kind, self.http_status = kind, http_status


def _provider_schema(schema: dict) -> dict:
    """The existing schema expressed in the provider's strict structured-output subset (drop $schema/title/maxLength,
    `const` -> single-value `enum`). Same allowed fields, indexes and shape; the deterministic validator re-checks all."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            for k in ("$schema", "title", "maxLength"):
                node.pop(k, None)
            if "const" in node:
                node["enum"] = [node.pop("const")]
                node.setdefault("type", "string")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    return s


class OpenAIMappingProposer:
    is_live = True

    def __init__(self, api_key: str, model: str, max_output_tokens: int, timeout_seconds: float,
                 reasoning_effort: str | None = None, send_value_shapes: bool = False, client=None):
        if not api_key and client is None:
            raise ProviderCallError("authentication_missing")
        self.model, self.max_output_tokens, self.timeout = model, max_output_tokens, timeout_seconds
        self.reasoning_effort, self.send_value_shapes = reasoning_effort, send_value_shapes
        self.provider_id = f"openai-responses/{model}"
        if client is None:
            import openai                                   # lazy: only a constructed live adapter needs the SDK
            self._openai = openai
            client = openai.OpenAI(api_key=api_key, max_retries=0)   # retries are the gateway's (AI_MAX_RETRIES)
        else:
            self._openai = None
        self._client = client
        self.requests = 0                                   # actual HTTP requests attempted by this adapter
        self.last_usage: dict | None = None
        self.usage_log: list[dict] = []                     # one entry per request: tokens as reported, status

    def request_kwargs(self, request: ProposalRequest) -> dict:
        payload = render(request, self.send_value_shapes)
        kwargs = {
            "model": self.model, "instructions": instructions(),
            "input": [{"role": "user", "content": json.dumps(payload["data_block"], ensure_ascii=False)}],
            "text": {"format": {"type": "json_schema", "name": "smartparser_mapping_proposal", "strict": True,
                                "schema": _provider_schema(response_schema(request))}},
            "max_output_tokens": self.max_output_tokens, "store": False, "timeout": self.timeout,
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs

    def _kind(self, exc) -> tuple[str, int | None]:
        o = self._openai
        status = getattr(exc, "status_code", None)
        if o is None:
            return type(exc).__name__, status
        if isinstance(exc, o.AuthenticationError):
            return "authentication", status
        if isinstance(exc, o.PermissionDeniedError):
            return "permission_denied", status
        if isinstance(exc, o.RateLimitError):
            return "rate_limit_or_quota", status
        if isinstance(exc, o.NotFoundError):
            return "model_unavailable", status
        if isinstance(exc, o.BadRequestError):
            return "bad_request", status
        if isinstance(exc, o.APITimeoutError):
            return "timeout", None
        if isinstance(exc, o.APIConnectionError):
            return "connection", None
        if isinstance(exc, o.APIStatusError):
            return "api_status", status
        return "unexpected", status

    def propose(self, request: ProposalRequest) -> str:
        self.requests += 1
        kwargs = self.request_kwargs(request)
        sent = json.loads(kwargs["input"][0]["content"])["content"]
        meta = {"category": request.category,
                "sent_headers": [c["source_header"] for c in sent["unresolved_columns"]],
                "value_shapes_in_payload": any(c.get("value_shapes") for c in sent["unresolved_columns"])}
        try:
            resp = self._client.responses.create(**kwargs)
        except Exception as exc:                            # sanitised: never the provider's message text
            kind, status = self._kind(exc)
            self.usage_log.append({"status": "ERROR", "kind": kind, "http_status": status, **meta})
            raise ProviderCallError(kind, status) from None
        u = getattr(resp, "usage", None)
        details = getattr(u, "output_tokens_details", None) if u is not None else None
        self.last_usage = None if u is None else {
            "input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None),
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details is not None else None}
        status = getattr(resp, "status", None)
        self.usage_log.append({"status": status, "usage": self.last_usage, "response_model": getattr(resp, "model", None),
                               **meta})
        if status != "completed":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
            raise ProviderCallError(f"response_{status}" + (f":{reason}" if reason else ""))
        text = getattr(resp, "output_text", None)
        if not text:
            raise ProviderCallError("empty_output")
        return text
