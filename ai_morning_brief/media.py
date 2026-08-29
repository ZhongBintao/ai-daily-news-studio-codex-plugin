from __future__ import annotations

import json
import math
import os
import re
import shutil
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


MUSIC_SOURCE = Path(__file__).resolve().parent / "assets" / "music" / "ai-daily-news-bed.ogg"


def resolve_music_bed(project_dir: Path) -> Path:
    """Copy the pinned CC0 music asset into the private run directory."""

    if not MUSIC_SOURCE.is_file() or MUSIC_SOURCE.stat().st_size == 0:
        raise MediaError(f"missing pinned music asset: {MUSIC_SOURCE}")
    output = project_dir / "assets" / "music" / MUSIC_SOURCE.name
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MUSIC_SOURCE, output)
    return output


def _make_sfx(project_dir: Path, *, kind: str) -> Path:
    audio_dir = project_dir / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    if kind == "whoosh":
        output = audio_dir / "transition-whoosh.wav"
        result = run_command([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=color=violet:amplitude=0.22:duration=0.58:sample_rate=48000",
            "-af", "highpass=f=650,lowpass=f=5200,afade=t=in:st=0:d=0.08,afade=t=out:st=0.24:d=0.34,volume=0.55",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(output),
        ], timeout=60)
    else:
        output = audio_dir / "category-chime.wav"
        expression = "0.18*sin(2*PI*783.99*t)*exp(-4*t)+0.12*sin(2*PI*1174.66*t)*exp(-5*t)+0.08*sin(2*PI*1567.98*t)*exp(-6*t)"
        result = run_command([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"aevalsrc={expression}:s=48000:d=0.75",
            "-af", "lowpass=f=3500,afade=t=out:st=0.16:d=0.59,volume=0.45",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(output),
        ], timeout=60)
    if result.returncode != 0 or not output.is_file():
        raise MediaError(f"could not create {kind} sound effect: {(result.stderr or '')[-500:]}")
    return output


def make_audio_assets(project_dir: Path, duration: float) -> dict[str, Path]:
    return {
        "bed": resolve_music_bed(project_dir),
        "whoosh": _make_sfx(project_dir, kind="whoosh"),
        "chime": _make_sfx(project_dir, kind="chime"),
    }


def mix_audio(project_dir: Path, narration: Path, bed: Path, events: Iterable[Mapping[str, Any]] = ()) -> Path:
    """Mix narration, ducked music, and timed transition sounds into one track."""

    output = project_dir / "assets" / "audio" / "final-mix.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = media_duration(narration)
    event_list = [event for event in events if Path(str(event.get("path") or "")).is_file()]
    args = ["ffmpeg", "-y", "-i", str(narration), "-stream_loop", "-1", "-i", str(bed)]
    for event in event_list:
        args.extend(["-i", str(event["path"])])
    filters = [
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=duration={duration:.3f},asetpts=N/SR/TB[narr]",
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=duration={duration:.3f},asetpts=N/SR/TB,highpass=f=70,lowpass=f=12000,volume=0.34,afade=t=in:st=0:d=1.2,afade=t=out:st={max(duration - 1.8, 0):.3f}:d=1.8[music]",
        "[music][narr]sidechaincompress=threshold=0.045:ratio=3:attack=18:release=420:makeup=1[ducked]",
    ]
    mix_inputs = ["[narr]", "[ducked]"]
    for index, event in enumerate(event_list):
        start = max(0.0, min(duration, float(event.get("start", 0.0))))
        delay_ms = int(round(start * 1000))
        volume = max(0.0, min(1.0, float(event.get("volume", 0.2))))
        label = f"sfx{index}"
        filters.append(
            f"[{index + 2}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume:.3f},adelay={delay_ms}:all=1,atrim=duration={duration:.3f},asetpts=N/SR/TB[{label}]"
        )
        mix_inputs.append(f"[{label}]")
    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=7[out]"
    )
    args.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output),
    ])
    result = run_command(args, timeout=300)
    if result.returncode != 0 or not output.is_file():
        raise MediaError(f"could not mix audio: {(result.stderr or '')[-500:]}")
    return output


def _srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


_SUBTITLE_ASCII_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*")
_SUBTITLE_HARD_BREAKS = set("。！？!?")
_SUBTITLE_SOFT_BREAKS = set("，,、；;：:")
_SUBTITLE_PUNCTUATION = _SUBTITLE_HARD_BREAKS | _SUBTITLE_SOFT_BREAKS | set("\"'（）()[]【】")


