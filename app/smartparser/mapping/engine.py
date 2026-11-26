"""Module F - deterministic column -> canonical field mapping.

Tier order (spec): exact -> known alias -> normalised name -> validated template
-> (AI suggestion, advisory only, never applied here).

Conflict policy - nothing is chosen arbitrarily:
* one source column matching several fields at its best tier  -> ambiguity
* several source columns matching the same field (any tiers)   -> ambiguity
Ambiguous fields/columns are left unmapped and reported for resolution.
"""
from __future__ import annotations

from collections import defaultdict

from ..models.enums import MappingStatus, MatchMethod
from ..models.results import AmbiguousMapping, ColumnMapping, MappingResult
from ..schemas.model import SchemaDefinition
from .names import normalise_name
from .templates import TemplateRegistry, layout_fingerprint

_TIER_ORDER = [MatchMethod.EXACT, MatchMethod.ALIAS, MatchMethod.NORMALISED]


def _candidates(header: str, schema: SchemaDefinition) -> tuple[MatchMethod, list[str]] | None:
    h = header.strip()
    hc = h.casefold()
    hn = normalise_name(h)
    tiers = {
        MatchMethod.EXACT: [f.name for f in schema.fields if f.name == h],
        MatchMethod.ALIAS: [f.name for f in schema.fields
                            if any(a.strip().casefold() == hc for a in f.aliases)],
        MatchMethod.NORMALISED: [f.name for f in schema.fields
                                 if hn and (normalise_name(f.name) == hn
                                            or any(normalise_name(a) == hn for a in f.aliases))],
    }
    for tier in _TIER_ORDER:
        if tiers[tier]:
            return tier, tiers[tier]
    return None


def map_columns(headers: list[str], schema: SchemaDefinition,
                templates: TemplateRegistry | None = None,
                manual: dict[str, str] | None = None) -> MappingResult:
    """Map source headers onto ``schema``.

    ``manual`` is an explicit user-confirmed {source column: field} override; it
    is applied first and recorded as ``MatchMethod.MANUAL``.
    """
    result = MappingResult(
        status=MappingStatus.NOT_ATTEMPTED, category=schema.category,
        schema_version=schema.schema_version,
        schema_verification=schema.verification_status.value,
        layout_fingerprint=layout_fingerprint(headers),
    )
    if not schema.is_defined:
        result.status = MappingStatus.SCHEMA_UNAVAILABLE
        result.unmapped_columns = list(headers)
        return result

    field_names = {f.name for f in schema.fields}
    claims: dict[str, list[tuple[int, MatchMethod, str | None]]] = defaultdict(list)
    ambiguous_cols: set[int] = set()
    resolved_cols: set[int] = set()

    for col, fld in (manual or {}).items():
        if fld not in field_names:
            raise ValueError(f"manual mapping targets unknown field '{fld}'")
        for idx, h in enumerate(headers):
            if h == col:
                claims[fld].append((idx, MatchMethod.MANUAL, None))
                resolved_cols.add(idx)

    for idx, h in enumerate(headers):
        if idx in resolved_cols:
            continue
        found = _candidates(h, schema)
        if not found:
            continue
        tier, fields = found
        resolved_cols.add(idx)
        if len(fields) > 1:  # cannot happen with a load-validated schema, but stay safe
            ambiguous_cols.add(idx)
            result.ambiguities.append(AmbiguousMapping(
                source_columns=[h], candidate_fields=sorted(fields),
                reason=f"column matches several fields at tier '{tier}'"))
            continue
        claims[fields[0]].append((idx, tier, None))

    # Tier 4: validated template, only for columns still unresolved.
    if templates is not None:
        compat = templates.find_compatible(headers, schema.category, schema.schema_version)
        if compat:
            tpl = compat[0]
            used = False
            for idx, h in enumerate(headers):
                if idx in resolved_cols or h not in tpl.mapping:
                    continue
                fld = tpl.mapping[h]
                if fld not in field_names:
                    continue
                claims[fld].append((idx, MatchMethod.TEMPLATE, tpl.template_id))
                resolved_cols.add(idx)
                used = True
            if used:
                result.template_id = tpl.template_id

    mapped_cols: set[int] = set()
    for fld, cl in claims.items():
        if len(cl) > 1:
            result.ambiguities.append(AmbiguousMapping(
                source_columns=[headers[i] for i, _, _ in cl], candidate_fields=[fld],
                reason="several source columns match the same canonical field"))
            ambiguous_cols.update(i for i, _, _ in cl)
            continue
        idx, method, tpl_id = cl[0]
        result.mappings.append(ColumnMapping(
            source_column=headers[idx], source_index=idx, canonical_field=fld,
            method=method, template_id=tpl_id))
        mapped_cols.add(idx)

    result.mappings.sort(key=lambda m: m.source_index)
    result.unmapped_columns = [h for i, h in enumerate(headers)
                               if i not in mapped_cols and i not in ambiguous_cols]
    mapped_fields = {m.canonical_field for m in result.mappings}
    ambiguous_fields = {f for a in result.ambiguities for f in a.candidate_fields}
    result.missing_required_fields = [f.name for f in schema.fields
                                      if f.required and f.name not in mapped_fields
                                      and f.name not in ambiguous_fields]
    result.missing_optional_fields = [f.name for f in schema.fields
                                      if not f.required and f.name not in mapped_fields
                                      and f.name not in ambiguous_fields]
    if result.ambiguities:
        result.status = MappingStatus.AMBIGUOUS
    elif result.missing_required_fields:
        result.status = MappingStatus.INCOMPLETE
    else:
        result.status = MappingStatus.COMPLETE
    return result
