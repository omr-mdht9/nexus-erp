"""Add release-control fields and exact monetary storage.

Revision ID: 0003_release_control_slice
Revises: 0002_audit_logs
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_release_control_slice"
down_revision = "0002_audit_logs"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "products": ("cost", "sale_price"),
    "journal_lines": ("debit", "credit"),
    "invoices": ("subtotal", "tax_amount", "total"),
    "invoice_lines": ("unit_price", "line_total"),
    "productions": ("total_cost",),
    "sales_quotations": ("total",),
    "purchase_orders": ("total",),
    "sales_orders": ("total",),
    "sales_quotation_lines": ("unit_price",),
    "purchase_order_lines": ("unit_price",),
    "sales_order_lines": ("unit_price",),
    "payments": ("amount",),
    "payment_allocations": ("amount",),
}

NON_NULL_MONEY_COLUMNS = {
    ("invoice_lines", "unit_price"),
    ("sales_quotation_lines", "unit_price"),
    ("purchase_order_lines", "unit_price"),
    ("sales_order_lines", "unit_price"),
    ("payments", "amount"),
    ("payment_allocations", "amount"),
}


def _alter_money_columns(existing_type: sa.types.TypeEngine, target_type: sa.types.TypeEngine) -> None:
    for table_name, column_names in MONEY_COLUMNS.items():
        with op.batch_alter_table(table_name) as batch:
            for column_name in column_names:
                batch.alter_column(
                    column_name,
                    existing_type=existing_type,
                    type_=target_type,
                    existing_nullable=(table_name, column_name) not in NON_NULL_MONEY_COLUMNS,
                    postgresql_using=f"{column_name}::numeric(18,2)"
                    if isinstance(target_type, sa.Numeric)
                    else f"{column_name}::double precision",
                )


def upgrade() -> None:
    _alter_money_columns(sa.Float(), sa.Numeric(18, 2))

    with op.batch_alter_table("invoices") as batch:
        batch.alter_column(
            "tax_rate",
            existing_type=sa.Float(),
            type_=sa.Numeric(7, 4),
            existing_nullable=True,
            postgresql_using="tax_rate::numeric(7,4)",
        )
        batch.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_type", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_invoices_created_by_id_users", "users", ["created_by_id"], ["id"])
        batch.create_index("ix_invoices_created_by_id", ["created_by_id"])
        batch.create_index("ix_invoices_source", ["source_type", "source_id"])

    op.execute(
        """
        UPDATE invoices
        SET created_by_id = (
            SELECT audit_logs.actor_id
            FROM audit_logs
            WHERE audit_logs.entity_type = 'invoice'
              AND audit_logs.entity_id = invoices.id
              AND audit_logs.action IN ('create', 'create_draft')
            ORDER BY audit_logs.id ASC
            LIMIT 1
        )
        WHERE created_by_id IS NULL
        """
    )
    for source_type, conversion_table, source_column, entity_type in (
        ("sales_quotation", "sales_quotation_conversions", "quotation_id", "sales_quotation"),
        ("sales_order", "sales_order_conversions", "sales_order_id", "sales_order"),
        ("purchase_order", "purchase_order_conversions", "purchase_order_id", "purchase_order"),
    ):
        op.execute(
            sa.text(
                f"""
                UPDATE invoices
                SET source_type = :source_type,
                    source_id = (
                        SELECT conversions.{source_column}
                        FROM {conversion_table} AS conversions
                        WHERE conversions.invoice_id = invoices.id
                        LIMIT 1
                    ),
                    created_by_id = COALESCE(
                        created_by_id,
                        (
                            SELECT audit_logs.actor_id
                            FROM {conversion_table} AS conversions
                            JOIN audit_logs
                              ON audit_logs.entity_type = :entity_type
                             AND audit_logs.entity_id = conversions.{source_column}
                             AND audit_logs.action = 'convert'
                            WHERE conversions.invoice_id = invoices.id
                            ORDER BY audit_logs.id ASC
                            LIMIT 1
                        )
                    )
                WHERE EXISTS (
                    SELECT 1
                    FROM {conversion_table} AS conversions
                    WHERE conversions.invoice_id = invoices.id
                )
                """
            ).bindparams(source_type=source_type, entity_type=entity_type)
        )

    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="posted"))
        batch.add_column(sa.Column("voided_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("voided_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reversal_journal_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_payments_voided_by_id_users", "users", ["voided_by_id"], ["id"])
        batch.create_foreign_key(
            "fk_payments_reversal_journal_id_journals",
            "journals",
            ["reversal_journal_id"],
            ["id"],
        )
        batch.create_index("ix_payments_status", ["status"])

    with op.batch_alter_table("payment_allocations") as batch:
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_index("ix_payment_allocations_active", ["active"])


def downgrade() -> None:
    with op.batch_alter_table("payment_allocations") as batch:
        batch.drop_index("ix_payment_allocations_active")
        batch.drop_column("active")

    with op.batch_alter_table("payments") as batch:
        batch.drop_index("ix_payments_status")
        batch.drop_constraint("fk_payments_reversal_journal_id_journals", type_="foreignkey")
        batch.drop_constraint("fk_payments_voided_by_id_users", type_="foreignkey")
        batch.drop_column("reversal_journal_id")
        batch.drop_column("voided_by_id")
        batch.drop_column("voided_at")
        batch.drop_column("status")

    with op.batch_alter_table("invoices") as batch:
        batch.drop_index("ix_invoices_source")
        batch.drop_index("ix_invoices_created_by_id")
        batch.drop_constraint("fk_invoices_created_by_id_users", type_="foreignkey")
        batch.drop_column("source_id")
        batch.drop_column("source_type")
        batch.drop_column("created_by_id")
        batch.alter_column(
            "tax_rate",
            existing_type=sa.Numeric(7, 4),
            type_=sa.Float(),
            existing_nullable=True,
            postgresql_using="tax_rate::double precision",
        )

    _alter_money_columns(sa.Numeric(18, 2), sa.Float())
