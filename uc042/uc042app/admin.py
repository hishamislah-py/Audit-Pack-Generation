"""Local maintenance commands for the publication registry (run while the backend is stopped; they take the same
instance lock):

    python -m uc042app.admin import-legacy-investigations [--pack PACK-...] [--dry-run]
    python -m uc042app.admin verify-registry
    python -m uc042app.admin db-upgrade                      apply Alembic migrations to UC042_DATABASE_URL
    python -m uc042app.admin db-status                       current and latest migration
    python -m uc042app.admin import-file-state --from DIR [--dry-run]   copy file-backed state into the database
    python -m uc042app.admin import-poc-scenarios [--dry-run]           register the September POC scenario packs and their
                                                                        source documents (in place, read-only) in the archive
    python -m uc042app.admin verify-pack-references           read-only: every pack reference in the database resolves
                                                                        to a verified pack of the same period and hash
    python -m uc042app.admin unify-databases --source-database DB --source-profile NAME [--approve-period-merge PER-...]
                                             [--source-state-dir DIR] [--dry-run]
                                                                        copy a legacy database into this one (uc042app.db.unify)
    python -m uc042app.admin record-investigation-authorization --investigation-id INV-... --status STATUS --basis TEXT
                                                                        append an authorisation decision (never changes artefacts)
    python -m uc042app.admin list-investigation-authorizations

Legacy import registers existing published investigations that pass verify_published as LEGACY_BASELINE_IMPORT. It never
modifies an investigation artefact and never regenerates an investigation ID.
"""
import argparse
import sys

from .config import ConfigurationError, Settings
from .errors import AppError
from .services import Services
from .services.registry import RegistrationRefused


def _services():
    svc = Services(Settings.from_env())
    svc._instance.acquire()
    return svc


def _release(svc):
    svc._instance.release()
    if svc.engine is not None:
        svc.engine.dispose()


def _database_url():
    url = Settings.from_env().database_url
    if not url:
        raise ConfigurationError("UC042_DATABASE_URL is not set (see uc042/.env.example)")
    return url


def _safe(url):
    from sqlalchemy.engine import make_url
    return make_url(url).render_as_string(hide_password=True)


def db_upgrade(args):
    from .db import upgrade
    url = _database_url()
    upgrade(url, args.revision)
    print(f"{_safe(url)}: upgraded to {args.revision}")


def db_status(args):
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from .db import alembic_config, make_engine
    url = _database_url()
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    print(f"{_safe(url)}: current {current or 'none'}, latest {head}{'' if current == head else ' (run db-upgrade)'}")
    sys.exit(0 if current == head else 1)


def import_file_state(args):
    from .db.importer import import_file_state as run
    svc = _services()
    try:
        if not svc.database:
            raise ConfigurationError("UC042_DATABASE_URL is not set: there is no database to import into")
        report = run(args.source, svc.repos, dry_run=args.dry_run)
    finally:
        _release(svc)
    for kind, key, outcome, note in report.rows:
        if outcome != "UNCHANGED":
            print(f"{outcome:<12} {kind:<18} {key}{'  ' + note if note else ''}")
    print(f"{report.count('IMPORTED') or report.count('WOULD_IMPORT')} to import / imported, {report.count('UNCHANGED')} unchanged, "
          f"{len(report.conflicts)} conflict(s); the source folder was not modified")
    sys.exit(1 if report.conflicts else 0)


def import_legacy(args):
    svc = _services()
    try:
        for pack_id in [args.pack] if args.pack else svc.packs.pack_ids():
            pack = svc.packs.load(pack_id)
            for d in sorted((svc.investigations.root_for(pack_id) / pack_id).glob("EXC-*/INV-*")):
                if args.dry_run:
                    problems = svc.registry.check(d, pack)
                    print(f"{d.name}: {'registered' if not problems else 'would import (' + '; '.join(problems) + ')'}")
                    continue
                try:
                    entry, created = svc.registry.import_legacy(d, pack, svc.settings.analyst_id)
                    print(f"{d.name}: {'imported' if created else 'already registered'} as {entry['record_type']} (seq {entry['seq']})")
                except RegistrationRefused as e:
                    print(f"{d.name}: NOT imported: {e}")
    finally:
        _release(svc)


