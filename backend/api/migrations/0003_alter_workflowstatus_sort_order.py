from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_defect_logging_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowstatus",
            name="sort_order",
            field=models.IntegerField(default=0, validators=[MinValueValidator(0)]),
        ),
    ]
