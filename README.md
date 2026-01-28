# BAKLIZ

BAKLIZ is a self-hosted B2B prospecting automation that guarantees a fixed number of Outlook email drafts per day while strictly enforcing exclusion rules (Blacklist + History).

## Quick start (Docker)

1) Copy env and fill required values:
- `cp .env.example infra/.env`

2) Start stack:
- `docker compose -f infra/docker-compose.yml up --build`

3) Open:
- Backend API: `http://localhost:8000/docs`
- Frontend UI: `http://localhost:5173`
- n8n: `http://localhost:5678`

## Demo mode

If `LINKUP_API_KEY` is empty, the backend runs in demo mode and uses mocked sourcing/enrichment so a dry-run can still reach the daily quota.

## Optional: Zeliq email enrichment

Set `EMAIL_ENRICH_PROVIDER=zeliq` and configure `ZELIQ_API_KEY`, `ZELIQ_CALLBACK_BASE_URL`, `ZELIQ_WEBHOOK_SECRET`. Zeliq callbacks require a public URL (localhost won't work without a tunnel).
