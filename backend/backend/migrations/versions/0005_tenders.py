from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = '0005_tenders'
down_revision = '0004_add_ivfflat_index'
branch_labels = None
depends_on = None


def upgrade():
    # --- Tender Sources ---
    op.create_table(
        'tender_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('api_url', sa.Text(), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False, server_default=''),
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(20), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # --- Suppliers ---
    op.create_table(
        'suppliers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, server_default='unknown'),
        sa.Column('website', sa.Text(), nullable=False, server_default=''),
        sa.Column('email', sa.String(255), nullable=False, server_default=''),
        sa.Column('phone', sa.String(50), nullable=False, server_default=''),
        sa.Column('telegram', sa.String(100), nullable=False, server_default=''),
        sa.Column('whatsapp', sa.String(50), nullable=False, server_default=''),
        sa.Column('contact_persons', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('inn', sa.String(12), nullable=False, server_default=''),
        sa.Column('kpp', sa.String(9), nullable=False, server_default=''),
        sa.Column('ogrn', sa.String(15), nullable=False, server_default=''),
        sa.Column('legal_address', sa.Text(), nullable=False, server_default=''),
        sa.Column('tags', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('rating', postgresql.JSONB(), nullable=False, server_default='{"avg_response_time_hours": null, "response_rate": 0, "price_competitiveness": 0, "reliability": 0}'),
        sa.Column('total_lots', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successful_deals', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_volume_rub', sa.DECIMAL(18,2), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_suppliers_email', 'suppliers', ['email'], unique=False, postgresql_where=sa.text("email != ''"))
    op.create_index('idx_suppliers_inn', 'suppliers', ['inn'], unique=False, postgresql_where=sa.text("inn != ''"))
    op.create_index('idx_suppliers_type', 'suppliers', ['type'])

    # --- Tenders ---
    op.create_table(
        'tenders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tender_sources.id'), nullable=False),
        sa.Column('source_tender_id', sa.String(255), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('nmck', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='RUB'),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('customer_name', sa.Text(), nullable=False, server_default=''),
        sa.Column('customer_inn', sa.String(12), nullable=False, server_default=''),
        sa.Column('customer_kpp', sa.String(9), nullable=False, server_default=''),
        sa.Column('platform', sa.String(100), nullable=False, server_default=''),
        sa.Column('source_url', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(50), nullable=False, server_default='NEW'),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('structured_data', postgresql.JSONB(), nullable=True),
        sa.Column('matched_category_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('similarity_score', sa.Float(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('score_components', postgresql.JSONB(), nullable=True),
        sa.Column('selected_supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('suppliers.id'), nullable=True),
        sa.Column('final_margin_absolute', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('final_margin_percent', sa.Float(), nullable=True),
        sa.Column('risk_level', sa.String(10), nullable=True),
        sa.Column('risk_details', postgresql.JSONB(), nullable=True),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_tenders_source_id', 'tenders', ['source_id', 'source_tender_id'], unique=True)
    op.create_index('idx_tenders_status', 'tenders', ['status'])
    op.create_index('idx_tenders_deadline', 'tenders', ['deadline_at'])
    op.create_index('idx_tenders_created', 'tenders', ['created_at'])

    # --- Tender Documents ---
    op.create_table(
        'tender_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=False, server_default='application/octet-stream'),
        sa.Column('source_url', sa.Text(), nullable=False, server_default=''),
        sa.Column('storage_path', sa.Text(), nullable=False, server_default=''),
        sa.Column('parsed_text', sa.Text(), nullable=True),
        sa.Column('parse_status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('parse_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_td_tender_id', 'tender_documents', ['tender_id'])

    # --- Tender Positions ---
    op.create_table(
        'tender_positions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('position_number', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('characteristics', sa.Text(), nullable=False, server_default=''),
        sa.Column('gost', sa.String(100), nullable=False, server_default=''),
        sa.Column('okpd2', sa.String(20), nullable=False, server_default=''),
        sa.Column('quantity', sa.DECIMAL(18, 4), nullable=False),
        sa.Column('unit', sa.String(50), nullable=False, server_default='шт'),
        sa.Column('is_essential', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('idx_tp_tender_id', 'tender_positions', ['tender_id'])

    # --- Tender Requirements ---
    op.create_table(
        'tender_requirements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('delivery_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivery_address', sa.Text(), nullable=False, server_default=''),
        sa.Column('delivery_conditions', sa.Text(), nullable=False, server_default=''),
        sa.Column('license_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sro_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('security_bid', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('security_contract', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('prepayment_percent', sa.Float(), nullable=True),
        sa.Column('stages_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('special_conditions', postgresql.JSONB(), nullable=False, server_default='[]'),
    )
    op.create_index('idx_tr_tender_id', 'tender_requirements', ['tender_id'], unique=True)

    # --- Tender Status History ---
    op.create_table(
        'tender_status_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('previous_status', sa.String(50), nullable=True),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('set_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_tsh_tender_id', 'tender_status_history', ['tender_id'])
    op.create_index('idx_tsh_set_at', 'tender_status_history', ['set_at'])


def downgrade():
    op.drop_table('tender_status_history')
    op.drop_table('tender_requirements')
    op.drop_table('tender_positions')
    op.drop_table('tender_documents')
    op.drop_table('tenders')
    op.drop_table('suppliers')
    op.drop_table('tender_sources')
