import os
import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


class ReleaseControlMigrationTests(unittest.TestCase):
    def test_legacy_schema_upgrades_and_backfills_control_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "legacy.db"
            database_url = f"sqlite:///{database_path}"
            engine = sa.create_engine(database_url)
            metadata = sa.MetaData()

            sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
            sa.Table(
                "products",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("cost", sa.Float),
                sa.Column("sale_price", sa.Float),
            )
            sa.Table("journals", metadata, sa.Column("id", sa.Integer, primary_key=True))
            sa.Table(
                "journal_lines",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("debit", sa.Float),
                sa.Column("credit", sa.Float),
            )
            sa.Table(
                "invoices",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("subtotal", sa.Float),
                sa.Column("tax_rate", sa.Float),
                sa.Column("tax_amount", sa.Float),
                sa.Column("total", sa.Float),
            )
            sa.Table(
                "invoice_lines",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("unit_price", sa.Float, nullable=False),
                sa.Column("line_total", sa.Float),
            )
            sa.Table(
                "productions",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("total_cost", sa.Float),
            )
            for table_name in ("sales_quotations", "purchase_orders", "sales_orders"):
                sa.Table(
                    table_name,
                    metadata,
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("total", sa.Float),
                )
            for table_name in (
                "sales_quotation_lines",
                "purchase_order_lines",
                "sales_order_lines",
            ):
                sa.Table(
                    table_name,
                    metadata,
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("unit_price", sa.Float, nullable=False),
                )
            sa.Table(
                "payments",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("amount", sa.Float, nullable=False),
            )
            sa.Table(
                "payment_allocations",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("amount", sa.Float, nullable=False),
            )
            sa.Table(
                "audit_logs",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("actor_id", sa.Integer, nullable=False),
                sa.Column("action", sa.String(80), nullable=False),
                sa.Column("entity_type", sa.String(50), nullable=False),
                sa.Column("entity_id", sa.Integer),
            )
            for table_name, source_column in (
                ("sales_quotation_conversions", "quotation_id"),
                ("sales_order_conversions", "sales_order_id"),
                ("purchase_order_conversions", "purchase_order_id"),
            ):
                sa.Table(
                    table_name,
                    metadata,
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column(source_column, sa.Integer, nullable=False),
                    sa.Column("invoice_id", sa.Integer, nullable=False),
                )

            metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
                connection.execute(sa.text("INSERT INTO journals (id) VALUES (1)"))
                connection.execute(
                    sa.text(
                        "INSERT INTO invoices (id, subtotal, tax_rate, tax_amount, total) "
                        "VALUES (1, 10.0, 14.0, 1.4, 11.4), (2, 20.0, 14.0, 2.8, 22.8)"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO audit_logs (id, actor_id, action, entity_type, entity_id) "
                        "VALUES (1, 1, 'create_draft', 'invoice', 1), "
                        "(2, 1, 'convert', 'sales_order', 5)"
                    )
                )
                connection.execute(sa.text("INSERT INTO sales_orders (id, total) VALUES (5, 20.0)"))
                connection.execute(
                    sa.text(
                        "INSERT INTO sales_order_conversions (id, sales_order_id, invoice_id) "
                        "VALUES (1, 5, 2)"
                    )
                )
                connection.execute(sa.text("INSERT INTO payments (id, amount) VALUES (1, 11.4)"))
                connection.execute(sa.text("INSERT INTO payment_allocations (id, amount) VALUES (1, 11.4)"))

            config = Config("alembic.ini")
            old_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = database_url
            try:
                command.stamp(config, "0002_audit_logs")
                command.upgrade(config, "head")
            finally:
                if old_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = old_url

            inspector = sa.inspect(engine)
            invoice_columns = {column["name"]: column for column in inspector.get_columns("invoices")}
            self.assertTrue({"created_by_id", "source_type", "source_id"} <= set(invoice_columns))
            self.assertIn("numeric", type(invoice_columns["total"]["type"]).__name__.lower())
            payment_columns = {column["name"] for column in inspector.get_columns("payments")}
            self.assertTrue({"status", "voided_at", "voided_by_id", "reversal_journal_id"} <= payment_columns)
            allocation_columns = {column["name"] for column in inspector.get_columns("payment_allocations")}
            self.assertIn("active", allocation_columns)

            with engine.connect() as connection:
                direct = connection.execute(
                    sa.text("SELECT created_by_id FROM invoices WHERE id = 1")
                ).one()
                converted = connection.execute(
                    sa.text("SELECT created_by_id, source_type, source_id FROM invoices WHERE id = 2")
                ).one()
                payment = connection.execute(
                    sa.text("SELECT status FROM payments WHERE id = 1")
                ).one()
                allocation = connection.execute(
                    sa.text("SELECT active FROM payment_allocations WHERE id = 1")
                ).one()
                revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()

            self.assertEqual(direct.created_by_id, 1)
            self.assertEqual(tuple(converted), (1, "sales_order", 5))
            self.assertEqual(payment.status, "posted")
            self.assertTrue(allocation.active)
            self.assertEqual(revision, "0003_release_control_slice")


if __name__ == "__main__":
    unittest.main()
