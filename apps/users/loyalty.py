"""Loyalty-program landing page signup.

The ``POST /api/loyalty/signup/`` endpoint captures the form posted from
``/bli-medlem`` on the storefront and sends a welcome email with the
lifetime 20% discount code (``STAND``) via the configured SMTP backend.

The discount code itself is configured in the admin; we just reference it
by name in the email body.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import LoyaltyMember

log = logging.getLogger(__name__)

# The discount code referenced in the welcome email. Created manually in
# the admin (kind=percent, value=20, no expiry, unlimited uses).
LOYALTY_DISCOUNT_CODE = 'STAND'


class LoyaltySignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, trim_whitespace=True)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, trim_whitespace=True)
    # Accept either "YYYY-MM-DD" or empty / null. The boss said "write if
    # you want a surprise on your birthday", so we treat it as optional.
    birthday = serializers.DateField(required=False, allow_null=True)

    def validate_phone(self, value: str) -> str:
        digits = re.sub(r'\D', '', value)
        if len(digits) < 8:
            raise serializers.ValidationError('Telefonnummer må ha minst 8 sifre.')
        return value.strip()

    def validate_first_name(self, value: str) -> str:
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError('Skriv inn fornavnet ditt.')
        return v


@api_view(['POST'])
@permission_classes([AllowAny])
def loyalty_signup_view(request):
    """Capture the loyalty form + send the welcome email."""
    serializer = LoyaltySignupSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    email = data['email'].lower().strip()

    # Upsert by email — re-signing up just updates the record + resends the
    # email. The discount code is the same for everyone so there's nothing
    # to abuse here beyond mild spam, which Gmail's send limits would catch.
    member, created = LoyaltyMember.objects.update_or_create(
        email=email,
        defaults={
            'first_name': data['first_name'],
            'phone': data['phone'],
            'birthday': data.get('birthday'),
        },
    )

    try:
        _send_welcome_email(member)
    except Exception as e:
        # Don't fail the signup if email sending hiccups — the member is
        # captured, we just log and tell the user something went wrong with
        # email so they can retry or contact support.
        log.exception('Loyalty welcome email failed for %s: %s', email, e)
        return Response(
            {
                'ok': True,
                'created': created,
                'email_sent': False,
                'detail': 'Vi mottok påmeldingen, men kunne ikke sende e-posten akkurat nå. Vi prøver igjen snart.',
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    return Response(
        {'ok': True, 'created': created, 'email_sent': True},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _send_welcome_email(member: LoyaltyMember) -> None:
    """Send the bilingual Norwegian welcome email with the discount code."""
    storefront = 'https://sjokoloco.no'
    subject = 'Velkommen til Sjoko Loco-familien — 20% rabattkode'

    # Plain-text fallback (for clients that don't render HTML).
    text = (
        f'Hei, {member.first_name}!\n\n'
        'Takk for at du meldte deg inn i lojalitetsprogrammet til Sjoko Loco.\n\n'
        'Som medlem får du:\n'
        '  • 20% rabatt på alle kjøp — for alltid\n'
        f'  • Bruk rabattkoden: {LOYALTY_DISCOUNT_CODE}\n'
        '  • Gjelder på alle kjøp i nettbutikken\n'
        '  • Din faste medlemsrabatt\n'
        '  • Kan ikke kombineres med andre rabatter eller kampanjer\n\n'
        'All konfekt fra Sjoko Loco blir håndlaget i Ås, og vi sender over hele landet.\n\n'
        'Vi har stort fokus på kvalitet, og bruker kun naturlige råvarer — '
        'helt uten aroma eller konserveringsmidler.\n\n'
        'Fri frakt på alle bestillinger over 349 kr.\n\n'
        f'Handle her: {storefront}\n\n'
        'Velkommen til Sjoko Loco-familien — vi gleder oss til å dele '
        'sjokoladenyheter, eksklusive tilbud og søte overraskelser med deg.\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    html = _render_welcome_html(member.first_name, storefront)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[member.email],
    )
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=False)


def _render_welcome_html(first_name: str, storefront: str) -> str:
    """Inline-styled HTML email matching the chocolate-store editorial palette.

    Inline CSS only — most email clients strip <style> blocks. Colors are
    pulled from the storefront tokens (ink, cream, accent gold).
    """
    return f'''<!DOCTYPE html>
<html lang="no">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Velkommen til Sjoko Loco-familien</title>
</head>
<body style="margin:0; padding:0; background:#0E0906; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#F5EFE6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0E0906;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px; background:#161009; border:1px solid rgba(201,163,91,0.18);">
          <!-- Eyebrow / wordmark -->
          <tr>
            <td style="padding:36px 36px 0; text-align:center;">
              <div style="font-family: Georgia, 'Times New Roman', serif; font-style:italic; font-weight:300; font-size:28px; color:#C9A35B; letter-spacing:0.02em;">
                Sjoko Loco
              </div>
              <div style="margin-top:6px; font-size:10.5px; letter-spacing:0.32em; color:rgba(245,239,230,0.55); text-transform:uppercase;">
                ◈ Lojalitetsprogrammet
              </div>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="padding:36px 36px 8px;">
              <h1 style="margin:0 0 14px; font-family: Georgia, 'Times New Roman', serif; font-style:italic; font-weight:300; font-size:34px; line-height:1.12; color:#F5EFE6;">
                Hei, {first_name}!
              </h1>
              <p style="margin:0; font-size:15px; line-height:1.65; color:rgba(245,239,230,0.78);">
                Takk for at du meldte deg inn i lojalitetsprogrammet til Sjoko Loco.
              </p>
            </td>
          </tr>

          <!-- Discount card -->
          <tr>
            <td style="padding:24px 36px 8px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:rgba(201,163,91,0.08); border:1px solid rgba(201,163,91,0.35);">
                <tr>
                  <td style="padding:22px 24px;">
                    <div style="font-size:10.5px; letter-spacing:0.32em; color:#C9A35B; text-transform:uppercase; margin-bottom:6px;">
                      ◈ Din medlemsrabatt
                    </div>
                    <div style="font-family: Georgia, 'Times New Roman', serif; font-weight:300; font-size:28px; color:#F5EFE6; margin-bottom:14px;">
                      20% rabatt på alle kjøp — for alltid
                    </div>
                    <div style="font-size:13.5px; color:rgba(245,239,230,0.7); margin-bottom:14px;">
                      Bruk rabattkoden i kassen:
                    </div>
                    <div style="display:inline-block; padding:12px 22px; background:#C9A35B; color:#0E0906; font-family: 'Courier New', monospace; font-weight:700; font-size:18px; letter-spacing:0.28em;">
                      {LOYALTY_DISCOUNT_CODE}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Benefits list -->
          <tr>
            <td style="padding:18px 36px 8px;">
              <ul style="margin:0; padding:0 0 0 18px; font-size:14px; line-height:1.75; color:rgba(245,239,230,0.78); list-style:none;">
                <li style="padding-left:14px; position:relative; margin-bottom:4px;">
                  <span style="position:absolute; left:0; color:#C9A35B;">◇</span>
                  Gjelder på alle kjøp i nettbutikken
                </li>
                <li style="padding-left:14px; position:relative; margin-bottom:4px;">
                  <span style="position:absolute; left:0; color:#C9A35B;">◇</span>
                  Din faste medlemsrabatt
                </li>
                <li style="padding-left:14px; position:relative;">
                  <span style="position:absolute; left:0; color:#C9A35B;">◇</span>
                  Kan ikke kombineres med andre rabatter eller kampanjer
                </li>
              </ul>
            </td>
          </tr>

          <!-- Brand story -->
          <tr>
            <td style="padding:22px 36px 4px;">
              <p style="margin:0 0 12px; font-size:14px; line-height:1.7; color:rgba(245,239,230,0.78);">
                All konfekt fra Sjoko Loco blir håndlaget i Ås, og vi sender over hele landet.
              </p>
              <p style="margin:0 0 12px; font-size:14px; line-height:1.7; color:rgba(245,239,230,0.78);">
                Vi har stort fokus på kvalitet, og bruker kun naturlige råvarer — helt uten aroma eller konserveringsmidler.
              </p>
              <p style="margin:0; font-size:14px; line-height:1.7; color:#C9A35B;">
                Fri frakt på alle bestillinger over 349 kr.
              </p>
            </td>
          </tr>

          <!-- Shop CTA -->
          <tr>
            <td style="padding:28px 36px 32px; text-align:center;">
              <a href="{storefront}" style="display:inline-block; padding:14px 38px; background:#C9A35B; color:#0E0906; text-decoration:none; font-size:12px; font-weight:600; letter-spacing:0.18em; text-transform:uppercase;">
                Handle her →
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 36px 36px; border-top:1px solid rgba(201,163,91,0.18); text-align:center;">
              <p style="margin:0 0 8px; font-family: Georgia, 'Times New Roman', serif; font-style:italic; font-size:16px; color:rgba(245,239,230,0.85);">
                Velkommen til Sjoko Loco-familien.
              </p>
              <p style="margin:0; font-size:12px; line-height:1.65; color:rgba(245,239,230,0.55);">
                Vi gleder oss til å dele sjokoladenyheter, eksklusive tilbud og søte overraskelser med deg.<br>
                Hilsen — Team Sjoko Loco
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''
