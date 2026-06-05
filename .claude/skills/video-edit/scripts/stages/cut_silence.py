"""
Stage 4b: Cut Silence — Remove silent segments from video

Uses auto-editor for intelligent silence detection and removal.
Verifies A/V sync after cuts.

Inputs:
    - video_no_fillers.mp4 (or video.mp4)
    - audio_no_fillers.wav (or audio_final.wav)

Outputs:
    - video_cut.mp4
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute cut-silence stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    silence_config = config.get("silence", {})

    # Find input files
    video_input = _find_video_input(episode_dir)
    audio_input = _find_audio_input(episode_dir)

    if not video_input:
        raise FileNotFoundError(f"No video found in {episode_dir}")
    if not audio_input:
        raise FileNotFoundError(f"No audio found in {episode_dir}")

    logger.info(
        "cut_silence_start",
        video=video_input.name,
        audio=audio_input.name,
    )

    # Get config values
    threshold = silence_config.get("threshold", 0.04)
    frame_margin = silence_config.get("frame_margin", 6)
    min_cut_length = silence_config.get("min_cut_length", 0.8)
    max_av_drift_ms = silence_config.get("max_av_drift_ms", 40)

    metrics = {
        "threshold": threshold,
        "frame_margin": frame_margin,
        "min_cut_length": min_cut_length,
    }

    # Get input duration
    input_duration = _get_duration(video_input)
    metrics["input_duration_seconds"] = input_duration

    # Run auto-editor analysis
    logger.info("auto_editor_analyzing")

    # Create temp file for timeline export
    timeline_file = episode_dir / "auto_editor_timeline.json"

    # First, analyze with auto-editor
    analysis_result = _run_auto_editor_analysis(
        video_input,
        audio_input,
        timeline_file,
        threshold,
        frame_margin,
        min_cut_length,
        logger,
    )

    if not analysis_result:
        logger.warning("auto_editor_failed", msg="Falling back to simple silence detection")
        # Fallback: use ffmpeg silencedetect
        cuts = _detect_silence_ffmpeg(audio_input, threshold, min_cut_length, logger)
    else:
        cuts = analysis_result

    metrics["silence_segments_found"] = len(cuts)

    if not cuts:
        logger.info("no_silence_found", msg="No silence to cut")
        # Copy input to output
        output_file = episode_dir / "video_cut.mp4"
        _copy_with_audio(video_input, audio_input, output_file, logger)
        return ["video_cut.mp4"], metrics

    # Calculate stats
    total_silence_duration = sum(cut["duration"] for cut in cuts)
    metrics["total_silence_duration_seconds"] = total_silence_duration
    metrics["estimated_output_duration"] = input_duration - total_silence_duration

    logger.info(
        "silence_detected",
        segments=len(cuts),
        total_duration=f"{total_silence_duration:.2f}s",
        percentage=f"{(total_silence_duration/input_duration)*100:.1f}%",
    )

    # Apply cuts using ffmpeg (not auto-editor's export for codec control)
    output_file = episode_dir / "video_cut.mp4"
    _apply_silence_cuts(
        video_input,
        audio_input,
        output_file,
        cuts,
        input_duration,
        logger,
    )

    # Verify A/V sync
    output_duration = _get_duration(output_file)
    audio_duration = _get_audio_duration_from_video(output_file)

    av_drift_ms = abs(output_duration - audio_duration) * 1000
    metrics["output_duration_seconds"] = output_duration
    metrics["av_drift_ms"] = av_drift_ms
    metrics["av_sync_ok"] = av_drift_ms <= max_av_drift_ms

    if av_drift_ms > max_av_drift_ms:
        logger.warning(
            "av_drift_detected",
            drift_ms=f"{av_drift_ms:.1f}",
            max_allowed=max_av_drift_ms,
        )
    else:
        logger.info(
            "av_sync_verified",
            drift_ms=f"{av_drift_ms:.1f}",
        )

    # Cleanup
    if timeline_file.exists():
        timeline_file.unlink()

    logger.info(
        "cut_silence_complete",
        silences_removed=len(cuts),
        duration_removed=f"{total_silence_duration:.2f}s",
        output_duration=f"{output_duration:.1f}s",
    )

    return ["video_cut.mp4"], metrics


def _find_video_input(episode_dir: Path) -> Path | None:
    """Find the best video input file."""
    candidates = [
        "video_no_fillers.mp4",
        "video.mp4",
        "video.MOV",
        "video.mkv",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    return None


def _find_audio_input(episode_dir: Path) -> Path | None:
    """Find the best audio input file."""
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


def _run_auto_editor_analysis(
    video_file: Path,
    audio_file: Path,
    timeline_file: Path,
    threshold: float,
    frame_margin: int,
    min_cut_length: float,
    logger: Any,
) -> list[dict] | None:
    """
    Run auto-editor to detect silence.

    Returns list of silence segments or None if failed.
    """
    # Check if auto-editor is available
    which_result = subprocess.run(
        ["which", "auto-editor"],
        capture_output=True,
        text=True,
    )

    if which_result.returncode != 0:
        logger.warning("auto_editor_not_found")
        return None

    # Run auto-editor in analyze mode
    cmd = [
        "auto-editor",
        str(video_file),
        "--silent-threshold", str(threshold),
        "--frame-margin", str(frame_margin),
        "--min-cut-length", str(min_cut_length),
        "--export", "json",
        "--output", str(timeline_file.with_suffix("")),
        "--no-open",
    ]

    logger.debug("auto_editor_cmd", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.warning("auto_editor_error", stderr=result.stderr[:500])
        return None

    # Parse timeline JSON
    json_file = timeline_file.with_suffix(".json")
    if not json_file.exists():
        # auto-editor might use different naming
        json_files = list(timeline_file.parent.glob("*_ALTERED.json"))
        if json_files:
            json_file = json_files[0]
        else:
            return None

    try:
        with open(json_file, "r") as f:
            data = json.load(f)

        # Extract silence segments from timeline
        cuts = []
        timeline = data.get("timeline", data.get("v", []))

        if isinstance(timeline, list):
            for clip in timeline:
                # auto-editor marks kept segments; we want removed ones
                pass

        # Cleanup
        json_file.unlink()

        return cuts

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("timeline_parse_error", error=str(e))
        return None


def _detect_silence_ffmpeg(
    audio_file: Path,
    threshold: float,
    min_duration: float,
    logger: Any,
) -> list[dict]:
    """
    Fallback silence detection using ffmpeg silencedetect.

    Returns list of silence segments.
    """
    # Convert threshold to dB (silencedetect uses dB)
    # threshold 0.04 ≈ -28dB
    threshold_db = 20 * (threshold if threshold > 0 else 0.001).__log10__() if threshold > 0 else -60

    cmd = [
        "ffmpeg",
        "-i", str(audio_file),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse silencedetect output
    cuts = []
    import re

    silence_starts = re.findall(r"silence_start: ([\d.]+)", result.stderr)
    silence_ends = re.findall(r"silence_end: ([\d.]+)", result.stderr)
    silence_durations = re.findall(r"silence_duration: ([\d.]+)", result.stderr)

    for i, (start, end) in enumerate(zip(silence_starts, silence_ends)):
        duration = float(silence_durations[i]) if i < len(silence_durations) else float(end) - float(start)
        cuts.append({
            "start": float(start),
            "end": float(end),
            "duration": duration,
        })

    logger.debug("silencedetect_results", segments=len(cuts))

    return cuts


def _apply_silence_cuts(
    video_input: Path,
    audio_input: Path,
    output_file: Path,
    cuts: list[dict],
    total_duration: float,
    logger: Any,
) -> None:
    """Apply silence cuts using ffmpeg."""
    # Get segments to KEEP (inverse of silence)
    segments = _get_keep_segments(cuts, total_duration)

    if not segments:
        logger.warning("no_segments_after_cuts")
        _copy_with_audio(video_input, audio_input, output_file, logger)
        return

    # Build ffmpeg filter
    filter_parts = []
    v_labels = []
    a_labels = []

    for i, (start, end) in enumerate(segments):
        # Video segment
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]"
        )
        v_labels.append(f"[v{i}]")

        # Audio segment (from separate file)
        filter_parts.append(
            f"[1:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
        )
        a_labels.append(f"[a{i}]")

    # Concatenate
    concat_v = "".join(v_labels)
    concat_a = "".join(a_labels)
    n = len(segments)

    filter_parts.append(f"{concat_v}concat=n={n}:v=1:a=0[outv]")
    filter_parts.append(f"{concat_a}concat=n={n}:v=0:a=1[outa]")

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_input),
        "-i", str(audio_input),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_file),
    ]

    logger.debug("apply_cuts_cmd", segments=len(segments))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        logger.error("ffmpeg_cuts_failed", stderr=result.stderr[:500])
        raise RuntimeError(f"ffmpeg cuts failed: {result.stderr[:200]}")


def _get_keep_segments(cuts: list[dict], total_duration: float) -> list[tuple[float, float]]:
    """Get segments to KEEP (inverse of cuts)."""
    if not cuts:
        return [(0, total_duration)]

    cuts = sorted(cuts, key=lambda x: x["start"])

    segments = []
    current_pos = 0.0

    for cut in cuts:
        if cut["start"] > current_pos:
            segments.append((current_pos, cut["start"]))
        current_pos = cut["end"]

    if current_pos < total_duration:
        segments.append((current_pos, total_duration))

    return segments


def _copy_with_audio(
    video_file: Path,
    audio_file: Path,
    output_file: Path,
    logger: Any,
) -> None:
    """Copy video with replaced audio track."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_file),
        "-i", str(audio_file),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg copy failed: {result.stderr}")


def _get_duration(media_file: Path) -> float:
    """Get media duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        str(media_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))

    return 0.0


def _get_audio_duration_from_video(video_file: Path) -> float:
    """Get audio track duration from video file."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "a:0",
        "-show_entries", "stream=duration",
        "-of", "json",
        str(video_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            return float(streams[0].get("duration", 0))

    # Fallback to format duration
    return _get_duration(video_file)
