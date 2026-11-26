"""Phase 6 offline parity harness (no AI call, read-only on every input). Strict since the independent review (DR-02).

For every persisted investigation record found (published and not published) in this copy, in Clone E's storage and in
the 16 Nov showcase storage:
  * tools-mode records with a tool-call transcript are compared: the deterministic packet is rebuilt for the same pack and
    exception and measured for
      - coverage of every record the MODEL fetched with a tool and then cited (the records deterministic retrieval must
        supply);
      - coverage of every NOT_FOUND search the model cited. STRICT (DR-02): covered only by a deterministic search with
        the same COMPLETE normalised query (every key; only date / reference synonyms folded; a None filter equals an
        absent one) whose own result is also NOT_FOUND. Every miss is listed; the denominator is never reduced;
      - packet size and pruning register;
  * every other record (fixed mode, no transcript) is listed under "excluded" with its reason: nothing is skipped silently;
  * attempts are reported by status: published, completed but not published, failed (and any other status).
The normaliser below is the harness's own, deliberately independent of det_retrieval._norm.
Usage: python -I -m tests.det_parity [out.json]"""
import glob
import json
import sys
from pathlib import Path

from uc042lib.investigation import det_retrieval as det
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.packet_view import model_view_text
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for

ROOT = Path(__file__).resolve().parent.parent
P10 = Path("C:/Users/artlptp263user/p10")
STORES = [  # (label, investigations root, packs root, datasets root)
    ("copy", ROOT / "investigations", ROOT / "packs", ROOT / "uc042_dataset"),
    ("copy-history", ROOT / "demo_history" / "investigations", ROOT / "demo_history" / "packs", ROOT / "demo_history" / "datasets"),
    ("clone-e", P10 / "env_e" / "investigations", P10 / "env_e" / "packs", P10 / "env_e" / "docstore" / "cases"),
    ("showcase", P10 / "env_s" / "investigations", P10 / "env_s" / "packs", P10 / "env_s" / "docstore" / "cases"),
]

DATE_KEYS = ("date", "statement_date", "booking_date", "recon_date")
REFERENCE_KEYS = ("reference", "bank_reference")


def full_query(query):
    """The harness's own complete normalised query: every key kept; None values dropped (no filter); the date and the
    reference synonyms mapped to one name each when they agree."""
    q = {k: v for k, v in (query or {}).items() if v is not None}
    for group, name in ((DATE_KEYS, "date"), (REFERENCE_KEYS, "reference")):
        present = {k: q[k] for k in group if k in q}
        if present and len(set(json.dumps(v) for v in present.values())) == 1:
            value = next(iter(present.values()))
            for k in present:
                q.pop(k)
            q[name] = value
    return json.dumps(q, sort_keys=True, ensure_ascii=False)


def not_found_covered(model_search, det_searches):
    """True only when a deterministic search has the same complete normalised query AND is itself NOT_FOUND."""
    key = full_query(model_search.get("query"))
    return any(s.get("result") == "NOT_FOUND" and full_query(s.get("query")) == key for s in det_searches)


# Approved semantic equivalence (owner approval, 16 Nov 2026; one case: Clone E EXC-CASE-01 SEARCH-08). Tried only when the
# exact match fails, and only for this relationship: follow_relationship over settlement_line_to_transaction is a primary-key
# lookup of IN-11 by the line's txn_id (tools.follow_relationship, how == "pk"), which is the same lookup as the file-shaped
# search {"file": "IN-11", "txn_id": <txn_id>} that packet.py / tools.get_settlement_batch record for a line's transaction.
APPROVED_EQUIVALENCES = {"settlement_line_to_transaction": ("IN-13", "txn_id", "IN-11", "txn_id")}


def relationship_equivalent_query(model_query, store):
    """The file-shaped query an approved relationship-shaped query is equivalent to, or None. Requires: exactly the keys
    evidence_id / relationship / value; an approved relationship; the source record present in the pack's data, of the
    relationship's source file, whose own field value equals `value` exactly (verified against the data, not the query)."""
    q = model_query or {}
    if set(q) != {"evidence_id", "relationship", "value"} or q["relationship"] not in APPROVED_EQUIVALENCES:
        return None
    src_file, field, target_file, target_key = APPROVED_EQUIVALENCES[q["relationship"]]
    value, source = q["value"], store.get(q["evidence_id"], "parity probe") if q["evidence_id"] else None
    if not value or source is None or source.get("file_id") != src_file or source["fields"].get(field) != value:
        return None
    return full_query({"file": target_file, target_key: value})


def not_found_equivalent(model_search, det_packet, store):
    """Approved semantic-equivalence coverage: the equivalent file-shaped query is a NOT_FOUND search of the deterministic
    packet, and the same source line (same evidence_id, same txn_id) is a record of that packet. Never by txn_id alone."""
    key = relationship_equivalent_query(model_search.get("query"), store)
    if key is None:
        return False
    q = model_search["query"]
    src_file, field, _, _ = APPROVED_EQUIVALENCES[q["relationship"]]
    line = next((r for r in det_packet["source_records"] if r["evidence_id"] == q["evidence_id"]), None)
    if line is None or line.get("file_id") != src_file or line["fields"].get(field) != q["value"]:
        return False
    return any(s.get("result") == "NOT_FOUND" and full_query(s.get("query")) == key for s in det_packet["searches"])


