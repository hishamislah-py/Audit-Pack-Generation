"""Fix8 D1 - live AI MAPPING proposals in the application: configuration from the server's AI env file.

The live proposer is the EXISTING `OpenAIMappingProposer` wrapped by the EXISTING `ProposalGateway` (feature flag, budget
gate, deduplication, timeout + retry, PROVIDER_CALL audit). Nothing here changes how a proposal is validated, routed or
approved: deterministic mapping runs first, only unresolved headers are sent, the deterministic validator decides every
class, and a person decides every column (the POC auto-accept policy stays as shipped: DISABLED).

Credentials: the env file is read with an EXACT key allowlist (the same keys the closure runner uses; never a prefix
match, so UC042_LLM_FALLBACK_* / database URLs are never read). The key is handed to the adapter only; it is never put in
a log, an audit record, the `/api/app` view or an exception message.

Defaults are safe: mapping AI is OFF unless the server is started with `--mapping-ai on`; value shapes are NOT sent unless
`--mapping-ai-send-value-shapes` is given (owner default: off); a per-day call cap and an output-token cap always apply.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AIConfig
from .gateway import DisabledLiveProvider, ProposalGateway, UsageLedger

ENV_KEYS = ("OPENAI_API_KEY", "UC042_LLM_PROVIDER", "UC042_LLM_MODEL", "UC042_LLM_TIMEOUT_SECONDS",
            "UC042_LLM_MAX_TOKENS", "UC042_OPENAI_REASONING_EFFORT")
REGION_NOT_PINNED = "provider default (not pinned; owner decision)"


def read_env_allowlist(path: str | Path | None) -> dict:
    """Only ENV_KEYS, exactly; every other line of the file is ignored."""
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
        if k not in ENV_KEYS:
            continue
        v = v.strip()
        if v[:1] in ("'", '"') and len(v) >= 2 and v[-1] == v[0]:
            v = v[1:-1]
        else:
            v = v.split(" #", 1)[0].strip()
        out[k] = v
    return out


@dataclass(frozen=True)
class MappingAISettings:
    """Server flags (webapp/server.py). `enabled` is the feature flag; everything else is a hard limit."""
    enabled: bool = False
    env_file: str | None = None
    max_calls_per_day: int = 20
    max_output_tokens: int = 4000
    max_cost_per_day: float = 1.0            # enforced only when a pricing entry exists for the model
    timeout_seconds: float | None = None     # default: UC042_LLM_TIMEOUT_SECONDS, else 60
    max_retries: int = 1
    send_value_shapes: bool = False
    pricing: dict | None = None              # {model: {input_per_m, cached_input_per_m, output_per_m}}


class _PricedProposer:
    """Adds a measured cost to the usage record when a pricing entry exists (so the daily cost cap is enforceable);
    otherwise the usage is passed through unchanged (cost is then not measured, and that is reported)."""

    def __init__(self, inner, price: dict | None):
        self.inner, self.price = inner, price
        self.provider_id = inner.provider_id
        self.is_live = True

    @property
    def last_usage(self):
        u = getattr(self.inner, "last_usage", None)
        if u is None or not self.price:
            return u
        inp, out = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        cost = (inp * float(self.price.get("input_per_m", 0)) + out * float(self.price.get("output_per_m", 0))) / 1e6
        return {**u, "cost": round(cost, 6)}

    @property
    def last_call(self):
        return getattr(self.inner, "last_call", None)

    def propose(self, request):
        return self.inner.propose(request)


def build_mapping_gateway(settings: MappingAISettings, log, ledger_path: Path) -> tuple[ProposalGateway, dict]:
    """(gateway, llm_mode view). LIVE only when the flag is on AND the env file supplies an OpenAI key; otherwise the
    disabled provider (every call DENIED and audited) and an honest mode label saying why."""
    ledger = UsageLedger(ledger_path)
    if not settings.enabled:
        return (ProposalGateway(proposer=DisabledLiveProvider(), config=AIConfig(), log=log, ledger=ledger),
                {"mode": "DISABLED", "label": "AI mapping proposals disabled (--mapping-ai off)", "fixtures": []})
    vals = read_env_allowlist(settings.env_file)
    provider = (vals.get("UC042_LLM_PROVIDER") or "openai").strip().lower()
    model = (vals.get("UC042_LLM_MODEL") or "").strip() or None
    problem = None
    if not settings.env_file:
        problem = "the server was started without --ai-env-file"
    elif not Path(settings.env_file).is_file():
        problem = "the AI env file does not exist"
    elif not vals.get("OPENAI_API_KEY", "").strip():
        problem = "OPENAI_API_KEY is not set in the AI env file"
    elif provider != "openai":
        problem = f"provider {provider!r} is not supported for mapping (OpenAI only)"
    elif not model:
        problem = "UC042_LLM_MODEL is not set in the AI env file"
    if problem:
        return (ProposalGateway(proposer=DisabledLiveProvider(), config=AIConfig(), log=log, ledger=ledger),
                {"mode": "UNAVAILABLE", "label": f"AI mapping proposals unavailable: {problem}", "fixtures": [],
                 "problem": problem})
    try:
        timeout = float(settings.timeout_seconds or vals.get("UC042_LLM_TIMEOUT_SECONDS") or 60)
    except ValueError:
        timeout = 60.0
    effort = (vals.get("UC042_OPENAI_REASONING_EFFORT") or "").strip() or None
    from .openai_provider import OpenAIMappingProposer
    key = vals.pop("OPENAI_API_KEY")
    adapter = OpenAIMappingProposer(api_key=key, model=model, max_output_tokens=settings.max_output_tokens,
                                    timeout_seconds=timeout, reasoning_effort=effort,
                                    send_value_shapes=settings.send_value_shapes)
    del key
    price = (settings.pricing or {}).get(model)
    proposer = _PricedProposer(adapter, price)
    cfg = AIConfig(enabled=True, provider="openai", model=model, region=REGION_NOT_PINNED, store=False,
                   max_output_tokens=settings.max_output_tokens, max_calls_per_day=settings.max_calls_per_day,
                   max_cost_per_day=settings.max_cost_per_day, timeout_seconds=timeout,
                   max_retries=settings.max_retries, send_value_shapes=settings.send_value_shapes)
    mode = {"mode": "LIVE", "label": f"Live AI mapping proposals (OpenAI {model}); every proposal is reviewed by an "
                                     "analyst", "fixtures": [], "provider": "openai", "model": model,
            "reasoning_effort": effort, "store": False, "value_shapes_sent": settings.send_value_shapes,
            "max_calls_per_day": settings.max_calls_per_day, "max_output_tokens": settings.max_output_tokens,
            "timeout_seconds": timeout, "max_retries": settings.max_retries,
            "cost_cap": settings.max_cost_per_day if price else None,
            "cost_measured": bool(price), "auto_accept": False}
    return ProposalGateway(proposer=proposer, config=cfg, log=log, ledger=ledger), mode
