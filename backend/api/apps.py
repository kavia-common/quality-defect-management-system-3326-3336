from __future__ import annotations

import logging

from django.apps import AppConfig
from django.core.management import call_command
from django.db import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self) -> None:
        """
        Attempt to auto-repair SQLite migration drift and auto-seed demo data when DB is empty.

        Why this exists:
        - The project uses a shared SQLite database file that may already contain tables,
          or be missing newer columns if migrations were added later.
        - In hackathon/demo environments we want the dashboard to show data without
          requiring manual terminal steps.

        Safety/robustness:
        - Runs at most once per process.
        - If DB is not ready (e.g., migrate not run yet) it logs and exits without crashing.
        - Seeding only occurs when there are zero defects.
        """
        # Prevent duplicate execution (Django may import AppConfig multiple times).
        if getattr(self, "_auto_seed_ran", False):
            return
        self._auto_seed_ran = True

        from .models import Defect  # local import to avoid app-loading side effects

        try:
            # If the DB is drifted (missing columns), even a simple count can crash.
            # Repair first; command is idempotent for SQLite.
            call_command("repair_sqlite_migrations", verbosity=0)

            if Defect.objects.count() == 0:
                call_command("seed_demo_data", verbosity=0)
                logger.info("Auto-seeded demo data because database was empty.")
        except (OperationalError, ProgrammingError) as exc:
            # Typical when migrations haven't run yet or schema is missing tables.
            logger.warning("Auto-seed skipped (database not ready): %s", exc)
        except Exception as exc:  # pragma: no cover
            # Never block server startup due to demo helpers.
            logger.exception("Auto-seed encountered an unexpected error: %s", exc)
