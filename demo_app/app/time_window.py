"""比较任务完成时间与服务等级截止时间。"""

from datetime import datetime


def completed_within_sla(completed_at: str, deadline: str) -> bool:
    completed = datetime.fromisoformat(completed_at)
    due = datetime.fromisoformat(deadline)
    return completed <= due
