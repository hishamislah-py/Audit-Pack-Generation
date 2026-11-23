"""Relationship register (TMS, 23 Nov 2026): the engine's deterministic financial-relationship discovery as ONE structured
contract carried by the audit pack to investigations, the AI closing summary and the final pack.

Why: the engine discovers relationships between exceptions in two layers. The default correlation (validate.py,
`_correlate_exceptions`) has shallow fixed rules (L1 reference, L2 persistence, L3 lineage applied to any failing snapshot,
single-line amount candidates). Workstream 3 enrichment (enrichment.py, off by default) discovers far more: transaction,
duplicate, timing and snapshot lineage with amounts reconciled exactly, line-SUM candidates over settlement lines,
suspected common causes (confirmed facts separated from unverified inferences) and REJECTED coincidences. Until now that
model only reached the pack as flattened group/candidate strings plus a side file (processing/enrichment.json) that no
consumer read, so the AI had to rediscover low-level relationships it could not see.

The register is built ONLY for runs with enrichment (EngineRules.enrichment_v1): every pack built with the default rules is
byte-identical to before. It copies the engine's own results; it never sets a cause, never confirms a common cause and never
changes an exception. Citations are resolved to evidence-register records (source documents only).

Statuses (from the engine):
  CONFIRMED  a shared source record or reference connects the exceptions AND the amounts reconcile exactly
  CANDIDATE  an indirect link (for example settlement lines whose amounts SUM to a client's roll-forward difference): the
             attribution rests on amounts only - never a cause on its own
  REJECTED   an apparent link the records contradict or do not support (for example equal date and amount with no shared
             record, or lineage through a record that is not itself out of line)
Common causes are SUSPECTED (or NOT_ESTABLISHED), never confirmed.
"""

import re

SCHEMA = "uc042-relationship-register/1.0"
_LINK = re.compile(r"^(EXC-\S+)—(EXC-\S+) (L\d[^:]*): (.*) \[(.*)\]$")
STATEMENT = ("Relationships discovered deterministically by the engine. Discovery never establishes a cause: a CANDIDATE rests on "
             "amounts or indirect links only, a REJECTED relationship must not be used as support, and a common cause is at most "
             "SUSPECTED until an analyst verifies it.")


def _cites(refs):
    return "; ".join(r for r in refs if r)


def build_relationship_register(v, resolve):
    """The register for an enriched engine run `v`; None for a default run. `resolve(text, owner)` is the pack's citation
    resolver (evidence IDs; records are added to the evidence register)."""
    st = getattr(v, "enrichment", None)
    if not getattr(v.rules, "enrichment_v1", False) or st is None:
        return None
    prefix = v.scenario_id()
    rels = []

    def add(exc_ids, link_type, status, basis, refs, amounts=None, contradicting=False):
        rid = f"REL-{prefix}-{len(rels) + 1:02d}"
        recs = resolve(_cites(refs), rid) if refs else []
        rels.append({"relationship_id": rid, "exception_ids": sorted(exc_ids), "link_type": link_type, "status": status,
                     "basis": basis, "amounts": dict(amounts or {}),
                     "supporting_records": [] if contradicting else recs,
                     "contradicting_records": recs if contradicting else [],
                     "provenance": {"discovered_by": "engine relationship discovery (enrichment-v1)", "rule": link_type}})

    for r in st.get("relationships", []):
        add(r["exception_ids"], r["link_type"], r["strength"], r["basis"], r.get("evidence") or [], r.get("amounts"),
            contradicting=r["strength"] == "REJECTED")
    # The links that formed the engine's investigation groups (L1 reference, L2 persistence, L3 lineage; with enrichment an
    # L3 snapshot link exists only when evidence-backed) are CONFIRMED relationships too: record each pair not already
    # present, with its own citations (format written by validate._correlate_exceptions: "A—B KIND: basis [cites]").
    have = {(tuple(r["exception_ids"]), r["status"]) for r in rels}
    for g in getattr(v, "groups", []):
        for part in (g.get("links") or "").split(" | "):
            m = _LINK.match(part.strip())
            if not m:
                continue
            a, b, kind, basis, cites = m.groups()
            pair = tuple(sorted([a, b]))
            if (pair, "CONFIRMED") in have:
                continue
            have.add((pair, "CONFIRMED"))
            add(pair, kind.strip(), "CONFIRMED", basis.strip(), [c.strip() for c in cites.split(",") if c.strip()])
    for c in st.get("rejected_coincidences", []):
        add(c["exception_ids"], "DATE_AMOUNT_COINCIDENCE", "REJECTED",
            f"{c['basis']} ({c['date']}, {c['currency']} {c['amount']})", [], {"amount": c["amount"]})
    causes = []
    for c in st.get("common_causes", []):
        cid = c.get("common_cause_id") or f"CC-{prefix}-{len(causes) + 1:02d}"
        causes.append({"common_cause_id": cid, "exception_ids": list(c["exception_ids"]), "status": c["status"],
                       "proposed_common_cause": c["proposed_common_cause"], "confirmed_facts": list(c.get("confirmed_facts") or []),
                       "unverified_inferences": list(c.get("unverified_inferences") or []),
                       "missing_evidence": list(c.get("missing_evidence") or []),
                       "all_missing_lines_accounted_for": c.get("all_missing_lines_accounted_for"),
                       "unaccounted_lines": list(c.get("unaccounted_lines") or []), "note": c.get("note", ""),
                       "supporting_records": resolve(_cites(c.get("evidence") or []), cid),
                       "provenance": {"discovered_by": "engine relationship discovery (enrichment-v1)", "rule": "COMMON_CAUSE"}})
    return {"schema": SCHEMA, "statement": STATEMENT, "relationships": rels, "common_causes": causes}
