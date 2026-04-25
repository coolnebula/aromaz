import unittest

from app.services.order_service import _totals


class TaxTotalsTests(unittest.TestCase):
    def test_configurable_percent_applies(self):
        items = [{"price": 100, "qty": 1, "voided": False}]
        t = _totals(items, discount=0, tax_rate_percent=10.0)
        self.assertEqual(t["subtotal"], 100.0)
        self.assertEqual(t["tax"], 10.0)
        self.assertEqual(t["total"], 110.0)

    def test_percent_applied_after_discount(self):
        items = [{"price": 200, "qty": 1, "voided": False}]
        t = _totals(items, discount=50, tax_rate_percent=5.0)
        self.assertEqual(t["subtotal"], 200.0)
        self.assertEqual(t["discount"], 50.0)
        # (200 - 50) * 0.05 = 7.5
        self.assertEqual(t["tax"], 7.5)
        self.assertEqual(t["total"], 157.5)


if __name__ == "__main__":
    unittest.main()
