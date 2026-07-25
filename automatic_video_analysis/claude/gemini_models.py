"""Curated list of video-capable Gemini models for the UI dropdown.

These are ordered best-accuracy-first for this task based on our testing
(Pro 3.1 scored 7/7 on serve detection vs Flash 2.5's 6/7). The UI also allows
typing a custom model id.
"""

# (model_id, human label)
VIDEO_MODELS: list[tuple[str, str]] = [
    ("gemini-3.1-pro-preview", "Pro 3.1 — most accurate (recommended)"),
    ("gemini-2.5-flash", "Flash 2.5 — cheapest & fast"),
    ("gemini-3.6-flash", "Flash 3.6 — newer, fast"),
    ("gemini-2.5-pro", "Pro 2.5"),
]

DEFAULT_MODEL = VIDEO_MODELS[0][0]
