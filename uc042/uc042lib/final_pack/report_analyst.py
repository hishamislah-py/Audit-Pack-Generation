"""Analyst edition of the final audit pack (renderer uc042-final-report-renderer/4.0-analyst), 23 Nov 2026.

An ADDITIONAL, shorter PDF drawn from a stored final pack; the existing renderer's output stays the full technical report,
byte for byte unchanged. Layout per the owner-approved reference FAP-CASE-PER-2026-09_analyst_edition.pdf:
header, 1 Outcome, 2 Exceptions, 3 Reconciliation results, 4 Evidence received, 5 Review and sign-off, Appendix.

Data rules (non-negotiable):
* every value comes from stored records: the final pack; the deterministic source pack it pins by content SHA-256 (the
  engine's computed / reported values and notes, verified before use); the Ringfence provenance supplement written with
  the pack (original filenames, package, mapping). Nothing is recalculated except counts and per-area sums of stored
  result counts, which are labelled as such;
* analyst reasons and comments and the accepted AI assessment are reproduced verbatim (typos included);
* a rejected investigation's AI content never appears; the AI closing summary, limitations section, key points,
  observations, hypotheses, evidence-gap blocks, daily tables, settlement rows and record dumps are not rendered;
* candidate relationships are always labelled unverified; next steps always "not yet done";
* an element without a stored source is omitted and logged (build_model(...)["omitted"]); nothing is invented.
No AI request is made. The grouping of checks into areas and the plain-English check titles are fixed presentation
tables of this renderer (codes are always shown next to them)."""
from __future__ import annotations

import io
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .render_pdf import PdfGlyphError, _unicode_fonts
from .statement import build_statement

ANALYST_RENDERER_VERSION = "uc042-final-report-renderer/4.0-analyst"

# ------------------------------------------------------------------------------------------------ palette (navy / grey)
NAVY = colors.HexColor("#1f3550")
INK = colors.HexColor("#18212c")
INK2 = colors.HexColor("#46505c")
LINE = colors.HexColor("#d6dbe1")
PANEL = colors.HexColor("#f3f5f8")
PANEL2 = colors.HexColor("#f7f8fa")
WHITE = colors.white
PALETTE_HEX = ("#1f3550", "#18212c", "#46505c", "#d6dbe1", "#f3f5f8", "#f7f8fa", "#ffffff")

# ------------------------------------------------------------------------------------------------ presentation tables
CHECK_TITLES = {  # check code -> (card title, at-a-glance sentence title)
    "C11-BATCH-ARITH": ("Settlement batch arithmetic", "Settlement batch does not reconcile to its lines."),
    "C11-BATCH-BANK": ("Settlement batch against bank", "Settlement batch does not match the bank."),
    "C11-TXN-LINE": ("Settlement line against transaction", "Settlement line does not match its transaction."),
    "C11-BANK-ENTRY": ("Settlement bank entry", "Settlement bank entry does not match."),
    "CBAL-ROLLFWD": ("Client balance roll-forward", "Client balance does not roll forward."),
    "CBAL-NONNEG": ("Client balance non-negative", "A client balance is negative."),
    "C04-REQUIREMENT": ("Safeguarding requirement", "The safeguarding requirement does not agree."),
    "C05-RESOURCE": ("Safeguarding resource", "The safeguarding resource does not agree."),
    "C06-DIFFERENCE": ("Internal reconciliation difference", "The internal reconciliation shows a difference."),
    "FUND-TOPUP": ("Funding top-up", "A required top-up cannot be confirmed."),
    "C07-BANK-EVIDENCE": ("Bank evidence", "Bank evidence is missing or does not agree."),
    "RC2-LEDGER": ("Firm ledger balance", "The firm's ledger balance does not agree."),
    "C08-DIFFERENCE": ("External reconciliation difference", "The external reconciliation shows a difference."),
    "BC-VS-EOD": ("Bank confirmation against statement", "The bank confirmation and statement differ."),
    "CASH-BANK-LINK": ("Cash book to bank link", "A cash-book entry has no matching bank entry."),
    "BANK-CASH-LINK": ("Bank to cash book link", "A bank entry has no matching cash-book entry."),
    "RC4-DIRECT": ("Client transaction against bank", "A client transaction does not match the bank."),
    "C09-ALLOCATION": ("Unallocated receipts", "An unallocated receipt is outstanding."),
    "C12-REFUND": ("Refunds", "A refund does not reconcile."),
    "C13-CURRENCY": ("Currency", "A currency check failed."),
    "DQ22-CONTINUITY": ("Statement continuity", "A bank statement does not continue from the previous day."),
    "DQ23-STATEMENT": ("Statement completeness", "A bank statement is incomplete."),
    "C14-COVER": ("Evidence coverage", "Required evidence does not cover the day."),
    "C07-COVER": ("Bank evidence coverage", "Bank evidence does not cover the day."),
    "C01-COVER": ("Internal reconciliation coverage", "An internal reconciliation is missing."),
    "DUPLICATE_CASHBOOK_ENTRY": ("Duplicate cash-book entry", "The same cash-book entry is recorded twice."),
    "BANK_LEDGER_DIFFERENCE": ("Bank and ledger difference", "The bank and the firm's ledger differ."),
    "INTERNAL_DIFFERENCE": ("Internal reconciliation difference", "The internal reconciliation shows a difference."),
    "MISSING_BANK_EVIDENCE": ("Missing bank evidence", "Bank evidence is missing."),
}
AREAS = [
    ("Data quality and completeness", ["V01-SCHEMA", "V01-PDF", "C14-COVER", "DQ23-STATEMENT", "DQ22-CONTINUITY"]),
    ("Reconciliation point", ["C03-POLICY", "C03-POINT"]),
    ("Internal reconciliation and client balances", ["C01-COVER", "C04-REQUIREMENT", "C05-RESOURCE", "C06-DIFFERENCE",
                                                     "FUND-TOPUP", "CBAL-NONNEG", "CBAL-ROLLFWD"]),
    ("External reconciliation", ["C07-COVER", "BC-VS-EOD", "C07-BANK-EVIDENCE", "RC2-LEDGER", "C08-DIFFERENCE",
                                 "CASH-BANK-LINK", "BANK-CASH-LINK"]),
    ("Settlement", ["C11-BATCH-ARITH", "C11-BATCH-BANK", "C11-TXN-LINE", "C11-BANK-ENTRY"]),
    ("Receipts, refunds and currency", ["RC4-DIRECT", "C09-ALLOCATION", "C12-REFUND", "C13-CURRENCY"]),
    ("Designation, governance and records", ["C10-DESIGNATION", "C16-GOVERNANCE", "C16-RETURN", "DISC-LOG"]),
]
STATUS_WORDS = {"CLEAN": "Clean", "EXCEPTIONS_OPEN": "Exceptions open", "EVIDENCE_INCOMPLETE": "Evidence incomplete"}
ASSESSMENT_WORDS = {"EVIDENCE_SUFFICIENT": "evidence sufficient", "PARTIALLY_SUFFICIENT": "partially sufficient",
                    "INSUFFICIENT_EVIDENCE": "insufficient evidence", "CONFLICTING_EVIDENCE": "conflicting evidence"}
