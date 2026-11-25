"""Database unification: copy a legacy UC-042 application database (e.g. uc042_history) into the unified database.

    python -m uc042app.admin unify-databases --source-database uc042_history --source-profile historical-demo \
        [--approve-period-merge PER-2026-09] [--dry-run]

The unified database is UC042_DATABASE_URL, migrated to head (0003: schemas audit and operations). The source database is
on the same server, at revision 0002_title_submissions (tables in public). The source is only read (READ ONLY, REPEATABLE
READ snapshot); nothing in it is changed.

Rules (the run stops, and nothing is written, on anything not covered):
  * One transaction on the target. A failure or a stop rolls everything back: no partially migrated record exists.
  * Resumable and idempotent: every source row gets a record_provenance row (source database, table, key -> target key,
    action, the complete original row). A source row that already has one is skipped, so a re-run copies nothing twice;
    new source rows are copied by a re-run, and a migrated row that has since CHANGED in the source stops the run.
  * Identifiers are preserved. A source key already present in the target is accepted only if the rows are identical
    (IDENTICAL) or the period is listed in --approve-period-merge (MERGED, rule below); any other collision stops the run.
  * Activity events are the only renumbered records (their serial IDs overlap): a new ID, with the original in provenance.
  * Approved period merge (business decision, report 19): the target's status is kept unless it is EMPTY (an EMPTY source
    status never overwrites a processed one), the target's title is kept unless empty (then the source title is used),
    last_processed_at is the later of the two, and the target row as it was before the merge is recorded in provenance
    (MERGE_TARGET) next to the source row (MERGED). Pack references and activity trails of both are kept.
  * Files are verified before anything is written: every source pack reference must be a verified pack with the
    registered content hash in the source profile's packs root; every registry entry's artefact must match its pinned
    hashes; every GENERATED final-pack record must point to a final pack that verifies. A mismatch stops the run.
  * Copied periods of the source profile get storage_profile = that profile; a source period outside the profile may be
    copied only if it has no packs (otherwise its storage would be ambiguous: stop).
  * The publication registry is copied verbatim (no renumbering): a registry seq already used in the target by a different
    entry stops the run.
"""
import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from uc042lib.final_pack.persistence import verify_final_pack
from uc042lib.final_pack.sources import load_pack
from uc042lib.investigation import roots as inv_roots

from ..services.registry import PINNED, fingerprint
from . import models as m

SOURCE_REVISION = "0002_title_submissions"
# Dependency order (parents first). Keys are the primary-key columns.
TABLES = (
    ("reconciliation_periods", m.ReconciliationPeriod, ("period_id",)),
    ("upload_batches", m.UploadBatch, ("batch_id",)),
    ("source_documents", m.SourceDocument, ("document_id",)),
    ("processing_runs", m.ProcessingRun, ("run_id",)),
    ("period_packs", m.PeriodPack, ("period_id", "pack_id")),
    ("jobs", m.JobRow, ("job_id",)),
    ("review_sessions", m.ReviewSessionRow, ("review_id",)),
    ("review_decisions", m.ReviewDecisionRow, ("review_decision_id",)),
    ("previews", m.PreviewRow, ("preview_id",)),
    ("final_pack_records", m.FinalPackRecordRow, ("review_decision_id",)),
    ("investigation_registry", m.RegistryEntryRow, ("seq",)),
    ("activity_events", m.ActivityEvent, ("id",)),
)
RENUMBERED = {"activity_events"}


class UnificationStopped(Exception):
    """A stop condition: an unexplained collision, a historical data conflict, an artefact integrity failure or an
    ambiguity. Nothing was written."""


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _same(a, b):
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a.astimezone(timezone.utc) == b.astimezone(timezone.utc)
    return a == b


def _key(row, cols):
    return "|".join(str(row[c]) for c in cols)


class Report:
    def __init__(self, migration_id):
        self.migration_id = migration_id
        self.actions = {}  # table -> {action: n}
        self.notes = []

    def count(self, table, action):
        self.actions.setdefault(table, {}).setdefault(action, 0)
        self.actions[table][action] += 1

    def as_dict(self):
        return {"migration_id": self.migration_id, "actions": self.actions, "notes": self.notes}


