"""订单支付客户端；gateway 由调用方注入。"""


def charge_order(gateway, order_id: str, amount: int) -> str:
    for attempt in range(2):
        try:
            return gateway.charge(order_id, amount)
        except TimeoutError:
            if attempt == 1:
                raise
    raise RuntimeError("payment attempts exhausted")