def _subtitle_units(text: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        match = _SUBTITLE_ASCII_RE.match(text, index)
        if match:
            # Keep a single separator before an ASCII token so the visible
            # caption remains the authored broadcast text (e.g. ``128K 上下文``)
            # while timing still weights only spoken characters.
            prefix = " " if index > 0 and text[index - 1].isspace() else ""
            value = prefix + match.group(0)
            units.append({"text": value, "weight": max(1, len(match.group(0))), "punct": False})
            index = match.end()
            continue
        prefix = " " if index > 0 and text[index - 1].isspace() else ""
        value = prefix + text[index]
        units.append({"text": value, "weight": 1, "punct": value.strip() in _SUBTITLE_PUNCTUATION})
        index += 1
    return units


def _word_anchors(words: list[Mapping[str, Any]], duration: float) -> list[tuple[float, float]]:
    anchors: list[tuple[float, float]] = []
    for word in words:
        raw = str(word.get("word") or word.get("text") or "").strip()
        if not raw:
            continue
        chars = [char for char in raw if not char.isspace()]
        if not chars:
            continue
        start = max(0.0, min(duration, float(word.get("start", 0.0))))
        end = max(start + 0.04, min(duration, float(word.get("end", start + 0.2))))
        step = (end - start) / len(chars)
        anchors.extend((start + step * index, start + step * (index + 1)) for index in range(len(chars)))
    return anchors


def _timed_units(text: str, words: list[Mapping[str, Any]], duration: float) -> list[dict[str, Any]]:
    units = _subtitle_units(text)
    if not units:
        return []
    anchors = _word_anchors(words, duration)
    # Azure occasionally collapses the tail of a short utterance onto one
    # timestamp (notably when a segment is padded with silence).  Using those
    # anchors verbatim would give the final clause zero duration and silently
    # drop it from the SRT.  Fall back to deterministic proportional timing
    # whenever the alignment has too few distinct character anchors.
    distinct_anchors = {(round(start, 3), round(end, 3)) for start, end in anchors}
    if not anchors or len(distinct_anchors) < max(3, int(len(units) * 0.6)):
        anchors = [(duration * index / max(1, sum(unit["weight"] for unit in units)), duration * (index + 1) / max(1, sum(unit["weight"] for unit in units))) for index in range(max(1, sum(unit["weight"] for unit in units)))]
    total_weight = max(1, sum(int(unit["weight"]) for unit in units))
    total_anchors = len(anchors)
    cursor = 0
    timed: list[dict[str, Any]] = []
    for unit in units:
        weight = int(unit["weight"])
        start_index = min(total_anchors - 1, int(round(cursor / total_weight * total_anchors)))
        end_index = min(total_anchors, max(start_index + 1, int(round((cursor + weight) / total_weight * total_anchors))))
        timed.append({**unit, "start": anchors[start_index][0], "end": anchors[end_index - 1][1]})
        cursor += weight
    return timed


def _visible_weight(units: Iterable[Mapping[str, Any]]) -> int:
    return sum(max(0, int(unit.get("weight", 0))) for unit in units)


def _split_long_clause(clause: list[dict[str, Any]], maximum: int) -> list[list[dict[str, Any]]]:
    """Split at soft punctuation when possible, keeping phrases readable."""

    if _visible_weight(clause) <= maximum:
        return [clause]
    pieces: list[list[dict[str, Any]]] = []
    remaining = list(clause)
    while remaining:
        if _visible_weight(remaining) <= maximum:
            pieces.append(remaining)
            break
        weight = 0
        last_fit = 0
        last_soft_break = 0
        for index, unit in enumerate(remaining):
            unit_weight = int(unit.get("weight", 1))
            if weight + unit_weight > maximum:
                break
            weight += unit_weight
            last_fit = index + 1
            if str(unit.get("text") or "").strip() in _SUBTITLE_SOFT_BREAKS:
                last_soft_break = index + 1
        split_at = last_soft_break or last_fit or 1
        pieces.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return pieces


def _merge_orphan_phrases(phrases: list[list[dict[str, Any]]], maximum: int) -> list[list[dict[str, Any]]]:
    """Fold short tails back into their neighbour without crossing sentences."""

    if len(phrases) < 2:
        return phrases
    merged = [list(phrase) for phrase in phrases]
    changed = True
    while changed and len(merged) > 1:
        changed = False
        for index in range(1, len(merged)):
            previous, current = merged[index - 1], merged[index]
            tail = _visible_weight(current)
            previous_punctuation = str(previous[-1].get("text", "")).strip()
            if tail <= 3 and previous_punctuation not in _SUBTITLE_HARD_BREAKS and _visible_weight(previous) + tail <= maximum:
                merged[index - 1] = previous + current
                del merged[index]
                changed = True
                break
    return merged


def _phrase_text(phrase: list[dict[str, Any]], previous: dict[str, Any] | None, *, final: bool) -> str:
    raw = "".join(str(unit.get("text") or "") for unit in phrase)
    if final:
        raw = raw.rstrip()
    return raw


def _phrase_cues(text: str, words: list[Mapping[str, Any]], offset: float, duration: float) -> list[dict[str, Any]]:
    timed = _timed_units(text.strip(), words, duration)
    if not timed:
        return []
    maximum = 28
    clauses: list[list[dict[str, Any]]] = []
    current_clause: list[dict[str, Any]] = []
    for unit in timed:
        current_clause.append(unit)
        punctuation = str(unit.get("text") or "").strip()
        if punctuation in _SUBTITLE_HARD_BREAKS:
            clauses.append(current_clause)
            current_clause = []
    if current_clause:
        clauses.append(current_clause)
    clauses = [piece for clause in clauses for piece in _split_long_clause(clause, maximum)]
    phrases: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for clause_index, clause in enumerate(clauses):
        if not current:
            current = list(clause)
            continue
        combined_weight = _visible_weight(current) + _visible_weight(clause)
        previous_punctuation = str(current[-1].get("text", "")).strip()
        # A short clause such as “星期五，” is kept with its next clause;
        # otherwise each comma becomes a distracting one- or two-word card.
        if previous_punctuation in _SUBTITLE_SOFT_BREAKS and _visible_weight(current) < 5 and combined_weight <= maximum:
            current.extend(clause)
        else:
            phrases.append(current)
            current = list(clause)
    if current:
        phrases.append(current)
    phrases = _merge_orphan_phrases(phrases, maximum)
    cues: list[dict[str, Any]] = []
    for index, phrase in enumerate(phrases):
        previous = cues[-1] if cues else None
        phrase_text = _phrase_text(phrase, previous, final=index == len(phrases) - 1)
        stripped_text = phrase_text.strip()
        if stripped_text and stripped_text[0] in _SUBTITLE_PUNCTUATION and previous is not None:
            previous["text"] = str(previous.get("text") or "") + stripped_text[0]
            phrase_text = phrase_text.replace(stripped_text[0], "", 1)
            stripped_text = phrase_text.strip()
        if stripped_text and all(char in _SUBTITLE_PUNCTUATION for char in stripped_text):
            if previous is not None:
                previous["text"] = str(previous.get("text") or "") + phrase_text
                previous["end"] = max(float(previous["end"]), offset + float(phrase[-1]["end"]))
            continue
        if not stripped_text:
            continue
        start = max(0.0, float(phrase[0]["start"]))
        end = min(duration, float(phrase[-1]["end"]))
        cues.append({"start": offset + start, "end": offset + end, "text": phrase_text})
    return cues


def write_subtitles(project_dir: Path, script: Mapping[str, Any], durations: Mapping[str, float], *, aligned: bool = True, spoken_durations: Mapping[str, float] | None = None) -> tuple[Path, list[dict[str, Any]]]:
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    alignment_dir = project_dir / "artifacts" / "alignments"
    for segment in script.get("segments", []):
        segment_id = str(segment["id"])
        duration = float(durations.get(segment_id, 0.0))
        alignment_path = alignment_dir / f"{segment_id}.json"
        text = str(segment.get("broadcast_text") or "").strip()
        if not text or duration <= 0:
            cursor += duration
            continue
        speech_duration = float((spoken_durations or {}).get(segment_id, duration))
        speech_duration = max(0.05, min(duration, speech_duration))
        if aligned and alignment_path.is_file():
            data = json.loads(alignment_path.read_text(encoding="utf-8"))
            cues.extend(_phrase_cues(text, list(data.get("word_timestamps") or []), cursor, speech_duration))
        else:
            cues.extend(_phrase_cues(text, [], cursor, speech_duration))
        cursor += duration
    total_duration = cursor
    normalized: list[dict[str, Any]] = []
    previous_end = 0.0
    for cue in cues:
        text = str(cue.get("text") or "")
        visible_text = text.strip()
        if not visible_text or all(char in _SUBTITLE_PUNCTUATION for char in visible_text):
            continue
        start = max(previous_end, max(0.0, float(cue["start"])))
        end = min(max(0.0, float(cue["end"])), max(0.0, max(start, total_duration)))
        if end <= start:
            continue
        normalized.append({"index": len(normalized) + 1, "start": round(start, 3), "end": round(end, 3), "text": text.rstrip()})
        previous_end = end
    srt_path = project_dir / "assets" / "subtitles" / "subtitles.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, cue in enumerate(normalized, 1):
        lines.extend([str(index), f"{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}", cue["text"], ""])
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path, normalized
