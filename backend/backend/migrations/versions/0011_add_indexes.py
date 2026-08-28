from alembic import op
revision = '0011_add_indexes'
down_revision = '0010_files_webhooks_dispatch'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('idx_tenders_nmck', 'tenders', ['nmck'])
    op.create_index('idx_tenders_published', 'tenders', ['published_at'])
    op.create_index('idx_tenders_matched_category', 'tenders', ['matched_category_id'])
    op.create_index('idx_tenders_score', 'tenders', ['score'])
    op.execute("CREATE INDEX idx_tenders_embedding ON tenders USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
    op.create_index('idx_suppliers_tags', 'suppliers', ['tags'], postgresql_using='gin')
    op.create_index('idx_suppliers_deleted_at', 'suppliers', ['deleted_at'])

def downgrade():
    op.drop_index('idx_tenders_nmck', table_name='tenders')
    op.drop_index('idx_tenders_published', table_name='tenders')
    op.drop_index('idx_tenders_matched_category', table_name='tenders')
    op.drop_index('idx_tenders_score', table_name='tenders')
    op.execute("DROP INDEX IF EXISTS idx_tenders_embedding")
    op.drop_index('idx_suppliers_tags', table_name='suppliers')
    op.drop_index('idx_suppliers_deleted_at', table_name='suppliers')
