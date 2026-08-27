from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .config import DEFAULT_LOCALE, DEFAULT_RATE, DEFAULT_REGION, DEFAULT_VOICE, load_allowed_env
from .media import MediaError, concat_narration, make_procedural_bed, media_duration, mix_audio, write_json, write_subtitles


class OpenMontageError(RuntimeError):
    """Raised when OpenMontage or Azure cannot complete a stage."""


def _load_azure_environment(env_path: Path | None) -> dict[str, str]:
    values = load_allowed_env(env_path)
    for key, value in values.items():
        os.environ[key] = value
    if not os.environ.get("AZURE_SPEECH_REGION"):
        os.environ["AZURE_SPEECH_REGION"] = DEFAULT_REGION
    # Older local .env files sometimes store the STT endpoint under the TTS
    # name. Translate it without ever logging the endpoint or key value.
    endpoint = os.environ.get("AZURE_TTS_ENDPOINT", "").rstrip("/")
    if endpoint and ".api.cognitive.microsoft.com" in endpoint:
        os.environ["AZURE_SPEECH_ENDPOINT"] = endpoint
        os.environ.pop("AZURE_TTS_ENDPOINT", None)
    if not os.environ.get("AZURE_SPEECH_KEY"):
        raise OpenMontageError("AZURE_SPEECH_KEY is not configured")
    return values


def synthesize_and_align(
    project_dir: Path,
    script: Mapping[str, Any],
    *,
    openmontage_root: Path,
    env_path: Path | None = None,
    align: bool = True,
) -> dict[str, Any]:
    _load_azure_environment(env_path)
    if not openmontage_root.is_dir():
        raise OpenMontageError(f"OpenMontage directory not found: {openmontage_root}")
    sys.path.insert(0, str(openmontage_root))
    try:
        from tools.audio.azure_tts import AzureTTS
        from tools.analysis.azure_stt import AzureSpeechToText
    except Exception as exc:  # pragma: no cover - depends on local checkout
        raise OpenMontageError(f"could not import OpenMontage audio tools: {exc}") from exc

    audio_dir = project_dir / "assets" / "audio"
    alignment_dir = project_dir / "artifacts" / "alignments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    alignment_dir.mkdir(parents=True, exist_ok=True)
    tts = AzureTTS()
    stt = AzureSpeechToText()
    manifest: list[dict[str, Any]] = []
    durations: dict[str, float] = {}
    for segment in script.get("segments", []):
        segment_id = str(segment["id"])
        text = str(segment.get("broadcast_text") or "").strip()
        if not text:
            raise OpenMontageError(f"empty narration text for {segment_id}")
        output_path = audio_dir / f"narration-{segment_id}.wav"
        result = tts.execute({
            "text": text,
            "voice": DEFAULT_VOICE,
            "locale": DEFAULT_LOCALE,
            "rate": DEFAULT_RATE,
            "pitch": "0%",
            "output_format": "wav",
            "output_path": str(output_path),
        })
        if not result.success or not output_path.is_file() or output_path.stat().st_size == 0:
            raise OpenMontageError(f"Azure TTS failed for {segment_id}: {result.error}")
        duration = media_duration(output_path)
        durations[segment_id] = duration
        alignment_path: Path | None = None
        word_count = 0
        if align:
            alignment_result = stt.execute({
                "input_path": str(output_path),
                "language": DEFAULT_LOCALE,
                "diarize": False,
                "profanity_filter": "None",
                "output_dir": str(alignment_dir),
            })
            words = (alignment_result.data or {}).get("word_timestamps", []) if alignment_result.success else []
            if not alignment_result.success or not words:
                raise OpenMontageError(f"Azure word alignment failed for {segment_id}: {alignment_result.error}")
            word_count = len(words)
            alignment_path = alignment_dir / f"{segment_id}.json"
            write_json(alignment_path, {
                "version": "1.0",
                "provider": "azure",
                "language": DEFAULT_LOCALE,
                "duration_seconds": alignment_result.data.get("duration_seconds"),
                "segments": alignment_result.data.get("segments", []),
                "word_timestamps": words,
                "source_audio": f"assets/audio/{output_path.name}",
                "script_section_id": segment_id,
            })
        manifest.append({
            "segment_id": segment_id,
            "audio_path": f"assets/audio/{output_path.name}",
            "alignment_path": f"artifacts/alignments/{alignment_path.name}" if alignment_path else None,
            "provider": "azure",
            "voice": DEFAULT_VOICE,
            "locale": DEFAULT_LOCALE,
            "region": os.environ.get("AZURE_SPEECH_REGION", DEFAULT_REGION),
            "word_count": word_count,
            "duration_seconds": round(duration, 3),
            "temperature_parameter_sent": False,
        })
    segment_ids = [str(segment["id"]) for segment in script.get("segments", [])]
    narration = concat_narration(project_dir, segment_ids)
    bed = make_procedural_bed(project_dir, media_duration(narration))
    final_mix = mix_audio(project_dir, narration, bed)
    subtitle_path, cues = write_subtitles(project_dir, script, durations, aligned=align)
    write_json(project_dir / "artifacts" / "azure_audio_manifest.json", {
        "version": "1.0",
        "provider": "azure",
        "voice": DEFAULT_VOICE,
        "locale": DEFAULT_LOCALE,
        "region": os.environ.get("AZURE_SPEECH_REGION", DEFAULT_REGION),
        "tts_settings": {"rate": DEFAULT_RATE, "pitch": "0%", "temperature_parameter_sent": False},
        "segments": manifest,
        "audio": {"narration_track": "assets/audio/narration-track.wav", "bed": "assets/music/procedural-morning-bed.wav", "final_mix": "assets/audio/final-mix.wav"},
        "subtitle_path": "assets/subtitles/subtitles.srt",
        "subtitle_cue_count": len(cues),
        "failure_policy": "stop on Azure failure; no alternate voice",
        "no_secrets_in_artifacts": True,
    })
    return {"durations": durations, "final_mix": final_mix, "subtitle_path": subtitle_path, "manifest": manifest, "subtitle_cues": cues}


