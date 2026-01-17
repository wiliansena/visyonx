from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7e617b96e00f'
down_revision = '22b04479e9da'
branch_labels = None
depends_on = None


def upgrade():
    # Necessário para CREATE INDEX CONCURRENTLY
    op.execute("COMMIT")

    # Índice base (quase todas as queries)
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nf_empresa_data
        ON nota_fiscal (empresa_id, data_emissao)
    """)

    # BI por cliente
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nf_empresa_cliente_data
        ON nota_fiscal (empresa_id, cliente, data_emissao)
    """)

    # BI por representante
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nf_empresa_rep_data
        ON nota_fiscal (empresa_id, representante, data_emissao)
    """)

    # BI por rede
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nf_empresa_rede_data
        ON nota_fiscal (empresa_id, rede_loja, data_emissao)
    """)

    # Índice para ordenação da listagem (opcional mas recomendado)
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_nf_empresa_data_numero
        ON nota_fiscal (empresa_id, data_emissao DESC, numero DESC)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_nf_empresa_data_numero")
    op.execute("DROP INDEX IF EXISTS idx_nf_empresa_rede_data")
    op.execute("DROP INDEX IF EXISTS idx_nf_empresa_rep_data")
    op.execute("DROP INDEX IF EXISTS idx_nf_empresa_cliente_data")
    op.execute("DROP INDEX IF EXISTS idx_nf_empresa_data")
