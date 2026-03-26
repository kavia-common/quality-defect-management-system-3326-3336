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


def _pick_status_by_codes(codes: list[str]) -> WorkflowStatus | None:
    """Pick the first active WorkflowStatus matching any of the provided codes (in order)."""
    if not codes:
        return None
    for code in codes:
        obj = WorkflowStatus.objects.filter(code=code, is_active=True).first()
        if obj:
            return obj
    return None


def _defect_has_root_cause(defect: Defect) -> bool:
    """Return True if the defect has a 5-Why analysis with non-empty root_cause."""
    if not hasattr(defect, "five_why") or defect.five_why is None:
        return False
    return bool((defect.five_why.root_cause or "").strip())


def _defect_actions_completion(defect: Defect) -> tuple[int, int]:
    """Return (done_count, total_count) for the defect's actions."""
    total = CorrectiveAction.objects.filter(defect=defect).count()
    done = CorrectiveAction.objects.filter(defect=defect, status=CorrectiveAction.Status.DONE).count()
    return done, total


def _auto_advance_defect_based_on_actions(defect: Defect, *, actor: str = "system") -> None:
    """
    Advance defect status if business rules are met:
    - If defect has actions and all are done => move to VERIFIED (if exists) else PENDING_VERIFICATION.
    """
    done, total = _defect_actions_completion(defect)
    if total <= 0:
        return
    if done != total:
        return

    # Prefer VERIFIED (matches existing seed), else use PENDING_VERIFICATION.
    to_status = _pick_status_by_codes(["VERIFIED", "PENDING_VERIFICATION"])
    if not to_status or defect.status_id == to_status.id:
        return

    from_status = defect.status
    defect.status = to_status
    defect.updated_at = timezone.now()
    if to_status.is_terminal:
        defect.closed_at = defect.closed_at or timezone.now()
    else:
        defect.closed_at = None
    defect.save(update_fields=["status", "updated_at", "closed_at"])

    DefectHistory.objects.create(
        defect=defect,
        event_type=DefectHistory.EventType.STATUS_CHANGE,
        message="All corrective actions completed; defect advanced automatically.",
        from_status=from_status,
        to_status=to_status,
        actor=actor,
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
    """
    CRUD for defects + workflow transitions, overdue queries, and CSV export.

    Acceptance-criteria enforcement:
    - Root cause must be present before moving beyond "In Analysis".
      (We interpret "beyond Open" as progressing out of analysis into action/closure stages.)
    - Prevent closure unless at least one corrective action exists and all actions are completed.
    """

    queryset = Defect.objects.select_related("status").all().prefetch_related("actions", "five_why")
    serializer_class = DefectSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Optional filters for frontend convenience:
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

    def perform_update(self, serializer):
        """
        Override update to keep updated_at consistent.
        We intentionally do not allow arbitrary nested writes in this endpoint.
        """
        serializer.save(updated_at=timezone.now())
        # No automatic gating here; gating is enforced on transition endpoint.

    @swagger_auto_schema(
        method="post",
        operation_summary="Transition defect status (workflow-enforced)",
        operation_description=(
            "Performs a workflow transition for a defect by status code.\n\n"
            "Acceptance rules:\n"
            "- Root cause must exist before moving beyond analysis into action/verification/closure stages.\n"
            "- You cannot transition to a terminal/closed status unless:\n"
            "  (1) at least one corrective action exists, and\n"
            "  (2) all actions are marked DONE.\n"
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
        if getattr(from_status, "id", None) == to_status.id:
            return Response({"detail": "Defect already in that status."}, status=status.HTTP_400_BAD_REQUEST)

        # Acceptance workflow enforcement (authoritative requirements):
        # Open -> In Analysis -> Actions In Progress -> Closed
        #
        # - Root cause must be filled before "In Analysis"
        # - At least one corrective action must exist before "Actions In Progress"
        # - All actions must be completed before "Closed"
        #
        # NOTE: Frontend also gates these transitions for UX, but backend remains the source of truth.

        # Root-cause gating for entering IN_ANALYSIS.
        if to_status.code == "IN_ANALYSIS" and not _defect_has_root_cause(defect):
            return Response(
                {
                    "detail": (
                        "Root Cause Analysis is required before moving to In Analysis. "
                        "Please complete the 5-Why fields and root cause summary first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Actions gating for entering ACTIONS_IN_PROGRESS.
        if to_status.code == "ACTIONS_IN_PROGRESS":
            total_actions = CorrectiveAction.objects.filter(defect=defect).count()
            if total_actions <= 0:
                return Response(
                    {
                        "detail": (
                            "At least one corrective action is required before moving to Actions In Progress. "
                            "Please create a corrective action first."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Closure gating for CLOSED (and for terminal statuses if any are used as closure).
        if to_status.code == "CLOSED" or to_status.is_terminal:
            done, total = _defect_actions_completion(defect)
            if total <= 0:
                return Response(
                    {"detail": "At least one corrective action is required before closing a defect."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if done != total:
                return Response(
                    {"detail": f"All corrective actions must be completed before closure. ({done}/{total} done)"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        defect.status = to_status
        defect.updated_at = timezone.now()

        if to_status.is_terminal:
            defect.closed_at = defect.closed_at or timezone.now()
        else:
            defect.closed_at = None

        defect.save(update_fields=["status", "updated_at", "closed_at"])

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

        # IMPORTANT: set proper content type and attachment disposition for immediate download.
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="defects.csv"'
        response["X-Content-Type-Options"] = "nosniff"

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
                "root_cause",
                "actions_total",
                "actions_done",
            ]
        )

        # Ensure we don't explode queries:
        # - use iterator for defects
        # - when the base queryset uses prefetch_related (as this ViewSet does),
        #   Django requires an explicit chunk_size for iterator().
        # - per row we do 2 simple counts (acceptable for hackathon scale)
        for d in qs.iterator(chunk_size=2000):
            done, total = _defect_actions_completion(d)
            root_cause = ""
            if hasattr(d, "five_why") and d.five_why is not None:
                root_cause = (d.five_why.root_cause or "").strip()

            writer.writerow(
                [
                    d.id,
                    d.defect_key or "",
                    d.title,
                    d.severity,
                    d.priority,
                    d.status.code if d.status_id else "",
                    d.status.name if d.status_id else "",
                    d.part_number or "",
                    d.defect_type or "",
                    d.quantity_affected if d.quantity_affected is not None else "",
                    d.production_line or "",
                    d.shift or "",
                    d.reported_by or "",
                    d.assigned_to or "",
                    d.area or "",
                    d.source or "",
                    d.occurred_at.date().isoformat() if d.occurred_at else "",
                    d.due_date.date().isoformat() if d.due_date else "",
                    d.closed_at.isoformat() if d.closed_at else "",
                    d.created_at.isoformat() if d.created_at else "",
                    d.updated_at.isoformat() if d.updated_at else "",
                    root_cause,
                    total,
                    done,
                ]
            )

        return response


class FiveWhyAnalysisViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Create/update/retrieve 5-Why analysis for a defect.

    Acceptance rules:
    - After saving 5-Why, defect is automatically moved to "IN_ANALYSIS" if currently NEW/TRIAGED.
    """

    queryset = FiveWhyAnalysis.objects.select_related("defect").all()
    serializer_class = FiveWhyAnalysisSerializer

    @swagger_auto_schema(
        method="put",
        operation_summary="Upsert 5-Why analysis for defect",
        operation_description=(
            "Creates or updates the defect's 5-Why analysis in a single call.\n\n"
            "Side effects:\n"
            "- If the defect is in NEW/TRIAGED and analysis is saved, defect is moved to IN_ANALYSIS automatically."
        ),
        request_body=FiveWhyAnalysisSerializer,
        responses={200: FiveWhyAnalysisSerializer},
        tags=["analysis"],
    )
    @action(detail=False, methods=["put"], url_path=r"by-defect/(?P<defect_id>\d+)")
    def upsert_by_defect(self, request, defect_id: str):
        defect = Defect.objects.select_related("status").filter(id=defect_id).first()
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
            message = "5-Why analysis updated"
        else:
            analysis = serializer.save(defect=defect)
            message = "5-Why analysis created"

        DefectHistory.objects.create(
            defect=defect,
            event_type=DefectHistory.EventType.ANALYSIS_UPDATE,
            message=message,
            actor=request.data.get("created_by", "") or "",
        )

        # Auto-move defect to IN_ANALYSIS after saving analysis (as requested).
        in_analysis = _pick_status_by_codes(["IN_ANALYSIS"])
        if in_analysis and defect.status and defect.status.code in {"NEW", "TRIAGED"} and defect.status_id != in_analysis.id:
            from_status = defect.status
            defect.status = in_analysis
            defect.updated_at = timezone.now()
            defect.closed_at = None
            defect.save(update_fields=["status", "updated_at", "closed_at"])
            DefectHistory.objects.create(
                defect=defect,
                event_type=DefectHistory.EventType.STATUS_CHANGE,
                message="Moved to IN_ANALYSIS after saving 5-Why analysis.",
                from_status=from_status,
                to_status=in_analysis,
                actor="system",
            )

        return Response(self.get_serializer(analysis).data)


class CorrectiveActionViewSet(viewsets.ModelViewSet):
    """
    CRUD for corrective actions with overdue helpers.

    Acceptance rules:
    - Allow marking action as completed (status DONE, completed_at auto-set).
    - When all actions for a defect are completed, defect status advances automatically.
    """

    queryset = CorrectiveAction.objects.select_related("defect", "defect__status").all()
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
        _auto_advance_defect_based_on_actions(action_obj.defect, actor="system")

    def perform_create(self, serializer):
        action_obj: CorrectiveAction = serializer.save()
        DefectHistory.objects.create(
            defect=action_obj.defect,
            event_type=DefectHistory.EventType.ACTION_UPDATE,
            message=f"Action created: {action_obj.title}",
            actor=self.request.data.get("actor", "") or "",
        )

        # If there is an action created, encourage workflow movement:
        # Move IN_ANALYSIS -> ACTIONS_IN_PROGRESS automatically when first action is added (if statuses exist).
        actions_in_progress = _pick_status_by_codes(["ACTIONS_IN_PROGRESS"])
        if actions_in_progress and action_obj.defect.status and action_obj.defect.status.code == "IN_ANALYSIS":
            from_status = action_obj.defect.status
            action_obj.defect.status = actions_in_progress
            action_obj.defect.updated_at = timezone.now()
            action_obj.defect.closed_at = None
            action_obj.defect.save(update_fields=["status", "updated_at", "closed_at"])
            DefectHistory.objects.create(
                defect=action_obj.defect,
                event_type=DefectHistory.EventType.STATUS_CHANGE,
                message="Moved to ACTIONS_IN_PROGRESS after adding first corrective action.",
                from_status=from_status,
                to_status=actions_in_progress,
                actor="system",
            )

        _auto_advance_defect_based_on_actions(action_obj.defect, actor="system")

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

        by_status_qs = Defect.objects.values("status__code").annotate(c=Count("id")).order_by()
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
