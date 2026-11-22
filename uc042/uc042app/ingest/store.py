"""Controlled file storage for uploaded source documents (UC042_DOCUMENT_STORE). The database holds metadata and a
storage reference; the bytes live here.

    objects/<sha[:2]>/<sha256>      uploaded originals, content-addressed and write-once. Two uploads with the same content
                                    share one object; a file with the same NAME but different content is a different
                                    object, so nothing is ever overwritten because a filename matches.
    cases/<run_id>/                 processing case folders (prepared by uc042lib.prepare for one processing run)

Storage references:
    object:<sha256>                 an uploaded original in objects/
    dataset:<dataset>/<rel path>    a POC scenario document registered in place (uc042_dataset/, read-only; only
                                    source_data/*.csv and supporting_documents/*.pdf are ever referenced)
Every read re-checks the SHA-256 recorded in the database."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

from ..storage import _replace

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATASET_REF_RE = re.compile(r"^dataset:([A-Za-z0-9_.-]+)/(source_data/[A-Za-z0-9_.-]+\.csv|supporting_documents/[A-Za-z0-9_.-]+\.pdf)$")


class StoreError(Exception):
    """A stored document is missing, unreadable or no longer matches its recorded SHA-256."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


class DocumentStore:
    def __init__(self, root, datasets_root):
        self.root = Path(root)
        self.datasets_root = Path(datasets_root)

    @property
    def cases_root(self):
        return self.root / "cases"

    def _object(self, sha):
        if not SHA_RE.match(sha):
            raise StoreError("invalid object reference")
        return self.root / "objects" / sha[:2] / sha

    def put(self, data):
        """Store bytes write-once; returns (storage_ref, sha256). An existing object with this hash is verified, not rewritten."""
        sha = sha256_bytes(data)
        path = self._object(sha)
        if path.exists():
            if sha256_bytes(path.read_bytes()) != sha:
                raise StoreError(f"stored object {sha[:12]}… no longer matches its hash")
            return f"object:{sha}", sha
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():  # a concurrent identical upload won the race; same content by construction
                Path(tmp).unlink()
            else:
                _replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return f"object:{sha}", sha

    def path(self, storage_ref):
        """Resolve a storage reference to a file path (never outside the store or the dataset folder)."""
        if storage_ref.startswith("object:"):
            return self._object(storage_ref[len("object:"):])
        m = DATASET_REF_RE.match(storage_ref)
        if m:
            path = (self.datasets_root / m.group(1) / m.group(2)).resolve()
            if self.datasets_root.resolve() not in path.parents:
                raise StoreError("invalid dataset reference")
            return path
        raise StoreError("unsupported storage reference")

    def read(self, storage_ref, expected_sha):
        path = self.path(storage_ref)
        try:
            data = path.read_bytes()
        except OSError:
            raise StoreError("the stored document is missing") from None
        if sha256_bytes(data) != expected_sha:
            raise StoreError("the stored document no longer matches its recorded SHA-256")
        return data
