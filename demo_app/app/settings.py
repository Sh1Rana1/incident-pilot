"""应用超时配置加载。"""


def load_request_timeout(environment: dict[str, str]) -> int:
    variable_name = "REQUEST_TIMEOUT_SECONDS"
    raw_value = environment.get(variable_name)
    if raw_value is None:
        raise KeyError(f"missing environment variable: {variable_name}")
    timeout = int(raw_value)
    if timeout <= 0:
        raise ValueError("HTTP timeout must be positive")
    return timeout
