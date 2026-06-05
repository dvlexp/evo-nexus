"""
Video Edit Pipeline — Stage Modules

Each stage module exposes a `run(episode_dir, config, preview, logger)` function
that returns (artifacts: list[str], metrics: dict).
"""

from pathlib import Path
from typing import Protocol, Any


class StageProtocol(Protocol):
    """Protocol for stage modules."""

    def run(
        self,
        episode_dir: Path,
        config: dict,
        preview: bool,
        logger: Any,
    ) -> tuple[list[str], dict]:
        """
        Execute the stage.

        Args:
            episode_dir: Path to episode directory
            config: Configuration dict from defaults.yaml
            preview: True if running in preview mode
            logger: Structlog logger instance

        Returns:
            Tuple of (artifact filenames, metrics dict)
        """
        ...


# Stage registry — populated by imports
STAGE_MODULES: dict[str, StageProtocol] = {}


def register_stage(name: str, module: StageProtocol) -> None:
    """Register a stage module."""
    STAGE_MODULES[name] = module


def get_stage_module(name: str) -> StageProtocol | None:
    """Get a stage module by name."""
    return STAGE_MODULES.get(name)


# Import and register all stage modules
def _register_stages() -> None:
    """Import and register all stage modules."""
    from . import sync
    from . import audio
    from . import transcribe
    from . import cut_fillers
    from . import cut_silence
    from . import bg_removal
    from . import motion_graphics
    from . import sfx
    from . import render

    register_stage("sync", sync)
    register_stage("audio", audio)
    register_stage("transcribe", transcribe)
    register_stage("cut-fillers", cut_fillers)
    register_stage("cut-silence", cut_silence)
    register_stage("bg-removal", bg_removal)
    register_stage("motion-graphics", motion_graphics)
    register_stage("sfx", sfx)
    register_stage("render", render)


_register_stages()
