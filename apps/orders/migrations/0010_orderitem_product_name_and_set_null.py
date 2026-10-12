"""Let a product be deleted without destroying the orders it appears on.

``OrderItem.product`` was PROTECT, so any product that had ever been ordered
could not be removed from the catalogue — the admin's delete button returned a
500 for every one of them. PROTECT was guarding something real (an order has to
keep saying what was bought), but the guard was in the wrong place: the thing
worth protecting is the *name*, not the row.

So: snapshot the name onto the line, backfill every existing line from its
product, then relax the FK to SET_NULL. After this an order reads correctly
whether or not the product still exists.

The backfill is reversible-safe: the reverse operation simply drops the column,
and restoring PROTECT would fail only if a product had already been deleted —
which is the honest outcome, since those orders would then have no product to
point back at.
"""
from django.db import migrations, models
import django.db.models.deletion


def backfill_product_names(apps, schema_editor):
    """Copy each line's current product name onto the line itself."""
    OrderItem = apps.get_model('orders', 'OrderItem')
    updated = 0
    for item in OrderItem.objects.select_related('product').iterator():
        if not item.product_name and item.product_id and item.product:
            item.product_name = item.product.name[:200]
            item.save(update_fields=['product_name'])
            updated += 1
    print(f'  backfilled product_name on {updated} order line(s)')


def noop_reverse(apps, schema_editor):
    """Nothing to undo — the column is dropped by the reverse of AddField."""


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0009_alter_order_status'),
        ('products', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='product_name',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        # Backfill BEFORE relaxing the FK, so every existing line already has a
        # name by the time a product can be deleted.
        migrations.RunPython(backfill_product_names, noop_reverse),
        migrations.AlterField(
            model_name='orderitem',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='products.product',
            ),
        ),
    ]
