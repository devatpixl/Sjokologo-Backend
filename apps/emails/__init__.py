"""Transactional email — public API.

All call sites should import the small wrappers below rather than touching
``transactional.send()`` or template helpers directly.
"""

from .signup import send_welcome_email, send_admin_new_signup_email
from .orders import (
    send_order_confirmation_email,
    send_admin_new_order_email,
    send_order_packing_email,
    send_order_shipped_email,
    send_order_delivered_email,
)

__all__ = [
    'send_welcome_email',
    'send_admin_new_signup_email',
    'send_order_confirmation_email',
    'send_admin_new_order_email',
    'send_order_packing_email',
    'send_order_shipped_email',
    'send_order_delivered_email',
]
