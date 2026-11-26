"""The review snapshot: exactly which inputs a preview, a closing summary and a final pack are built from. Its hash is
what a human GENERATE decision must carry (spec 06 §6.2), so the reviewer always decided on what is generated."""
import hashlib
from pathlib import Path

from ..investigation import config as inv_config
from ..pack.model import canonical
from .model import ASSEMBLER_VERSION, SNAPSHOT_VERSION, AnalystReview, Selection
from .sources import FinalPackInputError, list_investigations, load_bundle, load_pack


class ReviewSnapshot:
    """Verified inputs for one deterministic pack: the pack, the per-exception selections and the loaded artefacts of the
    selected investigations. `content` is canonical and hashed as `sha256`.

    analyst_reviews is None when the caller supplied no analyst reviews (the Phase 1 library behaviour, unchanged);
    otherwise it maps each selected investigation to the analyst's active ACCEPT / REJECT decision, and only ACCEPTED
    investigations contribute AI content."""

    def __init__(self, pack, selections, bundles, attempts, content, packs_root=None, analyst_reviews=None):
        self.pack, self.selections, self.bundles, self.attempts, self.content = pack, selections, bundles, attempts, content
        self.packs_root = packs_root  # where the pack was verified; validation re-verifies it there
        self.analyst_reviews = analyst_reviews
        self.sha256 = hashlib.sha256(canonical(content).encode("utf-8")).hexdigest()

    @property
    def pack_id(self):
        return self.pack["metadata"]["pack_id"]

    @property
    def reviewed(self):
        """True when the snapshot was built with the analyst's investigation reviews (final-pack schema 1.1)."""
        return self.analyst_reviews is not None

    def accepted(self, selection):
        """Whether an INCLUDED selection's AI content belongs in the report: always without analyst reviews (Phase 1),
        only on an ACCEPT decision with them."""
        if selection.inclusion != "INCLUDED":
            return False
        return not self.reviewed or self.analyst_reviews[selection.investigation_id].decision == "ACCEPT"

    @property
    def accepted_ids(self):
        return [s.investigation_id for s in self.selections if self.accepted(s)]


def _reviews(analyst_reviews):
    if analyst_reviews is None:
        return None
    items = analyst_reviews.values() if isinstance(analyst_reviews, dict) else analyst_reviews
    out = {}
    for r in items:
        r = r if isinstance(r, AnalystReview) else AnalystReview.model_validate(r)
        out[r.investigation_id] = r
    return out


def build_review_snapshot(pack_id, selections, packs_root=None, investigations_root=None, analyst_reviews=None):
    """Verify the pack and every selected investigation, and fix the inputs. Raises FinalPackInputError with all problems.

    analyst_reviews: the analyst's active decision per investigation (AnalystReview or dict; a mapping or a list). When
    given, every INCLUDED investigation needs one: a pending (unreviewed) investigation is never treated as accepted, and
    a decision must refer to the exact findings the artefact holds. The decisions are part of the snapshot content, so a
    changed decision changes the snapshot hash (a preview built before it is stale)."""
    pack = load_pack(pack_id, packs_root)
    reviews = _reviews(analyst_reviews)
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
                if reviews is not None:
                    r = reviews.get(s.investigation_id)
                    if r is None:
                        problems.append(f"{eid}: investigation {s.investigation_id} is pending analyst review (ACCEPT or REJECT "
                                        "it in the Exception Workspace); a pending investigation is never treated as accepted")
                    elif r.exception_id != eid:
                        problems.append(f"{eid}: the analyst review {r.analyst_review_id} belongs to {r.exception_id}")
                    elif r.findings_sha256 != b["findings_sha256"]:
                        problems.append(f"{eid}: the analyst review {r.analyst_review_id} was recorded on different findings "
                                        f"than {s.investigation_id} now holds; review it again")
                    else:
                        row["analyst_review"] = r.model_dump()
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
    if reviews is not None:  # only then: a snapshot without analyst reviews keeps its exact Phase 1 content and hash
        content["analyst_reviews"] = True
        reviews = {s.investigation_id: reviews[s.investigation_id] for s in by_exc.values() if s.inclusion == "INCLUDED"}
    return ReviewSnapshot(pack, [by_exc[e] for e in exc_ids], bundles, attempts, content, packs_root, reviews)
