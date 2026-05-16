from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("bid_checker", "0002_appsettings")]

    operations = [
        migrations.CreateModel(
            name="GuestPilot",
            fields=[
                ("staff_number", models.CharField(
                    max_length=20, primary_key=True, serialize=False,
                    help_text="Kalitta employee number (Emp. No.)"
                )),
                ("name", models.CharField(
                    max_length=100,
                    help_text="Lastname, Firstname — must match the all-bids XLS exactly"
                )),
                ("seat_class", models.CharField(
                    max_length=2,
                    choices=[("CA", "Captain"), ("FO", "First Officer")],
                    default="FO"
                )),
                ("fleet", models.CharField(max_length=10, default="777")),
                ("seniority_number", models.IntegerField(
                    null=True, blank=True,
                    help_text="Company-wide seniority number from the roster"
                )),
                ("is_active", models.BooleanField(
                    default=False,
                    help_text="Must be ticked for this pilot to view their bids"
                )),
                ("notes", models.TextField(blank=True)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("last_viewed_at", models.DateTimeField(null=True, blank=True)),
                ("view_count", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Approved guest pilot",
                "verbose_name_plural": "Approved guest pilots",
                "ordering": ["seniority_number"],
            },
        ),
    ]
