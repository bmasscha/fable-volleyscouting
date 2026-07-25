import subprocess
from pathlib import Path
from typing import List, Optional
import cv2

from .config import FFMPEG_PATH, OUTPUT_DIR
from .schemas import GameActionEvent

def get_video_duration(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps > 0 and frame_count > 0:
        return frame_count / fps
    return 99999.0

def extract_event_thumbnails(
    video_path: Path,
    events: Optional[List[GameActionEvent]] = None,
    output_dir: Optional[Path] = None,
    log_callback: Optional[callable] = None,
    progress_callback: Optional[callable] = None,
    serves: Optional[List[GameActionEvent]] = None
) -> List[Path]:
    events = events if events is not None else (serves or [])
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found at {video_path}")

    target_dir = output_dir or (OUTPUT_DIR / "serve_clips")
    target_dir.mkdir(parents=True, exist_ok=True)

    duration_sec = get_video_duration(video_path)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    thumbnail_paths = []
    total_count = len(events)
    log_msg = f"Extracting visual thumbnails for {total_count} detected events into {target_dir.name}..."
    if log_callback:
        log_callback(log_msg)
    else:
        print(log_msg)

    try:
        for idx, event in enumerate(events, 1):
            clean_time = event.timestamp_formatted.replace(":", "m") + "s"
            clean_action = event.action_type.replace("/", "-").replace(" ", "_")
            img_name = f"action_{idx:02d}_{clean_action}_at_{clean_time}.jpg"
            out_path = target_dir / img_name

            legacy_img_name = f"serve_{idx:02d}_at_{clean_time}.jpg"
            legacy_out_path = target_dir / legacy_img_name

            if out_path.exists() and out_path.stat().st_size > 5000:
                thumbnail_paths.append(out_path)
                if progress_callback:
                    progress_callback(idx, total_count)
                continue
            elif legacy_out_path.exists() and legacy_out_path.stat().st_size > 5000:
                thumbnail_paths.append(legacy_out_path)
                if progress_callback:
                    progress_callback(idx, total_count)
                continue

            target_sec = max(0, event.timestamp_start_sec)
            if target_sec >= duration_sec:
                if progress_callback:
                    progress_callback(idx, total_count)
                continue

            frame_idx = int(target_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            
            ret, frame = cap.read()
            if ret and frame is not None:
                time_str = event.timestamp_formatted
                info_text = f"Action #{idx} [{time_str}] - {event.team} ({event.action_type})"
                
                h, w, _ = frame.shape
                cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)
                cv2.putText(
                    frame, info_text, (15, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA
                )
                
                cv2.imwrite(str(out_path), frame)
                thumbnail_paths.append(out_path)
                msg = f" Saved thumbnail [{idx}/{total_count}]: {out_path.name}"
                if log_callback:
                    log_callback(msg)
                else:
                    print(msg)
            
            if progress_callback:
                progress_callback(idx, total_count)
    finally:
        cap.release()

    return thumbnail_paths

# Backward compatibility alias
extract_serve_thumbnails = extract_event_thumbnails

def extract_event_video_clips(
    video_path: Path,
    events: Optional[List[GameActionEvent]] = None,
    output_dir: Optional[Path] = None,
    padding_sec: float = 1.0,
    log_callback: Optional[callable] = None,
    progress_callback: Optional[callable] = None,
    serves: Optional[List[GameActionEvent]] = None
) -> List[Path]:
    events = events if events is not None else (serves or [])
    if not video_path.exists():
        return []


    target_dir = output_dir or (OUTPUT_DIR / "serve_clips")
    target_dir.mkdir(parents=True, exist_ok=True)

    duration_sec = get_video_duration(video_path)
    clip_paths = []
    total_count = len(events)
    log_msg = f"Extracting video clips for {total_count} detected events into {target_dir.name}..."
    if log_callback:
        log_callback(log_msg)
    else:
        print(log_msg)

    for idx, event in enumerate(events, 1):
        clean_time = event.timestamp_formatted.replace(":", "m") + "s"
        clean_action = event.action_type.replace("/", "-").replace(" ", "_")
        clip_name = f"action_{idx:02d}_{clean_action}_at_{clean_time}.mp4"
        out_path = target_dir / clip_name

        legacy_clip_name = f"serve_{idx:02d}_clip_{clean_time}.mp4"
        legacy_out_path = target_dir / legacy_clip_name

        if out_path.exists() and out_path.stat().st_size > 5000:
            clip_paths.append(out_path)
            if progress_callback:
                progress_callback(idx, total_count)
            continue
        elif legacy_out_path.exists() and legacy_out_path.stat().st_size > 5000:
            clip_paths.append(legacy_out_path)
            if progress_callback:
                progress_callback(idx, total_count)
            continue

        start_time = max(0.0, event.timestamp_start_sec - padding_sec)
        if start_time >= duration_sec:
            if progress_callback:
                progress_callback(idx, total_count)
            continue

        # Adjust clip duration based on action type
        is_attack = "attack" in event.action_type.lower() or "spike" in event.action_type.lower()
        if is_attack:
            # Attacks are explosive & fast; keep clips concise (2.5s to 6.0s max)
            raw_dur = (event.timestamp_end_sec - event.timestamp_start_sec) + (1.5 * padding_sec)
            clip_duration = max(2.5, min(raw_dur, 6.0))
        else:
            # Serves
            raw_dur = (event.timestamp_end_sec - event.timestamp_start_sec) + (2 * padding_sec)
            clip_duration = max(3.0, min(raw_dur, 12.0))
        
        # Standard H.264 + YUV420P MP4 encoding for 100% player compatibility
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-nostdin",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(clip_duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(out_path)
        ]
        
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
        except subprocess.TimeoutExpired:
            warn_msg = f" Warning: ffmpeg encode timed out for clip #{idx}"
            if log_callback:
                log_callback(warn_msg)
            else:
                print(warn_msg)

        if out_path.exists() and out_path.stat().st_size > 5000:
            clip_paths.append(out_path)
            msg = f" Saved clip [{idx}/{total_count}]: {out_path.name} ({out_path.stat().st_size / 1024:.1f} KB)"
            if log_callback:
                log_callback(msg)
            else:
                print(msg)

        if progress_callback:
            progress_callback(idx, total_count)

    return clip_paths

# Backward compatibility alias
extract_serve_video_clips = extract_event_video_clips


