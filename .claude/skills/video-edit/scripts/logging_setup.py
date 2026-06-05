"""
Video Edit Pipeline — Logging Setup
Structured logging with Rich console + file output
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import structlog
from rich.console import Console
from rich.logging import RichHandler


def setup_logging(
    episode_dir: Path,
    level: str = "INFO",
    console_output: bool = True,
) -> structlog.BoundLogger:
    """
    Configure structured logging for the video edit pipeline.

    Args:
        episode_dir: Directory where pipeline.log will be written
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        console_output: Whether to also output to console

    Returns:
        Configured structlog logger
    """
    log_file = episode_dir / "pipeline.log"
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Reset any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers = []

    handlers = []

    # File handler — always enabled
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    )
    handlers.append(file_handler)

    # Console handler — Rich for pretty output
    if console_output:
        console = Console(stderr=True)
        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        rich_handler.setLevel(numeric_level)
        handlers.append(rich_handler)

    logging.basicConfig(level=numeric_level, handlers=handlers)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger("video-edit")

    # Write session start marker
    logger.info(
        "pipeline_session_start",
        episode_dir=str(episode_dir),
        timestamp=datetime.now().isoformat(),
        python_version=sys.version,
    )

    return logger


def log_stage_start(logger: structlog.BoundLogger, stage: str) -> None:
    """Log the start of a pipeline stage."""
    logger.info(
        "stage_start",
        stage=stage,
        timestamp=datetime.now().isoformat(),
    )


def log_stage_end(
    logger: structlog.BoundLogger,
    stage: str,
    duration_seconds: float,
    artifacts: list[str],
    metrics: Optional[dict] = None,
) -> None:
    """Log the completion of a pipeline stage."""
    log_data = {
        "stage": stage,
        "duration_seconds": round(duration_seconds, 2),
        "artifacts": artifacts,
        "timestamp": datetime.now().isoformat(),
    }
    if metrics:
        log_data["metrics"] = metrics

    logger.info("stage_end", **log_data)


def log_stage_error(
    logger: structlog.BoundLogger,
    stage: str,
    error: Exception,
    duration_seconds: float,
) -> None:
    """Log a stage failure."""
    logger.error(
        "stage_error",
        stage=stage,
        error_type=type(error).__name__,
        error_message=str(error),
        duration_seconds=round(duration_seconds, 2),
        timestamp=datetime.now().isoformat(),
    )


def log_pipeline_end(
    logger: structlog.BoundLogger,
    success: bool,
    total_duration_seconds: float,
    stages_completed: list[str],
    final_outputs: list[str],
) -> None:
    """Log pipeline completion."""
    logger.info(
        "pipeline_end",
        success=success,
        total_duration_seconds=round(total_duration_seconds, 2),
        stages_completed=stages_completed,
        final_outputs=final_outputs,
        timestamp=datetime.now().isoformat(),
    )
