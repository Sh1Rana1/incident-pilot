"""运行三个确定性故障案例：python -m demo_app.run_case <case_id>。"""

import argparse

from demo_app.app.api import post_users
from demo_app.app.database import create_connection
from demo_app.app.pool import ConnectionPool
from demo_app.app.worker import process_job


CASES = ("missing_user_id", "schema_mismatch", "connection_leak")


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
    else:
        raise ValueError(f"未知案例: {case_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 IncidentPilot 故障演示案例")
    parser.add_argument("case_id", choices=CASES)
    arguments = parser.parse_args()
    run_case(arguments.case_id)


if __name__ == "__main__":
    main()
