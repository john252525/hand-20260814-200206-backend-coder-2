from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013_add_risk_details_and_indexes'
down_revision = '0012_fixes'
branch_labels = None
depends_on = None

def upgrade():
    # Добавляем risk_details в decisions
    op.add_column('decisions', sa.Column('risk_details', postgresql.JSONB(), nullable=True))
    # Недостающие индексы
    op.execute('CREATE INDEX IF NOT EXISTS idx_comms_external_id ON communications (external_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_ls_supplier_id ON lot_suppliers (supplier_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_tenders_source_id_simple ON tenders (source_id)')

def downgrade():
    op.drop_column('decisions', 'risk_details')
    op.execute('DROP INDEX IF EXISTS idx_comms_external_id')
    op.execute('DROP INDEX IF EXISTS idx_ls_supplier_id')
    op.execute('DROP INDEX IF EXISTS idx_tenders_source_id_simple')