CCY = {"GBP": "£", "EUR": "€", "USD": "$"}
REJECTED_TEXT = ("Not reported. The analyst rejected this investigation, so its AI content is excluded from this pack; the "
                 "original is kept unchanged in the investigation record.")
UNRESOLVED_LINE = ("Every exception remains UNRESOLVED. Neither an AI investigation, the analyst's decision on it, nor "
                   "generating this pack resolves an exception.")
BANNER = ("ILLUSTRATIVE SYNTHETIC DATA (decision D6). Deterministic checks of synthetic evidence — not an audit opinion or "
          "compliance certification; does not establish operational correctness or the cause of any exception.")
FOOTER = "ILLUSTRATIVE SYNTHETIC DATA · not an audit opinion or compliance certification · analyst edition of the generated report"
CLOSING_NOTE = ("Source-file hashes, engine fingerprints, cited source records, the full AI investigation and all daily tables "
                "are in the generated technical report for this pack. Every figure traces to its source file through the "
                "engine's result IDs and those hashes.")


# ------------------------------------------------------------------------------------------------ formatting helpers
def _num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def money(v, ccy=None):
    """Stored amount with currency symbol and thousands separators; digits unchanged (no rounding beyond the stored 2dp)."""
    s = str(v).strip() if v is not None else ""
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    neg, s = s.startswith("-"), s.lstrip("-")
    whole, _, frac = s.partition(".")
    whole = f"{int(whole):,}"
    sym = CCY.get(ccy or "", (ccy + " ") if ccy else "")
    return ("-" if neg else "") + sym + whole + ("." + frac if frac else "")


def day_long(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d.day} {d:%B %Y}"


def day_short(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d.day} {d:%b %Y}"


def day_noyear(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d.day} {d:%b}"


def when(iso, seconds=True):
    """'23 Nov 2026, 10:29:34 UTC' from a stored ISO timestamp (stored as UTC +00:00)."""
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d:%b %Y}, {d:%H:%M:%S}" if seconds else f"{d.day} {d:%b %Y}, {d:%H:%M}"


def human(code):
    return str(code or "").replace("_", " ").lower().capitalize()


def _lines(evidence):
    """'IN-12:settlement_batches_2026-09.csv#L43; IN-13:x.csv#L199-L204' -> 'settlement_batches_2026-09.csv line 43 · ...'."""
    files = {}
    for part in [p.strip() for p in str(evidence or "").split(";") if p.strip()]:
        m = re.match(r"(?:IN-\d+:)?([^#]+)#L(\d+)(?:-L(\d+))?$", part)
        if not m:
            files.setdefault(part, [])
            continue
        files.setdefault(m.group(1), []).append(m.group(2) if not m.group(3) else f"{m.group(2)}–{m.group(3)}")
    out = []
    for f, ls in files.items():
        if not ls:
            out.append(f)
        elif len(ls) == 1 and "–" not in ls[0]:
            out.append(f"{f} line {ls[0]}")
        else:
            out.append(f"{f} lines {', '.join(ls)}")
    return " · ".join(out)


