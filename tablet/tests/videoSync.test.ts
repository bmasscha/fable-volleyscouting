import { describe, expect, test } from "vitest";

import {
  FILE,
  POST_ROLL,
  PRE_ROLL,
  YOUTUBE,
  clip_window,
  event_to_video_time,
  suggest_offset,
  video_link,
  video_link_from_dict,
  video_link_to_dict,
} from "../src/core/videoSync";

describe("event_to_video_time", () => {
  test("no anchors -> null", () => {
    const link = video_link(FILE, "match.mp4");
    expect(event_to_video_time(link, 1000)).toBeNull();
    expect(clip_window(link, 1000)).toBeNull();
  });

  test("missing timestamp -> null", () => {
    const link = video_link(FILE, "match.mp4", [{ event_ts: 1000, video_seconds: 10 }]);
    expect(event_to_video_time(link, null)).toBeNull();
  });

  test("single anchor is a constant offset", () => {
    const link = video_link(FILE, "m", [{ event_ts: 1000, video_seconds: 10 }]);
    expect(event_to_video_time(link, 1000)).toBe(10);
    expect(event_to_video_time(link, 1030)).toBe(40);
    expect(event_to_video_time(link, 970)).toBe(-20);
  });

  test("two anchors interpolate and correct drift", () => {
    const link = video_link(FILE, "m", [
      { event_ts: 1000, video_seconds: 0 },
      { event_ts: 1100, video_seconds: 90 },
    ]);
    expect(event_to_video_time(link, 1000)).toBe(0);
    expect(event_to_video_time(link, 1100)).toBe(90);
    expect(event_to_video_time(link, 1050)).toBeCloseTo(45);
  });

  test("extrapolation outside the span uses the nearest offset", () => {
    const link = video_link(FILE, "m", [
      { event_ts: 1000, video_seconds: 0 },
      { event_ts: 1100, video_seconds: 90 },
    ]);
    expect(event_to_video_time(link, 1110)).toBeCloseTo(100);
    expect(event_to_video_time(link, 995)).toBeCloseTo(-5);
  });

  test("per-segment anchors absorb a recording gap between sets", () => {
    const link = video_link(FILE, "m", [
      { event_ts: 1000, video_seconds: 10 },
      { event_ts: 2000, video_seconds: 610 },
    ]);
    expect(event_to_video_time(link, 2000)).toBe(610);
  });
});

describe("clip_window", () => {
  test("is pre-roll before to post-roll after", () => {
    const link = video_link(FILE, "m", [{ event_ts: 1000, video_seconds: 100 }]);
    expect(clip_window(link, 1000)).toEqual([100 - PRE_ROLL, 100 + POST_ROLL]);
  });

  test("clamps to the start of the video", () => {
    const link = video_link(FILE, "m", [{ event_ts: 1000, video_seconds: 1 }]);
    expect(clip_window(link, 1000)).toEqual([0, 1 + POST_ROLL]);
  });

  test("honors custom roll values", () => {
    const link = video_link(FILE, "m", [{ event_ts: 0, video_seconds: 50 }], 1, 3);
    expect(clip_window(link, 0)).toEqual([49, 53]);
  });
});

test("suggest_offset = mtime - duration", () => {
  expect(suggest_offset(5000, 600)).toBe(4400);
});

test("video_link round-trips through dict", () => {
  const link = video_link(YOUTUBE, "dQw4w9WgXcQ", [
    { event_ts: 1000, video_seconds: 10 },
    { event_ts: 2000, video_seconds: 610 },
  ]);
  const restored = video_link_from_dict(video_link_to_dict(link));
  expect(restored.source_kind).toBe(YOUTUBE);
  expect(restored.source_ref).toBe("dQw4w9WgXcQ");
  expect(restored.anchors).toEqual(link.anchors);
  expect(restored.pre_roll).toBe(2);
  expect(restored.post_roll).toBe(5);
});
