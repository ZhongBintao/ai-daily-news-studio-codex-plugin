from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


class MediaError(RuntimeError):
    """Raised when a local audio/video contract cannot be produced."""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_command(args: list[str], *, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"command failed to start or timed out: {args[0]}") from exc


def media_duration(path: Path) -> float:
    result = run_command([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], timeout=30)
    if result.returncode != 0:
        raise MediaError(f"ffprobe could not read {path}: {(result.stderr or '')[-300:]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise MediaError(f"ffprobe returned no duration for {path}") from exc


def _audio_files(project_dir: Path, segment_ids: Iterable[str]) -> list[Path]:
    paths = [project_dir / "assets" / "audio" / f"narration-{segment_id}.wav" for segment_id in segment_ids]
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise MediaError(f"missing narration audio: {', '.join(missing)}")
    return paths


def concat_narration(project_dir: Path, segment_ids: Iterable[str]) -> Path:
    audio_paths = _audio_files(project_dir, segment_ids)
    output = project_dir / "assets" / "audio" / "narration-track.wav"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, suffix=".txt", delete=False) as handle:
        list_path = Path(handle.name)
        for path in audio_paths:
            handle.write(f"file '{path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
    try:
        result = run_command([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(output),
        ], timeout=300)
    finally:
        list_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output.is_file():
        raise MediaError(f"could not concatenate narration: {(result.stderr or '')[-500:]}")
    return output


def make_procedural_bed(project_dir: Path, duration: float) -> Path:
    output = project_dir / "assets" / "music" / "procedural-morning-bed.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    # A deterministic, quiet two-tone bed keeps the first version independent
    # of external music licensing and network availability.
    expression = "0.12*sin(2*PI*110*t)+0.045*sin(2*PI*165*t)+0.018*sin(2*PI*220*t)"
    result = run_command([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"aevalsrc={expression}:s=48000:d={max(duration, 0.1):.3f}",
        "-af", "afade=t=in:st=0:d=1,afade=t=out:st=" + f"{max(duration - 1.5, 0):.3f}:d=1.5",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(output),
    ], timeout=120)
    if result.returncode != 0 or not output.is_file():
        raise MediaError(f"could not create procedural music bed: {(result.stderr or '')[-500:]}")
    return output


def mix_audio(project_dir: Path, narration: Path, bed: Path) -> Path:
    output = project_dir / "assets" / "audio" / "final-mix.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run_command([
        "ffmpeg", "-y", "-i", str(narration), "-i", str(bed),
        "-filter_complex", "[1:a]volume=0.08[bed];[0:a][bed]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(output),
    ], timeout=300)
    if result.returncode != 0 or not output.is_file():
        raise MediaError(f"could not mix audio: {(result.stderr or '')[-500:]}")
    return output


def _srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _word_cues(words: list[Mapping[str, Any]], offset: float, *, max_words: int = 6, max_chars: int = 14) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []
    for word in words:
        text = str(word.get("word") or word.get("text") or "").strip()
        if not text:
            continue
        proposed = "".join(str(item.get("word") or item.get("text") or "").strip() for item in [*current, word])
        if current and (len(current) >= max_words or len(proposed) > max_chars):
            cues.append({
                "start": offset + float(current[0].get("start", 0)),
                "end": offset + float(current[-1].get("end", current[-1].get("start", 0) + 0.2)),
                "text": "".join(str(item.get("word") or item.get("text") or "").strip() for item in current),
            })
            current = []
        current.append(word)
    if current:
        cues.append({
            "start": offset + float(current[0].get("start", 0)),
            "end": offset + float(current[-1].get("end", current[-1].get("start", 0) + 0.2)),
            "text": "".join(str(item.get("word") or item.get("text") or "").strip() for item in current),
        })
    return cues


def write_subtitles(project_dir: Path, script: Mapping[str, Any], durations: Mapping[str, float], *, aligned: bool = True) -> tuple[Path, list[dict[str, Any]]]:
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    alignment_dir = project_dir / "artifacts" / "alignments"
    for segment in script.get("segments", []):
        segment_id = str(segment["id"])
        duration = float(durations.get(segment_id, 0.0))
        alignment_path = alignment_dir / f"{segment_id}.json"
        if aligned and alignment_path.is_file():
            data = json.loads(alignment_path.read_text(encoding="utf-8"))
            cues.extend(_word_cues(list(data.get("word_timestamps") or []), cursor))
        else:
            text = str(segment.get("broadcast_text") or "").strip()
            if text and duration > 0:
                cues.append({"start": cursor, "end": cursor + duration, "text": text})
        cursor += duration
    normalized: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, 1):
        start = max(0.0, float(cue["start"]))
        end = max(start + 0.12, float(cue["end"]))
        normalized.append({"index": index, "start": round(start, 3), "end": round(end, 3), "text": str(cue["text"])})
    srt_path = project_dir / "assets" / "subtitles" / "subtitles.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, cue in enumerate(normalized, 1):
        lines.extend([str(index), f"{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}", cue["text"], ""])
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path, normalized
