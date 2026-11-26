"""Application services and their wiring. `Services` owns the repositories, the instance lock and the job runner."""
import logging
import os
import tempfile
from pathlib import Path

from uc042lib.investigation.llm import investigator_from_env

from ..config import ConfigurationError
from ..jobs import JobRunner
from ..repositories import FileRepositories
from ..storage import InstanceLock
from .ai_authorization import AiAuthorizationService
from .cases import CaseService
from .final_packs import FinalPackService
from .investigation_reviews import InvestigationReviewService
from .auto_investigations import AutoInvestigationService
from .investigations import InvestigationService
from .layout import StorageLayout
from .locks import PackLocks
from .monthly import MonthlyService
from .packages import PackageService
from .packs import PackService
from .registry import PublicationRegistry
from .reviews import ReviewService

log = logging.getLogger("uc042app")


def database_repositories(url):
    """SQL repositories over UC042_DATABASE_URL. PostgreSQL must already be migrated (db-upgrade); a SQLite URL (tests
    only) gets its tables created from the models. Returns (repositories, engine)."""
    from ..db import check_schema, create_all_for_tests, make_engine, make_sessions
    from ..db.repositories import SqlRepositories
    engine = make_engine(url)
    try:
        if engine.dialect.name == "sqlite":
            create_all_for_tests(engine)
        else:
            check_schema(engine)
    except BaseException:
        engine.dispose()
        raise
    return SqlRepositories(make_sessions(engine)), engine


class Services:
    def __init__(self, settings, investigator_factory=None, repositories=None):
        self.settings = settings
        Path(settings.state_dir).mkdir(parents=True, exist_ok=True)
        self.engine = None
        if repositories is None and settings.database_url:
            repositories, self.engine = database_repositories(settings.database_url)
        self.repos = repositories or FileRepositories(settings.state_dir)
        factory = investigator_factory or investigator_from_env
        self.locks = PackLocks()
        # One database, several storage profiles: the primary roots plus every profile the database records on a period.
        profiles = set(settings.storage_profiles)
        if self.repos.periods is not None:
            profiles |= set(self.repos.periods.storage_profiles())
        self.layout = StorageLayout.from_settings(settings, profiles)
        self._check_layout()
        self.packs = PackService(self.layout)
        self.registry = PublicationRegistry(self.repos.registry)
        self.runner = JobRunner(self.repos.jobs, settings.job_workers, settings.ai_job_workers)
        self.ai_authorizations = AiAuthorizationService(settings, self.repos.ai_authorizations, self.repos.activity)
        self.investigations = InvestigationService(settings, self.packs, self.registry, self.runner, self.locks, factory,
                                                   self.repos.authorizations, self.ai_authorizations)
        self.investigation_reviews = InvestigationReviewService(settings, self.repos.investigation_reviews, self.packs,
                                                                self.investigations, self.runner, self.locks, self.repos.activity)
        self.investigations.analyst_reviews = self.investigation_reviews  # each published row shows its active decision
        self.final_packs = FinalPackService(settings, self.repos.final_packs, self.packs, self.repos.lineage)
        self.reviews = ReviewService(settings, self.repos, self.packs, self.investigations, self.final_packs, self.runner, self.locks,
                                     factory, self.ai_authorizations, self.investigation_reviews)
        self.auto_investigations = AutoInvestigationService(settings, self.packs, self.investigations, self.ai_authorizations,
                                                            self.runner, self.repos.activity)
        self.monthly = MonthlyService(settings, self.repos, self.packs, self.runner, self.final_packs)
        self.monthly.auto_investigations = self.auto_investigations  # mandatory enqueue after every processing run
        self.reviews.auto_investigations = self.auto_investigations  # per-exception status in the readiness checklist
        # Independent ZIP submissions (17 Nov 2026): a submission's review and analyst decisions see only the investigations
        # produced for that submission's own audit run.
        self.reviews.monthly = self.monthly
        self.investigation_reviews.submission_resolver = self.submission_investigations
        # ZIP-only operation (consolidated remediation): a submission's retries and a submission-only pack's guards
        self.auto_investigations.monthly = self.monthly
        self.investigations.submission_pack_check = self.monthly.is_submission_only_pack if self.repos.runs is not None else None
        # Phase B: submission-scoped investigation views, decisions locked once a submission's final pack is generated, and
        # the package / submission listing (read-only, except the package display name)
        self.investigations.submission_scope = self.auto_investigations.submission_scope
        self.investigation_reviews.locked_sessions = self.reviews.locked_sessions
        self.packages = PackageService(self.monthly, self.auto_investigations, self.investigation_reviews, self.reviews, self.final_packs)
        self.cases = CaseService(settings, self.repos, self.packs, self.investigations)
        self._instance = InstanceLock(settings.state_dir)
        self.started = False

    def submission_investigations(self, submission_id):
        """{exception_id: investigation_id} produced for one ZIP submission's audit run, or None when the submission is
        unknown (or the database repositories that hold submissions are not configured)."""
        if self.repos.runs is None:
            return None
        run = self.monthly.submission_run(submission_id)
        return None if run is None else self.auto_investigations.submission_investigations(run)

    def _check_layout(self):
        """Application state and uploaded documents must stay outside every served storage root (as for the primary)."""
        for label, own in (("application state", self.settings.state_dir), ("document store", self.settings.document_store)):
            if own is None:
                continue
            own = Path(own).resolve()
            for s in self.layout.sets[1:]:
                for root in (s.packs_root, s.datasets_root, s.investigations_root, s.final_packs_root):
                    root = Path(root).resolve()
                    if own == root or root in own.parents or own in root.parents:
                        raise ConfigurationError(f"the {label} directory must be separate from the {s.name} storage roots")

    def start(self):
        """Take the single-process lock, recover interrupted work, then start the job runner."""
        self._instance.acquire()
        try:
            interrupted = self.runner.recover()
            recovered = self.final_packs.recover()
            self.reviews.recover()
            self.monthly.recover()
            self.monthly.sync_packs()
            self.runner.start()
        except BaseException:
            self._instance.release()
            raise
        self.started = True
        if interrupted or recovered:
            log.warning("start-up recovery: %d job(s) interrupted, %d generation record(s) reconciled", len(interrupted), len(recovered))
        return self

    def stop(self):
        if self.started:
            self.runner.shutdown(wait=True)
            self._instance.release()
            self.started = False
        if self.engine is not None:
            self.engine.dispose()

    @property
    def database(self):
        """True when application state and the monthly document-management records are in the database."""
        return self.repos.periods is not None

    def database_ok(self):
        try:
            from sqlalchemy import text
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def storage_ok(self):
        try:
            fd, tmp = tempfile.mkstemp(prefix=".health-", dir=self.settings.state_dir)
            os.close(fd)
            os.unlink(tmp)
            return True
        except OSError:
            return False
