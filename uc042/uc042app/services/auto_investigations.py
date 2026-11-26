"""Automatic AI investigation of a pack's exceptions, under ONE recorded authorisation (operation AUTO_INVESTIGATION).

Trigger:
  * MANDATORY for every reconciliation run (processing or reassessment; policy MANDATORY_AUTO_INVESTIGATION): there is no
    opt-in. The processing confirmation discloses it, and the run-level authorisation is recorded when the run is started
    (authorize_run; pack_id empty: the pack does not exist yet). When the run has produced, verified and registered its
    pack, every exception of THAT pack is enqueued (MonthlyService calls after_run). Without a usable provider the refusal
    is recorded and the run shows NOT_STARTED with the configuration problem; or
  * explicitly, for an existing (e.g. historical) pack ("Investigate all exceptions"), or to retry the failed ones
    ("Retry failed investigations"), each with its own recorded authorisation.

Nothing here calls a model or duplicates the investigation engine: each exception is queued through
InvestigationService.enqueue_authorized, i.e. the existing job, LangGraph graph, eight read-only tools,
validation, write-once persistence and publication registry. Jobs run in the runner's bounded AI lane.

Every exception gets a recorded outcome (QUEUED, ALREADY_ACTIVE, ALREADY_INVESTIGATED, PREVIOUS_ATTEMPT_FAILED, ...): one
activity event per enqueue lists all of them, so nothing is skipped silently. Idempotent: an exception with an active job
or a usable investigation is not queued again, and a failed attempt is re-queued only by the explicit retry (a request the
provider refused, e.g. one exceeding its token limit, is never retried automatically). Exceptions are never resolved."""
from .. import ids
from ..clock import now_iso
from ..errors import Conflict, InvalidInput, NotFound, ServiceUnavailable
from .ai_authorization import AUTHORIZED, AUTO_INVESTIGATION
from .monthly import SUBMISSION_ID_RE

QUEUED, IN_PROGRESS, READY, ACCEPTED, REJECTED, FAILED, NOT_USABLE, NOT_INVESTIGATED = (
    "QUEUED", "IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED", "REJECTED", "FAILED", "NOT_USABLE", "NOT_INVESTIGATED")
LABELS = {QUEUED: "Queued", IN_PROGRESS: "Investigation in progress", READY: "Findings ready for review",
          ACCEPTED: "Accepted by analyst", REJECTED: "Rejected by analyst", FAILED: "Investigation failed — reason available",
          NOT_USABLE: "Investigation not usable", NOT_INVESTIGATED: "Not investigated"}
AUTO_TRIGGERS = ("AUTO_RUN", "AUTO_PACK", "AUTO_RETRY")
POLICY = "MANDATORY_AUTO_INVESTIGATION"  # every pack produced by a reconciliation run is investigated, exception by exception


