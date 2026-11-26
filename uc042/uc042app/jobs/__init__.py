"""Background jobs: a ThreadPoolExecutor in the single backend process, with every state change persisted
(QUEUED -> RUNNING -> COMPLETED | FAILED, or INTERRUPTED). Long AI calls (investigations, closing summaries) run here,
never on the event loop. The client polls GET /jobs/{job_id}.

Restart: the executor does not survive a restart, so persisted QUEUED/RUNNING jobs are marked INTERRUPTED at start-up.
They are never re-run automatically (no repeated OpenAI calls); the analyst starts a new job, and the investigation
layer's write-once persistence means a retry can never overwrite an earlier artefact.
"""
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from uc042lib.investigation.llm import redact

from .. import ids
from ..clock import now_iso

log = logging.getLogger("uc042app.jobs")
ACTIVE = ("QUEUED", "RUNNING")
_PATHLIKE = re.compile(r"([A-Za-z]:)?([\\/][\w.~-]+){2,}[\\/]?")  # file-system paths (two or more separators)


def safe_error(e):
    """An error summary for the client: exception class and a redacted, path-free, truncated message."""
    return f"{e.__class__.__name__}: {_PATHLIKE.sub('<path>', redact(str(e)))[:400]}"


class JobRunner:
    """Two lanes: the general pool (processing, previews, generation) and a separate, bounded lane for AI investigations
    (UC042_AI_JOB_WORKERS, default 1), so a queue of investigations never blocks processing and the provider's rate and
    token limits are respected. A job waiting in the AI lane stays QUEUED until it really starts."""

    def __init__(self, repo, workers=2, ai_workers=1):
        self.repo, self.workers, self.ai_workers = repo, workers, ai_workers
        self._executor = None
        self._ai_executor = None
        self._futures = {}
        self._lock = threading.Lock()

    def recover(self):
        """Mark jobs left QUEUED or RUNNING by a previous process as INTERRUPTED. Returns their IDs."""
        out = []
        for job in self.repo.list(statuses=ACTIVE):
            self.repo.update(job["job_id"], {"status": "INTERRUPTED", "completed_at": now_iso(),
                                             "error_summary": f"the backend restarted while this job was {job['status']}; it was "
                                                              "not re-run automatically. Start a new job to retry."})
            out.append(job["job_id"])
        return out

    def start(self):
        self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="uc042-job")
        self._ai_executor = ThreadPoolExecutor(max_workers=self.ai_workers, thread_name_prefix="uc042-ai")

    def shutdown(self, wait=True):
        for name in ("_executor", "_ai_executor"):
            ex = getattr(self, name)
            if ex is not None:
                ex.shutdown(wait=wait, cancel_futures=True)
                setattr(self, name, None)
        for job in self.repo.list(statuses=("QUEUED",)):  # cancelled before running
            self.repo.update(job["job_id"], {"status": "INTERRUPTED", "completed_at": now_iso(),
                                             "error_summary": "the backend stopped before this job started"})

    def create(self, operation, pack_id, submitted_by, exception_id=None, inputs=None, retry_of=None):
        job = {"job_id": ids.new_id("JOB"), "operation": operation, "pack_id": pack_id, "exception_id": exception_id,
               "inputs": inputs or {}, "status": "QUEUED", "submitted_at": now_iso(), "started_at": "", "completed_at": "",
               "submitted_by": submitted_by, "retry_of": retry_of, "error_summary": "", "result": None}
        return self.repo.create(job)

    def submit(self, job, fn, lane="general"):
        """Run fn(job) in the pool (lane "ai": the bounded AI lane). fn returns (status, result, error_summary) with status
        COMPLETED or FAILED."""
        executor = self._ai_executor if lane == "ai" else self._executor
        if executor is None:
            raise RuntimeError("the job runner is not started")
        with self._lock:
            self._futures[job["job_id"]] = executor.submit(self._run, job["job_id"], fn)
        return job

    def _run(self, job_id, fn):
        job = self.repo.update(job_id, {"status": "RUNNING", "started_at": now_iso()})
        try:
            status, result, error = fn(job)
        except Exception as e:  # isolated: one job's failure never affects others
            log.exception("job %s (%s) failed", job_id, job["operation"])
            status, result, error = "FAILED", None, safe_error(e)
        self.repo.update(job_id, {"status": status, "result": result, "error_summary": error or "", "completed_at": now_iso()})

    def wait(self, job_id, timeout=60):
        """Block until a submitted job finishes (tests and scripts only)."""
        future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.repo.get(job_id)

    def active(self, pack_id, exception_id=None, operation=None):
        return [j for j in self.repo.list(pack_id=pack_id, exception_id=exception_id, statuses=ACTIVE)
                if operation is None or j["operation"] == operation]
