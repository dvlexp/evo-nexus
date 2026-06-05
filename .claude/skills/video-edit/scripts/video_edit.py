#!/usr/bin/env python3
"""
Video Edit Pipeline — Main Entry Point
Processes raw YouTube episodes through a 9-stage pipeline.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

# Import pipeline modules
from checkpoint import CheckpointManager, STAGES, validate_stage
from logging_setup import (
    setup_logging,
    log_stage_start,
    log_stage_end,
    log_stage_error,
    log_pipeline_end,
)
from stages import get_stage_module


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="video_edit",
        description="Video Edit Pipeline — Post-production for YouTube videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Stages (in order):
  1. sync           Sync external audio with video (clap detection)
  2. audio          DeepFilterNet denoise + EQ + normalize -14 LUFS
  3. transcribe     WhisperX word-level timestamps PT-BR
  4. cut-fillers    Remove filler words PT-BR (≥250ms)
  5. cut-silence    Remove silences (>800ms) via auto-editor
  6. bg-removal     MediaPipe segmentation + composite background
  7. motion-graphics Overlay motion graphics from markers
  8. sfx            Mix SFX from markers
  9. render         H.264 16:9 + 9:16 Shorts

Examples:
  # Process episode
  python video_edit.py /path/to/episode/

  # Resume from a specific stage
  python video_edit.py /path/to/episode/ --resume-from bg-removal

  # Skip optional stages
  python video_edit.py /path/to/episode/ --skip bg-removal,motion-graphics

  # Preview mode (5min @ 540p)
  python video_edit.py /path/to/episode/ --preview
""",
    )

    parser.add_argument(
        "episode_dir",
        type=Path,
        help="Path to episode directory containing video.mp4",
    )

    parser.add_argument(
        "--resume-from",
        type=str,
        dest="resume_from",
        metavar="STAGE",
        help="Resume from this stage (skips earlier completed stages)",
    )

    parser.add_argument(
        "--skip",
        type=str,
        help="Comma-separated stages to skip (e.g., bg-removal,motion-graphics)",
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 5min @ 540p, skips heavy stages",
    )

    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Custom config file (default: config/defaults.yaml)",
    )

    parser.add_argument(
        "--cloud-bg-removal",
        type=str,
        choices=["runpod", "colab"],
        dest="cloud_bg_removal",
        metavar="PROVIDER",
        help="Use cloud GPU for BG removal (not implemented in v1)",
    )

    parser.add_argument(
        "--audio-offset",
        type=float,
        dest="audio_offset",
        metavar="SECONDS",
        help="Force manual sync offset (fallback when auto-detect fails)",
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset pipeline state and start fresh",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be done without executing",
    )

    return parser.parse_args()


def validate_episode_dir(episode_dir: Path) -> bool:
    """Validate that episode directory exists and has required files."""
    if not episode_dir.exists():
        print(f"Error: Episode directory does not exist: {episode_dir}")
        return False

    if not episode_dir.is_dir():
        print(f"Error: Not a directory: {episode_dir}")
        return False

    # Check for video file
    video_file = episode_dir / "video.mp4"
    if not video_file.exists():
        # Try alternative names
        alternatives = ["video.MOV", "video.mkv", "video.webm"]
        found = False
        for alt in alternatives:
            if (episode_dir / alt).exists():
                found = True
                break
        if not found:
            print(f"Warning: video.mp4 not found in {episode_dir}")
            # Not a fatal error — user might add it later

    return True


def run_stage(
    stage: str,
    episode_dir: Path,
    config: dict,
    preview: bool,
    logger,
) -> tuple[list[str], dict]:
    """
    Run a stage using the registered stage module.

    Returns:
        Tuple of (artifacts list, metrics dict)
    """
    stage_module = get_stage_module(stage)

    if stage_module is None:
        raise RuntimeError(f"Stage module not found: {stage}")

    # Call the stage's run function
    return stage_module.run(
        episode_dir=episode_dir,
        config=config,
        preview=preview,
        logger=logger,
    )


