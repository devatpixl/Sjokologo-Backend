"""WhatsApp ops alerts — public API.

Call sites should import from here rather than reaching into ``client`` or
``notifications`` directly, mirroring how ``apps.emails`` is used.
"""

from .notifications import build_new_order_message, notify_admin_new_order

__all__ = ['notify_admin_new_order', 'build_new_order_message']
