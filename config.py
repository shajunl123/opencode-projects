import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _detect_ffmpeg() -> str:
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "ffmpeg",
    ]
    for c in candidates:
        if shutil.which(c):
            return c
    return "ffmpeg"


class Config:
    API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
    API_KEY = os.getenv("API_KEY", "")
    MODEL = os.getenv("MODEL", "gpt-4o-mini")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
    WHISPER_MODE = os.getenv("WHISPER_MODE", "precise")
    FFMPEG_PATH = os.getenv("FFMPEG_PATH", _detect_ffmpeg())

    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))


cfg = Config()

# 本地 Whisper 模型路径（避免从 HuggingFace 下载）
WHISPER_LOCAL_MODEL = os.getenv('WHISPER_LOCAL_MODEL', '/home/ubuntu/models/whisper-base')
