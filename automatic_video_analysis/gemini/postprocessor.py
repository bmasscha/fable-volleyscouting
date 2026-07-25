import csv
import json
from pathlib import Path
from typing import List, Optional

from .config import OUTPUT_DIR
from .schemas import GameActionEvent, VolleyballMatchAnalysis

def format_timestamp(seconds: float) -> str:
    """Formats seconds into HH:MM:SS or MM:SS string."""
    seconds = int(round(seconds))
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

def process_and_reconcile_events(
    events: List[GameActionEvent],
    chunk_offset_sec: float = 0.0
) -> List[GameActionEvent]:
    adjusted_events = []
    for e in events:
        global_start = e.timestamp_start_sec + chunk_offset_sec
        global_end = e.timestamp_end_sec + chunk_offset_sec
        
        event_dict = e.model_dump()
        event_dict["timestamp_start_sec"] = global_start
        event_dict["timestamp_end_sec"] = global_end
        event_dict["timestamp_formatted"] = format_timestamp(global_start)
        
        adjusted_events.append(GameActionEvent(**event_dict))
    return adjusted_events

# Backward compatibility alias
process_and_reconcile_serves = process_and_reconcile_events

def deduplicate_events(events: List[GameActionEvent], min_gap_seconds: float = 3.0) -> List[GameActionEvent]:
    if not events:
        return []
        
    sorted_events = sorted(events, key=lambda x: x.timestamp_start_sec)
    deduped = [sorted_events[0]]
    
    for current in sorted_events[1:]:
        last = deduped[-1]
        gap = current.timestamp_start_sec - last.timestamp_start_sec
        same_action = (current.action_type.lower() == last.action_type.lower())
        same_team = (current.team.lower() == last.team.lower())
        
        # Deduplicate if same action type & team within min_gap_seconds
        if same_action and same_team and (gap <= min_gap_seconds):
            if current.confidence > last.confidence:
                deduped[-1] = current
        else:
            deduped.append(current)
                
    return deduped

# Backward compatibility alias
deduplicate_serves = deduplicate_events


def save_analysis_reports(
    analysis: VolleyballMatchAnalysis,
    output_dir: Optional[Path] = None,
    output_prefix: str = "volleyball_actions"
) -> tuple[Path, Path]:
    target_dir = output_dir or OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = target_dir / f"{output_prefix}_analysis.json"
    csv_path = target_dir / f"{output_prefix}_log.csv"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis.model_dump(), f, indent=2, ensure_ascii=False)
        
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Index", "Action Type", "Formatted Time", "Start Sec", "End Sec",
            "Team", "Action Details", "Player Info", "Confidence"
        ])
        for idx, event in enumerate(analysis.events, 1):
            writer.writerow([
                idx,
                event.action_type,
                event.timestamp_formatted,
                f"{event.timestamp_start_sec:.1f}",
                f"{event.timestamp_end_sec:.1f}",
                event.team,
                event.action_details,
                event.player_info,
                f"{event.confidence:.2f}"
            ])
            
    print(f"Reports saved to {target_dir}:")
    print(f" - JSON: {json_path.name}")
    print(f" - CSV:  {csv_path.name}")
    return json_path, csv_path
