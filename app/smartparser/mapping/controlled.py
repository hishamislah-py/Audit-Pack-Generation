"""Module F (Phase 2) - controlled, deterministic CSV column mapping for exact-header (UC-042) schemas.

Three kinds of header handling, in order:
  A. canonical    the header equals the canonical header exactly (Phase 1 path in classify/csv_classifier.py)
  B. structural   reordered columns, and - only if the active policy enables them - surrounding whitespace and case
                  variations of the canonical names
  C. alias        a header listed in the ACTIVE approved-alias rules (rules/approved_aliases.json). Every active alias
                  must reference an entry with status "approved" in the separate proposal catalogue
                  (rules/alias_proposals.json); proposed or rejected entries are never used.

Acceptance is all-or-nothing per category: every source column resolves to exactly one canonical field, every
canonical field is present exactly once, no column is unexpected. Anything else is rejected with reasons; nothing is
discarded silently (unexpected/duplicate/ambiguous columns are listed in the result). No LLM, no fuzzy matching.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..models.enums import MappingStatus, MatchMethod
from ..models.results import ColumnMapping, MappingResult
from ..schemas.model import SchemaDefinition
from .governed import FileMappingRule, LayoutRule, Lifecycle, definition_sha256, header_fingerprint
from .templates import layout_fingerprint
from ..csv_engine.reader import column_keys

RULES_DIR = Path(__file__).parent / "rules"
PROPOSAL_STATUSES = {"proposed", "approved", "rejected"}


class MappingRulesError(ValueError):
    pass


@dataclass(frozen=True)
class MappingPolicy:
    allow_reorder: bool = True
    trim_whitespace: bool = True
    case_insensitive: bool = True
    unexpected_columns: str = "reject"          # the only supported value in Phase 2
    source: str = "default"


@dataclass
class ApprovedAlias:
    alias_id: str
    category: str
    canonical_field: str
    alias: str
    proposal_id: str
    approved_by: str
    approved_at: str
    rule_version: int = 1               # Phase 3B-2 governance (defaults keep Phase 2 entries valid)
    status: str = "active"


@dataclass
class MappingRules:
    policy: MappingPolicy
    aliases: list[ApprovedAlias] = field(default_factory=list)
    source: str = ""
    layouts: list[LayoutRule] = field(default_factory=list)              # Phase 3B-2
    file_mappings: list[FileMappingRule] = field(default_factory=list)   # Phase 3B-2
    file_identity: tuple[str, str] | None = None   # (intake_id, source_sha256) a file mapping may apply to

    def aliases_for(self, category: str) -> list[ApprovedAlias]:
        """ACTIVE aliases only: revoked or superseded aliases stay on file for history but never match."""
        return [a for a in self.aliases if a.category == category and a.status == "active"]

    def header_rules_for(self, category: str, raw_headers: list[str]) -> list:
        """Active layouts and (for the identified upload only) active file mappings whose EXACT header list equals the
        file's header list."""
        fp = header_fingerprint(raw_headers)
        out = [r for r in self.layouts if r.category == category and r.lifecycle.status == "active"
               and r.header_fingerprint == fp and r.headers == list(raw_headers)]
        if self.file_identity is not None:
            out += [r for r in self.file_mappings if r.category == category and r.lifecycle.status == "active"
                    and (r.intake_id, r.source_sha256) == self.file_identity and r.headers == list(raw_headers)]
        return out

    def with_file_identity(self, intake_id: str, source_sha256: str) -> "MappingRules":
        return MappingRules(self.policy, self.aliases, self.source, self.layouts, self.file_mappings,
                            (intake_id, source_sha256))

    def without_file_identity(self) -> "MappingRules":
        """The same rules with no file mapping applicable (used by automatic classification: a file-specific mapping
        is only applied once the category comes from a recorded confirmation, never to decide the category)."""
        return MappingRules(self.policy, self.aliases, self.source, self.layouts, self.file_mappings, None)


def is_controlled(schema: SchemaDefinition | None) -> bool:
    """Routing rule (Phase 3B-0): a schema whose CSV mapping MUST go through `controlled_map` - the authoritative UC-042
    CSV categories (a generated CSV contract with exact_header matching). Every other schema (synthetic / provisional
    test schemas, stubs) keeps the generic `mapping.engine.map_columns` path."""
    return (schema is not None and schema.evidence_format == "csv" and schema.csv is not None
            and schema.classification.match_policy == "exact_header")


def _key(header: str, policy: MappingPolicy) -> str:
    h = header.replace("﻿", "")
    if policy.trim_whitespace:
        h = h.strip()
    if policy.case_insensitive:
        h = h.casefold()
    return h


