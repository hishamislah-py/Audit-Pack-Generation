"""Case ownership and authorisation (Fix8 D7, interface I-2). Enforced by api.py BEFORE any case / closure / review /
upload mutation is delegated to CaseService / ClosureService / PackageService; the frontend only mirrors it.

Model (who can do what):

* **Signed-in analyst** - may read everything (queue, every case, activity, runs, closure views, packs: reads stay open
  to signed-in analysts so colleagues can follow and review work); may register a case (it is assigned to them);
  may act on a case ONLY when ``case.assigned_to`` is their username (the case *owner*); may claim an unassigned case.
* **Supervisor** - an auth-file user whose ``roles`` contain ``"supervisor"``. May act on any case. Every action on a
  case they do not own is recorded as ``SUPERVISOR_OVERRIDE`` (attempted action, case, owner, outcome) right after
  the action. May reassign a case (claim endpoint with ``assigned_to``).
* **Refusal** - a restricted action by a non-owner, non-supervisor is refused with HTTP 403 ``NOT_CASE_OWNER`` and an
  ``ACCESS_DENIED`` audit event (actor, attempted action, case, owner); nothing is delegated, so nothing changes.
* **System work** - job threads, closure auto pack / investigations, listeners never pass through api.py and are not
  subject to ownership (they run as the analyst who started them or as the system actor, see identity.py).
* **--insecure-no-auth** - there is no signed-in user: the server reviewer acts (``authenticated=False``) and
  ownership is NOT enforced (test harnesses only).
"""
from __future__ import annotations

from . import identity
from .cases import CaseError

NOT_CASE_OWNER = "NOT_CASE_OWNER"


def enforced(a: identity.Actor | None = None) -> bool:
    a = a if a is not None else identity.current()
    return bool(a is not None and a.authenticated and not a.system)


def case_access(c: dict) -> dict:
    """The current actor's access to case `c` (for views; the frontend disables restricted actions with `reason`)."""
    a = identity.current()
    owner = c.get("assigned_to")
    if not enforced(a):
        return {"enforced": False, "owner": owner, "viewer": a.user if a else None, "is_owner": None,
                "supervisor": False, "can_act": True, "override": False, "reason": None, "can_claim": False,
                "can_reassign": False}
    is_owner = owner is not None and owner == a.user
    sup = a.supervisor
    can_act = is_owner or sup
    reason = None if can_act else (
        f"Assigned to {owner}: only the case owner or a supervisor can change this case ({NOT_CASE_OWNER})" if owner
        else f"This case is unassigned: claim it before acting on it ({NOT_CASE_OWNER})")
    return {"enforced": True, "owner": owner, "viewer": a.user, "is_owner": is_owner, "supervisor": sup,
            "can_act": can_act, "override": bool(sup and not is_owner), "reason": reason,
            "can_claim": owner is None or (sup and not is_owner), "can_reassign": sup}


def _pid(c: dict) -> str | None:
    return c["runs"][-1]["package_id"] if c.get("runs") else None


def deny(ctx, c: dict | None, action: str, reason: str, code: str = NOT_CASE_OWNER, **extra) -> CaseError:
    """Record ACCESS_DENIED and return the 403 to raise. No state is changed."""
    a = identity.current()
    ctx.log.append("ACCESS_DENIED", actor_id=a.user if a else None, actor_role=a.role if a else None,
                   details={"case_ref": (c or {}).get("case_ref"), "package_id": _pid(c) if c else None,
                            "attempted_action": action, "assigned_to": (c or {}).get("assigned_to"),
                            "code": code, "reason": reason, **extra})
    return CaseError(403, code, reason)


def authorize(ctx, c: dict, action: str) -> bool:
    """Raise 403 NOT_CASE_OWNER (audited) unless the actor may perform `action` on case `c`.
    Returns True when the action is allowed only as a supervisor override (to be audited by `audit_override`)."""
    if not enforced():
        return False
    acc = case_access(c)
    if acc["is_owner"]:
        return False
    if acc["supervisor"]:
        return True
    raise deny(ctx, c, action, acc["reason"])


def audit_override(ctx, c: dict, action: str, outcome: str, error: str | None = None) -> None:
    a = identity.current()
    ctx.log.append("SUPERVISOR_OVERRIDE", actor_id=a.user, actor_role=a.role,
                   details={"case_ref": c.get("case_ref"), "package_id": _pid(c), "attempted_action": action,
                            "assigned_to": c.get("assigned_to"), "outcome": outcome,
                            **({"error": error} if error else {})})


def guarded(ctx, c: dict, action: str, fn, to_code=None):
    """Authorise, then run `fn`. A supervisor override is audited after the action with its outcome."""
    override = authorize(ctx, c, action)
    if not override:
        return fn()
    try:
        out = fn()
    except Exception as exc:
        audit_override(ctx, c, action, "FAILED", (to_code(exc) if to_code else type(exc).__name__))
        raise
    audit_override(ctx, c, action, "COMPLETED")
    return out


def restrict_actions(doc, reason: str):
    """Disable every backend action ({enabled, reason}) in a view for a viewer who may not act (reads stay open)."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "actions" and isinstance(v, dict):
                for x in v.values():
                    if isinstance(x, dict) and "enabled" in x:
                        x["enabled"], x["reason"] = False, reason
            else:
                restrict_actions(v, reason)
    elif isinstance(doc, list):
        for v in doc:
            restrict_actions(v, reason)
    return doc
