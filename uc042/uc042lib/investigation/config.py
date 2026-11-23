"""Configuration for the investigation layer. Provider settings come from environment variables; no secrets in code.

A local `uc042/.env` file (never committed) is loaded once at import with python-dotenv. Variables already set in the
process environment always win, and no value is ever printed or logged.
"""
import os
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
PACKS_ROOT = PROJECT / "packs"
DATASETS_ROOT = PROJECT / "uc042_dataset"
INVESTIGATIONS_ROOT = PROJECT / "investigations"
ENV_FILE = PROJECT / ".env"

WORKFLOW_VERSION = "uc042-investigation-graph/1.1"            # fixed mode (V1)
TOOLS_WORKFLOW_VERSION = "uc042-investigation-graph/2.0-tools"  # tools mode (V2 nested tool-calling subgraph)
DET_WORKFLOW_VERSION = "uc042-investigation-graph/3.0-det"     # deterministic retrieval + one structured request (phase 6)
# Pre-request input-size guard for single-request modes (fixed / deterministic): estimated tokens of instructions + first
# message (about 3 characters per token, as the tool loop estimates). Tools mode keeps its own per-request guard.
ENV_SINGLE_REQUEST_MAX_INPUT_TOKENS = "UC042_SINGLE_REQUEST_MAX_INPUT_TOKENS"
DEFAULT_SINGLE_REQUEST_MAX_INPUT_TOKENS = 150000
PROMPT_VERSION = "uc042-investigator-prompt/1.11"              # 1.1: contradiction rules; 1.2: schema 1.4 explanatory fields;
# 1.3 / 2.3: the prompt names every causal phrase the findings validation refuses (validation.CAUSE_PATTERNS, unchanged);
# 2.2 named only two of them, so a live investigation was refused for "due to" (12 Nov 2026).
TOOLS_PROMPT_VERSION = "uc042-investigator-prompt/2.11-tools"
# 1.10 / 2.10-tools (23 Nov 2026, demo feedback): plain-English presentation rule (headline-first summary, amounts with
# currency, no control codes in prose, short titles and sentences). Wording only; no validation rule changed.
# 1.11 / 2.11-tools (23 Nov 2026, owner): the summary states what triggered the exception when the engine established it;
# £/€ symbols; evidence_references never lists the output's own item IDs (validation now drops them with a note).
# 1.9 / 2.9-tools (23 Nov 2026, live prompt-1.8 verification): engine relationships. The evidence of an enriched pack
# carries engine_relationships (relationship register 1.1 with proofs); the prompt never mentioned them, so a live TC06-01
# investigation called an engine-CONFIRMED relationship merely possible. Now: CONFIRMED = an engine result reported as a
# confirmed finding with the proof's figures and records; a relationship is not a cause (the reason for a faulty record
# stays in does_not_establish / hypotheses); CANDIDATE = hypotheses only; REJECTED = not related. Validation unchanged.
# 1.8 / 2.8-tools (20 Nov 2026, live M3 refusal): the five kinds of citable ID, the four citation classes of model view
# 1.3, evidence_basis (findings schema 1.5), and absent / not assessable / not retrieved. The earlier prompts listed the
# exception and MISS- IDs as finding support (confirmed_finding_ids) although validation never accepted them as such.
# 1.7 / 2.7-tools (review DR-12): the citation-class rule names a hypothesis's own contradictory_evidence field and the
# top-level contradictory_evidence list separately; the verified_links amounts column is described as model view 1.2 has it
# (signed, one-to-one only, null = not compared). Validation unchanged.
# 1.6 / 2.6-tools (phase 5): verified_links (tool vocabulary) and contextual associations in the view; no re-confirmation.
# 1.5 / 2.5-tools (phase 4): OpenAI requests carry the lossless model view (packet_view.py), no duplicated schema.
# 1.4 / 2.4-tools (token-optimisation copy, phase 1): citation classes (CAND- hypotheses only) and concise-output
# guidance; investigations use UC042_INVESTIGATION_MAX_OUTPUT_TOKENS.
FINDINGS_SCHEMA_VERSION = "uc042-investigation-findings/1.5"   # 1.3: compared contradictions; 1.4: finding/hypothesis explanations;
# 1.5: confirmed-finding evidence_basis (SOURCE_EVIDENCE / CONTROL_RESULT / EVIDENCE_ABSENCE), additive; older artefacts
# load with it as "not supplied" and keep their bytes
PACKET_VERSION = "uc042-evidence-packet/1.0"
LEDGER_VERSION = "uc042-evidence-ledger/1.0"

# Environment variables (values are never logged).
ENV_PROVIDER = "UC042_LLM_PROVIDER"        # "openai" (live, default), "anthropic" (live, legacy) or "offline" (simulated, tests only)
ENV_MODEL = "UC042_LLM_MODEL"
ENV_TIMEOUT = "UC042_LLM_TIMEOUT_SECONDS"  # per provider request
ENV_TOTAL_TIMEOUT = "UC042_LLM_TOTAL_TIMEOUT_SECONDS"  # wall-clock budget for one investigation's model calls
ENV_MAX_TOKENS = "UC042_LLM_MAX_TOKENS"            # closing summary (and any non-investigation structured request)
# Investigation requests (fixed-mode request and every tool-loop turn) have their own output budget, so raising it never
# changes the closing-summary budget. 12 Nov / 15 Nov / 16 Nov 2026: SC3C final answers used 7,877-8,000 of 8,000 and were
# truncated twice. A higher value can increase output consumption: deploying it needs owner approval.
ENV_INVESTIGATION_MAX_TOKENS = "UC042_INVESTIGATION_MAX_OUTPUT_TOKENS"
DEFAULT_INVESTIGATION_MAX_TOKENS = 12000
ENV_REASONING_EFFORT = "UC042_OPENAI_REASONING_EFFORT"  # optional; sent only when set
ENV_OPENAI_KEY = "OPENAI_API_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"

