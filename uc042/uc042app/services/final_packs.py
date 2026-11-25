"""Final audit packs: generation records (one per GENERATE decision), publication through the existing library
(assemble_final_pack -> publish_final_pack -> verify_final_pack), start-up recovery and read access to the published files.
Nothing here assembles or renders a report itself.

Versions are numbered over a reassessment LINEAGE (audit.pack_lineage): a deterministic pack produced by reassessing a
reporting period continues the version sequence of the pack it reassesses, so its first final pack supersedes the
period's previous final pack. A pack without a lineage row (every independent demonstration scenario, every pack before
reassessment existed) is its own lineage: its versions are exactly the per-pack versions as before."""
import hashlib
import json
import logging
import shutil
from pathlib import Path

from uc042lib.final_pack import assemble_final_pack, list_final_packs, publish_final_pack, verify_final_pack
from uc042lib.final_pack.model import GenerationInfo

from .. import ids
from ..errors import IntegrityFailure, NotFound
from ..jobs import safe_error
from ..clock import now_iso

log = logging.getLogger("uc042app.final_packs")
FILES = {"json": ("final_pack.json", "application/json"), "html": ("report.html", "text/html; charset=utf-8"),
         "pdf": ("report.pdf", "application/pdf"), "manifest": ("manifest.json", "application/json")}


