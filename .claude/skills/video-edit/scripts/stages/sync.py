"""
Stage 1: Sync — Synchronize external audio with video

Detects sync point via clap detection or cross-correlation fallback.
Handles drift correction if needed.

Inputs:
    - video.mp4 (or .MOV/.mkv/.webm)
    - audio_externo.wav (optional, if external mic used)

Outputs:
    - audio_synced.wav (48kHz mono 24-bit)
"""

import subprocess
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal
from scipy.io import wavfile


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute sync stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    sync_config = config.get("sync", {})
    audio_config = config.get("audio", {})

    # Find video file
    video_file = _find_video_file(episode_dir)
    if not video_file:
        raise FileNotFoundError(f"No video file found in {episode_dir}")

    logger.info("sync_start", video_file=video_file.name)

    # Check for external audio
    external_audio = episode_dir / "audio_externo.wav"
    has_external = external_audio.exists()

    if has_external:
        logger.info("external_audio_found", path=str(external_audio))
    else:
        logger.info("no_external_audio", msg="Using embedded audio from video")

    # Extract camera audio
    camera_audio = episode_dir / "camera_audio.wav"
    _extract_audio(video_file, camera_audio, audio_config, logger)

    metrics = {
        "has_external_audio": has_external,
        "video_file": video_file.name,
    }

    if has_external:
        # Perform sync detection
        offset, confidence, method = _detect_sync_offset(
            camera_audio,
            external_audio,
            sync_config,
            logger,
        )

        metrics.update({
            "sync_offset_seconds": offset,
            "sync_confidence": confidence,
            "sync_method": method,
        })

        logger.info(
            "sync_detected",
            offset_seconds=f"{offset:.3f}",
            confidence=f"{confidence:.2f}",
            method=method,
        )

        # Check for drift
        drift = _detect_drift(
            camera_audio,
            external_audio,
            sync_config,
            logger,
        )

        metrics["drift_samples_per_min"] = drift

        if abs(drift) > sync_config.get("max_drift_samples_per_min", 1):
            logger.warning(
                "drift_detected",
                drift_samples_per_min=drift,
                msg="Applying resample correction",
            )
            metrics["drift_corrected"] = True

        # Apply sync offset and create output
        output_file = episode_dir / "audio_synced.wav"
        _apply_sync(
            external_audio,
            output_file,
            offset,
            drift if abs(drift) > sync_config.get("max_drift_samples_per_min", 1) else 0,
            audio_config,
            logger,
        )
    else:
        # No external audio — just extract and normalize camera audio
        output_file = episode_dir / "audio_synced.wav"
        shutil.copy(camera_audio, output_file)
        metrics.update({
            "sync_offset_seconds": 0,
            "sync_confidence": 1.0,
            "sync_method": "embedded",
        })

    # Cleanup temp files
    if camera_audio.exists() and has_external:
        camera_audio.unlink()

    logger.info("sync_complete", output=output_file.name)

    return ["audio_synced.wav"], metrics


def _find_video_file(episode_dir: Path) -> Path | None:
    """Find video file in episode directory."""
    extensions = [".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".webm"]
    for ext in extensions:
        video = episode_dir / f"video{ext}"
        if video.exists():
            return video
    # Try any video file
    for ext in extensions:
        videos = list(episode_dir.glob(f"*{ext}"))
        if videos:
            return videos[0]
    return None


def _extract_audio(
    video_file: Path,
    output_file: Path,
    audio_config: dict,
    logger: Any,
) -> None:
    """Extract audio from video file."""
    sample_rate = audio_config.get("sample_rate", 48000)
    channels = audio_config.get("channels", 1)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_file),
        "-vn",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("extract_audio", cmd=" ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")


