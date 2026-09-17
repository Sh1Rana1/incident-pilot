"""本地支付模拟器：首次扣款成功后丢失响应，不访问网络。"""


class PaymentGateway:
    def __init__(self, lose_first_response: bool = True):
        self.lose_first_response = lose_first_response
        self.charges: list[tuple[str, int]] = []
        self.receipts: dict[str, str] = {}

    def charge(self, order_id: str, amount: int, *, idempotency_key=None) -> str:
        if idempotency_key is not None and idempotency_key in self.receipts:
            return self.receipts[idempotency_key]
        self.charges.append((order_id, amount))
        receipt = f"receipt-{len(self.charges)}"
        if idempotency_key is not None:
            self.receipts[idempotency_key] = receipt
        if self.lose_first_response and len(self.charges) == 1:
            raise TimeoutError("payment response lost after commit")
        return receipt
