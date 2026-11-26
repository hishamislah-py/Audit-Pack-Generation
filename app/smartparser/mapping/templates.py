"""Mapping template registry (spec section 4).

A template is a reusable *mapping*, never data. Only templates with status
``validated`` are applied automatically, and only to compatible layouts:
either the exact layout fingerprint matches, or every source column the
template maps is present in the new upload. Filenames play no part.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .names import normalise_name


class TemplateStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def layout_fingerprint(headers: list[str]) -> str:
    """Order-independent fingerprint of a header set (reordered columns -> same layout)."""
    key = "|".join(sorted(normalise_name(h) for h in headers))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class MappingTemplate(BaseModel):
    template_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str
    schema_version: str
    source_columns: list[str]
    layout_fingerprint: str
    mapping: dict[str, str]          # source column -> canonical field
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "manual"       # manual | ai_suggestion_confirmed | ...
    validation_outcome: str | None = None
    status: TemplateStatus = TemplateStatus.PROPOSED


class TemplateRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._templates: dict[str, MappingTemplate] = {}
        if self.path and self.path.exists():
            for t in json.loads(self.path.read_text("utf-8")):
                tpl = MappingTemplate.model_validate(t)
                self._templates[tpl.template_id] = tpl

    def _persist(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(
                [t.model_dump(mode="json") for t in self._templates.values()], indent=2), "utf-8")

    def add(self, category: str, schema_version: str, source_columns: list[str],
            mapping: dict[str, str], status: TemplateStatus = TemplateStatus.PROPOSED,
            created_by: str = "manual", validation_outcome: str | None = None) -> MappingTemplate:
        unknown = set(mapping) - set(source_columns)
        if unknown:
            raise ValueError(f"mapping references columns not in source_columns: {sorted(unknown)}")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("a canonical field may be mapped from only one source column")
        with self._lock:
            fp = layout_fingerprint(source_columns)
            prior = [t for t in self._templates.values()
                     if t.category == category and t.layout_fingerprint == fp]
            tpl = MappingTemplate(
                category=category, schema_version=schema_version, source_columns=source_columns,
                layout_fingerprint=fp, mapping=mapping, status=status, created_by=created_by,
                validation_outcome=validation_outcome,
                version=max((t.version for t in prior), default=0) + 1,
            )
            if status == TemplateStatus.VALIDATED:
                for t in prior:
                    if t.status == TemplateStatus.VALIDATED:
                        t.status = TemplateStatus.SUPERSEDED
            self._templates[tpl.template_id] = tpl
            self._persist()
        return tpl

    def set_status(self, template_id: str, status: TemplateStatus,
                   validation_outcome: str | None = None) -> MappingTemplate:
        with self._lock:
            tpl = self._templates[template_id]
            if status == TemplateStatus.VALIDATED:
                for t in self._templates.values():
                    if (t.template_id != template_id and t.category == tpl.category
                            and t.layout_fingerprint == tpl.layout_fingerprint
                            and t.status == TemplateStatus.VALIDATED):
                        t.status = TemplateStatus.SUPERSEDED
            tpl.status = status
            if validation_outcome is not None:
                tpl.validation_outcome = validation_outcome
            self._persist()
            return tpl

    def all(self) -> list[MappingTemplate]:
        return list(self._templates.values())

    def find_compatible(self, headers: list[str], category: str | None = None,
                        schema_version: str | None = None) -> list[MappingTemplate]:
        """Validated templates compatible with this header set, best first."""
        fp = layout_fingerprint(headers)
        present = set(headers)
        out = []
        for t in self._templates.values():
            if t.status != TemplateStatus.VALIDATED:
                continue
            if category and t.category != category:
                continue
            if schema_version and t.schema_version != schema_version:
                continue
            if t.layout_fingerprint == fp:
                out.append((0, t))
            elif set(t.mapping).issubset(present):
                out.append((1, t))
        return [t for _, t in sorted(out, key=lambda x: (x[0], -x[1].version))]
