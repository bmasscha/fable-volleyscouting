"""Batch serve-trajectory estimation over a folder of extracted clips.

Reads a clips folder (optionally its _actions.json to pick only serve clips),
estimates each serve's trajectory via Gemini keypoints, and writes an annotated
mp4 + preview png per serve, plus a summary json.

    python tools/trajectories.py clips_pro --model gemini-3.1-pro-preview
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trajectory as tj
import court_chart


def serve_clips(clips_dir: str) -> list[str]:
    """Serve clips from _actions.json if present, else all mp4s (excluding outputs)."""
    manifest = os.path.join(clips_dir, "_actions.json")
    if os.path.exists(manifest):
        data = json.load(open(manifest, encoding="utf-8"))
        files = [os.path.join(clips_dir, r["file"]) for r in data.get("results", [])
                 if r.get("action", "serve") == "serve" and r.get("file")]
        if files:
            return [f for f in files if os.path.exists(f)]
    return sorted(f for f in glob.glob(os.path.join(clips_dir, "*.mp4"))
                  if "_traj" not in os.path.basename(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips_dir")
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(args.clips_dir, "trajectories")
    os.makedirs(out_dir, exist_ok=True)
    clips = serve_clips(args.clips_dir)
    print(f"{len(clips)} serve clip(s) to process -> {out_dir}", file=sys.stderr)

    summary = []
    court_serves = []
    for clip in clips:
        base = os.path.splitext(os.path.basename(clip))[0]
        try:
            sa = tj.estimate_serve(clip, model=args.model)
            info = tj.render_trajectory(
                clip, sa.keypoints,
                os.path.join(out_dir, f"{base}_traj.mp4"),
                preview_png=os.path.join(out_dir, f"{base}_preview.png"),
            )
            info["placement"] = sa.model_dump(exclude={"keypoints"})
            summary.append({"clip": base, **{k: info[k] for k in ("flight_points", "has_arc")},
                            "target_zone": sa.target_zone})
            court_serves.append({
                "team": sa.serving_team,
                "player": sa.server_player or base.split("_")[-1],
                "serve_from_lateral": sa.serve_from_lateral,
                "target_depth": sa.target_depth,
                "target_lateral": sa.target_lateral,
                "target_zone": sa.target_zone,
            })
            print(f"  {base}: zone={sa.target_zone} from_lat={sa.serve_from_lateral:.2f}", file=sys.stderr)
        except Exception as e:
            print(f"  {base}: FAILED {e}", file=sys.stderr)
            summary.append({"clip": base, "error": str(e)})

    if court_serves:
        chart_png = os.path.join(out_dir, "serve_placement.png")
        court_chart.render_court_chart(court_serves, chart_png)
        print(f"Top-down placement chart -> {chart_png}", file=sys.stderr)

    with open(os.path.join(out_dir, "_trajectories.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"Done -> {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
