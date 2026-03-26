from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import CorrectiveAction, Defect, DefectHistory, FiveWhyAnalysis, WorkflowStatus


class WorkflowStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowStatus
        fields = [
            "id",
            "code",
            "name",
            "description",
            "sort_order",
            "is_terminal",
            "is_active",
            "created_at",
            "updated_at",
        ]


class FiveWhyAnalysisSerializer(serializers.ModelSerializer):
    defect_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = FiveWhyAnalysis
        fields = [
            "id",
            "defect_id",
            "problem_statement",
            "why1",
            "why2",
            "why3",
            "why4",
            "why5",
            "root_cause",
            "created_by",
            "created_at",
            "updated_at",
        ]


class CorrectiveActionSerializer(serializers.ModelSerializer):
    defect_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = CorrectiveAction
        fields = [
            "id",
            "defect_id",
            "title",
            "description",
            "owner",
            "due_date",
            "completed_at",
            "status",
            "effectiveness_check",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", None))
        completed_at = attrs.get("completed_at", getattr(self.instance, "completed_at", None))

        # If status is done, completed_at should be set (auto-fill if missing).
        if status == CorrectiveAction.Status.DONE and not completed_at:
            attrs["completed_at"] = timezone.now()

        # If status is not done, but completed_at is set, allow but keep it as-is (some teams backdate).
        return attrs


class DefectHistorySerializer(serializers.ModelSerializer):
    defect_id = serializers.IntegerField(read_only=True)
    from_status = WorkflowStatusSerializer(read_only=True)
    to_status = WorkflowStatusSerializer(read_only=True)

    class Meta:
        model = DefectHistory
        fields = [
            "id",
            "defect_id",
            "event_type",
            "message",
            "from_status",
            "to_status",
            "actor",
            "created_at",
        ]


class DefectSerializer(serializers.ModelSerializer):
    status = WorkflowStatusSerializer(read_only=True)
    status_id = serializers.PrimaryKeyRelatedField(
        source="status",
        queryset=WorkflowStatus.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    five_why = FiveWhyAnalysisSerializer(read_only=True)
    actions = CorrectiveActionSerializer(many=True, read_only=True)

    class Meta:
        model = Defect
        fields = [
            "id",
            "defect_key",
            "title",
            "description",
            "severity",
            "priority",
            "status",
            "status_id",
            # Additional defect logging fields (acceptance criteria)
            "part_number",
            "defect_type",
            "quantity_affected",
            "production_line",
            "shift",
            "reported_by",
            "assigned_to",
            "area",
            "source",
            "occurred_at",
            "due_date",
            "closed_at",
            "created_at",
            "updated_at",
            "five_why",
            "actions",
        ]

    def validate(self, attrs):
        # Ensure title is non-empty (schema says required).
        title = attrs.get("title", getattr(self.instance, "title", "") if self.instance else "")
        if title is not None and not str(title).strip():
            raise serializers.ValidationError({"title": "Title is required."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # If status is not supplied, default to NEW (if exists) else first by sort_order.
        status = validated_data.get("status")
        if status is None:
            status = WorkflowStatus.objects.filter(code="NEW").first() or WorkflowStatus.objects.order_by(
                "sort_order", "id"
            ).first()
            if status is None:
                raise serializers.ValidationError(
                    {"status_id": "No workflow statuses exist. Seed workflow_statuses first."}
                )
            validated_data["status"] = status

        defect = super().create(validated_data)
        DefectHistory.objects.create(
            defect=defect,
            event_type=DefectHistory.EventType.SYSTEM,
            message="Defect created",
            actor="system",
            to_status=defect.status,
        )
        return defect


class DefectCreateUpdateSerializer(serializers.ModelSerializer):
    """Simplified serializer for create/update to avoid nested writes."""

    class Meta:
        model = Defect
        fields = [
            "defect_key",
            "title",
            "description",
            "severity",
            "priority",
            "status",
            # Additional defect logging fields (acceptance criteria)
            "part_number",
            "defect_type",
            "quantity_affected",
            "production_line",
            "shift",
            "reported_by",
            "assigned_to",
            "area",
            "source",
            "occurred_at",
            "due_date",
            "closed_at",
        ]


class DefectTransitionRequestSerializer(serializers.Serializer):
    """Payload for defect status transitions."""

    to_status_code = serializers.CharField(max_length=64)
    actor = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")
    message = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_to_status_code(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("to_status_code is required.")
        return value


class DashboardMetricsSerializer(serializers.Serializer):
    total_defects = serializers.IntegerField()
    open_defects = serializers.IntegerField()
    closed_defects = serializers.IntegerField()
    overdue_defects = serializers.IntegerField()

    open_actions = serializers.IntegerField()
    overdue_actions = serializers.IntegerField()
    done_actions = serializers.IntegerField()
    actions_due_soon = serializers.IntegerField()

    by_status = serializers.DictField(child=serializers.IntegerField())
    by_severity = serializers.DictField(child=serializers.IntegerField())
