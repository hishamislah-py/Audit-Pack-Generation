"""Phase 3B-4 - AI mapping configuration (feature flags). Safe defaults: AI disabled, no provider, no network.

None of the provider, model, region, data-sharing, token or cost settings has been decided by the owner. Unset values
stay None and the budget gate denies every live call until they are configured. No credential is read or stored here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TEST_STUB_PROVIDER = "recorded_stub"


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _opt_int(v):
    return int(v) if v not in (None, "") else None


def _opt_float(v):
    return float(v) if v not in (None, "") else None


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = False                 # AI_MAPPING_ENABLED
    provider: str | None = None           # AI_PROVIDER (owner decision; "recorded_stub" = tests only)
    model: str | None = None              # AI_MODEL
    region: str | None = None             # AI_REGION
    store: bool = False                   # AI_STORE (provider-side retention; must stay false)
    max_output_tokens: int | None = None  # AI_MAX_OUTPUT_TOKENS
    max_calls_per_day: int | None = None  # AI_MAX_CALLS_PER_DAY
    max_cost_per_day: float | None = None  # AI_MAX_COST_PER_DAY (currency deliberately unspecified: owner decision)
    timeout_seconds: float = 30.0         # AI_TIMEOUT_SECONDS
    max_retries: int = 1                  # AI_MAX_RETRIES (one retry, Phase 3A)
    send_value_shapes: bool = False       # owner decision: may value shapes leave the machine? (stub: local only)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "AIConfig":
        e = os.environ if env is None else env
        return cls(enabled=_bool(e.get("AI_MAPPING_ENABLED"), False), provider=e.get("AI_PROVIDER") or None,
                   model=e.get("AI_MODEL") or None, region=e.get("AI_REGION") or None,
                   store=_bool(e.get("AI_STORE"), False), max_output_tokens=_opt_int(e.get("AI_MAX_OUTPUT_TOKENS")),
                   max_calls_per_day=_opt_int(e.get("AI_MAX_CALLS_PER_DAY")),
                   max_cost_per_day=_opt_float(e.get("AI_MAX_COST_PER_DAY")),
                   timeout_seconds=float(e.get("AI_TIMEOUT_SECONDS") or 30.0),
                   max_retries=int(e.get("AI_MAX_RETRIES") or 1),
                   send_value_shapes=_bool(e.get("AI_SEND_VALUE_SHAPES"), False))

    @property
    def is_test_stub(self) -> bool:
        return self.provider == TEST_STUB_PROVIDER
