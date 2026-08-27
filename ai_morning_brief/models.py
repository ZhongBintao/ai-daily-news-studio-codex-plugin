from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class SourceValidationError(ValueError):
    """Raised when an AIHOT item does not satisfy the public v1 contract."""


@dataclass(frozen=True)
class SourceItem:
    item_id: str
    title: str
    summary: str | None
    original_title: str | None
    category: str | None
    source_name: str
    aihot_url: str
    original_url: str
    published_at: str | None
    discovered_at: str
    score: float | int | None
    reason: str | None
    selected: bool
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceItem":
        required = ("id", "title", "source", "links", "discoveredAt", "selected")
        missing = [key for key in required if key not in value]
        if missing:
            raise SourceValidationError(f"AIHOT item missing keys: {', '.join(missing)}")
        source = value.get("source")
        links = value.get("links")
        if not isinstance(source, Mapping) or not source.get("name"):
            raise SourceValidationError(f"AIHOT item {value.get('id')!r} has invalid source")
        if not isinstance(links, Mapping) or not links.get("aihot") or not links.get("original"):
            raise SourceValidationError(f"AIHOT item {value.get('id')!r} has invalid links")
        title = str(value.get("title") or "").strip()
        discovered = str(value.get("discoveredAt") or "").strip()
        if not title or not discovered:
            raise SourceValidationError(f"AIHOT item {value.get('id')!r} has empty title/time")
        return cls(
            item_id=str(value["id"]),
            title=title,
            summary=str(value["summary"]).strip() if value.get("summary") else None,
            original_title=str(value["originalTitle"]).strip() if value.get("originalTitle") else None,
            category=str(value["category"]).strip() if value.get("category") else None,
            source_name=str(source["name"]).strip(),
            aihot_url=str(links["aihot"]).strip(),
            original_url=str(links["original"]).strip(),
            published_at=str(value["publishedAt"]).strip() if value.get("publishedAt") else None,
            discovered_at=discovered,
            score=value.get("score"),
            reason=str(value["reason"]).strip() if value.get("reason") else None,
            selected=bool(value["selected"]),
            raw=dict(value),
        )

    def source_text(self) -> str:
        return "\n".join(part for part in (self.title, self.summary or "") if part).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "title": self.title,
            "summary": self.summary,
            "originalTitle": self.original_title,
            "category": self.category,
            "source": {"name": self.source_name},
            "links": {"aihot": self.aihot_url, "original": self.original_url},
            "publishedAt": self.published_at,
            "discoveredAt": self.discovered_at,
            "score": self.score,
            "selected": self.selected,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SelectionResult:
    items: tuple[SourceItem, ...]
    mode: str
    category_counts: dict[str, int]
    eligible_count: int
    reason: str | None = None


@dataclass(frozen=True)
class ScriptSegment:
    segment_id: str
    kind: str
    title: str
    category: str
    source_item_id: str | None
    source_name: str | None
    broadcast_text: str
    source_fragments: tuple[dict[str, str], ...]
    screen_points: tuple[str, ...]
    layout_type: str
    aihot_url: str | None = None
    original_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.segment_id,
            "kind": self.kind,
            "title": self.title,
            "short_title": self.title,
            "category": self.category,
            "section": self.category,
            "source_item_id": self.source_item_id,
            "source_name": self.source_name,
            "broadcast_text": self.broadcast_text,
            "source_fragments": list(self.source_fragments),
            "screen_points": list(self.screen_points),
            "layout_type": self.layout_type,
            "aihot_url": self.aihot_url,
            "original_url": self.original_url,
            "delivery_cues": {"register": "factual", "energy": "clear", "pause_after_title": True},
        }