# ------------------------------------------------------------------------------------------------ model
def build_model(final, provenance=None, source_pack=None):
    """Everything the analyst edition shows, as plain data, plus the list of elements omitted for lack of a stored source.
    source_pack must be the verified deterministic pack the final pack pins (see verified_source_pack)."""
    omitted = []
    m, o = final["metadata"], final["outcome_summary"]
    fig = o["figures"]
    rr = final["reconciliation_results"]
    period = m["reporting_period"]
    month = datetime.strptime(period["start"], "%Y-%m-%d")
    status_code = fig.get("engine_case_status") or final["executive_summary"]["deterministic"]["engine_case_status"]
    exceptions = final["exception_register"]
    inv_by_id = {i["investigation_id"]: i for i in final.get("ai_investigations") or []}
    results = {}
    if source_pack is not None:
        for c in source_pack.get("control_register") or []:
            for r in c.get("results") or []:
                results[r["result_id"]] = r
    else:
        omitted.append("engine computed/reported values and notes: the deterministic source pack was not supplied")
    settle = {s["batch_id"]: s for s in rr.get("settlements") or []}
    ev_index = final.get("evidence_index") or {}

    start, end = datetime.strptime(period["start"], "%Y-%m-%d"), datetime.strptime(period["end"], "%Y-%m-%d")
    preview = m.get("status") == "PREVIEW"
    header = {
        "kicker": "UC-042 Safeguarding reconciliation · Monthly audit pack · Analyst edition",
        "title": f"{month:%B %Y} — {STATUS_WORDS.get(status_code, human(status_code))}" + (" (preview)" if preview else ""),
        "subline": (f"Reporting period {start.day}–{end.day} {end:%B %Y} · {m['reconciliation_days_count']} reconciliation days · "
                    f"Final pack {m['final_pack_id']}, version {m['version']} · generated {when(m['generated_at'], False)} UTC"),
        "banner": (("PREVIEW — not a final audit pack. No decision to generate the final audit pack has been recorded. ")
                   if preview else "") + BANNER,
        "running": f"UC-042 Monthly Audit Pack · {month:%B %Y} · Analyst edition",
        "running_right": f"Final pack {m['final_pack_id']}",
    }

    # ---- per-exception facts (engine only)
    def ccy_of(scope, ex):
        mm_ = re.search(r"\b(GBP|EUR|USD|CHF)\b", scope or "")
        return (mm_.group(1) if mm_ else None) or ex.get("currency") or None

    def prev_snapshot(client, ccy, date):
        best = None
        for k, rec in ev_index.items():
            f = rec.get("fields") or {}
            if rec.get("file_id") == "IN-03" and f.get("client_id") == client and f.get("currency") == ccy \
                    and str(f.get("recon_date", "")) < date and (best is None or f["recon_date"] > best["recon_date"]):
                best = f
        return best

    cards, glance = [], []
    # group investigations (24 Nov 2026): one AI investigation on a group's lead covers its other exceptions, and the
    # analyst decides once for the group. The Ringfence provenance supplement records which exceptions it covers.
    row_by_id = {r["exception"]["exception_id"]: r for r in exceptions}
    covered_by, covers_of = {}, {}
    for g in (provenance or {}).get("group_investigations") or []:
        lead_inv = (row_by_id.get(g.get("lead_exception_id")) or {}).get("investigation") or {}
        if lead_inv.get("investigation_id") != g.get("investigation_id") or lead_inv.get("inclusion") != "INCLUDED":
            omitted.append(f"group investigation {g.get('investigation_id')}: not the included investigation of "
                           f"{g.get('lead_exception_id')}; its coverage is not shown")
            continue
        covers_of[g["lead_exception_id"]] = list(g.get("covers") or [])
        for x in g.get("covers") or []:
            covered_by[x] = g
    for row in exceptions:
        ex, inv = row["exception"], row.get("investigation") or {}
        check = ex.get("category") or str(ex.get("root_cause", "")).split("|")[0]
        titles = CHECK_TITLES.get(check)
        if not titles:
            if re.fullmatch(r"[A-Z0-9_-]+", check or ""):
                omitted.append(f"{ex['exception_id']}: no plain-English title for check {check}; the code is shown")
            titles = (check, f"{check}.")              # the engine's category is already plain English
        scope = str(ex.get("root_cause", "")).split("|", 1)[1] if "|" in str(ex.get("root_cause", "")) else ""
        res = [results[i] for i in ex.get("affected_result_ids") or [] if i in results]
        r0 = res[0] if res else {}
        ccy = ccy_of(scope, ex)
        rows, sentence = [], ""
        date = (re.search(r"\d{4}-\d{2}-\d{2}", scope) or re.search(r"\d{4}-\d{2}-\d{2}", r0.get("scope", "")) or [None])[0]
        if check.startswith("C11-") and scope in settle:
            s = settle[scope]
            ccy = s.get("currency") or ccy
            date = s.get("settlement_date") or date
            rows.append(("Batch", f"{scope} · {str(s.get('counterparty_type', '')).lower()} settlement · {s.get('account_id')} · "
                                  f"{s.get('currency')} · {day_short(s['settlement_date'])} · net reported "
                                  f"{money(s.get('net_amount_reported'), s.get('currency'))}"))
            rows.append(("Result", f"Batch lines {s.get('lines_outcome')} (bank matching {s.get('bank_outcome')}). Affected result: "
                                   f"{' · '.join(ex.get('affected_result_ids') or [])}"))
            if r0.get("note"):
                rows.append(("Detail", r0["note"] + "."))
            sentence = (f"{str(s.get('counterparty_type', '')).capitalize()} batch {scope} ({s.get('account_id')})"
                        + (f": {r0['note']}." if r0.get("note") else "."))
        elif check == "CBAL-ROLLFWD" and re.match(r"([A-Z]{3})/(\S+) (\d{4}-\d{2}-\d{2})", scope):
            c3, client, date = re.match(r"([A-Z]{3})/(\S+) (\d{4}-\d{2}-\d{2})", scope).groups()
            ccy = c3
            rows.append(("Scope", f"Client {client} · {c3} · {day_short(date)}"))
            if r0.get("computed") and r0.get("reported"):
                prev = prev_snapshot(client, c3, date)
                rows.append(("Result", f"{r0.get('outcome', 'FAIL')} — engine roll-forward {money(r0['computed'], c3)}; recorded "
                                       f"17:00 snapshot {money(r0['reported'], c3)}"
                                       + (f" (previous snapshot, {day_noyear(prev['recon_date'])}: {money(prev['balance'], c3)})"
                                          if prev and prev.get("balance") else "")))
                sentence = (f"Client {client} ({c3}), {day_noyear(date)}: engine roll-forward {money(r0['computed'], c3)} "
                            f"against the recorded 17:00 snapshot {money(r0['reported'], c3)}.")
            else:
                omitted.append(f"{ex['exception_id']}: engine roll-forward values not available")
        else:
            if scope:
                rows.append(("Scope", scope))
            if r0:
                vals = (f"engine computed {money(r0['computed'], ccy)}; reported {money(r0['reported'], ccy)}"
                        if r0.get("computed") not in (None, "") and r0.get("reported") not in (None, "") else "")
                rows.append(("Result", " — ".join(x for x in (r0.get("outcome", ""), vals) if x)))
                if r0.get("note"):
                    rows.append(("Detail", r0["note"] + ("" if r0["note"].endswith(".") else ".")))
                sentence = (f"{scope}: {vals}." if vals else f"{scope}.") if scope else (vals + "." if vals else "")
            elif scope:
                sentence = f"{scope}."
        src = _lines(ex.get("evidence") or r0.get("evidence_refs"))
        if src:
            rows.append(("Source evidence", src))
        if ex.get("review_status"):
            rows.append(("Review status", human(ex["review_status"])))
        # ---- AI investigation and analyst decision
        ar, iid = inv.get("analyst_review") or {}, inv.get("investigation_id")
        ai_rows, ai_label = [], "Not investigated"
        g = covered_by.get(ex["exception_id"]) if not iid or inv.get("inclusion") != "INCLUDED" else None
        if g:
            lead = g["lead_exception_id"]
            lar = ((row_by_id[lead].get("investigation") or {}).get("analyst_review")) or {}
            ai_rows.append(("Investigation", f"Covered by the group investigation {g['investigation_id']} on {lead}: one AI "
                                             "investigation and one analyst decision for the whole group (see " + lead + ")."))
            if lar.get("decision") in ("ACCEPT", "REJECT"):
                ai_label = "Accepted" if lar["decision"] == "ACCEPT" else "Rejected"
                ai_rows.append(("Analyst decision", (f"TAG:{ai_label}", f"for the group, on {lead} · "
                                                     f"{lar['reviewer']['display_name']} · {when(lar['decided_at'])} UTC")))
            else:
                ai_rows.append(("Analyst decision", "No analyst decision is recorded for the group investigation."))
        elif not iid or inv.get("inclusion") != "INCLUDED":
            ai_rows.append(("Investigation", "No AI investigation was included for this exception."))
        elif ar.get("decision") == "REJECT":
            ai_label = "Rejected"
            ai_rows += [("Investigation", iid), ("AI conclusion", REJECTED_TEXT),
                        ("Analyst decision", ("TAG:Rejected", f"{ar['reviewer']['display_name']} · {when(ar['decided_at'])} UTC"))]
            if ar.get("rejection_reason"):
                ai_rows.append(("Reason (as recorded)", f"“{ar['rejection_reason']}”"))
        elif ar.get("decision") == "ACCEPT":
            ai_label = "Accepted"
            full = inv_by_id.get(iid) or {}
            a = full.get("assessment") or {}
            assess = ASSESSMENT_WORDS.get(a.get("overall_evidence_assessment") or inv.get("overall_evidence_assessment"))
            ai_rows.append(("Investigation", iid + (f" (AI-generated; overall evidence assessment: {assess})" if assess else " (AI-generated)")))
            if a.get("summary"):
                ai_rows.append(("AI conclusion", f"“{a['summary']}”"))
            else:
                omitted.append(f"{ex['exception_id']}: accepted investigation has no stored assessment summary")
            ai_rows.append(("Analyst decision", ("TAG:Accepted", f"{ar['reviewer']['display_name']} · {when(ar['decided_at'])} UTC")))
            if ar.get("comment"):
                ai_rows.append(("Analyst comment (as recorded)", f"“{ar['comment']}”"))
        else:
            ai_rows.append(("Investigation", iid))
            ai_rows.append(("Analyst decision", "No analyst decision is recorded for this investigation."))
        if covers_of.get(ex["exception_id"]):
            ai_rows.insert(1 if ai_rows else 0, ("Covers", "This investigation and decision also cover "
                                                 + ", ".join(covers_of[ex["exception_id"]]) + "."))
        sev = ex.get("severity") or ""
        cards.append({"exception_id": ex["exception_id"], "title": titles[0], "code": check, "severity": sev,
                      "status_tag": f"{ex.get('status', 'OPEN')} · {row.get('resolution_status', 'UNRESOLVED')}",
                      "engine_rows": rows, "ai_rows": ai_rows})
        glance.append({"exception_id": ex["exception_id"], "title": titles[1], "sentence": sentence, "severity": sev,
                       "ai_review": ai_label, "status": human(row.get("resolution_status", "UNRESOLVED")),
                       "date": date, "ccy": ccy, "check": check, "scope": scope})

    # ---- relationships
    rel = final.get("relationships") or {}
    candidates = rel.get("candidate_relationships") or []
    reg = (rel.get("relationship_register") or {}).get("relationships") or []
    confirmed = [r for r in reg if r.get("engine_status") == "CONFIRMED"]
    link_short = [f"{c.get('detail', '').rstrip('.')}. This is a candidate only, not an established relationship."
                  for c in candidates if c.get("detail")]
    link_box = None
    if candidates:
        parts = [f"Engine candidate ({c['candidate_id']}, {human(c.get('basis', '')).lower()}): {c.get('detail', '')}"
                 for c in candidates]
        established = ("The engine established no relationship between the exceptions." if not confirmed else
                       "The engine established: " + "; ".join(f"{', '.join(r['exception_ids'])} ({r.get('link_type', '')})"
                                                              for r in confirmed) + ".")
        link_box = {"title": "Possible link between the exceptions — unverified",
                    "parts": parts, "label": "Not evidence-backed and not an investigation group.", "established": established}
    confirmed_lines = [f"{', '.join(r['exception_ids'])}: {r.get('basis', '')}" for r in confirmed]

    # ---- next steps: accepted investigations only, verbatim, de-duplicated
    accepted_ids = [r["investigation"]["investigation_id"] for r in exceptions
                    if ((r.get("investigation") or {}).get("analyst_review") or {}).get("decision") == "ACCEPT"]
    steps, seen = [], set()
    for iid in accepted_ids:
        for s in (inv_by_id.get(iid) or {}).get("next_steps") or []:
            t = (s.get("action") or s.get("text") or "").strip()
            k = re.sub(r"\W+", " ", t.lower()).strip()
            if t and k not in seen:
                seen.add(k)
                steps.append(t)

    # ---- reconciliation results
    def daily(rows_, kind):
        n = len(rows_)
        outs = [k for k in (rows_[0].keys() if rows_ else []) if k.endswith("_outcome")]
        passed = sum(1 for r in rows_ if all(r.get(k) in (None, "PASS", "NOT_APPLICABLE") for k in outs))
        diff_days = len({r["date"] for r in rows_ if (_num(r.get("difference_reported")) or 0) != 0})
        return {"kind": kind, "records": n, "passed": passed, "diff_days": diff_days}
    internal = daily(rr.get("internal_by_currency_day") or [], "Internal: safeguarding requirement against resource, per currency")
    external = daily(rr.get("external_by_account_day") or [], "External: firm ledger against bank evidence, per safeguarding account")

    accounts, out_of_scope = [], []
    for a in m.get("accounts") or []:
        aid = a["account_id"]
        ext = [r for r in rr.get("external_by_account_day") or [] if r["account_id"] == aid]
        bat = [s for s in rr.get("settlements") or [] if s.get("account_id") == aid]
        if not ext and not bat:
            out_of_scope.append(a)
            continue
        ext_outs = [k for k in (ext[0].keys() if ext else []) if k.endswith("_outcome")]
        ext_fail = [r for r in ext if not all(r.get(k) in (None, "PASS", "NOT_APPLICABLE") for k in ext_outs)]
        ext_txt = (f"{len(ext)} days, all passed" if ext and not ext_fail else
                   f"{len(ext)} days, {len(ext) - len(ext_fail)} passed, {len(ext_fail)} with a failure" if ext else "—")
        lf = [s["batch_id"] for s in bat if s.get("lines_outcome") not in ("PASS", None)]
        bf = [s["batch_id"] for s in bat if s.get("bank_outcome") not in ("PASS", None)]
        if not lf and not bf:
            bat_txt = [(f"{len(bat)} · lines and bank: all passed", False)]
        else:
            bat_txt = [(f"{len(bat)} · lines: ", False)]
            bat_txt += [(f"{len(bat) - len(lf)} passed, ", False), (f"{len(lf)} failed", True), (f" ({', '.join(lf)})", False)] if lf \
                else [("all passed", False)]
            bat_txt += [(" · bank: ", False)] + ([(f"{len(bat) - len(bf)} passed, ", False), (f"{len(bf)} failed", True),
                                                  (f" ({', '.join(bf)})", False)] if bf else [("all passed", False)])
        kind = "Safeguarding" if a.get("account_class") == "RELEVANT_FUNDS_BANK" else human(a.get("account_class"))
        accounts.append({"account": aid, "type": f"{kind} ({a.get('currency')})", "external": ext_txt, "batches": bat_txt})
    if out_of_scope:
        classes = {human(a.get("account_class")) for a in out_of_scope}
        accounts.append({"account": ", ".join(a["account_id"] for a in out_of_scope),
                         "type": "Own funds" if classes == {"Own funds"} else ", ".join(sorted(classes)),
                         "external": None, "batches": [("Not in scope of the daily external reconciliation", False)]})

    checks = {c["check_id"]: c for c in rr.get("control_checks") or []}
    co = rr.get("control_outcomes") or {}
    full_pass = len(co.get("checks_all_passed_or_not_applicable") or [])
    failing = []
    for cid in co.get("checks_with_failures") or []:
        rc = (checks.get(cid) or {}).get("result_counts") or {}
        failing.append((cid, rc.get("FAIL", 0), rc.get("PASS", 0), rc.get("INSUFFICIENT_EVIDENCE", 0)))
    nofind = co.get("checks_no_findings") or []
    areas, placed, tot = [], set(), {}
    for name, ids in AREAS:
        present = [i for i in ids if i in checks]
        placed.update(present)
        if not present:
            continue
        counts = {}
        for i in present:
            for k, v in (checks[i].get("result_counts") or {}).items():
                counts[k] = counts.get(k, 0) + v
                tot[k] = tot.get(k, 0) + v
        fails = [i for i in present if (checks[i].get("result_counts") or {}).get("FAIL")]
        ins = [i for i in present if (checks[i].get("result_counts") or {}).get("INSUFFICIENT_EVIDENCE")]
        outcome = []
        if fails:
            outcome.append((f"{sum(checks[i]['result_counts']['FAIL'] for i in fails)} failed", True))
            outcome.append((f" ({', '.join(fails)})", False))
        if ins:
            outcome.append(((" · " if outcome else "") + f"{sum(checks[i]['result_counts']['INSUFFICIENT_EVIDENCE'] for i in ins)} "
                            "insufficient evidence", True))
            outcome.append((f" ({', '.join(ins)})", False))
        if not outcome:
            outcome.append(("All passed", False))
        nf = [i for i in present if i in nofind]
        if nf:
            outcome.append((f"; {', '.join(nf)} no findings", False))
        areas.append({"area": name, "checks": ", ".join(present), "results": sum(counts.values()), "outcome": outcome})
    others = [i for i in checks if i not in placed]
    if others:
        omitted.append(f"checks without an area in the presentation table, shown under 'Other checks': {', '.join(others)}")
        counts = {}
        for i in others:
            for k, v in (checks[i].get("result_counts") or {}).items():
                counts[k] = counts.get(k, 0) + v
                tot[k] = tot.get(k, 0) + v
        areas.append({"area": "Other checks", "checks": ", ".join(others), "results": sum(counts.values()),
                      "outcome": [("See the technical report", False)]})
    total_out = " · ".join(f"{v:,} {human(k).lower() if k not in ('PASS', 'FAIL') else ('passed' if k == 'PASS' else 'failed')}"
                           for k, v in sorted(tot.items(), key=lambda kv: ("PASS", "FAIL").index(kv[0]) if kv[0] in ("PASS", "FAIL") else 9))
    checks_sentence = [(f"{full_pass} checks passed in full. ", False)]
    if failing:
        checks_sentence.append((f"{len(failing)} check{'s' if len(failing) != 1 else ''} had failures: ", True))
        checks_sentence.append((", ".join(f"{c} ({f} failed, {p} passed)" for c, f, p, _ in failing) + ".", False))
    for nf in nofind:
        checks_sentence.append((f" {nf} reports problems only; it ran and found none.", False))
    recon = {"daily": [internal, external], "accounts": accounts, "checks_sentence": checks_sentence, "areas": areas,
             "total_results": sum(tot.values()), "total_outcome": total_out,
             "note": ("Values are copied from the engine's stored results; nothing is recalculated. Daily figures, all "
                      f"{len(rr.get('settlements') or [])} settlement batches and opening positions are in the generated technical report.")}

    # ---- evidence received
    prov_files = {f["evidence_category"]: f for f in (provenance or {}).get("source_files") or []}
    if provenance is None:
        omitted.append("original filenames, package name, case reference and column-mapping provenance: no provenance record supplied")
    ev_rows = []
    for f in final["source_inventory"]["files"]:
        unit = f.get("record_unit") or ""
        n = f.get("record_count")
        rec = (f"{n} page{'s' if str(n) != '1' else ''}" if "page" in unit else (f"{int(n):,}" if str(n).isdigit() else str(n or "")))
        orig = (prov_files.get(f["evidence_id"]) or {}).get("original_filename")
        if not orig:
            orig = str(f.get("source_file", "")).split("/")[-1]
            if provenance is not None:
                omitted.append(f"{f['evidence_id']}: no original filename in the provenance record; the canonical name is shown")
        desc = f.get("description", "") + (" (optional)" if f.get("requirement") == "OPTIONAL" and "optional" not in f.get("description", "").lower() else "")
        ev_rows.append((f["evidence_id"], desc, orig, rec))
    req_p, req_t = fig.get("required_files_present"), fig.get("required_files_total")
    opt_p, opt_t = fig.get("optional_files_present"), fig.get("optional_files_total")
    miss = fig.get("missing_evidence_items", 0)
    intro = [((f"All {req_t} required" if req_p == req_t else f"{req_p} of {req_t} required")
              + (f" and {opt_p} optional" if opt_p == opt_t else f" and {opt_p} of {opt_t} optional")
              + " files received; " + ("the engine recorded no missing evidence. " if not miss else
                                       f"the engine recorded {miss} missing-evidence item{'s' if miss != 1 else ''}. "), False)]
    if provenance and (provenance.get("zip") or {}).get("filename"):
        intro += [("Package ", False), ("MONO:" + provenance["zip"]["filename"], False),
                  (f" (Ringfence case {provenance['case_ref']}). ", False)]
        mp = provenance.get("mapping_provenance") or {}
        cols = [c for fl in mp.get("files") or [] for c in fl.get("columns") or []]
        if cols:
            exact = sum(1 for c in cols if c.get("method") == "DETERMINISTIC_EXACT" and c.get("disposition") == "MAPPED")
            ignored = sum(1 for c in cols if c.get("disposition") == "IGNORED")
            unresolved = sum(1 for c in cols if c.get("disposition") not in ("MAPPED", "IGNORED"))
            human_n = sum(1 for c in cols if c.get("decided_by") or c.get("confirmed_by"))
            nfiles = len(mp.get("files") or [])
            if exact == len(cols):
                intro.append((f"All {len(cols)} columns across {nfiles} files mapped by exact deterministic match — none ignored, "
                              "none unresolved" + (", no human mapping decisions." if not human_n else f", {human_n} human mapping decisions."), False))
            else:
                intro.append((f"{len(cols)} columns across {nfiles} files: {exact} mapped by exact deterministic match, "
                              f"{len(cols) - exact - ignored - unresolved} mapped by a rule or reviewed proposal, {ignored} ignored, "
                              f"{unresolved} unresolved; {human_n} human mapping decision{'s' if human_n != 1 else ''}.", False))
        else:
            omitted.append("column-mapping summary: the provenance record holds no mapping provenance")

    # ---- review and sign-off
    signoff = []
    for r in sorted((r for r in exceptions if (r.get("investigation") or {}).get("analyst_review")),
                    key=lambda r: r["investigation"]["analyst_review"]["decided_at"]):
        ar = r["investigation"]["analyst_review"]
        txt = (f"Reason: “{ar['rejection_reason']}”" if ar["decision"] == "REJECT" and ar.get("rejection_reason") else
               f"Comment: “{ar['comment']}”" if ar.get("comment") else "No comment recorded")
        signoff.append({"decision": ar["decision"], "tag": True, "subject": f"AI investigation, {r['exception']['exception_id']}",
                        "text": txt, "reviewer": ar["reviewer"]["display_name"], "time": when(ar["decided_at"]),
                        "ref": ar["analyst_review_id"]})
    hr = final.get("human_review") or {}
    if hr.get("decision") and hr.get("decided_at"):
        signoff.append({"decision": hr["decision"], "tag": False, "subject": "This audit pack",
                        "text": "Acknowledgement accepted (below)" if hr.get("acknowledgement_accepted") else "",
                        "reviewer": (hr.get("reviewer") or {}).get("display_name", ""), "time": when(hr["decided_at"]),
                        "ref": hr.get("review_decision_id", "")})
    prov_line = None
    if provenance and provenance.get("recon_run_id") and (provenance.get("zip") or {}).get("sha256"):
        prov_line = [("Provenance recorded with the decision: ", True),
                     (f"reconciliation run {provenance['recon_run_id']} · snapshot {provenance['snapshot_id']} · package SHA-256 ", False),
                     ("MONO:" + provenance["zip"]["sha256"], False), (" · full per-file and per-column provenance in ", False),
                     ("MONO:ringfence_provenance.json", False), (".", False)]

    # ---- appendix
    at = final["audit_trail"]
    appx = [("Final pack", f"{m['final_pack_id']} · version {m['version']} · {m['status']} · supersedes "
                           f"{m.get('supersedes_final_pack_id') or 'none'}"),
            ("Final content SHA-256", "MONO:" + final["final_content_sha256"]),
            ("Source deterministic pack", [(at["source_pack"]["pack_id"] + " · content SHA-256 ", False),
                                           ("MONO:" + at["source_pack"]["pack_content_sha256"], False)]),
            ("Review snapshot SHA-256", "MONO:" + at["review_snapshot_sha256"])]
    for r in at.get("analyst_reviews") or []:
        appx.append(("Accepted investigation" if r["decision"] == "ACCEPT" else "Rejected investigation",
                     [(r["investigation_id"] + " · findings ", False), ("MONO:" + r["findings_sha256"], False)]))
    appx.append(("Versions", f"schema {final['final_pack_schema_version']} · renderer {ANALYST_RENDERER_VERSION} (technical report: "
                             f"{m.get('report_renderer')}) · validation rules {at.get('validation_rules_version')} · processing run "
                             f"{m['source_pack']['processing_run_id']}"))

    # ---- outcome block
    sev = fig.get("exceptions_by_severity") or {}
    sev_txt = ", ".join(f"{v} {k}" if len(sev) > 1 else k for k, v in sev.items())
    n_exc, n_unres = fig.get("exceptions_total", 0), fig.get("exceptions_unresolved", 0)
    tiles = [(f"{fig['control_results_passed']:,}", f"of {fig['control_results_total']:,} control results passed"),
             (f"{fig['control_results_failed']:,}", "failed control results"),
             (f"{fig['checks_total']}", "checks performed"),
             (f"{n_exc}", (f"exceptions ({sev_txt}), " if sev_txt else "exceptions, ")
              + ("unresolved" if n_unres == n_exc else f"{n_unres} unresolved")),
             (f"{req_p} / {req_t}", f"required files (+{opt_p} of {opt_t} optional); "
              + ("no missing evidence" if not miss else f"{miss} missing-evidence items"))]
    if internal["passed"] == internal["records"] and external["passed"] == external["records"] \
            and not internal["diff_days"] and not external["diff_days"]:
        para = [(f"Both daily reconciliations agreed on every day — internal (requirement against resource) on all "
                 f"{internal['records']} currency-days and external (ledger against bank) on all {external['records']} "
                 "account-days, with no reported difference.", False)]
    else:
        para = [(f"Internal reconciliation (requirement against resource): {internal['passed']} of {internal['records']} "
                 f"currency-days passed, {internal['diff_days']} day(s) with a reported difference. External reconciliation "
                 f"(ledger against bank): {external['passed']} of {external['records']} account-days passed, "
                 f"{external['diff_days']} day(s) with a reported difference.", False)]
    if glance:
        def phrase(g):
            if g["check"].startswith("C11-") and g["scope"] in settle:
                s = settle[g["scope"]]
                return f"one {s.get('currency')} {str(s.get('counterparty_type', '')).lower()} settlement batch"
            if g["check"].startswith("CBAL-"):
                return "one client balance"
            return "one " + g["title"].rstrip(".").lower()
        ph = [phrase(g) for g in glance]
        dates = {g["date"] for g in glance if g["date"]}
        lead = "The exception concerns " if len(glance) == 1 else f"The {len(glance) if len(glance) > 2 else 'two'} exceptions concern "
        para.append((" " + lead + (", ".join(ph[:-1]) + " and " + ph[-1] if len(ph) > 1 else ph[0]), False))
        if len(dates) == 1:
            para += [(" on ", False), (day_long(next(iter(dates))), True)]
        amount = None
        for c in candidates:
            if "AMOUNT" in str(c.get("basis", "")).upper():
                mm_ = re.search(r"\((\d+\.\d{2})\)", c.get("detail", ""))
                if mm_:
                    amount = mm_.group(1)
        if amount and len(glance) == 2:
            ccys = {g["ccy"] for g in glance if g["ccy"]}
            para += [(", and involve the same amount, ", False), (money(amount, next(iter(ccys)) if len(ccys) == 1 else None), True)]
        para.append((".", False))
    statement = build_statement({c["check_id"]: c.get("result_counts") or {} for c in rr.get("control_checks") or []},
                                f"{month:%B %Y}", n_exc)
    outcome = {"status": STATUS_WORDS.get(status_code, human(status_code)).upper(), "headline": o["headline"],
               "note": "Deterministic engine case status for the checks it ran; not an independent audit conclusion.",
               "tiles": tiles, "paragraph": para, "glance": glance, "links": link_short, "steps": steps,
               "clean": not exceptions, "statement": statement}
    return {"renderer": ANALYST_RENDERER_VERSION, "header": header, "outcome": outcome, "cards": cards, "link_box": link_box,
            "confirmed_relationships": confirmed_lines, "recon": recon, "evidence": {"intro": intro, "rows": ev_rows},
            "signoff": {"rows": signoff, "ack": hr.get("acknowledgement_text", ""), "prov": prov_line,
                        "pending": "No decision to generate the final audit pack has been recorded yet (preview)." if preview else None},
            "appendix": appx, "omitted": omitted}


