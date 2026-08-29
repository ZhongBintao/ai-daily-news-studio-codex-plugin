from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from .media import write_json
from .config import CATEGORY_LABELS, CATEGORY_ORDER


TEMPLATE_PATH = Path(__file__).resolve().parent / "template" / "index.html"

_HIGHLIGHT_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#/-]*|\d+(?:\.\d+)?%?")


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _highlight_text(value: Any) -> str:
    """Escape untrusted text while highlighting readable product/data tokens."""

    text = str(value or "")
    parts: list[str] = []
    cursor = 0
    for match in _HIGHLIGHT_RE.finditer(text):
        parts.append(_esc(text[cursor:match.start()]))
        parts.append(f'<mark class="token-highlight">{_esc(match.group(0))}</mark>')
        cursor = match.end()
    parts.append(_esc(text[cursor:]))
    return "".join(parts)


def _point_heading(point: str, *, index: int, category: str) -> str:
    if re.search(r"\d|%|价格|投资|参数|版本", point):
        return "关键数据"
    if re.search(r"研究|论文|评测|方法", point):
        return "研究方法"
    if re.search(r"调试|调用|部署|工具|开发", point):
        return "开发实践"
    if re.search(r"开放|上线|发布|推出|推出|新增", point):
        return "核心进展"
    category_headings = {
        "ai-models": "模型能力",
        "ai-products": "产品进展",
        "industry": "行业观察",
        "paper": "技术洞察",
        "tip": "实践建议",
        "other": "后续动态",
    }
    return category_headings.get(category, ("重点信息", "补充信息")[index % 2])


def _icon_svg(kind: str) -> str:
    icons = {
        "spark": '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M24 4l3.6 13.2L41 21l-13.4 3.8L24 38l-3.6-13.2L7 21l13.4-3.8L24 4Z"/><path d="M39 32l1.6 5.4L46 39l-5.4 1.6L39 46l-1.6-5.4L32 39l5.4-1.6L39 32Z"/></svg>',
        "bars": '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M9 39V25h7v14H9Zm12 0V12h7v27h-7Zm12 0V6h7v33h-7Z"/></svg>',
        "chart": '<svg viewBox="0 0 48 48" aria-hidden="true"><rect x="7" y="7" width="34" height="34" rx="3"/><path d="M14 33v-8M23 33V15M32 33v-13M13 19h9M22 24h10"/></svg>',
        "clock": '<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="25" r="14"/><path d="M24 17v9l6 4M18 7h12M24 7v4"/></svg>',
        "code": '<svg viewBox="0 0 48 48" aria-hidden="true"><path d="m19 14-10 11 10 11M29 14l10 11-10 11M27 9l-6 32"/></svg>',
    }
    return icons.get(kind, icons["spark"])


def _point_icon(point: str, index: int) -> str:
    if re.search(r"\d|%|价格|投资|参数|版本", point):
        return "bars"
    if re.search(r"研究|论文|评测|方法", point):
        return "chart"
    if re.search(r"日期|月|日|截止|时间|生效", point):
        return "clock"
    if re.search(r"开发|代码|工具|部署|接口", point):
        return "code"
    return ("spark", "chart", "code")[index % 3]


def _points_markup(points: list[str], *, category: str) -> str:
    if not points:
        return '<div class="point-grid"><div class="point-card empty"><p>重点信息正在播报</p></div></div>'
    colors = ("terracotta", "amber", "teal", "red", "ochre")
    cards: list[str] = []
    visible_points = points[:5]
    for index, point in enumerate(visible_points):
        icon = _icon_svg(_point_icon(point, index))
        heading = _point_heading(point, index=index, category=category)
        cards.append(
            f'<article class="point-card {colors[index % len(colors)]}"><div class="point-icon">{icon}</div>'
            f'<div class="point-copy"><h3>{_esc(heading)}</h3><p>{_highlight_text(point)}</p></div></article>'
        )
    return f'<div class="point-grid count-{len(visible_points)}">{"".join(cards)}</div>'


def _overview_markup(groups: list[Mapping[str, Any]]) -> str:
    cards: list[str] = []
    accents = ("terracotta", "amber", "teal", "red", "ochre")
    for index, group in enumerate(groups):
        category = str(group.get("category") or "other")
        label = str(group.get("label") or CATEGORY_LABELS.get(category, category))
        items = list(group.get("items") or [])
        bullets = "".join(f'<li>{_esc(item.get("title"))}</li>' for item in items if isinstance(item, Mapping))
        cards.append(
            f'<article class="overview-card {accents[index % len(accents)]}"><div class="overview-card-head">'
            f'<div class="overview-icon">{_icon_svg(("spark", "bars", "chart", "clock", "code")[index % 5])}</div>'
            f'<h2>{_esc(label)}</h2></div><ul>{bullets}</ul></article>'
        )
    if not cards:
        return '<div class="overview-grid"><article class="overview-card empty"><p>今日暂无可播报资讯</p></article></div>'
    return '<div class="overview-grid">' + "".join(cards) + "</div>"


