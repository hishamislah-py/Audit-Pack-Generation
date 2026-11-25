"""The review snapshot: exactly which inputs a preview, a closing summary and a final pack are built from. Its hash is
what a human GENERATE decision must carry (spec 06 §6.2), so the reviewer always decided on what is generated."""
import hashlib
from pathlib import Path

from ..investigation import config as inv_config
from ..pack.model import canonical
from .model import ASSEMBLER_VERSION, SNAPSHOT_VERSION, Selection
from .sources import FinalPackInputError, list_investigations, load_bundle, load_pack


class ReviewSnapshot:
    """Verified inputs for one deterministic pack: the pack, the per-exception selections and the loaded artefacts of the
    selected investigations. `content` is canonical and hashed as `sha256`."""

    def __init__(self, pack, selections, bundles, attempts, content, packs_root=None):
        self.pack, self.selections, self.bundles, self.attempts, self.content = pack, selections, bundles, attempts, content
        self.packs_root = packs_root  # where the pack was verified; validation re-verifies it there
        self.sha256 = hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()

    @property
    def pack_id(self):
        return self.pack["metadata"]["pack_id"]


def build_review_snapshot(pack_id, selections, packs_root=None, investigations_root=None):
    """Verify the pack and every selected investigation, and fix the inputs. Raises FinalPackInputError with all problems."""
    pack = load_pack(pack_id, packs_root)
    selections = [s if isinstance(s, Selection) else Selection.model_validate(s) for s in selections]
    exc_ids = [x["exception_id"] for x in pack["exception_register"]["exceptions"]]
    by_exc, problems = {}, []
    for s in selections:
        if s.exception_id in by_exc:
            problems.append(f"{s.exception_id}: selected more than once")
        by_exc[s.exception_id] = s
    unknown = sorted(set(by_exc) - set(exc_ids))
    if unknown:
        problems.append(f"selections for exceptions not in the pack: {unknown}")
    missing = [e for e in exc_ids if e not in by_exc]
    if missing:
        problems.append(f"no selection for exceptions: {missing} (every exception needs an explicit selection)")
    bundles, attempts, rows = {}, {}, []
    for eid in exc_ids:
        s = by_exc.get(eid)
        if s is None:
            continue
        found = list_investigations(pack, eid, investigations_root)
        attempts[eid] = found
        eligible = {i["investigation_id"]: i for i in found["published"] if i["eligible"]}
        row = {"exception_id": eid, "inclusion": s.inclusion, "investigation_id": s.investigation_id, "reason": s.reason}
        if s.inclusion == "INCLUDED":
            info = next((i for i in found["published"] if i["investigation_id"] == s.investigation_id), None)
            if info is None:
                problems.append(f"{eid}: investigation {s.investigation_id} is not a published investigation of this exception")
            elif not info["eligible"]:
                problems.append(f"{eid}: investigation {s.investigation_id} is not eligible: {'; '.join(info['reasons'])}")
            else:
                b = load_bundle(Path(info["path"]))
                bundles[s.investigation_id] = b
                row.update(findings_sha256=b["findings_sha256"],
                           evidence_packet_sha256=b["findings"]["evidence_packet_sha256"],
                           evidence_ledger_sha256=b["findings"].get("evidence_ledger_sha256", ""))
        elif s.inclusion == "NOT_INVESTIGATED" and eligible:
            problems.append(f"{eid}: marked NOT_INVESTIGATED but eligible investigations exist ({sorted(eligible)}); "
                            "include one or use EXCLUDED_BY_ANALYST with a reason")
        rows.append(row)
    if problems:
        raise FinalPackInputError("; ".join(problems))
    content = {"snapshot_version": SNAPSHOT_VERSION, "assembler_version": ASSEMBLER_VERSION,
               "validation_rules": inv_config.FINDINGS_SCHEMA_VERSION,
               "pack": {"pack_id": pack["metadata"]["pack_id"], "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"]},
               "selections": rows}
    return ReviewSnapshot(pack, [by_exc[e] for e in exc_ids], bundles, attempts, content, packs_root)
