"""
Stage 6: Render — Final output in 16:9 and 9:16 formats

Combines video with graphics and audio with SFX into final outputs:
- final_16x9.mp4 (H.264 1920x1080 30fps)
- final_9x16_shorts.mp4 (H.264 1080x1920 30fps, max 60s)

Also handles preview mode (5min @ 540p).

Inputs:
    - video_with_graphics.mp4 (or previous video)
    - audio_with_sfx.wav (or previous audio)
    - transcript.json (for shorts segment detection)

Outputs:
    - final_16x9.mp4
    - final_9x16_shorts.mp4 (if shorts segment found)
    - preview_5min.mp4 (if preview mode)
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
    Execute render stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    render_config = config.get("render", {})
    preview_config = config.get("preview", {})

    # Find inputs
    video_input = _find_video_input(episode_dir)
    audio_input = _find_audio_input(episode_dir)

    if not video_input:
        raise FileNotFoundError(f"No video found in {episode_dir}")
    if not audio_input:
        raise FileNotFoundError(f"No audio found in {episode_dir}")

    logger.info(
        "render_start",
        video=video_input.name,
        audio=audio_input.name,
        preview=preview,
    )

    metrics = {}
    artifacts = []

    # Get input info
    video_info = _get_video_info(video_input)
    metrics["input_duration"] = video_info.get("duration", 0)
    metrics["input_resolution"] = f"{video_info.get('width', 0)}x{video_info.get('height', 0)}"

    if preview:
        # Preview mode: 5min @ 540p
        output_file = episode_dir / "preview_5min.mp4"
        duration_limit = preview_config.get("duration_seconds", 300)
        width = preview_config.get("width", 960)
        height = preview_config.get("height", 540)

        _render_16x9(
            video_input,
            audio_input,
            output_file,
            render_config,
            logger,
            duration_limit=duration_limit,
            scale=(width, height),
        )

        artifacts.append("preview_5min.mp4")
        metrics["preview_duration"] = min(duration_limit, video_info.get("duration", 0))

    else:
        # Full render

        # Render 16:9
        output_16x9 = episode_dir / "final_16x9.mp4"
        _render_16x9(
            video_input,
            audio_input,
            output_16x9,
            render_config,
            logger,
        )
        artifacts.append("final_16x9.mp4")

        # Verify output
        output_info = _get_video_info(output_16x9)
        metrics["output_16x9_duration"] = output_info.get("duration", 0)
        metrics["output_16x9_size_mb"] = output_16x9.stat().st_size / (1024 * 1024)

        # Render 9:16 shorts
        shorts_segment = _find_shorts_segment(episode_dir, video_info.get("duration", 0), logger)

        if shorts_segment:
            output_9x16 = episode_dir / "final_9x16_shorts.mp4"
            _render_9x16(
                video_input,
                audio_input,
                output_9x16,
                shorts_segment,
                render_config,
                logger,
            )
            artifacts.append("final_9x16_shorts.mp4")

            shorts_info = _get_video_info(output_9x16)
            metrics["output_9x16_duration"] = shorts_info.get("duration", 0)
            metrics["output_9x16_size_mb"] = output_9x16.stat().st_size / (1024 * 1024)
        else:
            logger.info("no_shorts_segment", msg="No shorts segment found, skipping 9:16")

    logger.info(
        "render_complete",
        artifacts=artifacts,
        preview=preview,
    )

    return artifacts, metrics


def _find_video_input(episode_dir: Path) -> Path | None:
    """Find video input."""
    candidates = [
        "video_with_graphics.mp4",
        "video_bg_replaced.mp4",
        "video_cut.mp4",
        "video_no_fillers.mp4",
        "video.mp4",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    return None


def _find_audio_input(episode_dir: Path) -> Path | None:
    """Find audio input."""
    candidates = [
        "audio_with_sfx.wav",
        "audio_no_fillers.wav",
        "audio_final.wav",
        "audio_synced.wav",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    return None


def _get_video_info(video_file: Path) -> dict:
    """Get video metadata."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    info = {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "duration": 0,
    }

    if result.returncode == 0:
        data = json.loads(result.stdout)

        # Video stream
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 1920)
                info["height"] = stream.get("height", 1080)

                fps_str = stream.get("r_frame_rate", "30/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    info["fps"] = float(num) / float(den) if float(den) > 0 else 30
                else:
                    info["fps"] = float(fps_str)
                break

        info["duration"] = float(data.get("format", {}).get("duration", 0))

    return info


def _render_16x9(
    video_input: Path,
    audio_input: Path,
    output_file: Path,
    config: dict,
    logger: Any,
    duration_limit: float | None = None,
    scale: tuple[int, int] | None = None,
) -> None:
    """Render final 16:9 video."""
    # Build ffmpeg command
    codec = config.get("video_codec", "libx264")
    preset = config.get("preset", "medium")
    crf = config.get("crf", 20)
    pix_fmt = config.get("pix_fmt", "yuv420p")
    profile = config.get("profile", "high")
    level = config.get("level", "4.1")
    audio_codec = config.get("audio_codec", "aac")
    audio_bitrate = config.get("audio_bitrate", "192k")
    audio_sr = config.get("audio_sample_rate", 48000)
    audio_channels = config.get("audio_channels", 2)
    target_width = scale[0] if scale else config.get("width_16x9", 1920)
    target_height = scale[1] if scale else config.get("height_16x9", 1080)
    fps = config.get("fps", 30)

    # Build filter
    vf_parts = [
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
    ]
    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_input),
        "-i", str(audio_input),
    ]

    # Duration limit for preview
    if duration_limit:
        cmd.extend(["-t", str(duration_limit)])

    cmd.extend([
        "-map", "0:v",
        "-map", "1:a",
        "-vf", vf,
        "-c:v", codec,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", pix_fmt,
        "-profile:v", profile,
        "-level", level,
        "-movflags", "+faststart",
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        "-ar", str(audio_sr),
        "-ac", str(audio_channels),
        str(output_file),
    ])

    logger.debug("render_16x9_cmd", output=output_file.name)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    if result.returncode != 0:
        logger.error("render_16x9_failed", stderr=result.stderr[:500])
        raise RuntimeError(f"Render failed: {result.stderr[:200]}")


