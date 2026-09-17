"""异步账单加载与同步展示入口。"""


async def load_invoice(invoice_id: str) -> dict:
    return {"invoice_id": invoice_id, "total": 128}


def invoice_total(invoice_id: str) -> int:
    pending = load_invoice(invoice_id)
    try:
        return pending["total"]
    finally:
        pending.close()
