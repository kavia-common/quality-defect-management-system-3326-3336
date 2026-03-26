#!/usr/bin/env python
"""
Root-level manage.py shim.

This repository's Django project lives under the `backend/` directory.
Some environments (CI, operators, docs) may try to run `python manage.py <command>`
from the repository root and fail because manage.py is not found.

This shim forwards execution to `backend/manage.py`.

Usage:
    python manage.py migrate
    python manage.py repair_sqlite_migrations
    python manage.py seed_demo_data
"""
from __future__ import annotations

import runpy
from pathlib import Path
import sys


# PUBLIC_INTERFACE
def main() -> None:
    """Forward all Django management commands to backend/manage.py."""
    repo_root = Path(__file__).resolve().parent
    backend_manage = repo_root / "backend" / "manage.py"
    if not backend_manage.exists():
        raise SystemExit(f"Expected backend manage.py at: {backend_manage}")

    # Ensure imports resolve as if we were running inside backend/
    sys.path.insert(0, str(repo_root / "backend"))

    runpy.run_path(str(backend_manage), run_name="__main__")


if __name__ == "__main__":
    main()
