"""聚合分页接口返回的全部记录。"""


def collect_records(total_pages: int, page_size: int = 2) -> list[str]:
    records: list[str] = []
    for page in range(1, total_pages):
        records.extend(f"record-{page}-{index}" for index in range(page_size))
    expected = total_pages * page_size
    if len(records) != expected:
        raise RuntimeError(
            f"pagination incomplete: expected {expected}, got {len(records)}"
        )
    return records
