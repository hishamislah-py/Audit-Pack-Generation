"""Model-facing view of the evidence packet (phase 4, token-optimisation copy).

The STORED packet (evidence_packet.json, packet_sha256, the ledger, allowed_citation_ids, validation) is never changed.
This module renders a separate, deterministic, versioned representation that is sent to the model instead of the raw
packet JSON. Since 1.2 it is EXACT: reconstruct_packet(render_model_view(p)) == p, every list in its original order, so
the packet hash (sha256 of uc042lib.pack.model.canonical(packet without packet_sha256)) recomputed from the view equals
packet_sha256. The records and control results keep their compact, sorted table layout and carry their original position
(packet_order); relationship_order records where each kept, contextual and derived edge stood. (1.1 was content-lossless
only: 57 of 76 packets did not reproduce their hash.) allowed_citation_ids is stored sorted (packet._citation_ids).

Hardening (DR-06): a key missing from some rows of a table is written as the MISSING sentinel and stays missing on
reconstruction (an explicit None stays None); a real value equal to the sentinel is refused; distinct provenance under one
file_id is kept per record (source_file_index); duplicate edges survive; evidence_ids None is handled; and
render_model_view refuses (ModelViewError) to return any view that does not reconstruct the packet exactly, so a lossy
view is never sent: the investigation fails before any provider request.

What the view changes, and nothing else:
  * file provenance (source_file, file_sha256, record_type) is stated once per file in source_files (once per distinct
    provenance when a file_id has more than one; each row then names its source_file_index);
  * records are laid out per file as a table: 'constants' hold a column whose value is the same on every row of that
    file, 'columns' names the per-row values, and each row keeps its own evidence_id and source_line, so every record
    stays individually identifiable and citable;
  * repetitive control results are laid out the same way;
  * a relationship edge is omitted only when it is exactly derivable: a 'cited_by_control_result' edge from a result to a
    record listed in that result's evidence_ids, whose join_key equals the record's own join_key;
  * citable IDs are given as citation classes (confirmed_finding_ids / hypotheses_only_ids); candidate relationships are
    listed as hypotheses-only. The classes describe allowed_citation_ids and never widen it;
  * group-shared material (provenance, records, links, group results) comes before exception-specific material, so
    members of one investigation group share a longer identical prefix (prompt caching).
JSON is written compactly (no insignificant whitespace). No prose summary ever replaces a record."""
import hashlib
import json

MODEL_VIEW_VERSION = "uc042-model-view/1.2"  # 1.1 (phase 5): verified_links in tool vocabulary; contextual associations separated;
# 1.2 (independent review, not yet released; one version for the whole revision): order-preserving exact reconstruction
# (DR-05), one-to-one signed amount comparison (DR-04), missing-value sentinel / per-record provenance / fail-closed
# invariant (DR-06), evidence_ids_without_derivable_edge wording (DR-07)
DERIVED_EDGE = "cited_by_control_result"
MISSING = {"__missing_key__": True}  # a key absent from this row (never confused with an explicit null)
PROVENANCE = ("source_file", "file_sha256", "record_type")


class ModelViewError(ValueError):
    """The packet cannot be rendered losslessly (or a view does not reconstruct): nothing is sent to the model."""
# Retrieval edges that are NOT identifier joins: a date coincidence and a free-text reference-string match.
CONTEXTUAL_LABELS = ("same account and settlement date, entry_type OWN_FUNDS_TOPUP", "same reference string")
# Relationship types whose two amounts measure the same money movement. A link of these types is compared only when it is
# genuinely one-to-one (DR-04, view 1.2: the source has exactly one target AND the target exactly one source for that
# relationship), using SIGNED values; a disagreement is reported, never explained. Line -> batch and transaction -> batch
# are part-to-whole and are never compared.
COMPARED = {"settlement_batch_to_bank_entry": ("net_amount_reported", "amount"),
            "cashbook_to_bank_entry": ("amount", "amount"),
            "settlement_line_to_transaction": ("amount", "amount")}
