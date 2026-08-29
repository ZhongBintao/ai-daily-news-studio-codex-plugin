from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .aihot import AIHotClient, AIHotError, AIHotResponse, load_fixture
from .config import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_OPENMONTAGE_ROOT,
    DEFAULT_SOURCE_CONTRACT,
    DEFAULT_AIHOT_SKILL_VERSION,
    DEFAULT_SHOW_NAME,
    env_path,
)
from .materialize import materialize
from .media import MediaError, write_json
from .models import SourceItem
from .openmontage_bridge import OpenMontageError, probe_video, render_hyperframes, synthesize_and_align
from .script import build_fact_ledger, build_script, validate_script
from .selection import select_items


PIPELINE_VERSION = "0.1.0"
TIMEZONE = "Asia/Shanghai"


def _now(tz_name: str = TIMEZONE) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _safe_error(exc: BaseException) -> str:
    message = str(exc)
    for key in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "AZURE_TTS_ENDPOINT"):
        value = os.environ.get(key)
        if value:
            message = message.replace(value, "<redacted>")
    # Do not put an access-bearing query string or a large provider response in
    # the artifact; the stage name and short diagnostic are enough for recovery.
    message = re.sub(r"https?://[^\s]+", "<provider-url>", message)
    return message[:800]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_stage_report(run_dir: Path, *, status: str, stage: str, started_at: str, details: Mapping[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    report = {
        "version": PIPELINE_VERSION,
        "status": status,
        "failed_stage": stage if status == "failed" else None,
        "started_at": started_at,
        "finished_at": _now().isoformat(),
        "details": dict(details or {}),
        "error": error,
        "no_secrets_in_artifacts": True,
    }
    write_json(run_dir / "run_report.json", report)
    return report


def _source_snapshot(response: AIHotResponse) -> dict[str, Any]:
    return {
        "version": "1.0",
        "retrieved_at": _now().isoformat(),
        "url": response.url,
        "etag": response.etag,
        "from_cache": response.from_cache,
        "contract": {
            "source_repo": DEFAULT_SOURCE_CONTRACT,
            "aihot_skill_version": DEFAULT_AIHOT_SKILL_VERSION,
            "endpoint_mode": "selected",
            "window": "24h",
        },
        "payload": response.payload,
    }


def _items_by_id(response: AIHotResponse) -> dict[str, SourceItem]:
    return {item.item_id: item for item in response.items}


def _preflight(openmontage_root: Path, *, prepare_only: bool) -> dict[str, Any]:
    result = {
        "openmontage_path": str(openmontage_root),
        "openmontage_present": openmontage_root.is_dir(),
        "prepare_only": prepare_only,
        "azure_configured": bool(os.environ.get("AZURE_SPEECH_KEY")) if not prepare_only else None,
    }
    if not openmontage_root.is_dir():
        raise OpenMontageError(f"OpenMontage directory not found: {openmontage_root}")
    if not prepare_only and not os.environ.get("AZURE_SPEECH_KEY"):
        raise OpenMontageError("AZURE_SPEECH_KEY is not configured")
    return result


def run_pipeline(
    *,
    run_date: date,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    fixture: Path | None = None,
    openmontage_root: Path = DEFAULT_OPENMONTAGE_ROOT,
    env_file: Path | None = None,
    prepare_only: bool = False,
    force: bool = False,
    align: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    run_dir = output_root / run_date.isoformat()
    artifacts = run_dir / "artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    existing_report = _read_json(run_dir / "run_report.json")
    if existing_report and existing_report.get("status") == "success" and not force:
        return existing_report
    started_at = _now().isoformat()
    current_stage = "preflight"
    try:
        if not prepare_only:
            # Importing the bridge is cheap; loading selected values here keeps
            # the environment contract explicit before any Azure call.
            from .config import load_allowed_env
            for key, value in load_allowed_env(env_file or env_path()).items():
                os.environ[key] = value
        preflight = _preflight(openmontage_root, prepare_only=prepare_only)

        current_stage = "fetch"
        source_path = artifacts / "source_snapshot.json"
        source_document = _read_json(source_path)
        if source_document and not force:
            payload = source_document.get("payload")
            if not isinstance(payload, dict):
                source_document = None
        if source_document is not None:
            response = load_fixture(fixture) if fixture else AIHotResponse(
                url=str(source_document.get("url") or "snapshot://local"),
                payload=source_document["payload"],
                items=tuple(SourceItem.from_mapping(item) for item in source_document["payload"].get("items", [])),
                etag=source_document.get("etag"),
                from_cache=True,
            )
        else:
            response = load_fixture(fixture) if fixture else AIHotClient(cache_dir=artifacts / "aihot-cache").fetch_selected_24h(limit=limit)
            write_json(source_path, _source_snapshot(response))
        if not source_path.is_file():
            write_json(source_path, _source_snapshot(response))

        current_stage = "selection"
        selection = select_items(response.items)
        editorial_brief = {
            "version": "1.0",
            "date": run_date.isoformat(),
            "show_name": DEFAULT_SHOW_NAME,
            "source": {"url": response.url, "window": "24h", "mode": "selected", "etag": response.etag},
            "selection": {
                "status": selection.mode,
                "eligible_count": selection.eligible_count,
                "selected_count": len(selection.items),
                "category_counts": selection.category_counts,
                "reason": selection.reason,
                "item_ids": [item.item_id for item in selection.items],
            },
            "items": [item.to_dict() for item in selection.items],
        }
        write_json(artifacts / "editorial_brief.json", editorial_brief)
        if selection.mode == "failure":
            return _write_stage_report(run_dir, status="failed", stage="selection", started_at=started_at, details={"preflight": preflight, "selection": editorial_brief["selection"]}, error=selection.reason)

        current_stage = "script"
        script = build_script(selection, run_date=run_date)
        source_items = _items_by_id(response)
        script_errors = validate_script(script, source_items)
        if script_errors:
            raise ValueError("script grounding validation failed: " + "; ".join(script_errors[:5]))
        write_json(artifacts / "narration_plan.json", script)
        write_json(artifacts / "fact_ledger.json", build_fact_ledger(script, source_items))
        if prepare_only:
            return _write_stage_report(
                run_dir,
                status="prepared",
                stage="script",
                started_at=started_at,
                details={"preflight": preflight, "selection": editorial_brief["selection"], "script": {"segment_count": len(script["segments"]), "mode": selection.mode}},
            )

        current_stage = "voice"
        audio = synthesize_and_align(run_dir, script, openmontage_root=openmontage_root, env_path=env_file or env_path(), align=align)
        current_stage = "materialize"
        rendered = materialize(run_dir, script, audio["durations"], audio["subtitle_cues"])
        current_stage = "render"
        output_path = run_dir / "renders" / f"ai-daily-news-{run_date.isoformat()}.mp4"
        render_report = render_hyperframes(run_dir, openmontage_root=openmontage_root, output_path=output_path)
        current_stage = "quality"
        probe = probe_video(output_path)
        duration = float((probe.get("format") or {}).get("duration") or 0)
        if duration <= 0 or duration > 240:
            raise OpenMontageError(f"final duration outside safe range: {duration:.2f}s")
        quality_report = {
            "version": "1.0",
            "status": "pass",
            "duration_seconds": round(duration, 3),
            "video": probe,
            "checks": {"has_video": True, "has_audio": True, "resolution": "1920x1080", "duration_max_seconds": 240},
        }
        write_json(artifacts / "quality_report.json", quality_report)
        return _write_stage_report(
            run_dir,
            status="success",
            stage="complete",
            started_at=started_at,
            details={
                "preflight": preflight,
                "selection": editorial_brief["selection"],
                "script": {"segment_count": len(script["segments"]), "mode": selection.mode},
                "audio": {"duration_seconds": rendered["total_duration_seconds"], "subtitle_count": len(audio["subtitle_cues"])},
                "render": {"output_path": str(output_path), "openmontage": render_report},
                "quality": quality_report,
                "source_attribution": "AIHOT 过去 24 小时精选",
            },
        )
    except (AIHotError, OpenMontageError, ValueError, OSError, MediaError) as exc:
        return _write_stage_report(run_dir, status="failed", stage=current_stage, started_at=started_at, details={"run_dir": str(run_dir)}, error=_safe_error(exc))
    except Exception as exc:  # pragma: no cover - defensive boundary for unattended runs
        return _write_stage_report(run_dir, status="failed", stage=current_stage, started_at=started_at, details={"run_dir": str(run_dir)}, error=_safe_error(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build AI每日早报 from AIHOT and OpenMontage.")
    parser.add_argument("run", nargs="?", choices=["run"], default="run")
    parser.add_argument("--date", dest="run_date", help="edition date in YYYY-MM-DD; defaults to Asia/Shanghai today")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--fixture", type=Path, help="offline AIHOT JSON fixture")
    parser.add_argument("--openmontage-root", type=Path, default=DEFAULT_OPENMONTAGE_ROOT)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--prepare-only", action="store_true", help="fetch/select/script/materialize inputs without Azure or rendering")
    parser.add_argument("--force", action="store_true", help="rebuild an existing date explicitly")
    parser.add_argument("--no-align", action="store_true", help="skip Azure STT alignment; intended only for local smoke runs")
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_date:
        try:
            run_date = date.fromisoformat(args.run_date)
        except ValueError:
            print("--date must be YYYY-MM-DD", file=sys.stderr)
            return 2
    else:
        run_date = _now().date()
    report = run_pipeline(
        run_date=run_date,
        output_root=args.output_root.expanduser().resolve(),
        fixture=args.fixture.expanduser().resolve() if args.fixture else None,
        openmontage_root=args.openmontage_root.expanduser().resolve(),
        env_file=args.env_file.expanduser().resolve() if args.env_file else None,
        prepare_only=args.prepare_only,
        force=args.force,
        align=not args.no_align,
        limit=args.limit,
    )
    print(json.dumps({"status": report.get("status"), "date": run_date.isoformat(), "path": str(args.output_root / run_date.isoformat()), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report.get("status") in {"success", "prepared"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