def verify_registry(args):
    """The registry file is well-formed, and every registered investigation still matches its entry."""
    svc = _services()
    failed = False
    try:
        problems = svc.registry.problems()
        for p in problems:
            print(f"registry: {p}")
        entries = [] if problems else svc.registry.entries()
        for e in entries:
            dirs = list(svc.investigations.root_for(e["pack_id"]).glob(f"{e['pack_id']}/{e['exception_id']}/{e['investigation_id']}"))
            issues = svc.registry.check(dirs[0], svc.packs.load(e["pack_id"])) if dirs else ["artefact directory not found"]
            failed |= bool(issues)
            auth = svc.investigations.authorization(e["investigation_id"])
            print(f"{e['seq']:>4} {e['record_type']:<23} {e['investigation_id']}: {'OK' if not issues else '; '.join(issues)}"
                  + (f"  [authorisation: {auth['status']}]" if auth else ""))
        print(f"{len(entries)} entries; {'problems found' if problems or failed else 'all verified'}")
    finally:
        _release(svc)
    sys.exit(1 if problems or failed else 0)


def import_poc_scenarios(args):
    svc = _services()
    try:
        if not svc.database:
            raise ConfigurationError("UC042_DATABASE_URL is not set: there is no archive to register the scenarios in")
        added = svc.monthly.unregistered_packs() if args.dry_run else svc.monthly.sync_packs()
        rows = svc.monthly.import_poc_documents(dry_run=args.dry_run)
    finally:
        _release(svc)
    print(f"{len(added)} pack(s) {'would be' if args.dry_run else 'newly'} registered under their period"
          + (" (dry run: nothing written)" if args.dry_run else ""))
    for r in rows:
        state = "would register" if args.dry_run else ("NOT registered" if r["problems"] else "registered")
        print(f"{r['scenario_id']:<5} {r['pack_id']}: {state} {r['documents']} document(s)"
              + (f"; problems: {'; '.join(r['problems'])}" if r["problems"] else ""))
    if not rows:
        print("nothing to register (already registered)")
    sys.exit(1 if any(r["problems"] for r in rows) else 0)


def verify_pack_references(args):
    """Read-only: every pack reference in the application state resolves to a verified pack of the same period and
    content hash. Changes nothing; exits 1 on any problem."""
    svc = _services()
    try:
        if not svc.database:
            raise ConfigurationError("UC042_DATABASE_URL is not set: there are no database references to verify")
        rep = svc.monthly.pack_references()
    finally:
        _release(svc)
    for period, packs in sorted(rep["periods"].items()):
        print(f"{period}: {len(packs)} registered pack(s)")
        for pid in sorted(packs):
            print(f"  {pid}")
    for p in rep["problems"]:
        print(f"PROBLEM {p['source']} {p['key']}: {p['pack_id']}: {p['problem']}")
    if rep["unregistered_packs"]:
        print(f"{len(rep['unregistered_packs'])} verified pack(s) in the packs root are not registered under a period")
    print(f"{rep['references']} reference(s) checked; {len(rep['problems'])} problem(s)")
    sys.exit(1 if rep["problems"] else 0)


def unify_databases(args):
    """Copy a legacy database into UC042_DATABASE_URL (one transaction; stops on any unapproved collision)."""
    from .db.unify import UnificationStopped, dumps, unify
    from .storage import InstanceLock
    svc = _services()
    source_lock = InstanceLock(args.source_state_dir) if args.source_state_dir else None
    try:
        if not svc.database:
            raise ConfigurationError("UC042_DATABASE_URL is not set: there is no unified database")
        if source_lock is not None:
            source_lock.acquire()  # the legacy backend must be stopped: its instance lock must be free
        report = unify(svc.engine, args.source_database, args.source_profile, tuple(args.approve_period_merge or ()),
                       dry_run=args.dry_run, recorded_by=svc.settings.analyst_id)
    except UnificationStopped as e:
        sys.exit(f"STOPPED (nothing written): {e}")
    finally:
        if source_lock is not None:
            source_lock.release()
        _release(svc)
    print(dumps(report))