# Sign of a record's (unsigned) amount from its own direction field; a missing or unknown value means "not compared".
#   IN-09 bank entry: C = money into the account (packet conventions.bank_dc);
#   IN-10 cash book:  D = money in (conventions.cashbook_dc);
#   IN-11 transaction: CR increases the client balance (conventions.transaction_direction);
#   IN-12 settlement batch: TO_FIRM = into the firm's account (agrees with the bank entry's dc_indicator on every
#         one-to-one batch -> bank link in the data);
#   IN-13 settlement line: same perspective as its transaction (C with CR, D with DR on every line -> transaction link).
SIGNS = {"IN-09": ("dc_indicator", {"C": 1, "D": -1}), "IN-10": ("dc_indicator", {"D": 1, "C": -1}),
         "IN-11": ("direction", {"CR": 1, "DR": -1}), "IN-12": ("direction", {"TO_FIRM": 1, "FROM_FIRM": -1}),
         "IN-13": ("dc_indicator", {"C": 1, "D": -1})}
AMOUNTS_COLUMN = "signed amounts [from, to, agree] (one-to-one links only; null = not compared)"

READING_GUIDE = (
    "source_files: provenance stated once per file. records_by_file: one table per file; 'constants' apply to EVERY row of "
    "that table; each row gives the values of 'columns' in order; every row is one source record, citable by its "
    "evidence_id. control_results: the same table layout. relationships: verified retrieval edges; a result's "
    "evidence_ids are also edges ('cited_by_control_result') and are not repeated there, except the pairs in "
    "evidence_ids_without_derivable_edge (edges not derivable from evidence_ids). packet_order, relationship_order, "
    "derived_order, source_file_index: storage order and provenance only, no evidential meaning. {\"__missing_key__\":true}: "
    "the row has no such key. citation_classes: which IDs may "
    "support a confirmed finding and which are hypotheses only. verified_links: every identifier link between records "
    "of this evidence, in the follow_relationship vocabulary, already established by Python. "
    "contextual_associations_NOT_VERIFIED_JOINS: date or free-text coincidences, context only, never proof of a link.")


def _table(rows, first, skip=()):
    """rows: list of dicts, possibly with different key sets. Returns {constants, columns, rows} with `first` columns
    leading each row. A key a row does not have is written as MISSING (DR-06), never as None."""
    for r in rows:
        for v in r.values():
            if v == MISSING:
                raise ModelViewError("a packet value equals the model view's missing-key sentinel")
    keys = sorted({k for r in rows for k in r} - set(first) - set(skip))
    constants = {}
    if len(rows) > 1:
        for k in keys:
            vals = [json.dumps(r.get(k, None), sort_keys=True) for r in rows]
            if all(k in r for r in rows) and len(set(vals)) == 1:
                constants[k] = rows[0][k]
    cols = list(first) + [k for k in keys if k not in constants]
    return {"constants": constants, "columns": cols, "rows": [[r.get(c, MISSING) for c in cols] for r in rows]}


def _untable(t):
    out = []
    for row in t["rows"]:
        rec = dict(t["constants"])
        rec.update({c: v for c, v in zip(t["columns"], row) if v != MISSING})
        out.append(rec)
    return out


def _derived_edge(result_id, eid, records):
    rec = records.get(eid)
    if rec is None or "join_key" not in rec:  # nothing to derive from: any stored edge stays listed in relationships
        return None
    return {"from": result_id, "to": eid, "relationship": DERIVED_EDGE, "join_key": rec["join_key"]}


