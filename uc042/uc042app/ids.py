"""Identifier formats. Every ID from a request is checked here before any storage is touched (spec 06 §8.3)."""
import re
import secrets

from uc042lib.final_pack.model import FINAL_PACK_ID_RE
from uc042lib.final_pack.sources import INVESTIGATION_ID_RE
from uc042lib.investigation.config import EXCEPTION_ID_RE, PACK_ID_RE

from .errors import InvalidInput

REVIEW_ID_RE = re.compile(r"^RS-[0-9a-f]{24}$")
DECISION_ID_RE = re.compile(r"^RD-[0-9a-f]{24}$")
PREVIEW_ID_RE = re.compile(r"^PV-[0-9a-f]{24}$")
JOB_ID_RE = re.compile(r"^JOB-[0-9a-f]{24}$")
CASE_ID_RE = re.compile(r"^CASE-[0-9a-f]{24}$")
AI_AUTHORIZATION_ID_RE = re.compile(r"^AIA-[0-9a-f]{24}$")

PATTERNS = {"pack_id": PACK_ID_RE, "exception_id": EXCEPTION_ID_RE, "investigation_id": INVESTIGATION_ID_RE,
            "review_id": REVIEW_ID_RE, "decision_id": DECISION_ID_RE, "preview_id": PREVIEW_ID_RE, "job_id": JOB_ID_RE,
            "final_pack_id": FINAL_PACK_ID_RE, "case_id": CASE_ID_RE,
            "authorization_id": AI_AUTHORIZATION_ID_RE}


def check(kind, value):
    if not isinstance(value, str) or not PATTERNS[kind].match(value):
        raise InvalidInput(f"invalid {kind.replace('_', ' ')}", code="INVALID_ID")
    return value


def new_id(prefix, nbytes=12):
    return f"{prefix}-{secrets.token_hex(nbytes)}"
