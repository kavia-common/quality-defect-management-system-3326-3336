from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import CorrectiveAction, Defect, WorkflowStatus


class HealthTests(APITestCase):
    def test_health(self):
        url = reverse("Health")  # Make sure the URL is named
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"message": "Server is up!"})


class OverdueActionsTests(APITestCase):
    def _seed_statuses_if_missing(self):
        """
        Ensure core workflow statuses exist for tests.

        This test suite shouldn't depend on manual seeding.
        """
        defaults = [
            ("NEW", "Open", 10, False),
            ("IN_ANALYSIS", "In Analysis", 20, False),
            ("ACTIONS_IN_PROGRESS", "Actions In Progress", 30, False),
            ("CLOSED", "Closed", 40, True),
        ]
        for code, name, sort, is_terminal in defaults:
            WorkflowStatus.objects.get_or_create(
                code=code,
                defaults={"name": name, "sort_order": sort, "is_terminal": is_terminal, "is_active": True},
            )

    def test_overdue_actions_endpoint_returns_overdue_and_excludes_done(self):
        """
        PUBLIC_INTERFACE
        Acceptance criteria: overdue alerts must work and at least one test must prove overdue logic.

        Verifies:
        - /api/actions/overdue/ returns actions whose due_date < now and status != done
        - DONE actions do not appear even if due_date is in the past
        """
        self._seed_statuses_if_missing()
        new_status = WorkflowStatus.objects.get(code="NEW")

        defect = Defect.objects.create(
            title="Test defect for overdue actions",
            description="",
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status=new_status,
            created_at=timezone.now(),
        )

        overdue_due_date = timezone.now() - timedelta(days=3)

        overdue_action = CorrectiveAction.objects.create(
            defect=defect,
            title="Overdue action",
            owner="QA",
            due_date=overdue_due_date,
            status=CorrectiveAction.Status.OPEN,
        )
        CorrectiveAction.objects.create(
            defect=defect,
            title="Past but done action",
            owner="QA",
            due_date=overdue_due_date,
            status=CorrectiveAction.Status.DONE,
            completed_at=timezone.now() - timedelta(days=1),
        )

        # Router basename is "actions" and action route is "overdue"
        url = "/api/actions/overdue/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data
        items = payload["results"] if isinstance(payload, dict) and "results" in payload else payload

        returned_ids = {it["id"] for it in items}
        self.assertIn(overdue_action.id, returned_ids)
        self.assertEqual(len(returned_ids), 1)
