"""
Stage 5c: SFX — Mix sound effects at transcript markers

Parses [sfx:NAME] markers from transcript and mixes matching
SFX files at the specified timestamps.

Inputs:
    - audio_final.wav (or audio_no_fillers.wav)
    - transcript.json (with markers)
    - assets/sfx/{NAME}.wav

Outputs:
    - audio_with_sfx.wav
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute sfx stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    sfx_config = config.get("sfx", {})

    # Find input audio
    audio_input = _find_audio_input(episode_dir)
    if not audio_input:
        raise FileNotFoundError(f"No audio found in {episode_dir}")

    # Load transcript
    transcript_file = episode_dir / "transcript.json"
    if not transcript_file.exists():
        logger.warning("no_transcript", msg="Skipping SFX stage")
        return _skip_stage(episode_dir, audio_input, logger)

    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    logger.info("sfx_start", audio=audio_input.name)

    # Parse SFX markers
    markers = _parse_sfx_markers(transcript, logger)

    metrics = {
        "markers_found": len(markers),
    }

    if not markers:
        logger.info("no_sfx_markers", msg="No [sfx:] markers found")
        return _skip_stage(episode_dir, audio_input, logger)

    logger.info("sfx_markers_parsed", count=len(markers))

    # Find SFX directory
    sfx_dir = _find_sfx_dir(episode_dir, config)

    if not sfx_dir or not sfx_dir.exists():
        logger.warning("no_sfx_dir", msg="SFX directory not found")
        return _skip_stage(episode_dir, audio_input, logger)

    # Load and prepare SFX files
    target_lufs = sfx_config.get("target_lufs", -20)
    sfx_files = []

    for marker in markers:
        sfx_name = marker["name"]
        timestamp = marker["timestamp"]

        # Find SFX file
        sfx_file = _find_sfx_file(sfx_dir, sfx_name)
        if not sfx_file:
            logger.warning("sfx_not_found", name=sfx_name)
            continue

        # Normalize SFX to target LUFS
        normalized_sfx = episode_dir / f"sfx_{sfx_name}_normalized.wav"
        _normalize_sfx(sfx_file, normalized_sfx, target_lufs, logger)

        sfx_files.append({
            "file": normalized_sfx,
            "timestamp": timestamp,
            "name": sfx_name,
        })

    metrics["sfx_files_loaded"] = len(sfx_files)

    if not sfx_files:
        logger.info("no_sfx_files", msg="No SFX files could be loaded")
        return _skip_stage(episode_dir, audio_input, logger)

    # Mix SFX into audio
    output_file = episode_dir / "audio_with_sfx.wav"
    _mix_sfx(audio_input, sfx_files, output_file, logger)

    # Cleanup normalized files
    for sfx in sfx_files:
        sfx["file"].unlink(missing_ok=True)

    logger.info(
        "sfx_complete",
        sfx_mixed=len(sfx_files),
        output=output_file.name,
    )

    return ["audio_with_sfx.wav"], metrics


def _skip_stage(episode_dir: Path, audio_input: Path, logger: Any) -> tuple[list[str], dict]:
    """Skip stage by copying input."""
    output_file = episode_dir / "audio_with_sfx.wav"
    subprocess.run(
        ["cp", str(audio_input), str(output_file)],
        capture_output=True,
        check=True,
    )
    return ["audio_with_sfx.wav"], {"skipped": True}


def _find_audio_input(episode_dir: Path) -> Path | None:
    """Find the best audio input."""
    candidates = [
        "audio_no_fillers.wav",
        "audio_final.wav",
        "audio_synced.wav",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    return None


def _find_sfx_dir(episode_dir: Path, config: dict) -> Path | None:
    """Find SFX directory."""
    # Episode-specific
    episode_sfx = episode_dir / "assets" / "sfx"
    if episode_sfx.exists():
        return episode_sfx

    # Skill default
    skill_dir = Path(__file__).parent.parent.parent
    skill_sfx = skill_dir / "assets" / "sfx"
    if skill_sfx.exists():
        return skill_sfx

    return None


def _find_sfx_file(sfx_dir: Path, name: str) -> Path | None:
    """Find SFX file by name."""
    extensions = [".wav", ".mp3", ".flac", ".ogg"]

    for ext in extensions:
        path = sfx_dir / f"{name}{ext}"
        if path.exists():
            return path

    # Case-insensitive search
    for file in sfx_dir.iterdir():
        if file.stem.lower() == name.lower():
            return file

    return None


def _parse_sfx_markers(transcript: dict, logger: Any) -> list[dict]:
    """
    Parse [sfx:NAME] markers from transcript.

    Supported formats:
        [sfx:NAME]
        [sfx:whoosh]
    """
    markers = []
    pattern = r'\[sfx:(\w+)\]'

    for segment in transcript.get("segments", []):
        text = segment.get("text", "")
        start = segment.get("start", 0)

        for match in re.finditer(pattern, text, re.IGNORECASE):
            name = match.group(1).lower()

            markers.append({
                "name": name,
                "timestamp": start,
            })

            logger.debug(
                "sfx_marker_found",
                name=name,
                timestamp=f"{start:.2f}",
            )

    return markers


def _normalize_sfx(
    input_file: Path,
    output_file: Path,
    target_lufs: float,
    logger: Any,
) -> None:
    """Normalize SFX to target LUFS."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-af", f"loudnorm=I={target_lufs}:TP=-1:LRA=7",
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.warning("sfx_normalize_failed", file=input_file.name, error=result.stderr[:200])
        # Fallback: just copy
        subprocess.run(["cp", str(input_file), str(output_file)], check=True)


def _mix_sfx(
    audio_input: Path,
    sfx_files: list[dict],
    output_file: Path,
    logger: Any,
) -> None:
    """Mix SFX into audio at specified timestamps."""
    if not sfx_files:
        subprocess.run(["cp", str(audio_input), str(output_file)], check=True)
        return

    # Get audio duration
    duration = _get_duration(audio_input)

    # Build filter graph
    inputs = ["-i", str(audio_input)]
    filter_parts = []
    mix_inputs = ["[0:a]"]

    for i, sfx in enumerate(sfx_files):
        inputs.extend(["-i", str(sfx["file"])])

        # Add delay to position SFX
        delay_ms = int(sfx["timestamp"] * 1000)
        filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[sfx{i}]")
        mix_inputs.append(f"[sfx{i}]")

    # Mix all streams
    mix_count = len(mix_inputs)
    filter_parts.append(
        f"{''.join(mix_inputs)}amix=inputs={mix_count}:duration=longest:dropout_transition=2[out]"
    )

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("sfx_mix_cmd", sfx_count=len(sfx_files))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.error("sfx_mix_failed", stderr=result.stderr[:500])
        # Fallback: copy without SFX
        subprocess.run(["cp", str(audio_input), str(output_file)], check=True)


def _get_duration(audio_file: Path) -> float:
    """Get audio duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        str(audio_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))

    return 0.0
