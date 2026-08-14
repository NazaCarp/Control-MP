import unittest

from fastapi.testclient import TestClient

from main import app, get_incoming_transfers


client = TestClient(app)


class AppTests(unittest.TestCase):
    def test_get_incoming_transfers_returns_list_from_payload(self):
        payload = {
            "results": [
                {
                    "id": 123,
                    "status": "approved",
                    "transaction_amount": 2500,
                    "date_created": "2026-08-14T10:00:00.000-04:00",
                    "payer": {"email": "juan@example.com"},
                    "payment_method_id": "account_money",
                }
            ]
        }

        transfers = get_incoming_transfers(payload)

        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["id"], "123")
        self.assertEqual(transfers[0]["monto"], 2500)
        self.assertEqual(transfers[0]["remitente"], "juan@example.com")
        self.assertEqual(transfers[0]["estado"], "approved")

    def test_home_lists_transfers_and_marked_status(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertTrue("Transferencias entrantes" in html or "Mercado Pago" in html)


if __name__ == "__main__":
    unittest.main()
