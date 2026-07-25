import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, FFMPEG_PATH, DEFAULT_YOUTUBE_URL

def download_youtube_video(
    url: str = DEFAULT_YOUTUBE_URL,
    output_filename: str = "match_video.mp4",
    max_height: int = 480,
    start_sec: Optional[int] = None,
    end_sec: Optional[int] = None,
    force_redownload: bool = False
) -> Path:
    """
    Downloads YouTube video at requested max height resolution (e.g. 480p).
    If file already exists locally, re-use cached file unless force_redownload is True.
    """
    output_path = DATA_DIR / output_filename
    
    if not force_redownload and output_path.exists() and output_path.stat().st_size > 1000000:
        print(f"[Cache] Video file already cached locally at: {output_path.name} ({output_path.stat().st_size / (1024*1024):.1f} MB). Skipping download.")
        return output_path

    cmd = [
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_PATH,
        "--no-playlist",
        "--format", "18/b[height<=480]/b",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-update",
        "--extractor-args", "youtube:player_client=default"
    ]
    
    if start_sec is not None and end_sec is not None:
        cmd.extend(["--download-sections", f"*{start_sec}-{end_sec}"])
        
    cmd.append(url)
    
    print(f"Downloading video from {url}...")
    if start_sec is not None and end_sec is not None:
        print(f"Section: {start_sec}s to {end_sec}s ({round((end_sec-start_sec)/60, 2)} min)")
        
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    
    if not output_path.exists():
        matches = list(DATA_DIR.glob("*.mp4"))
        if matches:
            output_path = matches[0]
        else:
            raise RuntimeError(f"Download failed: {result.stderr}")
            
    print(f"Video ready at: {output_path} ({output_path.stat().st_size / (1024*1024):.1f} MB)")
    return output_path

if __name__ == "__main__":
    path = download_youtube_video(start_sec=0, end_sec=300, output_filename="sample_0s_to_300s.mp4")
    print("Done:", path)
