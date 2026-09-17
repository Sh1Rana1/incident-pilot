"""确定性的 Notify SDK v3 模拟器。"""


def send_message(*, recipient: str, message: str) -> None:
    if not recipient or not message:
        raise ValueError("recipient and message are required")