def render_hyperframes(project_dir: Path, *, openmontage_root: Path, output_path: Path) -> dict[str, Any]:
    if not (project_dir / "hyperframes" / "index.html").is_file():
        raise OpenMontageError("HyperFrames workspace has no index.html")
    sys.path.insert(0, str(openmontage_root))
    try:
        from tools.video.hyperframes_compose import HyperFramesCompose
    except Exception as exc:  # pragma: no cover - depends on local checkout
        raise OpenMontageError(f"could not import OpenMontage HyperFrames tool: {exc}") from exc
    tool = HyperFramesCompose()
    result = tool.execute({
        "operation": "render_existing",
        "workspace_path": str(project_dir / "hyperframes"),
        "output_path": str(output_path),
        "quality": "standard",
        "fps": 30,
        "strict_check": False,
        "snapshots": True,
    })
    if not result.success:
        raise OpenMontageError(f"HyperFrames render failed: {result.error}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise OpenMontageError("HyperFrames reported success but output MP4 is missing")
    return result.data or {"output": str(output_path)}


def probe_video(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
            "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate,channels",
            "-of", "json", str(path),
        ], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OpenMontageError(f"ffprobe failed for {path}") from exc
    if result.returncode != 0:
        raise OpenMontageError(f"ffprobe failed: {(result.stderr or '')[-300:]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OpenMontageError("ffprobe returned invalid JSON") from exc
    streams = data.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise OpenMontageError("final MP4 must contain both video and audio streams")
    width, height = video.get("width"), video.get("height")
    if width != 1920 or height != 1080:
        raise OpenMontageError(f"final MP4 must be 1920x1080, got {width}x{height}")
    return data

