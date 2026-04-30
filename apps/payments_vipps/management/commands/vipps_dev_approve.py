"""Test-environment helper: simulate a customer approving a Vipps payment.

Replaces the "tap Approve in the Vipps MT app on a Norwegian phone" step in
local development. Calls Vipps' test-only force-approve endpoint, which then
fires the AUTHORIZED webhook to our registered URL exactly as a real
approval would.

Usage:
    python manage.py vipps_dev_approve <reference> [--phone 4748049667]

Refuses to run against the production base URL.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.orders.models import Order
from apps.payments_vipps.client import VippsClient
from apps.payments_vipps.exceptions import VippsAPIError


class Command(BaseCommand):
    help = 'Force-approve a Vipps test payment without using the MT app.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            'reference',
            help='Vipps reference (e.g. sl-00005-3d87ace0) of the order to approve.',
        )
        parser.add_argument(
            '--phone',
            default=None,
            help='Test user phone number in E.164 without "+" (e.g. 4748049667). '
                 'Defaults to settings.VIPPS_TEST_PHONE.',
        )

    def handle(self, *args, **options):
        reference: str = options['reference']
        phone: str | None = options.get('phone') or getattr(settings, 'VIPPS_TEST_PHONE', None)
        if not phone:
            raise CommandError(
                'No phone number provided. Pass --phone 4748049667 or set VIPPS_TEST_PHONE in .env.'
            )

        try:
            order = Order.objects.get(vipps_reference=reference)
        except Order.DoesNotExist:
            raise CommandError(f'No order found with vipps_reference={reference!r}')

        if order.payment_status != 'CREATED':
            raise CommandError(
                f'Order is in payment_status={order.payment_status!r}; '
                f'force-approve only makes sense for CREATED payments.'
            )

        if not order.vipps_redirect_url:
            raise CommandError('Order has no vipps_redirect_url; cannot extract token.')

        token = _extract_token(order.vipps_redirect_url)
        if not token:
            raise CommandError(
                f'Could not find a "token" query parameter in '
                f'vipps_redirect_url={order.vipps_redirect_url!r}'
            )

        self.stdout.write(f'Force-approving {reference} as phone={phone}...')

        client = VippsClient()
        try:
            client.force_approve(reference=reference, phone_number=phone, token=token)
        except VippsAPIError as exc:
            if exc.status_code == 404:
                raise CommandError(
                    f'Vipps returned 404. The reference may have expired or the test '
                    f'user has never approved a payment in the Vipps MT app. '
                    f'(Vipps requires test users be bootstrapped via one real MT-app '
                    f'approval before force-approve can be used.) Raw: {exc}'
                )
            raise CommandError(f'Force-approve failed: {exc}')

        self.stdout.write(self.style.SUCCESS(
            'Force-approve accepted. Watch Django logs for the AUTHORIZED webhook.'
        ))


def _extract_token(redirect_url: str) -> str | None:
    """Return the value of the ``token`` query parameter, or None."""
    parsed = urlparse(redirect_url)
    qs = parse_qs(parsed.query)
    values = qs.get('token') or []
    return values[0] if values else None
