import django.contrib.postgres.fields
from django.db import migrations, models


def text_to_array(apps, schema_editor):
    Application = apps.get_model("users", "Application")
    for app in Application.objects.all():
        text = app.additional_emails or ""
        app.additional_emails_array = [
            token.strip().lower() for token in text.split() if token.strip()
        ]
        app.save(update_fields=["additional_emails_array"])


def array_to_text(apps, schema_editor):
    Application = apps.get_model("users", "Application")
    for app in Application.objects.all():
        app.additional_emails = " ".join(app.additional_emails_array or [])
        app.save(update_fields=["additional_emails"])


class Migration(migrations.Migration):
    # Postgres can't cast text -> text[] in place, so add a new array column,
    # copy the whitespace-separated values across, drop the old column, and
    # rename the new one into place.
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="additional_emails_array",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.EmailField(max_length=254),
                blank=True,
                default=list,
                help_text=(
                    "Extra email addresses allowed to sign in to this "
                    "application, space separated, regardless of the team's "
                    "allowed domains."
                ),
                size=None,
            ),
        ),
        migrations.RunPython(text_to_array, array_to_text),
        migrations.RemoveField(
            model_name="application",
            name="additional_emails",
        ),
        migrations.RenameField(
            model_name="application",
            old_name="additional_emails_array",
            new_name="additional_emails",
        ),
    ]
