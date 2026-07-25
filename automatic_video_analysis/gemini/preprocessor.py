import subprocess
from pathlib import Path
from typing import Optional
import cv2

from .config import DATA_DIR, FFMPEG_PATH, DEFAULT_YOUTUBE_URL
from .downloader import download_youtube_video

def prepare_video_segment(
    url_or_file: str,
    is_local_file: bool,
    start_sec: int = 0,
    end_sec: int = 300,
    target_height: int = 480
) -> Path:
    """
    Prepares a fast, optimized 480p video segment for Gemini API analysis.
    Works seamlessly for both YouTube URLs and high-res local MP4 files.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    segment_filename = f"segment_{start_sec}s_to_{end_sec}s_{target_height}p.mp4"
    output_path = DATA_DIR / segment_filename

    # Return cached segment if already preprocessed
    if output_path.exists() and output_path.stat().st_size > 500000:
        print(f"[Preprocessor] Re-using preprocessed 480p video segment: {output_path.name} ({output_path.stat().st_size / (1024*1024):.1f} MB)")
        return output_path

    if not is_local_file:
        # Download YouTube section at 480p
        return download_youtube_video(
            url=url_or_file,
            output_filename=segment_filename,
            max_height=target_height,
            start_sec=start_sec,
            end_sec=end_sec
        )
    else:
        # Local video file: Trim section (start_sec to end_sec) and downscale to 480p
        local_src = Path(url_or_file)
        if not local_src.exists():
            raise FileNotFoundError(f"Local video file not found: {local_src}")

        print(f"[Preprocessor] Trimming & downscaling local video to 480p ({start_sec}s to {end_sec}s)...")
        duration = max(5, end_sec - start_sec)
        
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-ss", str(start_sec),
            "-i", str(local_src),
            "-t", str(duration),
            "-vf", f"scale=-2:{target_height}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path)
        ]
        
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if output_path.exists() and output_path.stat().st_size > 100000:
            print(f"[Preprocessor] Optimized local segment created: {output_path.name} ({output_path.stat().st_size / (1024*1024):.1f} MB)")
            return output_path
        else:
            print(f"[Preprocessor] Warning: ffmpeg downscaling fallback to direct local file.")
            return local_src
