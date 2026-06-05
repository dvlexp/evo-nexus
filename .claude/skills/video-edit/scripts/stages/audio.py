"""
Stage 2: Audio — Denoise, EQ, and normalize audio

Applies DeepFilterNet for noise reduction, EQ for voice optimization,
and normalizes to -14 LUFS for YouTube.

Inputs:
    - audio_synced.wav

Outputs:
    - audio_final.wav (48kHz mono 24-bit, -14 LUFS)
"""

import subprocess
import shutil
from pathlib import Path
from typing import Any


def run(
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger: Any,
) -> tuple[list[str], dict]:
    """
    Execute audio stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    audio_config = config.get("audio", {})
    denoise_config = config.get("denoise", {})
    eq_config = config.get("eq", {})

    input_file = episode_dir / "audio_synced.wav"
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    logger.info("audio_start", input=input_file.name)

    metrics = {}

    # Step 1: Measure input noise floor
    input_stats = _measure_audio_stats(input_file, logger)
    metrics["input_lufs"] = input_stats.get("lufs", -99)
    metrics["input_noise_floor_db"] = input_stats.get("noise_floor_db", -99)

    logger.info(
        "input_stats",
        lufs=f"{metrics['input_lufs']:.1f}",
        noise_floor=f"{metrics['input_noise_floor_db']:.1f}dB",
    )

    # Step 2: DeepFilterNet denoise
    denoised_file = episode_dir / "audio_denoised.wav"
    _apply_deepfilter(input_file, denoised_file, denoise_config, logger)

    # Measure noise reduction
    denoised_stats = _measure_audio_stats(denoised_file, logger)
    noise_reduction = metrics["input_noise_floor_db"] - denoised_stats.get("noise_floor_db", -99)
    metrics["noise_reduction_db"] = noise_reduction

    logger.info("denoise_complete", noise_reduction_db=f"{noise_reduction:.1f}")

    # Step 3: EQ and compression
    eq_file = episode_dir / "audio_eq.wav"
    _apply_eq_compression(denoised_file, eq_file, eq_config, audio_config, logger)

    # Step 4: Normalize to -14 LUFS
    output_file = episode_dir / "audio_final.wav"
    _normalize_lufs(eq_file, output_file, audio_config, logger)

    # Measure final stats
    final_stats = _measure_audio_stats(output_file, logger)
    metrics["output_lufs"] = final_stats.get("lufs", -99)
    metrics["output_true_peak_dbtp"] = final_stats.get("true_peak_dbtp", 0)

    # Validate LUFS
    target_lufs = audio_config.get("target_lufs", -14)
    tolerance = audio_config.get("lufs_tolerance", 0.5)
    lufs_ok = abs(metrics["output_lufs"] - target_lufs) <= tolerance

    if not lufs_ok:
        logger.warning(
            "lufs_out_of_range",
            measured=metrics["output_lufs"],
            target=target_lufs,
            tolerance=tolerance,
        )
    else:
        logger.info(
            "lufs_validated",
            measured=f"{metrics['output_lufs']:.1f}",
            target=target_lufs,
        )

    metrics["lufs_validated"] = lufs_ok

    # Cleanup temp files
    for temp in [denoised_file, eq_file]:
        if temp.exists():
            temp.unlink()

    logger.info("audio_complete", output=output_file.name)

    return ["audio_final.wav"], metrics


def _measure_audio_stats(audio_file: Path, logger: Any) -> dict:
    """Measure LUFS, true peak, and noise floor."""
    cmd = [
        "ffmpeg",
        "-i", str(audio_file),
        "-af", "loudnorm=print_format=json",
        "-f", "null",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    stats = {}

    # Parse loudnorm output from stderr
    stderr = result.stderr
    if "input_i" in stderr:
        import re
        import json

        # Find JSON block
        json_match = re.search(r'\{[^}]+\}', stderr, re.DOTALL)
        if json_match:
            try:
                loudnorm_data = json.loads(json_match.group())
                stats["lufs"] = float(loudnorm_data.get("input_i", -99))
                stats["true_peak_dbtp"] = float(loudnorm_data.get("input_tp", 0))
                stats["lra"] = float(loudnorm_data.get("input_lra", 0))
            except (json.JSONDecodeError, ValueError):
                pass

    # Measure noise floor (RMS of silent parts)
    # Use volumedetect for a rough estimate
    vol_cmd = [
        "ffmpeg",
        "-i", str(audio_file),
        "-af", "volumedetect",
        "-f", "null",
        "-",
    ]

    vol_result = subprocess.run(vol_cmd, capture_output=True, text=True)
    import re
    mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", vol_result.stderr)
    if mean_match:
        stats["mean_volume_db"] = float(mean_match.group(1))

    # Estimate noise floor from quiet sections (simplified)
    stats["noise_floor_db"] = stats.get("mean_volume_db", -40) - 20

    return stats


def _apply_deepfilter(
    input_file: Path,
    output_file: Path,
    denoise_config: dict,
    logger: Any,
) -> None:
    """Apply DeepFilterNet noise reduction."""
    # Check if deepFilter is available
    which_result = subprocess.run(
        ["which", "deep-filter"],
        capture_output=True,
        text=True,
    )

    if which_result.returncode != 0:
        # Try alternative command name
        which_result = subprocess.run(
            ["which", "deepFilter"],
            capture_output=True,
            text=True,
        )

    if which_result.returncode != 0:
        logger.warning(
            "deepfilter_not_found",
            msg="DeepFilterNet not installed, skipping denoise",
        )
        shutil.copy(input_file, output_file)
        return

    cmd_name = which_result.stdout.strip()
    attenuation = denoise_config.get("attenuation_limit", 100)

    cmd = [
        cmd_name,
        str(input_file),
        "-o", str(output_file),
        "--atten-lim", str(attenuation),
    ]

    logger.debug("deepfilter_cmd", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.warning(
            "deepfilter_failed",
            error=result.stderr,
            msg="Falling back to ffmpeg anlmdn filter",
        )
        # Fallback: use ffmpeg's built-in noise reduction
        _apply_ffmpeg_denoise(input_file, output_file, logger)


def _apply_ffmpeg_denoise(input_file: Path, output_file: Path, logger: Any) -> None:
    """Fallback denoise using ffmpeg's anlmdn filter."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-af", "anlmdn=s=7:p=0.002:r=0.002:m=15",
        str(output_file),
    ]

    logger.debug("ffmpeg_denoise", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg denoise failed: {result.stderr}")


def _apply_eq_compression(
    input_file: Path,
    output_file: Path,
    eq_config: dict,
    audio_config: dict,
    logger: Any,
) -> None:
    """Apply EQ and compression for voice optimization."""
    # Build filter chain
    filters = []

    # High-pass filter (remove rumble)
    highpass = eq_config.get("highpass_hz", 80)
    filters.append(f"highpass=f={highpass}")

    # Low-shelf cut at 200Hz
    lowshelf_hz = eq_config.get("lowshelf_hz", 200)
    lowshelf_gain = eq_config.get("lowshelf_gain_db", -2)
    filters.append(f"equalizer=f={lowshelf_hz}:t=q:w=1:g={lowshelf_gain}")

    # Presence boost at 3kHz
    presence_hz = eq_config.get("presence_hz", 3000)
    presence_gain = eq_config.get("presence_gain_db", 2)
    filters.append(f"equalizer=f={presence_hz}:t=q:w=1:g={presence_gain}")

    # Compressor
    threshold = eq_config.get("compressor_threshold_db", -18)
    ratio = eq_config.get("compressor_ratio", 3)
    attack = eq_config.get("compressor_attack_ms", 5)
    release = eq_config.get("compressor_release_ms", 50)
    filters.append(
        f"acompressor=threshold={threshold}dB:ratio={ratio}:attack={attack}:release={release}"
    )

    filter_chain = ",".join(filters)

    sample_rate = audio_config.get("sample_rate", 48000)
    channels = audio_config.get("channels", 1)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-af", filter_chain,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("eq_compression", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg EQ/compression failed: {result.stderr}")


