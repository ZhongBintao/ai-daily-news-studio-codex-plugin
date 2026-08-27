from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import SelectionResult, SourceItem


def select_items(
    items: Iterable[SourceItem],
    *,
    max_items: int = 8,
    minimum_items: int = 3,
    max_per_category: int = 2,
) -> SelectionResult:
    """Select in API order while preventing one category from taking over."""

    unique: list[SourceItem] = []
    seen: set[str] = set()
    for item in items:
        if not item.selected or not item.title.strip() or item.item_id in seen:
            continue
        seen.add(item.item_id)
        unique.append(item)

    selected: list[SourceItem] = []
    counts: Counter[str] = Counter()
    for item in unique:
        category = item.category or "other"
        if counts[category] >= max_per_category:
            continue
        selected.append(item)
        counts[category] += 1
        if len(selected) >= max_items:
            break
    if len(selected) < max_items:
        selected_ids = {item.item_id for item in selected}
        for item in unique:
            if item.item_id in selected_ids:
                continue
            selected.append(item)
            counts[item.category or "other"] += 1
            if len(selected) >= max_items:
                break

    if len(selected) < minimum_items:
        mode = "failure"
        reason = f"only {len(selected)} eligible AIHOT items; at least {minimum_items} required"
    elif len(selected) < 6:
        mode = "short"
        reason = f"low-volume day with {len(selected)} eligible AIHOT items"
    else:
        mode = "normal"
        reason = None
    return SelectionResult(
        items=tuple(selected),
        mode=mode,
        category_counts=dict(sorted(counts.items())),
        eligible_count=len(unique),
        reason=reason,
    )

