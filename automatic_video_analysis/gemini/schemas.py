from pydantic import BaseModel, Field
from typing import List, Optional

class GameActionEvent(BaseModel):
    action_type: str = Field(
        default="Serve",
        description="The category of action ('Serve', 'Spike/Attack', 'Block', 'Dig/Reception')."
    )
    timestamp_start_sec: float = Field(
        description="Exact timestamp in seconds when server tosses ball behind back line, or when attacker jumps."
    )
    timestamp_end_sec: float = Field(
        description="End time in seconds when the action concludes."
    )
    timestamp_formatted: str = Field(
        description="Human readable timestamp (e.g. '01:23')."
    )
    team: str = Field(
        default="Unknown",
        description="Team performing the action ('USA', 'France', or 'Unknown'). Verify jersey color & team name on jersey."
    )
    jersey_color: Optional[str] = Field(
        default="",
        description="Color of player's shirt (e.g. 'Red', 'White', 'Blue'). USA wears Red/White, France wears Blue."
    )
    serving_court_side: Optional[str] = Field(
        default="",
        description="Side of the net the server is standing on ('Left Side', 'Right Side', 'Near Side', 'Far Side')."
    )
    is_player_behind_back_line: bool = Field(
        default=True,
        description="True ONLY if player starts OUTSIDE the court terrain, behind the back endline."
    )
    ball_tossed_up_before_hit: bool = Field(
        default=True,
        description="True ONLY if player throws/tosses the ball up in the air before hitting it."
    )
    follows_setter_pass: bool = Field(
        default=False,
        description="True ONLY if this hit follows a set by a setter inside an active rally (Attacks)."
    )
    is_ball_over_net: bool = Field(
        default=True,
        description="True ONLY if the ball travels over the net into opponent's court."
    )
    action_details: Optional[str] = Field(
        default="",
        description="Specific details (e.g., 'Jump Serve', 'Float Serve', 'Cross-court Spike', 'Tip', 'Back-row Attack')."
    )
    player_info: Optional[str] = Field(
        default="",
        description="Jersey number, shirt color, or visual description of the player."
    )
    confidence: float = Field(
        default=0.9,
        description="Confidence score (0.0 to 1.0) for this event detection."
    )

    @property
    def serving_team(self) -> str:
        return self.team
    @serving_team.setter
    def serving_team(self, value: str):
        self.team = value

    @property
    def serve_type(self) -> str:
        return self.action_details or self.action_type
    @serve_type.setter
    def serve_type(self, value: str):
        self.action_details = value

    @property
    def server_description(self) -> str:
        return self.player_info or ""
    @server_description.setter
    def server_description(self, value: str):
        self.player_info = value

ServeEvent = GameActionEvent

class VolleyballMatchAnalysis(BaseModel):
    events: List[GameActionEvent] = Field(
        default_factory=list,
        description="List of verified game actions."
    )
    match_summary: Optional[str] = Field(
        default="",
        description="Brief summary of the video segment analyzed."
    )
    
    @property
    def serves(self) -> List[GameActionEvent]:
        return [e for e in self.events if e.action_type.lower() == "serve"]
        
    @serves.setter
    def serves(self, value: List[GameActionEvent]):
        self.events = value

    @property
    def attacks(self) -> List[GameActionEvent]:
        return [e for e in self.events if "attack" in e.action_type.lower() or "spike" in e.action_type.lower()]

