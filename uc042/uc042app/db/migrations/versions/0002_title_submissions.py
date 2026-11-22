"""period title; document submission kind, reason and replaced document (Phase 7)

Additive only: every new column has a server default or is nullable, so existing rows stay valid and unchanged in meaning.
  reconciliation_periods.title              editable report title (the period_id stays the immutable key)
  source_documents.submission_kind          INITIAL | ADDITIONAL_EVIDENCE | CORRECTION
  source_documents.submission_reason        why the document was added (required for additional evidence and corrections)
  source_documents.replaces_document_id     the earlier document a correction replaces (that document is never changed)

Revision ID: 0002_title_submissions
Revises: 0001_initial
Create Date: 2026-11-04 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_title_submissions'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reconciliation_periods', sa.Column('title', sa.Text(), nullable=False, server_default=''))
    op.add_column('source_documents', sa.Column('submission_kind', sa.String(length=24), nullable=False, server_default='INITIAL'))
    op.add_column('source_documents', sa.Column('submission_reason', sa.Text(), nullable=False, server_default=''))
    op.add_column('source_documents', sa.Column('replaces_document_id', sa.String(length=40), nullable=True))


def downgrade():
    op.drop_column('source_documents', 'replaces_document_id')
    op.drop_column('source_documents', 'submission_reason')
    op.drop_column('source_documents', 'submission_kind')
    op.drop_column('reconciliation_periods', 'title')
