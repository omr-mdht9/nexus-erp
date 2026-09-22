import importlib
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient


class SafetyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(cls.temp_dir.name) / 'nexus-test.db'}"
        os.environ["JWT_SECRET"] = "test-only-secret"
        os.environ["NEXUS_INITIAL_ADMIN_USERNAME"] = "testadmin"
        os.environ["NEXUS_INITIAL_ADMIN_PASSWORD"] = "NexusTest1!"

        import app.main as main
        cls.main = importlib.reload(main)
        cls.client = TestClient(cls.main.app)
        response = cls.client.post(
            "/api/auth/login",
            data={"username": "testadmin", "password": "NexusTest1!"},
        )
        response.raise_for_status()
        cls.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def create_user_headers(self, username, role="accountant"):
        created = self.client.post(
            "/api/users",
            json={"username": username, "password": "ReviewerTest1!", "role": role},
            headers=self.headers,
        )
        created.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": username, "password": "ReviewerTest1!"},
        )
        login.raise_for_status()
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_health_reports_connected_database(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "connected")
        self.assertIn("version", payload)

    def test_quote_creator_cannot_approve_own_quote(self):
        quote = self.client.post(
            "/api/sales-quotations",
            json={"customer_id": 2, "total": 100},
            headers=self.headers,
        )
        quote.raise_for_status()
        quote_id = quote.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/sales-quotations/{quote_id}/workflow",
                json={"action": "submit"},
                headers=self.headers,
            ).status_code,
            200,
        )
        response = self.client.post(
            f"/api/sales-quotations/{quote_id}/workflow",
            json={"action": "approve"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_invoice_creator_cannot_approve_or_post_own_draft(self):
        created = self.client.post(
            "/api/invoices",
            json={
                "kind": "sale",
                "party_id": 2,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 1, "unit_price": 100}],
                "post_now": False,
            },
            headers=self.headers,
        )
        created.raise_for_status()
        invoice_id = created.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/workflow",
                json={"action": "submit"},
                headers=self.headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/workflow",
                json={"action": "approve"},
                headers=self.headers,
            ).status_code,
            403,
        )

        reviewer = self.client.post(
            "/api/users",
            json={
                "username": "reviewer",
                "password": "ReviewerTest1!",
                "role": "accountant",
            },
            headers=self.headers,
        )
        reviewer.raise_for_status()
        reviewer_login = self.client.post(
            "/api/auth/login",
            data={"username": "reviewer", "password": "ReviewerTest1!"},
        )
        reviewer_login.raise_for_status()
        reviewer_headers = {
            "Authorization": f"Bearer {reviewer_login.json()['access_token']}"
        }
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/workflow",
                json={"action": "approve"},
                headers=reviewer_headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/post",
                headers=self.headers,
            ).status_code,
            403,
        )

    def test_stock_transfer_creates_balanced_movement_pair(self):
        warehouse = self.client.post(
            "/api/warehouses",
            json={"code": "WH-02", "name": "Transfer Destination"},
            headers=self.headers,
        )
        warehouse.raise_for_status()
        destination_id = warehouse.json()["id"]

        receipt = self.client.post(
            "/api/stock-adjustments",
            json={
                "product_id": 1,
                "warehouse_id": 1,
                "direction": "IN",
                "qty": 5,
                "reason": "Transfer test opening stock",
            },
            headers=self.headers,
        )
        receipt.raise_for_status()

        transfer = self.client.post(
            "/api/stock-transfers",
            json={
                "product_id": 1,
                "from_warehouse_id": 1,
                "to_warehouse_id": destination_id,
                "qty": 2,
                "reason": "Move stock for operational use",
            },
            headers=self.headers,
        )
        transfer.raise_for_status()
        reference = transfer.json()["reference"]
        self.assertEqual(transfer.json()["reason"], "Move stock for operational use")

        transfer_register = self.client.get("/api/stock-transfers", headers=self.headers)
        transfer_register.raise_for_status()
        transfer_record = next(x for x in transfer_register.json() if x["reference"] == reference)
        self.assertEqual(transfer_record["reason"], "Move stock for operational use")
        self.assertEqual(transfer_record["recorded_by"], "testadmin")

        movements = self.client.get("/api/stock-moves", headers=self.headers)
        movements.raise_for_status()
        related = [m for m in movements.json() if m["ref_no"] == reference]
        self.assertEqual(len(related), 2)
        self.assertEqual({m["direction"] for m in related}, {"IN", "OUT"})
        self.assertEqual(sum(m["qty"] for m in related), 4)

        balances = self.client.get("/api/stock-by-warehouse", headers=self.headers)
        balances.raise_for_status()
        destination = next(x for x in balances.json() if x["product_id"] == 1 and x["warehouse_id"] == destination_id)
        self.assertEqual(destination["qty"], 2)

    def test_inventory_role_cannot_create_financial_invoice(self):
        user = self.client.post(
            "/api/users",
            json={"username": "inventorytester", "password": "InventoryTest1!", "role": "inventory"},
            headers=self.headers,
        )
        user.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": "inventorytester", "password": "InventoryTest1!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = self.client.post(
            "/api/invoices",
            json={"kind": "sale", "party_id": 2, "warehouse_id": 1, "lines": [{"product_id": 1, "qty": 1, "unit_price": 10}]},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_inventory_role_cannot_access_admin_audit_log(self):
        user = self.client.post(
            "/api/users",
            json={"username": "inventoryaudit", "password": "InventoryTest1!", "role": "inventory"},
            headers=self.headers,
        )
        user.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": "inventoryaudit", "password": "InventoryTest1!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        self.assertEqual(
            self.client.get("/api/audit-logs", headers=headers).status_code,
            403,
        )

    def test_inventory_role_can_receive_approved_purchase_order(self):
        order = self.client.post(
            "/api/purchase-orders",
            json={"supplier_id": 1, "lines": [{"product_id": 1, "qty": 2, "unit_price": 10}]},
            headers=self.headers,
        )
        order.raise_for_status()
        order_id = order.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/purchase-orders/{order_id}/workflow",
                json={"action": "submit"},
                headers=self.headers,
            ).status_code,
            200,
        )
        reviewer = self.client.post(
            "/api/users",
            json={"username": "receiptapprover", "password": "ReviewerTest1!", "role": "accountant"},
            headers=self.headers,
        )
        reviewer.raise_for_status()
        reviewer_login = self.client.post(
            "/api/auth/login",
            data={"username": "receiptapprover", "password": "ReviewerTest1!"},
        )
        reviewer_login.raise_for_status()
        reviewer_headers = {"Authorization": f"Bearer {reviewer_login.json()['access_token']}"}
        self.assertEqual(
            self.client.post(
                f"/api/purchase-orders/{order_id}/workflow",
                json={"action": "approve"},
                headers=reviewer_headers,
            ).status_code,
            200,
        )
        operator = self.client.post(
            "/api/users",
            json={"username": "receiptoperator", "password": "InventoryTest1!", "role": "inventory"},
            headers=self.headers,
        )
        operator.raise_for_status()
        operator_login = self.client.post(
            "/api/auth/login",
            data={"username": "receiptoperator", "password": "InventoryTest1!"},
        )
        operator_login.raise_for_status()
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['access_token']}"}
        receipt = self.client.post(
            "/api/purchase-receipts",
            json={"purchase_order_id": order_id, "warehouse_id": 1},
            headers=operator_headers,
        )
        receipt.raise_for_status()
        self.assertEqual(receipt.json()["status"], "posted")
        duplicate = self.client.post(
            "/api/purchase-receipts",
            json={"purchase_order_id": order_id, "warehouse_id": 1},
            headers=operator_headers,
        )
        self.assertEqual(duplicate.status_code, 400)
        register = self.client.get("/api/purchase-receipts", headers=operator_headers)
        register.raise_for_status()
        self.assertTrue(any(row["purchase_order_id"] == order_id for row in register.json()))

    def test_inventory_role_can_transfer_available_stock(self):
        warehouse = self.client.post(
            "/api/warehouses",
            json={"code": "WH-ROLE", "name": "Role Test Destination"},
            headers=self.headers,
        )
        warehouse.raise_for_status()
        destination_id = warehouse.json()["id"]
        receipt = self.client.post(
            "/api/stock-adjustments",
            json={
                "product_id": 1,
                "warehouse_id": 1,
                "direction": "IN",
                "qty": 3,
                "reason": "Role transfer opening stock",
            },
            headers=self.headers,
        )
        receipt.raise_for_status()
        user = self.client.post(
            "/api/users",
            json={"username": "transferoperator", "password": "InventoryTest1!", "role": "inventory"},
            headers=self.headers,
        )
        user.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": "transferoperator", "password": "InventoryTest1!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        transfer = self.client.post(
            "/api/stock-transfers",
            json={
                "product_id": 1,
                "from_warehouse_id": 1,
                "to_warehouse_id": destination_id,
                "qty": 1,
                "reason": "Authorized warehouse replenishment",
            },
            headers=headers,
        )
        transfer.raise_for_status()
        reference = transfer.json()["reference"]
        self.assertTrue(reference.startswith("TRF-"))
        register = self.client.get("/api/stock-transfers", headers=headers)
        register.raise_for_status()
        self.assertTrue(any(row["reference"] == reference for row in register.json()))

    def test_accountant_cannot_adjust_stock(self):
        user = self.client.post(
            "/api/users",
            json={"username": "adjustmentreviewer", "password": "ReviewerTest1!", "role": "accountant"},
            headers=self.headers,
        )
        user.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": "adjustmentreviewer", "password": "ReviewerTest1!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 1, "warehouse_id": 1, "direction": "IN", "qty": 1, "reason": "Cycle count correction"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_accountant_cannot_manage_users(self):
        user = self.client.post(
            "/api/users",
            json={"username": "useradminreviewer", "password": "ReviewerTest1!", "role": "accountant"},
            headers=self.headers,
        )
        user.raise_for_status()
        login = self.client.post(
            "/api/auth/login",
            data={"username": "useradminreviewer", "password": "ReviewerTest1!"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = self.client.post(
            "/api/users",
            json={"username": "shouldnotcreate", "password": "RestrictedTest1!", "role": "inventory"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_stock_adjustment_cannot_reduce_below_available_stock(self):
        added = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 2, "warehouse_id": 1, "direction": "IN", "qty": 1, "reason": "Opening count"},
            headers=self.headers,
        )
        added.raise_for_status()
        balances = self.client.get("/api/stock-by-warehouse", headers=self.headers)
        balances.raise_for_status()
        available = next(
            row["qty"]
            for row in balances.json()
            if row["product_id"] == 2 and row["warehouse_id"] == 1
        )
        response = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 2, "warehouse_id": 1, "direction": "OUT", "qty": available + 1, "reason": "Count correction"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_stock_adjustment_requires_reason_and_is_traceable(self):
        invalid = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 1, "warehouse_id": 1, "direction": "SIDEWAYS", "qty": 1, "reason": "Cycle count correction"},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 400)

        adjustment = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 1, "warehouse_id": 1, "direction": "IN", "qty": 1, "reason": "Cycle count correction"},
            headers=self.headers,
        )
        adjustment.raise_for_status()
        reference = adjustment.json()["reference"]

        movements = self.client.get("/api/stock-moves", headers=self.headers)
        movements.raise_for_status()
        related = [m for m in movements.json() if m["ref_no"] == reference]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["direction"], "IN")
        self.assertEqual(related[0]["ref_type"], "adjustment")

        register = self.client.get("/api/stock-adjustments", headers=self.headers)
        register.raise_for_status()
        record = next(x for x in register.json() if x["reference"] == reference)
        self.assertEqual(record["reason"], "Cycle count correction")
        self.assertEqual(record["recorded_by"], "testadmin")

    def test_sales_order_requires_delivery_before_draft_invoice(self):
        stocked = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 1, "warehouse_id": 1, "direction": "IN", "qty": 2, "reason": "Delivery test stock"},
            headers=self.headers,
        )
        stocked.raise_for_status()
        before = self.client.get("/api/stock-by-warehouse", headers=self.headers)
        before.raise_for_status()
        before_qty = next(row["qty"] for row in before.json() if row["product_id"] == 1 and row["warehouse_id"] == 1)
        order = self.client.post(
            "/api/sales-orders",
            json={"customer_id": 2, "lines": [{"product_id": 1, "qty": 1, "unit_price": 100}]},
            headers=self.headers,
        )
        order.raise_for_status()
        order_id = order.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/sales-orders/{order_id}/workflow",
                json={"action": "submit"},
                headers=self.headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/sales-orders/{order_id}/workflow",
                json={"action": "approve"},
                headers=self.headers,
            ).status_code,
            403,
        )
        reviewer = self.client.post(
            "/api/users",
            json={"username": "orderapprover", "password": "ReviewerTest1!", "role": "accountant"},
            headers=self.headers,
        )
        reviewer.raise_for_status()
        reviewer_login = self.client.post(
            "/api/auth/login",
            data={"username": "orderapprover", "password": "ReviewerTest1!"},
        )
        reviewer_login.raise_for_status()
        reviewer_headers = {"Authorization": f"Bearer {reviewer_login.json()['access_token']}"}
        self.assertEqual(
            self.client.post(
                f"/api/sales-orders/{order_id}/workflow",
                json={"action": "approve"},
                headers=reviewer_headers,
            ).status_code,
            200,
        )
        operator = self.client.post(
            "/api/users",
            json={"username": "deliveryoperator", "password": "InventoryTest1!", "role": "inventory"},
            headers=self.headers,
        )
        operator.raise_for_status()
        operator_login = self.client.post(
            "/api/auth/login",
            data={"username": "deliveryoperator", "password": "InventoryTest1!"},
        )
        operator_login.raise_for_status()
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['access_token']}"}
        delivered = self.client.post(
            "/api/sales-deliveries",
            json={"sales_order_id": order_id, "warehouse_id": 1},
            headers=operator_headers,
        )
        delivered.raise_for_status()
        self.assertEqual(delivered.json()["status"], "posted")
        duplicate_delivery = self.client.post(
            "/api/sales-deliveries",
            json={"sales_order_id": order_id, "warehouse_id": 1},
            headers=operator_headers,
        )
        self.assertEqual(duplicate_delivery.status_code, 400)
        converted = self.client.post(
            f"/api/sales-orders/{order_id}/convert",
            json={"warehouse_id": 1},
            headers=reviewer_headers,
        )
        converted.raise_for_status()
        self.assertEqual(converted.json()["status"], "draft")
        invoice_id = converted.json()["invoice_id"]
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/workflow",
                json={"action": "submit"},
                headers=reviewer_headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/invoices/{invoice_id}/workflow",
                json={"action": "approve"},
                headers=self.headers,
            ).status_code,
            200,
        )
        poster = self.client.post(
            "/api/users",
            json={"username": "deliveryinvoiceposter", "password": "ReviewerTest1!", "role": "accountant"},
            headers=self.headers,
        )
        poster.raise_for_status()
        poster_login = self.client.post(
            "/api/auth/login",
            data={"username": "deliveryinvoiceposter", "password": "ReviewerTest1!"},
        )
        poster_login.raise_for_status()
        poster_headers = {"Authorization": f"Bearer {poster_login.json()['access_token']}"}
        posted = self.client.post(f"/api/invoices/{invoice_id}/post", headers=poster_headers)
        posted.raise_for_status()
        self.assertEqual(posted.json()["status"], "posted")
        duplicate = self.client.post(
            f"/api/sales-orders/{order_id}/convert",
            json={"warehouse_id": 1},
            headers=reviewer_headers,
        )
        self.assertEqual(duplicate.status_code, 400)
        after = self.client.get("/api/stock-by-warehouse", headers=self.headers)
        after.raise_for_status()
        after_qty = next(row["qty"] for row in after.json() if row["product_id"] == 1 and row["warehouse_id"] == 1)
        self.assertEqual(after_qty, before_qty - 1)

    def test_purchase_order_creator_cannot_approve_own_order(self):
        order = self.client.post(
            "/api/purchase-orders",
            json={"supplier_id": 1, "total": 100},
            headers=self.headers,
        )
        order.raise_for_status()
        order_id = order.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/purchase-orders/{order_id}/workflow",
                json={"action": "submit"},
                headers=self.headers,
            ).status_code,
            200,
        )
        response = self.client.post(
            f"/api/purchase-orders/{order_id}/workflow",
            json={"action": "approve"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_immediate_invoice_posting_is_rejected(self):
        response = self.client.post(
            "/api/invoices",
            json={
                "kind": "sale",
                "party_id": 2,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 1, "unit_price": "10.00"}],
                "post_now": True,
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Immediate posting is disabled", response.json()["detail"])

    def test_legacy_invoice_without_creator_identity_fails_closed(self):
        with self.main.SessionLocal() as session:
            invoice = self.main.Invoice(
                invoice_no="LEGACY-CONTROL-1",
                kind="sale",
                party_id=2,
                warehouse_id=1,
                subtotal=Decimal("10.00"),
                tax_rate=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total=Decimal("10.00"),
                status="submitted",
                created_by_id=None,
            )
            session.add(invoice)
            session.commit()
            invoice_id = invoice.id
        response = self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "approve"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("creator identity is unavailable", response.json()["detail"])

    def test_converted_invoice_preserves_creator_and_blocks_self_approval(self):
        reviewer_headers = self.create_user_headers("conversionreviewer")
        quotation = self.client.post(
            "/api/sales-quotations",
            json={
                "customer_id": 2,
                "lines": [{"product_id": 1, "qty": 1, "unit_price": "25.00"}],
            },
            headers=self.headers,
        )
        quotation.raise_for_status()
        quotation_id = quotation.json()["id"]
        self.client.post(
            f"/api/sales-quotations/{quotation_id}/workflow",
            json={"action": "submit"},
            headers=self.headers,
        ).raise_for_status()
        self.client.post(
            f"/api/sales-quotations/{quotation_id}/workflow",
            json={"action": "approve"},
            headers=reviewer_headers,
        ).raise_for_status()
        converted = self.client.post(
            f"/api/sales-quotations/{quotation_id}/convert",
            json={"warehouse_id": 1},
            headers=reviewer_headers,
        )
        converted.raise_for_status()
        invoice_id = converted.json()["invoice_id"]
        self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "submit"},
            headers=reviewer_headers,
        ).raise_for_status()
        blocked = self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "approve"},
            headers=reviewer_headers,
        )
        self.assertEqual(blocked.status_code, 403)
        invoices = self.client.get("/api/invoices", headers=self.headers)
        invoices.raise_for_status()
        row = next(item for item in invoices.json() if item["id"] == invoice_id)
        self.assertEqual(row["created_by"], "conversionreviewer")

    def test_purchase_receipt_is_the_stock_event_for_converted_po_invoice(self):
        reviewer_headers = self.create_user_headers("pocontrolreviewer")
        inventory_headers = self.create_user_headers("pocontroloperator", role="inventory")
        order = self.client.post(
            "/api/purchase-orders",
            json={
                "supplier_id": 1,
                "lines": [{"product_id": 2, "qty": 2, "unit_price": "11.00"}],
            },
            headers=self.headers,
        )
        order.raise_for_status()
        order_id = order.json()["id"]
        self.client.post(
            f"/api/purchase-orders/{order_id}/workflow",
            json={"action": "submit"},
            headers=self.headers,
        ).raise_for_status()
        self.client.post(
            f"/api/purchase-orders/{order_id}/workflow",
            json={"action": "approve"},
            headers=reviewer_headers,
        ).raise_for_status()
        converted = self.client.post(
            f"/api/purchase-orders/{order_id}/convert",
            json={"warehouse_id": 1},
            headers=reviewer_headers,
        )
        converted.raise_for_status()
        invoice_id = converted.json()["invoice_id"]
        self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "submit"},
            headers=reviewer_headers,
        ).raise_for_status()
        self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "approve"},
            headers=self.headers,
        ).raise_for_status()
        before = self.client.get("/api/stock-by-warehouse", headers=self.headers).json()
        before_qty = next(row["qty"] for row in before if row["product_id"] == 2 and row["warehouse_id"] == 1)
        missing_receipt = self.client.post(
            f"/api/invoices/{invoice_id}/post",
            headers=self.headers,
        )
        self.assertEqual(missing_receipt.status_code, 400)
        self.assertIn("goods receipt", missing_receipt.json()["detail"])
        receipt = self.client.post(
            "/api/purchase-receipts",
            json={"purchase_order_id": order_id, "warehouse_id": 1},
            headers=inventory_headers,
        )
        receipt.raise_for_status()
        after_receipt = self.client.get("/api/stock-by-warehouse", headers=self.headers).json()
        receipt_qty = next(row["qty"] for row in after_receipt if row["product_id"] == 2 and row["warehouse_id"] == 1)
        self.assertEqual(receipt_qty, before_qty + 2)
        with self.main.SessionLocal() as session:
            stored_receipt = session.query(self.main.PurchaseReceipt).filter_by(purchase_order_id=order_id).one()
            stored_receipt.status = "cancelled"
            session.commit()
        cancelled_receipt = self.client.post(f"/api/invoices/{invoice_id}/post", headers=self.headers)
        self.assertEqual(cancelled_receipt.status_code, 400)
        with self.main.SessionLocal() as session:
            stored_receipt = session.query(self.main.PurchaseReceipt).filter_by(purchase_order_id=order_id).one()
            stored_receipt.status = "posted"
            session.commit()
        posted = self.client.post(f"/api/invoices/{invoice_id}/post", headers=self.headers)
        posted.raise_for_status()
        after_post = self.client.get("/api/stock-by-warehouse", headers=self.headers).json()
        posted_qty = next(row["qty"] for row in after_post if row["product_id"] == 2 and row["warehouse_id"] == 1)
        self.assertEqual(posted_qty, receipt_qty)

    def test_inventory_role_cannot_read_financial_endpoints(self):
        inventory_headers = self.create_user_headers("financialboundary", role="inventory")
        draft = self.client.post(
            "/api/invoices",
            json={
                "kind": "sale",
                "party_id": 2,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 1, "unit_price": "12.00"}],
            },
            headers=self.headers,
        )
        draft.raise_for_status()
        for path in (
            "/api/accounts",
            "/api/journals",
            "/api/trial-balance",
            "/api/invoices",
            f"/api/invoices/{draft.json()['id']}",
            "/api/financial-summary",
            "/api/reconciliation",
        ):
            self.assertEqual(self.client.get(path, headers=inventory_headers).status_code, 403, path)
        dashboard = self.client.get("/api/dashboard", headers=inventory_headers)
        dashboard.raise_for_status()
        self.assertNotIn("sales", dashboard.json())
        self.assertNotIn("purchases", dashboard.json())
        self.assertNotIn("inventory_value", dashboard.json())
        products = self.client.get("/api/products", headers=inventory_headers)
        products.raise_for_status()
        self.assertTrue(all(row["cost"] is None and row["sale_price"] is None for row in products.json()))
        purchase_orders = self.client.get("/api/purchase-orders", headers=inventory_headers)
        purchase_orders.raise_for_status()
        self.assertTrue(all(row["total"] is None for row in purchase_orders.json()))
        sales_orders = self.client.get("/api/sales-orders", headers=inventory_headers)
        sales_orders.raise_for_status()
        self.assertTrue(all(row["total"] is None for row in sales_orders.json()))

    def test_payment_void_retains_history_and_reopens_invoice(self):
        reviewer_headers = self.create_user_headers("paymentreviewer")
        self.client.post(
            "/api/stock-adjustments",
            json={
                "product_id": 1,
                "warehouse_id": 1,
                "direction": "IN",
                "qty": 1,
                "reason": "Payment reversal test stock",
            },
            headers=self.headers,
        ).raise_for_status()
        draft = self.client.post(
            "/api/invoices",
            json={
                "kind": "sale",
                "party_id": 2,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 1, "unit_price": "30.00"}],
                "tax_rate": "0.00",
            },
            headers=self.headers,
        )
        draft.raise_for_status()
        invoice_id = draft.json()["id"]
        self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "submit"},
            headers=self.headers,
        ).raise_for_status()
        self.client.post(
            f"/api/invoices/{invoice_id}/workflow",
            json={"action": "approve"},
            headers=reviewer_headers,
        ).raise_for_status()
        self.client.post(f"/api/invoices/{invoice_id}/post", headers=reviewer_headers).raise_for_status()
        cash_before = self.client.get("/api/cash-summary", headers=self.headers).json()["receipts"]
        payment = self.client.post(
            "/api/payments",
            json={
                "kind": "receipt",
                "party_id": 2,
                "amount": "30.00",
                "invoice_id": invoice_id,
            },
            headers=self.headers,
        )
        payment.raise_for_status()
        payment_row = next(
            row
            for row in self.client.get("/api/payments", headers=self.headers).json()
            if row["payment_no"] == payment.json()["payment_no"]
        )
        voided = self.client.post(
            f"/api/payments/{payment_row['id']}/void",
            headers=reviewer_headers,
        )
        voided.raise_for_status()
        retained = next(
            row
            for row in self.client.get("/api/payments", headers=self.headers).json()
            if row["id"] == payment_row["id"]
        )
        self.assertEqual(retained["status"], "voided")
        self.assertEqual(retained["allocated"], 0)
        self.assertIsNotNone(retained["voided_at"])
        duplicate_void = self.client.post(
            f"/api/payments/{payment_row['id']}/void",
            headers=reviewer_headers,
        )
        self.assertEqual(duplicate_void.status_code, 400)
        reconciliation = self.client.get("/api/reconciliation", headers=self.headers).json()
        invoice_row = next(row for row in reconciliation if row["id"] == invoice_id)
        self.assertEqual(invoice_row["allocated"], 0)
        self.assertEqual(invoice_row["balance"], 30)
        cash_after = self.client.get("/api/cash-summary", headers=self.headers).json()["receipts"]
        self.assertEqual(cash_after, cash_before)
        with self.main.SessionLocal() as session:
            stored = session.get(self.main.Payment, payment_row["id"])
            allocation = session.query(self.main.PaymentAllocation).filter_by(payment_id=stored.id).one()
            self.assertEqual(stored.status, "voided")
            self.assertIsNotNone(stored.reversal_journal_id)
            self.assertFalse(allocation.active)

    def test_money_is_rounded_and_stored_as_decimal(self):
        draft = self.client.post(
            "/api/invoices",
            json={
                "kind": "sale",
                "party_id": 2,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 3, "unit_price": "0.10"}],
                "tax_rate": "5.00",
            },
            headers=self.headers,
        )
        draft.raise_for_status()
        with self.main.SessionLocal() as session:
            stored = session.get(self.main.Invoice, draft.json()["id"])
            self.assertIsInstance(stored.subtotal, Decimal)
            self.assertEqual(stored.subtotal, Decimal("0.30"))
            self.assertEqual(stored.tax_amount, Decimal("0.02"))
            self.assertEqual(stored.total, Decimal("0.32"))

    def test_health_route_is_defined_once(self):
        health_routes = [
            route
            for route in self.main.app.routes
            if getattr(route, "path", None) == "/api/health" and "GET" in getattr(route, "methods", set())
        ]
        self.assertEqual(len(health_routes), 1)


if __name__ == "__main__":
    unittest.main()
