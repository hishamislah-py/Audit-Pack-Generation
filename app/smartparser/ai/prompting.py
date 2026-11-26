"""Phase 3B-4 - versioned mapping prompt and strict, category-specific JSON response schema (for a later provider).

The schema restricts `canonical_field` to the confirmed category's field names plus UNMAPPABLE, and `source_index` to
the unresolved columns only. The deterministic validator (mapping.proposals.validate_proposal) remains the final
authority whatever a provider returns.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..mapping.proposals import RESPONSE_SCHEMA, UNMAPPABLE, ProposalRequest

PROMPT_VERSION = "uc042-mapping-prompt/1.0"
SCHEMA_VERSION = RESPONSE_SCHEMA            # "smartparser-mapping-proposal/1.0"
PROMPT_FILE = Path(__file__).parent / "prompts" / "mapping_prompt_v1.md"


def instructions() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def response_schema(request: ProposalRequest) -> dict:
    fields = [f.name for f in request.canonical_fields] + [UNMAPPABLE]
    indexes = [c.source_index for c in request.unresolved_columns]
    column = {
        "type": "object", "additionalProperties": False,
        "required": ["source_index", "source_header", "canonical_field", "assessment", "alternatives", "explanation",
                     "evidence"],
        "properties": {
            "source_index": {"type": "integer", "enum": indexes},
            "source_header": {"type": "string"},
            "canonical_field": {"type": "string", "enum": fields},
            "assessment": {"type": "string", "enum": ["CLEAR", "PLAUSIBLE", "AMBIGUOUS", "UNMAPPABLE"]},
            "alternatives": {"type": "array", "items": {"type": "string", "enum": fields[:-1]}},
            "explanation": {"type": "string", "maxLength": 2000},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        },
    }
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": SCHEMA_VERSION, "type": "object",
            "additionalProperties": False, "required": ["response_schema", "category", "columns", "notes"],
            "properties": {"response_schema": {"const": SCHEMA_VERSION}, "category": {"const": request.category},
                           "columns": {"type": "array", "items": column, "minItems": len(indexes),
                                       "maxItems": len(indexes)},
                           "notes": {"type": "string", "maxLength": 4000}}}


def render(request: ProposalRequest, send_value_shapes: bool = False) -> dict:
    """The provider payload: fixed instructions + a DATA block. Value shapes are included only if the owner allows."""
    data = json.loads(request.model_dump_json())
    if not send_value_shapes:
        for c in data["unresolved_columns"]:
            c["value_shapes"] = []
    return {"prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION, "instructions": instructions(),
            "data_block": {"notice": request.data_notice, "content": data}, "response_schema": response_schema(request)}


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
