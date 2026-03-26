from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import WorkflowStatus


class Command(BaseCommand):
    help = "Seed default workflow statuses if none exist."

    def handle(self, *args, **options):
        if WorkflowStatus.objects.exists():
            self.stdout.write(self.style.WARNING("workflow_statuses already seeded; nothing to do."))
            return

        defaults = [
            ("NEW", "New", "Reported; awaiting triage", 10, False),
            ("TRIAGED", "Triaged", "Reviewed and categorized; next steps assigned", 20, False),
            ("IN_PROGRESS", "In Progress", "Investigation or remediation in progress", 30, False),
            ("PENDING_VERIFICATION", "Pending Verification", "Fix/actions completed; awaiting verification", 40, False),
            ("VERIFIED", "Verified", "Verified effective; ready to close", 50, False),
            ("CLOSED", "Closed", "Closed/completed", 60, True),
        ]
        now = timezone.now()

        for code, name, description, sort_order, is_terminal in defaults:
            WorkflowStatus.objects.create(
                code=code,
                name=name,
                description=description,
                sort_order=sort_order,
                is_terminal=is_terminal,
                is_active=True,
                created_at=now,
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(defaults)} workflow statuses."))
