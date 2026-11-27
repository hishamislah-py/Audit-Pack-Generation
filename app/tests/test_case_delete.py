"""24 Nov 2026 (owner): completed cases have their own page and can be deleted. Deleting moves the case record to
cases/deleted (nothing else is touched), is audited, and a deleted case's reference is never reused."""
import pytest

from smartparser.webapp.cases import CaseError

from .test_ringfence_cases import ctx_for, make_zip


def completed(ctx, name):
    c = ctx.cases.create(name, "2026-09", "submission.zip", make_zip())
    c["status"], c["completed"] = "COMPLETED", {"case_status": "CLEAN", "at": "2026-09-30T00:00:00+00:00"}
    ctx.cases._save(c)
    return c["case_ref"]


def code(fn):
    with pytest.raises(CaseError) as e:
        fn()
    return e.value.args[1] if len(e.value.args) > 1 else getattr(e.value, "code", None)


def test_delete_moves_the_record_audits_and_never_reuses_the_number(tmp_path):
    ctx = ctx_for(tmp_path)
    r1, r2 = completed(ctx, "A Ltd"), completed(ctx, "B Ltd")
    assert (r1, r2) == ("RF-2026-09-001", "RF-2026-09-002")
    out = ctx.cases.delete(r2, True)
    assert out["deleted"] and out["kept_at"].startswith("cases")
    assert r2 not in ctx.cases.refs() and r2 not in [x["case_ref"] for x in ctx.cases.queue()["items"]]
    assert list((ctx.root / "cases" / "deleted").glob(f"{r2}__*.json"))
    ev = [e for e in ctx.events() if e["event_type"] == "CASE_DELETED"]
    assert len(ev) == 1 and ev[0]["details"]["case_ref"] == r2
    # numbering: the deleted RF-2026-09-002 is never handed out again
    assert ctx.cases.create("C Ltd", "2026-09", "submission.zip", make_zip())["case_ref"] == "RF-2026-09-003"
    ctx.cases.delete(r1, True)
    assert ctx.cases.create("D Ltd", "2026-09", "submission.zip", make_zip())["case_ref"] == "RF-2026-09-004"


def test_only_completed_cases_and_only_with_confirmation(tmp_path):
    ctx = ctx_for(tmp_path)
    waiting = ctx.cases.create("W Ltd", "2026-09", "submission.zip", make_zip())["case_ref"]
    with pytest.raises(CaseError) as e:
        ctx.cases.delete(waiting, True)
    assert "only a completed case can be deleted" in str(e.value.args)
    done = completed(ctx, "Done Ltd")
    with pytest.raises(CaseError) as e:
        ctx.cases.delete(done, None)
    assert "confirmation" in str(e.value.args)
    assert done in ctx.cases.refs()
