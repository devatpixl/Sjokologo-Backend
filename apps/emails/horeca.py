"""HORECA portal e-mails: registration received, approved, rejected, and the
internal heads-up to Sjoko Loco (K-57, K-59).

Same machinery as every other mail in this project — `render_layout` for the
HTML and the single `send()` in transactional.py, which is where
EMAIL_TEST_OVERRIDE is honoured. Nothing here talks to Django's mail API
directly; the one place that does (apps/users/loyalty.py) is the outlier, not
the pattern.
"""
from __future__ import annotations

from django.conf import settings

from .layout import (
    render_items_table,
    render_kv_block,
    render_layout,
    render_status_box,
)
from .transactional import send

PORTAL_PATH = '/horeca'


def _first_name(user) -> str:
    raw = (user.name or '').strip()
    return raw.split()[0] if raw else 'der'


def _portal_url() -> str:
    return f"{(settings.STOREFRONT_URL or '').rstrip('/')}{PORTAL_PATH}"


def send_horeca_registration_received_email(user, company, password_url=None) -> bool:
    """K-5 — we have the registration; approval is a human step and may wait."""
    first = _first_name(user)
    subject = 'Vi har mottatt registreringen deres'

    password_text = (
        f'Velg ditt eget passord her:\n{password_url}\n\n'
        'Lenken er gyldig i 7 dager.\n\n'
    ) if password_url else ''

    text = (
        f'Hei, {first}!\n\n'
        f'Vi har mottatt registreringen for {company.name}.\n\n'
        f'{password_text}'
        'Kontoen står nå som "venter godkjenning". Vi ser over den så snart vi '
        'kan, og du får en e-post når den er klar. Du kan logge inn og se deg '
        'om med en gang, men bestillinger kan ikke sendes før kontoen er '
        'godkjent.\n\n'
        f'Portalen: {_portal_url()}\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )

    intro_html = (
        f'<p style="margin:0 0 12px;">Vi har mottatt registreringen for '
        f'<strong>{company.name}</strong>.</p>'
        + ('<p style="margin:0 0 12px;">Trykk på knappen under for å velge ditt '
           'eget passord. Lenken er gyldig i 7 dager.</p>' if password_url else '')
        + '<p style="margin:0 0 12px;">Kontoen står nå som <em>venter '
          'godkjenning</em>. Du kan logge inn og se deg om med en gang, men '
          'bestillinger kan ikke sendes før vi har godkjent kontoen.</p>'
        + '<p style="margin:0; color:#C9A35B;">Du får en e-post så snart den er klar.</p>'
    )

    html = render_layout(
        eyebrow='◈ Registrering mottatt',
        heading=f'Hei, {first}!',
        intro_html=intro_html,
        cta_url=password_url or _portal_url(),
        cta_label='Opprett passord' if password_url else 'Åpne portalen',
    )
    return send(to=user.email, subject=subject, text_body=text,
                html_body=html, label='horeca_registration_received')


def send_horeca_company_approved_email(user, company) -> bool:
    """K-59 — the company may now order."""
    first = _first_name(user)
    subject = f'{company.name} er godkjent'

    text = (
        f'Hei, {first}!\n\n'
        f'{company.name} er nå godkjent som HORECA-kunde hos Sjoko Loco.\n\n'
        'Dere kan logge inn og legge inn bestillinger med en gang.\n\n'
        f'Portalen: {_portal_url()}\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Godkjent',
        heading=f'{company.name} er godkjent',
        intro_html=(
            '<p style="margin:0 0 12px;">Dere er nå registrert som '
            'HORECA-kunde hos Sjoko Loco, og kan legge inn bestillinger med '
            'en gang.</p>'
            '<p style="margin:0; color:#C9A35B;">Velkommen som kunde.</p>'
        ),
        cta_url=_portal_url(),
        cta_label='Legg inn bestilling',
    )
    return send(to=user.email, subject=subject, text_body=text,
                html_body=html, label='horeca_company_approved')


def send_horeca_company_rejected_email(user, company, reason: str = '') -> bool:
    """K-59 — declined, and the reason travels with it."""
    first = _first_name(user)
    subject = f'Registreringen for {company.name}'

    reason_text = f'\nBegrunnelse: {reason}\n' if reason else ''
    text = (
        f'Hei, {first}!\n\n'
        f'Vi kan dessverre ikke godkjenne registreringen for {company.name} nå.\n'
        f'{reason_text}\n'
        'Tror du dette er en feil, er det bare å svare på denne e-posten.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )

    blocks = render_kv_block('Begrunnelse', [('', reason)]) if reason else ''
    html = render_layout(
        eyebrow='◈ Registrering',
        heading='Vi kan ikke godkjenne denne nå',
        intro_html=(
            f'<p style="margin:0 0 12px;">Vi kan dessverre ikke godkjenne '
            f'registreringen for <strong>{company.name}</strong> nå.</p>'
            '<p style="margin:0;">Tror du dette er en feil, er det bare å svare '
            'på denne e-posten.</p>'
        ),
        blocks_html=blocks,
    )
    return send(to=user.email, subject=subject, text_body=text,
                html_body=html, label='horeca_company_rejected')


def send_admin_new_horeca_company_email(company) -> bool:
    """K-57 — internal heads-up that someone is waiting to be approved."""
    recipients = _ops_recipients()
    if not recipients:
        return False

    admin_url = f"{(settings.ADMIN_URL or '').rstrip('/')}/horeca/bedrifter"
    text = (
        'Ny HORECA-bedrift venter på godkjenning.\n\n'
        f'Bedrift: {company.name}\n'
        f'Org.nr: {company.org_number}\n'
        f'E-post: {company.email}\n'
        f'Telefon: {company.phone}\n\n'
        f'Godkjenn her: {admin_url}\n'
    )
    html = render_layout(
        eyebrow='◈ Ny bedrift',
        heading='Venter på godkjenning',
        intro_html='<p style="margin:0 0 12px;">En ny HORECA-bedrift har registrert seg.</p>',
        blocks_html=render_kv_block('Bedrift', [
            ('Navn', company.name),
            ('Org.nr', company.org_number),
            ('E-post', company.email),
            ('Telefon', company.phone),
        ]),
        cta_url=admin_url,
        cta_label='Åpne i admin',
    )
    return send(to=recipients, subject=f'Ny HORECA-bedrift: {company.name}',
                text_body=text, html_body=html, label='horeca_admin_new_company')


# ── Logo review (K-28, K-29, K-57) ──────────────────────────────────────────

def _ops_recipients() -> list[str]:
    """HORECA ops alerts, separate from ADMIN_NOTIFY_EMAILS.

    That list also receives every consumer order e-mail, so putting B2B alerts
    on it would silently CC whoever watches HORECA on the whole shop. Defaults
    to it, so nothing changes until HORECA_NOTIFY_EMAILS is set.
    """
    raw = getattr(settings, 'HORECA_NOTIFY_EMAILS', None) or settings.ADMIN_NOTIFY_EMAILS
    return [r.strip() for r in (raw or []) if r.strip()]


def send_horeca_logo_received_email(user, logo) -> bool:
    text = (
        f'Hei, {_first_name(user)}!\n\n'
        f'Vi har mottatt logoen "{logo.name}" og ser på den så snart vi kan.\n\n'
        'Du kan legge inn bestillinger i mellomtiden — produksjonen starter '
        'først når logoen er godkjent.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Logo mottatt',
        heading='Vi har fått logoen',
        intro_html=(
            f'<p style="margin:0 0 12px;">Vi har mottatt <strong>{logo.name}</strong> '
            'og ser på den så snart vi kan.</p>'
            '<p style="margin:0;">Du kan legge inn bestillinger i mellomtiden — '
            'produksjonen starter først når logoen er godkjent.</p>'
        ),
        cta_url=f'{_portal_url()}/logoer',
        cta_label='Se logoene mine',
    )
    return send(to=user.email, subject='Vi har mottatt logoen deres',
                text_body=text, html_body=html, label='horeca_logo_received')


def send_admin_new_horeca_logo_email(logo) -> bool:
    recipients = _ops_recipients()
    if not recipients:
        return False
    admin_url = f"{(settings.ADMIN_URL or '').rstrip('/')}/horeca/logoer"
    dims = (f'{logo.width_px}×{logo.height_px} px' if logo.width_px
            else f'vektor ({logo.detected_format.upper()})')
    text = (
        'Ny logo venter på godkjenning.\n\n'
        f'Bedrift: {logo.company.name}\n'
        f'Logo: {logo.name}\n'
        f'Format: {dims}\n\n'
        f'Godkjenn her: {admin_url}\n'
    )
    html = render_layout(
        eyebrow='◈ Ny logo',
        heading='Venter på godkjenning',
        intro_html='<p style="margin:0 0 12px;">En kunde har lastet opp en ny logo.</p>',
        blocks_html=render_kv_block('Logo', [
            ('Bedrift', logo.company.name),
            ('Navn', logo.name),
            ('Format', dims),
            ('Filstørrelse', f'{logo.byte_size / 1024 / 1024:.1f} MB'),
        ]),
        cta_url=admin_url,
        cta_label='Åpne i admin',
    )
    return send(to=recipients, subject=f'Ny HORECA-logo: {logo.company.name}',
                text_body=text, html_body=html, label='horeca_admin_new_logo')


def send_horeca_logo_approved_email(user, logo) -> bool:
    text = (
        f'Hei, {_first_name(user)}!\n\n'
        f'Logoen "{logo.name}" er godkjent og kan brukes på bestillinger.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Godkjent',
        heading=f'"{logo.name}" er godkjent',
        intro_html='<p style="margin:0;">Logoen kan nå brukes på bestillinger.</p>',
        cta_url=f'{_portal_url()}/bestill',
        cta_label='Legg inn bestilling',
    )
    return send(to=user.email, subject=f'Logoen "{logo.name}" er godkjent',
                text_body=text, html_body=html, label='horeca_logo_approved')


def send_horeca_logo_rejected_email(user, logo, reason: str = '') -> bool:
    """K-29 — a rejection without a reason is useless, so the reason travels."""
    text = (
        f'Hei, {_first_name(user)}!\n\n'
        f'Vi kan dessverre ikke bruke logoen "{logo.name}" slik den er nå.\n\n'
        f'Begrunnelse: {reason}\n\n'
        'Last gjerne opp en ny versjon i portalen.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Logo',
        heading='Vi trenger en annen versjon',
        intro_html=(
            f'<p style="margin:0 0 12px;">Vi kan dessverre ikke bruke '
            f'<strong>{logo.name}</strong> slik den er nå.</p>'
        ),
        blocks_html=render_kv_block('Begrunnelse', [('', reason)]) if reason else '',
        cta_url=f'{_portal_url()}/logoer',
        cta_label='Last opp ny versjon',
    )
    return send(to=user.email, subject=f'Logoen "{logo.name}" må endres',
                text_body=text, html_body=html, label='horeca_logo_rejected')


# ── Orders (K-23, K-49, K-57) ───────────────────────────────────────────────

def _order_rows(order):
    return [
        (f'{line.tray_count} × {line.product_name}'
         + (f' (logo: {line.logo_name})' if line.with_logo else ''),
         f'{line.piece_count} biter',
         f'kr {line.line_total_ex_vat:.0f}')
        for line in order.lines.all()
    ]


def _delivery_block(order):
    return render_kv_block('Levering', [
        ('Dato', order.delivery_date.strftime('%d.%m.%Y') if order.delivery_date else '—'),
        ('Tidsvindu', order.delivery_window_label or order.delivery_window or '—'),
        ('Adresse', f'{order.delivery_street}, {order.delivery_postal_code} {order.delivery_city}'),
        ('Kontakt', f'{order.delivery_contact_name} · {order.delivery_contact_phone}'.strip(' ·')),
    ])


def send_horeca_order_received_email(order) -> bool:
    """K-23 — order number, contents, sum, address and time window."""
    to = order.placed_by_email or order.company.email
    if not to:
        return False
    lines = '\n'.join(
        f'  {line.tray_count} × {line.product_name} — {line.piece_count} biter'
        for line in order.lines.all()
    )
    date = order.delivery_date.strftime('%d.%m.%Y') if order.delivery_date else '—'
    text = (
        f'Takk for bestillingen!\n\n'
        f'Ordrenummer: {order.order_number}\n\n'
        f'{lines}\n\n'
        f'Sum eks. mva: kr {order.subtotal_ex_vat:.0f}\n'
        f'Levering: {date}, {order.delivery_window_label}\n'
        f'{order.delivery_street}, {order.delivery_postal_code} {order.delivery_city}\n\n'
        'Bestillingen faktureres som vanlig — ingen betaling i portalen.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow=f'◈ {order.order_number}',
        heading='Bestillingen er mottatt',
        intro_html='<p style="margin:0;">Takk! Vi har mottatt bestillingen og '
                   'bekrefter den så snart vi har sjekket dato og antall.</p>',
        blocks_html=(
            render_items_table(
                _order_rows(order),
                [('Sum eks. mva', f'kr {order.subtotal_ex_vat:.0f}'),
                 ('Mva', f'kr {order.vat_amount:.0f}'),
                 ('Totalt', f'kr {order.total_inc_vat:.0f}')],
            )
            + _delivery_block(order)
        ),
        cta_url=f'{_portal_url()}/bestillinger/{order.order_number}',
        cta_label='Se bestillingen',
        footer_lines=['Faktureres som vanlig — ingen betaling i portalen.'],
    )
    return send(to=to, subject=f'Bestilling {order.order_number} er mottatt',
                text_body=text, html_body=html, label='horeca_order_received')


def send_admin_new_horeca_order_email(order) -> bool:
    recipients = _ops_recipients()
    if not recipients:
        return False
    admin_url = f"{(settings.ADMIN_URL or '').rstrip('/')}/horeca/ordrer/{order.order_number}"
    date = order.delivery_date.strftime('%d.%m.%Y') if order.delivery_date else '—'
    text = (
        f'Ny HORECA-bestilling {order.order_number}\n\n'
        f'Bedrift: {order.company_name}\n'
        f'Levering: {date}, {order.delivery_window_label}\n'
        f'Brett: {order.tray_count}\n'
        f'Sum eks. mva: kr {order.subtotal_ex_vat:.0f}\n\n'
        f'{admin_url}\n'
    )
    html = render_layout(
        eyebrow='◈ Ny bestilling',
        heading=order.order_number,
        intro_html=f'<p style="margin:0 0 12px;">Ny bestilling fra '
                   f'<strong>{order.company_name}</strong>.</p>',
        blocks_html=(
            render_kv_block('Oppsummering', [
                ('Brett', str(order.tray_count)),
                ('Levering', f'{date} · {order.delivery_window_label}'),
                ('Sum eks. mva', f'kr {order.subtotal_ex_vat:.0f}'),
            ])
            + _delivery_block(order)
        ),
        cta_url=admin_url,
        cta_label='Åpne i admin',
    )
    return send(to=recipients, subject=f'Ny HORECA-bestilling {order.order_number}',
                text_body=text, html_body=html, label='horeca_admin_new_order')


# K-49 — one mail per real status change. Internal states send nothing, the
# same reasoning apps/orders/admin_views.py already applies to Pakkes.
_STATUS_COPY = {
    'bekreftet': ('Bestillingen er bekreftet',
                  'Vi har sjekket dato og antall, og bestillingen er bekreftet.'),
    'klar': ('Bestillingen er klar',
             'Bestillingen er ferdig produsert og klar til levering.'),
    'levert': ('Bestillingen er levert',
               'Bestillingen er levert. Takk for handelen!'),
}


def send_horeca_order_status_email(order) -> bool:
    copy = _STATUS_COPY.get(order.status)
    if copy is None:
        return False
    subject_tail, body = copy
    to = order.placed_by_email or order.company.email
    if not to:
        return False
    date = order.delivery_date.strftime('%d.%m.%Y') if order.delivery_date else '—'
    text = (
        f'{body}\n\n'
        f'Ordrenummer: {order.order_number}\n'
        f'Levering: {date}, {order.delivery_window_label}\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow=f'◈ {order.order_number}',
        heading=subject_tail,
        intro_html=f'<p style="margin:0;">{body}</p>',
        blocks_html=render_status_box('Status', order.get_status_display())
                    + _delivery_block(order),
        cta_url=f'{_portal_url()}/bestillinger/{order.order_number}',
        cta_label='Se bestillingen',
    )
    return send(to=to, subject=f'{order.order_number}: {subject_tail.lower()}',
                text_body=text, html_body=html, label='horeca_order_status')


def send_horeca_order_cancelled_email(order) -> bool:
    to = order.placed_by_email or order.company.email
    if not to:
        return False
    reason = f'\nBegrunnelse: {order.cancellation_reason}\n' if order.cancellation_reason else ''
    text = (
        f'Bestilling {order.order_number} er avbestilt.\n{reason}\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow=f'◈ {order.order_number}',
        heading='Bestillingen er avbestilt',
        intro_html='<p style="margin:0;">Bestillingen er avbestilt og blir ikke produsert.</p>',
        blocks_html=(render_kv_block('Begrunnelse', [('', order.cancellation_reason)])
                     if order.cancellation_reason else ''),
    )
    return send(to=to, subject=f'{order.order_number} er avbestilt',
                text_body=text, html_body=html, label='horeca_order_cancelled')


def send_horeca_invite_email(user, company, inviter_name='', password_url=None) -> bool:
    """K-8 — a colleague has been given access to the company's portal.

    Uses the ordinary 7-day welcome link, not the 60-minute reset one: an
    invitation is a welcome, and somebody who opens their mail the next morning
    should not find it already dead.
    """
    first = _first_name(user)
    by = f' av {inviter_name}' if inviter_name else ''
    password_text = (
        f'Velg ditt eget passord her:\n{password_url}\n\nLenken er gyldig i 7 dager.\n\n'
    ) if password_url else ''

    text = (
        f'Hei, {first}!\n\n'
        f'Du er invitert{by} til å bestille på vegne av {company.name} '
        'i Sjoko Locos bedriftsportal.\n\n'
        f'{password_text}'
        f'Portalen: {_portal_url()}\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Invitasjon',
        heading=f'Velkommen til {company.name}s portal',
        intro_html=(
            f'<p style="margin:0 0 12px;">Du er invitert{by} til å bestille på '
            f'vegne av <strong>{company.name}</strong>.</p>'
            + ('<p style="margin:0;">Trykk på knappen under for å velge ditt '
               'eget passord. Lenken er gyldig i 7 dager.</p>'
               if password_url else
               '<p style="margin:0;">Logg inn med passordet du har fra før.</p>')
        ),
        cta_url=password_url or _portal_url(),
        cta_label='Opprett passord' if password_url else 'Åpne portalen',
    )
    return send(to=user.email, subject=f'Invitasjon til {company.name}',
                text_body=text, html_body=html, label='horeca_invite')


def send_horeca_password_reset_email(user, reset_url, minutes: int = 60) -> bool:
    """K-7. The lifetime is derived, never hardcoded — the consumer templates
    have "7 dager" written into four places and that is the mistake not to
    repeat here."""
    first = _first_name(user)
    text = (
        f'Hei, {first}!\n\n'
        'Du har bedt om å tilbakestille passordet til bedriftsportalen.\n\n'
        f'{reset_url}\n\n'
        f'Lenken er gyldig i {minutes} minutter. Har du ikke bedt om dette, '
        'kan du se bort fra denne e-posten.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow='◈ Nytt passord',
        heading='Tilbakestill passordet',
        intro_html=(
            '<p style="margin:0 0 12px;">Trykk på knappen under for å velge et '
            f'nytt passord. Lenken er gyldig i <strong>{minutes} minutter</strong>.</p>'
            '<p style="margin:0; color:#C9A35B;">Har du ikke bedt om dette, kan '
            'du se bort fra e-posten.</p>'
        ),
        cta_url=reset_url,
        cta_label='Velg nytt passord',
    )
    return send(to=user.email, subject='Nytt passord til bedriftsportalen',
                text_body=text, html_body=html, label='horeca_password_reset')


def send_horeca_order_changed_email(order) -> bool:
    """K-56 — we moved something on an order the customer already has."""
    to = order.placed_by_email or order.company.email
    if not to:
        return False
    date = order.delivery_date.strftime('%d.%m.%Y') if order.delivery_date else '—'
    text = (
        f'Bestilling {order.order_number} er oppdatert.\n\n'
        f'Ny levering: {date}, {order.delivery_window_label}\n'
        f'{order.delivery_street}, {order.delivery_postal_code} {order.delivery_city}\n\n'
        'Stemmer ikke dette, ta kontakt med oss.\n\n'
        'Hilsen\nTeam Sjoko Loco'
    )
    html = render_layout(
        eyebrow=f'◈ {order.order_number}',
        heading='Bestillingen er oppdatert',
        intro_html='<p style="margin:0;">Vi har endret leveringen på denne '
                   'bestillingen. Stemmer ikke dette, ta kontakt med oss.</p>',
        blocks_html=_delivery_block(order),
        cta_url=f'{_portal_url()}/bestillinger/{order.order_number}',
        cta_label='Se bestillingen',
    )
    return send(to=to, subject=f'{order.order_number} er oppdatert',
                text_body=text, html_body=html, label='horeca_order_changed')
