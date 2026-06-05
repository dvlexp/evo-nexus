"""
Video Edit Pipeline — Checkpoint Manager
Persists pipeline state for resume capability
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Pipeline stages in order
STAGES = [
    "sync",
    "audio",
    "transcribe",
    "cut-fillers",
    "cut-silence",
    "bg-removal",
    "motion-graphics",
    "sfx",
    "render",
]


class CheckpointManager:
    """
    Manages pipeline state persistence for resume capability.

    State is stored in pipeline_state.json with structure:
    {
        "pipeline_version": "1.0",
        "episode_dir": "/path/to/episode",
        "started_at": "ISO timestamp",
        "stages": {
            "sync": {
                "status": "completed|in_progress|pending|skipped|failed",
                "started_at": "ISO timestamp",
                "finished_at": "ISO timestamp",
                "artifacts": ["audio_synced.wav"],
                "metrics": {"offset": 0.5, "confidence": 0.95},
                "error": null
            },
            ...
        },
        "current_stage": "audio",
        "last_updated": "ISO timestamp"
    }
    """

    PIPELINE_VERSION = "1.0"

    def __init__(self, episode_dir: Path, state_file: str = "pipeline_state.json"):
        """
        Initialize checkpoint manager.

        Args:
            episode_dir: Directory containing the episode
            state_file: Name of the state file (default: pipeline_state.json)
        """
        self.episode_dir = Path(episode_dir)
        self.state_path = self.episode_dir / state_file
        self.state = self._load_or_create()

    def _load_or_create(self) -> dict:
        """Load existing state or create new."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    state = json.load(f)
                # Validate version
                if state.get("pipeline_version") != self.PIPELINE_VERSION:
                    # Migration could happen here; for now, keep as-is
                    pass
                return state
            except (json.JSONDecodeError, KeyError):
                # Corrupted state file — start fresh
                pass

        return self._create_initial_state()

    def _create_initial_state(self) -> dict:
        """Create initial pipeline state."""
        now = datetime.now().isoformat()
        return {
            "pipeline_version": self.PIPELINE_VERSION,
            "episode_dir": str(self.episode_dir),
            "started_at": now,
            "stages": {
                stage: {
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "artifacts": [],
                    "metrics": {},
                    "error": None,
                }
                for stage in STAGES
            },
            "current_stage": None,
            "last_updated": now,
        }

    def _save(self) -> None:
        """Persist state to disk."""
        self.state["last_updated"] = datetime.now().isoformat()
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def mark_started(self, stage: str) -> None:
        """Mark a stage as in progress."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        self.state["stages"][stage]["status"] = "in_progress"
        self.state["stages"][stage]["started_at"] = datetime.now().isoformat()
        self.state["stages"][stage]["finished_at"] = None
        self.state["stages"][stage]["error"] = None
        self.state["current_stage"] = stage
        self._save()

    def mark_done(
        self,
        stage: str,
        artifacts: list[str],
        metrics: Optional[dict] = None,
    ) -> None:
        """Mark a stage as completed."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        self.state["stages"][stage]["status"] = "completed"
        self.state["stages"][stage]["finished_at"] = datetime.now().isoformat()
        self.state["stages"][stage]["artifacts"] = artifacts
        if metrics:
            self.state["stages"][stage]["metrics"] = metrics

        # Move to next stage
        idx = STAGES.index(stage)
        if idx < len(STAGES) - 1:
            self.state["current_stage"] = STAGES[idx + 1]
        else:
            self.state["current_stage"] = None

        self._save()

    def mark_failed(self, stage: str, error: str) -> None:
        """Mark a stage as failed."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        self.state["stages"][stage]["status"] = "failed"
        self.state["stages"][stage]["finished_at"] = datetime.now().isoformat()
        self.state["stages"][stage]["error"] = error
        self._save()

    def mark_skipped(self, stage: str, reason: str = "user requested") -> None:
        """Mark a stage as skipped."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        self.state["stages"][stage]["status"] = "skipped"
        self.state["stages"][stage]["finished_at"] = datetime.now().isoformat()
        self.state["stages"][stage]["metrics"] = {"skip_reason": reason}
        self._save()

    def is_complete(self, stage: str) -> bool:
        """Check if a stage is already completed."""
        if stage not in STAGES:
            return False
        return self.state["stages"][stage]["status"] == "completed"

    def is_skipped(self, stage: str) -> bool:
        """Check if a stage was skipped."""
        if stage not in STAGES:
            return False
        return self.state["stages"][stage]["status"] == "skipped"

    def get_status(self, stage: str) -> str:
        """Get the status of a stage."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")
        return self.state["stages"][stage]["status"]

    def get_artifacts(self, stage: str) -> list[str]:
        """Get artifacts produced by a stage."""
        if stage not in STAGES:
            return []
        return self.state["stages"][stage].get("artifacts", [])

    def get_metrics(self, stage: str) -> dict:
        """Get metrics from a stage."""
        if stage not in STAGES:
            return {}
        return self.state["stages"][stage].get("metrics", {})

    def get_current_stage(self) -> Optional[str]:
        """Get the current/next stage to run."""
        return self.state.get("current_stage")

    def get_stages_to_run(
        self,
        resume_from: Optional[str] = None,
        skip: Optional[list[str]] = None,
    ) -> list[str]:
        """
        Get list of stages to run, respecting resume and skip.

        Args:
            resume_from: Stage to resume from (skips earlier stages)
            skip: List of stages to skip

        Returns:
            Ordered list of stage names to execute
        """
        skip = skip or []
        to_run = []

        resume_idx = 0
        if resume_from:
            if resume_from not in STAGES:
                raise ValueError(f"Unknown stage: {resume_from}")
            resume_idx = STAGES.index(resume_from)

        for i, stage in enumerate(STAGES):
            # Skip if before resume point
            if i < resume_idx:
                continue

            # Skip if in skip list
            if stage in skip:
                continue

            # Skip if already completed (unless explicitly resuming from it)
            if self.is_complete(stage) and stage != resume_from:
                continue

            to_run.append(stage)

        return to_run

    def get_completed_stages(self) -> list[str]:
        """Get list of completed stages in order."""
        return [
            stage for stage in STAGES
            if self.state["stages"][stage]["status"] == "completed"
        ]

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of pipeline state."""
        completed = self.get_completed_stages()
        skipped = [s for s in STAGES if self.is_skipped(s)]
        failed = [
            s for s in STAGES
            if self.state["stages"][s]["status"] == "failed"
        ]
        pending = [
            s for s in STAGES
            if self.state["stages"][s]["status"] in ("pending", "in_progress")
        ]

        return {
            "episode_dir": str(self.episode_dir),
            "started_at": self.state.get("started_at"),
            "last_updated": self.state.get("last_updated"),
            "current_stage": self.state.get("current_stage"),
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "pending": pending,
            "progress": f"{len(completed)}/{len(STAGES)} stages",
        }

    def reset(self) -> None:
        """Reset all state (start fresh)."""
        self.state = self._create_initial_state()
        self._save()

    def reset_stage(self, stage: str) -> None:
        """Reset a specific stage to pending."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}")

        self.state["stages"][stage] = {
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "artifacts": [],
            "metrics": {},
            "error": None,
        }
        self._save()


def get_stage_index(stage: str) -> int:
    """Get the index of a stage in the pipeline."""
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    return STAGES.index(stage)


def validate_stage(stage: str) -> bool:
    """Check if a stage name is valid."""
    return stage in STAGES


def get_all_stages() -> list[str]:
    """Get all stage names in order."""
    return STAGES.copy()
