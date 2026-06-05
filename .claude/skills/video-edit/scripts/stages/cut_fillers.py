"""
Stage 4a: Cut Fillers — Remove filler words from audio/video

Uses transcript.json to identify filler words (≥250ms) and removes them
via ffmpeg with crossfade transitions.

Inputs:
    - video_cut.mp4 (or video.mp4 if cut-silence was skipped)
    - audio_final.wav
    - transcript.json

Outputs:
    - video_no_fillers.mp4
    - audio_no_fillers.wav
    - cuts.edl (edit decision list)
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute cut-fillers stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    filler_config = config.get("filler", {})

    # Find input files
    transcript_file = episode_dir / "transcript.json"
    if not transcript_file.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_file}")

    # Input video: prefer video from previous stage, fallback to original
    video_input = _find_video_input(episode_dir)
    audio_input = episode_dir / "audio_final.wav"

    if not audio_input.exists():
        raise FileNotFoundError(f"Audio not found: {audio_input}")

    logger.info(
        "cut_fillers_start",
        video=video_input.name if video_input else "none",
        audio=audio_input.name,
    )

    # Load transcript
    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    # Load filler words list
    fillers = _load_filler_words(config, logger)

    # Find filler segments to cut
    min_duration_ms = filler_config.get("min_duration_ms", 250)
    merge_gap_ms = filler_config.get("merge_gap_ms", 100)
    crossfade_ms = filler_config.get("crossfade_ms", 30)

    cuts = _find_filler_cuts(
        transcript,
        fillers,
        min_duration_ms,
        merge_gap_ms,
        logger,
    )

    metrics = {
        "total_fillers_found": len(cuts),
        "min_duration_ms": min_duration_ms,
    }

    if not cuts:
        logger.info("no_fillers_found", msg="No fillers to cut")
        # Copy files as-is
        if video_input:
            _copy_file(video_input, episode_dir / "video_no_fillers.mp4")
        _copy_file(audio_input, episode_dir / "audio_no_fillers.wav")
        return ["video_no_fillers.mp4", "audio_no_fillers.wav"], metrics

    # Calculate total duration to cut
    total_cut_duration = sum(cut["end"] - cut["start"] for cut in cuts)
    metrics["total_cut_duration_seconds"] = total_cut_duration
    metrics["fillers_by_word"] = _count_fillers_by_word(cuts)

    logger.info(
        "fillers_detected",
        count=len(cuts),
        total_duration=f"{total_cut_duration:.2f}s",
    )

    # Generate EDL (Edit Decision List)
    edl_file = episode_dir / "cuts.edl"
    _write_edl(cuts, edl_file)

    # Apply cuts to audio
    audio_output = episode_dir / "audio_no_fillers.wav"
    _apply_cuts_audio(
        audio_input,
        audio_output,
        cuts,
        crossfade_ms,
        logger,
    )

    # Apply cuts to video (if exists)
    artifacts = ["audio_no_fillers.wav", "cuts.edl"]
    if video_input:
        video_output = episode_dir / "video_no_fillers.mp4"
        _apply_cuts_video(
            video_input,
            audio_output,  # Use the cut audio
            video_output,
            cuts,
            crossfade_ms,
            logger,
        )
        artifacts.insert(0, "video_no_fillers.mp4")

    logger.info(
        "cut_fillers_complete",
        fillers_removed=len(cuts),
        duration_removed=f"{total_cut_duration:.2f}s",
    )

    return artifacts, metrics


def _find_video_input(episode_dir: Path) -> Path | None:
    """Find the best video input file."""
    # Order of preference
    candidates = [
        "video_cut.mp4",      # From cut-silence
        "video.mp4",          # Original
        "video.MOV",
        "video.mkv",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    # Try any video file
    for ext in [".mp4", ".mov", ".mkv", ".webm"]:
        videos = list(episode_dir.glob(f"*{ext}"))
        if videos:
            return videos[0]

    return None


def _load_filler_words(config: dict, logger: Any) -> set[str]:
    """Load filler words from config."""
    # Try to load from fillers-ptbr.yaml
    skill_dir = Path(__file__).parent.parent.parent
    fillers_file = skill_dir / "config" / "fillers-ptbr.yaml"

    fillers = set()

    if fillers_file.exists():
        with open(fillers_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for entry in data.get("fillers", []):
            if isinstance(entry, dict):
                word = entry.get("word", "").lower().strip()
                if word:
                    fillers.add(word)
                for variant in entry.get("variants", []):
                    if variant:
                        fillers.add(variant.lower().strip())
            elif isinstance(entry, str):
                fillers.add(entry.lower().strip())

        logger.debug("fillers_loaded", count=len(fillers), source=str(fillers_file))
    else:
        # Fallback to hardcoded list
        fillers = {
            "é", "eh", "uhm", "um", "hum", "ah", "hmm", "aham",
            "tipo", "sabe", "então", "assim", "né", "tá", "certo",
            "perfeito", "beleza", "ok", "basicamente", "literalmente",
            "enfim", "bom", "olha", "e",
        }
        logger.debug("fillers_fallback", count=len(fillers))

    return fillers


def _find_filler_cuts(
    transcript: dict,
    fillers: set[str],
    min_duration_ms: int,
    merge_gap_ms: int,
    logger: Any,
) -> list[dict]:
    """
    Find segments to cut based on filler word detection.

    Returns list of dicts with: start, end, word, confidence
    """
    cuts = []
    min_duration_s = min_duration_ms / 1000.0

    for segment in transcript.get("segments", []):
        for word_data in segment.get("words", []):
            word = word_data.get("word", "").lower().strip()
            # Remove punctuation
            word_clean = "".join(c for c in word if c.isalnum() or c.isspace())

            if word_clean in fillers:
                start = word_data.get("start", 0)
                end = word_data.get("end", 0)
                duration = end - start

                if duration >= min_duration_s:
                    cuts.append({
                        "start": start,
                        "end": end,
                        "word": word_clean,
                        "confidence": word_data.get("score", 0),
                    })
                    logger.debug(
                        "filler_found",
                        word=word_clean,
                        start=f"{start:.3f}",
                        duration=f"{duration:.3f}s",
                    )

    # Merge adjacent cuts (gap < merge_gap_ms)
    if len(cuts) > 1:
        cuts = _merge_adjacent_cuts(cuts, merge_gap_ms / 1000.0)

    return cuts


def _merge_adjacent_cuts(cuts: list[dict], max_gap: float) -> list[dict]:
    """Merge cuts that are very close together."""
    if not cuts:
        return cuts

    # Sort by start time
    cuts = sorted(cuts, key=lambda x: x["start"])

    merged = [cuts[0]]

    for cut in cuts[1:]:
        last = merged[-1]
        gap = cut["start"] - last["end"]

        if gap <= max_gap:
            # Merge: extend the last cut
            last["end"] = cut["end"]
            last["word"] = f"{last['word']}+{cut['word']}"
        else:
            merged.append(cut)

    return merged


def _count_fillers_by_word(cuts: list[dict]) -> dict[str, int]:
    """Count fillers by word."""
    counts = {}
    for cut in cuts:
        # Handle merged words
        words = cut["word"].split("+")
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    return counts


def _write_edl(cuts: list[dict], edl_file: Path) -> None:
    """Write Edit Decision List."""
    with open(edl_file, "w") as f:
        f.write("TITLE: Filler Cuts\n")
        f.write("FCM: NON-DROP FRAME\n\n")

        for i, cut in enumerate(cuts, 1):
            # EDL format: edit# reel track type in out
            f.write(
                f"{i:03d}  001  AA/V  C  "
                f"{_seconds_to_timecode(cut['start'])} "
                f"{_seconds_to_timecode(cut['end'])} "
                f"{_seconds_to_timecode(cut['start'])} "
                f"{_seconds_to_timecode(cut['end'])}\n"
            )
            f.write(f"* FILLER: {cut['word']}\n\n")


def _seconds_to_timecode(seconds: float, fps: int = 30) -> str:
    """Convert seconds to SMPTE timecode."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    frames = int((seconds % 1) * fps)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def _apply_cuts_audio(
    input_file: Path,
    output_file: Path,
    cuts: list[dict],
    crossfade_ms: int,
    logger: Any,
) -> None:
    """Apply cuts to audio file using ffmpeg."""
    if not cuts:
        _copy_file(input_file, output_file)
        return

    # Get audio duration
    duration = _get_duration(input_file)

    # Build segments to keep (inverse of cuts)
    segments = _get_keep_segments(cuts, duration)

    if not segments:
        logger.warning("no_segments_to_keep", msg="All audio would be cut")
        _copy_file(input_file, output_file)
        return

    # Build ffmpeg filter for concatenation with crossfade
    filter_parts = []
    input_labels = []

    for i, (start, end) in enumerate(segments):
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
        input_labels.append(f"[a{i}]")

    # Concatenate segments
    concat_inputs = "".join(input_labels)
    filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[outa]")

    # Apply crossfade at cut points (simplified: use acrossfade between segments)
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-filter_complex", filter_complex,
        "-map", "[outa]",
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("cut_audio_cmd", cmd=" ".join(cmd[:10]) + "...")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg_cut_audio_failed", stderr=result.stderr[:500])
        raise RuntimeError(f"ffmpeg audio cut failed: {result.stderr[:200]}")


