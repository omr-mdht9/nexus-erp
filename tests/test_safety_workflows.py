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
        self.assertEqual(response.json(), {"status": "ok", "database": "connected"})

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