def verified_links(packet):
    """Every link between records of the packet that follow_relationship would establish, computed with exactly the rules
    of tools.RELATIONSHIPS (identifier joins only). Listed once, under the tool's relationship name, with the join value;
    for amount-bearing pairs both amounts and whether they agree; and the control results citing both records. Candidate
    relationships and contextual (date / free-text) edges are never listed here."""
    from .tools import RELATIONSHIPS
    recs = {r["evidence_id"]: r for r in packet["source_records"]}
    bank = [r for r in packet["source_records"] if r["file_id"] == "IN-09"]
    cited = {}
    for res in packet["control_results"]:
        for eid in res.get("evidence_ids") or []:
            cited.setdefault(eid, set()).add(res["result_id"])
    links, rules = [], {}
    for name, (src, field, tgt, how, label) in RELATIONSHIPS.items():
        for r in sorted((x for x in packet["source_records"] if x["file_id"] == src), key=lambda x: x["evidence_id"]):
            value = r["fields"].get(field) or ""
            if not value:
                continue
            if how == "pk":
                targets = [recs[f"{tgt}:{value}"]] if f"{tgt}:{value}" in recs else []
            else:  # same rule as EvidenceStore.bank_entries_by_reference
                acct = r["fields"].get("account_id")
                targets = [e for e in sorted(bank, key=lambda x: x["evidence_id"])
                           if e["fields"].get("account_id") == acct and value in (e["fields"].get("bank_reference"), e["fields"].get("end_to_end_ref"))]
            for t in targets:
                rules[name] = label
                links.append((name, r, t, value))
    out_n, in_n = {}, {}  # links per (relationship, source) and per (relationship, target)
    for name, r, t, _ in links:
        out_n[(name, r["evidence_id"])] = out_n.get((name, r["evidence_id"]), 0) + 1
        in_n[(name, t["evidence_id"])] = in_n.get((name, t["evidence_id"]), 0) + 1
    rows = []
    for name, r, t, value in links:
        amounts = None
        if name in COMPARED and out_n[(name, r["evidence_id"])] == 1 and in_n[(name, t["evidence_id"])] == 1:
            fa, ta = COMPARED[name]
            a, b = _signed(r, fa), _signed(t, ta)
            if a is not None and b is not None:
                amounts = [_fmt(a), _fmt(b), a == b]
        both = sorted(cited.get(r["evidence_id"], set()) & cited.get(t["evidence_id"], set()))
        rows.append([name, r["evidence_id"], t["evidence_id"], value, amounts, both or None])
    return {"rules": rules,
            "columns": ["relationship", "from", "to", "join_value", AMOUNTS_COLUMN, "control_results"],
            "rows": rows}


def _signed(record, amount_field):
    """The record's amount with the sign of its own direction field, or None (missing / unparsable amount, unknown direction).
    Never an absolute value."""
    from decimal import Decimal, InvalidOperation
    sign_field, signs = SIGNS.get(record.get("file_id"), (None, {}))
    sign = signs.get(record["fields"].get(sign_field)) if sign_field else None
    raw = record["fields"].get(amount_field)
    if sign is None or raw in (None, ""):
        return None
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return v * sign if v.is_finite() else None


def _fmt(v):
    return format(v, "f")


def _citation_classes(packet):
    candidates = {c["candidate_id"] for c in packet.get("candidate_relationships", [])}
    allowed = list(packet.get("allowed_citation_ids", []))
    return {"confirmed_finding_ids": [i for i in allowed if i not in candidates],
            "hypotheses_only_ids": [i for i in allowed if i in candidates]}


ORDER = "packet_order"  # a row's position in the stored packet's list (records, control results)


def _result_layout(control_results):
    """Control results with their stored position, in the view's layout order: (for_exception, result_id)."""
    return sorted((dict(r, **{ORDER: i}) for i, r in enumerate(control_results)),
                  key=lambda r: (r["for_exception"], r["result_id"], r[ORDER]))


def _derivation(results_in_layout, records):
    """[(result_id, evidence_id, edge, key)] in derivation order: every evidence_id of every result, in view layout order."""
    out = []
    for res in results_in_layout:
        for eid in res.get("evidence_ids") or []:  # DR-06: evidence_ids may be None
            e = _derived_edge(res["result_id"], eid, records)
            if e is not None:
                out.append((res["result_id"], eid, e, json.dumps(e, sort_keys=True)))
    return out


def _provenance(r):
    return tuple(json.dumps(r.get(k, MISSING), sort_keys=True) for k in PROVENANCE)


