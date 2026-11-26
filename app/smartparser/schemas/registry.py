"""Schema registry: loads one JSON definition per category from a directory."""
from __future__ import annotations

import json
from pathlib import Path

from .categories import OFFICIAL_CATEGORIES
from .model import SchemaDefinition, SchemaVerification

DEFAULT_DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class SchemaRegistryError(ValueError):
    pass


class SchemaRegistry:
    def __init__(self, schemas: list[SchemaDefinition], allow_non_official: bool = False):
        self._schemas: dict[str, SchemaDefinition] = {}
        for s in schemas:
            info = OFFICIAL_CATEGORIES.get(s.category)
            if info is None and not allow_non_official:
                raise SchemaRegistryError(f"Unknown category id '{s.category}'")
            if info is not None and info.evidence_format != s.evidence_format:
                raise SchemaRegistryError(
                    f"{s.category}: format '{s.evidence_format}' contradicts brief ('{info.evidence_format}')"
                )
            if s.category in self._schemas:
                raise SchemaRegistryError(f"Duplicate definition for {s.category}")
            self._schemas[s.category] = s
        self._check_identities()
        if not allow_non_official:
            # Every official category is always present - as a MISSING stub if need be.
            for cid, info in OFFICIAL_CATEGORIES.items():
                self._schemas.setdefault(
                    cid,
                    SchemaDefinition(
                        category=cid, title=info.title, evidence_format=info.evidence_format,
                        optional_evidence=info.optional,
                    ),
                )

    def _check_identities(self) -> None:
        """Content identities must not collide: two exact CSV headers that are equal, or two PDF label sets that are
        equal without being declared as a shared group, would make classification ambiguous by construction."""
        headers: dict[tuple, str] = {}
        for s in self._schemas.values():
            if s.csv is not None:
                key = tuple(s.csv.header)
                if key in headers:
                    raise SchemaRegistryError(f"{s.category} and {headers[key]} have the same canonical header")
                headers[key] = s.category
        labels = {s.category: frozenset(l.label for l in s.pdf.labels) for s in self._schemas.values() if s.pdf}
        for a, la in labels.items():
            same = sorted(b for b, lb in labels.items() if b != a and lb == la)
            declared = sorted(self._schemas[a].pdf.shared_label_group)
            if same != declared:
                raise SchemaRegistryError(f"{a}: categories with the same PDF labels {same} differ from the declared "
                                          f"shared_label_group {declared}")

    def exact_header_index(self) -> dict[tuple, str]:
        """{canonical header tuple: category} for schemas matched by exact header."""
        return {tuple(s.csv.header): s.category for s in self._schemas.values()
                if s.csv is not None and s.is_defined and s.classification.match_policy == "exact_header"}

    @classmethod
    def from_directory(cls, path: str | Path = DEFAULT_DEFINITIONS_DIR,
                       allow_non_official: bool = False) -> "SchemaRegistry":
        schemas = []
        for file in sorted(Path(path).glob("*.json")):
            try:
                schemas.append(SchemaDefinition.model_validate(json.loads(file.read_text("utf-8"))))
            except Exception as exc:  # surface which file is broken
                raise SchemaRegistryError(f"{file.name}: {exc}") from exc
        return cls(schemas, allow_non_official=allow_non_official)

    def get(self, category: str) -> SchemaDefinition | None:
        return self._schemas.get(category)

    def all(self) -> list[SchemaDefinition]:
        return list(self._schemas.values())

    def defined(self, evidence_format: str | None = None) -> list[SchemaDefinition]:
        return [s for s in self._schemas.values()
                if s.is_defined and (evidence_format is None or s.evidence_format == evidence_format)]

    def coverage_report(self) -> list[dict]:
        return [
            {
                "category": s.category,
                "title": s.title,
                "format": s.evidence_format,
                "optional": s.optional_evidence,
                "verification_status": s.verification_status.value,
                "field_count": len(s.pdf.labels) if s.pdf is not None else len(s.fields),
                "schema_version": s.schema_version,
                "definition_source": s.definition_source,
            }
            for s in sorted(self._schemas.values(), key=lambda x: x.category)
        ]

    def missing_categories(self) -> list[str]:
        return [s.category for s in self._schemas.values()
                if s.verification_status == SchemaVerification.MISSING]
