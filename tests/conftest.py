from pathlib import Path

import pytest

from smartparser import SmartParser
from smartparser.intake import EvidenceStore
from smartparser.mapping.templates import TemplateRegistry
from smartparser.schemas import SchemaRegistry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _manual_reconciliation_step_by_default(monkeypatch):
    """23 Nov 2026: the server continues from a passed Smart Parser run to activation and reconciliation by itself
    (cases._maybe_auto_reconcile). The existing tests pin the manual step, which RINGFENCE_AUTO_RECONCILE=off keeps;
    tests of the automatic step remove the variable (test_auto_reconcile_ai_parallel.py)."""
    monkeypatch.setenv("RINGFENCE_AUTO_RECONCILE", "off")

LEDGER_OK = (
    "entry_id,entry_date,amount,currency,description\n"
    "E1,2026-10-01,100.00,GBP,Opening\n"
    "E2,2026-10-02,-25.50,GBP,Fee\n"
    "E3,2026-10-03,1250.75,EUR,\"Transfer, inbound\"\n"
)


@pytest.fixture
def test_registry() -> SchemaRegistry:
    return SchemaRegistry.from_directory(FIXTURES / "schemas", allow_non_official=True)


@pytest.fixture
def parser(test_registry, tmp_path) -> SmartParser:
    return SmartParser(schemas=test_registry,
                       templates=TemplateRegistry(tmp_path / "templates.json"),
                       store=EvidenceStore(tmp_path / "store"))


@pytest.fixture
def run(parser):
    def _run(content, filename="evidence.csv", period="2026-10", encoding="utf-8", **kw):
        data = content if isinstance(content, bytes) else content.encode(encoding)
        return parser.process_bytes(data, filename, period, **kw)
    return _run


def codes(result):
    return [i.code.value for i in result.all_issues()]
