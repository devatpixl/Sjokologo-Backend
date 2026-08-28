from django.db import migrations, models
from django.db.models import F


def backfill_existing(apps, schema_editor):
    """Every order that already exists was e-mailed at creation time under the
    old behaviour. Stamp them so a redelivered Vipps webhook can never mail
    those customers a second time.
    """
    Order = apps.get_model('orders', 'Order')
    Order.objects.filter(confirmation_emails_sent_at__isnull=True).update(
        confirmation_emails_sent_at=F('created_at'),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0007_order_bundles_applied_order_coupon_code_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="confirmation_emails_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_existing, migrations.RunPython.noop),
    ]