def _find_shorts_segment(
    episode_dir: Path,
    total_duration: float,
    logger: Any,
) -> dict | None:
    """
    Find shorts segment from transcript markers or instructions.

    Returns dict with 'start' and 'end' times, or None.
    """
    max_shorts_duration = 60  # Max 60s for shorts

    # Check instructions.md for shorts_segments
    instructions_file = episode_dir / "instructions.md"
    if instructions_file.exists():
        content = instructions_file.read_text()

        # Parse shorts_segments from YAML-like format
        if "shorts_segments:" in content.lower():
            # Extract first segment
            start_match = re.search(r"start:\s*(\d{2}):(\d{2}):(\d{2})", content)
            end_match = re.search(r"end:\s*(\d{2}):(\d{2}):(\d{2})", content)

            if start_match and end_match:
                start = int(start_match.group(1)) * 3600 + int(start_match.group(2)) * 60 + int(start_match.group(3))
                end = int(end_match.group(1)) * 3600 + int(end_match.group(2)) * 60 + int(end_match.group(3))

                duration = end - start
                if 0 < duration <= max_shorts_duration:
                    logger.info("shorts_from_instructions", start=start, end=end)
                    return {"start": start, "end": end}

    # Check transcript for [shorts:start] / [shorts:end] markers
    transcript_file = episode_dir / "transcript.json"
    if transcript_file.exists():
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript = json.load(f)

        shorts_start = None
        shorts_end = None

        for segment in transcript.get("segments", []):
            text = segment.get("text", "").lower()
            timestamp = segment.get("start", 0)

            if "[shorts:start]" in text:
                shorts_start = timestamp
            elif "[shorts:end]" in text:
                shorts_end = timestamp

        if shorts_start is not None and shorts_end is not None:
            duration = shorts_end - shorts_start
            if 0 < duration <= max_shorts_duration:
                logger.info("shorts_from_markers", start=shorts_start, end=shorts_end)
                return {"start": shorts_start, "end": shorts_end}

    # Fallback: use first 60s if video is longer than 60s
    if total_duration > max_shorts_duration:
        logger.info("shorts_fallback_first_60s")
        return {"start": 0, "end": min(60, total_duration)}

    # If video is already short enough, use whole thing
    if total_duration <= max_shorts_duration:
        logger.info("shorts_whole_video", duration=total_duration)
        return {"start": 0, "end": total_duration}

    return None


