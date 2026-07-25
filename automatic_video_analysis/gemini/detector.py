import time
from pathlib import Path
from typing import List, Optional, Union
import cv2
from google import genai
from google.genai import types

from .config import API_KEY, DEFAULT_MODEL
from .schemas import VolleyballMatchAnalysis

def get_video_duration_sec(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps > 0 and frame_count > 0:
        return frame_count / fps
    return 99999.0

def build_multi_action_prompt(target_actions: List[str], duration_sec: float) -> str:
    actions_str = ", ".join(target_actions) if target_actions else "Serves, Spikes/Attacks"
    
    prompt = f"""
You are an elite Olympic volleyball video analyst and scout.
Analyze this video segment with 100% visual and domain precision.

VIDEO DURATION NOTICE: This video segment is exactly {duration_sec:.1f} seconds long.
CRITICAL: Do NOT report any timestamps greater than {duration_sec:.1f} seconds!

YOUR GOAL: Extract occurrences of ONLY the requested actions: [{actions_str}].

TEAM UNIFORM & COURT SIDE IDENTIFICATION RULES:
- USA TEAM: Players wear RED or WHITE jerseys. If the player is wearing a RED or WHITE shirt, team MUST be assigned as 'USA'.
- FRANCE TEAM: Players wear BLUE jerseys. If the player is wearing a BLUE shirt, team MUST be assigned as 'France'.
- `jersey_color`: State the primary shirt color (e.g. 'Red', 'White', 'Blue').
- `serving_court_side`: State the side of the court the player is standing on ('Left Side' vs 'Right Side').

STRICT DOMAIN RULES TO DISTINGUISH SERVES FROM ATTACKS:

1. SERVE (CRITICAL CRITERIA):
   - POSITION: Player MUST start OUTSIDE of the court terrain, behind the back endline in the service zone.
   - BALL PREPARATION: Player holds the ball in hand(s) and THROWS/TOSSES THE BALL UP into the air before hitting it.
   - RALLY START: This is the very first contact of a point, initiating a new rally.
   - `timestamp_start_sec`: The exact second the player is standing outside the court tossing the ball up.
   - `is_player_behind_back_line`: MUST BE TRUE.
   - `ball_tossed_up_before_hit`: MUST BE TRUE.
   - `follows_setter_pass`: MUST BE FALSE.
   - `is_ball_over_net`: MUST BE TRUE.

2. SPIKE / ATTACK (CRITICAL CRITERIA):
   - DEFINITION: Any hit during a live rally where an attacking player strikes the ball towards the opponent's court and THE BALL CROSSES OVER THE NET.
   - VARIATION: Includes hard spikes, soft tips, roll shots, back-row attacks, and overpass hits.
   - MULTIPLE ATTACKS: In a single rally there can be MULTIPLE attacks (e.g. Team A spikes -> Team B digs -> Team B sets -> Team B spikes). Record EACH attack attempt separately with its start time (jump/hit) and end time (crosses net/lands).
   - POSITION: Occurs INSIDE or NEAR court terrain (front row at net or back row inside bounds).
   - SEQUENCE: Occurs AFTER a pass/set inside an active rally (or an immediate overpass hit).
   - `is_player_behind_back_line`: MUST BE FALSE.
   - `ball_tossed_up_before_hit`: MUST BE FALSE.
   - `follows_setter_pass`: MUST BE TRUE.
   - `is_ball_over_net`: MUST BE TRUE (Do NOT count sets/passes that stay on the same side of the net!).

REJECTION RULES:
- NEVER mark a hit inside the court following a setter's set as a Serve!
- NEVER mark a hit without a ball toss up behind the endline as a Serve!
- NEVER mark a setup pass or setting action that remains on the same side of the net as an Attack!
- NEVER mark a defensive dig or block touch that stays on the same side as an Attack!

FOR EACH DETECTED EVENT:
- `action_type`: EXACT category ('Serve', 'Spike/Attack', 'Block', or 'Dig/Reception').
- `timestamp_start_sec`: Timestamp in seconds when action starts (between 0.0 and {duration_sec:.1f}).
- `timestamp_end_sec`: Timestamp in seconds when action concludes.
- `timestamp_formatted`: Time formatted as 'MM:SS'.
- `team`: Team performing the action ('USA', 'France', or 'Unknown').
- `jersey_color`: Player shirt color ('Red', 'White', 'Blue').
- `serving_court_side`: Side of court ('Left Side' vs 'Right Side').
- `is_player_behind_back_line`: True ONLY if player is outside court behind back line.
- `ball_tossed_up_before_hit`: True ONLY if player threw/tossed ball up in air before hitting.
- `follows_setter_pass`: True ONLY if hit follows a set by a setter inside rally.
- `is_ball_over_net`: True ONLY if ball travels over net to opponent court.
- `action_details`: Specific technique (e.g. 'Jump Serve', 'Float Serve', 'Cross-court Spike', 'Tip', 'Back-row Spike').
- `player_info`: Jersey number or visual description.
- `confidence`: Confidence score (0.0 to 1.0).

Be thorough, precise, and double-check jersey colors before assigning team identity.
"""
    return prompt

class ServeDetector:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.client = genai.Client(api_key=API_KEY)

    def analyze_video(
        self,
        video_path: Path,
        target_actions: Optional[List[str]] = None,
        prompt: Optional[str] = None,
        cleanup_file: bool = True
    ) -> VolleyballMatchAnalysis:
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found at {video_path}")

        duration_sec = get_video_duration_sec(video_path)
        
        if prompt is None:
            prompt = build_multi_action_prompt(
                target_actions=target_actions or ["Serve"],
                duration_sec=duration_sec
            )

        print(f"[Gemini Files API] Uploading video: {video_path.name} ({video_path.stat().st_size / (1024*1024):.1f} MB, Duration: {duration_sec:.1f}s)...")
        uploaded_file = self.client.files.upload(file=str(video_path))
        print(f"[Gemini Files API] File uploaded. ID: {uploaded_file.name}. Processing...")

        start_wait = time.time()
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(3)
            uploaded_file = self.client.files.get(name=uploaded_file.name)
            print(f" Waiting for video processing... ({int(time.time() - start_wait)}s)")

        if uploaded_file.state.name != "ACTIVE":
            raise RuntimeError(f"File upload failed with state: {uploaded_file.state.name}")

        print(f"[Gemini API] Video state is ACTIVE. Analyzing with model '{self.model_name}'...")
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VolleyballMatchAnalysis,
                    temperature=0.1
                )
            )

            print("[Gemini API] Analysis received!")
            analysis = VolleyballMatchAnalysis.model_validate_json(response.text)
            
            # Domain-rule post-filtering
            valid_events = []
            for e in analysis.events:
                if e.timestamp_start_sec > duration_sec or e.confidence < 0.65:
                    continue
                    
                # Fix team assignment if jersey color is explicitly red or white vs blue
                if e.jersey_color:
                    j_color = e.jersey_color.lower()
                    if "red" in j_color or "white" in j_color:
                        e.team = "USA"
                    elif "blue" in j_color:
                        e.team = "France"

                act_lower = e.action_type.lower()
                if "serve" in act_lower:
                    if e.is_player_behind_back_line and e.ball_tossed_up_before_hit and not e.follows_setter_pass:
                        valid_events.append(e)
                elif "spike" in act_lower or "attack" in act_lower:
                    # Attack rule: must cross over net, ball not tossed up behind endline
                    if e.is_ball_over_net and not e.ball_tossed_up_before_hit and not e.is_player_behind_back_line:
                        valid_events.append(e)
                else:
                    valid_events.append(e)
                    
            print(f"[Filter] Retained {len(valid_events)} verified actions out of {len(analysis.events)} candidates.")
            analysis.events = valid_events
            
            return analysis

        finally:
            if cleanup_file:
                try:
                    print(f"[Gemini Files API] Deleting uploaded file {uploaded_file.name}...")
                    self.client.files.delete(name=uploaded_file.name)
                except Exception as e:
                    print(f"Warning: Failed to delete file {uploaded_file.name}: {e}")