def _render(packet):
    records = {r["evidence_id"]: r for r in packet["source_records"]}
    provs = {}  # file_id -> distinct provenance tuples (DR-06: never collapsed to the first one)
    for r in packet["source_records"]:
        if any(r.get(k) == MISSING for k in PROVENANCE):
            raise ModelViewError("a packet value equals the model view's missing-key sentinel")
        provs.setdefault(r["file_id"], set()).add(_provenance(r))
    source_files, index = [], {}
    for fid in sorted(provs):
        for prov in sorted(provs[fid]):
            index[(fid, prov)] = len(source_files)
            values = [json.loads(v) for v in prov]
            source_files.append(dict({"file_id": fid}, **{k: v for k, v in zip(PROVENANCE, values) if v != MISSING}))
    by_file = {}
    for fid in sorted(provs):
        rows = []
        for i, r in sorted(enumerate(packet["source_records"]), key=lambda x: (x[1]["evidence_id"], x[0])):
            if r["file_id"] != fid:
                continue
            row = dict({k: v for k, v in r.items() if k not in ("fields", "file_id") + PROVENANCE},
                       **{f"field.{k}": v for k, v in r["fields"].items()}, **{ORDER: i})
            if len(provs[fid]) > 1:
                row["source_file_index"] = index[(fid, _provenance(r))]
            rows.append(row)
        by_file[fid] = _table(rows, ("evidence_id", "source_line", ORDER))
    results_layout = _result_layout(packet["control_results"])
    present = {json.dumps(e, sort_keys=True) for e in packet["relationships"]}
    derived, derived_seq, without_edge = set(), [], []
    for result_id, eid, e, key in _derivation(results_layout, records):
        if key in present:
            if key not in derived:
                derived.add(key)
                derived_seq.append(key)
        else:  # the edge is not derivable from evidence_ids for this pair (DR-07): listed, never invented
            without_edge.append([result_id, eid])
    kind = []  # per stored edge: D derived (re-created from evidence_ids), C contextual, K kept as listed
    for e in packet["relationships"]:
        key = json.dumps(e, sort_keys=True)
        kind.append("D" if key in derived else "C" if e["relationship"] in CONTEXTUAL_LABELS else "K")
    kept = [e for e, k in zip(packet["relationships"], kind) if k == "K"]
    contextual = [e for e, k in zip(packet["relationships"], kind) if k == "C"]
    d_slots = [derived_seq.index(json.dumps(e, sort_keys=True)) for e, k in zip(packet["relationships"], kind) if k == "D"]
    derived_order = None if d_slots == list(range(len(d_slots))) else d_slots  # duplicates make it explicit (DR-06)
    handled = {"packet_version", "packet_sha256", "pack_id", "pack_content_sha256", "conventions", "source_records", "relationships",
               "investigation_group", "candidate_relationships", "control_results", "conflicts", "searches", "missing_evidence",
               "retrieval_truncated", "related_exceptions", "investigation_route", "investigation_scope", "exception",
               "allowed_citation_ids"}
    extras = {k: packet[k] for k in sorted(packet) if k not in handled}  # e.g. a deterministic packet's rule version and pruning register
    view = {
        "model_view_version": MODEL_VIEW_VERSION,
        "reading_guide": READING_GUIDE,
        "packet_version": packet["packet_version"], "packet_sha256": packet["packet_sha256"],
        "pack_id": packet["pack_id"], "pack_content_sha256": packet["pack_content_sha256"],
        "conventions": packet["conventions"],
        # group-shared material first
        "source_files": source_files,
        "records_by_file": by_file,
        "verified_links": verified_links(packet),
        "relationships": kept,
        "contextual_associations_NOT_VERIFIED_JOINS": contextual,
        "evidence_ids_without_derivable_edge": without_edge,
        "relationship_order": "".join(kind),
        "derived_order": derived_order,
        "investigation_group": packet["investigation_group"],
        "candidate_relationships_HYPOTHESES_ONLY": packet["candidate_relationships"],
        "control_results": _table(results_layout, ("result_id", "evidence_ids", ORDER)),
        "conflicts": packet["conflicts"],
        "searches": packet["searches"],
        "missing_evidence": packet["missing_evidence"],
        "retrieval_truncated": packet["retrieval_truncated"],
        # exception-specific material last
        "related_exceptions": packet["related_exceptions"],
        "investigation_route": packet["investigation_route"],
        "investigation_scope": packet["investigation_scope"],
        "exception": packet["exception"],
        "citation_classes": _citation_classes(packet),
    }
    if extras:
        view["packet_extras"] = extras
    return view


def render_model_view(packet):
    """The model view (a dict; key order is significant and deterministic). Fail closed (DR-06): raises ModelViewError
    unless the view, read back exactly as it is sent (JSON), reconstructs the packet exactly. A lossy view is never
    returned, so it can never be sent."""
    try:
        view = _render(packet)
        back = reconstruct_packet(json.loads(json.dumps(view, ensure_ascii=False)))
    except ModelViewError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ModelViewError(f"model view cannot be rendered losslessly: {e.__class__.__name__}: {str(e)[:200]}") from e
    if back != packet:
        raise ModelViewError("model view does not reconstruct the packet exactly; nothing is sent")
    return view


def model_view_text(packet):
    """The exact text embedded in the request (compact JSON, insertion order, UTF-8 kept)."""
    return json.dumps(render_model_view(packet), ensure_ascii=False, separators=(",", ":"))