def load_proposals(path: str | Path) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    props = doc["proposals"]
    ids = [p["proposal_id"] for p in props]
    if len(ids) != len(set(ids)):
        raise MappingRulesError("duplicate proposal_id in the alias catalogue")
    for p in props:
        for k in ("proposal_id", "category", "canonical_field", "proposed_header", "reason", "risk", "status"):
            if not p.get(k):
                raise MappingRulesError(f"{p.get('proposal_id')}: '{k}' is required")
        if p["status"] not in PROPOSAL_STATUSES:
            raise MappingRulesError(f"{p['proposal_id']}: unknown status {p['status']!r}")
        if p["status"] in ("approved", "rejected"):
            meta = p.get("decision") or {}
            if not (meta.get("decided_by") and meta.get("decided_at")):
                raise MappingRulesError(f"{p['proposal_id']}: status {p['status']} needs decision.decided_by/decided_at")
    return props


def load_rules(registry, rules_path: str | Path | None = None, proposals_path: str | Path | None = None,
               layouts_path: str | Path | None = None, file_mappings_path: str | Path | None = None) -> MappingRules:
    """Load the active rules and check them against the catalogue and the registry. Raises MappingRulesError.
    Layouts and file mappings are read from `approved_layouts.json` / `file_mappings.json` next to the alias rules
    (or the given paths) when those files exist."""
    rules_path = Path(rules_path or RULES_DIR / "approved_aliases.json")
    proposals_path = Path(proposals_path or RULES_DIR / "alias_proposals.json")
    layouts_path = Path(layouts_path or rules_path.parent / "approved_layouts.json")
    file_mappings_path = Path(file_mappings_path or rules_path.parent / "file_mappings.json")
    doc = json.loads(rules_path.read_text(encoding="utf-8"))
    p = doc.get("policy", {})
    policy = MappingPolicy(allow_reorder=bool(p.get("allow_reorder", True)),
                           trim_whitespace=bool(p.get("trim_whitespace", True)),
                           case_insensitive=bool(p.get("case_insensitive", True)),
                           unexpected_columns=p.get("unexpected_columns", "reject"), source=str(rules_path))
    if policy.unexpected_columns != "reject":
        raise MappingRulesError("only unexpected_columns = 'reject' is supported in Phase 2")
    proposals = {x["proposal_id"]: x for x in load_proposals(proposals_path)}
    aliases = []
    for a in doc.get("aliases", []):
        prop = proposals.get(a.get("proposal_id"))
        if prop is None:
            raise MappingRulesError(f"{a.get('alias_id')}: no catalogue proposal {a.get('proposal_id')!r}")
        if prop["status"] != "approved":
            raise MappingRulesError(f"{a.get('alias_id')}: proposal {prop['proposal_id']} is {prop['status']}, not approved")
        if (prop["category"], prop["canonical_field"], prop["proposed_header"]) != \
                (a["category"], a["canonical_field"], a["alias"]):
            raise MappingRulesError(f"{a['alias_id']}: differs from its approved proposal {prop['proposal_id']}")
        lifecycle = Lifecycle.model_validate(a.get("lifecycle") or {})
        if a.get("registry_definition_sha256"):
            schema = registry.get(a["category"])
            if schema is None or definition_sha256(schema) != a["registry_definition_sha256"]:
                raise MappingRulesError(f"{a['alias_id']}: approved for a different {a['category']} registry definition")
        aliases.append(ApprovedAlias(a["alias_id"], a["category"], a["canonical_field"], a["alias"], prop["proposal_id"],
                                     prop["decision"]["decided_by"], prop["decision"]["decided_at"],
                                     int(a.get("rule_version", 1)), lifecycle.status))
    layouts = _load_header_rules(layouts_path, "layouts", LayoutRule, registry)
    file_mappings = _load_header_rules(file_mappings_path, "file_mappings", FileMappingRule, registry)
    rules = MappingRules(policy, aliases, str(rules_path), layouts, file_mappings)
    _check_collisions(rules, registry)
    return rules


