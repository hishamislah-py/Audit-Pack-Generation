"""Canonical audit-pack model: deterministic identifiers, canonical JSON, fingerprints and required structure."""
import hashlib
import json
import re
from pathlib import Path

from . import config

ENGINE_DIR = Path(__file__).resolve().parent.parent
CITATION = re.compile(r"IN-(\d\d):([^#;\s,\]]+)(?:#L(\d+)(?:-L(\d+))?)?")
MONEY = re.compile(r"^-?\d+\.\d{2}$")

# Sections and keys every pack must contain (V1). Empty registers are explicit empty lists plus a statement.
REQUIRED = {
    "metadata": ["pack_id", "pack_schema_version", "reporting_period", "reconciliation_days", "entity", "asset_pool_id",
                 "currency_scope", "accounts", "source_dataset", "processing_run_id", "generation_status", "synthetic_notice"],
    "executive_summary": ["generation_status", "evidence_completeness", "control_outcomes", "exceptions", "exception_review",
                          "investigation_groups", "candidate_relationships", "missing_evidence_items", "engine_case_status",
                          "pack_review_status"],
    "reconciliation_summary": ["internal_by_currency_day", "external_by_account_day", "opening_positions", "client_balances_note"],
    "control_register": [],
    "evidence_register": ["files", "records"],
    "settlement_register": [],
    "exception_register": ["exceptions", "statement"],
    "investigation_group_register": ["groups", "statement", "candidate_relationships", "candidate_statement"],
    "missing_evidence_register": ["items", "statement", "optional_not_provided"],
    "audit_trail": ["inputs", "intake", "baseline_manifest_sha256", "engine_fingerprint", "configuration_fingerprint", "pack_layer_fingerprint",
                    "correlation_version", "processing_outputs", "pack_content_sha256", "review_events", "narrative"],
    "statements": ["synthetic_notice", "entity_notice", "not_a_compliance_opinion", "limitations"],
}


def canonical(obj):
    """Canonical JSON text: sorted keys, fixed separators, UTF-8, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(pack):
    """Hash of the canonical pack without its self-referential fields (pack_id, pack_content_sha256)."""
    body = json.loads(json.dumps(pack))
    body["metadata"]["pack_id"] = ""
    body["audit_trail"]["pack_content_sha256"] = ""
    return sha256_text(canonical(body))


def pack_id(scenario_id, period_id, chash):
    return f"PACK-{scenario_id}-{period_id}-{chash[:12]}"


def result_id(r):
    return f"{r['check_id']}|{r['scope']}"


def engine_fingerprint():
    h = hashlib.sha256()
    for name in config.ENGINE_MODULES:
        h.update(name.encode())
        h.update((ENGINE_DIR / name).read_bytes())
    return h.hexdigest()


def pack_layer_fingerprint():
    """Hash of the pack-assembly code: a change to it yields a new run ID and pack ID (no silent change)."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def configuration_fingerprint(registry_controls, engine_rules=None):
    """engine_rules: the run's EngineRules.recorded() (only departures from the published pre-17-Nov-2026 behaviour, so the
    fingerprints of packs built under the published rules are unchanged and every pack built under the approved rule
    records it)."""
    cfg = {"pack_schema_version": config.PACK_SCHEMA_VERSION, "entity_id": config.ENTITY_ID,
           "control_registry": registry_controls, "not_available": config.NOT_AVAILABLE,
           "limitations": config.LIMITATIONS}
    if engine_rules:
        cfg["engine_rules"] = engine_rules
    return sha256_text(canonical(cfg))


def run_id(input_hashes, engine_fp, config_fp, pack_fp):
    return "RUN-" + sha256_text(canonical({"inputs": input_hashes, "engine": engine_fp, "configuration": config_fp,
                                           "pack_layer": pack_fp}))[:16]
