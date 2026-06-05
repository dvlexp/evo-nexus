"""
Stage 5a: Background Removal — Replace video background using MediaPipe

Uses MediaPipe Selfie Segmentation for CPU-based background removal.
Composites the subject over a studio background image.

Inputs:
    - video_cut.mp4 (or previous video artifact)
    - assets/studio-bg.png (background image)

Outputs:
    - video_bg_replaced.mp4
"""

import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute bg-removal stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    bg_config = config.get("bg_removal", {})
    render_config = config.get("render", {})

    # Check episode-specific instructions
    instructions = _load_instructions(episode_dir)
    if instructions.get("skip_bg_removal", False):
        logger.info("bg_removal_skipped", reason="instructions.md skip directive")
        return _skip_stage(episode_dir, logger)

    # Find input video
    video_input = _find_video_input(episode_dir)
    if not video_input:
        raise FileNotFoundError(f"No video found in {episode_dir}")

    # Find background image
    bg_image = _find_background_image(episode_dir, instructions, config, logger)

    logger.info(
        "bg_removal_start",
        video=video_input.name,
        background=bg_image.name if bg_image else "none",
    )

    metrics = {}

    # Get video info
    video_info = _get_video_info(video_input)
    total_frames = video_info.get("total_frames", 0)
    fps = video_info.get("fps", 30)
    width = video_info.get("width", 1920)
    height = video_info.get("height", 1080)

    metrics["input_frames"] = total_frames
    metrics["fps"] = fps
    metrics["resolution"] = f"{width}x{height}"

    if not bg_image or not bg_image.exists():
        logger.warning("no_background_image", msg="Skipping BG removal - no background")
        return _skip_stage(episode_dir, logger)

    # Import MediaPipe
    try:
        import mediapipe as mp
    except ImportError:
        raise RuntimeError("MediaPipe not installed. Run: pip install mediapipe")

    # Load background image
    bg_array = cv2.imread(str(bg_image))
    if bg_array is None:
        raise ValueError(f"Cannot load background image: {bg_image}")

    # Resize background to match video
    bg_array = cv2.resize(bg_array, (width, height))

    # Setup MediaPipe
    model_selection = bg_config.get("model_selection", 1)
    feather_kernel = bg_config.get("feather_radius", 3)

    mp_selfie = mp.solutions.selfie_segmentation
    segmentor = mp_selfie.SelfieSegmentation(model_selection=model_selection)

    logger.info(
        "mediapipe_initialized",
        model_selection=model_selection,
        feather_kernel=feather_kernel,
    )

    # Setup output paths
    temp_frames_dir = episode_dir / "tmp_bg_frames"
    temp_frames_dir.mkdir(exist_ok=True)
    output_file = episode_dir / "video_bg_replaced.mp4"

    # Check for existing checkpoint
    checkpoint_file = episode_dir / "bg_removal_checkpoint.txt"
    start_frame = 0
    if checkpoint_file.exists():
        try:
            start_frame = int(checkpoint_file.read_text().strip())
            logger.info("resuming_from_checkpoint", frame=start_frame)
        except ValueError:
            pass

    # Process frames
    cap = cv2.VideoCapture(str(video_input))

    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    processed = start_frame
    start_time = time.time()
    eta_logged = False

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1

            # Segment
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = segmentor.process(frame_rgb)

            if results.segmentation_mask is not None:
                # Get mask
                mask = results.segmentation_mask

                # Apply feathering (Gaussian blur on mask edges)
                if feather_kernel > 1:
                    mask = cv2.GaussianBlur(mask, (feather_kernel, feather_kernel), 0)

                # Expand mask to 3 channels
                mask_3ch = np.stack([mask] * 3, axis=-1)

                # Composite: foreground * mask + background * (1 - mask)
                composite = (frame.astype(np.float32) * mask_3ch +
                            bg_array.astype(np.float32) * (1 - mask_3ch))
                composite = np.clip(composite, 0, 255).astype(np.uint8)
            else:
                # No segmentation - use original frame
                composite = frame

            # Save frame
            frame_path = temp_frames_dir / f"frame_{frame_idx:08d}.png"
            cv2.imwrite(str(frame_path), composite)

            processed += 1

            # Checkpoint every 100 frames
            if processed % 100 == 0:
                checkpoint_file.write_text(str(processed))

                # Log ETA
                elapsed = time.time() - start_time
                frames_done = processed - start_frame
                if frames_done > 0:
                    fps_actual = frames_done / elapsed
                    remaining = total_frames - processed
                    eta_seconds = remaining / fps_actual if fps_actual > 0 else 0

                    if not eta_logged or processed % 500 == 0:
                        logger.info(
                            "bg_removal_progress",
                            processed=processed,
                            total=total_frames,
                            fps=f"{fps_actual:.1f}",
                            eta_minutes=f"{eta_seconds/60:.1f}",
                        )
                        eta_logged = True

    finally:
        cap.release()
        segmentor.close()

    metrics["frames_processed"] = processed
    metrics["processing_fps"] = processed / (time.time() - start_time) if time.time() > start_time else 0

    logger.info(
        "frames_processed",
        total=processed,
        fps=f"{metrics['processing_fps']:.1f}",
    )

    # Reassemble video with ffmpeg
    logger.info("reassembling_video")

    # Extract original audio
    audio_file = episode_dir / "temp_bg_audio.wav"
    _extract_audio(video_input, audio_file)

    # Create video from frames
    frame_pattern = str(temp_frames_dir / "frame_%08d.png")
    render_fps = render_config.get("fps", 30)

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(render_fps),
        "-i", frame_pattern,
        "-i", str(audio_file),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg reassemble failed: {result.stderr[:500]}")

    # Cleanup
    logger.info("cleaning_up_temp_files")
    import shutil
    shutil.rmtree(temp_frames_dir, ignore_errors=True)
    audio_file.unlink(missing_ok=True)
    checkpoint_file.unlink(missing_ok=True)

    logger.info("bg_removal_complete", output=output_file.name)

    return ["video_bg_replaced.mp4"], metrics


