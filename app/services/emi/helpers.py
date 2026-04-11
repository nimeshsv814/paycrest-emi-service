from __future__ import annotations


def _customer_query(customer_id: str | int) -> dict:
    filters: list[dict] = [{"customer_id": customer_id}, {"_id": customer_id}]
    if isinstance(customer_id, str) and customer_id.isdigit():
        as_int = int(customer_id)
        filters.extend([{"customer_id": as_int}, {"_id": as_int}])
    elif isinstance(customer_id, int):
        as_str = str(customer_id)
        filters.extend([{"customer_id": as_str}, {"_id": as_str}])
    return {"$or": filters}