def _scene_markup(segment: Mapping[str, Any], *, index: int, start: float, duration: float) -> str:
    kind = str(segment.get("kind") or "news")
    segment_id = _safe_id(str(segment.get("id") or f"scene-{index:02d}"))
    if kind == "intro":
        return (
            f'<section id="scene-{segment_id}" class="scene intro-scene" data-kind="intro" '
            f'data-category="intro"><div class="scene-inner intro-inner"><div class="intro-orbit"></div><div class="intro-content">'
            f'<div class="intro-rule"></div><p class="intro-kicker">AI DAILY NEWS / 每日编辑部</p><h1>{_esc(segment.get("title") or "AI每日早报")}</h1>'
            f'<p class="intro-english">AI Daily News</p></div></div></section>'
        )
    if kind == "overview":
        groups = [group for group in (segment.get("screen_groups") or []) if isinstance(group, Mapping)]
        return (
            f'<section id="scene-{segment_id}" class="scene overview-scene" data-kind="overview" data-category="overview">'
            f'<div class="scene-inner overview-inner"><div class="overview-heading"><p class="section-kicker">AI DAILY NEWS / 今日编辑室</p>'
            f'<h1>{_esc(segment.get("title") or "资讯概览")}</h1><p class="overview-subtitle">屏幕上是今天的主要内容</p></div>'
            f'{_overview_markup(groups)}</div></section>'
        )
    if kind == "outro":
        return (
            f'<section id="scene-{segment_id}" class="scene outro-scene" data-kind="outro" '
            f'data-category="outro"><div class="scene-inner outro-inner"><div class="outro-content"><div class="outro-mark"></div>'
            f'<h1>明天见</h1><p>今天的 AI 资讯播送完毕</p><span class="outro-english">AI Daily News</span></div></div></section>'
        )
    category = str(segment.get("category") or "other")
    layout = _esc(segment.get("layout_type") or "headline-stack")
    points = segment.get("screen_points") or []
    return (
        f'<section id="scene-{segment_id}" class="scene news-scene layout-{layout}" data-kind="news" '
        f'data-category="{_esc(category)}"><div class="scene-inner detail-inner"><div class="detail-heading"><p class="section-kicker">{_esc(CATEGORY_LABELS.get(category, category))} / AI DAILY NEWS</p>'
        f'<h2>{_esc(segment.get("title"))}</h2></div><div class="detail-visual">{_points_markup([str(point) for point in points], category=category)}<div class="signal-sweep"></div></div></div>'
        f'</section>'
    )


def _caption_markup(cues: list[Mapping[str, Any]]) -> str:
    return "".join(
        f'<div class="clip caption" id="caption-{index:04d}" data-start="{float(cue.get("start", 0)):.3f}" '
        f'data-duration="{max(0.12, float(cue.get("end", 0)) - float(cue.get("start", 0))):.3f}" '
        f'data-track-index="{200 + index}" aria-hidden="true">{_esc(cue.get("text"))}</div>'
        for index, cue in enumerate(cues, 1)
    )


