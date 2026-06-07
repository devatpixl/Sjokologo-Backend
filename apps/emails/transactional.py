"""Central transactional-email send helper.

Every outbound transactional email goes through :func:`send`. This is the
single point where the ``EMAIL_TEST_OVERRIDE`` rewrite happens, where
failures are swallowed-and-logged (so a Gmail blip never breaks the user
action that triggered the mail), and where every send is structured-logged
for later auditing.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

log = logging.getLogger(__name__)


def send(
    *,
    to: str | Iterable[str],
    subject: str,
    text_body: str,
    html_body: str,
    label: str,
) -> bool:
    """Send a transactional email. Returns True on success, False on failure.

    ``label`` is a short tag (``'welcome'``, ``'order_confirmation'``, …)
    used purely in logging so we can trace which call site sent what.

    When ``settings.EMAIL_TEST_OVERRIDE`` is set, the message is rewritten
    to that single recipient and the original ``to`` address(es) are
    stamped into the subject so the receiver can tell which email it
    *would* have been in production.
    """
    if isinstance(to, str):
        original_recipients = [to]
    else:
        original_recipients = list(to)

    if not original_recipients:
        log.warning('[%s] no recipients — skipping send', label)
        return False

    override = (settings.EMAIL_TEST_OVERRIDE or '').strip()
    if override:
        effective_to = [override]
        # Make it obvious in the inbox which real customer would have
        # received this in production.
        subject = f'[→ {", ".join(original_recipients)}] {subject}'
    else:
        effective_to = original_recipients

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=effective_to,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
    except Exception as exc:
        log.exception(
            '[%s] email send failed — to=%s effective_to=%s err=%s',
            label,
            original_recipients,
            effective_to,
            exc,
        )
        return False

    log.info(
        '[%s] email sent — to=%s effective_to=%s',
        label,
        original_recipients,
        effective_to,
    )
    return True
