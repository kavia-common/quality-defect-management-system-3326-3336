from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="WorkflowStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField(blank=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("is_terminal", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "workflow_statuses", "ordering": ["sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="Defect",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("defect_key", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("title", models.TextField()),
                ("description", models.TextField(blank=True)),
                ("severity", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")], default="medium", max_length=16)),
                ("priority", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")], default="medium", max_length=16)),
                ("reported_by", models.TextField(blank=True)),
                ("assigned_to", models.TextField(blank=True)),
                ("area", models.TextField(blank=True)),
                ("source", models.TextField(blank=True)),
                ("occurred_at", models.DateTimeField(blank=True, null=True)),
                ("due_date", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="defects", to="api.workflowstatus"),
                ),
            ],
            options={
                "db_table": "defects",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status"], name="idx_defects_status_id"),
                    models.Index(fields=["due_date"], name="idx_defects_due_date"),
                    models.Index(fields=["created_at"], name="idx_defects_created_at"),
                ],
            },
        ),
        migrations.CreateModel(
            name="FiveWhyAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("problem_statement", models.TextField(blank=True)),
                ("why1", models.TextField(blank=True)),
                ("why2", models.TextField(blank=True)),
                ("why3", models.TextField(blank=True)),
                ("why4", models.TextField(blank=True)),
                ("why5", models.TextField(blank=True)),
                ("root_cause", models.TextField(blank=True)),
                ("created_by", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "defect",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="five_why", to="api.defect"),
                ),
            ],
            options={"db_table": "five_why_analyses"},
        ),
        migrations.CreateModel(
            name="CorrectiveAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.TextField()),
                ("description", models.TextField(blank=True)),
                ("owner", models.TextField(blank=True)),
                ("due_date", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("open", "Open"), ("in_progress", "In Progress"), ("blocked", "Blocked"), ("done", "Done"), ("cancelled", "Cancelled")], default="open", max_length=16)),
                ("effectiveness_check", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "defect",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="actions", to="api.defect"),
                ),
            ],
            options={
                "db_table": "corrective_actions",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["defect"], name="idx_actions_defect_id"),
                    models.Index(fields=["due_date"], name="idx_actions_due_date"),
                ],
            },
        ),
        migrations.CreateModel(
            name="DefectHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("comment", "Comment"), ("status_change", "Status Change"), ("edit", "Edit"), ("analysis_update", "Analysis Update"), ("action_update", "Action Update"), ("system", "System")], max_length=32)),
                ("message", models.TextField(blank=True)),
                ("actor", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "defect",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="api.defect"),
                ),
                (
                    "from_status",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="history_from", to="api.workflowstatus"),
                ),
                (
                    "to_status",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="history_to", to="api.workflowstatus"),
                ),
            ],
            options={
                "db_table": "defect_history",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["defect"], name="idx_history_defect_id"),
                    models.Index(fields=["created_at"], name="idx_history_created_at"),
                ],
            },
        ),
    ]
