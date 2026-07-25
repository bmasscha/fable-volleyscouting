import unittest
from pathlib import Path
from automatic_video_analysis.gemini.schemas import GameActionEvent, VolleyballMatchAnalysis
from automatic_video_analysis.gemini.postprocessor import (
    format_timestamp,
    process_and_reconcile_serves,
    deduplicate_serves
)

class TestVolleyballAnalysisPipeline(unittest.TestCase):

    def test_format_timestamp(self):
        self.assertEqual(format_timestamp(45.0), "00:45")
        self.assertEqual(format_timestamp(125.0), "02:05")
        self.assertEqual(format_timestamp(3665.0), "01:01:05")

    def test_schema_validation(self):
        event = GameActionEvent(
            action_type="Serve",
            timestamp_start_sec=15.5,
            timestamp_end_sec=20.2,
            timestamp_formatted="00:15",
            team="France",
            is_player_behind_back_line=True,
            ball_tossed_up_before_hit=True,
            follows_setter_pass=False,
            action_details="Jump Serve",
            player_info="#9 Blue shirt",
            confidence=0.95
        )
        analysis = VolleyballMatchAnalysis(events=[event], match_summary="Test match segment")
        
        json_data = analysis.model_dump_json()
        restored = VolleyballMatchAnalysis.model_validate_json(json_data)
        
        self.assertEqual(len(restored.events), 1)
        self.assertEqual(restored.events[0].team, "France")
        self.assertTrue(restored.events[0].is_player_behind_back_line)
        self.assertTrue(restored.events[0].ball_tossed_up_before_hit)
        self.assertFalse(restored.events[0].follows_setter_pass)
        self.assertEqual(len(restored.serves), 1)

    def test_attack_schema_validation(self):
        event = GameActionEvent(
            action_type="Spike/Attack",
            timestamp_start_sec=22.0,
            timestamp_end_sec=24.5,
            timestamp_formatted="00:22",
            team="USA",
            is_player_behind_back_line=False,
            ball_tossed_up_before_hit=False,
            follows_setter_pass=True,
            is_ball_over_net=True,
            action_details="Cross-court Spike",
            player_info="#12 Red shirt",
            confidence=0.92
        )
        analysis = VolleyballMatchAnalysis(events=[event], match_summary="Attack test segment")
        
        json_data = analysis.model_dump_json()
        restored = VolleyballMatchAnalysis.model_validate_json(json_data)
        
        self.assertEqual(len(restored.events), 1)
        self.assertEqual(len(restored.attacks), 1)
        self.assertEqual(len(restored.serves), 0)
        self.assertEqual(restored.attacks[0].team, "USA")
        self.assertTrue(restored.attacks[0].is_ball_over_net)
        self.assertTrue(restored.attacks[0].follows_setter_pass)

    def test_timestamp_reconciliation(self):
        events = [
            GameActionEvent(
                action_type="Serve",
                timestamp_start_sec=10.0,
                timestamp_end_sec=15.0,
                timestamp_formatted="00:10",
                team="USA",
                action_details="Float Serve",
                is_player_behind_back_line=True,
                ball_tossed_up_before_hit=True,
                follows_setter_pass=False
            ),
            GameActionEvent(
                action_type="Spike/Attack",
                timestamp_start_sec=20.0,
                timestamp_end_sec=23.0,
                timestamp_formatted="00:20",
                team="France",
                action_details="Line Spike",
                is_player_behind_back_line=False,
                ball_tossed_up_before_hit=False,
                follows_setter_pass=True,
                is_ball_over_net=True
            )
        ]
        reconciled = process_and_reconcile_serves(events, chunk_offset_sec=300.0)
        self.assertEqual(reconciled[0].timestamp_start_sec, 310.0)
        self.assertEqual(reconciled[0].timestamp_formatted, "05:10")
        self.assertEqual(reconciled[1].timestamp_start_sec, 320.0)
        self.assertEqual(reconciled[1].timestamp_formatted, "05:20")

    def test_deduplication(self):
        events = [
            GameActionEvent(
                action_type="Serve",
                timestamp_start_sec=10.0,
                timestamp_end_sec=15.0,
                timestamp_formatted="00:10",
                team="France",
                action_details="Jump Serve",
                is_player_behind_back_line=True,
                ball_tossed_up_before_hit=True,
                follows_setter_pass=False,
                confidence=0.8
            ),
            GameActionEvent(
                action_type="Serve",
                timestamp_start_sec=12.0,
                timestamp_end_sec=17.0,
                timestamp_formatted="00:12",
                team="France",
                action_details="Jump Serve",
                is_player_behind_back_line=True,
                ball_tossed_up_before_hit=True,
                follows_setter_pass=False,
                confidence=0.95
            ),
            GameActionEvent(
                action_type="Spike/Attack",
                timestamp_start_sec=25.0,
                timestamp_end_sec=28.0,
                timestamp_formatted="00:25",
                team="USA",
                action_details="Cross-court Spike",
                is_player_behind_back_line=False,
                ball_tossed_up_before_hit=False,
                follows_setter_pass=True,
                is_ball_over_net=True,
                confidence=0.9
            ),
            GameActionEvent(
                action_type="Spike/Attack",
                timestamp_start_sec=26.5,
                timestamp_end_sec=29.0,
                timestamp_formatted="00:26",
                team="USA",
                action_details="Cross-court Spike",
                is_player_behind_back_line=False,
                ball_tossed_up_before_hit=False,
                follows_setter_pass=True,
                is_ball_over_net=True,
                confidence=0.85
            ),
        ]
        deduped = deduplicate_serves(events, min_gap_seconds=3.0)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].action_type, "Serve")
        self.assertEqual(deduped[0].confidence, 0.95)
        self.assertEqual(deduped[1].action_type, "Spike/Attack")
        self.assertEqual(deduped[1].timestamp_start_sec, 25.0)

if __name__ == "__main__":
    unittest.main()

