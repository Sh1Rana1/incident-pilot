"""后台任务处理。异常路径故意没有释放连接。"""

from demo_app.app.pool import ConnectionPool


def process_job(pool: ConnectionPool, should_fail: bool) -> None:
    connection = pool.acquire()
    if should_fail:
        raise ValueError("invalid job payload")
    pool.release(connection)
