#!/usr/bin/env bash
#
# video-edit skill installer
# Runs on CPU-only (i5-2415M compatible, no AVX2 requirement)
#
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${SKILL_DIR}/.venv"
VENDOR_DIR="${SKILL_DIR}/vendor"
MODELS_DIR="${SKILL_DIR}/models"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Step 1: Check ffmpeg >= 4.4 ---
check_ffmpeg() {
    log_info "Checking ffmpeg..."
    if ! command -v ffmpeg &> /dev/null; then
        log_error "ffmpeg not found. Install with: sudo apt install ffmpeg"
        exit 1
    fi
    
    FFMPEG_VERSION=$(ffmpeg -version | head -n1 | grep -oP 'ffmpeg version \K[0-9]+\.[0-9]+' | head -1)
    MAJOR=$(echo "$FFMPEG_VERSION" | cut -d. -f1)
    MINOR=$(echo "$FFMPEG_VERSION" | cut -d. -f2)
    
    if [[ "$MAJOR" -lt 4 ]] || { [[ "$MAJOR" -eq 4 ]] && [[ "$MINOR" -lt 4 ]]; }; then
        log_error "ffmpeg version $FFMPEG_VERSION found, but >= 4.4 required"
        exit 1
    fi
    log_info "ffmpeg $FFMPEG_VERSION OK"
}

# --- Step 2: Create venv ---
create_venv() {
    log_info "Creating virtual environment at ${VENV_DIR}..."
    
    if [[ -d "$VENV_DIR" ]]; then
        log_warn "venv already exists, skipping creation"
    else
        python3 -m venv "$VENV_DIR"
    fi
    
    # Activate venv
    source "${VENV_DIR}/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip --quiet
    log_info "venv created and activated"
}

# --- Step 3: Install Python dependencies ---
install_deps() {
    log_info "Installing Python dependencies (this may take a while)..."
    source "${VENV_DIR}/bin/activate"
    
    pip install --no-cache-dir -r "${SKILL_DIR}/requirements.txt"
    
    log_info "Python dependencies installed"
}

# --- Step 4: Download models ---
download_models() {
    log_info "Downloading models..."
    mkdir -p "$MODELS_DIR"
    source "${VENV_DIR}/bin/activate"
    
    # WhisperX medium model (downloads on first use, but we can pre-cache)
    log_info "  - WhisperX medium PT-BR will download on first transcription"
    
    # MediaPipe selfie segmentation downloads automatically on first use
    log_info "  - MediaPipe selfie segmentation will download on first use"
    
    # YOLOv8n - small model for face tracking
    log_info "  - Downloading YOLOv8n..."
    python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null || true
    
    log_info "Models ready (some will download on first use)"
}

# --- Step 5: Clone vendor dependencies ---
clone_vendors() {
    log_info "Setting up vendor dependencies..."
    mkdir -p "$VENDOR_DIR"
    
    # HyperFrames (HTML to MP4 motion graphics)
    if [[ ! -d "${VENDOR_DIR}/HyperFrames" ]]; then
        log_info "  - Cloning HyperFrames..."
        git clone --depth 1 https://github.com/nickhartjes/HyperFrames.git "${VENDOR_DIR}/HyperFrames" 2>/dev/null || {
            log_warn "HyperFrames clone failed (may not exist or private). Motion graphics will be unavailable."
        }
    else
        log_info "  - HyperFrames already present"
    fi
    
    # Note: Autocrop-vertical functionality will be implemented directly using ultralytics
    log_info "  - Autocrop-vertical: using built-in YOLOv8 implementation"
    
    log_info "Vendor setup complete"
}

# --- Step 6: Verify installation ---
verify_install() {
    log_info "Verifying installation..."
    source "${VENV_DIR}/bin/activate"
    
    python3 << 'EOFPYTHON'
import sys
errors = []

try:
    import whisperx
    print("  ✓ whisperx")
except ImportError as e:
    errors.append(f"whisperx: {e}")

try:
    import mediapipe
    print("  ✓ mediapipe")
except ImportError as e:
    errors.append(f"mediapipe: {e}")

try:
    import df
    print("  ✓ deepfilternet")
except ImportError as e:
    # deepfilternet imports as 'df'
    try:
        from deepfilternet import enhance
        print("  ✓ deepfilternet")
    except ImportError as e2:
        errors.append(f"deepfilternet: {e2}")

try:
    import ffmpeg_normalize
    print("  ✓ ffmpeg-normalize")
except ImportError as e:
    errors.append(f"ffmpeg-normalize: {e}")

try:
    from auto_editor import __version__
    print("  ✓ auto-editor")
except ImportError as e:
    errors.append(f"auto-editor: {e}")

try:
    from ultralytics import YOLO
    print("  ✓ ultralytics (YOLOv8)")
except ImportError as e:
    errors.append(f"ultralytics: {e}")

try:
    import numpy
    print("  ✓ numpy")
except ImportError as e:
    errors.append(f"numpy: {e}")

try:
    import scipy
    print("  ✓ scipy")
except ImportError as e:
    errors.append(f"scipy: {e}")

try:
    import yaml
    print("  ✓ pyyaml")
except ImportError as e:
    errors.append(f"pyyaml: {e}")

try:
    import rich
    print("  ✓ rich")
except ImportError as e:
    errors.append(f"rich: {e}")

try:
    import structlog
    print("  ✓ structlog")
except ImportError as e:
    errors.append(f"structlog: {e}")

if errors:
    print("\nErrors:")
    for err in errors:
        print(f"  ✗ {err}")
    sys.exit(1)
else:
    print("\nAll dependencies OK!")
    sys.exit(0)
EOFPYTHON
    
    log_info "Installation verified successfully"
}

# --- Main ---
main() {
    log_info "=== video-edit skill installer ==="
    log_info "Skill directory: ${SKILL_DIR}"
    echo
    
    check_ffmpeg
    create_venv
    install_deps
    download_models
    clone_vendors
    verify_install
    
    echo
    log_info "=== Installation complete ==="
    log_info "Activate with: source ${VENV_DIR}/bin/activate"
    log_info "Run with: python ${SKILL_DIR}/scripts/video_edit.py --help"
}

main "$@"
