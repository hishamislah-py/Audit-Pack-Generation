"""Phase 3B-9 - file-based package store (same pattern as EvidenceStore / RuleStore; single-user POC, no locking).

    <root>/packages/<package_id>/package.json                      current package state (atomic replace, revision)
    <root>/packages/<package_id>/snapshots/<snapshot_id>.json      IMMUTABLE (exclusive create; never rewritten)
    <root>/packages/<package_id>/manifests/<snapshot_id>.manifest.json   IMMUTABLE reconciliation-ready manifest
    <root>/packages/<package_id>/cases/<case_id>.json              column-review case snapshot (resumable after restart)
    <root>/packages/<package_id>/sessions/<session_id>.json        proposal review session (+ .request.json)
    <root>/previews/<intake_id>/...                                canonical previews + provenance sidecars

Original uploaded bytes are NOT kept here: they stay in the content-addressed EvidenceStore (never overwritten); a file
version references them by intake ID + SHA-256.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..mapping.proposals import ProposalRequest
from ..review.intake import ColumnReviewCase
from ..review.session import ReviewSession
from .models import EvidencePackage, PackageSnapshot


class PackageStoreError(ValueError):
    pass


def _retry_sharing(fn, attempts: int = 60, delay: float = 0.05):
    """Windows refuses to replace (or open) a file another thread is reading / replacing at that instant: a transient
    sharing violation (PermissionError). Retry briefly; any other error, or a persistent one, propagates unchanged."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def _read_text(p: Path) -> str:
    return _retry_sharing(lambda: p.read_text(encoding="utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _retry_sharing(lambda: tmp.replace(path))


def _create_once(path: Path, text: str) -> None:
    """Exclusive create: an immutable record can be written exactly once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise PackageStoreError(f"{path.name} already exists and is immutable") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


class PackageStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        (self.root / "packages").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ packages
    def _dir(self, package_id: str) -> Path:
        if not package_id or any(c in package_id for c in "/\\.:"):
            raise PackageStoreError(f"invalid package id {package_id!r}")
        return self.root / "packages" / package_id

    def create(self, pkg: EvidencePackage) -> None:
        _create_once(self._dir(pkg.package_id) / "package.json", pkg.model_dump_json(indent=1))

    def load(self, package_id: str) -> EvidencePackage:
        p = self._dir(package_id) / "package.json"
        if not p.is_file():
            raise PackageStoreError(f"unknown package {package_id}")
        return EvidencePackage.model_validate_json(_read_text(p))

    def save(self, pkg: EvidencePackage) -> EvidencePackage:
        """Write the next revision; refuses a stale copy (protects against a lost update / repeated operation)."""
        on_disk = self.load(pkg.package_id)
        if on_disk.revision != pkg.revision:
            raise PackageStoreError(f"package {pkg.package_id} changed (revision {on_disk.revision}, "
                                    f"this copy {pkg.revision}); reload and retry")
        pkg.revision += 1
        _atomic_write(self._dir(pkg.package_id) / "package.json", pkg.model_dump_json(indent=1))
        return pkg

    def list(self) -> list[str]:
        return sorted(p.parent.name for p in (self.root / "packages").glob("*/package.json"))

    # ------------------------------------------------------------------ immutable snapshot + manifest
    def snapshot_path(self, package_id: str, snapshot_id: str) -> Path:
        return self._dir(package_id) / "snapshots" / f"{snapshot_id}.json"

    def manifest_path(self, package_id: str, snapshot_id: str) -> Path:
        return self._dir(package_id) / "manifests" / f"{snapshot_id}.manifest.json"

    def write_snapshot(self, snap: PackageSnapshot) -> Path:
        p = self.snapshot_path(snap.package_id, snap.snapshot_id)
        _create_once(p, snap.model_dump_json(indent=1))
        return p

    def load_snapshot(self, package_id: str, snapshot_id: str) -> PackageSnapshot:
        p = self.snapshot_path(package_id, snapshot_id)
        if not p.is_file():
            raise PackageStoreError(f"unknown snapshot {snapshot_id}")
        return PackageSnapshot.model_validate_json(_read_text(p))

    def write_manifest(self, package_id: str, snapshot_id: str, doc: dict) -> Path:
        p = self.manifest_path(package_id, snapshot_id)
        _create_once(p, json.dumps(doc, indent=1, ensure_ascii=False))
        return p

    # ------------------------------------------------------------------ review state (resumable)
    def save_case(self, package_id: str, case: ColumnReviewCase) -> None:
        _atomic_write(self._dir(package_id) / "cases" / f"{case.case_id}.json", case.model_dump_json(indent=1))

    def load_case(self, package_id: str, case_id: str) -> ColumnReviewCase:
        p = self._dir(package_id) / "cases" / f"{case_id}.json"
        if not p.is_file():
            raise PackageStoreError(f"unknown review case {case_id}")
        return ColumnReviewCase.model_validate_json(_read_text(p))

    def save_session(self, package_id: str, session: ReviewSession, request: ProposalRequest | None = None) -> None:
        d = self._dir(package_id) / "sessions"
        _atomic_write(d / f"{session.session_id}.json", session.model_dump_json(indent=1))
        if request is not None:
            _atomic_write(d / f"{session.session_id}.request.json", request.model_dump_json(indent=1))

    def load_session(self, package_id: str, session_id: str) -> tuple[ReviewSession, ProposalRequest]:
        d = self._dir(package_id) / "sessions"
        if not (d / f"{session_id}.json").is_file():
            raise PackageStoreError(f"unknown review session {session_id}")
        return (ReviewSession.model_validate_json(_read_text(d / f"{session_id}.json")),
                ProposalRequest.model_validate_json(_read_text(d / f"{session_id}.request.json")))

    def rel(self, path: Path | None) -> str | None:
        return None if path is None else Path(path).resolve().relative_to(self.root).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root / rel
