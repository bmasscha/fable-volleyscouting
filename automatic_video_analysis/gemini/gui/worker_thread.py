import sys
from pathlib import Path
from typing import List, Optional

from .qt_compat import QThread, Signal
from ..config import DEFAULT_YOUTUBE_URL, DEFAULT_MODEL, OUTPUT_DIR
from ..preprocessor import prepare_video_segment
from ..detector import ServeDetector
from ..postprocessor import process_and_reconcile_serves, deduplicate_serves, save_analysis_reports
from ..verify_clips import extract_serve_thumbnails, extract_serve_video_clips

class AnalysisWorker(QThread):
    sig_log = Signal(str)
    sig_progress = Signal(int)
    sig_finished = Signal(object, str)
    sig_error = Signal(str)

    def __init__(
        self,
        url_or_path: str,
        is_local_file: bool,
        start_sec: int,
        end_sec: int,
        model_name: str,
        target_actions: List[str],
        output_dir: Path,
        clip_padding_sec: float = 1.0,
        extract_clips: bool = True
    ):
        super().__init__()
        self.url_or_path = url_or_path
        self.is_local_file = is_local_file
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.model_name = model_name
        self.target_actions = target_actions
        self.output_dir = Path(output_dir)
        self.clip_padding_sec = clip_padding_sec
        self.extract_clips = extract_clips

    def run(self):
        try:
            self.sig_progress.emit(10)
            self.sig_log.emit("Starting Fast Volleyball Video Analysis Pipeline...")

            # 1. Prepare 480p Video Segment
            self.sig_log.emit(f"Preparing 480p video segment ({self.start_sec}s to {self.end_sec}s)...")
            video_path = prepare_video_segment(
                url_or_file=self.url_or_path,
                is_local_file=self.is_local_file,
                start_sec=self.start_sec,
                end_sec=self.end_sec,
                target_height=480
            )

            self.sig_progress.emit(35)

            # 2. Upload and Analyze with Gemini API
            self.sig_log.emit(f"Uploading optimized 480p video segment to Gemini Files API (Model: {self.model_name})...")
            detector = ServeDetector(model_name=self.model_name)
            
            self.sig_log.emit(f"Targeting actions: {', '.join(self.target_actions)}...")
            raw_analysis = detector.analyze_video(
                video_path=video_path,
                target_actions=self.target_actions
            )

            self.sig_progress.emit(75)

            # 3. Clip Generation
            clips_dir = self.output_dir / "serve_clips"
            if self.extract_clips and raw_analysis.events:
                total_events = len(raw_analysis.events)
                self.sig_log.emit(f"Extracting visual thumbnails for {total_events} events into {clips_dir.name}...")
                
                def thumb_prog(curr, tot):
                    prog = 75 + int((curr / tot) * 8)
                    self.sig_progress.emit(prog)

                extract_serve_thumbnails(
                    video_path=video_path,
                    events=raw_analysis.events,
                    output_dir=clips_dir,
                    log_callback=self.sig_log.emit,
                    progress_callback=thumb_prog
                )
                self.sig_progress.emit(83)
                
                self.sig_log.emit(f"Extracting MP4 video proof clips for {total_events} events into {clips_dir.name}...")
                
                def clip_prog(curr, tot):
                    prog = 83 + int((curr / tot) * 12)
                    self.sig_progress.emit(prog)

                try:
                    extract_serve_video_clips(
                        video_path=video_path,
                        events=raw_analysis.events,
                        output_dir=clips_dir,
                        padding_sec=self.clip_padding_sec,
                        log_callback=self.sig_log.emit,
                        progress_callback=clip_prog
                    )

                except Exception as e:
                    self.sig_log.emit(f"Warning during video clip extraction: {e}")

            self.sig_progress.emit(95)


            # 4. Post-processing & Reports
            reconciled_serves = process_and_reconcile_serves(
                raw_analysis.events,
                chunk_offset_sec=float(self.start_sec)
            )
            final_serves = deduplicate_serves(reconciled_serves)
            raw_analysis.events = final_serves

            json_path, csv_path = save_analysis_reports(
                raw_analysis,
                output_dir=self.output_dir,
                output_prefix="volleyball_actions"
            )

            self.sig_progress.emit(100)
            self.sig_log.emit(f"Analysis complete! Detected {len(final_serves)} actions. Saved reports to {self.output_dir}")
            self.sig_finished.emit(raw_analysis, str(self.output_dir))

        except Exception as e:
            self.sig_log.emit(f"ERROR: {str(e)}")
            self.sig_error.emit(str(e))
