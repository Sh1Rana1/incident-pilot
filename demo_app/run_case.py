"""运行十个预登记确定性故障案例，支持模块和脚本两种启动方式。"""

import argparse
import asyncio
import sys
from pathlib import Path


# 直接执行 ``python demo_app/run_case.py`` 时，Python 只把 demo_app 目录
# 放进模块搜索路径。显式加入项目根目录，让下面的绝对导入也能找到 demo_app。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_app.app.api import post_users
from demo_app.app.database import create_connection
from demo_app.app.pool import ConnectionPool
from demo_app.app.worker import process_job
from demo_app.app.webhook import deliver_webhook
from demo_app.app.async_jobs import profile_name
from demo_app.app.retry_policy import charge_order
from demo_app.app.time_window import completed_within_sla
from demo_app.app.cache_store import load_profile_cache, seed_profile_cache
from demo_app.app.pagination import paginate_events
from demo_app.app.settings import load_request_timeout
from demo_app.fixtures.payment_gateway import PaymentGateway


CASES = (
    "missing_user_id",
    "schema_mismatch",
    "connection_leak",
    "documentation_required",
    "async_missing_await",
    "retry_non_idempotent",
    "timezone_mismatch",
    "cache_key_version",
    "pagination_off_by_one",
    "config_env_rename",
)


def run_case(case_id: str) -> None:
    if case_id == "missing_user_id":
        post_users({"email": "demo@example.com"}, create_connection())
    elif case_id == "schema_mismatch":
        post_users(
            {"user_id": "user-001", "email": "demo@example.com"},
            create_connection(),
        )
    elif case_id == "connection_leak":
        pool = ConnectionPool(max_size=2)
        for _ in range(2):
            try:
                process_job(pool, should_fail=True)
            except ValueError:
                pass
        process_job(pool, should_fail=False)
    elif case_id == "documentation_required":
        deliver_webhook()
    elif case_id == "async_missing_await":
        asyncio.run(profile_name("user-001"))
    elif case_id == "retry_non_idempotent":
        gateway = PaymentGateway()
        charge_order(gateway, "order-001", 100)
        if len(gateway.charges) != 1:
            raise RuntimeError("duplicate charge: expected 1, got 2")
    elif case_id == "timezone_mismatch":
        within_sla = completed_within_sla(
            "2026-09-18T00:00:00Z",
            "2026-09-18T08:45:00+08:00",
            max_minutes=60,
        )
        if not within_sla:
            raise RuntimeError("timezone mismatch: expected 45 minutes within SLA")
    elif case_id == "cache_key_version":
        cache = seed_profile_cache("user-001")
        load_profile_cache(cache, "user-001")
    elif case_id == "pagination_off_by_one":
        events = ["event-001", "event-002", "event-003"]
        first_page = paginate_events(events, page=1, page_size=2)
        if first_page != events[:2]:
            raise RuntimeError(
                f"pagination off by one: expected {events[:2]}, got {first_page}"
            )
    elif case_id == "config_env_rename":
        load_request_timeout({"HTTP_TIMEOUT_SECONDS": "15"})
    else:
        raise ValueError(f"未知案例: {case_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 IncidentPilot 故障演示案例")
    parser.add_argument("case_id", choices=CASES)
    arguments = parser.parse_args()
    run_case(arguments.case_id)


if __name__ == "__main__":
    main()
