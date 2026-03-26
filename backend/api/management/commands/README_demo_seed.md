# Demo seed data

This backend includes a management command that seeds realistic demo data:
- 20 defects with varied titles, severities/priorities, areas, owners
- multiple statuses (Open/NEW, In Analysis, Actions In Progress, Closed)
- several overdue defects (past due_date) for overdue dashboards
- 5-Why root cause analyses on a subset
- corrective actions on a subset (mix of open/in-progress/done)

## Run

From the backend folder:

```bash
python manage.py seed_demo_data
```

If you want to delete and recreate only the demo defects:

```bash
python manage.py seed_demo_data --reset
```

## Notes

- The command will ensure required workflow statuses exist (NEW, IN_ANALYSIS, ACTIONS_IN_PROGRESS, VERIFIED, CLOSED, etc.).
- Existing non-demo records are not touched.
