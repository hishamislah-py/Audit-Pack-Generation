"""Fix8 Agent B: D8 (final-pack integrity in every view), D5 app side (preview failure diagnostics) and D3 rendering
(column mapping provenance in the Ringfence provenance supplement and the GENERATE comment).

OFFLINE: no live AI anywhere. Unit tests use fixtures; the journey tests use the REAL UC-042 library subprocess with the
clearly marked TEST DOUBLE investigator of tests/test_closure_service.py (skipped without UC042_ROOT /
UC042_CLOSURE_PYTHON). The mapping provenance of Agent A (contract I-3) is a FIXTURE here until
smartparser/webapp/mapping_provenance.py is merged; test_mapping_provenance_module_is_installed is an xfail(strict) that
turns into a normal test (and must pass) once it exists."""
import copy
import hashlib
import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest

from smartparser.reconciliation.closure_runner import ClosureRunner, ClosureRunnerError, RUNNER_DEFS, RUNNER_MAIN
from smartparser.webapp import closure as closure_mod
from smartparser.webapp.closure import (ClosureService, mapping_provenance_problems, mapping_provenance_sentence)
from smartparser.webapp.context import AppContext

from .test_closure_service import (ANALYST, CLOSURE_PY, TEST_POLICY, UC042_ROOT, USER, DoubleRunner, R, code_of, ctx_for,
                                   make_zip, needs_closure, reconcile, tmp_path, wait_closure, wait_job)  # noqa: F401

MODULE = "smartparser.webapp.mapping_provenance"
HAVE_MODULE = importlib.util.find_spec(MODULE) is not None


def mapping_fixture(package_id="PKG-X", snapshot_id="SNAP-X"):
    """A contract I-3 document (fixture; shapes exactly as in FIX8_COORDINATION_BRIEF.md section 4)."""
    col = {"source_position": 1, "source_header": "Txn Ref", "canonical_field": "transaction_id", "disposition": "MAPPED",
           "method": "DETERMINISTIC_EXACT", "rule_id": "IN-11.transaction_id", "rule_version": "1.2", "proposal_id": None,
           "proposal_class": None, "decided_by": None, "decided_at": None, "confirmed_by": "fix8.alice@ringfence.test",
           "confirmed_at": "2026-11-22T10:00:00+00:00", "validation": "PASS", "audit_event_seqs": [12, 13]}
    ai = dict(col, source_position=2, source_header="Amt (GBP)", canonical_field="amount", method="AI_PROPOSED",
              rule_id=None, rule_version=None, proposal_id="MP-0001", proposal_class="HIGH_CONFIDENCE",
              decided_by="fix8.alice@ringfence.test", decided_at="2026-11-22T09:59:00+00:00", audit_event_seqs=[14])
    ign = dict(col, source_position=3, source_header="Notes", canonical_field=None, disposition="IGNORED",
               method="ANALYST_IGNORED", rule_id=None, rule_version=None, validation="NOT_RECORDED", confirmed_by=None,
               confirmed_at=None, audit_event_seqs=[])
    return {"schema": "ringfence-mapping-provenance/1.0", "package_id": package_id, "snapshot_id": snapshot_id,
            "files": [{"evidence_category": "IN-11", "file_version_id": "FV-0001", "version_number": 1,
                       "original_filename": "bank_export_sept.csv", "source_sha256": "ab" * 32, "intake_id": "INT-1",
                       "version_status": "ACTIVE", "review_kind": "MAPPING", "columns": [col, ai, ign]}],
            "notes": ["decided_by of deterministic mappings is not recorded (historical)"]}


@pytest.fixture
def fake_mapping_module(monkeypatch):
    """Installs a FIXTURE implementation of contract I-3 (tests only)."""
    calls = []
    mod = types.ModuleType(MODULE)

    def build_mapping_provenance(ctx, package_id, snapshot_id):
        calls.append((package_id, snapshot_id))
        return mapping_fixture(package_id, snapshot_id)
    mod.build_mapping_provenance = build_mapping_provenance
    monkeypatch.setitem(sys.modules, MODULE, mod)
    import smartparser.webapp as pkg
    monkeypatch.setattr(pkg, "mapping_provenance", mod, raising=False)
    return calls


def _bare_service():
    return ClosureService.__new__(ClosureService)                 # _check_files / _integrity use no service state


