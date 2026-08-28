from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010_files_webhooks_dispatch'
down_revision = '0009_decision_webhook'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=False, server_default='application/octet-stream'),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_files_entity', 'files', ['entity_type', 'entity_id'])


def downgrade():
    op.drop_table('files')