def _load_header_rules(path: Path, key: str, model, registry) -> list:
    if not path.is_file():
        return []
    out = []
    for item in json.loads(path.read_text(encoding="utf-8")).get(key, []):
        try:
            rule = model.model_validate(item)
        except Exception as exc:   # strict schema: a malformed rule file is an error, never skipped silently
            raise MappingRulesError(f"{path.name}: invalid {key[:-1]} record: {exc}") from exc
        schema = registry.get(rule.category)
        if not is_controlled(schema):
            raise MappingRulesError(f"{rule.rule_id}: {rule.category} is not a controlled UC-042 CSV category")
        if definition_sha256(schema) != rule.registry_definition_sha256:
            raise MappingRulesError(f"{rule.rule_id}: approved for a different {rule.category} registry definition")
        unknown = [c.canonical_field for c in rule.columns
                   if c.canonical_field is not None and schema.field(c.canonical_field) is None]
        if unknown:
            raise MappingRulesError(f"{rule.rule_id}: fields not in {rule.category}: {unknown}")
        out.append(rule)
    ids = [(r.rule_id, r.rule_version) for r in out]
    if len(ids) != len(set(ids)):
        raise MappingRulesError(f"{path.name}: duplicate rule id/version")
    return out


def _check_collisions(rules: MappingRules, registry) -> None:
    """Under the policy, every canonical name and active alias of a category must map to exactly one field."""
    for s in registry.defined("csv"):
        if s.csv is None:
            continue
        owner: dict[str, str] = {}
        for f in s.fields:
            k = _key(f.name, rules.policy)
            if k in owner:
                raise MappingRulesError(f"{s.category}: policy makes '{f.name}' and '{owner[k]}' indistinguishable")
            owner[k] = f.name
        for a in rules.aliases_for(s.category):
            if s.field(a.canonical_field) is None:
                raise MappingRulesError(f"{a.alias_id}: {s.category} has no field '{a.canonical_field}'")
            k = _key(a.alias, rules.policy)
            if k in owner and owner[k] != a.canonical_field:
                raise MappingRulesError(f"{a.alias_id}: ambiguous alias '{a.alias}' also matches '{owner[k]}' in "
                                        f"{s.category}")
            owner[k] = a.canonical_field
    for kind, items, key in (("layouts", rules.layouts, lambda r: (r.category, r.header_fingerprint)),
                             ("file mappings", rules.file_mappings,
                              lambda r: (r.category, r.intake_id, r.source_sha256, r.header_fingerprint))):
        seen: dict = {}
        for r in items:
            if r.lifecycle.status != "active":
                continue
            if key(r) in seen:
                raise MappingRulesError(f"two active {kind} for the same key: {seen[key(r)]} and {r.rule_id}")
            seen[key(r)] = r.rule_id


