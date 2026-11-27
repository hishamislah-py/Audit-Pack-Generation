"""Phase 3B-2 - a writable governed rule store (one directory holding the four rule files).

    approved_aliases.json   active-alias rules (Phase 2 format + optional governance/lifecycle fields)
    alias_proposals.json    the alias catalogue (proposed / approved / rejected)
    approved_layouts.json   source-system layouts (LayoutRule)
    file_mappings.json      one-upload mappings (FileMappingRule)

The packaged production rules directory (`mapping/rules/`) is NEVER written at runtime: a store must be created in a
separate directory (`RuleStore.initialise`). Entries are never deleted; lifecycle changes only set status metadata.
Every write is validated by re-loading the whole store against the registry; an invalid write is rolled back.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .controlled import RULES_DIR, MappingRules, MappingRulesError, load_rules
from .governed import FileMappingRule, LayoutRule, Lifecycle

FILES = {"aliases": "approved_aliases.json", "proposals": "alias_proposals.json",
         "layouts": "approved_layouts.json", "file_mappings": "file_mappings.json"}
LIST_KEY = {"aliases": "aliases", "proposals": "proposals", "layouts": "layouts", "file_mappings": "file_mappings"}


class RuleStoreError(ValueError):
    pass


class RuleStore:
    def __init__(self, root: str | Path, registry):
        self.root = Path(root).resolve()
        if self.root == RULES_DIR.resolve():
            raise RuleStoreError("the packaged production rules directory is never written at runtime")
        missing = [n for n in FILES.values() if not (self.root / n).is_file()]
        if missing:
            raise RuleStoreError(f"{self.root} is not a rule store (missing {missing}); use RuleStore.initialise")
        self.registry = registry

    @classmethod
    def initialise(cls, root: str | Path, registry, source_dir: str | Path = RULES_DIR) -> "RuleStore":
        root, source_dir = Path(root).resolve(), Path(source_dir)
        if root == RULES_DIR.resolve():
            raise RuleStoreError("the packaged production rules directory is never written at runtime")
        if root.exists() and any(root.iterdir()):
            raise RuleStoreError(f"{root} is not empty")
        root.mkdir(parents=True, exist_ok=True)
        for kind in ("aliases", "proposals", "layouts"):
            src = source_dir / FILES[kind]
            if src.is_file():
                shutil.copyfile(src, root / FILES[kind])
            else:
                (root / FILES[kind]).write_text(json.dumps({LIST_KEY[kind]: []}, indent=2) + "\n", encoding="utf-8")
        (root / FILES["file_mappings"]).write_text(json.dumps(
            {"file_mappings": [], "note": "one-upload mappings; never reused for another intake"}, indent=2) + "\n",
            encoding="utf-8")
        store = cls(root, registry)
        store.load()
        return store

    # ------------------------------------------------------------------ io
    def path(self, kind: str) -> Path:
        return self.root / FILES[kind]

    def read(self, kind: str) -> dict:
        return json.loads(self.path(kind).read_text(encoding="utf-8"))

    def load(self) -> MappingRules:
        return load_rules(self.registry, self.path("aliases"), self.path("proposals"), self.path("layouts"),
                          self.path("file_mappings"))

    def _write_validated(self, changes: dict[str, dict]) -> MappingRules:
        backups = {k: self.path(k).read_bytes() for k in changes}
        try:
            for k, doc in changes.items():
                tmp = self.path(k).with_suffix(".tmp")
                tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp.replace(self.path(k))
            return self.load()
        except (MappingRulesError, ValueError) as exc:
            for k, data in backups.items():
                self.path(k).write_bytes(data)
            raise RuleStoreError(f"rejected rule change: {exc}") from exc

    # ------------------------------------------------------------------ additions
    def add_layout(self, rule: LayoutRule) -> MappingRules:
        doc = self.read("layouts")
        doc["layouts"].append(json.loads(rule.model_dump_json()))
        return self._write_validated({"layouts": doc})

    def add_file_mapping(self, rule: FileMappingRule) -> MappingRules:
        doc = self.read("file_mappings")
        doc["file_mappings"].append(json.loads(rule.model_dump_json()))
        return self._write_validated({"file_mappings": doc})

    def add_alias(self, proposal: dict, alias: dict) -> MappingRules:
        props, aliases = self.read("proposals"), self.read("aliases")
        existing = {p["proposal_id"]: i for i, p in enumerate(props["proposals"])}
        if proposal["proposal_id"] in existing:
            props["proposals"][existing[proposal["proposal_id"]]] = proposal
        else:
            props["proposals"].append(proposal)
        aliases["aliases"].append(alias)
        return self._write_validated({"proposals": props, "aliases": aliases})

    # ------------------------------------------------------------------ lifecycle
    def find(self, kind: str, rule_id: str) -> list[dict]:
        key = {"aliases": "alias_id", "layouts": "layout_id", "file_mappings": "file_mapping_id"}[kind]
        return [x for x in self.read(kind)[LIST_KEY[kind]] if x.get(key) == rule_id]

    def set_lifecycle(self, kind: str, rule_id: str, rule_version: int, lifecycle: Lifecycle) -> MappingRules:
        """Change ONLY the lifecycle of one active rule version (active -> revoked / superseded)."""
        key = {"aliases": "alias_id", "layouts": "layout_id", "file_mappings": "file_mapping_id"}[kind]
        doc = self.read(kind)
        hits = [x for x in doc[LIST_KEY[kind]] if x.get(key) == rule_id and int(x.get("rule_version", 1)) == rule_version]
        if len(hits) != 1:
            raise RuleStoreError(f"{kind} {rule_id} v{rule_version} not found")
        current = Lifecycle.model_validate(hits[0].get("lifecycle") or {})
        if current.status != "active":
            raise RuleStoreError(f"{rule_id} v{rule_version} is {current.status}; only an active rule can change")
        hits[0]["lifecycle"] = json.loads(lifecycle.model_dump_json())
        return self._write_validated({kind: doc})
