#!/usr/bin/env python3
import argparse, json, os, sys, time
from pathlib import Path
import cv2, numpy as np
from PIL import Image

MODEL_PATH = Path(".claude/skills/video-edit/vendor/models/selfie_segmenter.tflite")

def load_bg(bg_path, w, h):
    bg = Image.open(bg_path).convert("RGB").resize((w, h), Image.LANCZOS)
    return np.array(bg)[:, :, ::-1].copy()

def make_segmenter():
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions, RunningMode
    import mediapipe as mp
    opts = ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=RunningMode.IMAGE,
        output_confidence_masks=True,
    )
    return ImageSegmenter.create_from_options(opts)

def run(episode_dir, resume=True, preview=0):
    ep = Path(episode_dir)
    frames_dir = ep / "tmp" / "bg_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    bg_path = "workspace/projects/youtube/assets/studio-bg.png"
    video_in = ep / "video_cut.mp4"
    video_out = ep / "video_bg_replaced.mp4"
    audio_src = ep / "audio_clean.wav"
    state_path = ep / "pipeline_state.json"

    cap = cv2.VideoCapture(str(video_in))
    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if preview > 0:
        total = min(total, int(preview * fps))
    bg = load_bg(bg_path, W, H)
    print(f"[bg-removal] {W}x{H} @{fps}fps {total} frames", flush=True)

    start = 0
    if resume:
        ex = sorted(frames_dir.glob("frame_*.png"))
        if ex:
            start = int(ex[-1].stem.split("_")[1]) + 1
            print(f"[resume] from frame {start}", flush=True)

    if start < total:
        import mediapipe as mp
        segmenter = make_segmenter()
        cap = cv2.VideoCapture(str(video_in))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        t0 = time.time()
        for i in range(start, total):
            ret, frame = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = segmenter.segment(mp_img)
            mask = result.confidence_masks[0].numpy_view()  # float32 0..1
            mb = cv2.GaussianBlur(mask, (5, 5), 0)
            m3 = np.stack([mb, mb, mb], axis=-1)
            out = np.clip(frame.astype(np.float32)*m3 + bg.astype(np.float32)*(1-m3), 0, 255).astype(np.uint8)
            cv2.imwrite(str(frames_dir / f"frame_{i:06d}.png"), out)
            if i % 300 == 0 and i > start:
                el = time.time()-t0; fps_p = (i-start)/el if el>0 else 1
                print(f"[{i}/{total}] {100*i/total:.1f}% {fps_p:.1f}fps ETA {(total-i)/fps_p/60:.0f}min", flush=True)
        cap.release()
        segmenter.close()
        print(f"[frames done] {(time.time()-t0)/60:.1f}min", flush=True)
    else:
        print("[skip] all frames already exist", flush=True)

    print("[compose] ffmpeg...", flush=True)
    ii = f"-i {audio_src}" if audio_src.exists() else ""
    ai = f"-map 0:v -map 1:a -c:a aac -b:a 192k" if audio_src.exists() else "-an"
    cmd = f"ffmpeg -y -framerate {fps} -i {frames_dir}/frame_%06d.png {ii} -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p {ai} {video_out}"
    if os.system(cmd) != 0:
        sys.exit(1)
    print(f"[done] {video_out}", flush=True)

    if state_path.exists():
        from datetime import datetime
        s = json.loads(state_path.read_text())
        s["stages"]["bg-removal"].update({"status":"completed","finished_at":datetime.now().isoformat()[:19],"artifacts":["video_bg_replaced.mp4"],"metrics":{"total_frames":total,"width":W,"height":H}})
        s["current_stage"] = "motion-graphics"
        s["last_updated"] = datetime.now().isoformat()[:19]
        state_path.write_text(json.dumps(s, indent=2))
        print("[state] -> motion-graphics", flush=True)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--episode-dir", required=True)
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--preview", type=int, default=0)
    a = p.parse_args()
    run(a.episode_dir, resume=not a.no_resume, preview=a.preview)
