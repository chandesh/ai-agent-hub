"""Generic API parser with cursor pagination (MCP Registry)."""

import os

import httpx

from app.scripts.parsers.base import BaseParser


class APIParser(BaseParser):
    """Fetches pages from a JSON API using a cursor from the response."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.expected_schema = config.get("expected_schema_url")
        self.client = httpx.AsyncClient(
            timeout=config.get("timeout_sec", 30.0),
            headers=self._auth_headers(config.get("auth")),
        )

    @staticmethod
    def _auth_headers(auth: dict | None) -> dict:
        if not auth:
            return {}
        if auth.get("type") == "bearer":
            token = os.getenv(auth.get("env_var", ""), "")
            return {"Authorization": f"Bearer {token}"} if token else {}
        return {}

    async def fetch_page(self, cursor: str | None) -> dict:
        params = dict(self.config.get("params", {}))
        if cursor:
            params["cursor"] = cursor
        response = await self.client.get(self.config["endpoint"], params=params)
        response.raise_for_status()
        return response.json()

    def has_next_page(self, response: dict) -> bool:
        return bool(response.get("metadata", {}).get("nextCursor"))

    def next_page_token(self, response: dict) -> str | None:
        return response.get("metadata", {}).get("nextCursor")

    def _check_schema(self, item: dict) -> bool:
        if not self.expected_schema:
            return True
        return item.get("server", {}).get("$schema") == self.expected_schema

    async def close(self) -> None:
        await self.client.aclose()
