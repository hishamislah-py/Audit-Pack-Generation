"""analyst reviews of AI investigations (append-only, immutable)

audit.investigation_reviews records the analyst's ACCEPT / REJECT decision on one published AI investigation, for the exact
findings it holds (findings SHA-256 and findings schema version), with the reviewer reference, the time, an optional comment
(ACCEPT) or the reason for rejection exactly as written (REJECT). A changed decision is a new row with the next revision and a
reference to the decision it supersedes; (investigation_id, revision) is unique, so two concurrent decisions made on the
same revision cannot both be stored. The latest revision is the active decision. On PostgreSQL a trigger refuses UPDATE and
DELETE: a decision cannot be changed or removed.

The table is new; no existing table or row is changed. Downgrade refuses while the table holds data (the rollback is then
the pre-migration backup).

Revision ID: 0005_investigation_reviews
Revises: 0004_ai_authorization_lineage
Create Date: 2026-11-05 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_investigation_reviews'
down_revision = '0004_ai_authorization_lineage'
branch_labels = None
depends_on = None

AUDIT = 'audit'
TABLE = 'investigation_reviews'


def upgrade():
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('analyst_review_id', sa.String(length=40), nullable=False, unique=True),
        sa.Column('period_id', sa.String(length=16), nullable=False, index=True),
        sa.Column('pack_id', sa.String(length=64), nullable=False, index=True),
        sa.Column('exception_id', sa.String(length=48), nullable=False),
        sa.Column('investigation_id', sa.String(length=48), nullable=False, index=True),
        sa.Column('findings_sha256', sa.String(length=64), nullable=False),
        sa.Column('findings_schema_version', sa.String(length=64), nullable=False),
        sa.Column('decision', sa.String(length=8), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=False),
        sa.Column('reviewer_id', sa.String(length=64), nullable=False),
        sa.Column('reviewer_name', sa.String(length=128), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('supersedes_review_id', sa.String(length=40), nullable=True),
        sa.UniqueConstraint('investigation_id', 'revision', name='uq_investigation_reviews_revision'),
        sa.CheckConstraint("decision IN ('ACCEPT', 'REJECT')", name='ck_investigation_reviews_decision'),
        sa.CheckConstraint("decision <> 'REJECT' OR length(trim(rejection_reason)) > 0", name='ck_investigation_reviews_reason'),
        schema=AUDIT)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(f"""
            CREATE FUNCTION {AUDIT}.refuse_investigation_review_change() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit.investigation_reviews is append-only: % is not allowed', TG_OP;
            END $$""")
        op.execute(f"""
            CREATE TRIGGER investigation_reviews_immutable BEFORE UPDATE OR DELETE ON {AUDIT}.{TABLE}
            FOR EACH ROW EXECUTE FUNCTION {AUDIT}.refuse_investigation_review_change()""")


def downgrade():
    conn = op.get_bind()
    held = conn.execute(sa.text(f'SELECT count(*) FROM {AUDIT}.{TABLE}')).scalar()
    if held:
        raise RuntimeError(f'downgrade would discard {held} analyst review decision(s); restore the pre-migration backup instead')
    if conn.dialect.name == 'postgresql':
        op.execute(f'DROP TRIGGER investigation_reviews_immutable ON {AUDIT}.{TABLE}')
        op.execute(f'DROP FUNCTION {AUDIT}.refuse_investigation_review_change()')
    op.drop_table(TABLE, schema=AUDIT)