def _detect_sync_offset(
    camera_audio: Path,
    external_audio: Path,
    sync_config: dict,
    logger: Any,
) -> tuple[float, float, str]:
    """
    Detect sync offset between camera and external audio.

    Returns:
        Tuple of (offset_seconds, confidence, method)
    """
    clap_window = sync_config.get("clap_search_window", 30)
    clap_highpass = sync_config.get("clap_highpass_hz", 2000)
    clap_min_amp = sync_config.get("clap_min_amplitude", 0.8)
    xcorr_window = sync_config.get("xcorr_window", 60)

    # Load audio files
    cam_sr, cam_data = wavfile.read(camera_audio)
    ext_sr, ext_data = wavfile.read(external_audio)

    # Ensure same sample rate
    if cam_sr != ext_sr:
        raise ValueError(f"Sample rate mismatch: camera={cam_sr}, external={ext_sr}")

    # Convert to float
    cam_float = cam_data.astype(np.float32) / np.iinfo(cam_data.dtype).max
    ext_float = ext_data.astype(np.float32) / np.iinfo(ext_data.dtype).max

    # Mono if needed
    if len(cam_float.shape) > 1:
        cam_float = cam_float.mean(axis=1)
    if len(ext_float.shape) > 1:
        ext_float = ext_float.mean(axis=1)

    # Try clap detection first
    clap_samples = int(clap_window * cam_sr)
    cam_window = cam_float[:clap_samples]
    ext_window = ext_float[:clap_samples]

    # Apply highpass filter for clap detection
    nyq = cam_sr / 2
    b, a = signal.butter(4, clap_highpass / nyq, btype='high')
    cam_hp = signal.filtfilt(b, a, cam_window)
    ext_hp = signal.filtfilt(b, a, ext_window)

    # Normalize
    cam_hp = cam_hp / (np.abs(cam_hp).max() + 1e-10)
    ext_hp = ext_hp / (np.abs(ext_hp).max() + 1e-10)

    # Find peaks
    cam_peak_idx = np.argmax(np.abs(cam_hp))
    ext_peak_idx = np.argmax(np.abs(ext_hp))
    cam_peak_val = np.abs(cam_hp[cam_peak_idx])
    ext_peak_val = np.abs(ext_hp[ext_peak_idx])

    logger.debug(
        "clap_detection",
        cam_peak=f"{cam_peak_val:.3f}",
        ext_peak=f"{ext_peak_val:.3f}",
        threshold=clap_min_amp,
    )

    if cam_peak_val >= clap_min_amp and ext_peak_val >= clap_min_amp:
        # Clap detected
        offset_samples = ext_peak_idx - cam_peak_idx
        offset_seconds = offset_samples / cam_sr
        confidence = min(cam_peak_val, ext_peak_val)
        return offset_seconds, confidence, "clap"

    # Fallback: cross-correlation
    logger.info("clap_fallback", msg="Using cross-correlation")

    xcorr_samples = int(xcorr_window * cam_sr)
    cam_xcorr = cam_float[:xcorr_samples]
    ext_xcorr = ext_float[:xcorr_samples]

    correlation = signal.correlate(ext_xcorr, cam_xcorr, mode='full')
    lags = signal.correlation_lags(len(ext_xcorr), len(cam_xcorr), mode='full')

    max_idx = np.argmax(correlation)
    offset_samples = lags[max_idx]
    offset_seconds = offset_samples / cam_sr

    # Confidence from correlation peak
    confidence = correlation[max_idx] / (len(cam_xcorr) * np.std(cam_xcorr) * np.std(ext_xcorr) + 1e-10)
    confidence = min(1.0, max(0.0, confidence))

    return offset_seconds, confidence, "xcorr"


def _detect_drift(
    camera_audio: Path,
    external_audio: Path,
    sync_config: dict,
    logger: Any,
) -> float:
    """
    Detect clock drift by comparing correlation at multiple points.

    Returns:
        Drift in samples per minute
    """
    # Load audio
    cam_sr, cam_data = wavfile.read(camera_audio)
    _, ext_data = wavfile.read(external_audio)

    cam_float = cam_data.astype(np.float32) / np.iinfo(cam_data.dtype).max
    ext_float = ext_data.astype(np.float32) / np.iinfo(ext_data.dtype).max

    if len(cam_float.shape) > 1:
        cam_float = cam_float.mean(axis=1)
    if len(ext_float.shape) > 1:
        ext_float = ext_float.mean(axis=1)

    # Check drift at 1min intervals over first 10 minutes
    window_size = int(60 * cam_sr)  # 1 min window
    max_check_time = int(min(10 * 60, len(cam_float) / cam_sr - 60))  # Up to 10 min

    if max_check_time < 2:
        return 0.0  # Audio too short to detect drift

    offsets = []
    for minute in range(0, max_check_time, 60):
        start = int(minute * cam_sr)
        end = start + window_size

        if end > len(cam_float) or end > len(ext_float):
            break

        cam_chunk = cam_float[start:end]
        ext_chunk = ext_float[start:end]

        correlation = signal.correlate(ext_chunk, cam_chunk, mode='full')
        lags = signal.correlation_lags(len(ext_chunk), len(cam_chunk), mode='full')

        max_idx = np.argmax(correlation)
        offset = lags[max_idx]
        offsets.append((minute, offset))

    if len(offsets) < 2:
        return 0.0

    # Linear regression to find drift
    minutes = np.array([o[0] / 60 for o in offsets])
    samples = np.array([o[1] for o in offsets])

    if len(minutes) > 1:
        slope, _ = np.polyfit(minutes, samples, 1)
        return slope  # samples per minute
    return 0.0


def _apply_sync(
    input_file: Path,
    output_file: Path,
    offset_seconds: float,
    drift_samples_per_min: float,
    audio_config: dict,
    logger: Any,
) -> None:
    """Apply sync offset and drift correction."""
    sample_rate = audio_config.get("sample_rate", 48000)

    filters = []

    # Apply offset
    if offset_seconds > 0:
        # External audio is ahead — trim start
        filters.append(f"atrim=start={offset_seconds}")
    elif offset_seconds < 0:
        # External audio is behind — add silence at start
        delay_ms = int(abs(offset_seconds) * 1000)
        filters.append(f"adelay={delay_ms}|{delay_ms}")

    # Apply drift correction via resample
    if abs(drift_samples_per_min) > 0:
        # Calculate correction factor
        # If drift is positive (ext faster), we need to slow it down
        correction = 1.0 - (drift_samples_per_min / (60 * sample_rate))
        filters.append(f"aresample={int(sample_rate * correction)}:resampler=soxr")
        filters.append(f"aresample={sample_rate}")

    filter_chain = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-af", filter_chain,
        "-ar", str(sample_rate),
        "-ac", str(audio_config.get("channels", 1)),
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("apply_sync", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg sync failed: {result.stderr}")
