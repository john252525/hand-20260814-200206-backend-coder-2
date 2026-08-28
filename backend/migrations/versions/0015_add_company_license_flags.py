from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0015_add_company_license_flags'
down_revision = '0014_add_missing_count'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    # Добавляем флаги наличия лицензий/СРО у компании
    conn.execute(
        sa.text("INSERT INTO settings (section, key, value, description) VALUES ('company', 'has_license', 'false', 'Наличие лицензии у компании')")
    )
    conn.execute(
        sa.text("INSERT INTO settings (section, key, value, description) VALUES ('company', 'has_sro', 'false', 'Наличие допуска СРО у компании')")
    )

def downgrade():
    op.execute("DELETE FROM settings WHERE section='company' AND key IN ('has_license','has_sro')")
