from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    """
    Repair Django migration state for the shared SQLite database.

    Background:
    - This app often points to a shared SQLite file that may already contain tables
      but have missing Django migration history OR have schema drift (missing columns).

    Symptoms:
    - `migrate` fails with: table "<...>" already exists
    - `seed_demo_data` fails because some columns do not exist
    - API endpoints fail due to missing columns (OperationalError)

    Strategy:
    1) Ensure django_migrations exists (`migrate --run-syncdb`)
    2) Apply migrations with `--fake-initial` (handles "table already exists")
    3) Apply remaining migrations normally
    4) If SQLite errors indicate drift like "duplicate column"/"already exists", retry
       applying migrations with `--fake` as a last resort to mark them applied.

    This is intentionally conservative and best-effort; it avoids destructive schema changes.
    """

    # PUBLIC_INTERFACE
    def handle(self, *args, **options):
        """Repair the migration state and apply outstanding migrations in an idempotent way."""
        vendor = connection.vendor
        if vendor != "sqlite":
            self.stdout.write(
                self.style.WARNING(
                    f"repair_sqlite_migrations is intended for SQLite; current DB vendor is {vendor!r}. Proceeding."
                )
            )

        self.stdout.write("Step 1/4: Ensuring migration table exists (migrate --run-syncdb)...")
        call_command("migrate", "--run-syncdb", "--noinput", verbosity=1)

        self.stdout.write("Step 2/4: Faking initial migrations where tables already exist (--fake-initial)...")
        call_command("migrate", "--fake-initial", "--noinput", verbosity=1)

        try:
            self.stdout.write("Step 3/4: Applying any remaining migrations normally...")
            call_command("migrate", "--noinput", verbosity=1)
        except Exception as exc:
            msg = str(exc).lower()
            # Common drift patterns for SQLite:
            # - duplicate column name
            # - table ... already exists
            # - index ... already exists
            drift_indicators = ("duplicate column", "already exists", "duplicate")
            if any(ind in msg for ind in drift_indicators):
                self.stdout.write(
                    self.style.WARNING(
                        "Detected possible SQLite schema drift while applying migrations. "
                        "Retrying with `migrate --fake` to align migration history without destructive changes."
                    )
                )
                call_command("migrate", "--fake", "--noinput", verbosity=1)
            else:
                raise

        self.stdout.write("Step 4/4: Final migrate pass to ensure consistency...")
        call_command("migrate", "--noinput", verbosity=1)

        self.stdout.write(self.style.SUCCESS("SQLite migration repair complete."))
