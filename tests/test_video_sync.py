"""Tests for core.video_sync: anchor-based timestamp->video mapping and clip
windows."""
import pytest

from core.video_sync import (FILE, YOUTUBE, POST_ROLL, PRE_ROLL, Anchor,
                             VideoLink, clip_window, event_to_video_time,
                             suggest_offset, youtube_id)


def test_no_anchors_yields_no_mapping():
    link = VideoLink(source_kind=FILE, source_ref="match.mp4")
    assert event_to_video_time(link, 1000.0) is None
    assert clip_window(link, 1000.0) is None


def test_missing_timestamp_yields_no_mapping():
    link = VideoLink(anchors=[Anchor(event_ts=1000.0, video_seconds=10.0)])
    assert event_to_video_time(link, None) is None


def test_single_anchor_is_constant_offset():
    # event 1000 sits at video second 10 -> offset 990
    link = VideoLink(anchors=[Anchor(event_ts=1000.0, video_seconds=10.0)])
    assert event_to_video_time(link, 1000.0) == 10.0
    assert event_to_video_time(link, 1030.0) == 40.0
    assert event_to_video_time(link, 970.0) == -20.0  # before video start


def test_two_anchors_interpolate_and_correct_drift():
    # 100 s of wall clock spans 90 s of video (a ~10% clock/rate difference)
    link = VideoLink(anchors=[
        Anchor(event_ts=1000.0, video_seconds=0.0),
        Anchor(event_ts=1100.0, video_seconds=90.0),
    ])
    assert event_to_video_time(link, 1000.0) == 0.0
    assert event_to_video_time(link, 1100.0) == 90.0
    assert event_to_video_time(link, 1050.0) == pytest.approx(45.0)


def test_extrapolation_outside_span_uses_nearest_offset():
    link = VideoLink(anchors=[
        Anchor(event_ts=1000.0, video_seconds=0.0),
        Anchor(event_ts=1100.0, video_seconds=90.0),
    ])
    # after the last anchor: slope 1 from (1100, 90)
    assert event_to_video_time(link, 1110.0) == pytest.approx(100.0)
    # before the first: slope 1 from (1000, 0)
    assert event_to_video_time(link, 995.0) == pytest.approx(-5.0)


def test_recording_gap_between_sets_handled_by_per_segment_anchors():
    # Set 2 restarts the video clock earlier than a single global offset would
    # predict (camera was paused between sets). A second anchor fixes set 2.
    link = VideoLink(anchors=[
        Anchor(event_ts=1000.0, video_seconds=10.0),   # set 1 action
        Anchor(event_ts=2000.0, video_seconds=610.0),  # set 2 action (gap absorbed)
    ])
    # midway through set 2, near the second anchor, maps close to it
    assert event_to_video_time(link, 2000.0) == 610.0


def test_clip_window_is_pre_and_post_roll():
    link = VideoLink(anchors=[Anchor(event_ts=1000.0, video_seconds=100.0)])
    start, end = clip_window(link, 1000.0)
    assert start == 100.0 - PRE_ROLL
    assert end == 100.0 + POST_ROLL
    assert end - start == PRE_ROLL + POST_ROLL


def test_clip_window_clamped_to_video_start():
    link = VideoLink(anchors=[Anchor(event_ts=1000.0, video_seconds=1.0)])
    start, end = clip_window(link, 1000.0)
    assert start == 0.0            # 1 - 2 would be negative
    assert end == 1.0 + POST_ROLL


def test_custom_roll_values():
    link = VideoLink(anchors=[Anchor(event_ts=0.0, video_seconds=50.0)],
                     pre_roll=1.0, post_roll=3.0)
    assert clip_window(link, 0.0) == (49.0, 53.0)


def test_suggest_offset():
    # video finished (mtime) at wall-clock 5000, ran 600 s -> started at 4400
    assert suggest_offset(5000.0, 600.0) == 4400.0


def test_youtube_id_from_urls_and_bare_id():
    assert youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("not a video") is None
    assert youtube_id("") is None


def test_roundtrip_to_from_dict():
    link = VideoLink(source_kind=YOUTUBE, source_ref="dQw4w9WgXcQ",
                     anchors=[Anchor(1000.0, 10.0), Anchor(2000.0, 610.0)],
                     pre_roll=2.0, post_roll=5.0)
    restored = VideoLink.from_dict(link.to_dict())
    assert restored.source_kind == YOUTUBE
    assert restored.source_ref == "dQw4w9WgXcQ"
    assert restored.anchors == link.anchors
    assert restored.pre_roll == 2.0 and restored.post_roll == 5.0