def model_view_sha256(packet):
    return hashlib.sha256(model_view_text(packet).encode("utf-8")).hexdigest()


def _in_stored_order(rows, what):
    """Rows carrying packet_order -> the rows in stored order, without packet_order. Fails closed unless the positions are
    exactly 0..n-1 (no gap, no duplicate)."""
    positions = sorted(r.get(ORDER) for r in rows) if all(isinstance(r.get(ORDER), int) for r in rows) else None
    if positions != list(range(len(rows))):
        raise ModelViewError(f"model view: {what} packet_order is not a permutation of 0..{len(rows) - 1}")
    out = [None] * len(rows)
    for r in rows:
        out[r[ORDER]] = {k: v for k, v in r.items() if k != ORDER}
    return out


def reconstruct_packet(view):
    """Exact inverse of render_model_view: the stored packet, every list in its stored order (model view 1.2). Raises
    ModelViewError (a ValueError) when the view's ordering or provenance data does not account for every row and edge
    (fail closed, never guess)."""
    entries = view["source_files"]
    per_file = {}
    for i, f in enumerate(entries):
        per_file.setdefault(f["file_id"], []).append(i)
    records = []
    for fid, t in view["records_by_file"].items():
        for row in _untable(t):
            idx = row.pop("source_file_index", None)
            if idx is None:
                if len(per_file.get(fid, [])) != 1:
                    raise ModelViewError(f"model view: {fid} has {len(per_file.get(fid, []))} provenance entries and the row names none")
                idx = per_file[fid][0]
            if not isinstance(idx, int) or not 0 <= idx < len(entries) or entries[idx]["file_id"] != fid:
                raise ModelViewError(f"model view: invalid source_file_index for {fid}")
            rec = dict({"file_id": fid}, **{k: entries[idx][k] for k in PROVENANCE if k in entries[idx]}, fields={})
            for k, v in row.items():
                if k.startswith("field."):
                    rec["fields"][k[len("field."):]] = v
                else:
                    rec[k] = v
            records.append(rec)
    records = _in_stored_order(records, "source record")
    by_id = {r.get("evidence_id"): r for r in records}
    results_layout = _untable(view["control_results"])  # the view's layout order, as rendered
    control_results = _in_stored_order(results_layout, "control result")
    skip = {tuple(x) for x in view["evidence_ids_without_derivable_edge"]}
    derived_seq, seen = [], set()
    for result_id, eid, e, key in _derivation(results_layout, by_id):
        if (result_id, eid) not in skip and key not in seen:
            seen.add(key)
            derived_seq.append(e)
    order, kept, contextual = view["relationship_order"], list(view["relationships"]), list(view["contextual_associations_NOT_VERIFIED_JOINS"])
    d_slots = view.get("derived_order") or list(range(order.count("D")))
    if (set(order) - set("DCK") or order.count("K") != len(kept) or order.count("C") != len(contextual)
            or order.count("D") != len(d_slots) or not all(isinstance(i, int) and 0 <= i < len(derived_seq) for i in d_slots)
            or set(d_slots) != set(range(len(derived_seq)))):
        raise ModelViewError("model view: relationship_order does not account for every kept, contextual and derived edge")
    it = {"K": iter(kept), "C": iter(contextual), "D": iter(derived_seq[i] for i in d_slots)}
    rels = [next(it[k]) for k in order]
    cc = view["citation_classes"]
    return {"packet_version": view["packet_version"], "packet_sha256": view["packet_sha256"], "pack_id": view["pack_id"],
            "pack_content_sha256": view["pack_content_sha256"], "conventions": view["conventions"], "source_records": records,
            "relationships": rels, "investigation_group": view["investigation_group"],
            "candidate_relationships": view["candidate_relationships_HYPOTHESES_ONLY"], "control_results": control_results,
            "conflicts": view["conflicts"], "searches": view["searches"], "missing_evidence": view["missing_evidence"],
            "retrieval_truncated": view["retrieval_truncated"], "related_exceptions": view["related_exceptions"],
            "investigation_route": view["investigation_route"], "investigation_scope": view["investigation_scope"],
            "exception": view["exception"],
            "allowed_citation_ids": sorted(cc["confirmed_finding_ids"] + cc["hypotheses_only_ids"]),
            **view.get("packet_extras", {})}
