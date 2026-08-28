from alembic import op

revision = '0004_add_ivfflat_index'
down_revision = '0003_categories_idempotency'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX idx_categories_embedding ON categories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_categories_embedding")
