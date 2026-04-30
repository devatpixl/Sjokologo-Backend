"""Idempotently (re)register our webhook subscription with Vipps.

Run once per environment (test, prod). The signing secret is returned by Vipps
only at registration time; this command persists it to the
``VippsWebhookRegistration`` table and prints it for ops to mirror to a secrets
vault if needed.

If a registration already exists for our ``VIPPS_WEBHOOK_URL``, the command
deletes it first (both at Vipps and locally) and creates a fresh one — this is
the only way to recover a lost secret.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.payments_vipps.client import VippsClient
from apps.payments_vipps.exceptions import VippsAPIError
from apps.payments_vipps.models import VippsWebhookRegistration


DEFAULT_EVENTS = [
    'epayments.payment.created.v1',
    'epayments.payment.authorized.v1',
    'epayments.payment.captured.v1',
    'epayments.payment.refunded.v1',
    'epayments.payment.cancelled.v1',
    'epayments.payment.aborted.v1',
    'epayments.payment.expired.v1',
    'epayments.payment.terminated.v1',
]


class Command(BaseCommand):
    help = 'Register (or re-register) the Vipps webhook for this environment.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--url',
            default=None,
            help='Override the webhook URL (defaults to settings.VIPPS_WEBHOOK_URL).',
        )

    def handle(self, *args, **options):
        webhook_url: str = options.get('url') or getattr(settings, 'VIPPS_WEBHOOK_URL', '')
        if not webhook_url:
            raise CommandError(
                'No webhook URL configured. Set VIPPS_WEBHOOK_URL in .env or pass --url.'
            )

        client = VippsClient()

        # 1. List existing webhooks and delete any pointing at our URL.
        try:
            existing = client.list_webhooks()
        except VippsAPIError as exc:
            raise CommandError(f'Failed to list existing webhooks: {exc}')

        for entry in existing:
            if entry.get('url') == webhook_url:
                webhook_id = entry.get('id', '')
                self.stdout.write(f'Deleting existing webhook {webhook_id} pointing at {webhook_url}')
                try:
                    client.delete_webhook(webhook_id)
                except VippsAPIError as exc:
                    self.stdout.write(self.style.WARNING(
                        f'  delete failed (continuing): {exc}'
                    ))
                VippsWebhookRegistration.objects.filter(webhook_id=webhook_id).update(is_active=False)

        # Mark all local registrations inactive — only the new one will be active.
        VippsWebhookRegistration.objects.update(is_active=False)

        # 2. Register fresh.
        try:
            result = client.register_webhook(webhook_url, DEFAULT_EVENTS)
        except VippsAPIError as exc:
            raise CommandError(f'Failed to register webhook: {exc}')

        webhook_id = result.get('id', '')
        secret = result.get('secret', '')
        if not webhook_id or not secret:
            raise CommandError(f'Vipps returned an unexpected payload: {result!r}')

        VippsWebhookRegistration.objects.create(
            webhook_id=webhook_id,
            url=webhook_url,
            events=DEFAULT_EVENTS,
            secret=secret,
            is_active=True,
        )

        self.stdout.write(self.style.SUCCESS('Webhook registered successfully.'))
        self.stdout.write(f'  webhook_id: {webhook_id}')
        self.stdout.write(f'  url:        {webhook_url}')
        self.stdout.write(f'  events:     {len(DEFAULT_EVENTS)} subscribed')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'IMPORTANT: the signing secret is shown once and stored in the database.'
        ))
        self.stdout.write(f'  secret: {secret}')
        self.stdout.write('')
        self.stdout.write(
            'Mirror this value to your secrets vault if you operate one. '
            'If lost, re-run this command to rotate.'
        )
