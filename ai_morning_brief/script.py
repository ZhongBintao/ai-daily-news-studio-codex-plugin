from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date
from typing import Any, Iterable, Mapping

from .config import CATEGORY_LABELS, CATEGORY_ORDER, DEFAULT_SHOW_NAME, DEFAULT_SHOW_NAME_EN
from .models import ScriptSegment, SelectionResult, SourceItem


_SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?", re.UNICODE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?(?:\s?[万亿千万百十%％倍个名家月日年美元港元欧元元桶/日]+)?", re.UNICODE)
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#/-]*")
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?\b")
_WEEKDAY_NAMES = "一二三四五六日"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ").strip())


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.findall(_clean(text)) if part.strip()]


def _without_terminal_punctuation(text: str) -> str:
    return text.rstrip("。！？!?；;，, ")


def _dedupe_fragments(title: str, summary: str | None) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = [{"source_field": "title", "source_text": _clean(title)}]
    if summary:
        candidates.extend({"source_field": "summary", "source_text": _clean(sentence)} for sentence in _sentences(summary))
    fragments: list[dict[str, str]] = []
    seen_normalized: set[str] = set()
    title_core = _without_terminal_punctuation(_clean(title))
    for fragment in candidates:
        text = fragment["source_text"]
        normalized = _without_terminal_punctuation(text).replace(" ", "")
        if not normalized or normalized in seen_normalized:
            continue
        if fragment["source_field"] == "summary" and normalized == title_core.replace(" ", ""):
            continue
        seen_normalized.add(normalized)
        fragments.append(fragment)
    return fragments


def build_broadcast(item: SourceItem, *, maximum_chars: int = 155) -> tuple[str, tuple[dict[str, str], ...]]:
    fragments = _dedupe_fragments(item.title, item.summary)
    if not fragments:
        fragments = [{"source_field": "title", "source_text": _clean(item.title)}]
    chosen: list[dict[str, str]] = []
    total = 0
    for fragment in fragments:
        text = fragment["source_text"]
        extra = len(text) + (1 if chosen else 0)
        if chosen and total + extra > maximum_chars:
            break
        chosen.append(fragment)
        total += extra
        if len(chosen) >= 3:
            break
    broadcast = "。".join(_without_terminal_punctuation(part["source_text"]) for part in chosen) + "。"
    return broadcast, tuple(chosen)


def screen_points(item: SourceItem, fragments: Iterable[Mapping[str, str]]) -> tuple[str, ...]:
    clauses: list[str] = []
    for fragment in fragments:
        for clause in re.split(r"[，,。；;]", fragment["source_text"]):
            clause = clause.strip()
            if clause and clause not in clauses:
                clauses.append(clause)
    with_numbers = [clause for clause in clauses if _NUMBER_RE.search(clause) or _DATE_RE.search(clause)]
    ordered = with_numbers + [clause for clause in clauses if clause not in with_numbers]
    return tuple(ordered[:5])


def _overview_groups(items: Iterable[SourceItem]) -> tuple[dict[str, Any], ...]:
    grouped: "OrderedDict[str, list[dict[str, str]]]" = OrderedDict()
    for item in items:
        category = item.category or "other"
        grouped.setdefault(category, []).append({"item_id": item.item_id, "title": _clean(item.title)})
    ordered_categories = [category for category in CATEGORY_ORDER if category in grouped]
    ordered_categories.extend(category for category in grouped if category not in ordered_categories)
    return tuple(
        {
            "category": category,
            "label": CATEGORY_LABELS.get(category, category),
            "items": list(grouped[category]),
        }
        for category in ordered_categories
    )


def layout_for(item: SourceItem, broadcast: str) -> str:
    category = item.category or "other"
    if _NUMBER_RE.search(broadcast):
        return "numeric-spotlight"
    if _DATE_RE.search(broadcast):
        return "timeline"
    if category == "paper":
        return "research-abstract"
    if category in {"ai-models", "ai-products"}:
        return "launch-card"
    return "headline-stack"


