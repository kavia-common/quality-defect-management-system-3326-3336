from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class WorkflowStatus(models.Model):
    """Workflow status/state for defects."""

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    is_terminal = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_statuses"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code}"


class Defect(models.Model):
    """Core defect record."""

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    defect_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    title = models.TextField()
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.ForeignKey(WorkflowStatus, on_delete=models.PROTECT, related_name="defects")

    reported_by = models.TextField(blank=True)
    assigned_to = models.TextField(blank=True)
    area = models.TextField(blank=True)
    source = models.TextField(blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "defects"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="idx_defects_status_id"),
            models.Index(fields=["due_date"], name="idx_defects_due_date"),
            models.Index(fields=["created_at"], name="idx_defects_created_at"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.defect_key or f"DEF-{self.id}"


class FiveWhyAnalysis(models.Model):
    """5-Why analysis; exactly one per defect (optional)."""

    defect = models.OneToOneField(Defect, on_delete=models.CASCADE, related_name="five_why")
    problem_statement = models.TextField(blank=True)
    why1 = models.TextField(blank=True)
    why2 = models.TextField(blank=True)
    why3 = models.TextField(blank=True)
    why4 = models.TextField(blank=True)
    why5 = models.TextField(blank=True)
    root_cause = models.TextField(blank=True)

    created_by = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "five_why_analyses"

    def __str__(self) -> str:  # pragma: no cover
        return f"FiveWhy(defect_id={self.defect_id})"


class CorrectiveAction(models.Model):
    """Corrective / preventive action (CAPA) linked to a defect (many per defect)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    defect = models.ForeignKey(Defect, on_delete=models.CASCADE, related_name="actions")

    title = models.TextField()
    description = models.TextField(blank=True)
    owner = models.TextField(blank=True)

    due_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    effectiveness_check = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "corrective_actions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["defect"], name="idx_actions_defect_id"),
            models.Index(fields=["due_date"], name="idx_actions_due_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Action({self.id})"


class DefectHistory(models.Model):
    """Append-only history/comments log for a defect."""

    class EventType(models.TextChoices):
        COMMENT = "comment", "Comment"
        STATUS_CHANGE = "status_change", "Status Change"
        EDIT = "edit", "Edit"
        ANALYSIS_UPDATE = "analysis_update", "Analysis Update"
        ACTION_UPDATE = "action_update", "Action Update"
        SYSTEM = "system", "System"

    defect = models.ForeignKey(Defect, on_delete=models.CASCADE, related_name="history")
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    message = models.TextField(blank=True)

    from_status = models.ForeignKey(
        WorkflowStatus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_from",
    )
    to_status = models.ForeignKey(
        WorkflowStatus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_to",
    )
    actor = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "defect_history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["defect"], name="idx_history_defect_id"),
            models.Index(fields=["created_at"], name="idx_history_created_at"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"History({self.event_type} defect_id={self.defect_id})"
