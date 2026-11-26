"""Engine rules as they stood when the stored (immutable) packs were published, for the reproducibility tests.

Packs published before 17 Nov 2026 record a reconciled zero difference in C06-DIFFERENCE / C08-DIFFERENCE as
NOT_APPLICABLE; the approved rule since then is PASS. Stored packs are never rewritten, so a test that proves "the current
code reproduces the stored pack" rebuilds it under the rules it was published with, passed EXPLICITLY to the engine
(uc042lib.validate.EngineRules; consolidated remediation D1): nothing is patched, so other runs are never affected."""
from uc042lib.validate import PUBLISHED_RULES_BEFORE_17_NOV_2026 as PUBLISHED_RULES  # noqa: F401
