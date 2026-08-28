from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008_commercial_offers'
down_revision = '0007_sprint2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'commercial_offers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('lot_supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('lot_suppliers.id'), nullable=False),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('source_communication_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('communications.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PROCESSING'),
        sa.Column('coverage', sa.Float(), nullable=False, server_default='0'),
        sa.Column('clarification_needed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('clarification_items', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('total_cost', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('delivery_cost', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('total_cost_with_delivery', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('total_cost_with_all', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('margin_absolute', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('margin_percent', sa.Float(), nullable=True),
        sa.Column('payment_terms', postgresql.JSONB(), nullable=True),
        sa.Column('delivery_terms', postgresql.JSONB(), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_text_snippet', sa.Text(), nullable=False, server_default=''),
        sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_co_lot_supplier', 'commercial_offers', ['lot_supplier_id'])
    op.create_index('idx_co_tender', 'commercial_offers', ['tender_id'])

    op.create_table(
        'offer_positions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('commercial_offer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('commercial_offers.id'), nullable=False),
        sa.Column('tender_position_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tender_positions.id'), nullable=True),
        sa.Column('supplier_name', sa.Text(), nullable=False),
        sa.Column('match_type', sa.String(10), nullable=False, server_default='not_found'),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('price_per_unit', sa.DECIMAL(18, 4), nullable=True),
        sa.Column('quantity_available', sa.DECIMAL(18, 4), nullable=True),
        sa.Column('delivery_days', sa.Integer(), nullable=True),
        sa.Column('nds_included', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('nds_rate', sa.Float(), nullable=True),
        sa.Column('total_price', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('idx_op_offer_id', 'offer_positions', ['commercial_offer_id'])
    op.create_index('idx_op_tender_pos', 'offer_positions', ['tender_position_id'])

    op.create_table(
        'communication_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('communication_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('communications.id'), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=False, server_default='application/octet-stream'),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('is_parsed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_ca_communication', 'communication_attachments', ['communication_id'])


def downgrade():
    op.drop_table('communication_attachments')
    op.drop_table('offer_positions')
    op.drop_table('commercial_offers')
