import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

for d in [DATA_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Gemini API Configuration
DEFAULT_MODEL = "gemini-2.5-flash"
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# FFMPEG path from imageio-ffmpeg
FFMPEG_PATH = r"C:\Users\bertm\anaconda3\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

# Video download settings
DEFAULT_YOUTUBE_URL = "https://youtu.be/o-E31sQlLF8"
CHUNK_DURATION_SECONDS = 300
OVERLAP_SECONDS = 10
