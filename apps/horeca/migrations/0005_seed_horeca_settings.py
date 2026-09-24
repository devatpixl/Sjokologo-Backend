"""Seed the singleton settings row.

Without this a fresh database has no HorecaSettings, so the calendar has no
lead times and no capacity and the first request either 500s or silently
invents defaults. Creating it here means a clean checkout works with no manual
step — which is the difference between "clone and run" and a README footnote
everybody misses.
"""
from django.db import migrations


def seed(apps, schema_editor):
    HorecaSettings = apps.get_model('horeca', 'HorecaSettings')
    HorecaSettings.objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    # Deliberately a no-op: dropping operational settings on a reverse
    # migration would lose Terje's capacity and lead-time numbers.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('horeca', '0004_order_number_sequence'),
    ]

    operations = [migrations.RunPython(seed, unseed)]
