from pathlib import Path
from typing import List, Tuple
import cv2
import numpy as np

class TrajectoryPlotterAddon:
    """
    Extensible Addon for plotting ball trajectory arcs and court heatmaps.
    Can be expanded with Deep Learning ball tracking keypoint models (e.g. TrackNet / YOLO-volleyball).
    """
    def __init__(self):
        self.enabled = True

    def draw_trajectory_overlay(
        self,
        clip_path: Path,
        trajectory_points: List[Tuple[int, int]],
        output_path: Path
    ) -> Path:
        """
        Draws a smooth cyan/yellow glowing parabola trajectory arc onto an MP4 video clip.
        """
        if not clip_path.exists() or len(trajectory_points) < 2:
            return clip_path

        cap = cv2.VideoCapture(str(clip_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            # Draw accumulated trajectory points up to current frame
            curr_points = trajectory_points[:min(frame_idx + 1, len(trajectory_points))]
            for i in range(1, len(curr_points)):
                pt1 = curr_points[i - 1]
                pt2 = curr_points[i]
                # Glowing trajectory line
                cv2.line(frame, pt1, pt2, (255, 255, 0), 4, cv2.LINE_AA)
                cv2.circle(frame, pt2, 6, (0, 255, 255), -1)

            out.write(frame)
            frame_idx += 1

        cap.release()
        out.release()
        return output_path