def _cited(f):
    ids = set()
    for x in f.get("confirmed_findings") or []:
        ids |= set(x.get("evidence_ids") or []) | set(x.get("supporting_records") or [])
    for h in f.get("hypotheses") or []:
        ids |= set(h.get("supporting_evidence") or []) | set(h.get("contradictory_evidence") or [])
    for c in f.get("contradictory_evidence") or []:
        ids |= set(c.get("evidence_ids") or []) | set(c.get("compared_evidence") or [])
    for m in f.get("missing_evidence") or []:
        ids |= set(m.get("related_ids") or [])
    return ids


def _status(kind, f):
    if kind == "published":
        return "published"
    s = (f.get("investigation_status") or "").upper()
    return {"COMPLETED": "completed_not_published", "FAILED": "failed"}.get(s, "other")


def _records():
    """Every persisted record: (label, kind, findings, ledger, tool_calls, packs_root, data_root, excluded_reason, path)."""
    for label, inv_root, packs_root, data_root in STORES:
        if not inv_root.is_dir():
            continue
        for fp in sorted(glob.glob(str(inv_root / "PACK-*" / "EXC-*" / "INV-*" / "findings.json"))):
            d = Path(fp).parent
            f = json.loads(Path(fp).read_text(encoding="utf-8"))
            why = None
            if f.get("investigation_mode") != "tools":
                why = f"{f.get('investigation_mode') or 'fixed'} mode: no model-directed tool fetches to compare"
            elif not (d / "tool_calls.json").is_file() or not (d / "evidence_ledger.json").is_file():
                why = "tools mode without a tool-call transcript or evidence ledger"
            tc = json.loads((d / "tool_calls.json").read_text(encoding="utf-8")) if not why else None
            ledger = json.loads((d / "evidence_ledger.json").read_text(encoding="utf-8")) if not why else None
            yield label, "published", f, ledger, tc, packs_root, data_root, why, fp
        for fp in sorted(glob.glob(str(inv_root / "_not_published" / "PACK-*" / "*" / "*.json"))):
            x = json.loads(Path(fp).read_text(encoding="utf-8"))
            f = x.get("result") or {}
            why = None
            if f.get("investigation_mode") != "tools":
                why = f"{f.get('investigation_mode') or 'fixed'} mode: no model-directed tool fetches to compare"
            elif not x.get("tool_calls") or not x.get("evidence_ledger"):
                why = "tools mode without a tool-call transcript or evidence ledger"
            yield label, "not_published", f, x.get("evidence_ledger"), x.get("tool_calls"), packs_root, data_root, why, fp


def _excluded_row(label, kind, f, why, fp):
    return {"store": label, "status": _status(kind, f), "pack_id": f.get("pack_id"), "exception_id": f.get("exception_id"),
            "investigation_id": f.get("investigation_id"), "investigation_mode": f.get("investigation_mode"), "reason": why,
            "record": Path(fp).name}


def run(excluded=None):
    """Rows of compared attempts. Records that cannot be compared are appended to `excluded` (when given) with a reason."""
    rows = []
    for label, kind, f, ledger, tc, packs_root, data_root, why, fp in _records():
        if why:
            if excluded is not None:
                excluded.append(_excluded_row(label, kind, f, why, fp))
            continue
        pid, exc = f["pack_id"], f["exception_id"]
        pack = store = None
        errors = []
        for pr, dr in [(packs_root, data_root)] + [(x[2], x[3]) for x in STORES]:  # the pack and its source rows, wherever they are
            try:
                pack = load_pack(pid, pr)
                store = EvidenceStore(pack, dr)
                break
            except Exception as e:  # noqa: BLE001 - reported, never hidden
                errors.append(str(e)[:80])
                pack = store = None
        status = _status(kind, f)
        if store is None:
            rows.append({"store": label, "status": status, "pack_id": pid, "exception_id": exc, "error": f"pack or sources not loadable: {errors[-1:]}"})
            continue
        case = build_case(pack, exc)
        route = route_for(case["exception"], case["candidates"], case["results"])
        base = build_packet(case, build_scope(case), route, retrieve(route, case, store))
        fetched = set()
        for c in tc.get("tool_calls") or []:
            fetched |= set(c.get("new_evidence_ids") or [])
        cited = _cited(f)
        target = sorted(i for i in fetched & cited if ":" in i)
        model_nf = {s["search_id"]: s for s in ledger.get("searches", []) if s.get("result") == "NOT_FOUND"}
        cited_nf = [model_nf[i] for i in sorted(cited) if i in model_nf]
        row = {"store": label, "status": status, "pack_id": pid, "exception_id": exc, "route": route,
               "investigation_id": f.get("investigation_id"), "deterministic_supported": det.supported(route),
               "model_fetched_records": len(fetched), "model_fetched_and_cited": target}
        if det.supported(route):
            col = retrieve(route, case, store)
            reg = det.expand(col, case, route, store)
            p = det.finalise_packet(build_packet(case, build_scope(case), route, col), reg)
            ids = {r["evidence_id"] for r in p["source_records"]}
            nf_missed, nf_semantic, nf_exact = [], [], 0
            for s in cited_nf:
                entry = {"search_id": s["search_id"], "query": s["query"], "description": s["description"][:120]}
                if not_found_covered(s, p["searches"]):
                    nf_exact += 1
                elif not_found_equivalent(s, p, store):
                    nf_semantic.append(dict(entry, matched_by="approved semantic equivalence",
                                            equivalent_query=json.loads(relationship_equivalent_query(s["query"], store))))
                else:
                    nf_missed.append(entry)
            row.update(covered=[i for i in target if i in ids], missed=[i for i in target if i not in ids],
                       not_found_searches_cited=len(cited_nf), not_found_covered=nf_exact + len(nf_semantic),
                       not_found_covered_exact=nf_exact, not_found_semantic_matches=nf_semantic,
                       not_found_missed=nf_missed,
                       # informational only: both are taken from the case, so they cannot differ by construction
                       miss_items_preserved=[m["item_id"] for m in base["missing_evidence"]] == [m["item_id"] for m in p["missing_evidence"]],
                       candidates_unchanged=base["candidate_relationships"] == p["candidate_relationships"],
                       candidates_not_citable_in_findings=all(c["candidate_id"] not in ids for c in p["candidate_relationships"]),
                       records_base=len(base["source_records"]), records_det=len(p["source_records"]),
                       view_chars_base=len(model_view_text(base)), view_chars_det=len(model_view_text(p)),
                       retrieval_rule_version=p["retrieval_rule_version"],
                       pruning_register=reg, at_cap=len(p["source_records"]) >= det.DET_MAX_RECORDS)
        rows.append(row)
    return rows


