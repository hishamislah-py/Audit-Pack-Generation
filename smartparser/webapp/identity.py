"""Per-request actor identity (Fix8 D6, interface I-1).

The acting identity is held in a context variable, set ONLY by ``api.route`` from the trusted server-side session
(never from a client-supplied field). Every audit writer reads it:

* ``CaseService._audit`` / ``PackageService._audit`` record ``actor_id`` = the signed-in user and ``actor_role`` = the
  user's access role (``analyst`` or ``supervisor``);
* ``AppContext.reviewer`` returns a per-request ``Reviewer(reviewer_id=<user>, role=<reviewer role>, kind=<server kind>)``
  while a request is active, otherwise the server reviewer fixed at start-up;
* background job threads started by an analyst action run under the actor captured when the job was created
  (``bind``); work that has no initiating actor runs as the system actor (``actor_role="system"``,
  ``actor_id=SYSTEM_ACTOR_ID``) so system actions are always distinguishable from analyst actions.

Without authentication (``--insecure-no-auth``) ``api.route`` acts as the server reviewer with ``authenticated=False``;
authorisation (authz.py) is then not enforced.
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

SYSTEM_ACTOR_ID = "ringfence-system"
SYSTEM_ROLE = "system"
SUPERVISOR = "supervisor"
ANALYST = "analyst"


@dataclass(frozen=True)
class Actor:
    user: str                                   # actor_id recorded on audit events
    role: str                                   # actor_role recorded on audit events (analyst | supervisor | system)
    roles: frozenset = field(default_factory=frozenset)   # access roles from the credentials file
    reviewer_role: str | None = None            # role presented to the AuthorityPolicy (None = the server's role)
    authenticated: bool = True                  # False: --insecure-no-auth (server reviewer, no enforcement)
    system: bool = False

    @property
    def supervisor(self) -> bool:
        return SUPERVISOR in self.roles

    def as_record(self) -> dict:
        return {"user": self.user, "role": self.role, "system": self.system, "authenticated": self.authenticated}


_CURRENT: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("ringfence_actor", default=None)


def current() -> Actor | None:
    return _CURRENT.get()


def current_actor() -> tuple[str | None, str | None]:
    """(user, role) of the acting identity; (None, None) outside any request / job context."""
    a = _CURRENT.get()
    return (a.user, a.role) if a else (None, None)


@contextmanager
def acting_as_actor(actor: Actor | None):
    tok = _CURRENT.set(actor)
    try:
        yield actor
    finally:
        _CURRENT.reset(tok)


@contextmanager
def acting_as(user: str, role: str | None = None, roles=(), reviewer_role: str | None = None,
              authenticated: bool = True):
    roles = frozenset(roles or ())
    role = role or (SUPERVISOR if SUPERVISOR in roles else ANALYST)
    with acting_as_actor(Actor(user=user, role=role, roles=roles, reviewer_role=reviewer_role,
                               authenticated=authenticated)) as a:
        yield a


def system_actor(actor_id: str = SYSTEM_ACTOR_ID) -> Actor:
    return Actor(user=actor_id, role=SYSTEM_ROLE, system=True, authenticated=False)


@contextmanager
def acting_as_system(actor_id: str = SYSTEM_ACTOR_ID):
    with acting_as_actor(system_actor(actor_id)) as a:
        yield a


def bind(fn, actor: Actor | None = None):
    """Wrap a job-thread target so it runs under the actor captured NOW (job creation), or the system actor when
    nothing initiated it. New threads start with an empty context, so this is the only way identity reaches a job."""
    captured = actor if actor is not None else (_CURRENT.get() or system_actor())

    def run(*args, **kw):
        with acting_as_actor(captured):
            return fn(*args, **kw)
    run.actor = captured
    return run


def start_thread(fn, *args) -> threading.Thread:
    """threading.Thread(target=bind(fn), daemon=True).start() - the actor-propagating spawn used by job starters."""
    t = threading.Thread(target=bind(fn), args=args, daemon=True)
    t.start()
    return t
