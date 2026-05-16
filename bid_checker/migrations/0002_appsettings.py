from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("bid_checker", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="AppSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("key", models.CharField(max_length=100, unique=True)),
                ("value", models.TextField(blank=True)),
            ],
            options={"verbose_name": "App setting", "verbose_name_plural": "App settings"},
        ),
    ]
