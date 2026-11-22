"""Phase 3B-1 - the mapping-proposer interface and a RECORDED-RESPONSE TEST STUB.

`MappingProposer` is the small interface a proposer implements: it receives a `ProposalRequest` (headers, value shapes
and field context only) and returns the raw response TEXT, which the caller parses and validates as untrusted input.

`RecordedResponseStub` is a TEST IMPLEMENTATION, not an LLM: it returns pre-recorded response texts for exactly matching
requests (confirmed category + unresolved header list). It performs no network access, needs no credentials, and never
writes rules or approvals. No live provider exists in this phase.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..mapping.proposals import ProposalRequest


class ProposerError(Exception):
    pass


class FixtureNotFound(ProposerError):
    pass


class MappingProposer(Protocol):
    provider_id: str

    def propose(self, request: ProposalRequest) -> str: ...


class RecordedResponseStub:
    provider_id = "recorded_stub/1.0 (TEST IMPLEMENTATION - not an LLM, no network)"

    def __init__(self, fixtures: list[dict]):
        self._fixtures = fixtures
        self.calls: list[ProposalRequest] = []

    @classmethod
    def from_directory(cls, path: str | Path) -> "RecordedResponseStub":
        return cls([json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(path).glob("*.json"))])

    def propose(self, request: ProposalRequest) -> str:
        self.calls.append(request)
        key = (request.category, [c.source_header for c in request.unresolved_columns])
        for fx in self._fixtures:
            if (fx["match"]["category"], fx["match"]["unresolved_headers"]) == key:
                text = fx["response_text"]
                return text if isinstance(text, str) else json.dumps(text)
        raise FixtureNotFound(f"no recorded response for {key[0]} with unresolved headers {key[1]}")
