"""Add 'julekalender' to Product.category.

choices is validation metadata only — Django records it in the migration, but
the column stays an unconstrained varchar, so this alters no data and changes
no existing row. It exists so the admin's category dropdown offers the option
and serializer validation accepts it.

A new category rather than renaming an existing one: the advent calendar must
not inherit another product's slug, URL or order history, and has to be
retirable after Christmas without touching them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_product_is_active'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='category',
            field=models.CharField(
                choices=[
                    ('liten-sjokoladeboks', 'Liten sjokoladeboks'),
                    ('stor-sjokoladeboks', 'Stor sjokoladeboks'),
                    ('sjokoladebarer', 'Sjokoladebarer'),
                    ('julekalender', 'Julekalender'),
                ],
                max_length=50,
            ),
        ),
    ]
