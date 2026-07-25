"""Live end-to-end runner: calls Gemini on a real clip and prints raw + parsed output.

Also serves as the empirical timebase probe: if a clip starting at --start returns
small timestamps (near 0), Gemini reports CLIP-relative times (our assumption).

    python tools/run_live.py "https://youtu.be/o-E31sQlLF8" --start 10:00 --end 15:00 --model gemini-2.5-flash
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai
from google.genai import types

import serve_detector as sd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--start", default="10:00")
    ap.add_argument("--end", default="15:00")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--media-resolution", default="MEDIA_RESOLUTION_LOW")
    args = ap.parse_args()

    start_s = sd.parse_timestamp(args.start)
    end_s = sd.parse_timestamp(args.end)
    client = genai.Client()

    contents = sd.build_contents(args.url, start_s, end_s, args.fps)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[sd.Serve],
        media_resolution=args.media_resolution,
        temperature=0.0,
    )
    print(f"Calling {args.model} on window [{args.start}..{args.end}] ...", file=sys.stderr)
    resp = client.models.generate_content(model=args.model, contents=contents, config=config)

    print("\n===== RAW TEXT =====")
    print(resp.text)

    um = resp.usage_metadata
    if um:
        print("\n===== USAGE =====")
        print(f"prompt={um.prompt_token_count} candidates={um.candidates_token_count} total={um.total_token_count}")

    print("\n===== PARSED (absolute video timestamps) =====")
    serves = sd.serves_from_json(resp.text, clip_start_seconds=start_s)
    for s in serves:
        print(f"  clip={s.timestamp:>6} -> video={s.video_timestamp:>8}  {s.serving_team:<7} conf={s.confidence:.2f}  {s.reasoning}")
    print(f"\n{len(serves)} serve(s).")


if __name__ == "__main__":
    main()
