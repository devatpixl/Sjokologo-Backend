"""Alert by e-mail if the WhatsApp link dies.

WhatsApp silently kills a linked device when its phone stays offline for ~14
days. The only symptom is that order alerts stop arriving, which nobody
notices until an order is missed. This runs from cron and mails the ops
addresses the moment the session stops being WORKING.

Deliberately e-mail and not WhatsApp: the thing being reported broken *is*
WhatsApp, so alerting over it would be useless.

Only mails on a change of state, so a long outage does not send a message
every 15 minutes. State lives in /tmp and simply re-alerts after a reboot.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from django.core.mail import send_mail

from apps.whatsapp.client import session_status

STATE = Path("/tmp/whatsapp_session_state")


def main() -> int:
    status = session_status() or "UNREACHABLE"
    previous = STATE.read_text().strip() if STATE.exists() else ""
    STATE.write_text(status)

    if status == previous:
        return 0  # nothing changed, stay quiet

    recipients = [r.strip() for r in (settings.ADMIN_NOTIFY_EMAILS or []) if r.strip()]
    if not recipients:
        return 0

    if status == "WORKING":
        if previous:  # recovered from a bad state
            subject = "Sjokoloco WhatsApp: tilkoblingen er tilbake"
            body = "WhatsApp-varslingen fungerer igjen (status WORKING)."
        else:
            return 0  # first ever run, nothing to report
    else:
        subject = f"Sjokoloco WhatsApp NEDE (status: {status})"
        body = (
            f"WhatsApp-varselet for nye ordrer er nede. Status: {status}.\n\n"
            "Ordrevarsler til butikkeier sendes IKKE nå.\n\n"
            "Vanligste årsak: telefonen som eier +47 91 90 57 34 har vaert "
            "offline i mer enn 14 dager, saa WhatsApp har koblet fra enheten.\n\n"
            "Fiks: kjor ~/pair-sjokoloko.sh 4791905734 og koble til paa nytt "
            "(Innstillinger > Tilkoblede enheter > Koble til en enhet)."
        )

    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
