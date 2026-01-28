# BAKLIZ Ops

## Manual run (API)

1) Login:
- `POST /api/auth/login` with `{ "username": "...", "password": "..." }`

2) Trigger run:
- `POST /api/run?dry_run=true` with body `{ "overrides": { "daily_objective": 10 } }`

## Run auditing

- History: `GET /api/history`
- Run logs: `GET /api/runs`

## Common status codes

- `EXCLUDED_BLACKLIST`
- `EXCLUDED_HISTORY_SMB`
- `DUPLICATE_PERSON_BLOCKED`
- `ENRICH_FAILED`
- `DRY_RUN_READY`
- `DRAFT_CREATED`
- `POOL_EXHAUSTED`
- `ERROR_{TYPE}` (e.g. `ERROR_LINKUP`, `ERROR_GRAPH`)

