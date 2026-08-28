from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007_sprint2'
down_revision = '0006_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lot_suppliers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('match_relevance', sa.String(10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_ls_tender_supplier', 'lot_suppliers', ['tender_id', 'supplier_id'], unique=True)

    op.create_table(
        'communications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('lot_supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lot_suppliers.id'), nullable=False),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('subject', sa.Text(), nullable=False, server_default=''),
        sa.Column('body_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('body_html', sa.Text(), nullable=False, server_default=''),
        sa.Column('message_type', sa.String(30), nullable=False, server_default='other'),
        sa.Column('external_id', sa.String(500), nullable=False, server_default=''),
        sa.Column('in_reply_to_external_id', sa.String(500), nullable=False, server_default=''),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_comms_lot_supplier', 'communications', ['lot_supplier_id'])
    op.create_index('idx_comms_tender', 'communications', ['tender_id'])


def downgrade():
    op.drop_table('communications')
    op.drop_table('lot_suppliers')
