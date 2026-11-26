"""Phase 3B-11 - build a mapping-review DEMO WORKSPACE (synthetic data; RECORDED proposal responses; no network).

    py -3.11 tools/demo_3b11.py <workspace dir>

Creates <workspace>/{rules,evidence,audit.jsonl,pk} and one single-category TEST PACKAGE (IN-10 only - not a complete
UC-042 package) per scenario, each submitted through the real PackageService -> MappingOrchestrator -> gate / gateway /
validator / policy. The proposer is the RecordedResponseStub (a test implementation, NOT an LLM): the responses below
mirror what the live model returned in Phase 3B-10 (UNMAPPABLE, PLAUSIBLE ...), so no live call is repeated.

    A  clear semantic headers          -> AUTO_ACCEPT (test-only POC policy) -> VALIDATED
    B  ambiguous 'reference' / 'value' -> proposal review session
    C  UNMAPPABLE 'ref_code' (values ARE payment references) -> UNMAPPABLE_PROPOSAL review case (analyst can map)
    D  UNMAPPABLE 'display_colour' (colour codes)             -> UNMAPPABLE_PROPOSAL review case. The only uncovered
       field (payment_reference) is FREE TEXT in the UC-042 contract, so mapping colour codes to it is not refused
       deterministically - the analyst's judgement decides (the demo leaves it unresolved / rejects it)
    E  extra column 'operator_memo'    -> header-count review case
    F  missing column 'currency'       -> RESUBMISSION_REQUIRED
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from smartparser.ai.config import AIConfig  # noqa: E402
from smartparser.ai.gateway import ProposalGateway  # noqa: E402
from smartparser.ai.proposer import RecordedResponseStub  # noqa: E402
from smartparser.intake.store import EvidenceStore  # noqa: E402
from smartparser.mapping.rule_store import RuleStore  # noqa: E402
from smartparser.orchestration.orchestrator import MappingOrchestrator  # noqa: E402
from smartparser.orchestration.policy import PocAutoAcceptPolicy  # noqa: E402
from smartparser.packages.service import PackageService, Submission  # noqa: E402
from smartparser.packages.store import PackageStore  # noqa: E402
from smartparser.review.audit import AuditLog  # noqa: E402
from smartparser.review.authority import AuthorityPolicy  # noqa: E402
from smartparser.schemas import SchemaRegistry  # noqa: E402

FIX = HERE / "tests" / "fixtures"
TEST_POC_POLICY = FIX / "orchestration" / "poc_auto_accept_enabled.json"
TEST_AUTHORITY = FIX / "review" / "test_authority_policy.json"
SEP = FIX / "uc042_canonical" / "PER-2026-09_set_01_clean_baseline"


def _files():
    with open(SEP / "manifest.csv", encoding="utf-8", newline="") as f:
        out = {}
        for r in csv.DictReader(f):
            out.setdefault(r["file_id"], SEP / r["relative_path"])
    return out


FILES = _files()


def table(fid):
    return list(csv.reader(io.StringIO(FILES[fid].read_bytes().decode("utf-8"))))


def dump(rows) -> bytes:
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode()


def replace_column(fid, col, header, values=None):
    r = table(fid)
    i = r[0].index(col)
    rows = [r[0][:i] + [header] + r[0][i + 1:]]
    for k, x in enumerate(r[1:]):
        rows.append(x[:i] + [x[i] if values is None else values[k % len(values)]] + x[i + 1:])
    return dump(rows), i


def recorded(category, cols):
    """A recorded response in the proposal schema: cols = [(source_index, header, field, assessment)]."""
    body = {"response_schema": "smartparser-mapping-proposal/1.0", "category": category, "notes": "recorded",
            "columns": [{"source_index": i, "source_header": h, "canonical_field": f, "assessment": a,
                         "alternatives": [], "explanation": "recorded response (mirrors the 3B-10 live answer)",
                         "evidence": []} for i, h, f, a in cols]}
    return {"match": {"category": category, "unresolved_headers": [h for _, h, _, _ in cols]},
            "response_text": json.dumps(body)}


def scenario_data():
    r10 = table("IN-10")
    a_ren = {"ledger_entry_id": "cash_book_entry_id", "account_id": "safeguarding_account_id",
             "posted_ts": "posting_timestamp"}
    a = dump([[a_ren.get(c, c) for c in r10[0]]] + r10[1:])
    b = dump([[{"payment_reference": "reference", "amount": "value"}.get(c, c) for c in r10[0]]] + r10[1:])
    c, ci = replace_column("IN-10", "payment_reference", "ref_code")
    d, di = replace_column("IN-10", "payment_reference", "display_colour", ["#FF0000", "#00AA00", "#0000FF"])
    e = dump([r10[0] + ["operator_memo"]] + [x + ["free text"] for x in r10[1:]])
    cur = r10[0].index("currency")
    f = dump([[v for j, v in enumerate(x) if j != cur] for x in r10])
    fixtures = [
        recorded("IN-10", [(0, "cash_book_entry_id", "ledger_entry_id", "CLEAR"),
                           (1, "safeguarding_account_id", "account_id", "CLEAR"),
                           (2, "posting_timestamp", "posted_ts", "CLEAR")]),
        recorded("IN-10", [(4, "value", "amount", "PLAUSIBLE"), (7, "reference", "payment_reference", "PLAUSIBLE")]),
        recorded("IN-10", [(ci, "ref_code", "UNMAPPABLE", "UNMAPPABLE")]),
        recorded("IN-10", [(di, "display_colour", "UNMAPPABLE", "UNMAPPABLE")]),
    ]
    return {"A": a, "B": b, "C": c, "D": d, "E": e, "F": f}, fixtures


def build_service(root: Path, proposer=None, poc_policy=TEST_POC_POLICY) -> PackageService:
    reg = SchemaRegistry.from_directory()
    log = AuditLog(root / "audit.jsonl")
    store = RuleStore(root / "rules", reg) if (root / "rules").exists() else RuleStore.initialise(root / "rules", reg)
    gw = ProposalGateway(proposer=proposer or RecordedResponseStub([]),
                         config=AIConfig(enabled=True, provider="recorded_stub"), log=log)
    orch = MappingOrchestrator(reg, store, EvidenceStore(root / "evidence"), gw, PocAutoAcceptPolicy.load(poc_policy), log)
    return PackageService(PackageStore(root / "pk"), orch, AuthorityPolicy.load(TEST_AUTHORITY), actor_id="demo-analyst")


def build(root: str | Path, scenarios: str = "ABCDEF") -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data, fixtures = scenario_data()
    stub = RecordedResponseStub(fixtures)
    svc = build_service(root, stub)
    out = {}
    names = {"A": "clear", "B": "ambiguous", "C": "unmappable_mappable", "D": "unmappable_colour",
             "E": "extra_column", "F": "missing_column"}
    for k in scenarios:
        pkg = svc.create_package("2026-09", ["IN-10"])
        o = svc.submit(pkg.package_id, [Submission(data[k], f"cashbook_{names[k]}.csv", "IN-10")])[0]
        v = o.file_version
        out[k] = {"package_id": pkg.package_id, "file_version_id": v.file_version_id, "status": v.version_status,
                  "processing_status": v.processing_status, "review_case_id": v.review_case_id,
                  "review_session_id": v.review_session_id, "label": "TEST PACKAGE (IN-10 only)"}
    out["_provider_calls"] = len(stub.calls)
    out["_provider"] = stub.provider_id
    (root / "demo_index.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1]), indent=1))