def build_script(selection: SelectionResult, *, run_date: date, show_name: str = DEFAULT_SHOW_NAME) -> dict[str, Any]:
    segments: list[ScriptSegment] = []
    for index, item in enumerate(selection.items, 1):
        broadcast, fragments = build_broadcast(item)
        segments.append(
            ScriptSegment(
                segment_id=f"story-{index:02d}",
                kind="news",
                title=item.title,
                category=item.category or "other",
                source_item_id=item.item_id,
                source_name=item.source_name,
                broadcast_text=broadcast,
                source_fragments=fragments,
                screen_points=screen_points(item, fragments),
                layout_type=layout_for(item, broadcast),
                aihot_url=item.aihot_url,
                original_url=item.original_url,
            )
        )
    intro = ScriptSegment(
        segment_id="intro",
        kind="intro",
        title=show_name,
        category="开场",
        source_item_id=None,
        source_name=None,
        broadcast_text=(
            f"各位观众早上好，今天是{run_date.month}月{run_date.day}日，"
            f"星期{_WEEKDAY_NAMES[run_date.weekday()]}，欢迎收看今天的AI早报，下面是详细报道"
        ),
        source_fragments=tuple(),
        screen_points=tuple(),
        layout_type="intro",
    )
    overview = ScriptSegment(
        segment_id="overview",
        kind="overview",
        title=f"{run_date.isoformat()} 资讯概览",
        category="overview",
        source_item_id=None,
        source_name=None,
        broadcast_text="首先来看今日资讯概览，请看屏幕上的主要内容。",
        source_fragments=tuple(),
        screen_points=tuple(),
        layout_type="overview",
        screen_groups=_overview_groups(selection.items),
        minimum_duration_seconds=12.0,
    )
    outro = ScriptSegment(
        segment_id="outro",
        kind="outro",
        title="明天见",
        category="结尾",
        source_item_id=None,
        source_name=None,
        broadcast_text="今天的AI资讯播送完了，我们明天见",
        source_fragments=tuple(),
        screen_points=tuple(),
        layout_type="outro",
    )
    ordered = [intro, overview, *segments, outro]
    return {
        "version": "1.0",
        "show_name": show_name,
        "show_name_en": DEFAULT_SHOW_NAME_EN,
        "date": run_date.isoformat(),
        "mode": selection.mode,
        "title": f"{run_date.isoformat()} {show_name}",
        "opening": {"duration_seconds": 4.0, "style": "editorial-reveal", "hero_segment_id": overview.segment_id},
        "segments": [segment.to_dict() for segment in ordered],
        "source_item_ids": [item.item_id for item in selection.items],
        "category_counts": selection.category_counts,
        "selection_reason": selection.reason,
        "editorial_policy": "factual-only; source title and summary fragments; no independent analysis",
    }


def _tokens(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text)) | set(_ASCII_TOKEN_RE.findall(text))


def validate_script(script: Mapping[str, Any], source_items: Mapping[str, SourceItem]) -> list[str]:
    errors: list[str] = []
    segments = script.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["script has no segments"]
    for raw in segments:
        if not isinstance(raw, Mapping):
            errors.append("script contains a non-object segment")
            continue
        if raw.get("kind") != "news":
            continue
        item_id = str(raw.get("source_item_id") or "")
        item = source_items.get(item_id)
        if item is None:
            errors.append(f"segment {raw.get('id')} references unknown source item {item_id}")
            continue
        source_text_raw = item.source_text()
        source_text = re.sub(r"\s+", "", source_text_raw)
        fragments = raw.get("source_fragments") or []
        if not fragments:
            errors.append(f"segment {raw.get('id')} has no source fragments")
        for fragment in fragments:
            if not isinstance(fragment, Mapping) or not fragment.get("source_text"):
                errors.append(f"segment {raw.get('id')} has malformed source fragment")
                continue
            fragment_text = str(fragment["source_text"])
            if re.sub(r"\s+", "", fragment_text) not in source_text:
                errors.append(f"segment {raw.get('id')} contains a fragment not found in its source")
        broadcast = str(raw.get("broadcast_text") or "")
        if not broadcast:
            errors.append(f"segment {raw.get('id')} has empty broadcast text")
        source_tokens = _tokens(source_text_raw)
        extra_tokens = _tokens(broadcast) - source_tokens
        if extra_tokens:
            errors.append(f"segment {raw.get('id')} adds unsupported tokens: {sorted(extra_tokens)}")
    return errors


def build_fact_ledger(script: Mapping[str, Any], source_items: Mapping[str, SourceItem]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for segment in script.get("segments", []):
        if segment.get("kind") != "news":
            continue
        item = source_items.get(str(segment.get("source_item_id")))
        if item is None:
            continue
        records.append(
            {
                "segment_id": segment["id"],
                "source_item_id": item.item_id,
                "source_name": item.source_name,
                "source_urls": {"aihot": item.aihot_url, "original": item.original_url},
                "source_fields": {"title": item.title, "summary": item.summary},
                "claims": list(segment.get("source_fragments", [])),
                "validation": "exact source fragments only; no independent analysis",
            }
        )
    return {"version": "1.0", "records": records}
