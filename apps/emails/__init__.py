"""Transactional email — public API.

All call sites should import the small wrappers below rather than touching
``transactional.send()`` or template helpers directly.
"""

from .signup import send_welcome_email, send_admin_new_signup_email, send_password_reset_email
from .orders import (
    send_order_confirmation_email,
    send_order_confirmed_email,
    send_admin_new_order_email,
    send_order_packing_email,
    send_order_shipped_email,
    send_order_ready_for_pickup_email,
    send_order_delivered_email,
)
from .horeca import (
    send_horeca_registration_received_email,
    send_horeca_logo_received_email,
    send_horeca_logo_approved_email,
    send_horeca_logo_rejected_email,
    send_admin_new_horeca_logo_email,
    send_horeca_order_received_email,
    send_admin_new_horeca_order_email,
    send_horeca_order_status_email,
    send_horeca_order_cancelled_email,
    send_horeca_company_approved_email,
    send_horeca_company_rejected_email,
    send_admin_new_horeca_company_email,
    send_horeca_invite_email,
    send_horeca_password_reset_email,
    send_horeca_order_changed_email,
)

__all__ = [
    'send_welcome_email',
    'send_password_reset_email',
    'send_admin_new_signup_email',
    'send_order_confirmation_email',
    'send_order_confirmed_email',
    'send_admin_new_order_email',
    'send_order_packing_email',
    'send_order_shipped_email',
    'send_order_ready_for_pickup_email',
    'send_order_delivered_email',
    'send_horeca_registration_received_email',
    'send_horeca_company_approved_email',
    'send_horeca_company_rejected_email',
    'send_admin_new_horeca_company_email',
    'send_horeca_logo_received_email',
    'send_horeca_logo_approved_email',
    'send_horeca_logo_rejected_email',
    'send_admin_new_horeca_logo_email',
    'send_horeca_order_received_email',
    'send_admin_new_horeca_order_email',
    'send_horeca_order_status_email',
    'send_horeca_order_cancelled_email',
    'send_horeca_invite_email',
    'send_horeca_password_reset_email',
    'send_horeca_order_changed_email',
]
