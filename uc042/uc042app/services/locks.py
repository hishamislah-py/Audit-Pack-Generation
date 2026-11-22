"""Per-pack serialisation. In-process only: correct for the single backend process enforced by the instance lock
(storage.InstanceLock). It gives no protection across processes or machines; Phase 5 replaces it with database locks."""
import threading
from contextlib import contextmanager

from ..errors import Conflict


class PackLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}

    def _lock(self, pack_id):
        with self._guard:
            return self._locks.setdefault(pack_id, threading.Lock())

    @contextmanager
    def hold(self, pack_id, timeout=30, busy_code="PACK_BUSY"):
        """Serialise writes for one deterministic pack. Waits up to `timeout` seconds (0: fail immediately)."""
        lock = self._lock(pack_id)
        acquired = lock.acquire(timeout=timeout) if timeout else lock.acquire(blocking=False)
        if not acquired:
            raise Conflict("another operation on this pack is in progress; try again", code=busy_code)
        try:
            yield
        finally:
            lock.release()
