"""Shared helpers for the renderer 3.0 tests (not a test module): building reviewed final packs for the regression matrix
offline (mocked provider HTTP layer, temporary folders), and the audit-integrity checks that every matrix case must pass.

audit_integrity(final, pack, pdf_bytes, html) returns a list of problems (empty = every check passed). Each check compares
the report with the stored deterministic pack or the final pack's own records, never with expectations written in the test."""
import hashlib
import io
import re
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from tests.final_pack_support import PACK, make_investigation, review_for, summary_investigator
from uc042lib.final_pack import (AnalystReview, GenerationInfo, Selection, assemble_final_pack, assemble_preview,
                                 build_review_snapshot, generate_closing_summary, load_pack, not_required_closing_summary,
                                 render_html, render_pdf, unavailable_closing_summary)
from uc042lib.final_pack.report import block_texts, build_report
from uc042lib.final_pack.report_v3 import classify_limitations, money, unformat
from uc042lib.final_pack.sources import list_investigations, output_of
from uc042lib.final_pack.summary import COMPLIANCE_PATTERNS, _asserts
from uc042lib.investigation.validation import RESOLUTION_PATTERNS

ROOT = Path(__file__).resolve().parent.parent
SCENARIO_A_ROOT = ROOT / "tests" / "fixtures" / "scenario_a_packs"
SCENARIO_A_PACK = "PACK-CASE-PER-2026-09-36987c6261a5"
REVIEWER = {"user_id": "analyst-7", "display_name": "Matrix Analyst"}


def pdf_text(data):
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def norm(s):
    return "".join(str(s).split())


def pdf_body(data, final):
    """The PDF's text without the running header, footer and page numbers (normalised)."""
    m = final["metadata"]
    header = norm(f"UC-042 Final Audit Pack - {m['final_pack_id']} - {m['reporting_period']['period_id']}")
    footer = norm(f"Synthetic data - not a compliance opinion - content {final['final_content_sha256'][:12]}"
                  + (" - PREVIEW, not a final audit pack" if m["status"] == "PREVIEW" else ""))
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        t = norm(p.extract_text())
        t = re.sub(r"Page\d+of\d+", "", t.replace(header, "").replace(footer, ""))
        out.append(t)
    return "".join(out)


def findings_sha(inv_root, pack, exc, inv_id):
    info = next(i for i in list_investigations(pack, exc, inv_root)["published"] if i["investigation_id"] == inv_id)
    return hashlib.sha256((Path(info["path"]) / "findings.json").read_bytes()).hexdigest()


def build(scenario, plan, inv_root, summary="ai", final=False, packs_root=None, pack_id=None, summary_edit=None):
    """A reviewed preview (or GENERATED final pack) of `scenario`. plan: {exception_id: "ACCEPT" | "REJECT" |
    "NOT_INVESTIGATED" | ("EXCLUDED", reason) | ("ACCEPT", comment) | ("REJECT", reason, comment)}; exceptions not named are
    NOT_INVESTIGATED. summary: "ai" (validated AI summary via the mocked HTTP layer), "not_required", "unavailable" or
    "invalid" (refused AI output, recorded as UNAVAILABLE with its findings)."""
    pack_id = pack_id or PACK[scenario]
    pack = load_pack(pack_id, packs_root)
    selections, reviews = [], {}
    for x in pack["exception_register"]["exceptions"]:
        eid = x["exception_id"]
        p = plan.get(eid, "NOT_INVESTIGATED")
        p = p if isinstance(p, tuple) else (p,)
        if p[0] == "NOT_INVESTIGATED":
            selections.append(Selection(exception_id=eid, inclusion="NOT_INVESTIGATED"))
        elif p[0] == "EXCLUDED":
            selections.append(Selection(exception_id=eid, inclusion="EXCLUDED_BY_ANALYST", reason=p[1]))
        else:
            inv_id = make_investigation(scenario, eid, inv_root)
            selections.append(Selection(exception_id=eid, inclusion="INCLUDED", investigation_id=inv_id))
            decision = p[0]
            reviews[inv_id] = AnalystReview(
                analyst_review_id=f"AR-{eid}", investigation_id=inv_id, exception_id=eid, decision=decision,
                findings_sha256=findings_sha(inv_root, pack, eid, inv_id),
                comment=(p[2] if decision == "REJECT" and len(p) > 2 else p[1] if decision == "ACCEPT" and len(p) > 1 else ""),
                rejection_reason=(p[1] if decision == "REJECT" and len(p) > 1 else
                                  "The AI treated the difference as unexplained; the analyst's own review disagrees." if decision == "REJECT" else ""),
                reviewer=REVIEWER, decided_at="2026-11-18T09:51:00+00:00")
    snap = build_review_snapshot(pack_id, selections, packs_root=packs_root, investigations_root=inv_root, analyst_reviews=reviews)
    if summary == "not_required":
        s = not_required_closing_summary(snap)
    elif summary == "unavailable":
        s = unavailable_closing_summary(snap, "closing summary generation failed (timeout)")
    elif summary == "invalid":
        s = unavailable_closing_summary(snap, "closing summary generation failed (invalid_summary)",
                                        ["suggested_next_steps[0]: references not in the supplied input: ['']"])
    else:
        s = generate_closing_summary(snap, summary_investigator(snap, summary_edit)[0])
    if not final:
        return assemble_preview(snap, s), pack, snap
    review = review_for(snap, s, reviewer=REVIEWER, acknowledged_summary_unavailable=s.status == "UNAVAILABLE")
    return assemble_final_pack(snap, s, review, GenerationInfo(generated_at="2026-11-18T10:00:00+00:00")), pack, snap


