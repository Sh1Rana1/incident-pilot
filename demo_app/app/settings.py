"""加载通知服务的客户端超时配置。"""


def load_timeout_ms(environment: dict[str, str]) -> int:
    return int(environment.get("REQUEST_TIMEOUT_MS", "5000"))


def validate_timeout_configuration(environment: dict[str, str]) -> None:
    configured = load_timeout_ms(environment)
    required = int(environment["SERVICE_TIMEOUT_MS"])
    if configured != required:
        raise RuntimeError(
            f"timeout configuration mismatch: loaded {configured}, expected {required}"
        )