@dataclass
class ControlledMapping:
    category: str
    accepted: bool
    mappings: list[dict]
    variations: list[str]
    rejections: list[str]
    unexpected_columns: list[str]
    duplicate_fields: dict[str, list[str]]
    ambiguous_columns: list[str]
    missing_fields: list[str]
    ignored_columns: list[dict] = field(default_factory=list)   # Phase 3B-7 governed exclusions

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def controlled_map(raw_headers: list[str], schema: SchemaDefinition, rules: MappingRules) -> ControlledMapping:
    pol = rules.policy
    canon = {f.name: pos for pos, f in enumerate(schema.fields)}
    targets: dict[str, list[tuple[str, str, str | None]]] = {}
    for f in schema.fields:
        targets.setdefault(_key(f.name, pol), []).append((f.name, "canonical", None))
    versions = {}
    for a in rules.aliases_for(schema.category):
        targets.setdefault(_key(a.alias, pol), []).append((a.canonical_field, "alias", a.alias_id))
        versions[a.alias_id] = a.rule_version

    # Phase 3B-2: an approved layout / file mapping applies only to the EXACT header list it was approved for.
    header_rules = rules.header_rules_for(schema.category, raw_headers)
    rule_rejections = []
    if len(header_rules) > 1:
        rule_rejections.append(f"several approved rules match this exact header list: "
                               f"{[r.rule_id for r in header_rules]}")
        header_rules = []
    override = {}
    if header_rules:
        r = header_rules[0]
        kind_name = "layout" if isinstance(r, LayoutRule) else "file_mapping"
        override = {c.source_index: (c.canonical_field, kind_name, r.rule_id, c.disposition, c.ignore_reason)
                    for c in r.columns}
        versions[r.rule_id] = r.rule_version

    mappings, unexpected, ambiguous, claims, ignored = [], [], [], {}, []
    variations = set()
    for pos, h in enumerate(raw_headers):
        found = targets.get(_key(h, pol), [])
        fields = {f for f, _, _ in found}
        approved_by = None
        if pos in override:
            o_field, o_kind, o_id, o_disp, o_reason = override[pos]
            if o_disp == "IGNORE":
                # governed reviewer exclusion (Phase 3B-7): not mapped, not unexpected, recorded with its reason
                ignored.append({"source_position": pos, "source_header": h, "rule_id": o_id,
                                "rule_version": versions.get(o_id), "reason": o_reason})
                continue
            if found and len(fields) == 1 and o_field not in fields:
                ambiguous.append(h)
                rule_rejections.append(f"approved rule {o_id} maps {h!r} to {o_field!r} but the deterministic rules "
                                       f"map it to {sorted(fields)[0]!r}")
                continue
            if not found:
                if o_field is None:
                    unexpected.append(h)          # left unmapped by the reviewer: still unexpected under the policy
                    continue
                found, fields = [(o_field, o_kind, o_id)], {o_field}
            elif len(fields) == 1 and o_field in fields:
                # Fix8 D3: the deterministic match agrees with the approved rule for this exact header list; the
                # approved rule is what governs the column (a person decided it), so it is attributed to that rule.
                # The deterministic variant (exact / case / whitespace / alias) is kept as the match detail.
                approved_by = (o_kind, o_id)
        if not found:
            unexpected.append(h)
            continue
        if len(fields) > 1:
            ambiguous.append(h)
            continue
        fld, kind, alias_id = found[0]
        if kind in ("layout", "file_mapping"):
            how = kind
        elif kind == "alias":
            how = "alias"
        elif h == fld:
            how = "exact"
        elif h.strip() == fld:
            how = "whitespace"
        elif h.strip() != h:
            how = "case+whitespace"
        else:
            how = "case"
        if how != "exact":
            variations.add(how)
        claims.setdefault(fld, []).append(h)
        rule_id = alias_id if kind in ("alias", "layout", "file_mapping") else None
        entry = {"source_header": h, "source_position": pos, "canonical_field": fld,
                 "canonical_position": canon[fld], "match": how,
                 "alias_id": alias_id if kind == "alias" else None,
                 "rule_id": rule_id, "rule_version": versions.get(rule_id) if rule_id else None}
        if approved_by is not None:
            entry.update(approved_by=approved_by[0], rule_id=approved_by[1], rule_version=versions.get(approved_by[1]))
        mappings.append(entry)
    duplicates = {f: hs for f, hs in claims.items() if len(hs) > 1}
    missing = [f.name for f in schema.fields if f.name not in claims]
    reordered = [m["canonical_position"] for m in mappings] != sorted(m["canonical_position"] for m in mappings)
    if reordered:
        variations.add("reordered")
    rej = list(rule_rejections)
    if unexpected:
        rej.append(f"unexpected column(s) {unexpected} (policy: reject; the columns are reported, not dropped)")
    if ambiguous:
        rej.append(f"ambiguous column(s) {ambiguous}")
    if duplicates:
        rej.append(f"several columns map to the same field: {duplicates}")
    if missing:
        rej.append(f"missing required column(s) {missing}")
    if reordered and not pol.allow_reorder:
        rej.append("columns are reordered and the policy does not allow it")
    return ControlledMapping(schema.category, not rej, sorted(mappings, key=lambda m: m["source_position"]),
                             sorted(variations), rej, unexpected, duplicates, ambiguous, missing, ignored)


_METHOD = {"exact": MatchMethod.EXACT, "alias": MatchMethod.ALIAS, "whitespace": MatchMethod.POLICY_NORMALISED,
           "case": MatchMethod.POLICY_NORMALISED, "case+whitespace": MatchMethod.POLICY_NORMALISED,
           "layout": MatchMethod.APPROVED_LAYOUT, "file_mapping": MatchMethod.APPROVED_FILE_MAPPING}


def to_mapping_result(mappings: list[dict], schema: SchemaDefinition, trimmed_headers: list[str],
                      ignored: list[dict] | None = None) -> MappingResult:
    """The pipeline's MappingResult for an accepted controlled mapping (`ControlledMapping.mappings`; columns addressed
    by the reader's trimmed header names, which is how records and the validator refer to them)."""
    res = MappingResult(status=MappingStatus.COMPLETE, category=schema.category, schema_version=schema.schema_version,
                        schema_verification=schema.verification_status.value,
                        layout_fingerprint=layout_fingerprint(trimmed_headers))
    keys = column_keys(trimmed_headers)      # position-unique record keys (duplicate names never collide)
    res.ignored_columns = [dict(x, record_key=keys[x["source_position"]]) for x in (ignored or [])]
    for m in mappings:
        res.mappings.append(ColumnMapping(
            source_column=keys[m["source_position"]], source_index=m["source_position"],
            canonical_field=m["canonical_field"], method=_METHOD[m.get("approved_by") or m["match"]],
            variation=m["match"],
            original_header=m["source_header"], alias_id=m["alias_id"], rule_id=m.get("rule_id"),
            rule_version=m.get("rule_version")))
    return res