def section_blocks(blocks, anchor):
    out, on = [], False
    for b in blocks:
        if b["type"] == "section":
            on = b["anchor"] == anchor
            continue
        if on and b["type"] != "footer":
            out.append(b)
    return out


def _cells(blocks, header):
    """(row, column value) of every table in blocks whose headers include `header`."""
    for b in blocks:
        if b["type"] == "table" and header in b["headers"]:
            j = b["headers"].index(header)
            for r in b["rows"]:
                yield r, r[j]


def _money_ok(shown, stored, ccy):
    if stored in (None, ""):
        return shown == "-"
    try:
        Decimal(str(stored))
    except Exception:
        return shown == str(stored)
    back = unformat(shown, ccy)
    return Decimal(back) == Decimal(str(stored)) and back.lstrip("-").split(".")[-1:] == str(stored).lstrip("+-").split(".")[-1:] \
        if "." in str(stored) else Decimal(back) == Decimal(str(stored))


def audit_integrity(final, pack, pdf=None, html=None, snapshot=None):
    """Phase 5 audit-integrity checks 1-13 (14-15 are publication/verification tests). Returns problems."""
    problems = []
    blocks = build_report(final)
    texts = block_texts(blocks)
    allt = "\n".join(texts)
    co = pack["executive_summary"]["control_outcomes"]
    g = final["outcome_summary"]["figures"]
    # 1 control-result counts
    if (g["control_results_total"], g["control_results_by_outcome"], g["checks_total"]) != \
            (co["total_results"], co["by_outcome"], co["check_types"]):
        problems.append("1: outcome figures differ from the engine's control outcomes")
    if sum(co["by_outcome"].values()) != co["total_results"]:
        problems.append("1: engine by_outcome does not add up (source data)")
    if f"{co['by_outcome'].get('PASS', 0):,} of {co['total_results']:,} control results passed across {co['check_types']:,} checks." not in allt:
        problems.append("1: headline count sentence missing")
    if len(final["reconciliation_results"]["control_checks"]) != len(pack["control_register"]):
        problems.append("1: control checks listed differ from the control register")
    for c, row in zip(pack["control_register"], [r for r, _ in _cells(section_blocks(blocks, "details"), "Outcome (engine)")]):
        if row[0] != c["check_id"] or row[3] != c["check_outcome"]:
            problems.append(f"1: control check row {row[0]} differs from the register")
    # 2 exceptions: each exactly once, same as the pack, UNRESOLVED
    ids = [x["exception_id"] for x in pack["exception_register"]["exceptions"]]
    heads = [b["heading"].split(" - ")[0] for b in blocks if b["type"] == "item" and b["kind"] == "unresolved"]
    if heads != ids:
        problems.append(f"2: exception items {heads} != register {ids}")
    if any(b["badge"] != "UNRESOLVED" for b in blocks if b["type"] == "item" and b["kind"] == "unresolved"):
        problems.append("2: an exception is not labelled UNRESOLVED")
    if bool(ids) != any(b["type"] == "section" and b["anchor"] == "exceptions" for b in blocks):
        problems.append("2: exceptions section shown/omitted wrongly")
    # 3 financial figures: every formatted amount converts back to the stored value
    r = final["reconciliation_results"]
    det = section_blocks(blocks, "details")
    tables = [b for b in det if b["type"] == "table"]
    internal = next(b for b in tables if b["headers"][:3] == ["Date", "Ccy", "Requirement"])
    for row, src in zip(internal["rows"], r["internal_by_currency_day"]):
        for j, k in ((2, "requirement"), (3, "resource"), (4, "difference"), (5, "difference_reported")):
            if not _money_ok(row[j], src[k], src["currency"]):
                problems.append(f"3: internal {src['date']} {k}: shown {row[j]!r} stored {src[k]!r}")
    external = next(b for b in tables if b["headers"][:3] == ["Date", "Account", "Ledger"])
    for row, src in zip(external["rows"], r["external_by_account_day"]):
        for j, k in ((2, "ledger_balance"), (3, "bank_balance"), (4, "difference"), (5, "difference_reported")):
            if not _money_ok(row[j], src[k], src["currency"]):
                problems.append(f"3: external {src['date']} {src['account_id']} {k}: shown {row[j]!r} stored {src[k]!r}")
    batches = next(b for b in tables if b["headers"][0] == "Batch")
    for row, src in zip(batches["rows"], r["settlements"]):
        if not _money_ok(row[5], src["net_amount_reported"], src["currency"]):
            problems.append(f"3: batch {src['batch_id']}: shown {row[5]!r} stored {src['net_amount_reported']!r}")
    if (len(internal["rows"]), len(external["rows"]), len(batches["rows"])) != \
            (len(r["internal_by_currency_day"]), len(r["external_by_account_day"]), len(r["settlements"])):
        problems.append("3: a daily or settlement row is missing")
    for e in final["exception_register"]:
        x = e["exception"]
        item = next(b for b in blocks if b["type"] == "item" and b["heading"].startswith(x["exception_id"] + " - "))
        shown = dict(item["fields"])["Amount (engine)"]
        if x["amount"] != "" and not _money_ok(shown, x["amount"], x["currency"]):
            problems.append(f"3: {x['exception_id']} amount shown {shown!r} stored {x['amount']!r}")
    # 4 citations resolve to the evidence index (and the index to the ledger: validate.py FV6 at assembly)
    for inv in final["ai_investigations"]:
        for fnd in inv["confirmed_findings"]:
            for eid in fnd["evidence_refs"] + fnd["supporting_records"]:
                if eid in final["evidence_index"]:
                    e = final["evidence_index"][eid]
                    if f"{eid} ({e['source_file']}:{e['source_line']})" not in allt:
                        problems.append(f"4: citation {eid} not shown with its source line")
    # 5/6 source inventory: every file, same identity and availability
    inv_rows = [row for row, _ in _cells(section_blocks(blocks, "evidence"), "Availability")]
    files = final["source_inventory"]["files"]
    if [(r_[0], r_[1], r_[5]) for r_ in inv_rows] != [(x["evidence_id"], x["source_file"], x["availability"]) for x in files]:
        problems.append("5/6: source inventory rows differ from the source inventory")
    if [x["evidence_id"] for x in files] != [x["evidence_id"] for x in pack["evidence_register"]["files"]]:
        problems.append("6: a source file of the pack is missing from the final pack")
    hashes = {row[0]: row[2] for row, _ in _cells(section_blocks(blocks, "appendix"), "SHA-256")}
    if hashes != {x["evidence_id"]: x["sha256"] for x in files}:
        problems.append("5: appendix hashes differ from the source inventory")
    # 7 missing evidence never reported as present
    items = pack["missing_evidence_register"]["items"]
    if items and ("The engine recorded no missing evidence." in allt or "No required evidence is missing" in allt):
        problems.append("7: missing evidence reported as absent")
    if items and not all(i["item_id"] in allt for i in items):
        problems.append("7: a missing-evidence item is not shown")
    # 8 hypotheses never shown as confirmed observations
    hyp = {h["ref"] for inv in final["ai_investigations"] for h in inv["hypotheses"]}
    for b in blocks:
        if b["type"] == "item" and b["kind"] == "confirmed" and b["heading"].split(" - ")[0] in hyp:
            problems.append(f"8: hypothesis {b['heading']} shown as a confirmed observation")
        if b["type"] == "item" and b["kind"] == "hypothesis" and "NOT ESTABLISHED" not in b["badge"]:
            problems.append("8: a hypothesis is not labelled NOT ESTABLISHED")
    # 9 AI content never inside the deterministic sections (1-5)
    ai_texts = [inv["assessment"]["summary"] for inv in final["ai_investigations"]] + \
               [f["description"] for inv in final["ai_investigations"] for f in inv["confirmed_findings"]]
    for anchor in ("outcome", "overview", "accounts", "details", "evidence"):
        det_text = "\n".join(block_texts(section_blocks(blocks, anchor)))
        for t in ai_texts:
            if len(t) > 30 and t in det_text:
                problems.append(f"9: AI text appears in deterministic section {anchor}")
    # 10 analyst decisions: attributed exactly as recorded
    for e in final["exception_register"]:
        rv = e["investigation"].get("analyst_review")
        if not rv:
            continue
        item = next((b for b in section_blocks(blocks, "review") if b["type"] == "item" and b["heading"].startswith(e["exception"]["exception_id"])), None)
        if item is None:
            problems.append(f"10: no decision shown for {e['exception']['exception_id']}")
            continue
        f_ = dict(item["fields"])
        if f_["Reviewer"] != f"{rv['reviewer']['display_name']} ({rv['reviewer']['user_id']})" or f_["Reviewed at"] != rv["decided_at"]:
            problems.append("10: decision attributed wrongly")
        if rv["decision"] == "REJECT" and f_.get("Reason for rejection (exactly as recorded by the analyst)") != rv["rejection_reason"]:
            problems.append("10: rejection reason not shown exactly")
    if final["human_review"].get("decision") == "GENERATE":
        kv = next(b for b in section_blocks(blocks, "review") if b["type"] == "kv")
        if dict(kv["pairs"])["Reviewer"] != f"{final['human_review']['reviewer']['display_name']} ({final['human_review']['reviewer']['user_id']})":
            problems.append("10: generation decision attributed wrongly")
    # 11 rejected investigations: never shown as accepted, no AI text anywhere
    rejected = [e["investigation"]["investigation_id"] for e in final["exception_register"]
                if (e["investigation"].get("analyst_review") or {}).get("decision") == "REJECT"]
    for iid in rejected:
        if any(i["investigation_id"] == iid for i in final["ai_investigations"]):
            problems.append(f"11: rejected {iid} is in ai_investigations")
        if any(b["type"] == "item" and b["kind"] == "accepted" and iid in str(b["fields"]) for b in blocks):
            problems.append(f"11: rejected {iid} shown as accepted")
        if snapshot is not None:
            out = output_of(snapshot.bundles[iid])
            passages = [out.investigation_summary] + [x.claim for x in out.confirmed_findings]
            accepted_text = "\n".join(str(output_of(snapshot.bundles[a]).model_dump()) for a in snapshot.accepted_ids)
            for p in passages:
                if len(p) >= 40 and p in allt and p not in accepted_text and p not in str(pack):
                    problems.append(f"11: rejected AI text appears in the report: {p[:60]!r}")
    # 12/13 no resolution, compliance or certification claim in text the report composes (stored statements excluded)
    stored = set(final["statements"].values()) | {final["human_review"].get("acknowledgement_text", "")}
    ai_own = set(ai_texts)
    for t in texts:
        if t in stored or t in ai_own or t.startswith("Reason for rejection"):
            continue
        if any(_asserts(p, t) for p in RESOLUTION_PATTERNS):
            problems.append(f"12: resolution claim: {t[:90]!r}")
        if any(_asserts(p, t) for p in COMPLIANCE_PATTERNS):
            problems.append(f"13: compliance/opinion claim: {t[:90]!r}")
    # limitations: each exactly once, main body or appendix
    main, app = classify_limitations(final)
    shown = [t for _, t in main] + [t for _, t in app]
    if sorted(shown) != sorted(x["text"] for x in final["limitations"]):
        problems.append("limitations: not every limitation is shown exactly once")
    for x in final["limitations"]:
        if texts.count(x["text"]) != 1:
            problems.append(f"limitations: {x['text'][:60]!r} shown {texts.count(x['text'])} times")
    # renderers agree with the blocks
    if pdf is not None:
        pt = pdf_body(pdf, final)
        # an item heading repeats on a continuation page (render_pdf repeatRows): also compare with every heading removed
        stripped = pt
        for b in blocks:
            if b["type"] == "item":
                stripped = stripped.replace(norm(f"{b['heading']}   [{b['badge']}]"), "")
        pt = pt + "\n" + stripped
        for t in texts:
            # A row split across pages has the page footer/header and the repeated item heading inside it: a long value is
            # checked piece by piece ("; "-separated), every piece must be in the PDF.
            if norm(t) not in pt and not all(norm(p) in pt for p in re.split(r"[;,] ", str(t)) if p.strip()):
                problems.append(f"pdf: missing text {t[:70]!r}")
                break
    if html is not None:
        from html import escape
        for t in texts:
            if escape(str(t)) not in html:
                problems.append(f"html: missing text {t[:70]!r}")
                break
    return problems


def render_all(final):
    return render_pdf(final), render_html(final)


__all__ = ["build", "audit_integrity", "render_all", "section_blocks", "pdf_text", "norm", "money", "REVIEWER", "SCENARIO_A_ROOT",
           "SCENARIO_A_PACK", "re"]
