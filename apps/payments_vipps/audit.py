"""Thin shim over ``apps.orders.audit`` for the Vipps webhook & reconciler.

Keeps the call sites inside ``handlers.py`` / ``capture.py`` /
``vipps_reconcile`` short and consistent.
"""
from __future__ import annotations

from apps.orders.audit import record_order_event
from apps.orders.models import Order


def record_payment_status_change(
    order: Order,
    *,
    old_status: str,
    new_status: str,
    source: str,
    note: str = '',
) -> None:
    """Record a payment_status transition. No-op if the status didn't change."""
    if old_status == new_status:
        return
    record_order_event(
        order,
        action='payment_status_changed',
        source=source,
        from_value={'payment_status': old_status},
        to_value={'payment_status': new_status},
        note=note,
    )
