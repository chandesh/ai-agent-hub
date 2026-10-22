"""GitHub Search parser with page pagination and rate-limit backoff."""

import asyncio
import os
import random

import httpx

from app.scripts.parsers.base import BaseParser


class GitHubSearchParser(BaseParser):
    """Fetches GitHub repository search results one page at a time."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.rate_limit = config.get("rate_limit", {})
        self._current_page: int | None = None
        self.client = httpx.AsyncClient(
            timeout=config.get("timeout_sec", 30.0),
            headers=self._headers(config.get("auth")),
        )

    @staticmethod
    def _headers(auth: dict | None) -> dict:
        headers = {"Accept": "application/vnd.github+json"}
        if auth and auth.get("type") == "bearer":
            token = os.getenv(auth.get("env_var", "GITHUB_TOKEN"), "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    async def fetch_page(self, page: int | None) -> dict:
        params = dict(self.config.get("params", {}))
        page = page or 1
        params["page"] = page
        max_retries = self.rate_limit.get("max_retries", 3)
        base_delay = self.rate_limit.get("base_delay_sec", 2)

        for attempt in range(max_retries + 1):
            response = await self.client.get(self.config["endpoint"], params=params)
            remaining = response.headers.get("X-RateLimit-Remaining")
            if response.status_code == 429 or (
                response.status_code == 403 and remaining == "0"
            ):
                if attempt >= max_retries:
                    break
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
                continue

            response.raise_for_status()
            self._current_page = page
            return response.json()

        raise RuntimeError("Max retries exceeded")

    def has_next_page(self, response: dict) -> bool:
        return len(response.get("items", [])) > 0

    def next_page_token(self, response: dict) -> int:
        return (self._current_page or 1) + 1

    async def close(self) -> None:
        await self.client.aclose()
