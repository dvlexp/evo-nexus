"""
Stage 5b: Motion Graphics — Overlay animated graphics from markers

Parses transcript markers [graphic:NAME] and overlays HTML-rendered
motion graphics at the specified timestamps.

Inputs:
    - video_bg_replaced.mp4 (or previous video)
    - transcript.json (with markers)
    - assets/motion-templates/{NAME}.html

Outputs:
    - video_with_graphics.mp4
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
    Execute motion-graphics stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    mg_config = config.get("motion_graphics", {})

    # Find input video
    video_input = _find_video_input(episode_dir)
    if not video_input:
        raise FileNotFoundError(f"No video found in {episode_dir}")

    # Load transcript
    transcript_file = episode_dir / "transcript.json"
    if not transcript_file.exists():
        logger.warning("no_transcript", msg="Skipping motion graphics")
        return _skip_stage(episode_dir, video_input, logger)

    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    logger.info("motion_graphics_start", video=video_input.name)

    # Parse markers from transcript
    markers = _parse_graphic_markers(transcript, logger)

    metrics = {
        "markers_found": len(markers),
    }

    if not markers:
        logger.info("no_graphic_markers", msg="No [graphic:] markers found")
        return _skip_stage(episode_dir, video_input, logger)

    logger.info("markers_parsed", count=len(markers))

    # Find template directory
    templates_dir = _find_templates_dir(episode_dir, config)

    if not templates_dir or not templates_dir.exists():
        logger.warning("no_templates_dir", msg="Motion templates not found")
        return _skip_stage(episode_dir, video_input, logger)

    # Process each marker
    default_duration = mg_config.get("default_duration", 2.5)
    safe_margin = mg_config.get("safe_zone_margin", 5) / 100.0

    overlays = []
    for marker in markers:
        graphic_name = marker["name"]
        timestamp = marker["timestamp"]
        duration = marker.get("duration", default_duration)

        # Find template
        template_file = templates_dir / f"{graphic_name}.html"
        if not template_file.exists():
            logger.warning(
                "template_not_found",
                name=graphic_name,
                searched=str(template_file),
            )
            continue

        # Render template to video
        rendered_file = _render_template(
            template_file,
            episode_dir,
            duration,
            logger,
        )

        if rendered_file:
            overlays.append({
                "file": rendered_file,
                "timestamp": timestamp,
                "duration": duration,
                "name": graphic_name,
            })

    metrics["overlays_rendered"] = len(overlays)

    if not overlays:
        logger.info("no_overlays_rendered", msg="No graphics could be rendered")
        return _skip_stage(episode_dir, video_input, logger)

    # Apply overlays to video
    output_file = episode_dir / "video_with_graphics.mp4"

    _apply_overlays(
        video_input,
        overlays,
        output_file,
        safe_margin,
        logger,
    )

    # Cleanup rendered files
    for overlay in overlays:
        if overlay["file"].exists():
            overlay["file"].unlink()

    logger.info(
        "motion_graphics_complete",
        overlays_applied=len(overlays),
        output=output_file.name,
    )

    return ["video_with_graphics.mp4"], metrics


def _skip_stage(episode_dir: Path, video_input: Path, logger: Any) -> tuple[list[str], dict]:
    """Skip stage by copying input."""
    output_file = episode_dir / "video_with_graphics.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_input),
        "-c:v", "copy",
        "-c:a", "copy",
        str(output_file),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    return ["video_with_graphics.mp4"], {"skipped": True}


def _find_video_input(episode_dir: Path) -> Path | None:
    """Find video input."""
    candidates = [
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


def _find_templates_dir(episode_dir: Path, config: dict) -> Path | None:
    """Find motion templates directory."""
    # Episode-specific templates
    episode_templates = episode_dir / "assets" / "motion-templates"
    if episode_templates.exists():
        return episode_templates

    # Skill templates
    skill_dir = Path(__file__).parent.parent.parent
    skill_templates = skill_dir / "assets" / "motion-templates"
    if skill_templates.exists():
        return skill_templates

    return None


def _parse_graphic_markers(transcript: dict, logger: Any) -> list[dict]:
    """
    Parse [graphic:NAME] markers from transcript.

    Supported formats:
        [graphic:NAME]
        [graphic:NAME duration=2.5]
        [lower-third:TEXT]
    """
    import re

    markers = []
    pattern = r'\[graphic:(\w+)(?:\s+duration=([0-9.]+))?\]'
    lower_third_pattern = r'\[lower-third:([^\]]+)\]'

    for segment in transcript.get("segments", []):
        text = segment.get("text", "")
        start = segment.get("start", 0)

        # Check for graphic markers
        for match in re.finditer(pattern, text):
            name = match.group(1)
            duration = float(match.group(2)) if match.group(2) else None

            markers.append({
                "name": name,
                "timestamp": start,
                "duration": duration,
            })

            logger.debug(
                "marker_found",
                type="graphic",
                name=name,
                timestamp=f"{start:.2f}",
            )

        # Check for lower-third markers
        for match in re.finditer(lower_third_pattern, text):
            text_content = match.group(1).strip()

            markers.append({
                "name": "lower-third",
                "timestamp": start,
                "text": text_content,
            })

            logger.debug(
                "marker_found",
                type="lower-third",
                text=text_content[:30],
                timestamp=f"{start:.2f}",
            )

    return markers


def _render_template(
    template_file: Path,
    episode_dir: Path,
    duration: float,
    logger: Any,
) -> Path | None:
    """
    Render HTML template to MP4 using HyperFrames or fallback.

    Returns path to rendered video or None if failed.
    """
    # Find HyperFrames
    skill_dir = Path(__file__).parent.parent.parent
    hyperframes_dir = skill_dir / "vendor" / "HyperFrames"

    output_file = episode_dir / f"motion_{template_file.stem}_{int(duration*1000)}.mp4"

    if hyperframes_dir.exists():
        # Use HyperFrames
        render_script = hyperframes_dir / "render.py"

        if render_script.exists():
            cmd = [
                "python3", str(render_script),
                str(template_file),
                "-o", str(output_file),
                "--duration", str(duration),
                "--transparent",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and output_file.exists():
                return output_file

            logger.warning(
                "hyperframes_failed",
                error=result.stderr[:200] if result.stderr else "unknown",
            )

    # Fallback: Create simple graphic with ffmpeg
    logger.info("hyperframes_fallback", msg="Using ffmpeg for simple overlay")

    # Create a simple colored rectangle as placeholder
    width, height = 400, 100
    color = "0x00FFA7"  # Evolution green

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={width}x{height}:d={duration}",
        "-vf", "format=rgba",
        "-c:v", "png",
        str(output_file.with_suffix(".png")),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        # Convert PNG sequence to video
        png_file = output_file.with_suffix(".png")
        cmd2 = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(png_file),
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuva420p",
            str(output_file),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True)
        png_file.unlink(missing_ok=True)

        if result2.returncode == 0 and output_file.exists():
            return output_file

    return None


def _apply_overlays(
    video_input: Path,
    overlays: list[dict],
    output_file: Path,
    safe_margin: float,
    logger: Any,
) -> None:
    """Apply overlay graphics to video."""
    if not overlays:
        # Just copy
        cmd = ["ffmpeg", "-y", "-i", str(video_input), "-c", "copy", str(output_file)]
        subprocess.run(cmd, capture_output=True, check=True)
        return

    # Build complex filter for overlays
    inputs = ["-i", str(video_input)]
    filter_parts = []

    # Add overlay inputs
    for i, overlay in enumerate(overlays):
        inputs.extend(["-i", str(overlay["file"])])

    # Build filter graph
    current = "0:v"

    for i, overlay in enumerate(overlays):
        timestamp = overlay["timestamp"]
        duration = overlay.get("duration", 2.5)

        # Calculate position (bottom center with safe margin)
        # overlay_w and overlay_h are placeholder variables for ffmpeg
        x_pos = "(main_w-overlay_w)/2"
        y_pos = f"main_h-overlay_h-{int(safe_margin * 1080)}"

        # Enable filter expression for timed overlay
        enable = f"between(t,{timestamp},{timestamp + duration})"

        out_label = f"v{i+1}"
        filter_parts.append(
            f"[{current}][{i+1}:v]overlay={x_pos}:{y_pos}:enable='{enable}'[{out_label}]"
        )
        current = out_label

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{current}]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "copy",
        str(output_file),
    ]

    logger.debug("overlay_cmd", overlays=len(overlays))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        logger.error("overlay_failed", stderr=result.stderr[:500])
        # Fallback: copy without overlays
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(video_input),
            "-c", "copy",
            str(output_file),
        ]
        subprocess.run(cmd_fallback, capture_output=True, check=True)
