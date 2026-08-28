from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009_decision_webhook'
down_revision = '0008_commercial_offers'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenders.id'), nullable=False, unique=True),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('chosen_supplier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('suppliers.id'), nullable=True),
        sa.Column('chosen_offer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('commercial_offers.id'), nullable=True),
        sa.Column('margin_at_decision', sa.DECIMAL(18, 2), nullable=True),
        sa.Column('risk_level_at_decision', sa.String(10), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_decisions_tender', 'decisions', ['tender_id'], unique=True)

    op.create_table(
        'webhooks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('events', postgresql.JSONB(), nullable=False),
        sa.Column('secret', sa.String(255), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(20), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('webhooks')
    op.drop_table('decisions')