class AutoInvestigationService:
    def __init__(self, settings, packs, investigations, ai_authorizations, runner, activity=None):
        self.settings, self.packs, self.investigations = settings, packs, investigations
        self.auth, self.runner, self.activity = ai_authorizations, runner, activity
        self.monthly = None  # set by Services: submission runs (independent ZIP submissions)

    # ---------------------------------------------------------------- authorisation (recorded before anything runs)
    def authorize(self, confirmation, period_id, pack_id="", scope="PACK", **details):
        """Check and record one AUTO_INVESTIGATION authorisation. Refusals (not confirmed, configuration changed since the
        dialog, provider not configured) are recorded and raised. Returns the authorisation record."""
        auth = self.auth
        config, changed = auth.require(AUTO_INVESTIGATION, confirmation)
        context = dict(details, scope=scope, period_id=period_id)
        if changed:
            auth.changed(AUTO_INVESTIGATION, changed, pack_id, config, **context)
        try:  # the same provider check as a single investigation (InvestigationService._investigator)
            investigator = self.investigations._investigator()
        except (ServiceUnavailable, InvalidInput) as e:
            auth.refuse(AUTO_INVESTIGATION, e, pack_id, config, **context)
        return auth.record(AUTO_INVESTIGATION, AUTHORIZED, pack_id, config, authorization_id=ids.new_id("AIA"),
                           provider=getattr(investigator, "provider", None), model=getattr(investigator, "model", None), **context)

    def authorize_run(self, disclosure, period_id, run_id, **details):
        """MANDATORY automatic investigation of the pack a reconciliation run will produce (application AI usage policy
        MANDATORY_AUTO_INVESTIGATION). There is no opt-in: the analyst's processing confirmation, which discloses that every
        resulting exception is investigated by the configured provider (OpenAI; no fallback) and that live calls may incur charges,
        is the run-level authorisation, recorded here BEFORE the run is created. No separate per-investigation step.

        disclosure: what the processing confirmation showed ({provider, model}); if the
        configuration changed since, the processing request is refused (and the refusal recorded) so the analyst sees the
        new configuration first.

        Returns the run's auto_investigation record. Without a usable provider the run still processes (the deterministic
        result never depends on AI), but the refusal is recorded and the run carries status NOT_STARTED with the exact
        configuration problem: investigations are never silently skipped and never reported as done."""
        auth = self.auth
        config = auth.configuration()
        context = dict(details, scope="RUN", period_id=period_id, processing_run_id=run_id, policy=POLICY,
                       basis="PROCESSING_CONFIRMATION", disclosure_shown=bool(disclosure))
        if disclosure:
            _, changed = auth.require(AUTO_INVESTIGATION, dict(disclosure, confirmed=True))
            if changed:
                auth.changed(AUTO_INVESTIGATION, changed, "", config, **context)
        base = {"policy": POLICY, "provider": config.get("provider") or "", "model": config.get("model") or ""}
        try:
            investigator = self.investigations._investigator()
        except (ServiceUnavailable, InvalidInput) as e:
            reason = getattr(e, "detail", str(e))[:300]
            problem = config.get("configuration_problem") or reason
            rec = auth.record(AUTO_INVESTIGATION, f"REFUSED_{getattr(e, 'code', 'ERROR')}"[:48], "", config, reason=reason, **context)
            return dict(base, authorization_id=rec["authorization_id"], authorized_at=rec["authorized_at"], authorized_by=rec["authorized_by"],
                        status="NOT_STARTED", error=f"AI investigations cannot run: {problem}", configuration_problem=problem)
        rec = auth.record(AUTO_INVESTIGATION, AUTHORIZED, "", config, authorization_id=ids.new_id("AIA"),
                          provider=getattr(investigator, "provider", None), model=getattr(investigator, "model", None), **context)
        return dict(base, authorization_id=rec["authorization_id"], authorized_at=rec["authorized_at"], authorized_by=rec["authorized_by"],
                    provider=rec["provider"], model=rec["model"], status="AUTHORIZED")

    # ---------------------------------------------------------------- status of one exception / one pack
    def exception_status(self, pack_id, exception_id, pack=None):
        row = self.investigations.for_exception(pack_id, exception_id, pack if pack is not None else self.packs.load(pack_id))
        jobs = sorted((j for j in self.runner.repo.list(pack_id=pack_id, exception_id=exception_id) if j["operation"] == "INVESTIGATION"),
                      key=lambda j: j["submitted_at"])
        latest = jobs[-1] if jobs else None
        usable = [p for p in row["published"] if p["eligible"]]
        decisions = [(p.get("analyst_review") or {}).get("decision") for p in usable]
        if row["active_jobs"]:
            state = QUEUED if row["active_jobs"][0]["status"] == "QUEUED" else IN_PROGRESS
        elif "ACCEPT" in decisions:
            state = ACCEPTED
        elif "REJECT" in decisions and None not in decisions:
            state = REJECTED
        elif usable:
            state = READY
        elif latest and latest["status"] in ("FAILED", "INTERRUPTED"):
            state = FAILED
        elif row["published"]:
            state = NOT_USABLE
        else:
            state = NOT_INVESTIGATED
        return {"exception_id": exception_id, "state": state, "label": LABELS[state],
                "job": {k: latest.get(k) for k in ("job_id", "status", "submitted_at", "started_at", "completed_at", "error_summary", "retry_of")}
                       | {"trigger": (latest.get("inputs") or {}).get("trigger"), "authorization_id": (latest.get("inputs") or {}).get("authorization_id")}
                       if latest else None,
                "usable_investigations": [p["investigation_id"] for p in usable],
                "published": len(row["published"]), "failed_attempts": len(row["not_published"]),
                "exception_resolution": "UNRESOLVED"}

    def pack_status(self, pack_id, submission_id=None):
        """submission_id (optional): every exception's state in that ZIP submission only (its own jobs, investigations and
        decisions; see submission_exception_status) and only its own authorisations. Without it: unchanged."""
        if submission_id is not None:
            return self.submission_pack_status(pack_id, submission_id)
        pack = self.packs.load(pack_id)
        rows = [self.exception_status(pack_id, e, pack) for e in self.packs.exception_ids(pack)]
        counts = {s: 0 for s in LABELS}
        for r in rows:
            counts[r["state"]] += 1
        auth_ids = {r["job"]["authorization_id"] for r in rows if r["job"] and r["job"]["trigger"] in AUTO_TRIGGERS}
        period_id = pack["metadata"]["reporting_period"]["period_id"]
        authorizations = [a for a in self.auth.list(period_id=period_id)
                          if a["operation"] == AUTO_INVESTIGATION and (a["pack_id"] == pack_id or a["authorization_id"] in auth_ids)]
        return {"pack_id": pack_id, "period_id": period_id, "exceptions": rows, "counts": counts,
                "labels": LABELS, "authorizations": authorizations,
                "active": counts[QUEUED] + counts[IN_PROGRESS], "can_start": any(r["state"] == NOT_INVESTIGATED for r in rows),
                "can_retry": any(r["state"] == FAILED for r in rows)}

    # ---------------------------------------------------------------- enqueue
    def enqueue(self, pack_id, authorization_id, trigger, retry=False, run_id=None, fresh=False, execution=None):
        """Queue every applicable exception of the pack (all its exceptions: each stays OPEN / UNRESOLVED) under the recorded
        authorisation. Returns the per-exception outcomes; records them in one activity event.

        fresh=True (an independent ZIP submission, approved 17 Nov 2026): every exception is investigated again for this
        submission's audit run (execution: {submission_id, run_id, authorization_id}), whatever earlier submissions of
        identical content produced or are still running: their jobs, investigations and analyst decisions are never reused,
        and each result is stored as this execution's own artefact."""
        if trigger not in AUTO_TRIGGERS:
            raise InvalidInput("unknown trigger")
        pack = self.packs.load(pack_id)
        items = []
        for exc in self.packs.exception_ids(pack):
            st = self.exception_status(pack_id, exc, pack)
            job = st["job"]
            if fresh:  # the audit run is the execution scope: never another run's active or finished job
                try:
                    new, created = self.investigations.enqueue_authorized(pack_id, exc, authorization_id, trigger,
                                                                          execution=execution or {"authorization_id": authorization_id})
                    items.append({"exception_id": exc, "outcome": "QUEUED" if created else "ALREADY_ACTIVE", "job_id": new["job_id"]})
                except (ServiceUnavailable, InvalidInput) as e:
                    items.append({"exception_id": exc, "outcome": "NOT_QUEUED", "reason": getattr(e, "detail", str(e))[:300]})
            elif st["state"] in (QUEUED, IN_PROGRESS):
                items.append({"exception_id": exc, "outcome": "ALREADY_ACTIVE", "job_id": job and job["job_id"]})
            elif st["usable_investigations"]:
                items.append({"exception_id": exc, "outcome": "ALREADY_INVESTIGATED", "investigation_id": st["usable_investigations"][0]})
            elif st["state"] == FAILED and not retry:
                items.append({"exception_id": exc, "outcome": "PREVIOUS_ATTEMPT_FAILED", "job_id": job["job_id"],
                              "reason": "an earlier attempt failed; use Retry failed investigations"})
            elif retry and st["state"] != FAILED:
                items.append({"exception_id": exc, "outcome": "NOT_RETRIED", "reason": f"state {st['state']}"})
            else:
                try:
                    new, created = self.investigations.enqueue_authorized(pack_id, exc, authorization_id, trigger,
                                                                          retry_of=job["job_id"] if retry and job else None)
                    items.append({"exception_id": exc, "outcome": "QUEUED" if created else "ALREADY_ACTIVE", "job_id": new["job_id"]})
                except (ServiceUnavailable, InvalidInput) as e:  # recorded per exception; the others continue
                    items.append({"exception_id": exc, "outcome": "NOT_QUEUED", "reason": getattr(e, "detail", str(e))[:300]})
        summary = {o: sum(1 for i in items if i["outcome"] == o) for o in sorted({i["outcome"] for i in items})}
        if self.activity is not None:
            self.activity.append({"at": now_iso(), "actor": self.settings.analyst_id, "action": "AUTO_INVESTIGATION_ENQUEUED",
                                  "entity_type": "pack", "entity_id": pack_id,
                                  "details": {"authorization_id": authorization_id, "trigger": trigger, "run_id": run_id,
                                              "exceptions": len(items), "summary": summary, "items": items}})
        return {"pack_id": pack_id, "authorization_id": authorization_id, "trigger": trigger, "items": items, "summary": summary}

    def start_for_pack(self, pack_id, confirmation, retry=False):
        self.investigations.refuse_pack_wide(pack_id)  # a submission's pack: only that submission's own (scoped) retry
        pack = self.packs.load(pack_id)
        period_id = pack["metadata"]["reporting_period"]["period_id"]
        rec = self.authorize(confirmation, period_id, pack_id, scope="RETRY_FAILED" if retry else "PACK",
                             exceptions=len(self.packs.exception_ids(pack)))
        return self.enqueue(pack_id, rec["authorization_id"], "AUTO_RETRY" if retry else "AUTO_PACK", retry=retry)

    def after_run(self, run, pack_id):
        """Called by MonthlyService once an authorised run's pack is persisted, verified and registered."""
        auto = (run.get("result") or {}).get("auto_investigation") or {}
        if not auto.get("authorization_id") or auto.get("status") != "AUTHORIZED" or not pack_id:
            return None
        result = run.get("result") or {}
        if result.get("purpose") == "SUBMISSION":  # independent submission: this audit run is the execution scope
            execution = {"submission_id": result.get("submission_id"), "run_id": run["run_id"], "authorization_id": auto["authorization_id"]}
            return self.enqueue(pack_id, auto["authorization_id"], "AUTO_RUN", run_id=run["run_id"], fresh=True, execution=execution)
        return self.enqueue(pack_id, auto["authorization_id"], "AUTO_RUN", run_id=run["run_id"])

    def own_jobs(self, run):
        """Every investigation job of one submission's audit run, oldest first: matched by the run in the job's execution
        context (inputs.execution.run_id: the run's own jobs and every submission-scoped retry), or, for jobs queued before
        execution contexts existed, by the run's original authorisation. Never another submission's jobs."""
        result = (run or {}).get("result") or {}
        pack_id, run_id = result.get("pack_id"), (run or {}).get("run_id")
        auth = (result.get("auto_investigation") or {}).get("authorization_id")
        if not pack_id or not run_id:
            return []
        out = []
        for j in self.investigations.runner.repo.list(pack_id=pack_id):
            inputs = j.get("inputs") or {}
            if j["operation"] == "INVESTIGATION" and ((inputs.get("execution") or {}).get("run_id") == run_id
                                                     or (auth and inputs.get("authorization_id") == auth)):
                out.append(j)
        return out

    def submission_jobs(self, run):
        """{exception_id: the submission's latest investigation job} (any status; a retry supersedes the failed attempt)."""
        return {j["exception_id"]: j for j in self.own_jobs(run)}

    def submission_investigations(self, run):
        """{exception_id: investigation_id} produced FOR one submission's audit run (its latest completed job per exception,
        retries included); never another submission's, even for an identical pack."""
        out = {}
        for j in self.own_jobs(run):
            inv = (j.get("result") or {}).get("investigation_id")
            if j["status"] == "COMPLETED" and inv:
                out[j["exception_id"]] = inv  # oldest first: the latest completed job per exception wins
        return out

    def submission_exception_status(self, run, exception_id, active_decisions, eligible):
        """One exception's AI status in ONE submission, from that submission's own jobs, investigations and decisions only
        (same shape as exception_status; never the pack-wide state of other submissions or the legacy scope).
        active_decisions: the submission's active decisions {investigation_id: view}; eligible: {investigation_id: bool}."""
        jobs = self.submission_jobs(run)
        produced = self.submission_investigations(run)
        latest = jobs.get(exception_id)
        inv = produced.get(exception_id)
        usable = [inv] if inv and eligible.get(inv) else []
        decision = (active_decisions.get(inv) or {}).get("decision") if inv else None
        if latest and latest["status"] in ("QUEUED", "RUNNING"):
            state = QUEUED if latest["status"] == "QUEUED" else IN_PROGRESS
        elif usable and decision == "ACCEPT":
            state = ACCEPTED
        elif usable and decision == "REJECT":
            state = REJECTED
        elif usable:
            state = READY
        elif latest and latest["status"] in ("FAILED", "INTERRUPTED"):
            state = FAILED
        elif inv or (latest and latest["status"] == "COMPLETED"):
            state = NOT_USABLE
        else:
            state = NOT_INVESTIGATED
        return {"exception_id": exception_id, "state": state, "label": LABELS[state],
                "job": {k: latest.get(k) for k in ("job_id", "status", "submitted_at", "started_at", "completed_at", "error_summary", "retry_of")}
                       | {"trigger": (latest.get("inputs") or {}).get("trigger"), "authorization_id": (latest.get("inputs") or {}).get("authorization_id")}
                       if latest else None,
                "usable_investigations": usable, "exception_resolution": "UNRESOLVED", "submission_id": (run.get("result") or {}).get("submission_id")}

    def submission_scope(self, submission_id, pack_id=None):
        """One ZIP submission's own execution scope, for read-only submission-scoped views: its audit run, the IDs of its own
        investigation jobs (the run's jobs and every submission-scoped retry), the artefacts they produced (published IDs and
        not-published record names) and {exception_id: investigation_id} of its latest completed job per exception.
        Refuses an invalid ID (422 INVALID_ID), an unknown submission (404) and, with pack_id, a pack the submission's
        audit run did not produce (409 SUBMISSION_PACK_MISMATCH)."""
        if not isinstance(submission_id, str) or not SUBMISSION_ID_RE.match(submission_id):
            raise InvalidInput("invalid submission id", code="INVALID_ID")
        run = self.monthly.submission_run(submission_id) if self.monthly is not None else None
        if run is None:
            raise NotFound("submission not found")
        result = run.get("result") or {}
        if pack_id is not None and (run["status"] != "SUCCEEDED" or result.get("pack_id") != pack_id):
            raise Conflict("this submission's audit run has not produced this pack", code="SUBMISSION_PACK_MISMATCH",
                           extra={"run_status": run["status"], "pack_id": result.get("pack_id")})
        jobs = self.own_jobs(run)
        produced = {}
        published, not_published = set(), set()
        for j in jobs:  # oldest first: the latest completed job per exception wins
            res = j.get("result") or {}
            if res.get("investigation_id"):
                published.add(res["investigation_id"])
                if j["status"] == "COMPLETED":
                    produced[j["exception_id"]] = res["investigation_id"]
            if res.get("not_published_record"):
                not_published.add(res["not_published_record"])
        return {"submission_id": submission_id, "run": run, "job_ids": {j["job_id"] for j in jobs},
                "authorization_ids": {(j.get("inputs") or {}).get("authorization_id") for j in jobs} - {None},
                "published": published, "not_published": not_published, "produced": produced}

    def submission_pack_status(self, pack_id, submission_id):
        """pack_status for ONE submission (same shape plus submission_id and run_id). can_start is always False (a
        submission's pack is never investigated pack-wide); can_retry: the submission-scoped retry has something to do."""
        scope = self.submission_scope(submission_id, pack_id)
        run = scope["run"]
        pack = self.packs.load(pack_id)
        reviews = self.investigations.analyst_reviews
        active = reviews.active_for_pack(pack_id, submission_id) if reviews is not None else {}
        rows = []
        for e in self.packs.exception_ids(pack):
            eligible = {r["investigation_id"]: r["eligible"] for r in self.investigations.published(pack, e)["published"]}
            rows.append(self.submission_exception_status(run, e, active, eligible))
        counts = {s: 0 for s in LABELS}
        for r in rows:
            counts[r["state"]] += 1
        auth_ids = set(scope["authorization_ids"])
        own = ((run.get("result") or {}).get("auto_investigation") or {}).get("authorization_id")
        if own:
            auth_ids.add(own)
        period_id = pack["metadata"]["reporting_period"]["period_id"]
        authorizations = [a for a in self.auth.list(period_id=period_id)
                          if a["operation"] == AUTO_INVESTIGATION and a["authorization_id"] in auth_ids]
        return {"pack_id": pack_id, "period_id": period_id, "submission_id": submission_id, "run_id": run["run_id"],
                "exceptions": rows, "counts": counts, "labels": LABELS, "authorizations": authorizations,
                "active": counts[QUEUED] + counts[IN_PROGRESS], "can_start": False,
                "can_retry": any(r["state"] in (FAILED, NOT_INVESTIGATED) for r in rows)}

    def submission_artefacts(self, run):
        """Every artefact the submission's own executions produced: published investigation IDs and the names of their
        not-published attempt records (to keep other submissions' attempts out of this submission's review)."""
        published, not_published = set(), set()
        for j in self.own_jobs(run):
            res = j.get("result") or {}
            if res.get("investigation_id"):
                published.add(res["investigation_id"])
            if res.get("not_published_record"):
                not_published.add(res["not_published_record"])
        return {"published": published, "not_published": not_published}

    def retry_submission(self, submission_id, confirmation, exception_ids=None):
        """Re-run, WITHIN its own submission, every exception of a submission's audit run that has no completed
        investigation for that submission: failed, interrupted or never-enqueued (a crash before the run's jobs were
        queued). A new authorisation is recorded first; each new job carries the submission's execution context
        (submission_id, run_id, the new authorisation) and links the attempt it retries. Never a pack-wide investigation."""
        run = self.monthly.submission_run(submission_id) if self.monthly is not None else None
        if run is None:
            raise NotFound("submission not found")
        result = run.get("result") or {}
        pack_id = result.get("pack_id")
        if run["status"] != "SUCCEEDED" or not pack_id:
            raise Conflict("the submission's audit run has not produced a pack", code="SUBMISSION_NOT_AUDITED",
                           extra={"run_status": run["status"]})
        pack = self.packs.load(pack_id)
        all_ids = self.packs.exception_ids(pack)
        targets = list(exception_ids) if exception_ids else all_ids
        unknown = [e for e in targets if e not in all_ids]
        if unknown:
            raise InvalidInput(f"not exceptions of this submission's pack: {unknown}", code="UNKNOWN_EXCEPTION")
        produced, jobs = self.submission_investigations(run), self.submission_jobs(run)
        todo = [e for e in targets if e not in produced and not (jobs.get(e) and jobs[e]["status"] in ("QUEUED", "RUNNING"))]
        if not todo:
            raise Conflict("every selected exception already has a completed or active investigation for this submission",
                           code="NOTHING_TO_RETRY")
        rec = self.authorize(confirmation, run["period_id"], pack_id, scope="SUBMISSION_RETRY", submission_id=submission_id,
                             run_id=run["run_id"], exceptions=len(todo))
        execution = {"submission_id": submission_id, "run_id": run["run_id"], "authorization_id": rec["authorization_id"]}
        items = []
        for exc in targets:
            if exc in produced:
                items.append({"exception_id": exc, "outcome": "ALREADY_INVESTIGATED", "investigation_id": produced[exc]})
            elif exc not in todo:
                items.append({"exception_id": exc, "outcome": "ALREADY_ACTIVE", "job_id": jobs[exc]["job_id"]})
            else:
                try:
                    new, _ = self.investigations.enqueue_authorized(pack_id, exc, rec["authorization_id"], "AUTO_RETRY",
                                                                    retry_of=(jobs.get(exc) or {}).get("job_id"), execution=execution)
                    items.append({"exception_id": exc, "outcome": "QUEUED", "job_id": new["job_id"]})
                except (ServiceUnavailable, InvalidInput) as e:
                    items.append({"exception_id": exc, "outcome": "NOT_QUEUED", "reason": getattr(e, "detail", str(e))[:300]})
        summary = {o: sum(1 for i in items if i["outcome"] == o) for o in sorted({i["outcome"] for i in items})}
        if self.activity is not None:
            self.activity.append({"at": now_iso(), "actor": self.settings.analyst_id, "action": "SUBMISSION_INVESTIGATIONS_RETRIED",
                                  "entity_type": "run", "entity_id": run["run_id"],
                                  "details": {"submission_id": submission_id, "authorization_id": rec["authorization_id"],
                                              "summary": summary, "items": items}})
        return {"pack_id": pack_id, "submission_id": submission_id, "run_id": run["run_id"],
                "authorization_id": rec["authorization_id"], "trigger": "AUTO_RETRY", "items": items, "summary": summary}
