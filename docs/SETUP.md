# BAKLIZ Setup (Self-Hosted)

## Services
- Postgres (source of truth)
- Backend (FastAPI) on `:8000`
- Frontend (React/Vite) on `:5173`
- n8n (Community Edition) on `:5678`

## 1) Configure environment

Docker Compose reads `infra/.env`.

Copy the example env file:
- PowerShell (Windows): `Copy-Item .env.example infra/.env`
- macOS/Linux: `cp .env.example infra/.env`

Set at minimum:
- `JWT_SECRET`
- `ADMIN_PASSWORD`

Optional:
- `LINKUP_API_KEY` (enables live sourcing/enrichment)
- `GRAPH_CLIENT_ID`, `GRAPH_TENANT_ID` (enables live Outlook draft creation)
- Zeliq (optional email enrichment):
  - `EMAIL_ENRICH_PROVIDER=zeliq`
  - `ZELIQ_API_KEY`, `ZELIQ_CALLBACK_BASE_URL`, `ZELIQ_WEBHOOK_SECRET`

## 2) Start the stack

- `docker compose -f infra/docker-compose.yml up --build`

Backend runs migrations automatically at startup.

## 3) Open the UI

- Frontend: `http://localhost:5173`
- Backend API docs: `http://localhost:8000/docs`
- n8n: `http://localhost:5678`

## 4) Demo mode

If `LINKUP_API_KEY` is empty, the backend automatically uses demo data for sourcing/enrichment so you can run `dry_run` end-to-end.

To force demo mode even with a Linkup key:
- `BAKLIZ_DEMO_MODE=true`

## Linkup quick test (optional)

Do not hardcode your key in code. The Linkup SDK reads it from `LINKUP_API_KEY`.

```python
from linkup import LinkupClient

client = LinkupClient()  # reads LINKUP_API_KEY from env

response = client.search(
  query="What is Microsoft's revenue and operating income for 2024?",
  depth="standard",
  output_type="searchResults",
  include_images=False,
)

print(response)
```

If you posted your API key anywhere public (including chats), rotate/revoke it and issue a new one.

## Zeliq email enrichment (optional)

Zeliq's enrich endpoints are asynchronous and require a `callback_url` that is reachable from the public internet.

For local development, you must expose your backend with a tunnel (example using ngrok):
- `ngrok http 8000`
- Set `ZELIQ_CALLBACK_BASE_URL` to the public `https://...` URL that ngrok prints.

Callback endpoint implemented by the backend:
- `POST /api/integrations/zeliq/callback/email`

## 5) Microsoft Graph (device code)

If you set `GRAPH_CLIENT_ID` + `GRAPH_TENANT_ID` and set config `run_mode=live`, the backend attempts to create Outlook drafts via `/me/messages`.

For `GRAPH_AUTH_MODE=device_code`, the backend logs a device code message on first use. Follow the instructions in the backend logs to authenticate once; the refresh token is cached at `GRAPH_TOKEN_CACHE_PATH`.

## 6) n8n workflow

1) In n8n UI: import `infra/n8n-workflow.json`.
2) Configure an SMTP credential for the "Send Alert Email" node.
3) Ensure n8n container has env vars:
   - `BAKLIZ_API_BASE_URL` (default: `http://backend:8000`)
   - `BAKLIZ_ADMIN_USERNAME`, `BAKLIZ_ADMIN_PASSWORD`

These are already wired in `infra/docker-compose.yml` (mapped from backend `ADMIN_USERNAME/ADMIN_PASSWORD`).
