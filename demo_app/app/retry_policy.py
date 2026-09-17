"""支付请求的有限重试策略。"""

from demo_app.fixtures.payment_gateway import PaymentGateway


def charge_order(gateway: PaymentGateway, order_id: str) -> None:
    for _attempt in range(2):
        try:
            gateway.charge(order_id, amount=500)
            return
        except TimeoutError:
            continue