def _read_source(source_url):
    """Every source table's rows from one consistent, read-only snapshot."""
    from . import make_engine
    engine = make_engine(source_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            revision = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
            if revision != SOURCE_REVISION:
                raise UnificationStopped(f"the source database is at {revision!r}; expected {SOURCE_REVISION} (tables in public)")
            rows = {}
            for table, _, cols in TABLES:
                order = ", ".join(cols)
                rows[table] = [dict(r._mapping) for r in conn.execute(text(f"SELECT * FROM public.{table} ORDER BY {order}"))]
            return rows
    finally:
        engine.dispose()


def _verify_files(src, profile):
    """Stop unless every artefact the source records reference verifies in the source profile's roots."""
    problems = []
    for r in src["period_packs"]:
        try:
            pack = load_pack(r["pack_id"], profile.packs_root)
        except Exception as e:  # missing, unverifiable or modified
            problems.append(f"pack {r['pack_id']}: {type(e).__name__}: {e}")
            continue
        if pack["audit_trail"]["pack_content_sha256"] != r["pack_content_sha256"]:
            problems.append(f"pack {r['pack_id']}: content hash differs from the registered reference")
        if pack["metadata"]["reporting_period"]["period_id"] != r["period_id"]:
            problems.append(f"pack {r['pack_id']}: registered under {r['period_id']}, pack is of another period")
    for r in src["investigation_registry"]:
        e = r["data"]
        d = profile.investigations_root / e["pack_id"] / e["exception_id"] / e["investigation_id"]
        if not d.is_dir():
            problems.append(f"registry seq {r['seq']}: artefact {e['investigation_id']} not found")
            continue
        fp = fingerprint(d)
        bad = [k for k in PINNED if fp[k] != e[k]]
        if bad:
            problems.append(f"registry seq {r['seq']}: {e['investigation_id']} differs from its registered hashes ({', '.join(bad)})")
    for r in src["final_pack_records"]:
        data = r["data"]
        if data.get("status") != "GENERATED":
            continue
        d = profile.final_packs_root / (data.get("final_pack_id") or "")
        issues = verify_final_pack(d) if (d / "manifest.json").is_file() else ["final pack not found"]
        if issues:
            problems.append(f"final pack {data.get('final_pack_id')}: {'; '.join(issues[:3])}")
    if problems:
        raise UnificationStopped("artefact verification failed: " + " | ".join(problems[:10]))


def _merge_period(target_row, source_row):
    """The approved September rule: keep the target's processed status and its pack references; take the source title only
    when the target has none; never let an EMPTY source status overwrite the target."""
    status = target_row["status"] if target_row["status"] != "EMPTY" else source_row["status"]
    title = target_row["title"] or source_row["title"]
    lp = [v for v in (target_row["last_processed_at"], source_row["last_processed_at"]) if v is not None]
    return {"status": status, "title": title, "last_processed_at": max(lp) if lp else None,
            "note": target_row["note"] or source_row["note"]}


def unify(target_engine, source_database, source_profile, approved_merges=(), dry_run=False, recorded_by="migration"):
    """Copy the source database into the target. Returns the report; raises UnificationStopped (nothing written)."""
    profile = inv_roots.storage_profile(source_profile)
    target_url = target_engine.url
    if source_database == target_url.database:
        raise UnificationStopped("the source and target are the same database")
    source_url = make_url(str(target_url.render_as_string(hide_password=False))).set(database=source_database)
    src = _read_source(source_url.render_as_string(hide_password=False))
    _verify_files(src, profile)
    for p in src["reconciliation_periods"]:
        has_packs = any(r["period_id"] == p["period_id"] for r in src["period_packs"])
        if p["period_id"] not in profile.periods and has_packs:
            raise UnificationStopped(f"{p['period_id']} has packs but is outside the {profile.name} profile: storage is ambiguous")

    report = Report(f"UNIFY-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}")
    now = datetime.now(timezone.utc)
    prov = m.RecordProvenanceRow.__table__
    with target_engine.connect() as conn:
        trans = conn.begin()
        try:
            for table, model, cols in TABLES:
                t = model.__table__
                for row in src[table]:
                    key = _key(row, cols)
                    done = conn.execute(select(prov.c.source_row).where(prov.c.source_database == source_database,
                                                                        prov.c.source_table == table, prov.c.source_key == key)).first()
                    if done:
                        if json.loads(json.dumps(done[0], default=str)) != json.loads(json.dumps(
                                {k: _jsonable(v) for k, v in row.items()}, default=str)):
                            raise UnificationStopped(f"{table} {key} changed in the source after it was migrated; the change is "
                                                     "not applied automatically (historical data conflict)")
                        report.count(table, "ALREADY_MIGRATED")
                        continue
                    values = dict(row)
                    action, target_key = "COPIED", key
                    if table in RENUMBERED:
                        values.pop("id")
                        target_key = str(conn.execute(t.insert().values(**values).returning(t.c.id)).scalar())
                        action = "RENUMBERED"
                    else:
                        if table == "reconciliation_periods":
                            values["storage_profile"] = profile.name if row["period_id"] in profile.periods else ""
                        where = [t.c[c] == row[c] for c in cols]
                        existing = conn.execute(select(t).where(*where)).mappings().first()
                        if existing is None:
                            conn.execute(t.insert().values(**values))
                        elif all(_same(existing[c], row[c]) for c in row):
                            action = "IDENTICAL"
                        elif table == "reconciliation_periods" and row["period_id"] in approved_merges:
                            merged = _merge_period(existing, row)
                            conn.execute(prov.insert().values(
                                migration_id=report.migration_id, source_database=target_url.database, source_table=table,
                                source_key=f"{key}|before-merge-{report.migration_id}", target_table=f"{m.AUDIT}.{table}",
                                target_key=key, action="MERGE_TARGET",
                                source_row={k: _jsonable(v) for k, v in existing.items()}, recorded_at=now))
                            conn.execute(t.update().where(*where).values(**merged))
                            action = "MERGED"
                            report.notes.append(f"{key}: merged (status {existing['status']} kept over {row['status']}; "
                                                f"title {merged['title']!r})")
                        else:
                            diff = [c for c in row if not _same(existing[c], row[c])]
                            raise UnificationStopped(f"identifier collision in {table}: {key} exists in the target with "
                                                     f"different values ({', '.join(diff)}); not an approved merge")
                    conn.execute(prov.insert().values(
                        migration_id=report.migration_id, source_database=source_database, source_table=table, source_key=key,
                        target_table=f"{t.schema}.{table}", target_key=target_key, action=action,
                        source_row={k: _jsonable(v) for k, v in row.items()}, recorded_at=now))
                    report.count(table, action)
            act = m.ActivityEvent.__table__
            if conn.dialect.name == "postgresql":
                conn.execute(text("SELECT setval(pg_get_serial_sequence('operations.activity_events', 'id'), "
                                  "(SELECT COALESCE(MAX(id), 1) FROM operations.activity_events))"))
            # Verification inside the transaction: every source row is accounted for exactly once.
            for table, _, cols in TABLES:
                n = conn.execute(select(func.count()).select_from(prov).where(prov.c.source_database == source_database,
                                                                             prov.c.source_table == table)).scalar()
                if n != len(src[table]):
                    raise UnificationStopped(f"verification: {table} has {len(src[table])} source rows but {n} provenance rows")
            conn.execute(act.insert().values(at=now, actor=recorded_by, action="DATABASE_UNIFIED", entity_type="database",
                                             entity_id=report.migration_id,
                                             details={"source_database": source_database, "source_profile": profile.name,
                                                      "actions": report.actions}))
            if dry_run:
                trans.rollback()
                report.notes.append("dry run: rolled back, nothing written")
            else:
                trans.commit()
        except BaseException:
            if trans.is_active:
                trans.rollback()
            raise
    return report


def provenance_summary(engine):
    """(source_database, source_table, action) -> count, for verification and the report."""
    prov = m.RecordProvenanceRow.__table__
    with engine.connect() as conn:
        rows = conn.execute(select(prov.c.source_database, prov.c.source_table, prov.c.action, func.count())
                            .group_by(prov.c.source_database, prov.c.source_table, prov.c.action)).all()
    return {(a, b, c): n for a, b, c, n in rows}


def dumps(report):
    return json.dumps(report.as_dict(), indent=1, sort_keys=True)
