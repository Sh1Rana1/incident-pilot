"""按需验证支付的成功路径和响应丢失路径。"""

import unittest

from demo_app.app.retry_policy import charge_order
from demo_app.fixtures.payment_gateway import PaymentGateway


class PaymentContractTests(unittest.TestCase):
    def test_lost_response_preserves_single_charge(self):
        gateway = PaymentGateway()
        self.assertEqual(charge_order(gateway, "order-001", 100), "receipt-1")
        self.assertEqual(gateway.charges, [("order-001", 100)])

    def test_successful_orders_remain_independent(self):
        gateway = PaymentGateway(lose_first_response=False)
        self.assertEqual(charge_order(gateway, "order-001", 100), "receipt-1")
        self.assertEqual(charge_order(gateway, "order-002", 200), "receipt-2")
        self.assertEqual(gateway.charges, [("order-001", 100), ("order-002", 200)])
