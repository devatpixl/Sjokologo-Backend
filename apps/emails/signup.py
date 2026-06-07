"""Signup-flow emails: welcome (#1) and admin notification (#2)."""

from __future__ import annotations

from html import escape

from django.conf import settings

from .layout import render_layout, render_kv_block
from .transactional import send


def _first_name(user) -> str:
    raw = (user.name or '').strip()
    if not raw:
        return 'der'
    return raw.split()[0]


def send_welcome_email(user) -> bool:
    """#1 — Welcome the brand-new customer to Sjoko Loco."""
    storefront = settings.STOREFRONT_URL.rstrip('/')
    first = _first_name(user)
    subject = 'Velkommen til Sjoko Loco'

    text = (
        f'Hei, {first}!\n\n'
        'Takk for at du opprettet en konto hos Sjoko Loco.\n\n'
        'Hos oss finner du håndlaget konfekt fra Ås, laget med naturlige '
        'råvarer — helt uten aroma eller konserveringsmidler.\n\n'
        'Fri frakt på alle bestillinger over 349 kr.\n\n'
        f'Handle her: {storefront}\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Takk for at du opprettet en konto hos Sjoko Loco.</p>'
        '<p style="margin:0 0 12px;">Hos oss finner du håndlaget konfekt fra Ås, '
        'laget med naturlige råvarer — helt uten aroma eller konserveringsmidler.</p>'
        '<p style="margin:0; color:#C9A35B;">Fri frakt på alle bestillinger over 349 kr.</p>'
    )

    html = render_layout(
        eyebrow='◈ Velkommen',
        heading=f'Hei, {first}!',
        intro_html=intro_html,
        cta_url=storefront,
        cta_label='Handle her',
    )

    return send(
        to=user.email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='welcome',
    )


def send_admin_new_signup_email(user) -> bool:
    """#2 — Tell ops a new customer just registered."""
    recipients = [r.strip() for r in (settings.ADMIN_NOTIFY_EMAILS or []) if r.strip()]
    if not recipients:
        # No internal recipients configured — silently no-op (e.g. CI).
        return False

    admin_url = (settings.ADMIN_URL or '').rstrip('/')
    name = (user.name or '').strip() or '(uten navn)'
    phone = (user.phone or '').strip() or '—'
    customer_link = f'{admin_url}/customers/{user.id}' if admin_url else ''

    subject = f'Ny kunde registrert — {name}'

    text_lines = [
        f'Ny kunde registrert på sjokoloco.no.',
        '',
        f'Navn:   {name}',
        f'E-post: {user.email}',
        f'Telefon: {phone}',
        f'ID:     {user.id}',
    ]
    if customer_link:
        text_lines += ['', f'Se kunde i admin: {customer_link}']
    text = '\n'.join(text_lines)

    intro_html = (
        '<p style="margin:0;">En ny kunde har nettopp opprettet en konto.</p>'
    )

    kv_rows = [
        ('Navn', name),
        ('E-post', user.email),
        ('Telefon', phone),
        ('Kunde-ID', str(user.id)),
    ]

    html = render_layout(
        eyebrow='◈ Intern varsling',
        heading='Ny kunde registrert',
        intro_html=intro_html,
        blocks_html=render_kv_block('◈ Detaljer', kv_rows),
        cta_url=customer_link or None,
        cta_label='Se kunde i admin' if customer_link else None,
        closing_html=(
            '<p style="margin:0; font-size:12px; color:rgba(245,239,230,0.55);">'
            'Sendt automatisk fra Sjoko Loco-API</p>'
        ),
    )

    return send(
        to=recipients,
        subject=subject,
        text_body=text,
        html_body=html,
        label='admin_new_signup',
    )
