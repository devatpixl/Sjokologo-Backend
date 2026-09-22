"""Alert by e-mail if the WhatsApp link dies.

The WhatsApp ping to the shop owner is a *second* channel: every paid order
also sends ``send_admin_new_order_email``. So a dead session degrades the
alerting, it never silences it. Saying otherwise — as an earlier version of
this script did — turns a minor outage into a Sunday-night escalation.

Deliberately e-mail and not WhatsApp: the thing being reported broken *is*
WhatsApp, so alerting over it would be useless.

This does NOT guess at a cause. WhatsApp's server can drop a linked device for
several reasons that look identical from here (the phone re-installed WhatsApp,
someone logged the device out, the 4-device limit evicted the oldest, or
WhatsApp purged an unofficial client), and the previous version asserted the
one cause that turned out not to fit — a session six days old was reported as
"offline for more than 14 days". It now reports the status, says the cause is
in the container log, and gives the command that shows it.

Only mails on a change of state, so a long outage does not send a message every
15 minutes. Every transition is also printed, and cron appends stdout to
/var/log/sjokoloko/whatsapp_health.log — that file is the only record of how
often this happens, which is what decides whether the link needs replacing
rather than re-pairing. State lives in /tmp and simply re-alerts after a reboot.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from django.core.mail import send_mail

from apps.whatsapp.client import session_status

STATE = Path("/tmp/whatsapp_session_state")

# The number whose WhatsApp account the server is linked to as a device. Its
# display name is "Sjoko Loco", i.e. the shop's own account — not the owner's
# personal phone, which is the *recipient* of the alerts and is never involved
# in re-pairing.
LINKED_NUMBER = "4791905734"

# Reading the container log is what identifies the cause; nothing else does.
DIAGNOSE_CMD = (
    'docker logs waha-sjokoloko 2>&1 | grep -iE '
    '"stream errored|device_removed|logged.?out" | tail -5'
)

# Verified against the routes this WAHA build (2026.7.2, NOWEB) maps at boot.
REPAIR_STEPS = f"""\
1) Pixl, paa serveren – be om en koblingskode:
     K=$(grep -hoP '^WAHA_API_KEY=\\K.*' /srv/sjokoloko/api/.env)
     curl -s -X POST -H "X-Api-Key: $K" \\
       http://127.0.0.1:3004/api/sessions/sjokoloko/logout
     curl -s -X POST -H "X-Api-Key: $K" \\
       http://127.0.0.1:3004/api/sessions/sjokoloko/start
     curl -s -X POST -H "X-Api-Key: $K" -H 'Content-Type: application/json' \\
       -d '{{"phoneNumber":"{LINKED_NUMBER}"}}' \\
       http://127.0.0.1:3004/api/sjokoloko/auth/request-code

2) Paa telefonen +47 {LINKED_NUMBER[2:4]} {LINKED_NUMBER[4:6]} {LINKED_NUMBER[6:8]} {LINKED_NUMBER[8:]}:
   WhatsApp > Innstillinger > Tilkoblede enheter > Koble til en enhet >
   "Koble til med telefonnummer i stedet" > skriv inn koden.
   Koden varer i ca. 60 sekunder, saa noen maa staa klar med telefonen.

3) Bekreft:
     curl -s -H "X-Api-Key: $K" \\
       http://127.0.0.1:3004/api/sessions/sjokoloko | grep -o '"status":"[A-Z_]*"'
   Skal vise WORKING."""


def _log(line: str) -> None:
    """One timestamped line to stdout; cron appends it to the health log."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"{stamp} {line}", flush=True)


def _recipients() -> list[str]:
    """Who hears about an outage.

    Separate from ADMIN_NOTIFY_EMAILS on purpose: that list also receives every
    customer order e-mail (apps/emails/orders.py), so adding a developer there
    to get outage alerts would silently CC them on the shop's order flow.
    Defaults to ADMIN_NOTIFY_EMAILS, so behaviour is unchanged until
    WHATSAPP_ALERT_EMAILS is actually set.
    """
    configured = getattr(settings, "WHATSAPP_ALERT_EMAILS", None) or []
    if not configured:
        configured = settings.ADMIN_NOTIFY_EMAILS or []
    return [r.strip() for r in configured if r.strip()]


def _body(status: str) -> str:
    """The message for a non-WORKING status, written to be acted on."""
    unaffected = (
        "E-postvarsel om nye ordrer gaar som normalt. Butikkeier faar fortsatt "
        "hver betalte ordre paa e-post — det er kun WhatsApp-pinget som mangler.\n\n"
    )

    if status == "FAILED":
        return (
            f"WhatsApp-varselet for nye ordrer er nede. Status: {status}.\n\n"
            + unaffected
            + "WhatsApp har fjernet koblingen til serveren. Aarsaken staar i "
            "loggen — den kan vaere at WhatsApp er reinstallert paa telefonen, "
            "at noen har logget ut enheten under Tilkoblede enheter, eller at "
            "grensen paa 4 tilkoblede enheter har kastet ut den eldste.\n\n"
            f"Se aarsak:\n  {DIAGNOSE_CMD}\n\n"
            "Fiks — koble til paa nytt:\n"
            f"{REPAIR_STEPS}\n"
        )

    if status == "UNREACHABLE":
        return (
            f"WhatsApp-varselet svarer ikke. Status: {status}.\n\n"
            + unaffected
            + "Dette er WAHA-tjenesten paa serveren, ikke telefonen. Ingen "
            "telefon og ingen ny kobling trengs.\n\n"
            "Fiks:\n  docker restart waha-sjokoloko\n"
        )

    return (
        f"WhatsApp-varselet er ikke i normal drift. Status: {status}.\n\n"
        + unaffected
        + "Dette er vanligvis en midlertidig tilstand under oppkobling. "
        "Trenger ingen handling med mindre den staar slik i mer enn en time.\n"
    )


def main() -> int:
    status = session_status() or "UNREACHABLE"
    previous = STATE.read_text().strip() if STATE.exists() else ""
    STATE.write_text(status)

    if status == previous:
        return 0  # nothing changed, stay quiet

    _log(f"state change: {previous or '(none)'} -> {status}")

    recipients = _recipients()
    if not recipients:
        _log("no recipients configured, no mail sent")
        return 0

    if status == "WORKING":
        if not previous:
            return 0  # first ever run, nothing to report
        subject = "Sjokoloco WhatsApp: tilkoblingen er tilbake"
        body = "WhatsApp-varslingen fungerer igjen (status WORKING)."
    else:
        subject = f"Sjokoloco WhatsApp NEDE (status: {status})"
        body = _body(status)

    # Not fail_silently: a swallowed SMTP error means nobody is told and no
    # trace is left, which is the same failure this script exists to prevent.
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)
        _log(f"alert mailed to {len(recipients)} recipient(s)")
    except Exception as exc:  # noqa: BLE001 — cron job, must never traceback
        _log(f"alert mail FAILED: {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
