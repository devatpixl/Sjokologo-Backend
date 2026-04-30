"""Reconciliation cron entry point.

Scheduled via OS cron, e.g. ``*/5 * * * * cd /srv/sjokoloko-api && python manage.py vipps_reconcile``.

Finds Order rows that are stuck in CREATED, AUTHORIZED, or FAILED for more than
60 seconds, calls Vipps' authoritative ``GET /payments/{reference}`` for each,
and converges local state. If an order is in AUTHORIZED but Vipps reports it
captured, we converge to CAPTURED. If it's still AUTHORIZED at Vipps too, we
retry capture using the persisted idempotency key.

Batch size is bounded so a single run never overwhelms the API or the DB.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone as djtz

from apps.orders.models import Order

from apps.payments_vipps.capture import apply_aggregate_snapshot, capture_payment
from apps.payments_vipps.client import VippsClient
from apps.payments_vipps.exceptions import VippsAPIError

logger = logging.getLogger('apps.payments_vipps')

DEFAULT_BATCH_SIZE = 50
DEFAULT_GRACE_SECONDS = 60


class Command(BaseCommand):
    help = 'Reconcile stuck Vipps orders with the authoritative Vipps state.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
            help=f'Maximum orders to process per run (default {DEFAULT_BATCH_SIZE}).',
        )
        parser.add_argument(
            '--grace-seconds', type=int, default=DEFAULT_GRACE_SECONDS,
            help=f'Skip orders younger than this many seconds (default {DEFAULT_GRACE_SECONDS}).',
        )

    def handle(self, *args, **options) -> None:
        batch_size: int = options['batch_size']
        grace_seconds: int = options['grace_seconds']

        cutoff = djtz.now() - timedelta(seconds=grace_seconds)
        client = VippsClient()

        candidates = (
            Order.objects
            .filter(vipps_reference__isnull=False)
            .filter(payment_status__in=['CREATED', 'AUTHORIZED', 'FAILED'])
            .filter(Q(last_vipps_sync_at__lt=cutoff) | Q(last_vipps_sync_at__isnull=True))
            .order_by('last_vipps_sync_at', 'created_at')[:batch_size]
        )

        processed = 0
        for order in candidates:
            try:
                snapshot = client.get_payment(order.vipps_reference)
            except VippsAPIError as exc:
                logger.warning(
                    'vipps.reconcile.get_failed',
                    extra={
                        'order_id': order.pk,
                        'reference': order.vipps_reference,
                        'status_code': exc.status_code,
                    },
                )
                continue

            order = apply_aggregate_snapshot(order, snapshot, source='reconciler')

            # If we're still AUTHORIZED at both ends, retry capture.
            if order.payment_status == 'AUTHORIZED':
                try:
                    capture_payment(order, client=client, source='reconciler')
                except VippsAPIError as exc:
                    logger.warning(
                        'vipps.reconcile.capture_failed',
                        extra={
                            'order_id': order.pk,
                            'reference': order.vipps_reference,
                            'status_code': exc.status_code,
                        },
                    )
            processed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Reconciled {processed} order(s) (batch_size={batch_size}, grace={grace_seconds}s).'
        ))
