"""微型连接池实现。"""


class ConnectionPool:
    def __init__(self, max_size: int = 2):
        self.max_size = max_size
        self.active = 0

    def acquire(self) -> object:
        if self.active >= self.max_size:
            raise RuntimeError("connection pool exhausted")
        self.active += 1
        return object()

    def release(self, connection: object) -> None:
        self.active -= 1
