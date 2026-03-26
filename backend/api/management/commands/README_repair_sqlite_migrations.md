# Repair SQLite migrations (shared canonical DB)

The backend is configured to use a canonical SQLite database file that may already exist and may already contain tables.

In some environments this can lead to migration-state drift:

- `python manage.py migrate` fails with `table "<...>" already exists`
- `python manage.py seed_demo_data` fails with missing columns (e.g. `defects.part_number`)

## Fix

From the `backend/` directory:

```bash
python manage.py repair_sqlite_migrations
python manage.py seed_demo_data
```

This repair command:

1. Ensures the `django_migrations` table exists.
2. Uses `--fake-initial` to mark initial migrations as applied when tables already exist.
3. Applies any remaining migrations normally.

## Notes

- This is intended for SQLite only and is safe for demo/dev environments.
- If you truly need a clean slate, delete the SQLite file and run `python manage.py migrate` again.
