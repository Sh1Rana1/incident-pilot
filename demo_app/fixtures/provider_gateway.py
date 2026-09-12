"""模拟不可检查源码的外部供应商网关。"""


PROVIDER_TIMEOUT_LIMIT_SECONDS = 10


def validate_timeout(timeout_seconds: int) -> None:
    if timeout_seconds > PROVIDER_TIMEOUT_LIMIT_SECONDS:
        raise RuntimeError("HTTP 422: timeout_policy_violation")
