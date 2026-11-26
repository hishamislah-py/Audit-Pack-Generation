"""Phase 3B-3: deterministic reprocessing, the 14-point handoff checklist and the PREVIEW-only canonical writer."""
import hashlib
import json
from pathlib import Path

import pytest

from smartparser.handoff.eligibility import HandoffPolicy, check_handoff
from smartparser.handoff.reprocess import ReprocessError, reprocess
from smartparser.handoff.writer import (DEFAULT_PROTECTED, MARKER, HandoffNotAuthorised, HandoffRefused, submit_to_uc042,
                                        write_preview)
from smartparser.mapping.templates import TemplateRegistry, TemplateStatus
from smartparser.review.approvals import approve_file_mapping, confirm_category, revoke_rule
from smartparser.review.session import approve_proposal, decide_column, open_review

from .phase3b_support import ANALYST, OWNER, SEP, dump, make_env, read, renamed_in10, short_example, tbl


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def approved_file_mapping(env, data=None, fixture="in10_valid_mix", leave=()):
    r = env.parse(data or renamed_in10())
    out = env.propose(r, fixture)
    s, ctx = env.session(r, out)
    open_review(s, ANALYST, env.policy, env.log)
    for c in s.columns:
        action = "LEAVE_UNMAPPED" if c.source_header in leave else "APPROVE"
        decide_column(s, c.source_index, action, ANALYST, "b", env.policy, env.log, ctx)
    approve_proposal(s, ANALYST, "b", env.policy, env.log, ctx)
    rule = approve_file_mapping(s, [ANALYST], "b", env.policy, env.store, env.log)
    conf = confirm_category(r.metadata.evidence_id, r.metadata.sha256, "IN-10", ANALYST, "cash-book export",
                            env.policy, env.log, env.reg)
    return r, rule, conf


def upload(env, data, filename="u.csv"):
    """A deterministic upload (automatic classification) stored in the evidence store."""
    return env.parser().process_bytes(data, filename, "2026-09")


# ============================================================================================ reprocessing
def test_reprocess_with_approved_file_mapping_is_deterministic_and_eligible(env, tmp_path):
    r, rule, conf = approved_file_mapping(env)
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    assert rr.category == "IN-10" and rr.category_basis == f"confirmed:{conf.confirmation_id}"
    assert rr.rules_used == [{"kind": "file_mapping", "rule_id": rule.file_mapping_id, "rule_version": 1}]
    assert rr.provider_calls == 0 and rr.original_intake_id == r.metadata.evidence_id
    again = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    assert rr.result.mapping.model_dump() == again.result.mapping.model_dump()          # reproducible
    assert [x.values for x in rr.result.records] == [x.values for x in again.result.records]
    e = check_handoff(rr, env.reg)
    assert e.eligible and len(e.checks) == 14 and e.submission_authorised is False
    out = write_preview(rr, e, env.reg, tmp_path / "out")
    # renaming headers back to canonical names and keeping cells reproduces the canonical source file byte for byte
    assert out["csv"].read_bytes() == read(SEP, "IN-10")
    assert out["csv"].name.startswith(MARKER)


def test_reprocess_never_calls_the_proposal_mechanism(env, monkeypatch):
    r, rule, conf = approved_file_mapping(env)
    import smartparser.mapping.proposal_runner as pr

    def boom(*a, **k):
        raise AssertionError("proposal mechanism called during reprocessing")
    monkeypatch.setattr(pr, "run_proposal", boom)
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    assert rr.result.metadata.mapping_status == "complete" and rr.provider_calls == 0


def test_reprocess_verifies_intake_sha_and_confirmation(env):
    r, rule, conf = approved_file_mapping(env)
    with pytest.raises(ReprocessError, match="unknown intake"):
        reprocess("no-such-intake", env.evidence, env.reg, env.store.load(), conf)
    other = upload(env, read(SEP, "IN-09"))
    with pytest.raises(ReprocessError, match="different upload"):
        reprocess(other.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    with pytest.raises(ReprocessError, match="neither identified deterministically nor confirmed"):
        reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), None)
    stored = env.evidence.root / "originals" / r.metadata.sha256[:2] / r.metadata.sha256
    stored.write_bytes(stored.read_bytes() + b"x")                       # tamper with the stored original
    with pytest.raises(ReprocessError, match="does not match its SHA-256"):
        reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)


@pytest.mark.parametrize("fid", ["IN-02", "IN-09", "IN-10", "IN-13"])
def test_canonical_and_reordered_files_are_eligible_without_rules(env, tmp_path, fid):
    canon = upload(env, read(SEP, fid))
    rr = reprocess(canon.metadata.evidence_id, env.evidence, env.reg, env.store.load())
    e = check_handoff(rr, env.reg)
    assert e.eligible, [(c.check_id, c.detail) for c in e.failed]
    assert write_preview(rr, e, env.reg, tmp_path / fid)["csv"].read_bytes() == read(SEP, fid)
    rows = tbl(fid)
    rev = upload(env, dump([list(reversed(x)) for x in rows]))
    rr2 = reprocess(rev.metadata.evidence_id, env.evidence, env.reg, env.store.load())
    e2 = check_handoff(rr2, env.reg)
    assert e2.eligible and rr2.result.classification.method == "csv_controlled_mapping"
    assert write_preview(rr2, e2, env.reg, tmp_path / f"{fid}r")["csv"].read_bytes() == read(SEP, fid)


