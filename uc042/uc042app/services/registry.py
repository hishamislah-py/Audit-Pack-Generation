"""Investigation publication registry: a separate, file-backed record of every investigation the backend accepts as
published. It closes the limitation in report 07 §9: an investigation ID is a content address, so a rewrite that also
recomputes the ID and renames the folder passes verify_published on its own. With the registry, eligibility also requires
that the files are the ones registered.

Each entry pins the SHA-256 of findings.json, evidence_packet.json and (tools mode) evidence_ledger.json, the pack
identity and the versions, at the moment of registration.

Record types:
  NEW_PUBLICATION          registered by the backend right after its own investigation job published the artefact.
  LEGACY_BASELINE_IMPORT   an artefact that existed before the registry, imported after it passed verify_published.
                           This fixes an integrity baseline FROM THE TIME OF IMPORT; it does not prove what the files
                           contained when they were originally published.

Trust limit (local POC): the registry is a plain file. A local administrator with write access to both the artefacts
and the registry can change both consistently. The registry detects inconsistent changes; it is not tamper-proof.
"""
import hashlib
import json
import threading
from pathlib import Path

from uc042lib.investigation.persistence import verify_published

from ..clock import now_iso
from ..errors import IntegrityFailure
from ..storage import StorageCorruption

NEW_PUBLICATION, LEGACY_BASELINE_IMPORT = "NEW_PUBLICATION", "LEGACY_BASELINE_IMPORT"
RECORD_TYPES = (NEW_PUBLICATION, LEGACY_BASELINE_IMPORT)
LEGACY_NOTE = ("Integrity baseline established at import time. It does not prove the contents of the artefact at its "
               "original publication time, which predates this registry.")
PINNED = ("pack_id", "pack_content_sha256", "findings_sha256", "evidence_packet_sha256", "evidence_packet_file_sha256",
          "evidence_ledger_file_sha256", "findings_schema_version", "prompt_version")


class RegistrationRefused(Exception):
    """The artefact cannot be registered (failed, simulated, unverifiable, wrong pack or registered with other hashes)."""


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else ""


def fingerprint(inv_dir):
    """Current hashes and identity of a published investigation directory (read-only)."""
    d = Path(inv_dir)
    findings = json.loads((d / "findings.json").read_text(encoding="utf-8"))
    m = findings.get("model_metadata") or {}
    return {"investigation_id": findings.get("investigation_id"), "directory_name": d.name,
            "exception_id": findings.get("exception_id"), "pack_id": findings.get("pack_id"),
            "pack_content_sha256": findings.get("pack_content_sha256"),
            "findings_schema_version": m.get("findings_schema_version", ""), "prompt_version": m.get("prompt_version", ""),
            "investigation_mode": findings.get("investigation_mode", "fixed"),
            "investigation_status": findings.get("investigation_status"), "validation_status": findings.get("validation_status"),
            "simulated": m.get("simulated", True),
            "findings_sha256": _sha_file(d / "findings.json"),
            "evidence_packet_sha256": findings.get("evidence_packet_sha256", ""),
            "evidence_packet_file_sha256": _sha_file(d / "evidence_packet.json"),
            "evidence_ledger_file_sha256": _sha_file(d / "evidence_ledger.json")}


class PublicationRegistry:
    def __init__(self, repo):
        self.repo = repo
        self._lock = threading.Lock()

    def signature(self):
        """Changes whenever the registry changes (used to invalidate cached eligibility)."""
        return self.repo.signature()

    def problems(self):
        """Problems with the registry file itself (empty: readable and well-formed)."""
        try:
            entries = self.repo.entries()
        except (StorageCorruption, KeyError, TypeError) as e:
            return [f"registry file is unreadable: {e}"]
        out = []
        for n, e in enumerate(entries, 1):
            missing = [k for k in ("investigation_id", "record_type", "recorded_at") + PINNED if k not in e]
            if missing:
                out.append(f"entry {n} lacks {missing}")
            elif e["record_type"] not in RECORD_TYPES:
                out.append(f"entry {n} has an unknown record type")
        return out

    def entries(self):
        problems = self.problems()
        if problems:  # fail closed: nothing is registry-verified while the registry is damaged
            raise IntegrityFailure("the investigation publication registry is damaged: " + "; ".join(problems[:3]),
                                   code="REGISTRY_UNREADABLE")
        return self.repo.entries()

    def entry_for(self, investigation_id):
        return next((e for e in reversed(self.entries()) if e["investigation_id"] == investigation_id), None)

    def _register(self, inv_dir, pack, record_type, recorded_by, note):
        problems = verify_published(inv_dir)
        if problems:
            raise RegistrationRefused("artefact verification failed: " + "; ".join(problems))
        fp = fingerprint(inv_dir)
        if fp["investigation_status"] != "COMPLETED" or fp["validation_status"] != "VALID":
            raise RegistrationRefused(f"not a completed, valid investigation ({fp['investigation_status']}/{fp['validation_status']})")
        if fp["simulated"] is not False:
            raise RegistrationRefused("simulated (offline) output is not AI analysis and is never registered")
        if fp["pack_id"] != pack["metadata"]["pack_id"] or fp["pack_content_sha256"] != pack["audit_trail"]["pack_content_sha256"]:
            raise RegistrationRefused("the investigation belongs to a different pack or pack content hash")
        with self._lock:
            existing = self.entry_for(fp["investigation_id"])
            if existing is not None:
                if all(existing[k] == fp[k] for k in PINNED):
                    return existing, False  # idempotent: already registered with the same files
                raise RegistrationRefused("already registered with different file hashes; the artefact may have been altered")
            entry = {"seq": len(self.entries()) + 1, "record_type": record_type,
                     **{k: fp[k] for k in ("investigation_id", "exception_id", "investigation_mode") + PINNED},
                     "recorded_at": now_iso(), "recorded_by": recorded_by, "verify_published": "OK", "note": note}
            self.repo.append(entry)
            return entry, True

    def register_new(self, inv_dir, pack, recorded_by):
        """Register an artefact the backend's own job has just published."""
        return self._register(inv_dir, pack, NEW_PUBLICATION, recorded_by, "")

    def import_legacy(self, inv_dir, pack, recorded_by):
        """Register a pre-registry artefact that verifies now (never rewrites it)."""
        return self._register(inv_dir, pack, LEGACY_BASELINE_IMPORT, recorded_by, LEGACY_NOTE)

    def check(self, inv_dir, pack):
        """Problems preventing registry verification of a published investigation (empty: registry-verified)."""
        try:
            fp = fingerprint(inv_dir)
        except (OSError, ValueError) as e:
            return [f"unreadable artefact: {e.__class__.__name__}"]
        try:
            entry = self.entry_for(fp["investigation_id"])
        except IntegrityFailure as e:
            return [e.detail]
        if entry is None:
            return ["not in the investigation publication registry (unregistered artefact)"]
        problems = []
        if fp["directory_name"] != entry["investigation_id"]:
            problems.append("directory name does not match the registered investigation ID")
        problems += [f"{k} differs from the registered value" for k in PINNED if fp[k] != entry[k]]
        if entry["pack_id"] != pack["metadata"]["pack_id"] or entry["pack_content_sha256"] != pack["audit_trail"]["pack_content_sha256"]:
            problems.append("registered for a different pack or pack content hash")
        return problems


def registry_summary(entry):
    if entry is None:
        return None
    return {k: entry[k] for k in ("seq", "record_type", "recorded_at", "findings_sha256", "evidence_packet_sha256",
                                  "findings_schema_version", "prompt_version", "note")}
