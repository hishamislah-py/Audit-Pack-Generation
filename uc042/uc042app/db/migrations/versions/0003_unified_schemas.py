"""one database, two schemas (audit, operations); period storage profile; exception cases; investigation authorisation
decisions; record provenance (database unification)

Moves the twelve existing tables out of public with ALTER TABLE ... SET SCHEMA (rows, keys, indexes and the activity
sequence move with them; nothing is copied or rewritten). Adds the foreign keys the model always implied, two lookup
indexes, reconciliation_periods.storage_profile (server default '', i.e. the backend's primary roots) and four new tables.
alembic_version stays in public. Downgrade reverses every step, but refuses while the new tables or storage_profile hold
data the drop would lose: after a data migration, the rollback is the pre-migration backup, not a downgrade.

Revision ID: 0003_unified_schemas
Revises: 0002_title_submissions
Create Date: 2026-11-04 13:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_unified_schemas'
down_revision = '0002_title_submissions'
branch_labels = None
depends_on = None

AUDIT, OPERATIONS = 'audit', 'operations'
OWNERSHIP = {
    'reconciliation_periods': AUDIT, 'period_packs': AUDIT, 'processing_runs': AUDIT, 'review_sessions': AUDIT,
    'review_decisions': AUDIT, 'previews': AUDIT, 'final_pack_records': AUDIT, 'investigation_registry': AUDIT,
    'upload_batches': OPERATIONS, 'source_documents': OPERATIONS, 'jobs': OPERATIONS, 'activity_events': OPERATIONS,
}
NEW_TABLES = ((OPERATIONS, 'exception_case_entries'), (OPERATIONS, 'exception_cases'), (AUDIT, 'record_provenance'),
              (AUDIT, 'investigation_authorizations'))


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    for schema in (AUDIT, OPERATIONS):
        op.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}')
    for table, schema in OWNERSHIP.items():
        op.execute(f'ALTER TABLE public.{table} SET SCHEMA {schema}')

    op.add_column('reconciliation_periods', sa.Column('storage_profile', sa.String(length=32), nullable=False, server_default=''),
                  schema=AUDIT)
    op.create_foreign_key('fk_period_packs_processing_run', 'period_packs', 'processing_runs', ['processing_run_id'], ['run_id'],
                          source_schema=AUDIT, referent_schema=AUDIT)
    op.create_foreign_key('fk_source_documents_replaces', 'source_documents', 'source_documents', ['replaces_document_id'],
                          ['document_id'], source_schema=OPERATIONS, referent_schema=OPERATIONS)
    op.create_index('ix_period_packs_pack_id', 'period_packs', ['pack_id'], schema=AUDIT)
    op.create_index('ix_source_documents_replaces', 'source_documents', ['replaces_document_id'], schema=OPERATIONS)

    op.create_table(
        'investigation_authorizations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('investigation_id', sa.String(length=48), nullable=False, index=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('basis', sa.Text(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        schema=AUDIT)
    op.create_table(
        'record_provenance',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('migration_id', sa.String(length=48), nullable=False, index=True),
        sa.Column('source_database', sa.String(length=64), nullable=False),
        sa.Column('source_table', sa.String(length=64), nullable=False),
        sa.Column('source_key', sa.String(length=256), nullable=False),
        sa.Column('target_table', sa.String(length=64), nullable=False),
        sa.Column('target_key', sa.String(length=256), nullable=False),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('source_row', _json(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('source_database', 'source_table', 'source_key', name='uq_record_provenance_source'),
        schema=AUDIT)
    op.create_table(
        'exception_cases',
        sa.Column('case_id', sa.String(length=40), primary_key=True),
        sa.Column('period_id', sa.String(length=16), sa.ForeignKey(f'{AUDIT}.reconciliation_periods.period_id'), nullable=False,
                  index=True),
        sa.Column('pack_id', sa.String(length=64), nullable=False, index=True),
        sa.Column('exception_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('human_resolution', sa.String(length=32), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('pack_id', 'exception_id', name='uq_exception_cases_pack_exception'),
        schema=OPERATIONS)
    op.create_table(
        'exception_case_entries',
        sa.Column('entry_id', sa.String(length=40), primary_key=True),
        sa.Column('case_id', sa.String(length=40), sa.ForeignKey(f'{OPERATIONS}.exception_cases.case_id'), nullable=False,
                  index=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('evidence_refs', _json(), nullable=False),
        sa.Column('details', _json(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.UniqueConstraint('case_id', 'seq', name='uq_exception_case_entries_seq'),
        schema=OPERATIONS)


def downgrade():
    conn = op.get_bind()
    held = {f'{s}.{t}': conn.execute(sa.text(f'SELECT count(*) FROM {s}.{t}')).scalar() for s, t in NEW_TABLES}
    held['audit.reconciliation_periods (storage_profile set)'] = conn.execute(
        sa.text("SELECT count(*) FROM audit.reconciliation_periods WHERE storage_profile <> ''")).scalar()
    held = {k: v for k, v in held.items() if v}
    if held:
        raise RuntimeError(f'downgrade would discard records ({held}); restore the pre-migration backup instead '
                           '(docs/audit_pack/19_..., rollback procedure)')
    for schema, table in NEW_TABLES:
        op.drop_table(table, schema=schema)
    op.drop_index('ix_source_documents_replaces', table_name='source_documents', schema=OPERATIONS)
    op.drop_index('ix_period_packs_pack_id', table_name='period_packs', schema=AUDIT)
    op.drop_constraint('fk_source_documents_replaces', 'source_documents', schema=OPERATIONS, type_='foreignkey')
    op.drop_constraint('fk_period_packs_processing_run', 'period_packs', schema=AUDIT, type_='foreignkey')
    op.drop_column('reconciliation_periods', 'storage_profile', schema=AUDIT)
    for table, schema in OWNERSHIP.items():
        op.execute(f'ALTER TABLE {schema}.{table} SET SCHEMA public')
    for schema in (AUDIT, OPERATIONS):
        op.execute(f'DROP SCHEMA {schema}')  # no CASCADE: fails if anything unexpected is left in the schema
