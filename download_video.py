import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

from config import cfg

logging.basicConfig(level=logging.INFO, format="[download] %(message)s")
log = logging.getLogger(__name__)


def extract_video_id(url: str) -> str:
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract video ID from URL: {url}")


def download(url: str, output_dir: Path, cookies: str | None = None) -> Path:
    video_id = extract_video_id(url)
    out = output_dir / video_id
    out.mkdir(parents=True, exist_ok=True)

    video_path = out / f"{video_id}.mp4"
    if video_path.exists():
        log.info(f"Video already exists: {video_path}, skipping download")
        return video_path

    log.info(f"Downloading {url} -> {out}")

    # download best video+audio and English VTT subtitles
    cmd = [
        "yt-dlp",
        url,
        "-o", str(out / f"{video_id}.%(ext)s"),
        "--write-subs",
        "--sub-langs", "en",
        "--sub-format", "vtt",
        "--convert-subs", "srt",
        "--embed-metadata",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--restrict-filenames",
    ]
    if cookies:
        cmd.extend(["--cookies-from-browser", cookies])
    log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"yt-dlp failed:\n{result.stderr}")
        sys.exit(1)
    log.info(result.stdout.strip())

    # find downloaded video file
    found = list(out.glob(f"{video_id}.mp4"))
    if not found:
        # try with the auto-generated filename pattern
        found = list(out.glob("*.mp4"))
    if not found:
        log.error("No mp4 found after download")
        sys.exit(1)
    video_path = found[0]
    # rename if needed
    target = out / f"{video_id}.mp4"
    if video_path != target:
        target.unlink(missing_ok=True)
        video_path.rename(target)

    log.info(f"Video saved: {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description="Download YouTube video + English subtitles")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "-o", "--output-dir",
        default=cfg.OUTPUT_DIR,
        type=Path,
        help=f"Output directory (default: {cfg.OUTPUT_DIR})",
    )
    parser.add_argument(
        "--cookies", default=None,
        help="Browser to extract cookies from (brave/chrome/safari). Helps bypass YouTube anti-scraping.",
    )
    args = parser.parse_args()
    download(args.url, args.output_dir, cookies=args.cookies)


if __name__ == "__main__":
    main()
