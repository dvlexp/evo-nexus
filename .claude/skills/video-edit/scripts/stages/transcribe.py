"""
Stage 3: Transcribe — Word-level transcription with WhisperX

Generates transcript.json with word-level timestamps for PT-BR.
Supports fallback to whisper.cpp if WhisperX fails.

Inputs:
    - audio_final.wav

Outputs:
    - transcript.json
"""

import json
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
    Execute transcribe stage.

    Returns:
        Tuple of (artifact filenames, metrics dict)
    """
    transcription_config = config.get("transcription", {})

    input_file = episode_dir / "audio_final.wav"
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    logger.info("transcribe_start", input=input_file.name)

    metrics = {}

    # Get audio duration
    duration = _get_audio_duration(input_file)
    metrics["audio_duration_seconds"] = duration

    logger.info("audio_duration", seconds=f"{duration:.1f}")

    # Try faster-whisper first (primary — no pyannote dependency, word-level native)
    output_file = episode_dir / "transcript.json"
    method = None

    try:
        transcript = _transcribe_faster_whisper(
            input_file,
            transcription_config,
            logger,
        )
        method = "faster-whisper"
    except Exception as e:
        logger.warning("faster_whisper_failed", error=str(e), msg="Falling back to WhisperX")
        try:
            transcript = _transcribe_whisperx(
                input_file,
                transcription_config,
                logger,
            )
            method = "whisperx"
        except Exception as e2:
            logger.warning("whisperx_failed", error=str(e2), msg="Falling back to whisper.cpp")
            try:
                transcript = _transcribe_whisper_cpp(
                    input_file,
                    transcription_config,
                    logger,
                )
                method = "whisper.cpp"
            except Exception as e3:
                logger.error("transcription_failed", errors=[str(e), str(e2), str(e3)])
                raise RuntimeError(f"All transcription methods failed. faster-whisper: {e}, WhisperX: {e2}, whisper.cpp: {e3}")

    # Validate transcript structure
    if not _validate_transcript(transcript):
        raise ValueError("Invalid transcript structure")

    # Calculate metrics
    total_words = sum(len(seg.get("words", [])) for seg in transcript.get("segments", []))
    metrics["total_words"] = total_words
    metrics["total_segments"] = len(transcript.get("segments", []))
    metrics["method"] = method
    metrics["words_per_minute"] = (total_words / (duration / 60)) if duration > 0 else 0

    logger.info(
        "transcribe_stats",
        total_words=total_words,
        total_segments=metrics["total_segments"],
        words_per_minute=f"{metrics['words_per_minute']:.1f}",
        method=method,
    )

    # Write transcript
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

    logger.info("transcribe_complete", output=output_file.name)

    return ["transcript.json"], metrics


def _get_audio_duration(audio_file: Path) -> float:
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
        import json as json_lib
        data = json_lib.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))

    return 0.0


def _transcribe_faster_whisper(
    audio_file: Path,
    config: dict,
    logger: Any,
) -> dict:
    """Primary transcription using faster-whisper (CTranslate2, CPU, word-level)."""
    from faster_whisper import WhisperModel

    model_size = config.get("model_size", "medium")
    language = config.get("language", "pt")
    compute_type = config.get("compute_type", "int8")

    logger.info("faster_whisper_loading", model=model_size, compute_type=compute_type)

    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    logger.info("faster_whisper_transcribing")
    segments_gen, info = model.transcribe(
        str(audio_file),
        language=language,
        word_timestamps=True,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    transcript = {"segments": [], "language": language, "model": model_size}

    for segment in segments_gen:
        seg_data = {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
            "words": [],
        }
        if segment.words:
            for word in segment.words:
                seg_data["words"].append({
                    "start": word.start,
                    "end": word.end,
                    "word": word.word.strip(),
                    "score": round(word.probability, 4),
                })
        transcript["segments"].append(seg_data)

    logger.info("faster_whisper_complete", segments=len(transcript["segments"]))
    return transcript


def _transcribe_whisperx(
    audio_file: Path,
    config: dict,
    logger: Any,
) -> dict:
    """Transcribe using WhisperX with word-level alignment."""
    try:
        import whisperx
    except ImportError:
        raise RuntimeError("WhisperX not installed. Run: pip install whisperx")

    model_size = config.get("model_size", "medium")
    language = config.get("language", "pt")
    compute_type = config.get("compute_type", "int8")
    device = config.get("device", "cpu")
    batch_size = config.get("batch_size", 8)

    logger.info(
        "whisperx_loading",
        model=model_size,
        device=device,
        compute_type=compute_type,
    )

    # Load model
    model = whisperx.load_model(
        model_size,
        device=device,
        compute_type=compute_type,
        language=language,
    )

    # Load audio
    audio = whisperx.load_audio(str(audio_file))

    # Transcribe
    logger.info("whisperx_transcribing")
    result = model.transcribe(audio, batch_size=batch_size, language=language)

    # Load alignment model
    logger.info("whisperx_aligning")
    align_model, align_metadata = whisperx.load_align_model(
        language_code=language,
        device=device,
    )

    # Align
    result = whisperx.align(
        result["segments"],
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    # Convert to our format
    transcript = {
        "segments": [],
        "language": language,
        "model": model_size,
    }

    for segment in result.get("segments", []):
        seg_data = {
            "start": segment.get("start", 0),
            "end": segment.get("end", 0),
            "text": segment.get("text", "").strip(),
            "words": [],
        }

        for word in segment.get("words", []):
            word_data = {
                "start": word.get("start", 0),
                "end": word.get("end", 0),
                "word": word.get("word", "").strip(),
                "score": word.get("score", 0),
            }
            seg_data["words"].append(word_data)

        transcript["segments"].append(seg_data)

    return transcript


def _transcribe_whisper_cpp(
    audio_file: Path,
    config: dict,
    logger: Any,
) -> dict:
    """Fallback transcription using whisper.cpp."""
    # Check for whisper.cpp
    whisper_path = shutil.which("whisper") or shutil.which("main")

    if not whisper_path:
        # Try common install locations
        common_paths = [
            Path.home() / "whisper.cpp" / "main",
            Path("/usr/local/bin/whisper"),
            Path.home() / ".local" / "bin" / "whisper",
        ]
        for p in common_paths:
            if p.exists():
                whisper_path = str(p)
                break

    if not whisper_path:
        raise RuntimeError("whisper.cpp not found")

    # Find model
    model_size = config.get("model_size", "medium")
    model_paths = [
        Path.home() / ".cache" / "whisper" / f"ggml-{model_size}.bin",
        Path.home() / "whisper.cpp" / "models" / f"ggml-{model_size}.bin",
        Path(f"/usr/share/whisper/models/ggml-{model_size}.bin"),
    ]

    model_path = None
    for p in model_paths:
        if p.exists():
            model_path = str(p)
            break

    if not model_path:
        raise RuntimeError(f"whisper.cpp model not found: ggml-{model_size}.bin")

    # Convert to 16kHz WAV (whisper.cpp requirement)
    temp_wav = audio_file.parent / "temp_whisper.wav"
    convert_cmd = [
        "ffmpeg",
        "-y",
        "-i", str(audio_file),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(temp_wav),
    ]

    subprocess.run(convert_cmd, capture_output=True, check=True)

    # Run whisper.cpp with JSON output
    output_json = audio_file.parent / "whisper_output.json"

    cmd = [
        whisper_path,
        "-m", model_path,
        "-f", str(temp_wav),
        "-l", config.get("language", "pt"),
        "--output-json",
        "-of", str(output_json.with_suffix("")),
        "--word-timestamps",
    ]

    logger.info("whisper_cpp_transcribing", cmd=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp file
    if temp_wav.exists():
        temp_wav.unlink()

    if result.returncode != 0:
        raise RuntimeError(f"whisper.cpp failed: {result.stderr}")

    # Read output
    if not output_json.exists():
        raise RuntimeError("whisper.cpp did not produce output")

    with open(output_json, "r", encoding="utf-8") as f:
        whisper_data = json.load(f)

    # Clean up output file
    output_json.unlink()

    # Convert to our format
    transcript = {
        "segments": [],
        "language": config.get("language", "pt"),
        "model": f"ggml-{model_size}",
    }

    for segment in whisper_data.get("transcription", []):
        seg_data = {
            "start": segment.get("offsets", {}).get("from", 0) / 1000.0,
            "end": segment.get("offsets", {}).get("to", 0) / 1000.0,
            "text": segment.get("text", "").strip(),
            "words": [],
        }

        for token in segment.get("tokens", []):
            if token.get("text", "").strip():
                word_data = {
                    "start": token.get("offsets", {}).get("from", 0) / 1000.0,
                    "end": token.get("offsets", {}).get("to", 0) / 1000.0,
                    "word": token.get("text", "").strip(),
                    "score": token.get("p", 0),
                }
                seg_data["words"].append(word_data)

        transcript["segments"].append(seg_data)

    return transcript


def _validate_transcript(transcript: dict) -> bool:
    """Validate transcript structure."""
    if not isinstance(transcript, dict):
        return False

    if "segments" not in transcript:
        return False

    segments = transcript["segments"]
    if not isinstance(segments, list):
        return False

    for seg in segments:
        if not isinstance(seg, dict):
            return False
        if "start" not in seg or "end" not in seg or "text" not in seg:
            return False
        if "words" not in seg:
            return False
        for word in seg.get("words", []):
            if not isinstance(word, dict):
                return False
            if "start" not in word or "end" not in word or "word" not in word:
                return False

    return True