# There is no automatic fallback provider: OpenAI is the only live provider for UC-042 (Groq removed 12 Nov 2026).
# A failed OpenAI request is reported as it failed; it is never sent to another provider.

DEFAULT_PROVIDER = "openai"
DEFAULT_MODELS = {"openai": "gpt-6-luna", "anthropic": "claude-sonnet-5-5"}
OPENAI_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def load_local_env(path=ENV_FILE):
    """Load a local .env into os.environ without overriding variables that are already set. Returns True if loaded."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is optional; the process environment still works
        return False
    return bool(load_dotenv(path, override=False))


LOCAL_ENV_LOADED = load_local_env()


def _number(name, default, kind):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ValueError(f"{name} must be a {kind.__name__}, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {raw!r}")
    return value


def provider_settings():
    """Provider settings from the environment. Raises ValueError for malformed values."""
    provider = (os.environ.get(ENV_PROVIDER, "").strip() or DEFAULT_PROVIDER).lower()
    timeout = _number(ENV_TIMEOUT, 120.0, float)
    effort = os.environ.get(ENV_REASONING_EFFORT, "").strip().lower() or None
    return {"provider": provider,
            "model": os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODELS.get(provider, ""),
            "timeout": timeout,
            "total_timeout": _number(ENV_TOTAL_TIMEOUT, max(300.0, timeout), float),
            "max_tokens": _number(ENV_MAX_TOKENS, 8000, int),
            "investigation_max_tokens": _number(ENV_INVESTIGATION_MAX_TOKENS, DEFAULT_INVESTIGATION_MAX_TOKENS, int),
            "reasoning_effort": effort}


# Investigation mode: "fixed" (V1, default) or "tools" (V2 bounded tool calling). Never switched silently.
ENV_MODE = "UC042_INVESTIGATION_MODE"
MODES = ("fixed", "tools", "deterministic")  # deterministic: phase 6 (not the application default)
DEFAULT_MODE = "fixed"

# V2 tool-calling limits (environment overrides in brackets).
ENV_TOOL_LIMITS = {"max_tool_calls": ("UC042_TOOLS_MAX_CALLS", 8),            # tool calls per investigation (incl. rejected/duplicate)
                   "max_rounds": ("UC042_TOOLS_MAX_ROUNDS", 4),               # model -> tools -> model rounds
                   "max_records_per_call": ("UC042_TOOLS_MAX_RECORDS_PER_CALL", 25),
                   "max_input_tokens": ("UC042_TOOLS_MAX_INPUT_TOKENS", 150000)}  # estimated, checked before every request
TOOL_MAX_RECORDS_PER_CALL = 25
TOOL_MAX_DATE_SPAN_DAYS = 7       # bank and cash-book date searches
TOOL_MAX_CLIENT_SPAN_DAYS = 31    # client transactions and snapshots


def investigation_mode():
    mode = (os.environ.get(ENV_MODE, "").strip() or DEFAULT_MODE).lower()
    if mode not in MODES:
        raise ValueError(f"{ENV_MODE} must be one of {MODES}, got {mode!r}")
    return mode


def tool_limits():
    """Tool-loop limits; the overall wall-clock budget is UC042_LLM_TOTAL_TIMEOUT_SECONDS (default 300 s)."""
    limits = {k: _number(env, default, int) for k, (env, default) in ENV_TOOL_LIMITS.items()}
    limits["max_total_records"] = MAX_RECORDS
    limits["total_timeout"] = provider_settings()["total_timeout"]
    return limits


def api_key_configured(name=ENV_OPENAI_KEY):
    """Whether a non-blank key is present (the value itself is never returned)."""
    return bool(os.environ.get(name, "").strip())


# Identifier formats accepted from callers (prevents path traversal through IDs).
PACK_ID_RE = re.compile(r"^PACK-[A-Z0-9]{1,12}-PER-\d{4}-\d{2}-[0-9a-f]{12}$")
EXCEPTION_ID_RE = re.compile(r"^EXC-[A-Z0-9]{1,12}-\d{2,3}$")

# Files that must never enter the investigation context (planted answers / test oracles).
FORBIDDEN_NAMES = {"answer_key.json", "mutations.json", "SCENARIO_NOTES.md", "scenario.json",
                   "scenario_definition.json"}  # the historical demonstration package's planted-answer files
# Any path part below an approved root (uc042lib.investigation.roots.FORBIDDEN_DIRS adds the same rule for the roots).
FORBIDDEN_DIR_PARTS = {"golden", "tests", "verification", "UC042_JAN_AUG_HISTORICAL_DEMO"}

# Cap on source records in one evidence packet (keeps the LLM context scoped).
MAX_RECORDS = 160


def single_request_max_input_tokens():
    return _number(ENV_SINGLE_REQUEST_MAX_INPUT_TOKENS, DEFAULT_SINGLE_REQUEST_MAX_INPUT_TOKENS, int)
