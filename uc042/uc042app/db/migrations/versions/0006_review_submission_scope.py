"""analyst review decisions scoped to an independent ZIP submission (owner-approved, 17 Nov 2026)

Each ZIP submission is an independent audit: its AI investigations are run afresh and the analyst's ACCEPT / REJECT decisions
on them count only for that submission. When a re-investigation yields byte-identical findings, the investigation ID is the
same as an earlier submission's, so a decision needs the submission it was made in.

  * audit.investigation_reviews gains a nullable submission_id. Existing rows are not changed (they keep NULL: legacy,
    period-level decisions).
  * The unique constraint (investigation_id, revision) becomes two partial unique indexes: legacy rows stay unique per
    (investigation_id, revision); submission rows are unique per (investigation_id, submission_id, revision). Two
    concurrent decisions on the same revision in the same scope still cannot both be stored.
  * The append-only trigger of migration 0005 (PostgreSQL: UPDATE and DELETE refused) is unchanged.

Downgrade refuses while a submission-scoped decision exists (it would be merged into the legacy scope); the rollback is then
the pre-migration backup.

Revision ID: 0006_review_submission_scope
Revises: 0005_investigation_reviews
Create Date: 2026-11-17 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_review_submission_scope'
down_revision = '0005_investigation_reviews'
branch_labels = None
depends_on = None

AUDIT = 'audit'
TABLE = 'investigation_reviews'


def upgrade():
    op.add_column(TABLE, sa.Column('submission_id', sa.String(length=40), nullable=True), schema=AUDIT)
    op.create_index('ix_investigation_reviews_submission_id', TABLE, ['submission_id'], schema=AUDIT)
    op.drop_constraint('uq_investigation_reviews_revision', TABLE, schema=AUDIT, type_='unique')
    op.create_index('uq_investigation_reviews_revision', TABLE, ['investigation_id', 'revision'], unique=True, schema=AUDIT,
                    postgresql_where=sa.text('submission_id IS NULL'))
    op.create_index('uq_investigation_reviews_submission_revision', TABLE, ['investigation_id', 'submission_id', 'revision'],
                    unique=True, schema=AUDIT, postgresql_where=sa.text('submission_id IS NOT NULL'))


def downgrade():
    conn = op.get_bind()
    held = conn.execute(sa.text(f'SELECT count(*) FROM {AUDIT}.{TABLE} WHERE submission_id IS NOT NULL')).scalar()
    if held:
        raise RuntimeError(f'downgrade would merge {held} submission-scoped analyst decision(s) into the legacy scope; '
                           'restore the pre-migration backup instead')
    op.drop_index('uq_investigation_reviews_submission_revision', TABLE, schema=AUDIT)
    op.drop_index('uq_investigation_reviews_revision', TABLE, schema=AUDIT)
    op.create_unique_constraint('uq_investigation_reviews_revision', TABLE, ['investigation_id', 'revision'], schema=AUDIT)
    op.drop_index('ix_investigation_reviews_submission_id', TABLE, schema=AUDIT)
    op.drop_column(TABLE, 'submission_id', schema=AUDIT)
