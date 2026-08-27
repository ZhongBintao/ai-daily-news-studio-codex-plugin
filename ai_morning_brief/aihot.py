from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config import DEFAULT_AIHOT_URL
from .models import SourceItem, SourceValidationError


class AIHotError(RuntimeError):
    """A safe, user-facing AIHOT retrieval or contract error."""


@dataclass(frozen=True)
class AIHotResponse:
    url: str
    payload: dict[str, Any]
    items: tuple[SourceItem, ...]
    etag: str | None
    from_cache: bool


class AIHotClient:
    """Anonymous read-only client for the public AIHOT v1 items endpoint."""

    def __init__(self, *, base_url: str = DEFAULT_AIHOT_URL, cache_dir: Path | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.user_agent = "ai-signal-morning-brief/0.1 (+https://aihot.virxact.com/aihot-skill/)"

    def fetch_selected_24h(self, *, limit: int = 20, force: bool = False) -> AIHotResponse:
        if not 1 <= limit <= 100:
            raise ValueError("AIHOT limit must be between 1 and 100")
        query = urllib.parse.urlencode({"mode": "selected", "window": "24h", "limit": str(limit)})
        url = f"{self.base_url}?{query}"
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        body_path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        etag_path = self.cache_dir / f"{key}.etag" if self.cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        old_etag = etag_path.read_text(encoding="utf-8").strip() if etag_path and etag_path.is_file() else ""
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if old_etag and not force:
            headers["If-None-Match"] = old_etag
        request = urllib.request.Request(url, headers=headers, method="GET")
        from_cache = False
        etag = old_etag or None
        raw_payload: bytes
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw_payload = response.read()
                etag = response.headers.get("ETag") or etag
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and body_path and body_path.is_file():
                raw_payload = body_path.read_bytes()
                from_cache = True
            else:
                detail = ""
                try:
                    detail = exc.read(300).decode("utf-8", errors="replace")
                except Exception:
                    pass
                raise AIHotError(f"AIHOT request failed with HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AIHotError(f"AIHOT request failed: {exc}") from exc

        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIHotError("AIHOT returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AIHotError("AIHOT returned a non-object response")
        query_shape = payload.get("query")
        if not isinstance(query_shape, Mapping) or query_shape.get("mode") != "selected" or query_shape.get("window") != "24h":
            raise AIHotError("AIHOT response did not match the selected 24h contract")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise AIHotError("AIHOT response has no items list")
        try:
            items = tuple(SourceItem.from_mapping(item) for item in raw_items if isinstance(item, Mapping))
        except SourceValidationError as exc:
            raise AIHotError(str(exc)) from exc
        if body_path and not from_cache:
            body_path.write_bytes(raw_payload)
            if etag_path and etag:
                etag_path.write_text(etag, encoding="utf-8")
        return AIHotResponse(url=url, payload=payload, items=items, etag=etag, from_cache=from_cache)


def load_fixture(path: Path) -> AIHotResponse:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AIHotError(f"fixture is not an object: {path}")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AIHotError(f"fixture has no items list: {path}")
    try:
        items = tuple(SourceItem.from_mapping(item) for item in raw_items if isinstance(item, Mapping))
    except SourceValidationError as exc:
        raise AIHotError(str(exc)) from exc
    return AIHotResponse(
        url=f"fixture://{path.name}",
        payload=payload,
        items=items,
        etag=None,
        from_cache=True,
    )

