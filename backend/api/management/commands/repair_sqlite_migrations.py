from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import connection


class Command(BaseCommand):
    """
    Repair Django migration state for the shared SQLite database.

    This project is configured to point Django at a canonical SQLite file that may already
    contain tables (e.g., created by a previous run or by the database workspace tooling)
    but may not have Django's migration history recorded.

    Symptom:
    - `python manage.py migrate` fails with: table "<...>" already exists
    - `python manage.py seed_demo_data` fails because some columns do not exist (missing migrations)

    What this command does:
    1) Ensures the `django_migrations` table exists (via `migrate --run-syncdb`).
    2) Marks core migrations as applied using `--fake-initial` so Django doesn't try to
       recreate tables that already exist.
    3) Applies any remaining migrations normally.

    Usage:
        python manage.py repair_sqlite_migrations
    """

    # PUBLIC_INTERFACE
    def handle(self, *args, **options):
        """Repair the migration state and apply outstanding migrations."""
        vendor = connection.vendor
        if vendor != "sqlite":
            self.stdout.write(
                self.style.WARNING(
                    f"repair_sqlite_migrations is intended for SQLite; current DB vendor is {vendor!r}. "
                    "Proceeding anyway."
                )
            )

        self.stdout.write("Step 1/3: Ensuring migration table exists (migrate --run-syncdb)...")
        call_command("migrate", "--run-syncdb", "--noinput", verbosity=1)

        # `--fake-initial` tells Django: if tables already exist, mark initial migration as applied.
        self.stdout.write("Step 2/3: Faking initial migrations where tables already exist (--fake-initial)...")
        call_command("migrate", "--fake-initial", "--noinput", verbosity=1)

        self.stdout.write("Step 3/3: Applying any remaining migrations normally...")
        call_command("migrate", "--noinput", verbosity=1)

        self.stdout.write(self.style.SUCCESS("Migration state repaired and migrations applied (if any were pending)."))
