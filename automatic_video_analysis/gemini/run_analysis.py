import argparse
import shutil
import sys
from pathlib import Path

from automatic_video_analysis.gemini.config import (
    DEFAULT_YOUTUBE_URL,
    DEFAULT_MODEL,
    OUTPUT_DIR
)
from automatic_video_analysis.gemini.downloader import download_youtube_video
from automatic_video_analysis.gemini.detector import ServeDetector
from automatic_video_analysis.gemini.postprocessor import (
    process_and_reconcile_serves,
    deduplicate_serves,
    save_analysis_reports
)
from automatic_video_analysis.gemini.verify_clips import (
    extract_serve_thumbnails,
    extract_serve_video_clips
)

def clear_output_folder():
    """Clears all existing contents in the output directory."""
    print(f"Clearing output directory: {OUTPUT_DIR}...")
    if OUTPUT_DIR.exists():
        for item in OUTPUT_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Output directory cleared.")

def run_pipeline(
    url: str = DEFAULT_YOUTUBE_URL,
    video_file: str = None,
    start_sec: int = 0,
    end_sec: int = 600,
    model_name: str = DEFAULT_MODEL,
    target_actions: list = None,
    test_folder: str = None,
    extract_clips: bool = True
):
    target_actions = target_actions or ["Serve", "Spike/Attack"]
    # Set up specific test directory if requested
    if test_folder:
        current_output_dir = OUTPUT_DIR / test_folder
    else:
        current_output_dir = OUTPUT_DIR
        
    clips_output_dir = current_output_dir / "serve_clips"
    current_output_dir.mkdir(parents=True, exist_ok=True)
    clips_output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print(f" AUTOMATIC VOLLEYBALL ANALYSIS ENGINE (MODEL: {model_name})")
    print(f" TARGET ACTIONS: {', '.join(target_actions)}")
    if test_folder:
        print(f" TEST SUBFOLDER: {test_folder}")
    print("=" * 75)
    
    # 1. Download or locate video
    if video_file and Path(video_file).exists():
        video_path = Path(video_file)
        print(f"Using local video file: {video_path}")
    else:
        print(f"Target YouTube URL: {url}")
        filename = f"sample_{start_sec}s_to_{end_sec}s.mp4"
        video_path = download_youtube_video(
            url=url,
            output_filename=filename,
            max_height=480,
            start_sec=start_sec,
            end_sec=end_sec
        )

    # 2. Analyze video segment with Gemini
    detector = ServeDetector(model_name=model_name)
    raw_analysis = detector.analyze_video(video_path=video_path, target_actions=target_actions)

    # 3. Extract Visual Clips from segment BEFORE offset conversion
    if extract_clips and raw_analysis.events:
        print(f"\n[Visual Proofs] Extracting thumbnails and video clips into {clips_output_dir.name}...")
        extract_serve_thumbnails(video_path=video_path, serves=raw_analysis.events, output_dir=clips_output_dir)
        try:
            extract_serve_video_clips(video_path=video_path, serves=raw_analysis.events, output_dir=clips_output_dir)
        except Exception as e:
            print(f"Note: Video clip extraction failed: {e}")

    # 4. Postprocess and reconcile global match timestamps
    reconciled_events = process_and_reconcile_serves(
        raw_analysis.events,
        chunk_offset_sec=float(start_sec)
    )
    final_events = deduplicate_serves(reconciled_events)
    raw_analysis.events = final_events

    # 5. Print Summary Table
    print("\n" + "=" * 75)
    print(f" DETECTED GAME ACTIONS ({len(final_events)} VERIFIED ACTIONS FOUND)")
    print("=" * 75)
    header = f"{'#':<4} | {'ACTION':<12} | {'TIME':<8} | {'TEAM':<8} | {'DETAILS':<18} | {'PLAYER INFO':<20}"
    print(header)
    print("-" * len(header))
    
    for idx, event in enumerate(final_events, 1):
        desc = (event.player_info[:18] + "...") if len(event.player_info or "") > 20 else (event.player_info or "N/A")
        det = (event.action_details[:16] + "...") if len(event.action_details or "") > 18 else (event.action_details or "N/A")
        print(f"{idx:<4} | {event.action_type:<12} | {event.timestamp_formatted:<8} | {event.team:<8} | {det:<18} | {desc:<20}")
    print("=" * 75 + "\n")

    # 6. Export JSON / CSV
    save_analysis_reports(raw_analysis, output_dir=current_output_dir, output_prefix="volleyball_actions")

    print("\nAnalysis complete! All outputs saved to:")
    print(f" - JSON & CSV: {current_output_dir}")
    print(f" - Visual Thumbnails & Clips: {clips_output_dir}")
    print("=" * 75)
    return len(final_events)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract game actions (serves, attacks) from YouTube volleyball match video.")
    parser.add_argument("--url", type=str, default=DEFAULT_YOUTUBE_URL, help="YouTube video URL")
    parser.add_argument("--video-file", type=str, default=None, help="Local video file path")
    parser.add_argument("--start", type=int, default=0, help="Start timestamp in seconds")
    parser.add_argument("--end", type=int, default=600, help="End timestamp in seconds (default 10 min preview)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--target-actions", nargs="+", default=["Serve", "Spike/Attack"], help="Target game actions (e.g. Serve Spike/Attack)")
    parser.add_argument("--test-folder", type=str, default=None, help="Subfolder under output/ for this test run")
    parser.add_argument("--clear-output", action="store_true", help="Clear the output directory before running")
    parser.add_argument("--no-clips", action="store_true", help="Disable thumbnail clip generation")

    args = parser.parse_args()
    
    if args.clear_output:
        clear_output_folder()
        
    run_pipeline(
        url=args.url,
        video_file=args.video_file,
        start_sec=args.start,
        end_sec=args.end,
        model_name=args.model,
        target_actions=args.target_actions,
        test_folder=args.test_folder,
        extract_clips=not args.no_clips
    )