def materialize(project_dir: Path, script: Mapping[str, Any], durations: Mapping[str, float], cues: list[Mapping[str, Any]]) -> dict[str, Any]:
    project_dir.mkdir(parents=True, exist_ok=True)
    segments = list(script.get("segments") or [])
    timings: dict[str, dict[str, float]] = {}
    cursor = 0.0
    scene_parts: list[str] = []
    category_slugs: list[str] = []
    for index, segment in enumerate(segments):
        segment_id = str(segment["id"])
        duration = max(0.2, float(durations.get(segment_id, 0.2)))
        timings[segment_id] = {"start": round(cursor, 3), "end": round(cursor + duration, 3), "duration": round(duration, 3)}
        scene_parts.append(_scene_markup(segment, index=index, start=cursor, duration=duration))
        category = str(segment.get("category") or "other")
        if segment.get("kind") == "news" and category not in category_slugs:
            category_slugs.append(category)
        cursor += duration
    total = round(cursor, 3)
    ordered_categories = [category for category in CATEGORY_ORDER if category in category_slugs]
    nav_entries = [("intro", "开场"), ("overview", "要闻")]
    nav_entries.extend((category, CATEGORY_LABELS.get(category, category)) for category in ordered_categories)
    nav_markup = "".join(
        f'<span class="nav-chip" id="nav-chip-{_safe_id(category)}" data-category="{_esc(category)}" data-layout-allow-overlap="true" data-layout-allow-occlusion="true">'
        f'<span class="nav-chip-base">{_esc(label)}</span>'
        f'<span class="nav-chip-active" id="nav-active-{_safe_id(category)}" data-layout-allow-overlap="true" data-layout-allow-occlusion="true" aria-hidden="true">{_esc(label)}</span></span>'
        for category, label in nav_entries
    )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__TOTAL_DURATION__": f"{total:.3f}",
        "__DATE__": _esc(str(script.get("date") or "").replace("-", ".")),
        "__SHOW_NAME__": _esc(script.get("show_name") or "AI每日早报"),
        "__SHOW_NAME_EN__": _esc(script.get("show_name_en") or "AI Daily News"),
        "__NAV_MARKUP__": nav_markup,
        "__SCENES__": "".join(scene_parts),
        "__CAPTIONS__": _caption_markup(cues),
        "__CUE_SPECS__": json.dumps(list(cues), ensure_ascii=False, separators=(",", ":")),
        "__SCENE_SPECS__": json.dumps([
            {"id": f"scene-{_safe_id(str(s['id']))}", **timings[str(s['id'])], "kind": s.get("kind"), "category": s.get("category", "")}
            for s in segments
        ], ensure_ascii=False, separators=(",", ":")),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    unresolved = [token for token in ("__TOTAL_DURATION__", "__DATE__", "__SHOW_NAME__", "__SHOW_NAME_EN__", "__NAV_MARKUP__", "__SCENES__", "__CAPTIONS__", "__CUE_SPECS__", "__SCENE_SPECS__") if token in template]
    if unresolved:
        raise ValueError(f"unresolved template placeholders: {unresolved}")

    workspace = project_dir / "hyperframes"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "index.html").write_text(template, encoding="utf-8")
    write_json(workspace / "hyperframes.json", {"project": project_dir.name, "width": 1920, "height": 1080, "fps": 30, "template_id": "ai-signal-morning-brief", "display_name": "AI每日早报"})
    (workspace / "DESIGN.md").write_text((Path(__file__).resolve().parent / "template" / "DESIGN.md").read_text(encoding="utf-8"), encoding="utf-8")
    for relative in (
        "assets/audio/final-mix.wav",
        "assets/audio/narration-track.wav",
        "assets/audio/transition-whoosh.wav",
        "assets/audio/category-chime.wav",
        "assets/subtitles/subtitles.srt",
        "assets/music/ai-daily-news-bed.ogg",
        "assets/music/README.md",
    ):
        source = project_dir / relative
        destination = workspace / relative
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    scene_plan = {
        "version": "1.0",
        "template_id": "ai-signal-morning-brief",
        "render_runtime": "hyperframes",
        "composition_mode": "templated",
        "scenes": [
            {"id": f"scene-{_safe_id(str(segment['id']))}", "type": segment.get("kind"), "category": segment.get("category"), "layout_type": segment.get("layout_type"), **timings[str(segment["id"])]}
            for segment in segments
        ],
    }
    edit_decisions = {
        "version": "1.0",
        "render_runtime": "hyperframes",
        "composition_mode": "templated",
        "cuts": [{"id": f"cut-{segment['id']}", "source": f"scene-{_safe_id(str(segment['id']))}", "in_seconds": timings[str(segment['id'])]["start"], "out_seconds": timings[str(segment['id'])]["end"], "transition": "editorial-push"} for segment in segments],
        "audio": {
            "narration": "assets/audio/narration-track.wav",
            "music": "assets/music/ai-daily-news-bed.ogg",
            "transition_whoosh": "assets/audio/transition-whoosh.wav",
            "category_chime": "assets/audio/category-chime.wav",
            "mixed": "assets/audio/final-mix.wav",
        },
        "subtitles": {"enabled": True, "source": "assets/subtitles/subtitles.srt", "style": "phrase"},
    }
    asset_manifest = {
        "version": "1.0",
        "assets": [
            {"id": "audio-final-mix", "type": "audio", "path": "assets/audio/final-mix.wav"},
            {"id": "music-bed", "type": "audio", "path": "assets/music/ai-daily-news-bed.ogg", "source": "OpenGameArt: Scaling Up (CC0)", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/"},
            {"id": "transition-whoosh", "type": "audio", "path": "assets/audio/transition-whoosh.wav", "source": "deterministic-local-sfx"},
            {"id": "category-chime", "type": "audio", "path": "assets/audio/category-chime.wav", "source": "deterministic-local-sfx"},
            {"id": "subtitles", "type": "subtitle", "path": "assets/subtitles/subtitles.srt", "cue_count": len(cues)},
        ],
        "metadata": {"template_id": "ai-signal-morning-brief", "display_name": "AI每日早报 / AI Daily News", "no_external_images": True, "no_secrets_in_artifacts": True},
    }
    artifacts = project_dir / "artifacts"
    write_json(artifacts / "scene_plan.json", scene_plan)
    write_json(artifacts / "edit_decisions.json", edit_decisions)
    write_json(artifacts / "asset_manifest.json", asset_manifest)
    write_json(project_dir / "project.json", {"version": "1.0", "project_id": project_dir.name, "title": script.get("title"), "template_id": "ai-signal-morning-brief", "render_runtime": "hyperframes", "composition_mode": "templated", "width": 1920, "height": 1080, "fps": 30, "source_date": script.get("date")})
    return {
        "workspace": workspace,
        "timings": timings,
        "total_duration_seconds": total,
        "scene_count": len(segments),
        "category_names": [CATEGORY_LABELS[category] for category in ordered_categories],
        "category_slugs": ordered_categories,
    }
