"""事件列表的页码分页。"""


def paginate_events(events: list[str], *, page: int, page_size: int) -> list[str]:
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    start = page * page_size
    end = start + page_size
    return events[start:end]
