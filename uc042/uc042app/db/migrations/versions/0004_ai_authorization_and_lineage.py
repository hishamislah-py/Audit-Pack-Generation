"""pre-execution AI authorisations (append-only, immutable) and deterministic-pack reassessment lineage

audit.ai_execution_authorizations records the analyst's explicit confirmation of a paid AI operation (an investigation or a
closing summary) BEFORE the job that calls the model is submitted, including confirmations that were refused (for example
an investigation already running). It is distinct from audit.investigation_authorizations, which records decisions about
already-published investigations. On PostgreSQL a trigger refuses UPDATE and DELETE on it: a record cannot be changed.

audit.pack_lineage links a deterministic pack produced by a REASSESSMENT run to the pack it reassesses (its predecessor)
and to the first pack of that reporting-period lineage. Packs with no lineage row (every pack before this revision, and
every independent demonstration scenario) are their own lineage. Final-pack versions are numbered over a lineage.

Downgrade refuses while either table holds data (the rollback is then the pre-migration backup).

Revision ID: 0004_ai_authorization_lineage
Revises: 0003_unified_schemas
Create Date: 2026-11-04 17:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_ai_authorization_lineage'
down_revision = '0003_unified_schemas'
branch_labels = None
depends_on = None

AUDIT = 'audit'
TABLES = ('ai_execution_authorizations', 'pack_lineage')


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


def upgrade():
    op.create_table(
        'ai_execution_authorizations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('authorization_id', sa.String(length=40), nullable=False, unique=True),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('result', sa.String(length=48), nullable=False),
        sa.Column('period_id', sa.String(length=16), nullable=False, index=True),
        sa.Column('pack_id', sa.String(length=64), nullable=False, index=True),
        sa.Column('exception_id', sa.String(length=48), nullable=True),
        sa.Column('review_id', sa.String(length=40), nullable=True),
        sa.Column('case_id', sa.String(length=40), nullable=True),
        sa.Column('job_id', sa.String(length=40), nullable=True, index=True),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('authorized_by', sa.String(length=64), nullable=False),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('details', _json(), nullable=False),
        schema=AUDIT)
    op.create_table(
        'pack_lineage',
        sa.Column('pack_id', sa.String(length=64), primary_key=True),
        sa.Column('period_id', sa.String(length=16), sa.ForeignKey(f'{AUDIT}.reconciliation_periods.period_id'), nullable=False,
                  index=True),
        sa.Column('predecessor_pack_id', sa.String(length=64), nullable=False),
        sa.Column('lineage_root_pack_id', sa.String(length=64), nullable=False, index=True),
        sa.Column('purpose', sa.String(length=16), nullable=False),
        sa.Column('processing_run_id', sa.String(length=40), sa.ForeignKey(f'{AUDIT}.processing_runs.run_id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('change_summary', _json(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        schema=AUDIT)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(f"""
            CREATE FUNCTION {AUDIT}.refuse_ai_authorization_change() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit.ai_execution_authorizations is append-only: % is not allowed', TG_OP;
            END $$""")
        op.execute(f"""
            CREATE TRIGGER ai_execution_authorizations_immutable BEFORE UPDATE OR DELETE ON {AUDIT}.ai_execution_authorizations
            FOR EACH ROW EXECUTE FUNCTION {AUDIT}.refuse_ai_authorization_change()""")


def downgrade():
    conn = op.get_bind()
    held = {t: conn.execute(sa.text(f'SELECT count(*) FROM {AUDIT}.{t}')).scalar() for t in TABLES}
    held = {k: v for k, v in held.items() if v}
    if held:
        raise RuntimeError(f'downgrade would discard records ({held}); restore the pre-migration backup instead')
    if conn.dialect.name == 'postgresql':
        op.execute(f'DROP TRIGGER ai_execution_authorizations_immutable ON {AUDIT}.ai_execution_authorizations')
        op.execute(f'DROP FUNCTION {AUDIT}.refuse_ai_authorization_change()')
    for t in TABLES:
        op.drop_table(t, schema=AUDIT)
