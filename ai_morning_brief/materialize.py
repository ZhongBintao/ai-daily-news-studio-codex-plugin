from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .media import write_json


TEMPLATE_PATH = Path(__file__).resolve().parent / "template" / "index.html"


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _points_markup(points: list[str]) -> str:
    if not points:
        return '<div class="point-grid"><div class="point-card empty"><span>—</span><small>源文本未提供结构化数字</small></div></div>'
    colors = ("blue", "orange", "teal")
    cards: list[str] = []
    for index, point in enumerate(points[:3]):
        cards.append(
            f'<div class="point-card {colors[index % len(colors)]}"><span class="point-index">0{index + 1}</span><p>{_esc(point)}</p></div>'
        )
    return '<div class="point-grid">' + "".join(cards) + "</div>"


def _scene_markup(segment: Mapping[str, Any], *, index: int, start: float, duration: float, total_stories: int) -> str:
    kind = str(segment.get("kind") or "news")
    segment_id = _safe_id(str(segment.get("id") or f"scene-{index:02d}"))
    if kind == "intro":
        return (
            f'<section id="scene-{segment_id}" class="clip scene intro-scene" data-start="{start:.3f}" data-duration="{duration:.3f}" data-track-index="{10 + index}" '
            f'data-category="开场"><div class="intro-orbit"></div><div class="intro-content">'
            f'<div class="eyebrow">AI SIGNAL / MORNING EDITION</div><h1>AI 信号早报</h1>'
            f'<p>{_esc(segment.get("broadcast_text"))}</p><div class="intro-meta"><span>DAILY EDITION</span><span>{total_stories:02d} STORIES</span></div>'
            f'</div></section>'
        )
    if kind == "outro":
        return (
            f'<section id="scene-{segment_id}" class="clip scene outro-scene" data-start="{start:.3f}" data-duration="{duration:.3f}" data-track-index="{10 + index}" '
            f'data-category="结尾"><div class="outro-content"><div class="eyebrow">SIGNAL CLOSED</div>'
            f'<h1>明早见</h1><p>{_esc(segment.get("broadcast_text"))}</p><div class="outro-line"></div></div></section>'
        )
    category = _esc(segment.get("category") or "AI 动态")
    layout = _esc(segment.get("layout_type") or "headline-stack")
    source_name = _esc(segment.get("source_name") or "AIHOT")
    points = segment.get("screen_points") or []
    return (
        f'<section id="scene-{segment_id}" class="clip scene news-scene layout-{layout}" data-start="{start:.3f}" data-duration="{duration:.3f}" data-track-index="{10 + index}" '
        f'data-category="{category}"><div class="story-top"><div class="story-index">{index:02d}<span>/ {total_stories:02d}</span></div>'
        f'<div class="category-label">{category}</div><div class="live-dot">LIVE SIGNAL</div></div>'
        f'<div class="story-body"><div class="story-copy"><div class="eyebrow">{layout.replace("-", " ").upper()}</div>'
        f'<h2>{_esc(segment.get("title"))}</h2><p class="story-lede">{_esc(segment.get("broadcast_text"))}</p></div>'
        f'<div class="story-visual">{_points_markup([str(point) for point in points])}<div class="signal-sweep"></div></div></div>'
        f'<div class="story-footer"><span class="source-pill">AIHOT 精选 · {source_name}</span><span class="story-hint">原文与链接见本期审计清单</span></div>'
        f'</section>'
    )


def _caption_markup(cues: list[Mapping[str, Any]]) -> str:
    return "".join(
        f'<div class="clip caption" id="caption-{index:04d}" data-start="{float(cue.get("start", 0)):.3f}" '
        f'data-duration="{max(0.12, float(cue.get("end", 0)) - float(cue.get("start", 0))):.3f}" '
        f'data-track-index="{200 + index}" data-layout-allow-occlusion="true">{_esc(cue.get("text"))}</div>'
        for index, cue in enumerate(cues, 1)
    )