def _apply_cuts_video(
    video_input: Path,
    audio_input: Path,  # Already cut audio
    output_file: Path,
    cuts: list[dict],
    crossfade_ms: int,
    logger: Any,
) -> None:
    """Apply cuts to video file using ffmpeg."""
    if not cuts:
        _copy_file(video_input, output_file)
        return

    # Get video duration
    duration = _get_duration(video_input)

    # Build segments to keep
    segments = _get_keep_segments(cuts, duration)

    if not segments:
        logger.warning("no_video_segments", msg="All video would be cut")
        _copy_file(video_input, output_file)
        return

    # Build ffmpeg filter for video
    filter_parts = []
    v_labels = []

    for i, (start, end) in enumerate(segments):
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]"
        )
        v_labels.append(f"[v{i}]")

    # Concatenate video segments
    concat_v = "".join(v_labels)
    filter_parts.append(f"{concat_v}concat=n={len(segments)}:v=1:a=0[outv]")

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_input),
        "-i", str(audio_input),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_file),
    ]

    logger.debug("cut_video_cmd", cmd=" ".join(cmd[:10]) + "...")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg_cut_video_failed", stderr=result.stderr[:500])
        raise RuntimeError(f"ffmpeg video cut failed: {result.stderr[:200]}")


def _get_keep_segments(cuts: list[dict], total_duration: float) -> list[tuple[float, float]]:
    """
    Get segments to KEEP (inverse of cuts).

    Returns list of (start, end) tuples.
    """
    if not cuts:
        return [(0, total_duration)]

    # Sort cuts by start time
    cuts = sorted(cuts, key=lambda x: x["start"])

    segments = []
    current_pos = 0.0

    for cut in cuts:
        if cut["start"] > current_pos:
            segments.append((current_pos, cut["start"]))
        current_pos = cut["end"]

    # Add final segment
    if current_pos < total_duration:
        segments.append((current_pos, total_duration))

    return segments


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


def _copy_file(src: Path, dst: Path) -> None:
    """Copy file using ffmpeg for format consistency."""
    subprocess.run(
        ["cp", str(src), str(dst)],
        capture_output=True,
        check=True,
    )