def _render_9x16(
    video_input: Path,
    audio_input: Path,
    output_file: Path,
    segment: dict,
    config: dict,
    logger: Any,
) -> None:
    """Render 9:16 shorts with face tracking crop."""
    start = segment["start"]
    end = segment["end"]
    duration = end - start

    target_width = config.get("width_9x16", 1080)
    target_height = config.get("height_9x16", 1920)
    fps = config.get("fps", 30)
    codec = config.get("video_codec", "libx264")
    preset = config.get("preset", "medium")
    crf = config.get("crf", 20)
    pix_fmt = config.get("pix_fmt", "yuv420p")
    audio_codec = config.get("audio_codec", "aac")
    audio_bitrate = config.get("audio_bitrate", "192k")

    # Try face-tracking crop with YOLOv8
    crop_result = _detect_face_crop(video_input, start, duration, logger)

    if crop_result:
        # Use detected crop
        crop_x, crop_y, crop_w, crop_h = crop_result
        vf = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_width}:{target_height}"
    else:
        # Fallback: center crop
        logger.info("face_crop_fallback", msg="Using center crop")
        # Calculate center crop from 16:9 to 9:16
        # Source is 1920x1080, we need 9:16 aspect
        # Crop height: 1080, width for 9:16 = 1080 * 9/16 = 607.5
        crop_w = 607
        crop_h = 1080
        crop_x = "(iw-607)/2"
        crop_y = 0
        vf = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_width}:{target_height}"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(video_input),
        "-ss", str(start),
        "-i", str(audio_input),
        "-t", str(duration),
        "-map", "0:v",
        "-map", "1:a",
        "-vf", vf,
        "-c:v", codec,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", pix_fmt,
        "-movflags", "+faststart",
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        str(output_file),
    ]

    logger.debug("render_9x16_cmd", duration=duration)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.error("render_9x16_failed", stderr=result.stderr[:500])
        # Fallback: simple center crop
        _render_9x16_simple(video_input, audio_input, output_file, segment, config, logger)


def _detect_face_crop(
    video_input: Path,
    start: float,
    duration: float,
    logger: Any,
) -> tuple[int, int, int, int] | None:
    """
    Detect face position for smart crop using YOLOv8.

    Returns (x, y, width, height) for crop, or None if failed.
    """
    try:
        from ultralytics import YOLO
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("yolo_not_available", msg="YOLOv8 not installed")
        return None

    try:
        # Load model
        model = YOLO("yolov8n.pt")

        # Sample frames
        cap = cv2.VideoCapture(str(video_input))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        start_frame = int(start * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # Sample every 30 frames (1 second)
        detections = []
        sample_count = min(int(duration), 10)  # Max 10 samples

        for i in range(sample_count):
            frame_pos = start_frame + i * int(fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)

            ret, frame = cap.read()
            if not ret:
                break

            # Detect person
            results = model(frame, classes=[0], verbose=False)  # class 0 = person

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    center_x = (x1 + x2) / 2
                    center_y = (y1 + y2) / 2
                    detections.append((center_x, center_y))

        cap.release()

        if not detections:
            return None

        # Average position
        avg_x = np.mean([d[0] for d in detections])
        avg_y = np.mean([d[1] for d in detections])

        # Calculate crop (9:16 aspect from 16:9)
        # Assuming 1920x1080 input
        frame_w, frame_h = 1920, 1080
        crop_h = frame_h  # Use full height
        crop_w = int(crop_h * 9 / 16)  # 607 pixels

        # Center crop on detected face
        crop_x = int(max(0, min(avg_x - crop_w / 2, frame_w - crop_w)))
        crop_y = 0

        logger.info(
            "face_detected",
            center_x=f"{avg_x:.0f}",
            center_y=f"{avg_y:.0f}",
            crop=f"{crop_x},{crop_y},{crop_w},{crop_h}",
        )

        return (crop_x, crop_y, crop_w, crop_h)

    except Exception as e:
        logger.warning("face_detection_failed", error=str(e))
        return None


def _render_9x16_simple(
    video_input: Path,
    audio_input: Path,
    output_file: Path,
    segment: dict,
    config: dict,
    logger: Any,
) -> None:
    """Render 9:16 with simple center crop (fallback)."""
    start = segment["start"]
    duration = segment["end"] - segment["start"]

    target_width = config.get("width_9x16", 1080)
    target_height = config.get("height_9x16", 1920)

    vf = f"crop=607:1080:(iw-607)/2:0,scale={target_width}:{target_height}"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(video_input),
        "-ss", str(start),
        "-i", str(audio_input),
        "-t", str(duration),
        "-map", "0:v",
        "-map", "1:a",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"Simple 9:16 render failed: {result.stderr[:200]}")
