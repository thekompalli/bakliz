from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bakliz:bakliz@localhost:5432/bakliz"

    jwt_secret: str = "change-me"
    jwt_issuer: str = "bakliz"
    jwt_audience: str = "bakliz-ui"
    jwt_exp_minutes: int = 60 * 12

    admin_username: str = "admin"
    admin_password: str = "admin"

    linkup_api_key: str | None = None
    # Force demo mode even if LINKUP_API_KEY is configured.
    bakliz_demo_mode: bool = False

    # Email enrichment provider: "linkup" (default) or "zeliq"
    email_enrich_provider: str = "linkup"

    # Linkup contact sourcing retries (bounded; per company, per run).
    # If emails are not found (after trying target contacts), the engine will ask Linkup again for more contacts.
    linkup_contact_search_attempts_per_company: int = 3

    # Zeliq integration (optional)
    zeliq_api_key: str | None = None
    # Public base URL (reachable by Zeliq) used to construct callback URLs.
    zeliq_callback_base_url: str | None = None
    # Shared secret added to callback URL.
    zeliq_webhook_secret: str | None = None
    # If >0, /run will wait up to N seconds for callbacks before falling back.
    zeliq_wait_seconds: int = 0

    graph_client_id: str | None = None
    graph_tenant_id: str | None = None
    graph_auth_mode: str = "device_code"
    graph_token_cache_path: str = "/data/msal_token_cache.bin"

    cors_allow_origins: str = "http://localhost:5173"
