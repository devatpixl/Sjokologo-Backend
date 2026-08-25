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


def send_welcome_email(user, password_url: str | None = None) -> bool:
    """#1 — Welcome the brand-new customer to Sjoko Loco.

    When ``password_url`` is given the mail leads with a "create your
    password" call to action: registration no longer asks for a password on
    the form, so this link is how the customer first gets into their account.
    """
    storefront = 'https://sjokoloco.no'
    first = _first_name(user)
    subject = 'Velkommen til Sjoko Loco'

    password_text = (
        'Velg ditt eget passord her:\n'
        f'{password_url}\n\n'
        'Lenken er gyldig i 7 dager.\n\n'
    ) if password_url else ''

    text = (
        f'Hei, {first}!\n\n'
        'Takk for at du opprettet en konto hos Sjoko Loco.\n\n'
        f'{password_text}'
        'Hos oss finner du håndlaget konfekt fra Ås, laget med naturlige '
        'råvarer — helt uten aroma eller konserveringsmidler.\n\n'
        'Fri frakt på alle bestillinger over 299 kr.\n\n'
        f'Handle her: {storefront}\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Takk for at du opprettet en konto hos Sjoko Loco.</p>'
        + ('<p style="margin:0 0 12px;">Trykk på knappen under for å velge ditt eget '
           'passord. Lenken er gyldig i 7 dager.</p>' if password_url else '')
        + '<p style="margin:0 0 12px;">Hos oss finner du håndlaget konfekt fra Ås, '
          'laget med naturlige råvarer — helt uten aroma eller konserveringsmidler.</p>'
        + '<p style="margin:0; color:#C9A35B;">Fri frakt på alle bestillinger over 299 kr.</p>'
    )

    if password_url:
        html = render_layout(
            eyebrow='◈ Velkommen',
            heading=f'Hei, {first}!',
            intro_html=intro_html,
            cta_url=password_url,
            cta_label='Opprett passord',
            cta_secondary_url=storefront,
            cta_secondary_label='Handle her',
        )
    else:
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


def send_password_reset_email(user, password_url: str) -> bool:
    """#3 — "Glemt passord": a fresh link to choose a new password.

    Shares the token format with the welcome mail, so a customer who never
    opened their welcome e-mail can recover through this flow too.
    """
    first = _first_name(user)
    subject = 'Velg nytt passord — Sjoko Loco'

    text = (
        f'Hei, {first}!\n\n'
        'Vi fikk en forespørsel om nytt passord til kontoen din hos Sjoko Loco.\n\n'
        'Velg nytt passord her:\n'
        f'{password_url}\n\n'
        'Lenken er gyldig i 7 dager.\n\n'
        'Har du ikke bedt om dette, kan du se bort fra denne e-posten — '
        'passordet ditt forblir uendret.\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Vi fikk en forespørsel om nytt passord til '
        'kontoen din hos Sjoko Loco.</p>'
        '<p style="margin:0 0 12px;">Trykk på knappen under for å velge et nytt '
        'passord. Lenken er gyldig i 7 dager.</p>'
        '<p style="margin:0; color:#8A7F76;">Har du ikke bedt om dette, kan du se '
        'bort fra denne e-posten — passordet ditt forblir uendret.</p>'
    )

    html = render_layout(
        eyebrow='◈ Passord',
        heading=f'Hei, {first}!',
        intro_html=intro_html,
        cta_url=password_url,
        cta_label='Velg nytt passord',
    )

    return send(
        to=user.email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='password_reset',
    )
