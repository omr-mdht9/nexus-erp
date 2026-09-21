import importlib
import os
import tempfile
import unittest
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
            "/api/invoices",
            json={
                "kind": "purchase",
                "party_id": 1,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 5, "unit_price": 10}],
                "post_now": True,
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
            "/api/invoices",
            json={
                "kind": "purchase",
                "party_id": 1,
                "warehouse_id": 1,
                "lines": [{"product_id": 1, "qty": 3, "unit_price": 10}],
                "post_now": True,
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
        response = self.client.post(
            "/api/stock-adjustments",
            json={"product_id": 2, "warehouse_id": 1, "direction": "OUT", "qty": 2, "reason": "Count correction"},
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


if __name__ == "__main__":
    unittest.main()
