"""Single emission point for OrderAuditLog rows.

All code paths that mutate an Order in a way ops cares about must call
``record_order_event``. Centralising this lets us add filtering, batching,
or alerting in one place later.
"""
from __future__ import annotations

from typing import Any

from .models import Order, OrderAuditLog


def record_order_event(
    order: Order,
    *,
    action: str,
    source: str,
    from_value: Any = None,
    to_value: Any = None,
    actor_user=None,
    note: str = '',
) -> OrderAuditLog:
    """Append a single audit row.

    Returns the created row. Failure to write is intentionally not swallowed
    — if auditing fails we want to know about it.
    """
    return OrderAuditLog.objects.create(
        order=order,
        action=action,
        source=source,
        from_value=from_value,
        to_value=to_value,
        actor_user=actor_user,
        note=note,
    )
