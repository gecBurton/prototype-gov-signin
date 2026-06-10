import django.db.models.deletion
from django.db import migrations, models


def assign_default_team(apps, schema_editor):
    Team = apps.get_model("users", "Team")
    User = apps.get_model("users", "User")
    Application = apps.get_model("users", "Application")
    team = Team.objects.create(name="Default Team")
    User.objects.update(team=team)
    Application.objects.update(team=team)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_allowed_email_domains"),
    ]

    operations = [
        migrations.CreateModel(
            name="Team",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
            ],
        ),
        migrations.AddField(
            model_name="user",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members",
                to="users.team",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="applications",
                to="users.team",
            ),
        ),
        migrations.RunPython(assign_default_team, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="application",
            name="owners",
        ),
    ]
