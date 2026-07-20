/** Synchronize scouting timestamps with a match video.
 *
 * Events carry a wall-clock unix `ts`; a video has its own 0-based timeline.
 * The user pins them with one or more *anchors* -- (event_ts, video_seconds)
 * pairs set by seeking the video to a known action. From those this module maps
 * any event timestamp to a video position and turns a matched action into a
 * fixed 2 s-before / 5 s-after clip window.
 *
 * Mirrors core/video_sync.py (see TRANSLATION.md). */

// Clip pulled around each action: 2 s before -> 5 s after (7 s total).
export const PRE_ROLL = 2.0;
export const POST_ROLL = 5.0;

// Video source kinds.
export const FILE = "file";
export const YOUTUBE = "youtube";

export interface Anchor {
  event_ts: number; // scouting wall-clock, unix seconds
  video_seconds: number; // position in the video (>= 0)
}

export interface VideoLink {
  source_kind: string; // FILE | YOUTUBE
  source_ref: string; // file identifier, or YouTube video id
  anchors: Anchor[];
  pre_roll: number;
  post_roll: number;
}

export function video_link(
  source_kind: string = FILE,
  source_ref = "",
  anchors: Anchor[] = [],
  pre_roll: number = PRE_ROLL,
  post_roll: number = POST_ROLL,
): VideoLink {
  return { source_kind, source_ref, anchors, pre_roll, post_roll };
}

export function video_link_to_dict(link: VideoLink): Record<string, unknown> {
  return {
    source_kind: link.source_kind,
    source_ref: link.source_ref,
    anchors: link.anchors.map((a) => [a.event_ts, a.video_seconds]),
    pre_roll: link.pre_roll,
    post_roll: link.post_roll,
  };
}

export function video_link_from_dict(d: Record<string, unknown>): VideoLink {
  const rawAnchors = Array.isArray(d.anchors) ? (d.anchors as unknown[]) : [];
  const anchors: Anchor[] = rawAnchors.map((entry) => {
    const pair = entry as [number, number];
    return { event_ts: Number(pair[0]), video_seconds: Number(pair[1]) };
  });
  return {
    source_kind: typeof d.source_kind === "string" ? d.source_kind : FILE,
    source_ref: typeof d.source_ref === "string" ? d.source_ref : "",
    anchors,
    pre_roll: typeof d.pre_roll === "number" ? d.pre_roll : PRE_ROLL,
    post_roll: typeof d.post_roll === "number" ? d.post_roll : POST_ROLL,
  };
}

/** Map a scouting timestamp to a video position (seconds), or null when the
 * link has no anchors or the event has no timestamp. One anchor -> constant
 * offset (slope 1); two or more -> piecewise-linear interpolation between the
 * surrounding anchors, extending the nearest anchor's offset outside the span.
 * The result may be negative (before the video starts); clip_window clamps it. */
export function event_to_video_time(link: VideoLink, ts: number | null): number | null {
  if (ts == null || link.anchors.length === 0) {
    return null;
  }
  const anchors = [...link.anchors].sort((a, b) => a.event_ts - b.event_ts);
  const first = anchors[0]!;
  const last = anchors[anchors.length - 1]!;
  if (ts <= first.event_ts) {
    return first.video_seconds + (ts - first.event_ts);
  }
  if (ts >= last.event_ts) {
    return last.video_seconds + (ts - last.event_ts);
  }
  for (let i = 0; i < anchors.length - 1; i++) {
    const lo = anchors[i]!;
    const hi = anchors[i + 1]!;
    if (lo.event_ts <= ts && ts <= hi.event_ts) {
      const span = hi.event_ts - lo.event_ts;
      if (span <= 0) {
        return lo.video_seconds;
      }
      const frac = (ts - lo.event_ts) / span;
      return lo.video_seconds + frac * (hi.video_seconds - lo.video_seconds);
    }
  }
  return null; // unreachable given the guards above
}

/** The (start, end) video window to play for an action at `ts`: pre_roll before
 * to post_roll after, clamped to the start of the video. */
export function clip_window(link: VideoLink, ts: number | null): [number, number] | null {
  const v = event_to_video_time(link, ts);
  if (v == null) {
    return null;
  }
  const start = Math.max(0.0, v - link.pre_roll);
  const end = Math.max(start, v + link.post_roll);
  return [start, end];
}

/** Estimate the wall-clock time at video position 0: a recording that finished
 * at `video_mtime` and ran `duration` seconds started at their difference. */
export function suggest_offset(video_mtime: number, duration: number): number {
  return video_mtime - duration;
}

const YOUTUBE_ID = /(?:v=|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([A-Za-z0-9_-]{11})/;

/** Extract the 11-char video id from a YouTube URL, or accept a bare id.
 * Returns null when nothing looks like a video id. */
export function youtube_id(url_or_id: string): string | null {
  const text = (url_or_id ?? "").trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(text)) {
    return text;
  }
  const m = YOUTUBE_ID.exec(text);
  return m != null ? m[1]! : null;
}
