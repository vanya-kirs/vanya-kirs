import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

LIMIT = 5


class BotApiClient:
    """HTTP client that communicates with the FastAPI backend."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.API_BASE_URL
        self._owner_telegram_id = settings.OWNER_TELEGRAM_ID
        self._bot_token = settings.BOT_TOKEN
        self._token: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        if not self._owner_telegram_id or not self._bot_token:
            logger.warning("OWNER_TELEGRAM_ID/BOT_TOKEN not set — requests will be unauthenticated")
            return
        try:
            resp = await self._client.post(
                "/api/v1/auth/bot",
                json={"telegram_id": self._owner_telegram_id, "bot_token": self._bot_token},
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
            logger.info("BotApiClient authenticated successfully")
        except Exception as exc:
            logger.error("BotApiClient login failed: %s", exc)

    async def _ensure_auth(self) -> None:
        if self._token is None:
            await self._login()

    def _headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        await self._ensure_auth()
        try:
            resp = await self._client.request(
                method, path, headers=self._headers(), **kwargs
            )
            if resp.status_code == 401:
                # Token expired — re-login once
                self._token = None
                await self._login()
                resp = await self._client.request(
                    method, path, headers=self._headers(), **kwargs
                )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        except httpx.ConnectError:
            logger.error("API connection error: %s %s", method, path)
            raise ConnectionError("API недоступен")
        except httpx.HTTPStatusError as exc:
            logger.error("API HTTP error %d: %s %s", exc.response.status_code, method, path)
            raise

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", path, params={k: v for k, v in params.items() if v is not None})

    async def _post(self, path: str, json: dict | None = None) -> Any:
        return await self._request("POST", path, json=json)

    async def _delete(self, path: str) -> Any:
        return await self._request("DELETE", path)

    async def _patch(self, path: str, json: dict) -> Any:
        return await self._request("PATCH", path, json=json)

    async def _get_raw(self, path: str, **params: Any) -> bytes:
        """Returns raw bytes (for CSV download)."""
        await self._ensure_auth()
        resp = await self._client.get(
            path,
            headers=self._headers(),
            params={k: v for k, v in params.items() if v is not None},
        )
        if resp.status_code == 401:
            self._token = None
            await self._login()
            resp = await self._client.get(
                path,
                headers=self._headers(),
                params={k: v for k, v in params.items() if v is not None},
            )
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    async def get_sources(self) -> list[dict]:
        return await self._get("/api/v1/sources") or []

    async def create_source(self, url: str, name: str) -> dict:
        return await self._post("/api/v1/sources", json={"url": url, "name": name})

    async def delete_source(self, source_id: int) -> bool:
        await self._delete(f"/api/v1/sources/{source_id}")
        return True

    async def toggle_source_parsing(self, source_id: int) -> dict:
        return await self._request("PATCH", f"/api/v1/sources/{source_id}/parsing")

    async def validate_source(self, url: str) -> dict:
        return await self._post("/api/v1/sources/validate", json={"url": url})

    async def import_sources(self, items: list[dict]) -> dict:
        return await self._post("/api/v1/sources/import", json={"items": items}) or {}

    # ------------------------------------------------------------------
    # Criteria
    # ------------------------------------------------------------------

    async def get_criteria(self) -> list[dict]:
        return await self._get("/api/v1/criteria") or []

    async def get_active_criteria(self) -> dict | None:
        try:
            return await self._get("/api/v1/criteria/active")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def create_criteria(
        self, name: str, description: str, min_score: int
    ) -> dict:
        return await self._post(
            "/api/v1/criteria",
            json={"name": name, "description": description, "min_score": min_score},
        )

    async def activate_criteria(self, criteria_id: int) -> dict:
        return await self._post(f"/api/v1/criteria/{criteria_id}/activate")

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    async def get_leads(
        self,
        min_score: int | None = None,
        status: str | None = None,
        limit: int = LIMIT,
        offset: int = 0,
    ) -> list[dict]:
        return await self._get(
            "/api/v1/leads",
            min_score=min_score,
            status=status,
            limit=limit,
            offset=offset,
        ) or []

    async def get_leads_count(
        self,
        min_score: int | None = None,
        status: str | None = None,
    ) -> int:
        data = await self._get(
            "/api/v1/leads/count",
            min_score=min_score,
            status=status,
        ) or {}
        return int(data.get("count", 0))

    async def get_lead(self, lead_id: int) -> dict:
        return await self._get(f"/api/v1/leads/{lead_id}")

    async def update_lead_status(self, lead_id: int, status: str) -> dict:
        return await self._patch(
            f"/api/v1/leads/{lead_id}/status", json={"status": status}
        )

    async def export_leads_xlsx(
        self, min_score: int = 40, status: str | None = None
    ) -> bytes:
        return await self._get_raw(
            "/api/v1/leads/export", min_score=min_score, status=status
        )

    # ------------------------------------------------------------------
    # Parse / Score
    # ------------------------------------------------------------------

    async def run_parse(self, source_id: int, limit: int = 200) -> dict:
        return await self._post(
            "/api/v1/parse/run", json={"source_id": source_id, "limit": limit}
        )

    async def run_parse_all(self) -> list[dict]:
        return await self._post("/api/v1/parse/run-all") or []

    async def run_score(self, source_id: int) -> dict:
        return await self._post(f"/api/v1/parse/score/{source_id}")

    async def get_task_status(self, task_id: str) -> dict:
        return await self._get(f"/api/v1/parse/task/{task_id}")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict:
        return await self._get("/api/v1/stats") or {}

    async def get_source_stats(self) -> list[dict]:
        return await self._get("/api/v1/stats/sources") or []

    async def get_discovered_sources(self) -> list[dict]:
        return await self._get("/api/v1/sources/discovered") or []

    async def get_inactive_sources(self) -> list[dict]:
        return await self._get("/api/v1/sources/inactive") or []

    async def trigger_global_search(self) -> dict:
        return await self._post("/api/v1/sources/global-search/trigger") or {}

    async def export_sources_xlsx(self) -> bytes:
        return await self._get_raw("/api/v1/sources/export")

    async def get_rejected_sources(
        self,
        reason: str | None = None,
        min_members: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        return await self._get(
            "/api/v1/sources/rejected",
            reason=reason,
            min_members=min_members,
            limit=limit,
        ) or []

    async def get_rejected_sources_count(
        self,
        reason: str | None = None,
        min_members: int | None = None,
    ) -> int:
        data = await self._get(
            "/api/v1/sources/rejected/count",
            reason=reason,
            min_members=min_members,
        ) or {}
        return int(data.get("count", 0))

    async def export_rejected_sources_xlsx(
        self,
        reason: str | None = None,
        min_members: int | None = None,
    ) -> bytes:
        return await self._get_raw(
            "/api/v1/sources/rejected/export",
            reason=reason,
            min_members=min_members,
        )

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    async def get_profile(self) -> dict:
        return await self._get("/api/v1/profile") or {}

    async def extend_subscription(self) -> dict:
        return await self._post("/api/v1/profile/subscribe")

    async def set_parsing_enabled(self, enabled: bool) -> dict:
        return await self._patch("/api/v1/profile/parsing", json={"enabled": enabled})

    async def set_min_score(self, score: int) -> dict:
        return await self._patch("/api/v1/criteria/active/min-score", json={"min_score": score})
