"""Module J - AI assistance interface (Phase 6). INTERFACE ONLY.

Contract: every AI output is an *advisory suggestion*. The pipeline records
suggestions next to deterministic results; it never applies them as fact,
never fills missing values with them, and always re-runs deterministic
validation on anything a human later confirms.
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class CategorySuggestion(BaseModel):
    category: str | None
    rationale: str
    advisory: bool = True


class MappingSuggestion(BaseModel):
    source_column: str
    canonical_field: str | None
    rationale: str
    advisory: bool = True


class FieldLocationSuggestion(BaseModel):
    field: str
    page: int | None = None
    excerpt: str | None = None
    rationale: str = ""
    advisory: bool = True


class AIAssistant(Protocol):
    def suggest_category(self, headers: list[str], sample_rows: list[list[str]],
                         candidates: list[str]) -> CategorySuggestion | None: ...

    def suggest_mappings(self, unmapped_columns: list[str], sample_values: dict[str, list[str]],
                         schema_fields: list[dict]) -> list[MappingSuggestion]: ...

    def explain_missing(self, field: str, context: dict) -> str | None: ...


class NullAssistant:
    """Default: AI disabled. Returns nothing."""

    def suggest_category(self, headers, sample_rows, candidates):
        return None

    def suggest_mappings(self, unmapped_columns, sample_values, schema_fields):
        return []

    def explain_missing(self, field, context):
        return None


__all__ = ["AIAssistant", "NullAssistant", "CategorySuggestion", "MappingSuggestion",
           "FieldLocationSuggestion"]