def _pack_dir(tmp_path):
    d = tmp_path / "FAP-T"
    d.mkdir()
    files = {"final_pack.json": b'{"a": 1}', "report.html": b"<html></html>", "report.pdf": b"%PDF-1.4 test"}
    for n, b in files.items():
        (d / n).write_bytes(b)
    manifest = json.dumps({"files": {n: {"sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()}}).encode()
    (d / "manifest.json").write_bytes(manifest)
    pj, pp = tmp_path / "prov.json", tmp_path / "prov.pdf"
    pj.write_bytes(b"{}"), pp.write_bytes(b"%PDF prov")
    fp = {"final_pack_id": "FAP-T", "status": "GENERATED", "verified": True, "path": str(d),
          "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
          "provenance": {"json": str(pj), "pdf": str(pp), "json_sha256": hashlib.sha256(b"{}").hexdigest(),
                         "pdf_sha256": hashlib.sha256(b"%PDF prov").hexdigest()}}
    return d, fp


# ============================================================================================ D8 unit (offline)
def test_integrity_is_recomputed_from_files_not_the_stored_flag(tmp_path):
    d, fp = _pack_dir(tmp_path)
    svc = _bare_service()
    assert svc._integrity(fp)["verified"] is True and svc._integrity(fp)["problems"] == []
    b = bytearray((d / "report.pdf").read_bytes()); b[-1] ^= 1
    (d / "report.pdf").write_bytes(bytes(b))                           # one byte, same size
    i = svc._integrity(fp)
    assert i["verified"] is False and i["status"] == "FAILED" and i["problems"] == ["report.pdf does not match its manifest SHA-256"]
    assert fp["verified"] is True                                      # the stored flag is never trusted, never rewritten


def test_integrity_problems_never_raise_for_malformed_or_tampered_manifests(tmp_path):
    svc = _bare_service()
    d, fp = _pack_dir(tmp_path)
    for content in (b"not json", b'{"no_files": 1}', b'{"files": []}', b'{"files": {"../x": {"sha256": "0"}}}', b"[]"):
        (d / "manifest.json").write_bytes(content)
        p = svc._check_files(fp)
        assert p and p[0] == "manifest.json differs from the manifest recorded at generation", (content, p)
    (d / "manifest.json").unlink()
    assert svc._check_files(fp)[0].startswith("manifest unreadable")
    (tmp_path / "b").mkdir()
    d2, fp2 = _pack_dir(tmp_path / "b")
    Path(fp2["provenance"]["pdf"]).write_bytes(b"changed")
    assert svc._check_files(fp2) == ["provenance pdf does not match the SHA-256 recorded at generation"]
    fp2.pop("provenance")
    assert "provenance json does not match the SHA-256 recorded at generation" in svc._check_files(fp2)


def test_a_pack_that_failed_at_generation_never_verifies_later(tmp_path):
    _, fp = _pack_dir(tmp_path)
    assert _bare_service()._integrity(dict(fp, verified=False))["verified"] is False


# ============================================================================================ D3 unit (offline, fixture)
def test_mapping_contract_checks_and_sentence():
    doc = mapping_fixture()
    assert mapping_provenance_problems(doc, "PKG-X", "SNAP-X") == []
    assert mapping_provenance_problems(doc, "PKG-Y", "SNAP-X")
    bad = copy.deepcopy(doc); bad["files"][0]["columns"][0]["method"] = "GUESSED"
    assert "outside the contract enumerations" in mapping_provenance_problems(bad, "PKG-X", "SNAP-X")[0]
    bad = copy.deepcopy(doc); del bad["files"][0]["columns"][1]["confirmed_by"]
    assert "lacks a contract field" in mapping_provenance_problems(bad, "PKG-X", "SNAP-X")[0]
    s = mapping_provenance_sentence(dict(doc, status="AVAILABLE"))
    assert s == ("Column mapping provenance: 1 file(s), 3 column(s) (2 MAPPED, 1 IGNORED, 0 UNRESOLVED; methods: "
                 "1 AI_PROPOSED, 1 ANALYST_IGNORED, 1 DETERMINISTIC_EXACT); per-column source, rule or proposal, decision "
                 "and confirmation in the Ringfence provenance supplement (ringfence_provenance.json, mapping_provenance).")
    assert mapping_provenance_sentence({"status": "UNAVAILABLE", "reason": "r"}).startswith(
        "Column mapping provenance: UNAVAILABLE (r)")


def test_guarded_import_reports_unavailable_visibly(tmp_path, monkeypatch):
    if HAVE_MODULE:
        pytest.skip("Agent A's module is installed; covered by test_mapping_provenance_module_is_installed")
    monkeypatch.setitem(sys.modules, MODULE, None)                     # import fails exactly like an absent module
    svc = _bare_service()
    mp = svc._mapping_provenance({"package_id": "PKG-X", "snapshot_id": "SNAP-X"})
    assert mp["status"] == "UNAVAILABLE" and "mapping provenance module is not installed" in mp["reason"]
    assert mp["files"] == []


def test_fixture_module_is_used_and_contract_breaks_are_unavailable(fake_mapping_module, monkeypatch):
    svc = _bare_service()
    svc.ctx = object()
    mp = svc._mapping_provenance({"package_id": "PKG-X", "snapshot_id": "SNAP-X"})
    assert mp["status"] == "AVAILABLE" and mp["files"][0]["columns"][1]["proposal_id"] == "MP-0001"
    assert fake_mapping_module == [("PKG-X", "SNAP-X")]
    sys.modules[MODULE].build_mapping_provenance = lambda ctx, p, s: dict(mapping_fixture(p, s), schema="other/9")
    mp = svc._mapping_provenance({"package_id": "PKG-X", "snapshot_id": "SNAP-X"})
    assert mp["status"] == "UNAVAILABLE" and "contract I-3" in mp["reason"]

    def boom(ctx, p, s):
        raise RuntimeError(r"store offline: C:\ws\packages\PKG-X\mapping.json and /srv/ws/x.json")
    sys.modules[MODULE].build_mapping_provenance = boom
    mp = svc._mapping_provenance({"package_id": "PKG-X", "snapshot_id": "SNAP-X"})
    assert mp["status"] == "UNAVAILABLE"
    assert mp["reason"] == "mapping provenance could not be built: RuntimeError: store offline: <path> and <path>"


@pytest.mark.xfail(not HAVE_MODULE, strict=True, reason="Agent A's smartparser/webapp/mapping_provenance.py (contract I-3) "
                                                         "is not merged into this branch yet")
def test_mapping_provenance_module_is_installed():
    from smartparser.webapp.mapping_provenance import build_mapping_provenance  # noqa: F401


# ============================================================================================ subprocess plumbing
@needs_closure
def test_runner_passes_structured_diagnostics_and_renders_the_mapping_table(tmp_path):
    class DiagRunner(ClosureRunner):
        SCRIPT = RUNNER_DEFS + (
            "\ndef op_boom(req):\n    e = ValueError('refused')\n    e.diagnostics = {'rejected_text_leaks': "
            "[{'investigation_id': 'INV-1', 'text': 't', 'rejected_source': 's', 'found_at': ['p']}], 'stage': 'x'}\n"
            "    raise e\nOPS['boom'] = op_boom\n") + RUNNER_MAIN
    with pytest.raises(ClosureRunnerError) as e:
        DiagRunner(UC042_ROOT, CLOSURE_PY)._call("boom", {}, ai=False, scratch=tmp_path / "s")
    assert e.value.diagnostics["rejected_text_leaks"][0]["investigation_id"] == "INV-1" and "refused" in str(e.value)
    # provenance PDF: the per-file column mapping table, readable
    doc = {"final_pack_id": "FAP-T", "case_ref": "RF-2026-09-001", "recon_run_id": "RECON-X", "snapshot_id": "SNAP-X",
           "package_id": "PKG-X", "pack_id": "PACK-X", "zip": {"filename": "a.zip", "sha256": "00"},
           "authorised_by": USER, "system_reviewer_id": "sys", "generated_at": "2026-11-22T10:00:00+00:00",
           "source_files": [], "decisions": [], "statement": "Statement.",
           "mapping_provenance": dict(mapping_fixture(), status="AVAILABLE", reason=None)}
    pj, pp = tmp_path / "p.json", tmp_path / "p.pdf"
    pj.write_text(json.dumps(doc), encoding="utf-8")
    ClosureRunner(UC042_ROOT, CLOSURE_PY).provenance_pdf(pj, pp, tmp_path / "s")
    text = _pdf_text(pp.read_bytes())
    for s in ("Column mapping provenance", "bank_export_sept.csv", "Txn Ref", "transaction_id", "MAPPED: deterministic",
              "(exact header)", "rule IN-11.transaction_id v1.2", "proposal MP-0001", "MAPPED: AI proposal",
              "fix8.alice@ringfence.test", "not recorded", "IGNORED: ignored by analyst", "PASS (audit #12, #13)",
              "Note: decided_by"):
        assert s in text, s
    doc["mapping_provenance"] = {"status": "UNAVAILABLE", "reason": "the mapping provenance module is not installed"}
    pj.write_text(json.dumps(doc), encoding="utf-8")
    ClosureRunner(UC042_ROOT, CLOSURE_PY).provenance_pdf(pj, pp, tmp_path / "s")
    assert "UNAVAILABLE: the mapping provenance module is not installed" in _pdf_text(pp.read_bytes())


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(data)).pages)


# ============================================================================================ D5 app side
class RefusingRunner(DoubleRunner):
    """TEST DOUBLE: the preview operation is refused with library-style diagnostics (no subprocess, no AI)."""

    def preview(self, **kw):
        raise ClosureRunnerError(
            "final pack failed validation: INV-X: text of the REJECTED investigation's AI output appears in the report",
            "FinalPackValidationError", [],
            {"stage": "assemble_preview", "errors": ["INV-X: text ..."],
             "rejected_text_leaks": [{"investigation_id": "INV-X", "text": "Rejected-only sentence of the test double.",
                                      "rejected_source": "investigation_summary",
                                      "found_at": ["closing_summary.output.summary_text"]}],
             "closing_summary": {"status": "GENERATED", "output": {"summary_text": "..."}}})


@needs_closure
def test_failed_preview_keeps_diagnostics_in_record_audit_and_view(tmp_path):
    ctx = ctx_for(tmp_path, runner_cls=RefusingRunner)
    ref = reconcile(ctx, make_zip())
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    j = wait_job(ctx, pv["job_id"])
    assert j["state"] == "failed" and j["result"]["failure_id"].startswith("PVF-")
    ev = [e for e in ctx.events() if e["event_type"] == "CLOSING_PREVIEW_FAILED"][-1]["details"]
    assert ev["failure_id"] == j["result"]["failure_id"] and ev["error_kind"] == "FinalPackValidationError"
    assert ev["rejected_text_leaks"] == [{"investigation_id": "INV-X", "text": "Rejected-only sentence of the test double.",
                                          "rejected_source": "investigation_summary",
                                          "found_at": ["closing_summary.output.summary_text"]}]
    v = R(ctx, "GET", f"cases/{ref}/closure")
    lf = v["review"]["last_preview_failure"]
    assert lf["failure_id"] == ev["failure_id"] and lf["rejected_text_leaks"][0]["text"].startswith("Rejected-only")
    c = ctx.closure._load(ref, v["recon_run_id"])
    rec = json.loads((ctx.closure._session_dir(c, v["review"]["review_id"]) / "preview_failures" /
                      f"{lf['failure_id']}.json").read_text(encoding="utf-8"))
    assert rec["closing_summary"]["status"] == "GENERATED" and rec["stage"] == "assemble_preview"
    assert rec["inputs_fingerprint"] and rec["selections"] is not None
    assert v["review"]["current_preview"] is None                       # a refused preview is never a preview


# ============================================================================================ D8 + D3 journeys
def _generate_clean(ctx):
    ref = reconcile(ctx, make_zip())
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    out = R(ctx, "POST", f"cases/{ref}/closure/review/decision", {
        "decision": "GENERATE", "acknowledgement_accepted": True, "acknowledged_summary_unavailable": False,
        "snapshot_sha256": v["review"]["current_preview"]["snapshot_sha256"], "expected_revision": v["revision"]})
    assert wait_job(ctx, out["job_id"])["state"] == "completed"
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "GENERATED" and v["final_pack"]["verified"] is True and v["final_pack"]["integrity"] == "VERIFIED"
    return ref, v, out


def _assert_integrity_failed(ctx, ref, problem):
    v = R(ctx, "GET", f"cases/{ref}/closure")
    assert v["state"] == "INTEGRITY_FAILED" and v["frozen"] is True
    assert v["final_pack"]["verified"] is False and v["final_pack"]["integrity"] == "FAILED"
    assert problem in v["final_pack"]["problems"]
    fp = R(ctx, "GET", f"cases/{ref}/closure/final-pack")
    assert fp["verified"] is False and fp["integrity"] == "FAILED" and problem in fp["problems"]
    for key in ("pdf", "json", "manifest", "provenance.json"):
        assert code_of(lambda: R(ctx, "GET", f"cases/{ref}/closure/final-pack/{key}")) == "INTEGRITY"
    assert code_of(lambda: R(ctx, "POST", f"cases/{ref}/closure/review/preview",
                             {"expected_revision": v["revision"]})) == "CLOSURE_FROZEN"
    return v


@needs_closure
def test_tampered_pdf_shows_integrity_failed_everywhere_and_after_restart(tmp_path, fake_mapping_module):
    ctx = ctx_for(tmp_path)
    ref, v, out = _generate_clean(ctx)
    # D3: the GENERATE comment and the provenance supplement carry the mapping provenance (fixture module)
    assert "Column mapping provenance: 1 file(s), 3 column(s)" in out["decision"]["comment"]
    prov = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.json")[1])
    assert prov["mapping_provenance"]["status"] == "AVAILABLE"
    assert prov["mapping_provenance"]["package_id"] == v["package_id"] and prov["mapping_provenance"]["snapshot_id"] == v["snapshot_id"]
    _, ppdf, _ = R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.pdf")
    assert "proposal MP-0001" in _pdf_text(ppdf)
    final = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/json")[1])
    assert "Column mapping provenance: 1 file(s)" in final["human_review"]["comment"]
    # D8: tamper one byte of report.pdf (size unchanged)
    c = ctx.closure._load(ref, v["recon_run_id"])
    pdf = Path(c["final_pack"]["path"]) / "report.pdf"
    stored_before = json.dumps(c["final_pack"], sort_keys=True)
    b = bytearray(pdf.read_bytes()); b[len(b) // 2] ^= 0x01
    pdf.write_bytes(bytes(b))
    _assert_integrity_failed(ctx, ref, "report.pdf does not match its manifest SHA-256")
    # the stored record is not rewritten, nothing is repaired or re-signed
    assert json.dumps(ctx.closure._load(ref, v["recon_run_id"])["final_pack"], sort_keys=True) == stored_before
    assert pdf.read_bytes() == bytes(b)
    # restart: a new context on the same workspace sees the same failure
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=UC042_ROOT)
    ctx2.closure = ClosureService(ctx2, DoubleRunner(UC042_ROOT, CLOSURE_PY))
    _assert_integrity_failed(ctx2, ref, "report.pdf does not match its manifest SHA-256")


@needs_closure
def test_tampered_manifest_shows_integrity_failed_and_mapping_unavailable_is_visible(tmp_path, monkeypatch):
    if not HAVE_MODULE:
        monkeypatch.setitem(sys.modules, MODULE, None)
    ctx = ctx_for(tmp_path)
    ref, v, out = _generate_clean(ctx)
    prov = json.loads(R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.json")[1])
    if not HAVE_MODULE:                                                 # visible, never invented
        assert prov["mapping_provenance"]["status"] == "UNAVAILABLE"
        assert "Column mapping provenance: UNAVAILABLE" in out["decision"]["comment"]
        _, ppdf, _ = R(ctx, "GET", f"cases/{ref}/closure/final-pack/provenance.pdf")
        assert "UNAVAILABLE: the mapping provenance module is not installed" in _pdf_text(ppdf)
    c = ctx.closure._load(ref, v["recon_run_id"])
    mpath = Path(c["final_pack"]["path"]) / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["final_pack_id"] = m["final_pack_id"] + "-tampered"
    mpath.write_text(json.dumps(m, indent=1), encoding="utf-8")
    _assert_integrity_failed(ctx, ref, "manifest.json differs from the manifest recorded at generation")
    ctx2 = AppContext(root=tmp_path / "ws", authority_path=TEST_POLICY, reviewer=ANALYST, uc042_root=UC042_ROOT)
    ctx2.closure = ClosureService(ctx2, DoubleRunner(UC042_ROOT, CLOSURE_PY))
    _assert_integrity_failed(ctx2, ref, "manifest.json differs from the manifest recorded at generation")


# ============================================================================================ lead items (23 Nov 2026)
def _record_transitions(ctx):
    """Hooks ClosureService._save: every closure write as (revision, the state it implies). The state is derived from
    the written record with _view's own rules for these fields (the hook must not call _view: _save runs under the
    closure lock and _view reads the case store, which other threads lock while waiting for the closure lock)."""
    seen, orig = [], ctx.closure._save

    def implied(c):
        pk = (c.get("pack") or {}).get("status")
        if pk == "PENDING":
            return "PACK_PENDING"
        if pk != "GENERATED":
            return "PACK_UNAVAILABLE"
        return "INVESTIGATING" if c.get("auto_investigation") == "STARTING" else f"AUTO_{c.get('auto_investigation')}"

    def save(c):
        out = orig(c)
        seen.append((out["revision"], implied(out)))
        return out
    ctx.closure._save = save
    return seen


@needs_closure
def test_clean_case_goes_pack_pending_to_ready_with_one_revision_bump(tmp_path):
    """QA E-15 / lead item 2: a clean case never shows INVESTIGATING and its revision does not move after READY
    (previously: pack GENERATED + auto_investigation STARTING, then a second write NOT_REQUIRED)."""
    import threading
    import time as _t
    ctx = ctx_for(tmp_path)
    seen = _record_transitions(ctx)
    polled, stop = [], threading.Event()
    ref = reconcile(ctx, make_zip())

    def poll():                                                          # an independent tight reader of the API view
        while not stop.is_set():
            try:
                v = R(ctx, "GET", f"cases/{ref}/closure")
                polled.append((v["revision"], v["state"]))
            except Exception:
                pass
    t = threading.Thread(target=poll, daemon=True); t.start()
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING",))
    _t.sleep(2.0)                                                        # anything still to come would land now
    stop.set(); t.join(5)
    v2 = R(ctx, "GET", f"cases/{ref}/closure")
    states = [s for _, s in seen]
    assert states == ["PACK_PENDING", "AUTO_NOT_REQUIRED"], seen       # created, then ONE write publishes the pack
    assert "INVESTIGATING" not in {s for _, s in polled}, sorted(set(polled))
    assert v["state"] == "READY" and v2["revision"] == v["revision"] == seen[-1][0]
    assert ctx.closure._load(ref, v["recon_run_id"])["auto_investigation"] == "NOT_REQUIRED"
    pack_ev = [e for e in ctx.events() if e["event_type"] == "AUDIT_PACK_GENERATED"][-1]
    assert (pack_ev["actor_role"], pack_ev["details"]["requested_by"], pack_ev["details"]["auto_investigation"]) == \
        ("system", USER, "NOT_REQUIRED")


class NoAiRunner(DoubleRunner):
    def ai_configuration(self):
        return dict(ClosureRunner.ai_configuration(self), available=False, problem="AI is not configured (test)")


@needs_closure
def test_exceptions_case_without_ai_is_refused_in_the_same_write(tmp_path):
    from .test_closure_service import scenario_zip
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path, runner_cls=NoAiRunner)
    seen = _record_transitions(ctx)
    ref = reconcile(ctx, data, customer, period)
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    assert "INVESTIGATING" not in [s for _, s in seen], seen
    assert ctx.closure._load(ref, v["recon_run_id"])["auto_investigation"] == "REFUSED"
    ev = [e for e in ctx.events() if e["event_type"] == "AI_AUTHORIZATION_REFUSED"][-1]
    assert (ev["actor_role"], ev["details"]["authorized_by"], ev["details"]["kind"]) == ("system", USER, "AUTO_INVESTIGATION")


@needs_closure
def test_system_reviewer_is_the_server_identity_and_roles_are_recorded(tmp_path):
    """Lead item 1 (I-1 follow-up): system_reviewer_id is ctx.server_reviewer everywhere (never the signed-in user);
    a supervisor's closure action is recorded with actor_role supervisor; automatic work is the system."""
    from smartparser.webapp import api, auth
    from .test_closure_service import scenario_zip
    alice, sup = "fix8.alice@ringfence.test", "fix8.supervisor@ringfence.test"
    data, customer, period = scenario_zip("scenario_2")
    ctx = ctx_for(tmp_path)
    h = auth.hash_password("pw-test", 1000)
    ctx.authenticator = auth.Authenticator({alice: h, sup: h}, profiles={sup: {"roles": ["supervisor"]}})

    def RU(method, path, body=None, user=alice):
        return api.route(ctx, method, [p for p in path.split("/") if p], {}, body or {}, user=user)
    import base64
    ref = RU("POST", "cases", {"customer_name": customer, "reporting_period": period, "zip_name": "u.zip",
                               "zip_b64": base64.b64encode(data).decode()})["case_ref"]
    from .test_ringfence_cases import settle
    RU("POST", f"cases/{ref}/start"); settle(ctx, ref, 300)
    RU("POST", f"cases/{ref}/activate", {"confirm": True}); RU("POST", f"cases/{ref}/reconcile"); settle(ctx, ref, 900)
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"))
    RU("POST", f"cases/{ref}/closure/review", {"expected_revision": v["revision"]}, user=alice)
    v = RU("GET", f"cases/{ref}/closure")
    x = next(x for x in v["exceptions"] if x["ai_state"] == "PUBLISHED")
    RU("POST", f"cases/{ref}/closure/review/selections", {"expected_revision": v["revision"], "selections": [
        {"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST"}]}, user=sup)
    server = ctx.server_reviewer.reviewer_id
    run_events = [e for e in ctx.events() if (e.get("details") or {}).get("recon_run_id") == v["recon_run_id"]]
    assert run_events and all(e["details"]["system_reviewer_id"] == server for e in run_events), \
        {(e["event_type"], e["details"]["system_reviewer_id"]) for e in run_events}
    by = {e["event_type"]: e for e in run_events}
    assert (by["CLOSING_REVIEW_OPENED"]["actor_id"], by["CLOSING_REVIEW_OPENED"]["actor_role"]) == (alice, "analyst")
    assert (by["CLOSING_SELECTIONS_CHANGED"]["actor_id"], by["CLOSING_SELECTIONS_CHANGED"]["actor_role"]) == (sup, "supervisor")
    for t in ("AUDIT_PACK_GENERATED", "AI_AUTHORIZED", "AI_INVESTIGATION_QUEUED", "AI_INVESTIGATION_PUBLISHED"):
        assert by[t]["actor_role"] == "system" and alice in (by[t]["details"].get("requested_by"),
                                                             by[t]["details"].get("authorized_by")), (t, by[t])
    c = ctx.closure._load(ref, v["recon_run_id"])
    auths = [json.loads(l) for l in (ctx.closure._dir(ref, c["recon_run_id"]) / "ai_authorizations.jsonl")
             .read_text(encoding="utf-8").splitlines() if l]
    assert auths and all(a["system_reviewer_id"] == server for a in auths)
    assert all(r["system_reviewer_id"] == server for r in ctx.closure._reviews(c))


# ============================================================================================ Windows sharing violations
def test_write_and_read_retry_sharing_violations_and_never_treat_them_as_missing(tmp_path, monkeypatch):
    """Lead item (23 Nov 2026): a transient PermissionError (WinError 5) on replace or read is retried; a persistent one
    propagates; only a missing file yields the default. OFFLINE (monkeypatched Path methods)."""
    import smartparser.packages.store as store
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    p = tmp_path / "closure.json"
    real_replace, real_read = Path.replace, Path.read_text
    fails = {"replace": 3, "read": 3}

    def flaky_replace(self, target):
        if fails["replace"] > 0:
            fails["replace"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_replace(self, target)

    def flaky_read(self, *a, **k):
        if self.name == "closure.json" and fails["read"] > 0:
            fails["read"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(Path, "read_text", flaky_read)
    closure_mod._write_json(p, {"revision": 7})
    assert fails["replace"] == 0 and closure_mod._read_json(p) == {"revision": 7} and fails["read"] == 0
    fails["read"] = 10 ** 6                                           # persistent: raised, not "missing"
    with pytest.raises(PermissionError):
        closure_mod._read_json(p, default="MISSING")
    fails["replace"] = 10 ** 6
    with pytest.raises(PermissionError):
        closure_mod._write_json(p, {"revision": 8})
    fails["read"] = 0
    assert closure_mod._read_json(tmp_path / "absent.json", default="MISSING") == "MISSING"


def test_a_job_that_raises_unexpectedly_ends_failed_and_releases_its_state(tmp_path):
    ctx = ctx_for(tmp_path)
    svc = ctx.closure
    ref, run = "RF-2026-09-001", "RECON-TEST-1"
    c = {"case_ref": ref, "recon_run_id": run, "pack": {"status": "PENDING", "pack_id": None, "reason": None},
         "auto_investigation": None, "revision": 0}
    svc._dir(ref, run).mkdir(parents=True)
    svc._save(c)
    j = ctx._new_job("audit_pack", None, case_ref=ref, recon_run_id=run, result=None)
    j["state"] = "running"

    def boom(job):
        raise PermissionError(5, "Access is denied")              # e.g. a sharing violation that outlived the retries
    svc._safe(boom, j)
    assert j["state"] == "failed" and "PermissionError" in j["error"]
    after = svc._load(ref, run)
    assert after["pack"]["status"] == "UNAVAILABLE" and "unexpected error" in after["pack"]["reason"]


def test_four_readers_and_one_writer_on_the_same_closure_file_never_fail(tmp_path):
    """R2 (lead, 23 Nov 2026): with readers polling the file, retries alone starved the writer (PermissionError after the
    retries). Readers and writers of one path now serialise on an in-process per-path lock. Deterministic stress: 4
    reader threads + 1 writer, 1500 writes, every read sees a complete document, zero errors. OFFLINE, real files."""
    import threading
    p = tmp_path / "registry.json"
    closure_mod._write_json(p, {"n": 0, "pad": "x" * 4000})
    errors, stop, reads = [], threading.Event(), [0]

    def reader():
        while not stop.is_set():
            try:
                d = closure_mod._read_json(p)
                assert d is not None and len(d["pad"]) == 4000, d     # never "missing", never partial
                reads[0] += 1
            except Exception as e:                                   # noqa: BLE001 - every error is a failure here
                errors.append(f"read {type(e).__name__}: {e}")

    ts = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in ts:
        t.start()
    try:
        for n in range(1, 1501):
            closure_mod._write_json(p, {"n": n, "pad": "x" * 4000})
            closure_mod._append(tmp_path / "log.jsonl", {"n": n})
    except Exception as e:                                           # noqa: BLE001
        errors.append(f"write {type(e).__name__}: {e}")
    finally:
        stop.set()
        for t in ts:
            t.join(10)
    assert errors == [], errors[:5]
    assert closure_mod._read_json(p)["n"] == 1500 and len(closure_mod._jsonl(tmp_path / "log.jsonl")) == 1500
    assert reads[0] > 0


# ============================================================================================ open items A/B/C (23 Nov 2026)
def _bare_closure(ctx, ref="RF-2026-09-001", run="RECON-TEST-2", **fields):
    svc = ctx.closure
    svc._dir(ref, run).mkdir(parents=True, exist_ok=True)
    c = {"case_ref": ref, "recon_run_id": run, "snapshot_id": "SNAP-X", "package_id": "PKG-X",
         "pack": {"status": "GENERATED", "pack_id": "PACK-X", "reason": None}, "revision": 0, **fields}
    return svc._save(c)


def test_a_view_revision_equals_disk_when_a_save_lands_while_the_view_is_built(tmp_path, monkeypatch):
    """(A) Torn view: a job saves the closure (and ends) while the view is being built. The returned revision must be the
    on-disk revision, never the previous one (which made the next action fail with 409 CLOSURE_CHANGED)."""
    ctx = ctx_for(tmp_path)
    svc = ctx.closure
    c0 = _bare_closure(ctx)
    ref, run = c0["case_ref"], c0["recon_run_id"]
    monkeypatch.setattr(svc, "_locate", lambda r: (svc._load(ref, run), run))
    calls = []

    def view_with_concurrent_save(c):
        calls.append(c["revision"])
        if len(calls) == 1:                                       # deterministic: one save while the first view builds
            svc._save(svc._load(ref, run))
        return {"revision": c["revision"]}
    monkeypatch.setattr(svc, "_view", view_with_concurrent_save)
    v = svc.view(ref)
    assert v["revision"] == svc._load(ref, run)["revision"] == c0["revision"] + 1, (v, calls)


@needs_closure
def test_b_auto_investigation_outcome_unwritable_never_leaves_investigating(tmp_path, monkeypatch):
    """(B) After the automatic investigations are queued, the closure record cannot be written any more (every _save
    raises: a persistent sharing violation), so the final _bump in the `finally` of _auto_investigations fails, and so
    does the old fallback (_fail_unexpected also writes through _save). The record stays STARTING on disk; the view must
    still not show INVESTIGATING once every job has ended. (Old code: INVESTIGATING forever.)"""
    from .test_closure_service import scenario_zip
    ctx = ctx_for(tmp_path)
    svc = ctx.closure
    state = {"unwritable": False, "refused": 0}
    real_inner, real_save = svc._auto_investigations_inner, svc._save

    def inner(*a, **k):
        out = real_inner(*a, **k)                                  # investigations are queued normally ...
        state["unwritable"] = True                                 # ... then the record becomes unwritable
        return out

    def save(c):
        if state["unwritable"]:
            state["refused"] += 1
            raise PermissionError(5, "Access is denied (injected, persistent)")
        return real_save(c)
    monkeypatch.setattr(svc, "_auto_investigations_inner", inner)
    monkeypatch.setattr(svc, "_save", save)
    data, customer, period = scenario_zip("scenario_2")
    ref = reconcile(ctx, data, customer, period)
    run = next(j["run_id"] for j in ctx.jobs.values() if j.get("kind") == "reconciliation" and j.get("run_id"))
    v = wait_closure(ctx, ref, lambda v: v["state"] not in ("PACK_PENDING", "INVESTIGATING"), timeout=180)
    assert state["refused"] >= 3                                   # the finally-bump was attempted and refused
    assert svc._load(ref, run)["auto_investigation"] == "STARTING"  # the record really stayed STARTING on disk
    assert v["state"] != "INVESTIGATING"
    jobs = [j for j in ctx.jobs.values() if j.get("case_ref") == ref]
    assert jobs and all(j["state"] not in ("queued", "running") for j in jobs), [(j["kind"], j["state"]) for j in jobs]


def _ready_clean_case(ctx):
    ref = reconcile(ctx, make_zip())
    v = wait_closure(ctx, ref, lambda v: v["state"] != "PACK_PENDING")
    pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
    assert wait_job(ctx, pv["job_id"])["state"] == "completed"
    return ref, R(ctx, "GET", f"cases/{ref}/closure")


@needs_closure
def test_c_generate_whose_job_cannot_start_is_generation_failed_never_generating(tmp_path, monkeypatch):
    """(C) decide_review GENERATE: (1) _job raises; (2) the job exists but its thread cannot start. Each time the error is
    re-raised, the review is GENERATION_FAILED (never GENERATING) and a created job is 'failed'."""
    ctx = ctx_for(tmp_path)
    svc = ctx.closure
    ref, v = _ready_clean_case(ctx)
    run = v["recon_run_id"]
    body = lambda v: {"decision": "GENERATE", "acknowledgement_accepted": True,                # noqa: E731
                      "snapshot_sha256": v["review"]["current_preview"]["snapshot_sha256"], "expected_revision": v["revision"]}
    real_job = svc._job

    def job_fails(kind, c, **extra):
        if kind == "final_pack":
            raise RuntimeError("injected: job store unavailable")
        return real_job(kind, c, **extra)
    monkeypatch.setattr(svc, "_job", job_fails)
    with pytest.raises(RuntimeError, match="injected: job store unavailable"):
        svc.decide_review(ref, body(v), USER)
    c = svc._load(ref, run)
    assert svc._session(c)["status"] == "GENERATION_FAILED" and "injected" in c["last_generation_failure"]["error"]
    assert not [j for j in ctx.jobs.values() if j.get("kind") == "final_pack" and j.get("case_ref") == ref]
    assert R(ctx, "GET", f"cases/{ref}/closure")["state"] == "GENERATION_FAILED"
    # (2) the job is created, its thread cannot start
    monkeypatch.setattr(svc, "_job", real_job)
    v = R(ctx, "GET", f"cases/{ref}/closure")
    if v["review"]["current_preview"] is None or v["review"]["current_preview"]["stale"]:
        pv = R(ctx, "POST", f"cases/{ref}/closure/review/preview", {"expected_revision": v["revision"]})
        if pv.get("job_id"):
            assert wait_job(ctx, pv["job_id"])["state"] == "completed"
        v = R(ctx, "GET", f"cases/{ref}/closure")

    def thread_fails(fn, *args):
        raise RuntimeError("injected: cannot start thread")
    monkeypatch.setattr(svc, "_thread", thread_fails)
    with pytest.raises(RuntimeError, match="injected: cannot start thread"):
        svc.decide_review(ref, body(v), USER)
    c = svc._load(ref, run)
    assert svc._session(c)["status"] == "GENERATION_FAILED"
    fj = [j for j in ctx.jobs.values() if j.get("kind") == "final_pack" and j.get("case_ref") == ref]
    assert len(fj) == 1 and fj[0]["state"] == "failed" and "could not be started" in fj[0]["error"]
    assert R(ctx, "GET", f"cases/{ref}/closure")["state"] == "GENERATION_FAILED"


def test_d_registry_corrupt_raises_missing_is_empty_and_a_corrupt_file_is_never_overwritten(tmp_path, monkeypatch):
    """(D) _registry: a missing file is an empty registry; a corrupt one raises. An investigation job that finishes while
    the registry is corrupt must not write it back (the old default would have wiped every published investigation)."""
    ctx = ctx_for(tmp_path)
    svc = ctx.closure
    c = _bare_closure(ctx)
    assert svc._registry(c) == {"investigations": {}, "attempts": []}          # missing: empty
    reg = svc._dir(c["case_ref"], c["recon_run_id"]) / "registry.json"
    corrupt = b'{"investigations": {"INV-1": {"exception_id": "EXC-1"}}, "attempts": [  <truncated'
    reg.write_bytes(corrupt)
    with pytest.raises(ValueError):
        svc._registry(c)
    monkeypatch.setattr(svc.runner, "investigate", lambda **kw: {"persist_outcome": "NOT_PUBLISHED", "ai_requests": [],
                                                                  "failure_reason": "test double: not published"})
    j = ctx._new_job("investigation", None, case_ref=c["case_ref"], recon_run_id=c["recon_run_id"],
                     exception_id="EXC-1", attempt=1, result=None)
    svc._safe(svc._run_investigation, j)
    assert reg.read_bytes() == corrupt                                          # never overwritten
    assert j["state"] == "failed"
