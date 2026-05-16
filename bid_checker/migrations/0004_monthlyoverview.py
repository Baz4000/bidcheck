from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("bid_checker", "0003_guestpilot")]

    operations = [
        migrations.CreateModel(
            name="MonthlyOverview",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("month", models.DateField(unique=True)),
                ("xlsx_data", models.BinaryField()),
                ("downloaded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-month"],
            },
        ),
    ]
