from __future__ import annotations

import csv
from datetime import timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import CorrectiveAction, Defect, DefectHistory, FiveWhyAnalysis, WorkflowStatus
from .serializers import (
    CorrectiveActionSerializer,
    DashboardMetricsSerializer,
    DefectHistorySerializer,
    DefectSerializer,
    DefectTransitionRequestSerializer,
    FiveWhyAnalysisSerializer,
    WorkflowStatusSerializer,
)


@api_view(["GET"])
def health(request):
    """Health check endpoint."""
    return Response({"message": "Server is up!"})


class WorkflowStatusViewSet(viewsets.ModelViewSet):
    """CRUD for workflow statuses (admin-like)."""

    queryset = WorkflowStatus.objects.all()
    serializer_class = WorkflowStatusSerializer


class DefectViewSet(viewsets.ModelViewSet):
    """CRUD for defects + custom actions for status transitions, overdue queries, and CSV export."""

    queryset = Defect.objects.select_related("status").all().prefetch_related("actions")
    serializer_class = DefectSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Optional filters for frontend convenience:
        # ?status=NEW or ?status_id=1
        status_code = self.request.query_params.get("status")
        status_id = self.request.query_params.get("status_id")
        severity = self.request.query_params.get("severity")
        priority = self.request.query_params.get("priority")
        assigned_to = self.request.query_params.get("assigned_to")
        overdue = self.request.query_params.get("overdue")

        if status_code:
            qs = qs.filter(status__code=status_code)
        if status_id:
            qs = qs.filter(status_id=status_id)
        if severity:
            qs = qs.filter(severity=severity)
        if priority:
            qs = qs.filter(priority=priority)
        if assigned_to:
            qs = qs.filter(assigned_to__icontains=assigned_to)

        if overdue in ("1", "true", "True"):
            now = timezone.now()
            qs = qs.filter(due_date__isnull=False, due_date__lt=now).exclude(status__is_terminal=True)

        return qs

    @swagger_auto_schema(
        method="post",
        operation_summary="Transition defect status",
        operation_description=(
            "Performs a workflow transition for a defect by status code.\n\n"
            "Business rules:\n"
            "- Only active statuses can be transitioned to.\n"
            "- When transitioning to a terminal status, defect.closed_at is set.\n"
            "- When transitioning from a terminal to non-terminal status, defect.closed_at is cleared."
        ),
        request_body=DefectTransitionRequestSerializer,
        responses={200: DefectSerializer},
        tags=["defects"],
    )
    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        defect: Defect = self.get_object()
        serializer = DefectTransitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        to_code = serializer.validated_data["to_status_code"]
        actor = serializer.validated_data.get("actor") or ""
        message = serializer.validated_data.get("message") or ""

        to_status = WorkflowStatus.objects.filter(code=to_code, is_active=True).first()
        if not to_status:
            return Response(
                {"detail": f"Unknown or inactive status code: {to_code}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_status = defect.status
        if from_status_id := getattr(from_status, "id", None):
            if from_status_id == to_status.id:
                return Response({"detail": "Defect already in that status."}, status=status.HTTP_400_BAD_REQUEST)

        defect.status = to_status
        defect.updated_at = timezone.now()

        if to_status.is_terminal:
            defect.closed_at = defect.closed_at or timezone.now()
        else:
            # Reopening
            defect.closed_at = None

        defect.save()

        DefectHistory.objects.create(
            defect=defect,
            event_type=DefectHistory.EventType.STATUS_CHANGE,
            message=message or f"Status changed to {to_status.code}",
            from_status=from_status,
            to_status=to_status,
            actor=actor,
        )

        return Response(DefectSerializer(defect, context={"request": request}).data)

    @swagger_auto_schema(
        method="get",
        operation_summary="List overdue defects",
        operation_description="Returns defects with due_date < now and not in terminal status.",
        responses={200: DefectSerializer(many=True)},
        tags=["defects"],
    )
    @action(detail=False, methods=["get"], url_path="overdue")
    def overdue(self, request):
        now = timezone.now()
        qs = (
            self.get_queryset()
            .filter(due_date__isnull=False, due_date__lt=now)
            .exclude(status__is_terminal=True)
            .order_by("due_date")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(DefectSerializer(page, many=True, context={"request": request}).data)
        return Response(DefectSerializer(qs, many=True, context={"request": request}).data)

    @swagger_auto_schema(
        method="get",
        operation_summary="Export defects to CSV",
        operation_description=(
            "Exports defects to CSV. Supports same query filters as /defects/.\n"
            "Response Content-Type: text/csv"
        ),
        manual_parameters=[
            openapi.Parameter("status", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("status_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("severity", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("priority", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("assigned_to", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("overdue", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN),
        ],
        responses={200: "CSV file"},
        tags=["export"],
    )
    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(self, request):
        qs = self.get_queryset().select_related("status")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="defects.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "id",
                "defect_key",
                "title",
                "severity",
                "priority",
                "status_code",
                "status_name",
                "reported_by",
                "assigned_to",
                "area",
                "source",
                "occurred_at",
                "due_date",
                "closed_at",
                "created_at",
                "updated_at",
            ]
        )

        for d in qs.iterator():
            writer.writerow(
                [
                    d.id,
                    d.defect_key or "",
                    d.title,
                    d.severity,
                    d.priority,
                    d.status.code if d.status_id else "",
                    d.status.name if d.status_id else "",
                    d.reported_by or "",
                    d.assigned_to or "",
                    d.area or "",
                    d.source or "",
                    d.occurred_at.isoformat() if d.occurred_at else "",
                    d.due_date.isoformat() if d.due_date else "",
                    d.closed_at.isoformat() if d.closed_at else "",
                    d.created_at.isoformat() if d.created_at else "",
                    d.updated_at.isoformat() if d.updated_at else "",
                ]
            )

        return response


class FiveWhyAnalysisViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Create/update/retrieve 5-Why analysis for a defect.

    Supports:
    - POST /five-whys/ with {"defect_id": ..., ...} to create (one per defect)
    - GET /five-whys/{id}/
    - PUT/PATCH /five-whys/{id}/
    - PUT/PATCH /defects/{id}/five-why/ via DefectViewSet (preferred)
    """

    queryset = FiveWhyAnalysis.objects.select_related("defect").all()
    serializer_class = FiveWhyAnalysisSerializer

    @swagger_auto_schema(
        method="put",
        operation_summary="Upsert 5-Why analysis for defect",
        operation_description="Creates or updates the defect's 5-Why analysis in a single call.",
        request_body=FiveWhyAnalysisSerializer,
        responses={200: FiveWhyAnalysisSerializer},
        tags=["analysis"],
    )
    @action(detail=False, methods=["put"], url_path=r"by-defect/(?P<defect_id>\d+)")
    def upsert_by_defect(self, request, defect_id: str):
        defect = Defect.objects.filter(id=defect_id).first()
        if not defect:
            return Response({"detail": "Defect not found."}, status=status.HTTP_404_NOT_FOUND)

        obj = FiveWhyAnalysis.objects.filter(defect=defect).first()
        if obj:
            serializer = self.get_serializer(obj, data=request.data, partial=False)
        else:
            serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        if obj:
            analysis = serializer.save(updated_at=timezone.now())
            event_type = DefectHistory.EventType.ANALYSIS_UPDATE
            message = "5-Why analysis updated"
        else:
            analysis = serializer.save(defect=defect)
            event_type = DefectHistory.EventType.ANALYSIS_UPDATE
            message = "5-Why analysis created"

        DefectHistory.objects.create(
            defect=defect,
            event_type=event_type,
            message=message,
            actor=request.data.get("created_by", "") or "",
        )
        return Response(self.get_serializer(analysis).data)


class CorrectiveActionViewSet(viewsets.ModelViewSet):
    """CRUD for corrective actions with overdue/summary helpers."""

    queryset = CorrectiveAction.objects.select_related("defect").all()
    serializer_class = CorrectiveActionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        defect_id = self.request.query_params.get("defect_id")
        owner = self.request.query_params.get("owner")
        status_param = self.request.query_params.get("status")
        overdue = self.request.query_params.get("overdue")

        if defect_id:
            qs = qs.filter(defect_id=defect_id)
        if owner:
            qs = qs.filter(owner__icontains=owner)
        if status_param:
            qs = qs.filter(status=status_param)
        if overdue in ("1", "true", "True"):
            now = timezone.now()
            qs = qs.filter(due_date__isnull=False, due_date__lt=now).exclude(status=CorrectiveAction.Status.DONE)
        return qs

    def perform_update(self, serializer):
        action_obj: CorrectiveAction = serializer.save(updated_at=timezone.now())
        DefectHistory.objects.create(
            defect=action_obj.defect,
            event_type=DefectHistory.EventType.ACTION_UPDATE,
            message=f"Action updated: {action_obj.title}",
            actor=self.request.data.get("actor", "") or "",
        )

    def perform_create(self, serializer):
        action_obj: CorrectiveAction = serializer.save()
        DefectHistory.objects.create(
            defect=action_obj.defect,
            event_type=DefectHistory.EventType.ACTION_UPDATE,
            message=f"Action created: {action_obj.title}",
            actor=self.request.data.get("actor", "") or "",
        )

    @swagger_auto_schema(
        method="get",
        operation_summary="List overdue corrective actions",
        operation_description="Returns actions with due_date < now and status != done.",
        responses={200: CorrectiveActionSerializer(many=True)},
        tags=["actions"],
    )
    @action(detail=False, methods=["get"], url_path="overdue")
    def overdue(self, request):
        now = timezone.now()
        qs = (
            self.get_queryset()
            .filter(due_date__isnull=False, due_date__lt=now)
            .exclude(status=CorrectiveAction.Status.DONE)
            .order_by("due_date")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                CorrectiveActionSerializer(page, many=True, context={"request": request}).data
            )
        return Response(CorrectiveActionSerializer(qs, many=True, context={"request": request}).data)


class DefectHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to defect history (comments, status changes, etc.)."""

    queryset = DefectHistory.objects.select_related("defect", "from_status", "to_status").all()
    serializer_class = DefectHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        defect_id = self.request.query_params.get("defect_id")
        if defect_id:
            qs = qs.filter(defect_id=defect_id)
        return qs


class DashboardViewSet(viewsets.ViewSet):
    """Dashboard aggregates for quick UI metrics."""

    @swagger_auto_schema(
        operation_summary="Get dashboard metrics",
        operation_description="Returns aggregate counts for defects and actions, including overdue and breakdowns.",
        responses={200: DashboardMetricsSerializer},
        tags=["dashboard"],
    )
    def list(self, request):
        now = timezone.now()
        soon = now + timedelta(days=7)

        total_defects = Defect.objects.count()
        closed_defects = Defect.objects.filter(status__is_terminal=True).count()
        open_defects = Defect.objects.exclude(status__is_terminal=True).count()
        overdue_defects = (
            Defect.objects.filter(due_date__isnull=False, due_date__lt=now).exclude(status__is_terminal=True).count()
        )

        open_actions = CorrectiveAction.objects.exclude(status=CorrectiveAction.Status.DONE).count()
        overdue_actions = (
            CorrectiveAction.objects.filter(due_date__isnull=False, due_date__lt=now)
            .exclude(status=CorrectiveAction.Status.DONE)
            .count()
        )
        done_actions = CorrectiveAction.objects.filter(status=CorrectiveAction.Status.DONE).count()
        actions_due_soon = (
            CorrectiveAction.objects.filter(due_date__isnull=False, due_date__gte=now, due_date__lte=soon)
            .exclude(status=CorrectiveAction.Status.DONE)
            .count()
        )

        by_status_qs = (
            Defect.objects.values("status__code")
            .annotate(c=Count("id"))
            .order_by()
        )
        by_status = {row["status__code"] or "UNKNOWN": row["c"] for row in by_status_qs}

        by_severity_qs = Defect.objects.values("severity").annotate(c=Count("id")).order_by()
        by_severity = {row["severity"] or "UNKNOWN": row["c"] for row in by_severity_qs}

        payload = {
            "total_defects": total_defects,
            "open_defects": open_defects,
            "closed_defects": closed_defects,
            "overdue_defects": overdue_defects,
            "open_actions": open_actions,
            "overdue_actions": overdue_actions,
            "done_actions": done_actions,
            "actions_due_soon": actions_due_soon,
            "by_status": by_status,
            "by_severity": by_severity,
        }
        return Response(payload)
