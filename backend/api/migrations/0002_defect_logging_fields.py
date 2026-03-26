from __future__ import annotations

from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="defect",
            name="part_number",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="defect",
            name="defect_type",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                choices=[
                    ("dimensional", "Dimensional"),
                    ("cosmetic", "Cosmetic"),
                    ("functional", "Functional"),
                    ("labeling", "Labeling"),
                    ("packaging", "Packaging"),
                    ("other", "Other"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="defect",
            name="quantity_affected",
            field=models.IntegerField(blank=True, null=True, validators=[MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name="defect",
            name="production_line",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="defect",
            name="shift",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
