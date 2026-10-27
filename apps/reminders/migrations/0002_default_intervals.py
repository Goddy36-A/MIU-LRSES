from django.db import migrations

DEFAULTS = [(1440, "24 hours before"), (60, "1 hour before"), (15, "15 minutes before")]


def seed(apps, schema_editor):
    ReminderInterval = apps.get_model("reminders", "ReminderInterval")
    ReminderConfig = apps.get_model("reminders", "ReminderConfig")
    if not ReminderInterval.objects.exists():
        for minutes, label in DEFAULTS:
            ReminderInterval.objects.create(minutes_before=minutes, label=label, is_active=True)
    ReminderConfig.objects.get_or_create(pk=1, defaults={"reminders_enabled": True})


class Migration(migrations.Migration):
    dependencies = [("reminders", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