def verified_source_pack(final, pack):
    """The deterministic pack only if it is the one the final pack pins (pack id and content SHA-256), else None."""
    from ..pack import model as pack_model
    want = final["audit_trail"]["source_pack"]
    if not pack or pack.get("metadata", {}).get("pack_id") != want["pack_id"]:
        return None
    recorded = pack.get("audit_trail", {}).get("pack_content_sha256", "")
    if recorded != want["pack_content_sha256"] or pack_model.content_hash(pack) != recorded:
        return None
    return pack


# ------------------------------------------------------------------------------------------------ drawing
class _Canvas(rl_canvas.Canvas):
    """Running header (title left, pack ID right) and footer (notice left, 'Page X of Y' right), two-pass numbering."""
    header = ("", "")
    font = "Helvetica"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self.setFont(self.font, 7)
            self.setFillColor(INK2)
            self.drawString(18 * mm, A4[1] - 11 * mm, self.header[0])
            self.drawRightString(A4[0] - 18 * mm, A4[1] - 11 * mm, self.header[1])
            self.drawString(18 * mm, 10 * mm, FOOTER)
            self.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def render_analyst_pdf(final, provenance=None, source_pack=None):
    """(pdf_bytes, model) for the analyst edition. Deterministic output (invariant=1). No AI request."""
    model = build_model(final, provenance, source_pack)
    F = _unicode_fonts()
    R, B, MONO = F.base, F.bold, F.mono

    def esc(text, font):
        return F.markup(str(text), font)

    def runs(parts, base=R):
        """[(text, bold)] or a plain string -> paragraph markup; 'MONO:' text is set in the mono face."""
        if isinstance(parts, str):
            parts = [(parts, False)]
        out = []
        for text, bold in parts:
            if text.startswith("MONO:"):
                out.append(f'<font name="{MONO}" size="7.5">{esc(text[5:], MONO)}</font>')
            elif bold:
                out.append(f'<font name="{B}">{esc(text, B)}</font>')
            else:
                out.append(esc(text, base))
        return "".join(out)

    S = {
        "kicker": ParagraphStyle("k", fontName=B, fontSize=8.5, leading=11, textColor=INK2, spaceAfter=3),
        "title": ParagraphStyle("t", fontName=B, fontSize=20, leading=25, textColor=NAVY, spaceAfter=4),
        "sub": ParagraphStyle("s", fontName=R, fontSize=8.8, leading=12, textColor=INK2, spaceAfter=8),
        "h1": ParagraphStyle("h1", fontName=B, fontSize=14, leading=18, textColor=NAVY, spaceBefore=12, spaceAfter=2),
        "h2": ParagraphStyle("h2", fontName=B, fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", fontName=R, fontSize=9.6, leading=13.4, textColor=INK, spaceAfter=6),
        "small": ParagraphStyle("sm", fontName=R, fontSize=8, leading=10.6, textColor=INK, spaceAfter=4),
        "muted": ParagraphStyle("mu", fontName=R, fontSize=7.8, leading=10.4, textColor=INK2, spaceAfter=4),
        "cell": ParagraphStyle("c", fontName=R, fontSize=8, leading=10.4, textColor=INK),
        "cellb": ParagraphStyle("cb", fontName=B, fontSize=8, leading=10.4, textColor=INK),
        "cellr": ParagraphStyle("cr", fontName=R, fontSize=8, leading=10.4, textColor=INK, alignment=2),
        "label": ParagraphStyle("l", fontName=B, fontSize=8, leading=10.4, textColor=INK2),
        "panelh": ParagraphStyle("ph", fontName=B, fontSize=7.6, leading=10, textColor=INK2, spaceAfter=2),
        "tile_n": ParagraphStyle("tn", fontName=B, fontSize=15, leading=18, textColor=NAVY, alignment=1),
        "tile_t": ParagraphStyle("tt", fontName=R, fontSize=7.4, leading=9.4, textColor=INK2, alignment=1),
        "badge": ParagraphStyle("bg", fontName=B, fontSize=9.5, leading=12, textColor=WHITE, alignment=1),
        "tag": ParagraphStyle("tg", fontName=B, fontSize=7.2, leading=9, textColor=NAVY, alignment=1),
        "cardh": ParagraphStyle("ch", fontName=B, fontSize=9.2, leading=12, textColor=INK),
        "st_h": ParagraphStyle("sth", fontName=B, fontSize=12.5, leading=16, textColor=NAVY, spaceAfter=2),
        "st_mark": ParagraphStyle("stm", fontName=B, fontSize=10, leading=12, textColor=NAVY, alignment=1),
        "st_markx": ParagraphStyle("stx", fontName=B, fontSize=10, leading=12, textColor=INK, alignment=1),
    }
    W = A4[0] - 36 * mm

    def P(parts, style="body"):
        return Paragraph(runs(parts, S[style].fontName), S[style])

    def tag_w(text):
        return stringWidth(str(text), B, 7.2) + 12

    def tag(text):
        t = Table([[Paragraph(esc(text, B), S["tag"])]], colWidths=[tag_w(text)])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("ROUNDEDCORNERS", [3, 3, 3, 3])]))
        return t

    def tags(*texts):
        t = Table([[tag(x) for x in texts]], colWidths=[tag_w(x) + 4 for x in texts])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        t.hAlign = "RIGHT"
        return t

    def grid(header, rows, widths, num_cols=(), bold_first=False):
        data = ([[Paragraph(esc(h, B), S["cellb"] if i not in num_cols else ParagraphStyle("hr", parent=S["cellb"], alignment=2))
                  for i, h in enumerate(header)]] if header else [])
        for r in rows:
            data.append([c if not isinstance(c, (str, list)) else
                         Paragraph(runs(c), S["cellr"] if i in num_cols else (S["cellb"] if bold_first and i == 0 else S["cell"]))
                         for i, c in enumerate(r)])
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK2)]
        t.setStyle(TableStyle(st))
        return t

    def kv(rows, label_w=36 * mm, width=None):
        width = width or W
        data = []
        for k, v in rows:
            if v in (None, "", []):
                continue  # never a label with an empty value
            if isinstance(v, tuple) and isinstance(v[0], str) and v[0].startswith("TAG:"):
                cell = Table([[tag(v[0][4:]), Paragraph(esc(" · " + v[1], R), S["cell"])]],
                             colWidths=[tag_w(v[0][4:]) + 4, width - label_w - tag_w(v[0][4:]) - 14])
                cell.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                          ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                          ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            else:
                cell = Paragraph(runs(v if isinstance(v, list) else [(v, False)]), S["cell"])
            data.append([Paragraph(esc(k, B), S["label"]), cell])
        t = Table(data, colWidths=[label_w, width - label_w])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def edged(flowables, width=W, bg=PANEL2, pad=8):
        t = Table([[flowables]], colWidths=[width])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, NAVY), ("LEFTPADDING", (0, 0), (-1, -1), pad + 2),
                               ("RIGHTPADDING", (0, 0), (-1, -1), pad), ("TOPPADDING", (0, 0), (-1, -1), pad),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
        return t

    def h1(text):
        return [CondPageBreak(45 * mm), P(text, "h1"), Table([[""]], colWidths=[W], rowHeights=[1.2],
                                     style=[("LINEABOVE", (0, 0), (-1, -1), 1.2, NAVY)]), Spacer(1, 6)]

    story = []
    hd, oc = model["header"], model["outcome"]
    story += [P(hd["kicker"].upper(), "kicker"), P(hd["title"], "title"), P(hd["subline"], "sub")]
    banner = Table([[Paragraph(esc(hd["banner"], R), S["small"])]], colWidths=[W])
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [banner, Spacer(1, 4)]

    # 1. Outcome
    story += h1("1. Outcome")
    badge = Table([[Paragraph(esc(oc["status"], B), S["badge"])]], colWidths=[46 * mm])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
    status = Table([[badge, [Paragraph(esc(oc["headline"], B), S["cellb"]), Paragraph(esc(oc["note"], R), S["muted"])]]],
                   colWidths=[50 * mm, W - 50 * mm - 12])
    status.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [edged([status], bg=PANEL), Spacer(1, 6)]
    st = oc.get("statement")
    if st and st.get("lines"):
        marks = {"PASS": ("✓", "st_mark"), "FAIL": ("✗", "st_markx"), "INCOMPLETE": ("!", "st_markx")}
        rows_ = []
        for ln in st["lines"]:
            mk, sty = marks.get(ln["state"], ("•", "st_markx"))
            rows_.append([Paragraph(esc(mk, B), S[sty]), Paragraph(esc(ln["area"], B), S["cellb"]),
                          Paragraph(esc(ln["text"], R), S["cell"])])
        inner_w = W - 22
        lt = Table(rows_, colWidths=[8 * mm, 46 * mm, inner_w - 54 * mm])
        lt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
                                ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        story += [KeepTogether([edged([P("RECONCILIATION STATEMENT · SYSTEM-GENERATED FROM THE ENGINE'S RESULTS, NOT AI", "panelh"),
                                       P(st["headline"], "st_h"), P(st["summary"], "body"), lt, Spacer(1, 4),
                                       P(st["note"], "muted")], bg=WHITE, pad=9)]), Spacer(1, 8)]
    tw = W / 5
    tiles = Table([[[Paragraph(esc(n, B), S["tile_n"]), Paragraph(esc(t, R), S["tile_t"])] for n, t in oc["tiles"]]],
                  colWidths=[tw] * 5)
    tiles.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 4, WHITE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)] +
                              [("BOX", (i, 0), (i, 0), 0.5, LINE) for i in range(5)]))
    story += [tiles, Spacer(1, 6), P(oc["paragraph"])]
    if oc["clean"]:
        story.append(P("No exceptions were raised; no AI investigation was required."))
    else:
        story.append(P("Exceptions at a glance", "h2"))
        rows = []
        for g in oc["glance"]:
            rows.append([[(g["exception_id"], True)], [(g["title"] + " ", True), (g["sentence"], False)], [(g["severity"], True)],
                         tag(g["ai_review"]) if g["ai_review"] in ("Accepted", "Rejected") else g["ai_review"], g["status"]])
        story.append(grid(["Exception", "What the engine found", "Severity", "AI review", "Status"], rows,
                          [24 * mm, W - 24 * mm - 18 * mm - 22 * mm - 20 * mm, 18 * mm, 22 * mm, 20 * mm]))
        for line in oc["links"]:
            story.append(Spacer(1, 4))
            story.append(P([("Possible link (unverified): ", True), (line, False)], "small"))
        if oc["steps"]:
            story.append(Paragraph(esc("What is needed next ", B) + f'<font name="{R}" size="8" color="#46505c">'
                                   + esc("(suggested by the AI investigation; not yet done)", R) + "</font>", S["h2"]))
            for i, s in enumerate(oc["steps"], 1):
                story.append(P(f"{i}. {s}", "small"))

    # 2. Exceptions
    if model["cards"]:
        intro_block = h1("2. Exceptions")[1:] + [P([("Every exception remains ", False), ("UNRESOLVED", True),
                        (". Neither an AI investigation, the analyst's decision on it, nor generating this pack resolves an exception.", False)], "small")]
        inner = W - 22
        for n_card, c in enumerate(model["cards"]):
            tg = [x for x in (c["severity"], c["status_tag"]) if x]
            tgw = sum(tag_w(x) + 4 for x in tg) + 4
            head = Table([[Paragraph(runs([(f"{c['exception_id']} — {c['title']}" + (f" ({c['code']})" if c['code'] != c['title'] else ""), True)]), S["cardh"]), tags(*tg)]],
                         colWidths=[inner - tgw, tgw])
            head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            eng = edged([P("WHAT THE ENGINE FOUND", "panelh"), kv(c["engine_rows"], 42 * mm, inner - 22)], width=inner, bg=PANEL2, pad=6)
            ai = edged([P("AI INVESTIGATION AND ANALYST DECISION", "panelh"), kv(c["ai_rows"], 42 * mm, inner - 22)],
                       width=inner, bg=PANEL2, pad=6)
            card = edged([head, Spacer(1, 6), eng, Spacer(1, 6), ai], width=W, bg=WHITE, pad=8)
            # the section heading travels with the first card (never orphaned at a page foot)
            story += [KeepTogether((intro_block if n_card == 0 else []) + [card]), Spacer(1, 8)]
        if model["link_box"]:
            lb = model["link_box"]
            body = [P(lb["title"].upper(), "panelh")]
            for p in lb["parts"]:
                head_, _, rest = p.partition(": ")
                body.append(P([(head_ + ": ", True), (rest + " ", False), (lb["label"], True), (" " + lb["established"], False)], "small"))
            story += [KeepTogether([edged(body, bg=PANEL)]), Spacer(1, 6)]
        if model["confirmed_relationships"]:
            story.append(P("Relationships established by the engine", "h2"))
            for line in model["confirmed_relationships"]:
                story.append(P(line, "small"))

    # 3. Reconciliation results
    rc = model["recon"]
    story += h1(("3" if model["cards"] else "2") + ". Reconciliation results")
    story.append(grid(["Reconciliation", "Daily records", "Passed", "Days with a reported difference"],
                      [[d["kind"], f"{d['records']:,}", f"{d['passed']:,}", f"{d['diff_days']}"] for d in rc["daily"]],
                      [W - 26 * mm - 18 * mm - 44 * mm, 26 * mm, 18 * mm, 44 * mm], num_cols=(1, 2, 3)))
    story.append(Spacer(1, 6))
    acc_rows = []
    for a in rc["accounts"]:
        if a["external"] is None:
            acc_rows.append([a["account"], a["type"], a["batches"], ""])
        else:
            acc_rows.append([a["account"], a["type"], a["external"], a["batches"]])
    acc = grid(["Account", "Type", "External reconciliation", "Settlement batches"], acc_rows,
               [32 * mm, 26 * mm, 32 * mm, W - 90 * mm])
    for i, a in enumerate(rc["accounts"], 1):
        if a["external"] is None:
            acc.setStyle(TableStyle([("SPAN", (2, i), (3, i))]))
    story.append(acc)
    story.append(P("Control checks", "h2"))
    story.append(P(rc["checks_sentence"], "small"))
    story.append(grid(["Area", "Checks", "Results (summed per area)", "Outcome"],
                      [[a["area"], a["checks"], f"{a['results']:,}", a["outcome"]] for a in rc["areas"]] +
                      [[[("Total", True)], "", [(f"{rc['total_results']:,}", True)], [(rc["total_outcome"], True)]]],
                      [30 * mm, W - 30 * mm - 32 * mm - 34 * mm, 32 * mm, 34 * mm], num_cols=(2,)))
    story.append(P(rc["note"], "muted"))

    # 4. Evidence received
    n = 4 if model["cards"] else 3
    ev = model["evidence"]
    story.append(KeepTogether(h1(f"{n}. Evidence received") + [P(ev["intro"], "small"),
                 grid(["Ref.", "Evidence", "File as submitted", "Records"], [list(r) for r in ev["rows"]],
                      [14 * mm, W - 14 * mm - 62 * mm - 20 * mm, 62 * mm, 20 * mm], num_cols=(3,))]))

    # 5. Review and sign-off
    so = model["signoff"]
    story += h1(f"{n + 1}. Review and sign-off")
    rows = [[tag(r["decision"]) if r["tag"] else [(r["decision"], True)], r["subject"], r["text"], r["reviewer"], r["time"], r["ref"]]
            for r in so["rows"]]
    if rows:
        ref_w = max(stringWidth(r["ref"], R, 8) for r in so["rows"]) + 10
        time_w = max(stringWidth(r["time"], R, 8) for r in so["rows"]) + 10
        dec_w = max(tag_w("GENERATE") + 10, 20 * mm)
        story.append(grid(["Decision", "Subject", "Recorded text", "Reviewer", "Time (UTC)", "Reference"], rows,
                          [dec_w, 25 * mm, W - dec_w - 25 * mm - 27 * mm - time_w - ref_w, 27 * mm, time_w, ref_w]))
    if so.get("pending"):
        story.append(P([(so["pending"], True)], "small"))
    story.append(Spacer(1, 6))
    if so["ack"]:
        story.append(P([("Acknowledgement: ", True), (so["ack"], False)], "small"))
    if so["prov"]:
        story.append(P(so["prov"], "small"))

    # Appendix
    story.append(KeepTogether(h1("Appendix — Integrity record") +
                              [kv([(k, v if isinstance(v, list) else ([(v, False)] if isinstance(v, str) else v)) for k, v in model["appendix"]], 40 * mm),
                               Spacer(1, 6), P(CLOSING_NOTE, "muted")]))

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=17 * mm,
                          title=hd["title"], author="UC-042 final-pack renderer (analyst edition)",
                          subject="Synthetic audit pack - not a compliance opinion", creator=ANALYST_RENDERER_VERSION, invariant=1)
    frame = Frame(18 * mm, 17 * mm, W, A4[1] - 35 * mm, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])
    canvas_cls = type("_AnalystCanvas", (_Canvas,), {"header": (hd["running"], hd["running_right"]), "font": R})
    doc.build(story, canvasmaker=canvas_cls)
    return buf.getvalue(), model
