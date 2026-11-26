"""Shared fixtures/helpers for the Phase 3B-2..3B-5 tests (not a test module). Everything writable lives in tmp
directories; the packaged production rules and policy are only read."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from smartparser import SmartParser
from smartparser.intake import EvidenceStore
from smartparser.mapping.proposal_runner import run_proposal
from smartparser.mapping.rule_store import RuleStore
from smartparser.review.audit import AuditLog
from smartparser.review.authority import AuthorityPolicy, Reviewer
from smartparser.review.session import ReviewContext, start_session

from .test_proposals import renamed_in10, short_example, stub
from .uc042_support import SEP, read, registry

ROOT = Path(__file__).resolve().parent.parent
TEST_POLICY = Path(__file__).parent / "fixtures" / "review" / "test_authority_policy.json"
ANALYST = Reviewer(reviewer_id="test-analyst-1", role="analyst", kind="TEST")
ANALYST2 = Reviewer(reviewer_id="test-analyst-2", role="analyst", kind="TEST")
OWNER = Reviewer(reviewer_id="test-data-owner-1", role="data_owner", kind="TEST")
SYSOWNER = Reviewer(reviewer_id="test-system-owner-1", role="system_owner", kind="TEST")


def tbl(fid):
    return list(csv.reader(io.StringIO(read(SEP, fid).decode("utf-8"))))


def dump(rows):
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue().encode()


@dataclass
class Env:
    root: Path
    reg: object
    policy: AuthorityPolicy
    log: AuditLog
    store: RuleStore
    evidence: EvidenceStore

    def rules(self, identity=None):
        r = self.store.load()
        return r.with_file_identity(*identity) if identity else r

    def parser(self, identity=None):
        return SmartParser(schemas=self.reg, store=self.evidence, mapping_rules=self.rules(identity))

    def parse(self, data, forced="IN-10", identity=None, filename="upload.csv"):
        return self.parser(identity).process_bytes(data, filename, "2026-09", forced_category=forced)

    def propose(self, result, fixture, revision_of=None):
        return run_proposal(result, self.reg, stub(fixture), rules=self.rules(), revision_of=revision_of)

    def session(self, result, outcome):
        s = start_session(outcome.record, outcome.request, list(result.csv_extraction.raw_headers), self.log)
        ctx = ReviewContext(outcome.request, self.reg.get(outcome.record.confirmed_category),
                            list(result.csv_extraction.raw_headers),
                            {c.index: list(c.sample_values) for c in result.csv_extraction.columns})
        return s, ctx


def make_env(tmp_path: Path, clock=None) -> Env:
    reg = registry()
    log = AuditLog(tmp_path / "audit.jsonl", **({"clock": clock} if clock else {}))
    store = RuleStore.initialise(tmp_path / "rules", reg)
    return Env(tmp_path, reg, AuthorityPolicy.load(TEST_POLICY), log, store, EvidenceStore(tmp_path / "evidence"))


__all__ = ["ANALYST", "ANALYST2", "OWNER", "SYSOWNER", "Env", "make_env", "renamed_in10", "short_example", "tbl", "dump",
           "read", "SEP", "registry", "ROOT"]