def materialize(project_dir: Path, script: Mapping[str, Any], durations: Mapping[str, float], cues: list[Mapping[str, Any]]) -> dict[str, Any]:
    project_dir.mkdir(parents=True, exist_ok=True)
    segments = list(script.get("segments") or [])
    news_count = sum(1 for segment in segments if segment.get("kind") == "news")
    timings: dict[str, dict[str, float]] = {}
    cursor = 0.0
    scene_parts: list[str] = []
    category_names: list[str] = []
    for index, segment in enumerate(segments):
        segment_id = str(segment["id"])
        duration = max(0.2, float(durations.get(segment_id, 0.2)))
        timings[segment_id] = {"start": round(cursor, 3), "end": round(cursor + duration, 3), "duration": round(duration, 3)}
        scene_parts.append(_scene_markup(segment, index=index if segment.get("kind") != "news" else index, start=cursor, duration=duration, total_stories=news_count))
        if segment.get("kind") == "news" and segment.get("category") not in category_names:
            category_names.append(str(segment.get("category")))
        cursor += duration
    total = round(cursor, 3)
    nav_markup = "".join(f'<span class="nav-chip">{_esc(name)}</span>' for name in category_names)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__TOTAL_DURATION__": f"{total:.3f}",
        "__DATE__": _esc(script.get("date")),
        "__NAV_MARKUP__": nav_markup,
        "__SCENES__": "".join(scene_parts),
        "__CAPTIONS__": _caption_markup(cues),
        "__CUE_SPECS__": json.dumps(list(cues), ensure_ascii=False, separators=(",", ":")),
        "__SCENE_SPECS__": json.dumps([{"id": f"scene-{_safe_id(str(s['id']))}", **timings[str(s['id'])], "category": s.get("category", "")} for s in segments], ensure_ascii=False, separators=(",", ":")),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    unresolved = [token for token in ("__TOTAL_DURATION__", "__DATE__", "__NAV_MARKUP__", "__SCENES__", "__CAPTIONS__", "__CUE_SPECS__", "__SCENE_SPECS__") if token in template]
    if unresolved:
        raise ValueError(f"unresolved template placeholders: {unresolved}")

    workspace = project_dir / "hyperframes"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "index.html").write_text(template, encoding="utf-8")
    write_json(workspace / "hyperframes.json", {"project": project_dir.name, "width": 1920, "height": 1080, "fps": 30, "template_id": "ai-signal-morning-brief"})
    (workspace / "DESIGN.md").write_text((Path(__file__).resolve().parent / "template" / "DESIGN.md").read_text(encoding="utf-8"), encoding="utf-8")
    for relative in ("assets/audio/final-mix.wav", "assets/subtitles/subtitles.srt"):
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
        "cuts": [{"id": f"cut-{segment['id']}", "source": f"scene-{_safe_id(str(segment['id']))}", "in_seconds": timings[str(segment['id'])]["start"], "out_seconds": timings[str(segment['id'])]["end"], "transition": "signal-wipe"} for segment in segments],
        "audio": {"narration": "assets/audio/narration-track.wav", "music": "assets/music/procedural-morning-bed.wav", "mixed": "assets/audio/final-mix.wav"},
        "subtitles": {"enabled": True, "source": "assets/subtitles/subtitles.srt", "style": "phrase"},
    }
    asset_manifest = {
        "version": "1.0",
        "assets": [
            {"id": "audio-final-mix", "type": "audio", "path": "assets/audio/final-mix.wav"},
            {"id": "subtitles", "type": "subtitle", "path": "assets/subtitles/subtitles.srt", "cue_count": len(cues)},
        ],
        "metadata": {"template_id": "ai-signal-morning-brief", "no_external_images": True, "no_secrets_in_artifacts": True},
    }
    artifacts = project_dir / "artifacts"
    write_json(artifacts / "scene_plan.json", scene_plan)
    write_json(artifacts / "edit_decisions.json", edit_decisions)
    write_json(artifacts / "asset_manifest.json", asset_manifest)
    write_json(project_dir / "project.json", {"version": "1.0", "project_id": project_dir.name, "title": script.get("title"), "template_id": "ai-signal-morning-brief", "render_runtime": "hyperframes", "composition_mode": "templated", "width": 1920, "height": 1080, "fps": 30, "source_date": script.get("date")})
    return {"workspace": workspace, "timings": timings, "total_duration_seconds": total, "scene_count": len(segments), "category_names": category_names}