def _normalize_lufs(
    input_file: Path,
    output_file: Path,
    audio_config: dict,
    logger: Any,
) -> None:
    """Normalize to target LUFS using ffmpeg-normalize."""
    target_lufs = audio_config.get("target_lufs", -14)
    true_peak = audio_config.get("true_peak_dbtp", -1)
    sample_rate = audio_config.get("sample_rate", 48000)

    # Check if ffmpeg-normalize is available
    which_result = subprocess.run(
        ["which", "ffmpeg-normalize"],
        capture_output=True,
        text=True,
    )

    if which_result.returncode == 0:
        # Use ffmpeg-normalize
        cmd = [
            "ffmpeg-normalize",
            str(input_file),
            "-o", str(output_file),
            "-t", str(target_lufs),
            "-tp", str(true_peak),
            "--keep-loudness-range-target",
            "-ar", str(sample_rate),
            "-c:a", "pcm_s24le",
            "-f",
        ]

        logger.debug("normalize", cmd=" ".join(cmd))

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.warning(
                "ffmpeg_normalize_failed",
                error=result.stderr,
                msg="Falling back to ffmpeg loudnorm",
            )
            _normalize_lufs_ffmpeg(input_file, output_file, audio_config, logger)
    else:
        # Fallback to ffmpeg loudnorm
        logger.info("ffmpeg_normalize_not_found", msg="Using ffmpeg loudnorm directly")
        _normalize_lufs_ffmpeg(input_file, output_file, audio_config, logger)


def _normalize_lufs_ffmpeg(
    input_file: Path,
    output_file: Path,
    audio_config: dict,
    logger: Any,
) -> None:
    """Fallback LUFS normalization using ffmpeg's loudnorm filter."""
    target_lufs = audio_config.get("target_lufs", -14)
    true_peak = audio_config.get("true_peak_dbtp", -1)
    sample_rate = audio_config.get("sample_rate", 48000)

    # Two-pass loudnorm for accurate results
    # First pass: analyze
    analyze_cmd = [
        "ffmpeg",
        "-i", str(input_file),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:print_format=json",
        "-f", "null",
        "-",
    ]

    result = subprocess.run(analyze_cmd, capture_output=True, text=True)

    # Parse analysis results
    import re
    import json

    measured_params = {}
    json_match = re.search(r'\{[^}]+\}', result.stderr, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            measured_params = {
                "measured_I": data.get("input_i", -24),
                "measured_TP": data.get("input_tp", -2),
                "measured_LRA": data.get("input_lra", 7),
                "measured_thresh": data.get("input_thresh", -34),
            }
        except json.JSONDecodeError:
            pass

    # Second pass: apply with measured values
    if measured_params:
        loudnorm_filter = (
            f"loudnorm=I={target_lufs}:TP={true_peak}"
            f":measured_I={measured_params['measured_I']}"
            f":measured_TP={measured_params['measured_TP']}"
            f":measured_LRA={measured_params['measured_LRA']}"
            f":measured_thresh={measured_params['measured_thresh']}"
            f":linear=true"
        )
    else:
        loudnorm_filter = f"loudnorm=I={target_lufs}:TP={true_peak}:linear=false"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-af", loudnorm_filter,
        "-ar", str(sample_rate),
        "-c:a", "pcm_s24le",
        str(output_file),
    ]

    logger.debug("loudnorm", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm failed: {result.stderr}")
