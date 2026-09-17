"""运行十二个预登记确定性故障案例，支持模块和脚本两种启动方式。"""

import argparse
import sys
from pathlib import Path


# 直接执行 ``python demo_app/run_case.py`` 时，Python 只把 demo_app 目录
# 放进模块搜索路径。显式加入项目根目录，让下面的绝对导入也能找到 demo_app。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_app.app.api import post_users
from demo_app.app.async_jobs import invoice_total
from demo_app.app.cache_store import read_profile, seed_profile_cache
from demo_app.app.database import create_connection
from demo_app.app.notification_client import notify_user
from demo_app.app.pagination import collect_records
from demo_app.app.pool import ConnectionPool
from demo_app.app.retry_policy import charge_order
from demo_app.app.settings import validate_timeout_configuration
from demo_app.app.time_window import completed_within_sla
from demo_app.app.transactions import create_import_connection, import_then_continue
from demo_app.app.worker import process_job
from demo_app.app.webhook import deliver_webhook
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
    "transaction_rollback",
    "dependency_contract_change",
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
        invoice_total("invoice-001")
    elif case_id == "retry_non_idempotent":
        charge_order(PaymentGateway(), "order-001")
    elif case_id == "timezone_mismatch":
        completed_within_sla(
            "2026-09-15T09:30:00+00:00",
            "2026-09-15T10:00:00",
        )
    elif case_id == "cache_key_version":
        cache = seed_profile_cache("user-001")
        read_profile(cache, "user-001")
    elif case_id == "pagination_off_by_one":
        collect_records(total_pages=3)
    elif case_id == "config_env_rename":
        validate_timeout_configuration({"SERVICE_TIMEOUT_MS": "1200"})
    elif case_id == "transaction_rollback":
        connection = create_import_connection()
        try:
            import_then_continue(connection)
        finally:
            connection.close()
    elif case_id == "dependency_contract_change":
        notify_user("user-001")
    else:
        raise ValueError(f"未知案例: {case_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 IncidentPilot 故障演示案例")
    parser.add_argument("case_id", choices=CASES)
    arguments = parser.parse_args()
    run_case(arguments.case_id)


if __name__ == "__main__":
    main()
