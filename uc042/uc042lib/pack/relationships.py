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
  CONFIRMED  a shared source record or reference connects the exceptions AND the engine kept the PROOF of the
             confirmation (schema 1.1: `proof`, uc042lib.relproof)
  CANDIDATE  an indirect link (for example settlement lines whose amounts SUM to a client's roll-forward difference): the
             attribution rests on amounts only - never a cause on its own
  REJECTED   an apparent link the records contradict or do not support (for example equal date and amount with no shared
             record, or lineage through a record that is not itself out of line)
Common causes are SUSPECTED (or NOT_ESTABLISHED), never confirmed.

Schema 1.1 (23 Nov 2026, evidence-bearing relationships; forensic report on TC06 01<->03):
  - links are read from the engine's STRUCTURED links (Validator.relationship_links), not parsed from group text
    (the text parser remains only as a fallback for an engine that does not expose structured links);
  - every relationship carries `relationship_type` (uc042lib.relproof.RELATIONSHIP_TYPES), `engine_status` (the engine's
    own status, never changed by anything downstream) and `proof` (rule, quantities, calculation, result, chronology,
    requirement effect, corroboration, established / not established, missing evidence, limitations, records), with every
    record citation resolved to an evidence-register ID;
  - a relationship the engine CONFIRMED but whose proof is absent is NOT presented as confirmed: `status` becomes CANDIDATE
    (engine_status stays CONFIRMED) and `limitations` says why. Nothing is falsely confirmed.
"""

import re

from ..relproof import has_proof, make_proof

SCHEMA = "uc042-relationship-register/1.1"
_LINK = re.compile(r"^(EXC-\S+)—(EXC-\S+) (L\d[^:]*): (.*) \[(.*)\]$")
STATEMENT = ("Relationships discovered deterministically by the engine. Discovery never establishes a cause: a CONFIRMED "
             "relationship carries the engine's proof that its exceptions are connected (often through one faulty record), "
             "and that proof states separately what it does NOT establish (usually why the record is wrong). A CANDIDATE "
             "rests on amounts or indirect links only, a REJECTED relationship must not be used as support, and a common "
             "cause is at most SUSPECTED until an analyst verifies it.")
NO_PROOF_LIMITATION = ("the engine confirmed this link but kept no proof of the confirmation; it is presented as a CANDIDATE "
                       "until the confirmation evidence is available")
_TYPE_OF_LINK = {"L1 REFERENCE": "SHARED_REFERENCE", "L2 PERSISTENCE": "PERSISTENCE", "L4 TRANSACTION LINEAGE": "TRANSACTION_LINEAGE",
                 "L5 TIMING TRACE": "TIMING_TRACE", "L6 DUPLICATE LINEAGE": "DUPLICATE_LINEAGE",
                 "L7 SNAPSHOT LINEAGE": "SHARED_FAULTY_RECORD", "LINE-SUM MATCH": "AMOUNT_COMBINATION",
                 "L3 LINEAGE (b)": "CAUSAL_PROPAGATION"}


def _cites(refs):
    return "; ".join(r for r in refs if r)


def _type_of(link_type, basis):
    if link_type in _TYPE_OF_LINK:
        return _TYPE_OF_LINK[link_type]
    if link_type.startswith("L3"):
        return ("BALANCE_LINEAGE" if basis.startswith("bank entry") else
                "SHARED_INPUT" if "uses the recomputed requirement" in basis else "CAUSAL_PROPAGATION")
    return "COINCIDENCE" if "COINCIDENCE" in link_type else "SHARED_REFERENCE"


def build_relationship_register(v, resolve):
    """The register for an enriched engine run `v`; None for a default run. `resolve(text, owner)` is the pack's citation
    resolver (evidence IDs; records are added to the evidence register)."""
    st = getattr(v, "enrichment", None)
    if not getattr(v.rules, "enrichment_v1", False) or st is None:
        return None
    prefix = v.scenario_id()
    rels = []

    def resolved_proof(proof, rid):
        if not proof:
            return None
        p = dict(proof)
        p["faulty_record"] = (resolve(p["faulty_record"], rid) or [""])[0] if p.get("faulty_record") else ""
        p["quantities"] = [dict(q, record=(resolve(q["record"], rid) or [""])[0] if q.get("record") else "") for q in p["quantities"]]
        p["records"] = list(dict.fromkeys(i for c in p.get("records") or [] for i in resolve(c, rid)))
        return p

    def add(exc_ids, link_type, status, basis, refs, amounts=None, contradicting=False, rtype=None, proof=None, rule=None):
        rid = f"REL-{prefix}-{len(rels) + 1:02d}"
        recs = resolve(_cites(refs), rid) if refs else []
        p = resolved_proof(proof, rid)
        limitations = list((p or {}).get("limitations") or [])
        shown = status
        if status == "CONFIRMED" and not has_proof(p):
            shown = "CANDIDATE"                       # rule 1: never present a CONFIRMED relationship without its proof
            limitations.append(NO_PROOF_LIMITATION)
        rels.append({"relationship_id": rid, "exception_ids": sorted(exc_ids), "link_type": link_type,
                     "relationship_type": rtype or _type_of(link_type, basis), "status": shown, "engine_status": status,
                     "basis": basis, "amounts": dict(amounts or {}),
                     "supporting_records": [] if contradicting else recs,
                     "contradicting_records": recs if contradicting else [],
                     "proof": p, "limitations": limitations,
                     "provenance": {"discovered_by": "engine relationship discovery (enrichment-v1)", "rule": rule or link_type}})

    for r in st.get("relationships", []):
        add(r["exception_ids"], r["link_type"], r["strength"], r["basis"], r.get("evidence") or [], r.get("amounts"),
            contradicting=r["strength"] == "REJECTED", rtype=r.get("relationship_type"), proof=r.get("proof"))
    # The links that formed the engine's investigation groups (L1 reference, L2 persistence, L3 lineage; with enrichment an
    # L3 snapshot link exists only when evidence-backed) are CONFIRMED relationships too: record each pair not already
    # present, with its type, proof and citations. Schema 1.1 reads the engine's structured links; the group-text parser
    # ("A—B KIND: basis [cites]") is kept only for an engine without structured links.
    have = {(tuple(r["exception_ids"]), r["engine_status"]) for r in rels}
    structured = getattr(v, "relationship_links", None)
    if structured is not None:
        group_links = [(tuple(l["exception_ids"]), l["link_type"], l["basis"], l["cites"], l.get("relationship_type"), l.get("proof"))
                       for l in structured if l.get("source") != "enrichment"]
    else:
        group_links = []
        for g in getattr(v, "groups", []):
            for part in (g.get("links") or "").split(" | "):
                m = _LINK.match(part.strip())
                if m:
                    a, b, kind, basis, cites = m.groups()
                    group_links.append(((a, b), kind.strip(), basis.strip(), [c.strip() for c in cites.split(",") if c.strip()], None, None))
    for (a, b), kind, basis, cites, rtype, proof in group_links:
        pair = tuple(sorted([a, b]))
        if (pair, "CONFIRMED") in have:
            continue
        have.add((pair, "CONFIRMED"))
        add(pair, kind, "CONFIRMED", basis, cites, rtype=rtype, proof=proof)
    for c in st.get("rejected_coincidences", []):
        basis = f"{c['basis']} ({c['date']}, {c['currency']} {c['amount']})"
        add(c["exception_ids"], "DATE_AMOUNT_COINCIDENCE", "REJECTED", basis, [], {"amount": c["amount"]}, rtype="COINCIDENCE",
            proof=make_proof("DATE_AMOUNT_COINCIDENCE", "COINCIDENCE", result="NO_SHARED_RECORD",
                             quantities=[(f"|discrepancy| of {e}", c["amount"], "") for e in c["exception_ids"]],
                             calculation=f"both exceptions show {c['currency']} {c['amount']} on {c['date']}; no source record or "
                                         "reference is shared",
                             established=["the same date, currency and amount"],
                             not_established=["any record connecting the two exceptions"],
                             limitations=["matching amounts and dates are never evidence of a relationship on their own"]))
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


def confirmed_relationships(register):
    """The relationships the AI must acknowledge or formally challenge (register status CONFIRMED, proof present)."""
    return [r for r in (register or {}).get("relationships", []) if r["status"] == "CONFIRMED"]
