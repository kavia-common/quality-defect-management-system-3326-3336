from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Ensure the backend workspace's conventional SQLite path points to the configured DB.

    Why:
    - Some operators/tools expect a local `backend/db.sqlite3` file.
    - Our Django settings point at a canonical DB (database workspace `myapp.db`).
    - If both exist independently, seeds/migrations may affect one DB while the API reads the other.

    This command creates/updates a symlink `backend/db.sqlite3` -> DATABASES['default']['NAME']
    when safe to do so.
    """

    # PUBLIC_INTERFACE
    def handle(self, *args, **options):
        """Create a stable db.sqlite3 symlink to the configured SQLite database file."""
        db_name = str(settings.DATABASES["default"]["NAME"])
        target = Path(db_name).expanduser().resolve()

        backend_dir = Path(__file__).resolve().parents[4]  # .../backend
        link_path = (backend_dir / "db.sqlite3").resolve()

        # If DB isn't SQLite or target doesn't exist yet, we still create the link path's parent.
        if not target.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Configured SQLite DB file does not exist yet: {target}. "
                    "Skipping link creation (run migrations/seed first)."
                )
            )
            return

        try:
            # If link_path exists and is already correct, no-op.
            if link_path.is_symlink() and link_path.resolve() == target:
                self.stdout.write(self.style.SUCCESS(f"db.sqlite3 link already points to: {target}"))
                return

            # If a real file exists at db.sqlite3 (not symlink), do not overwrite (could destroy data).
            if link_path.exists() and not link_path.is_symlink():
                self.stdout.write(
                    self.style.WARNING(
                        f"{link_path} exists and is not a symlink. Not modifying to avoid data loss. "
                        f"Configured DB is: {target}"
                    )
                )
                return

            # Remove stale symlink if present.
            if link_path.is_symlink():
                link_path.unlink()

            # Create symlink (relative links can be brittle across runners; use absolute).
            os.symlink(str(target), str(link_path))
            self.stdout.write(self.style.SUCCESS(f"Created db.sqlite3 symlink: {link_path} -> {target}"))
        except OSError as exc:
            self.stdout.write(self.style.WARNING(f"Could not create db.sqlite3 symlink: {exc}"))
