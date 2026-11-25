"""Atomic file primitives for application state and the single-process instance lock."""
import json
import os
import tempfile
import time
from pathlib import Path


class StorageCorruption(Exception):
    """A state file cannot be parsed. Never silently repaired."""


def _dumps(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _replace(src, dst, attempts=20):
    """os.replace, retried briefly on Windows sharing violations (a reader, indexer or antivirus holding the target)."""
    for n in range(attempts):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(0.025)


def atomic_write_json(path, obj):
    """Write a complete JSON file or nothing: stage in the same directory, fsync, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_dumps(obj).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def create_json(path, obj):
    """Write a new JSON file; raises FileExistsError if it already exists (never replaces)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_dumps(obj).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)  # atomic and exclusive: fails if the name is taken
        except FileExistsError:
            raise
        except OSError:  # file system without hard links: exclusive create instead
            with open(path, "xb") as f:
                f.write(_dumps(obj).encode("utf-8"))
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_json(path, default=None):
    path = Path(path)
    for n in range(20):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except PermissionError:  # Windows: the file is being replaced by another thread at this instant
            if n == 19:
                raise
            time.sleep(0.025)
        except ValueError as e:
            raise StorageCorruption(f"{path.name} cannot be parsed") from e


def append_line(path, obj):
    """Append one JSON line and fsync it. Callers serialise appends to the same file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        f.write((json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())


def read_lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise StorageCorruption(f"{path.name} line {n} cannot be parsed") from e
    return out


class InstanceLockError(Exception):
    """Another backend process already uses this application-state directory."""


class InstanceLock:
    """An OS-level exclusive lock on <state_dir>/instance.lock, held for the life of the process. The backend's locks
    are in-process, so it must run as ONE worker process per state directory; this lock enforces that by refusing to
    start a second process (or a second uvicorn worker) on the same state directory. It does not protect a state
    directory shared between machines."""

    def __init__(self, state_dir):
        self.path = Path(state_dir) / "instance.lock"
        self._f = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            raise InstanceLockError("another UC-042 backend process is already using this application-state directory "
                                    "(single-worker deployment only)") from None
        self._f = f
        return self

    def release(self):
        if self._f is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        finally:
            self._f.close()
            self._f = None
