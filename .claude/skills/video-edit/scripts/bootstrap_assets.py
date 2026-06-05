#!/usr/bin/env python3
"""
Video Edit Pipeline — Asset Bootstrap
Generates placeholder assets if required files are missing.
"""

import os
from pathlib import Path
from typing import Optional


def create_placeholder_image(path: Path, width: int, height: int, color: str = "#1a1a1a") -> None:
    """
    Create a simple placeholder PNG image.
    Uses pure Python to avoid PIL dependency for bootstrap.
    """
    # Simple approach: create a minimal valid PNG with solid color
    # For production, this would use PIL, but for placeholders we keep it simple

    # Create a README instead for now
    readme_path = path.parent / "README-assets.md"
    with open(readme_path, "a") as f:
        f.write(f"\n## Missing: {path.name}\n")
        f.write(f"- Expected dimensions: {width}x{height}\n")
        f.write(f"- Please provide a real image file at: `{path}`\n\n")

    print(f"  ⚠ Placeholder needed: {path.name} ({width}x{height})")


def create_placeholder_audio(path: Path, duration: float = 1.0) -> None:
    """
    Create a placeholder audio file note.
    Actual silent audio would require ffmpeg.
    """
    readme_path = path.parent / "README-assets.md"
    with open(readme_path, "a") as f:
        f.write(f"\n## Missing: {path.name}\n")
        f.write(f"- Expected duration: ~{duration}s\n")
        f.write(f"- Please provide a real audio file at: `{path}`\n\n")

    print(f"  ⚠ Placeholder needed: {path.name}")


def create_placeholder_template(path: Path, template_type: str) -> None:
    """
    Create a placeholder HTML motion template.
    """
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{template_type}</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            width: 1920px;
            height: 1080px;
            background: transparent;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: 'Inter', sans-serif;
        }}
        .container {{
            background: rgba(0, 255, 167, 0.9);
            padding: 20px 40px;
            border-radius: 8px;
        }}
        .text {{
            color: #000;
            font-size: 48px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="text">{{{{ text }}}}</div>
    </div>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(html_content)

    print(f"  ✓ Created template: {path.name}")


def bootstrap_skill_assets(skill_dir: Optional[Path] = None) -> bool:
    """
    Bootstrap required assets for the video-edit skill.

    Returns:
        True if all assets exist, False if placeholders were created
    """
    if skill_dir is None:
        skill_dir = Path(__file__).parent.parent

    assets_dir = skill_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    all_present = True
    readme_path = assets_dir / "README-assets.md"

    # Start fresh README
    with open(readme_path, "w") as f:
        f.write("# Asset Requirements\n\n")
        f.write("This file documents required assets for the video-edit pipeline.\n\n")

    print("\n=== Bootstrapping video-edit assets ===")

    # --- Background image ---
    studio_bg = assets_dir / "studio-bg.png"
    if not studio_bg.exists():
        # Check workspace location
        workspace_bg = Path("/home/daniel/evo-nexus/workspace/projects/youtube/assets/studio-bg.png")
        if workspace_bg.exists():
            # Symlink to workspace asset
            studio_bg.symlink_to(workspace_bg)
            print(f"  ✓ Linked studio-bg.png from workspace")
        else:
            create_placeholder_image(studio_bg, 1920, 1080, "#1a1a1a")
            all_present = False
    else:
        print(f"  ✓ Found: studio-bg.png")

    # --- SFX directory ---
    sfx_dir = assets_dir / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    required_sfx = [
        ("whoosh.wav", 0.5),
        ("pop.wav", 0.3),
        ("transition.wav", 1.0),
    ]

    for sfx_name, duration in required_sfx:
        sfx_path = sfx_dir / sfx_name
        if not sfx_path.exists():
            create_placeholder_audio(sfx_path, duration)
            all_present = False
        else:
            print(f"  ✓ Found: sfx/{sfx_name}")

    # --- Motion templates ---
    templates_dir = assets_dir / "motion-templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    required_templates = [
        "lower-third.html",
        "title-card.html",
        "callout.html",
    ]

    for template_name in required_templates:
        template_path = templates_dir / template_name
        if not template_path.exists():
            template_type = template_name.replace(".html", "").replace("-", " ").title()
            create_placeholder_template(template_path, template_type)
        else:
            print(f"  ✓ Found: motion-templates/{template_name}")

    # --- Finalize README ---
    with open(readme_path, "a") as f:
        if all_present:
            f.write("\n---\n✅ All assets present.\n")
        else:
            f.write("\n---\n⚠️ Some assets are missing. Please provide the files listed above.\n")

    print(f"\n{'✅ All assets present' if all_present else '⚠️ Some assets missing - see README-assets.md'}")

    return all_present


def bootstrap_episode_assets(episode_dir: Path) -> bool:
    """
    Bootstrap required files for a specific episode.

    Returns:
        True if episode is ready, False if missing required files
    """
    episode_dir = Path(episode_dir)

    if not episode_dir.exists():
        print(f"Error: Episode directory does not exist: {episode_dir}")
        return False

    print(f"\n=== Checking episode: {episode_dir.name} ===")

    # Check for video file
    video_extensions = [".mp4", ".MOV", ".mkv", ".webm"]
    video_found = False
    for ext in video_extensions:
        video_path = episode_dir / f"video{ext}"
        if video_path.exists():
            video_found = True
            print(f"  ✓ Video: video{ext}")
            break

    if not video_found:
        print("  ✗ No video file found (expected video.mp4)")

    # Check for external audio (optional)
    audio_path = episode_dir / "audio_externo.wav"
    if audio_path.exists():
        print("  ✓ External audio: audio_externo.wav")
    else:
        print("  ○ No external audio (will use camera audio)")

    # Check for instructions (optional)
    instructions_path = episode_dir / "instructions.md"
    if instructions_path.exists():
        print("  ✓ Instructions: instructions.md")
    else:
        print("  ○ No instructions.md (using defaults)")

    # Create episode assets dir if needed
    episode_assets = episode_dir / "assets"
    if not episode_assets.exists():
        episode_assets.mkdir(parents=True)
        print("  ✓ Created: assets/")

    return video_found


def main():
    """Main entry point for bootstrap script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Bootstrap assets for video-edit pipeline"
    )
    parser.add_argument(
        "--episode",
        type=Path,
        help="Bootstrap a specific episode directory",
    )
    parser.add_argument(
        "--skill-only",
        action="store_true",
        dest="skill_only",
        help="Only bootstrap skill assets, not episode",
    )

    args = parser.parse_args()

    # Always bootstrap skill assets
    skill_ready = bootstrap_skill_assets()

    # Optionally bootstrap episode
    if args.episode:
        episode_ready = bootstrap_episode_assets(args.episode)
        return 0 if (skill_ready and episode_ready) else 1

    return 0 if skill_ready else 1


if __name__ == "__main__":
    exit(main())
