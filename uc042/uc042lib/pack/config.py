"""Fixed configuration for the synthetic POC pack (decisions D2, D5)."""

PACK_SCHEMA_VERSION = "uc042-pack/0.1"
ENTITY_ID = "SYN-EMI-001"
ENTITY_NOTICE = ("Illustrative synthetic entity identifier for the UC-042 POC (decision D2); "
                 "not a confirmed Moorwand production identifier.")
CORRELATION_VERSION = "deterministic-v1"
NOT_AVAILABLE = "not available"
SYNTHETIC_NOTICE = ("ILLUSTRATIVE SYNTHETIC DATA (decision D6): all records, timings, references and fee treatments are "
                    "illustrative conventions for the UC-042 POC, not confirmed Moorwand practice.")
NOT_A_COMPLIANCE_OPINION = ("This pack presents deterministic checks of synthetic evidence. It is not a compliance opinion, "
                            "does not establish operational correctness, and does not establish the cause of any exception.")
GROUP_STATEMENT = "An investigation group links exceptions for review; it does not establish a cause."
LIMITATIONS = [
    "Resource items B-D are taken as reported (0.00); no independent source exists.",
    "The D+1 comparison is not performed (synthetic convention).",
    "PDF key details are parsed from a fixed synthetic layout; no human confirmation of extracted fields.",
    "Results show the internal consistency of illustrative synthetic data, not operational truth or compliance.",
    "Monthly totals are not included: the engine does not calculate them and the pack performs no financial calculation (D4).",
]
# Engine modules whose content defines the processing behaviour (engine fingerprint).
ENGINE_MODULES = ["schema.py", "period.py", "structure.py", "money.py", "validate.py"]

# Engine checks that emit a result only when they find a problem (no explicit PASS row). The pack lists them with
# check_outcome NO_FINDINGS when the engine's evidence gate shows the check ran; it never presents them as PASS.
FAILURE_ONLY_CHECKS = {
    "BANK-CASH-LINK": "emits a result only for a safeguarding bank entry without a cash-book counterpart",
}
