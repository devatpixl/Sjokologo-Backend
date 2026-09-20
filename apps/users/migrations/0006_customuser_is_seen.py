from django.db import migrations, models


def mark_existing_seen(apps, schema_editor):
    """Every customer that existed before the badge shipped counts as seen.

    Without this the admin opens the panel to a badge of every customer ever
    registered, which is noise, not a notification — ops would clear it once
    without reading and learn to ignore it. Starting at zero means the first
    number they ever see is a real new signup.
    """
    CustomUser = apps.get_model('users', 'CustomUser')
    CustomUser.objects.update(is_seen=True)


def unmark(apps, schema_editor):
    """Reverse leaves rows as they are — the column is dropped anyway."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_loyaltymember'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='is_seen',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_seen, unmark),
    ]