class FinalPackService:
    def __init__(self, settings, records, packs=None, lineage=None):
        # One final-packs root per storage root set: a final pack is published next to its source pack's set and read
        # from wherever it is (final pack IDs are unique; a duplicate across roots is an integrity failure).
        self.root, self.records, self.packs, self.lineage = Path(settings.final_packs_root), records, packs, lineage

    def roots(self):
        return self.packs.layout.final_pack_roots() if self.packs is not None else [self.root]

    def root_for(self, pack_id):
        return Path(self.packs.root_set(pack_id).final_packs_root) if self.packs is not None else self.root

    def _published(self, pack_id=None):
        return [m for root in self.roots() if root.is_dir() for m in list_final_packs(root, pack_id)]

    # ---------------------------------------------------------------- lineage and versions
    def lineage_root(self, pack_id):
        row = self.lineage.get(pack_id) if self.lineage is not None else None
        return row["lineage_root_pack_id"] if row else pack_id

    def lineage_packs(self, pack_id):
        """Every deterministic pack of the pack's reassessment lineage, the root first."""
        root = self.lineage_root(pack_id)
        rows = self.lineage.list(lineage_root_pack_id=root) if self.lineage is not None else []
        return [root] + [r["pack_id"] for r in rows if r["pack_id"] != root]

    def lineage_final_packs(self, pack_id):
        """Published final packs of the pack's lineage (all storage roots), oldest version first."""
        members = set(self.lineage_packs(pack_id))
        found = [m for m in self._published() if m["generation_record"]["source_pack_id"] in members]
        return sorted(found, key=lambda m: m["generation_record"]["version"])

    def next_version(self, pack_id):
        """(version, supersedes_final_pack_id) of the next final pack over the pack's lineage."""
        existing = self.lineage_final_packs(pack_id)
        if not existing:
            return 1, None
        return existing[-1]["generation_record"]["version"] + 1, existing[-1]["final_pack_id"]

    # ---------------------------------------------------------------- generation (called by the review service under the pack lock)
    def generate(self, snapshot, summary, review):
        """Record GENERATING, assemble, publish and verify. Returns the GENERATED record; on any failure the record is
        GENERATION_FAILED and the exception propagates (nothing partial is published: the library stages and renames)."""
        pack_id = snapshot.pack_id
        root = self.root_for(pack_id)
        version, supersedes = self.next_version(pack_id)
        record = self.records.create({"review_decision_id": review.review_decision_id, "review_id": review.review_session_id,
                                      "pack_id": pack_id, "status": "GENERATING", "version": version,
                                      "supersedes_final_pack_id": supersedes, "created_at": now_iso(), "created_by": review.reviewer.user_id,
                                      "final_pack_id": None, "final_content_sha256": None, "error_summary": ""})
        try:
            final = assemble_final_pack(snapshot, summary, review, GenerationInfo(version=version, supersedes_final_pack_id=supersedes))
            path = publish_final_pack(final, root, expected=(version, supersedes))
            problems = verify_final_pack(path)
            if problems:
                raise IntegrityFailure("the published final pack does not verify: " + "; ".join(problems))
        except Exception as e:
            log.exception("generation for decision %s failed", review.review_decision_id)
            self.records.update(review.review_decision_id, {"status": "GENERATION_FAILED", "error_summary": safe_error(e),
                                                            "completed_at": now_iso()})
            raise
        record = self.records.update(review.review_decision_id, {"status": "GENERATED", "final_pack_id": final["metadata"]["final_pack_id"],
                                                                 "final_content_sha256": final["final_content_sha256"],
                                                                 "completed_at": now_iso()})
        return record

    def recover(self):
        """Start-up: reconcile GENERATING records with storage (spec 06 §12) and remove abandoned staging folders."""
        published = {m["generation_record"]["review_decision_id"]: m for m in self._published()}
        out = []
        for r in self.records.list():
            if r["status"] != "GENERATING":
                continue
            m = published.get(r["review_decision_id"])
            if m is not None and not verify_final_pack(m["path"]):
                r = self.records.update(r["review_decision_id"], {"status": "GENERATED", "final_pack_id": m["final_pack_id"],
                                                                  "final_content_sha256": m["final_content_sha256"],
                                                                  "completed_at": now_iso(), "recovered": True})
            else:
                r = self.records.update(r["review_decision_id"], {"status": "GENERATION_FAILED", "completed_at": now_iso(),
                                                                  "error_summary": "the backend stopped during generation; "
                                                                                   "nothing was published", "recovered": True})
            out.append(r)
        for root in self.roots():
            for staging in root.glob(".tmp-*") if root.is_dir() else []:
                if staging.is_dir():
                    shutil.rmtree(staging, ignore_errors=True)
        return out

    # ---------------------------------------------------------------- reads
    def list(self, pack_id=None, lineage=False):
        """Published final packs: all, one deterministic pack's, or (lineage=True) every version of the pack's lineage."""
        if pack_id is not None:
            ids.check("pack_id", pack_id)
        out = []
        for m in (self.lineage_final_packs(pack_id) if lineage and pack_id else self._published(pack_id)):
            g = m["generation_record"]
            out.append({"final_pack_id": m["final_pack_id"], "pack_id": g["source_pack_id"], "version": g["version"],
                        "supersedes_final_pack_id": g["supersedes_final_pack_id"], "generated_at": g["generated_at"],
                        "review_decision_id": g["review_decision_id"], "final_content_sha256": m["final_content_sha256"]})
        return out

    def _dir(self, final_pack_id):
        ids.check("final_pack_id", final_pack_id)
        found = [root / final_pack_id for root in self.roots() if (root / final_pack_id / "manifest.json").is_file()]
        if not found:
            raise NotFound("final pack not found")
        if len(found) > 1:
            raise IntegrityFailure("the final pack exists in more than one storage root", code="DUPLICATE_FINAL_PACK")
        return found[0]

    def detail(self, final_pack_id):
        d = self._dir(final_pack_id)
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        final = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
        m = final["metadata"]
        return {"final_pack_id": final_pack_id, "status": m["status"], "version": m["version"],
                "supersedes_final_pack_id": m["supersedes_final_pack_id"], "generated_at": m["generated_at"],
                "source_pack": m["source_pack"], "final_content_sha256": final["final_content_sha256"],
                "human_review": {k: final["human_review"].get(k) for k in ("review_decision_id", "decision", "reviewer", "decided_at",
                                                                           "comment", "acknowledgement_accepted")},
                "files": {k: dict(manifest["files"][name], name=name) for k, (name, _) in FILES.items() if name in manifest["files"]},
                "record": self.records.get(final["human_review"]["review_decision_id"])}

    def verify(self, final_pack_id):
        problems = verify_final_pack(self._dir(final_pack_id))
        return {"final_pack_id": final_pack_id, "verified": not problems, "problems": problems}

    def file(self, final_pack_id, kind):
        """(bytes, media_type, sha256). The file is checked against the manifest before it is served."""
        d = self._dir(final_pack_id)
        name, media = FILES[kind]
        data = (d / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if kind != "manifest":
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            if manifest["files"][name]["sha256"] != digest:
                raise IntegrityFailure(f"{name} does not match its manifest SHA-256", code="FINAL_PACK_INTEGRITY_FAILED")
        return data, media, digest
