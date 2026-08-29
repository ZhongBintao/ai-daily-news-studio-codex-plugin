from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from .config import DEFAULT_LOCALE, DEFAULT_RATE, DEFAULT_REGION, DEFAULT_VOICE, load_allowed_env
from .media import MediaError, concat_narration, make_audio_assets, media_duration, mix_audio, write_json, write_subtitles


class OpenMontageError(RuntimeError):
    """Raised when OpenMontage or Azure cannot complete a stage."""


_TRANSIENT_PROVIDER_MARKERS = (
    "ssleoferror",
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "timed out",
    "max retries exceeded",
    "temporarily unavailable",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _retryable_provider_result(result: Any) -> bool:
    if result is None or getattr(result, "success", False):
        return False
    error = str(getattr(result, "error", "") or "").lower()
    return any(marker in error for marker in _TRANSIENT_PROVIDER_MARKERS)


def _execute_with_transient_retries(call: Any, *, attempts: int = 3) -> Any:
    """Retry only transport/server failures; never switch voice providers.

    A fresh ``trust_env=False`` session avoids an intermittent keep-alive/TLS
    EOF observed on the local proxy path while keeping the provider contract
    and credentials entirely inside the OpenMontage call.
    """

    import requests

    session = requests.Session()
    session.trust_env = False
    original_post = requests.post
    requests.post = session.post
    try:
        result = None
        for attempt in range(attempts):
            result = call()
            if not _retryable_provider_result(result) or attempt >= attempts - 1:
                return result
            time.sleep(1.5 * (attempt + 1))
        return result
    finally:
        requests.post = original_post
        session.close()


def _audio_events(script: Mapping[str, Any], durations: Mapping[str, float], assets: Mapping[str, Path]) -> list[dict[str, Any]]:
    """Place quiet whooshes at every story boundary and chimes at section changes."""

    events: list[dict[str, Any]] = []
    cursor = 0.0
    previous_category: str | None = None
    seen_news = False
    for segment in script.get("segments", []):
        segment_id = str(segment.get("id"))
        duration = max(0.0, float(durations.get(segment_id, 0.0)))
        kind = str(segment.get("kind") or "")
        if kind == "overview":
            events.append({"kind": "overview-entry", "path": str(assets["chime"]), "start": max(0.0, cursor - 0.10), "volume": 0.16})
        elif kind == "news":
            events.append({"kind": "story-boundary", "path": str(assets["whoosh"]), "start": max(0.0, cursor - 0.22), "volume": 0.34})
            category = str(segment.get("category") or "other")
            if seen_news and category != previous_category:
                events.append({"kind": "category-change", "path": str(assets["chime"]), "start": max(0.0, cursor - 0.06), "volume": 0.22})
            previous_category = category
            seen_news = True
        elif kind == "outro":
            events.append({"kind": "outro", "path": str(assets["chime"]), "start": max(0.0, cursor - 0.10), "volume": 0.20})
        cursor += duration
    return events


def _pad_audio(path: Path, target_duration: float) -> None:
    """Pad a short spoken segment with silence for overview reading time."""

    current = media_duration(path)
    if target_duration <= current + 0.02:
        return
    temporary = path.with_name(f".{path.stem}-padded.wav")
    result = subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(path),
        "-af", f"apad=pad_dur={target_duration - current:.3f}", "-t", f"{target_duration:.3f}",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(temporary),
    ], capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        raise OpenMontageError(f"could not pad audio segment {path.name}: {(result.stderr or '')[-400:]}")
    os.replace(temporary, path)


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
    spoken_durations: dict[str, float] = {}
    for segment in script.get("segments", []):
        segment_id = str(segment["id"])
        text = str(segment.get("broadcast_text") or "").strip()
        if not text:
            raise OpenMontageError(f"empty narration text for {segment_id}")
        output_path = audio_dir / f"narration-{segment_id}.wav"
        speech_path = audio_dir / f".narration-{segment_id}-speech.wav"
        result = _execute_with_transient_retries(lambda: tts.execute({
            "text": text,
            "voice": DEFAULT_VOICE,
            "locale": DEFAULT_LOCALE,
            "rate": DEFAULT_RATE,
            "pitch": "0%",
            "output_format": "wav",
            "output_path": str(speech_path),
        }))
        if not result.success or not speech_path.is_file() or speech_path.stat().st_size == 0:
            raise OpenMontageError(f"Azure TTS failed for {segment_id}: {result.error}")
        speech_duration = media_duration(speech_path)
        spoken_durations[segment_id] = speech_duration
        minimum_duration = max(0.0, float(segment.get("minimum_duration_seconds") or 0.0))
        if minimum_duration > speech_duration + 0.02:
            _pad_audio(speech_path, minimum_duration)
        os.replace(speech_path, output_path)
        duration = media_duration(output_path)
        durations[segment_id] = duration
        alignment_path: Path | None = None
        word_count = 0
        if align:
            alignment_result = _execute_with_transient_retries(lambda: stt.execute({
                "input_path": str(output_path),
                "language": DEFAULT_LOCALE,
                "diarize": False,
                "profanity_filter": "None",
                "output_dir": str(alignment_dir),
            }))
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
            "spoken_duration_seconds": round(speech_duration, 3),
            "duration_seconds": round(duration, 3),
            "temperature_parameter_sent": False,
        })
    segment_ids = [str(segment["id"]) for segment in script.get("segments", [])]
    narration = concat_narration(project_dir, segment_ids)
    audio_assets = make_audio_assets(project_dir, media_duration(narration))
    audio_events = _audio_events(script, durations, audio_assets)
    final_mix = mix_audio(project_dir, narration, audio_assets["bed"], audio_events)
    subtitle_path, cues = write_subtitles(project_dir, script, durations, aligned=align, spoken_durations=spoken_durations)
    write_json(project_dir / "artifacts" / "azure_audio_manifest.json", {
        "version": "1.0",
        "provider": "azure",
        "voice": DEFAULT_VOICE,
        "locale": DEFAULT_LOCALE,
        "region": os.environ.get("AZURE_SPEECH_REGION", DEFAULT_REGION),
        "tts_settings": {"rate": DEFAULT_RATE, "pitch": "0%", "temperature_parameter_sent": False},
        "segments": manifest,
        "audio": {
            "narration_track": "assets/audio/narration-track.wav",
            "bed": "assets/music/ai-daily-news-bed.ogg",
            "transition_whoosh": "assets/audio/transition-whoosh.wav",
            "category_chime": "assets/audio/category-chime.wav",
            "final_mix": "assets/audio/final-mix.wav",
            "events": audio_events,
        },
        "spoken_durations": {key: round(value, 3) for key, value in spoken_durations.items()},
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