def load_config(config_path: Optional[Path]) -> dict:
    """Load configuration from YAML file."""
    import yaml

    # Default config location
    skill_dir = Path(__file__).parent.parent
    default_config = skill_dir / "config" / "defaults.yaml"

    config_file = config_path if config_path else default_config

    if not config_file.exists():
        print(f"Warning: Config file not found: {config_file}")
        return {}

    with open(config_file, "r") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Validate episode directory
    if not validate_episode_dir(args.episode_dir):
        return 1

    # Cloud BG removal not implemented in v1
    if args.cloud_bg_removal:
        print(f"Error: --cloud-bg-removal={args.cloud_bg_removal} is not implemented in v1")
        print("Use local CPU processing or wait for v2")
        return 1

    # Validate resume-from stage
    if args.resume_from and not validate_stage(args.resume_from):
        print(f"Error: Unknown stage: {args.resume_from}")
        print(f"Valid stages: {', '.join(STAGES)}")
        return 1

    # Parse skip stages
    skip_stages = []
    if args.skip:
        skip_stages = [s.strip() for s in args.skip.split(",")]
        for stage in skip_stages:
            if not validate_stage(stage):
                print(f"Error: Unknown stage in --skip: {stage}")
                print(f"Valid stages: {', '.join(STAGES)}")
                return 1

    # Preview mode adds default skips
    if args.preview:
        preview_skips = ["bg-removal", "motion-graphics"]
        skip_stages = list(set(skip_stages + preview_skips))

    # Load config
    config = load_config(args.config)

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    args.episode_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(args.episode_dir, level=log_level)

    # Initialize checkpoint manager
    checkpoint = CheckpointManager(args.episode_dir)

    # Reset if requested
    if args.reset:
        logger.info("reset_requested", episode_dir=str(args.episode_dir))
        checkpoint.reset()

    # Get stages to run
    stages_to_run = checkpoint.get_stages_to_run(
        resume_from=args.resume_from,
        skip=skip_stages,
    )

    # Mark skipped stages
    for stage in skip_stages:
        if stage not in stages_to_run:
            checkpoint.mark_skipped(stage, reason="user skip list")

    logger.info(
        "pipeline_start",
        episode_dir=str(args.episode_dir),
        stages_to_run=stages_to_run,
        skipped_stages=skip_stages,
        preview_mode=args.preview,
        resume_from=args.resume_from,
    )

    if args.dry_run:
        print("\n=== DRY RUN ===")
        print(f"Episode: {args.episode_dir}")
        print(f"Stages to run: {', '.join(stages_to_run)}")
        print(f"Skipped: {', '.join(skip_stages) or '(none)'}")
        print(f"Preview mode: {args.preview}")
        print(f"Config: {args.config or 'defaults.yaml'}")
        return 0

    # Run pipeline
    pipeline_start = time.time()
    stages_completed = []
    success = True

    for stage in stages_to_run:
        log_stage_start(logger, stage)
        checkpoint.mark_started(stage)

        stage_start = time.time()
        try:
            # Run the stage
            artifacts, metrics = run_stage(
                stage=stage,
                episode_dir=args.episode_dir,
                config=config,
                preview=args.preview,
                logger=logger,
            )

            duration = time.time() - stage_start
            log_stage_end(logger, stage, duration, artifacts, metrics)
            checkpoint.mark_done(stage, artifacts, metrics)
            stages_completed.append(stage)

        except Exception as e:
            duration = time.time() - stage_start
            log_stage_error(logger, stage, e, duration)
            checkpoint.mark_failed(stage, str(e))
            logger.error("pipeline_abort", stage=stage, error=str(e))
            success = False
            break

    # Pipeline complete
    total_duration = time.time() - pipeline_start
    final_outputs = checkpoint.get_artifacts("render") if "render" in stages_completed else []

    log_pipeline_end(
        logger,
        success=success,
        total_duration_seconds=total_duration,
        stages_completed=stages_completed,
        final_outputs=final_outputs,
    )

    # Print summary
    summary = checkpoint.get_summary()
    print("\n=== Pipeline Summary ===")
    print(f"Episode: {summary['episode_dir']}")
    print(f"Progress: {summary['progress']}")
    print(f"Completed: {', '.join(summary['completed']) or '(none)'}")
    print(f"Skipped: {', '.join(summary['skipped']) or '(none)'}")
    print(f"Failed: {', '.join(summary['failed']) or '(none)'}")
    print(f"Duration: {total_duration:.1f}s")

    if success and "render" in stages_completed:
        print("\n=== Outputs ===")
        for output in final_outputs:
            print(f"  {args.episode_dir / output}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
