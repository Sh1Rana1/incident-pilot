"""通知 SDK 的应用适配层。"""


def send_welcome_notification(sdk, *, recipient: str, message: str) -> str:
    return sdk.send(recipient=recipient, message=message)
