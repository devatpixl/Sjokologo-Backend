"""A Postgres sequence for HORECA order numbers.

The consumer generator (apps/orders/models.py) is
`Order.objects.order_by('id').last()` inside save() — a read-then-write with no
lock, so two concurrent checkouts compute the same number and one dies on the
unique index. That is left alone (touching the consumer order path is out of
scope), but it must not be copied.

nextval() is atomic and lock-free. It is also non-transactional, so a
rolled-back order burns a number — gaps are correct for an identifier and this
is documented rather than "fixed".
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('horeca', '0003_catalogue_addresses_logos_orders'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE SEQUENCE IF NOT EXISTS horeca_order_number_seq '
                'START WITH 1 INCREMENT BY 1;',
            reverse_sql='DROP SEQUENCE IF EXISTS horeca_order_number_seq;',
        ),
    ]