# ============================================================================================ ineligible
def test_missing_required_fields_stay_ineligible(env, tmp_path):
    r, rule, conf = approved_file_mapping(env, short_example(), "in10_short_example")
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    e = check_handoff(rr, env.reg)
    assert not e.eligible and {1, 2, 5}.issubset({c.check_id for c in e.failed})
    with pytest.raises(HandoffRefused, match="not eligible"):
        write_preview(rr, e, env.reg, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_explicitly_unmapped_column_stays_ineligible(env):
    r, rule, conf = approved_file_mapping(env, leave=("txn_amt",))
    assert [c.canonical_field for c in rule.columns if c.source_header == "txn_amt"] == [None]
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    e = check_handoff(rr, env.reg)
    assert not e.eligible and 6 in {c.check_id for c in e.failed}


def test_revoked_rule_is_detected_and_no_longer_matches(env):
    r, rule, conf = approved_file_mapping(env)
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    revoke_rule("file_mappings", rule.file_mapping_id, 1, OWNER, "decision withdrawn", env.policy, env.store, env.log)
    rr.rules = env.store.load().with_file_identity(r.metadata.evidence_id, r.metadata.sha256)   # current rules
    e = check_handoff(rr, env.reg)
    assert not e.eligible and 9 in {c.check_id for c in e.failed} and "revoked" in e.failed[0].detail
    later = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    assert later.result.metadata.mapping_status == "not_attempted" and not check_handoff(later, env.reg).eligible


def test_d1_noncanonical_serialisation_stays_ineligible_unless_policy_allows(env):
    rows = tbl("IN-07")
    semi = upload(env, dump(rows).replace(b",", b";"))
    rr = reprocess(semi.metadata.evidence_id, env.evidence, env.reg, env.store.load())
    e = check_handoff(rr, env.reg)
    assert [c.check_id for c in e.failed] == [14] and "delimiter ';'" in e.failed[0].detail
    assert check_handoff(rr, env.reg, HandoffPolicy(allow_noncanonical_serialisation=True)).eligible


def test_nonconforming_values_block_handoff_and_are_never_fixed(env):
    rows = tbl("IN-10")
    i = rows[0].index("amount")
    rows[1][i] = "1,000.00"                                                # UC-042 rejects separators
    bad = upload(env, dump(rows))
    rr = reprocess(bad.metadata.evidence_id, env.evidence, env.reg, env.store.load())
    e = check_handoff(rr, env.reg)
    assert not e.eligible and {10, 11}.issubset({c.check_id for c in e.failed})
    assert rr.result.records[0].original["amount"] == "1,000.00"         # kept as is
    assert next(c for c in e.checks if c.check_id == 12).passed          # nothing was rewritten


# ============================================================================================ writer + gate
def test_sidecar_provenance_and_output_hash(env, tmp_path):
    r, rule, conf = approved_file_mapping(env)
    rr = reprocess(r.metadata.evidence_id, env.evidence, env.reg, env.store.load(), conf)
    out = write_preview(rr, check_handoff(rr, env.reg), env.reg, tmp_path / "o", now="2026-11-18T12:00:00+00:00")
    side = json.loads(out["sidecar"].read_text(encoding="utf-8"))
    assert side["status"] == MARKER and side["submission_authorised"] is False
    assert side["source"] == {"sha256": r.metadata.sha256, "intake_id": r.metadata.evidence_id,
                              "original_filename": "upload.csv"}
    assert side["category"]["confirmation_id"] == conf.confirmation_id
    assert side["canonical_header"] == env.reg.get("IN-10").csv.header
    entry = next(c for c in side["columns"] if c["canonical_field"] == "ledger_entry_id")
    assert (entry["original_header"], entry["source_index"], entry["method"], entry["rule_id"]) == \
        ("entry_ref", 0, "approved_file_mapping", rule.file_mapping_id)
    assert len(side["rows"]) == len(rr.result.records) and side["rows"][0]["source_line"] == 2
    assert side["output"]["sha256"] == hashlib.sha256(out["csv"].read_bytes()).hexdigest()
    assert all(c["passed"] for c in side["validation"]["eligibility"])


def test_writer_refuses_the_uc042_tree_and_submission_is_disabled(env, monkeypatch, tmp_path):
    canon = upload(env, read(SEP, "IN-09"))
    rr = reprocess(canon.metadata.evidence_id, env.evidence, env.reg, env.store.load())
    e = check_handoff(rr, env.reg)
    monkeypatch.setenv("UC042_ROOT", str(tmp_path / "uc042"))
    with pytest.raises(HandoffRefused, match="protected UC-042 tree"):
        write_preview(rr, e, env.reg, tmp_path / "uc042" / "source_data")
    with pytest.raises(HandoffRefused, match="protected UC-042 tree"):
        write_preview(rr, e, env.reg, str(Path(DEFAULT_PROTECTED[0]) / "out"))
    with pytest.raises(HandoffNotAuthorised):
        submit_to_uc042(rr, e)


def test_uc042_categories_ignore_template_registry(env, tmp_path):
    """Decision: UC-042 categories use governed approved_layouts only; a validated TemplateRegistry entry has no effect
    on them (TemplateRegistry is kept for synthetic/provisional schemas)."""
    from smartparser import SmartParser
    templates = TemplateRegistry(tmp_path / "t.json")
    rows = tbl("IN-10")
    headers = ["entry_ref"] + rows[0][1:]
    templates.add("IN-10", "1.0.0", headers, {"entry_ref": "ledger_entry_id"}, status=TemplateStatus.VALIDATED)
    p = SmartParser(schemas=env.reg, store=env.evidence, templates=templates, mapping_rules=env.rules())
    res = p.process_bytes(dump([headers] + rows[1:]), "x.csv", "2026-09")
    assert res.metadata.classification_status == "unknown"
