from alembic import op
import sqlalchemy as sa

revision = '0014_add_missing_count'
down_revision = '0013_add_risk_details_and_indexes'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('tenders', sa.Column('missing_count', sa.Integer(), nullable=False, server_default='0'))

def downgrade():
    op.drop_column('tenders', 'missing_count')