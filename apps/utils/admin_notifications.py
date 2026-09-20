"""The admin panel's notification feed.

One endpoint behind the bell in the top bar. It replaced the per-signup e-mail
to ops, so it has to answer the question that e-mail answered — *who* just
registered — not merely how many.

Cross-domain on purpose: today the only source is new customers, but orders and
contact messages belong here too. Add them to ``_sources()`` and both the bell
and its counter pick them up with no frontend change, which is why every item is
returned in the same shape rather than as a customer-specific payload.

Nothing is stored. The feed is derived from the rows themselves (a customer with
``is_seen=False`` is an unread notification), so there is no second table to keep
in step with the data it describes.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.users.models import CustomUser
from apps.users.permissions import IsAdminUser

# The dropdown shows a window, not the whole history — the count stays truthful
# even when it exceeds this.
MAX_ITEMS = 20


def _new_customer_items(limit):
    qs = (
        CustomUser.objects
        .filter(is_admin=False, user_type='registered', is_seen=False)
        .order_by('-created_at')
    )
    total = qs.count()
    items = [
        {
            'id': f'customer:{u.id}',
            'kind': 'customer',
            'title': 'Ny kunde registrert',
            'subtitle': (u.name or '').strip() or '(uten navn)',
            'meta': u.email,
            'href': f'/customers/{u.id}',
            'created_at': u.created_at.isoformat(),
        }
        for u in qs[:limit]
    ]
    return total, items


def _sources(limit):
    """Every feed source. Extend here, not in the view."""
    return [_new_customer_items(limit)]


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_notifications(request):
    total = 0
    items = []
    for source_total, source_items in _sources(MAX_ITEMS):
        total += source_total
        items.extend(source_items)
    items.sort(key=lambda i: i['created_at'], reverse=True)
    return Response({'count': total, 'items': items[:MAX_ITEMS]})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_notifications_mark_read(request):
    """Dismiss the feed.

    The bell and the Kunder page clear the same underlying flag, so pressing
    either leaves the other consistent. Opening the dropdown does not call this
    — ops asked for notifications that survive a look.
    """
    cleared = CustomUser.objects.filter(
        is_admin=False, user_type='registered', is_seen=False,
    ).update(is_seen=True)
    return Response({'cleared': cleared})
