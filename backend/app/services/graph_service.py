from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import msal

from app.core.settings import Settings


@dataclass
class DraftResult:
    message_id: str


class GraphClient:
    def __init__(self) -> None:
        self._settings = Settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.graph_client_id and self._settings.graph_tenant_id)

    def create_draft(self, *, to_email: str, subject: str, body: str) -> DraftResult:
        token = self._get_access_token(scopes=["Mail.ReadWrite"])

        payload = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }

        resp = httpx.post(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        msg_id = data.get("id")
        if not msg_id:
            raise RuntimeError("Graph did not return message id")
        return DraftResult(message_id=msg_id)

    def _get_access_token(self, *, scopes: list[str]) -> str:
        if not self.is_configured:
            raise RuntimeError("Graph client is not configured")

        if self._settings.graph_auth_mode != "device_code":
            raise RuntimeError(f"Unsupported GRAPH_AUTH_MODE: {self._settings.graph_auth_mode}")

        authority = f"https://login.microsoftonline.com/{self._settings.graph_tenant_id}"

        cache = msal.SerializableTokenCache()
        cache_path = Path(self._settings.graph_token_cache_path)
        if cache_path.exists():
            cache.deserialize(cache_path.read_text(encoding="utf-8"))

        app = msal.PublicClientApplication(
            client_id=self._settings.graph_client_id,
            authority=authority,
            token_cache=cache,
        )

        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(scopes=scopes, account=accounts[0])

        if not result:
            flow = app.initiate_device_flow(scopes=scopes)
            if "message" not in flow:
                raise RuntimeError(f"Device flow failed: {flow}")
            # Visible in container logs for the operator.
            print(flow["message"], flush=True)
            result = app.acquire_token_by_device_flow(flow)

        if not result or "access_token" not in result:
            raise RuntimeError(f"Could not acquire Graph token: {result}")

        if cache.has_state_changed:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(cache.serialize(), encoding="utf-8")

        return result["access_token"]