def _coverage(sup):
    targets = sum(len(r["model_fetched_and_cited"]) for r in sup)
    covered = sum(len(r["covered"]) for r in sup)
    uniq_t = {(r["pack_id"], r["exception_id"], i) for r in sup for i in r["model_fetched_and_cited"]}
    uniq_c = {(r["pack_id"], r["exception_id"], i) for r in sup for i in r["covered"]}
    return {"compared": len(sup), "cited_model_fetched_records": targets, "covered": covered,
            "distinct_per_exception": {"targets": len(uniq_t), "covered": len(uniq_c)},
            "not_found_searches_cited": sum(r["not_found_searches_cited"] for r in sup),
            "not_found_covered": sum(r["not_found_covered"] for r in sup)}


def summary(rows, excluded=None):
    if excluded is None:  # recompute the excluded list (read-only) so the summary always reports it
        excluded = []
        for label, kind, f, _, _, _, _, why, fp in _records():
            if why:
                excluded.append(_excluded_row(label, kind, f, why, fp))
    sup = [r for r in rows if r.get("deterministic_supported")]
    by = {k: [r for r in rows if r.get("status") == k] for k in ("published", "completed_not_published", "failed", "other")}
    out = {"investigations_examined": len(rows), "deterministic_supported": len(sup),
           "attempts": {"published": len(by["published"]), "completed_not_published": len(by["completed_not_published"]),
                        "failed": len(by["failed"]), "other": len(by["other"]),
                        "completed_investigations": len(by["published"]) + len(by["completed_not_published"])},
           "excluded": excluded,
           "unsupported_routes": sorted({r.get("route") for r in rows if not r.get("deterministic_supported") and r.get("route")}),
           "errors": [r for r in rows if r.get("error")],
           "missed": sorted({(r["pack_id"], r["exception_id"], i) for r in sup for i in r["missed"]}),
           "not_found_missed": [dict(m, store=r["store"], status=r["status"], pack_id=r["pack_id"], exception_id=r["exception_id"])
                                for r in sup for m in r["not_found_missed"]],
           "not_found_matching": "strict: complete normalised query and deterministic result NOT_FOUND; plus the approved "
                                 "settlement_line_to_transaction equivalence (reported separately)",
           "not_found_covered_exact": sum(r["not_found_covered_exact"] for r in sup),
           "not_found_semantic_matches": [dict(m, store=r["store"], status=r["status"], pack_id=r["pack_id"],
                                               exception_id=r["exception_id"]) for r in sup for m in r["not_found_semantic_matches"]],
           "miss_items_preserved_all": all(r["miss_items_preserved"] for r in sup),
           "candidates_unchanged_all": all(r["candidates_unchanged"] for r in sup),
           "any_at_record_budget": [(r["pack_id"], r["exception_id"]) for r in sup if r["at_cap"]],
           "pruning_entries": sum(len(r["pruning_register"]) for r in sup),
           "retrieval_rule_versions": sorted({r["retrieval_rule_version"] for r in sup})}
    out.update(_coverage(sup))
    out["by_status"] = {k: _coverage([r for r in v if r.get("deterministic_supported")]) for k, v in by.items() if v}
    return out


if __name__ == "__main__":
    excluded = []
    rows = run(excluded)
    out = {"summary": summary(rows, excluded), "rows": rows}
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1, default=str))
