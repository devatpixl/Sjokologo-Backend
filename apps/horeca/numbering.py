"""HORECA order numbers.

Distinct series from the consumer shop (`SL-#####`), for two reasons: a glance
at a number says which business it belongs to, and `'SLB-00001'.startswith('SL-')`
is False, so no existing prefix query can confuse the two.
"""
from django.conf import settings
from django.db import connection


def next_horeca_order_number() -> str:
    """Atomic and lock-free.

    `nextval()` is non-transactional by design, so a rolled-back order burns a
    number and the series has gaps. That is correct for an identifier — it is
    not a count of anything — and is far preferable to the consumer generator's
    read-then-write, which loses a whole order to an IntegrityError when two
    checkouts land together.
    """
    prefix = getattr(settings, 'HORECA_ORDER_PREFIX', 'SLB')
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('horeca_order_number_seq')")
        n = cur.fetchone()[0]
    return f'{prefix}-{n:05d}'
