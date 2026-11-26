"""Pre-execution authorisation of paid AI operations (an AI investigation of one exception; the AI closing summary of a
final review). Nothing here calls a model.

Every request that would start a model call must carry the analyst's explicit confirmation of the configured provider
and model. The service records that confirmation, append-only and immutable, BEFORE the job that calls the model is
submitted, and links it to the job; a refused request (provider not configured, configuration changed since the dialog
was shown, an investigation already running) is recorded with its refusal. A failed or interrupted job therefore always
has a traceable authorisation.

This is a different record from audit.investigation_authorizations (InvestigationService.authorization), which decides
whether an already-published investigation belongs to the approved published set. The two are never mixed."""
from uc042lib.investigation import config as inv_config

from .. import ids
from ..clock import now_iso
from ..errors import Conflict, InvalidInput, NotFound

INVESTIGATION, CLOSING_SUMMARY, AUTO_INVESTIGATION = "INVESTIGATION", "CLOSING_SUMMARY", "AUTO_INVESTIGATION"
AUTHORIZED = "AUTHORIZED"

STATEMENTS = {
    INVESTIGATION: ("I authorise one AI investigation of this exception by the configured model. Live API calls may incur "
                    "charges. The AI uses only the approved evidence sources of this deterministic pack. It cannot resolve "
                    "the exception, change the deterministic results or approve the audit."),
    AUTO_INVESTIGATION: ("I authorise automatic AI investigations, by the configured model, of every applicable exception in the "
                         "deterministic pack this authorisation covers (the pack produced by this reconciliation run, or the pack "
                         "named). One investigation runs per exception, in the background. Live API calls may incur charges. The "
                         "AI uses only the approved evidence sources of the pack. It cannot resolve any exception, change the "
                         "deterministic results or approve the audit."),
    CLOSING_SUMMARY: ("I authorise one AI closing-summary request for this final review by the configured model. Live API calls "
                      "may incur charges. The summary is written from the deterministic pack and the selected investigations "
                      "only. It does not resolve exceptions, approve the audit or certify compliance."),
}


def statements():
    """The statements the analyst confirms (OpenAI is the only provider; there is no automatic fallback)."""
    return dict(STATEMENTS)


def period_of(pack_id):
    """The reporting period in a pack identifier (PACK-<scenario>-PER-YYYY-MM-<hash>)."""
    parts = pack_id.split("-")
    return "-".join(parts[-4:-1]) if len(parts) >= 5 else ""


class AiAuthorizationService:
    def __init__(self, settings, repo, activity=None):
        self.settings, self.repo, self.activity = settings, repo, activity

    # ---------------------------------------------------------------- what the confirmation dialog shows
    @staticmethod
    def configuration():
        """The configured provider and model (no secrets): what an authorisation is given for."""
        try:
            s = inv_config.provider_settings()
            provider, model, effort, problem = s["provider"], s["model"], s["reasoning_effort"], None
        except ValueError as e:
            provider, model, effort, problem = "", "", None, str(e)[:200]
        key = {"openai": inv_config.ENV_OPENAI_KEY, "anthropic": getattr(inv_config, "ENV_ANTHROPIC_KEY", "ANTHROPIC_API_KEY")}
        configured = problem is None and provider in key and inv_config.api_key_configured(key[provider])
        if problem is None and not configured:  # say what is missing (the variable's name only, never a value)
            problem = (f"{key[provider]} is not set in the backend environment" if provider in key
                       else f"provider {provider!r} cannot be used for live AI operations from the application")
        return {"provider": provider, "model": model, "reasoning_effort": effort, "provider_configured": bool(configured),
                "configuration_problem": problem, "investigation_mode": "tools", "tool_limits": inv_config.tool_limits(),
                "charges_notice": "Live API calls to the configured provider may incur charges.",
                "statements": statements()}

    # ---------------------------------------------------------------- the confirmation
    def require(self, operation, confirmation):
        """The request must carry confirmed=true. A provider or model named by the client must still be the configured one
        (the dialog was not shown for a different configuration). Returns the configuration the confirmation applies to."""
        if not confirmation or confirmation.get("confirmed") is not True:
            raise InvalidInput(f"{operation.lower().replace('_', ' ')} needs the analyst's explicit authorisation "
                               "(confirmed: true) of the configured AI provider and model", code="AUTHORIZATION_REQUIRED",
                               extra={"configuration": self.configuration()})
        config = self.configuration()
        for field in ("provider", "model"):
            given = confirmation.get(field)
            if given and given != config[field]:
                return config, f"the {field} changed since it was shown ({given!r} -> {config[field]!r}); review and confirm again"
        for field in ("provider", "model"):  # there is no fallback provider: a dialog that showed one is out of date
            given = confirmation.get(f"fallback_{field}")
            if given is not None and given != "none":
                return config, (f"the fallback {field} changed since it was shown ({given!r} -> 'none'): there is no automatic "
                                "fallback provider; review and confirm again")
        return config, None

    def record(self, operation, result, pack_id, config, exception_id=None, review_id=None, case_id=None, job_id=None,
               authorization_id=None, period_id=None, **details):
        """Append one immutable authorisation record (the result is AUTHORIZED or REFUSED_<code>)."""
        rec = {"authorization_id": authorization_id or ids.new_id("AIA"), "operation": operation, "result": result,
               "period_id": period_id or period_of(pack_id), "pack_id": pack_id, "exception_id": exception_id, "review_id": review_id,
               "case_id": case_id, "job_id": job_id, "provider": details.pop("provider", None) or config.get("provider") or "",
               "model": details.pop("model", None) or config.get("model") or "", "authorized_by": self.settings.analyst_id,
               "authorized_at": now_iso(),
               "details": dict(details, statement=config.get("statements", STATEMENTS)[operation], provider_configured=config.get("provider_configured"),
                               reasoning_effort=config.get("reasoning_effort"))}
        rec = self.repo.record(rec)
        if self.activity is not None:
            self.activity.append({"at": rec["authorized_at"], "actor": rec["authorized_by"],
                                  "action": "AI_AUTHORIZED" if result == AUTHORIZED else "AI_AUTHORIZATION_REFUSED",
                                  "entity_type": "ai_authorization", "entity_id": rec["authorization_id"],
                                  "details": {"operation": operation, "result": result, "period_id": rec["period_id"],
                                              "pack_id": pack_id, "exception_id": exception_id, "review_id": review_id,
                                              "case_id": case_id, "job_id": job_id, "model": rec["model"]}})
        return rec

    def refuse(self, operation, error, pack_id, config, **context):
        """Record a refused confirmation, then raise the refusal unchanged."""
        self.record(operation, f"REFUSED_{getattr(error, 'code', 'ERROR')}"[:48], pack_id, config, reason=getattr(error, "detail", str(error))[:300],
                    **context)
        raise error

    def changed(self, operation, problem, pack_id, config, **context):
        self.refuse(operation, Conflict(problem, code="AI_CONFIGURATION_CHANGED", extra={"configuration": config}), pack_id, config,
                    **context)

    # ---------------------------------------------------------------- reads
    def list(self, **filters):
        return self.repo.list(**{k: v for k, v in filters.items() if v is not None})

    def get(self, authorization_id):
        rec = self.repo.get(ids.check("authorization_id", authorization_id))
        if rec is None:
            raise NotFound("AI authorisation not found")
        return rec
