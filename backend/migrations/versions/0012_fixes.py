from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012_fixes'
down_revision = '0011_add_indexes'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # добавить updated_at в tender_documents, если колонки нет, NOT NULL
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name='tender_documents' AND column_name='updated_at'")
    ).fetchone()
    if row is None:
        op.add_column(
            'tender_documents',
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        )
    # недостающие индексы
    op.execute('CREATE INDEX IF NOT EXISTS idx_comms_message_type ON communications (message_type)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_comms_sent_at ON communications (sent_at)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_co_status ON commercial_offers (status)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_ls_status ON lot_suppliers (status)')
    # разрешить ручное создание тендеров без источника
    op.alter_column('tenders', 'source_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade():
    # перед возвратом NOT NULL обновим NULL-значения системным источником (если есть)
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE tenders SET source_id = (SELECT id FROM tender_sources WHERE type='manual' LIMIT 1) WHERE source_id IS NULL")
    )
    op.alter_column('tenders', 'source_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.execute('DROP INDEX IF EXISTS idx_comms_message_type')
    op.execute('DROP INDEX IF EXISTS idx_comms_sent_at')
    op.execute('DROP INDEX IF EXISTS idx_co_status')
    op.execute('DROP INDEX IF EXISTS idx_ls_status')
    op.drop_column('tender_documents', 'updated_at')