def _skip_stage(episode_dir: Path, logger: Any) -> tuple[list[str], dict]:
    """Skip stage by copying input to output."""
    video_input = _find_video_input(episode_dir)
    output_file = episode_dir / "video_bg_replaced.mp4"

    if video_input:
        # Copy with re-encode for consistency
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_input),
            "-c:v", "copy",
            "-c:a", "copy",
            str(output_file),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    return ["video_bg_replaced.mp4"], {"skipped": True}


def _find_video_input(episode_dir: Path) -> Path | None:
    """Find the best video input."""
    candidates = [
        "video_cut.mp4",
        "video_no_fillers.mp4",
        "video.mp4",
    ]

    for name in candidates:
        path = episode_dir / name
        if path.exists():
            return path

    return None


def _find_background_image(
    episode_dir: Path,
    instructions: dict,
    config: dict,
    logger: Any,
) -> Path | None:
    """Find background image."""
    # Check instructions for custom background
    custom_bg = instructions.get("bg_image")
    if custom_bg:
        custom_path = episode_dir / "assets" / custom_bg
        if custom_path.exists():
            return custom_path

        # Try skill assets
        skill_dir = Path(__file__).parent.parent.parent
        custom_path = skill_dir / "assets" / custom_bg
        if custom_path.exists():
            return custom_path

    # Default background
    skill_dir = Path(__file__).parent.parent.parent
    default_bg = skill_dir / "assets" / "studio-bg.png"

    if default_bg.exists():
        return default_bg

    # Check episode assets
    episode_bg = episode_dir / "assets" / "studio-bg.png"
    if episode_bg.exists():
        return episode_bg

    logger.warning("no_background_found", searched=[str(default_bg), str(episode_bg)])
    return None


def _load_instructions(episode_dir: Path) -> dict:
    """Load episode-specific instructions."""
    instructions_file = episode_dir / "instructions.md"

    if not instructions_file.exists():
        return {}

    import yaml

    content = instructions_file.read_text()

    # Extract YAML frontmatter or simple key: value pairs
    result = {}

    # Check for skip directives
    if "skip:" in content.lower():
        lines = content.lower().split("\n")
        for line in lines:
            if "bg-removal" in line or "bg_removal" in line:
                result["skip_bg_removal"] = True

    # Check for custom background
    import re
    bg_match = re.search(r"bg_image:\s*(\S+)", content)
    if bg_match:
        result["bg_image"] = bg_match.group(1)

    return result


def _get_video_info(video_file: Path) -> dict:
    """Get video metadata."""
    import json

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
        "total_frames": 0,
        "duration": 0,
    }

    if result.returncode == 0:
        data = json.loads(result.stdout)

        # Get video stream info
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 1920)
                info["height"] = stream.get("height", 1080)

                # Parse frame rate
                fps_str = stream.get("r_frame_rate", "30/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    info["fps"] = float(num) / float(den) if float(den) > 0 else 30
                else:
                    info["fps"] = float(fps_str)

                info["total_frames"] = int(stream.get("nb_frames", 0))
                break

        # Get duration from format
        duration = float(data.get("format", {}).get("duration", 0))
        info["duration"] = duration

        # Estimate frames if not available
        if info["total_frames"] == 0 and duration > 0:
            info["total_frames"] = int(duration * info["fps"])

    return info


def _extract_audio(video_file: Path, output_file: Path) -> None:
    """Extract audio from video."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_file),
        "-vn",
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr}")