def record_authorization(args):
    """Append an authorisation decision for a published investigation. The artefact and its registry entry are unchanged."""
    from .services.investigations import AUTHORIZATION_STATUSES
    if args.status not in AUTHORIZATION_STATUSES:
        raise ConfigurationError(f"status must be one of {', '.join(AUTHORIZATION_STATUSES)}")
    if len(args.basis.strip()) < 10:
        raise ConfigurationError("the basis must explain the decision (at least 10 characters)")
    svc = _services()
    try:
        if svc.repos.authorizations is None:
            raise ConfigurationError("UC042_DATABASE_URL is not set: authorisation decisions are kept in the database")
        svc.investigations.locate(args.investigation_id)  # the published artefact must exist (never created or changed here)
        row = svc.repos.authorizations.record(args.investigation_id, args.status, args.basis.strip(), svc.settings.analyst_id)
        svc.repos.activity.append({"at": row["recorded_at"], "actor": svc.settings.analyst_id, "action": "INVESTIGATION_AUTHORIZATION_RECORDED",
                                   "entity_type": "investigation", "entity_id": args.investigation_id,
                                   "details": {"status": args.status, "basis": args.basis.strip()[:500]}})
    finally:
        _release(svc)
    print(f"{row['investigation_id']}: {row['status']} recorded (#{row['id']})")


def list_authorizations(args):
    svc = _services()
    try:
        rows = svc.repos.authorizations.list() if svc.repos.authorizations is not None else []
    finally:
        _release(svc)
    for r in rows:
        print(f"#{r['id']:<3} {r['recorded_at']} {r['investigation_id']}: {r['status']} - {r['basis']}")
    print(f"{len(rows)} decision(s)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m uc042app.admin", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("import-legacy-investigations", help="register pre-registry investigations that verify now")
    i.add_argument("--pack")
    i.add_argument("--dry-run", action="store_true")
    i.set_defaults(fn=import_legacy)
    v = sub.add_parser("verify-registry", help="check the registry file and every registered artefact")
    v.set_defaults(fn=verify_registry)
    u = sub.add_parser("db-upgrade", help="apply database migrations (Alembic)")
    u.add_argument("--revision", default="head")
    u.set_defaults(fn=db_upgrade)
    sub.add_parser("db-status", help="show the database migration state").set_defaults(fn=db_status)
    f = sub.add_parser("import-file-state", help="copy file-backed application state into the database (never deletes)")
    f.add_argument("--from", dest="source", required=True)
    f.add_argument("--dry-run", action="store_true")
    f.set_defaults(fn=import_file_state)
    s = sub.add_parser("import-poc-scenarios", help="register the POC scenario packs and source documents in the monthly archive")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=import_poc_scenarios)
    r = sub.add_parser("verify-pack-references", help="read-only: check every pack reference in the database against packs_root")
    r.set_defaults(fn=verify_pack_references)
    un = sub.add_parser("unify-databases", help="copy a legacy UC-042 database into this one (one transaction, resumable)")
    un.add_argument("--source-database", required=True)
    un.add_argument("--source-profile", required=True, help="storage profile of the source's artefacts, e.g. historical-demo")
    un.add_argument("--approve-period-merge", action="append", help="a period ID whose two records may be merged (repeatable)")
    un.add_argument("--source-state-dir", help="the legacy backend's application-state folder (its instance lock must be free)")
    un.add_argument("--dry-run", action="store_true")
    un.set_defaults(fn=unify_databases)
    ra = sub.add_parser("record-investigation-authorization", help="append an authorisation decision for a published investigation")
    ra.add_argument("--investigation-id", required=True)
    ra.add_argument("--status", required=True)
    ra.add_argument("--basis", required=True)
    ra.set_defaults(fn=record_authorization)
    sub.add_parser("list-investigation-authorizations", help="list authorisation decisions").set_defaults(fn=list_authorizations)
    args = p.parse_args(argv)
    try:
        args.fn(args)
    except (ConfigurationError, AppError) as e:
        sys.exit(f"error: {getattr(e, 'detail', e)}")


if __name__ == "__main__":
    main()
