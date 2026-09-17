"""确定性的外部支付网关模拟器。"""


class PaymentGateway:
    def __init__(self) -> None:
        self.charged_orders: set[str] = set()

    def charge(self, order_id: str, amount: int) -> None:
        if order_id in self.charged_orders:
            raise RuntimeError(f"duplicate charge: {order_id}")
        self.charged_orders.add(order_id)
        raise TimeoutError(f"gateway response lost after charging {amount}")
