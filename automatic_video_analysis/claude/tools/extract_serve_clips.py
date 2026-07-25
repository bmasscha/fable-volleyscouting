"""Detect serves in a window, then cut a short video fragment around each serve.

Downloads the requested window ONCE (cached under media/), runs serve detection
with the chosen model, and writes one mp4 per detected serve into --out-dir so a
human can eyeball whether each detection is really a serve.

    python tools/extract_serve_clips.py "https://youtu.be/o-E31sQlLF8" \
        --start 10:00 --end 15:00 --model gemini-2.5-flash --out-dir clips_flash

The window file is keyed by start/end only (not model), so running a second model
over the same window reuses the already-downloaded media.
"""
import argparse
import os
import re
import subprocess
import sys

import imageio_ffmpeg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_detector as sd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_DIR = os.path.join(HERE, "media")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def ensure_window(url: str, start_s: float, end_s: float) -> str:
    """Download [start,end] of the video to media/window_<start>_<end>.mp4 (cached)."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    out = os.path.join(MEDIA_DIR, f"window_{int(start_s)}_{int(end_s)}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        print(f"[window] using cached {os.path.basename(out)}", file=sys.stderr)
        return out
    print(f"[window] downloading {_hms(start_s)}-{_hms(end_s)} ...", file=sys.stderr)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", FFMPEG,
        "--download-sections", f"*{_hms(start_s)}-{_hms(end_s)}",
        "--force-keyframes-at-cuts",
        # prefer H.264/AAC in mp4 so clips are natively playable on Windows
        "-f", "bv*[height<=480][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=480][ext=mp4]/bv*[height<=480]+ba/b",
        "--merge-output-format", "mp4",
        "-o", out,
        url,
    ]
    subprocess.run(cmd, check=True)
    if not os.path.exists(out):  # some format paths leave a differing ext
        raise RuntimeError("window download did not produce expected file")
    return out


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-") or "x"


def cut_clip(window_file: str, at_seconds: float, out_path: str, pre: float, post: float):
    """Cut [at-pre, at+post] from window_file, re-encoding for frame-accurate, playable mp4."""
    start = max(0.0, at_seconds - pre)
    dur = (at_seconds - start) + post
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{start:.3f}", "-i", window_file, "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--start", default="10:00")
    ap.add_argument("--end", default="15:00")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pre", type=float, default=4.0, help="seconds before serve contact")
    ap.add_argument("--post", type=float, default=5.0, help="seconds after serve contact")
    args = ap.parse_args()

    start_s = sd.parse_timestamp(args.start)
    end_s = sd.parse_timestamp(args.end)

    window_file = ensure_window(args.url, start_s, end_s)

    print(f"[detect] {args.model} on [{args.start}..{args.end}] ...", file=sys.stderr)
    serves = sd.detect_serves(args.url, start=start_s, end=end_s, model=args.model)
    print(f"[detect] {len(serves)} serve(s)", file=sys.stderr)

    out_dir = os.path.join(HERE, args.out_dir) if not os.path.isabs(args.out_dir) else args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    manifest = []
    for i, sv in enumerate(serves, 1):
        name = f"{i:02d}_{_safe(sv.video_timestamp)}_{_safe(sv.serving_team)}_{_safe(sv.server or 'x')}.mp4"
        out_path = os.path.join(out_dir, name)
        # sv.clip_seconds is relative to the window start (== window file t=0)
        cut_clip(window_file, sv.clip_seconds, out_path, args.pre, args.post)
        manifest.append({
            "file": name,
            "video_timestamp": sv.video_timestamp,
            "serving_team": sv.serving_team,
            "server": sv.server,
            "confidence": sv.confidence,
            "reasoning": sv.reasoning,
        })
        print(f"  {name}", file=sys.stderr)

    import json
    with open(os.path.join(out_dir, "_serves.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": args.model, "window": f"{args.start}-{args.end}", "serves": manifest}, fh, indent=2)
    print(f"\n[done] {len(manifest)} clips -> {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
