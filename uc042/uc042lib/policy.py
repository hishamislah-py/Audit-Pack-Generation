"""Reconciliation-policy documents (IN-17): the versions this POC recognises, which version applies to a reporting
period, and the approved selections. Used at intake (uc042lib.prepare, the upload analysis) and by the historical
demonstration build; the engine itself only reads the one document a run selects (PeriodConfig.policy_version) and
never chooses between policy documents.

Every recognised version is a SYNTHETIC document. A policy PDF is recognised only if its key details state a version in
POLICY_VERSIONS, the stated effective date equals the registered one, and its text carries the version's required
markings (watermarks). Any other PDF with policy key details is unsupported and never used as a policy.

Applicability: a version applies to a period if it is effective by the period end and not superseded (the next
registered version's effective date) on or before the period start. When more than one supplied version applies, the
period needs an approved selection (APPROVED_SELECTIONS); without one the policy evidence is ambiguous and nothing is
selected. Decisions are recorded in docs/UC042_HISTORICAL_DEMO_DECISIONS.md (HD-1, HD-2).
"""
import re
from dataclasses import dataclass
from datetime import date

from .period import PeriodConfig


@dataclass(frozen=True)
class PolicyVersion:
    version: str
    effective: date
    classification: str          # ILLUSTRATIVE_SYNTHETIC or SYNTHETIC_PROJECT_DOCUMENT
    required_markings: tuple     # text that must appear in the document (whitespace-normalised)
    description: str
    decision: str = ""


@dataclass(frozen=True)
class ApprovedSelection:
    version: str
    decision: str
    basis: str


POLICY_VERSIONS = {
    "1.1": PolicyVersion(
        "1.1", date(2025, 10, 1), "ILLUSTRATIVE_SYNTHETIC",
        ("ILLUSTRATIVE SYNTHETIC DOCUMENT", "NOT AN OFFICIAL RECORD", "Illustrative predecessor of policy v1.2"),
        "Illustrative synthetic predecessor of v1.2 (same rules), created for the January-August 2026 historical "
        "demonstration. Not an actual or historical Moorwand policy.", "HD-1"),
    "1.2": PolicyVersion(
        "1.2", date(2026, 5, 7), "SYNTHETIC_PROJECT_DOCUMENT", ("SYNTHETIC DOCUMENT - UC-042 POC",),
        "The project's synthetic reconciliation policy (September 2026 baseline)."),
}

APPROVED_SELECTIONS = {
    "PER-2026-05": ApprovedSelection(
        "1.2", "HD-2", "v1.1 (illustrative) and v1.2 both apply to May 2026 (v1.2 effective 2026-05-07); v1.2, the version "
                       "in force at the period end, is selected for reconciliation; both documents stay in the source "
                       "inventory and audit trail; results under v1.1 were identical apart from the cited file name"),
}

SELECTED, SUPPLIED_NOT_SELECTED, NOT_APPLICABLE, AMBIGUOUS = "SELECTED", "SUPPLIED_NOT_SELECTED", "NOT_APPLICABLE", "AMBIGUOUS"


def normalise(text):
    return re.sub(r"\s+", " ", (text or "").replace("—", "-").replace("�", "-")).strip()


def document_text(path):
    from pypdf import PdfReader
    return normalise(" ".join(p.extract_text() or "" for p in PdfReader(str(path)).pages))


def recognise(details, text):
    """(version, problems) for a PDF identified as a policy by its key details. problems empty: a recognised version."""
    version = (details.get("Document version") or "").strip()
    reg = POLICY_VERSIONS.get(version)
    if reg is None:
        return None, [f"unsupported policy version {version or '(none)'!r}; recognised versions: {', '.join(POLICY_VERSIONS)}"]
    problems = []
    if (details.get("Effective date") or "").strip() != reg.effective.isoformat():
        problems.append(f"policy v{version} states effective date {details.get('Effective date') or '(none)'}, "
                        f"not the registered {reg.effective}")
    text = normalise(text)
    problems += [f"policy v{version} lacks the required marking {m!r}" for m in reg.required_markings if normalise(m) not in text]
    return version, problems


def _successor(version):
    later = sorted((v for v in POLICY_VERSIONS.values() if v.effective > POLICY_VERSIONS[version].effective), key=lambda v: v.effective)
    return later[0] if later else None


def applicability(version, period):
    """(applies, reason) of a registered version for a period."""
    reg = POLICY_VERSIONS[version]
    if reg.effective > period.end:
        return False, f"policy v{version} takes effect on {reg.effective}, after {period.label}"
    nxt = _successor(version)
    if nxt is not None and nxt.effective <= period.start:
        return False, f"policy v{version} is superseded by v{nxt.version} from {nxt.effective}, before {period.label}"
    return True, f"policy v{version} (effective {reg.effective}) applies to {period.label}"


def applicable_versions(period):
    return [v for v in POLICY_VERSIONS if applicability(v, period)[0]]


def select(period, supplied, override=None):
    """Choose the governing policy among the supplied recognised versions.

    supplied: {version: number of distinct files of that version}; override: a version selected explicitly by the caller
    (PeriodConfig.policy_version), which replaces the approved/automatic choice but must itself apply. Returns (selected version or None, basis,
    {version: (status, reason)}). Statuses: SELECTED, SUPPLIED_NOT_SELECTED (applies and is kept in the inventory, not
    used for reconciliation), NOT_APPLICABLE, AMBIGUOUS (several different files of one version, or several applicable
    versions without an approved selection)."""
    if not isinstance(period, PeriodConfig):
        period = PeriodConfig.from_id(period)
    status, usable = {}, []
    for version, count in sorted(supplied.items()):
        ok, why = applicability(version, period)
        if count > 1:
            status[version] = (AMBIGUOUS, f"{count} different files state policy v{version}; none is used")
        elif not ok:
            status[version] = (NOT_APPLICABLE, why)
        else:
            usable.append(version)
    approved = APPROVED_SELECTIONS.get(period.period_id)
    wanted = override if override is not None else approved.version if approved is not None else None
    if wanted is not None and wanted not in usable:
        # nothing is substituted: the other applicable versions stay supplied, and the policy evidence is missing
        for v in usable:
            status[v] = (SUPPLIED_NOT_SELECTED, f"policy v{v} supplied and kept in the source inventory; not used for "
                                                f"reconciliation (v{wanted} is required for {period.period_id})")
        how = "explicitly selected policy" if override is not None else \
            f"approved selection for {period.period_id} is policy"
        return None, (f"the {how} v{wanted}{f' ({approved.decision})' if override is None else ''}, which was not supplied "
                      "as a usable document"), status
    if override is not None:
        chosen, basis = override, f"policy v{override} selected explicitly for {period.period_id}"
    elif approved is not None:
        chosen, basis = approved.version, f"approved selection {approved.decision}: {approved.basis}"
    elif len(usable) == 1:
        chosen, basis = usable[0], applicability(usable[0], period)[1]
    elif not usable:
        return None, f"no supplied policy version applies to {period.period_id}", status
    else:
        for v in usable:
            status[v] = (AMBIGUOUS, f"policy versions {', '.join(usable)} all apply to {period.period_id} and no selection "
                                    "is approved; none is used")
        return None, f"more than one policy version applies to {period.period_id} without an approved selection", status
    for v in usable:
        status[v] = (SELECTED, basis) if v == chosen else (
            SUPPLIED_NOT_SELECTED, f"policy v{v} supplied and kept in the source inventory; not used for reconciliation "
                                   f"(v{chosen} selected)")
    return chosen, basis, status
