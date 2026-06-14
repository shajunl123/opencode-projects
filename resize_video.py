import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[resize] %(message)s")
log = logging.getLogger(__name__)

PRESETS = {
    "douyin":   {"width": 1080, "height": 1920, "desc": "9:16 portrait"},
    "xiaohongshu": {"width": 1080, "height": 1440, "desc": "3:4 portrait"},
    "bilibili": {"width": 1920, "height": 1080, "desc": "16:9 landscape"},
    "youtube":  {"width": 1920, "height": 1080, "desc": "16:9 landscape"},
}


def probe_size(video_path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        log.error(f"Could not probe video: {video_path}")
        sys.exit(1)
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def build_filter(in_w: int, in_h: int, target_w: int, target_h: int) -> str:
    scale = max(target_w / in_w, target_h / in_h)
    new_w = int(in_w * scale)
    new_h = int(in_h * scale)
    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    return (
        f"scale={new_w}:{new_h}:flags=lanczos,"
        f"crop={target_w}:{target_h}:{x}:{y}"
    )


def resize(video_path: Path, preset: str, output: Path) -> None:
    target = PRESETS[preset]
    log.info(f"Resizing to {target['desc']} ({target['width']}x{target['height']})")

    in_w, in_h = probe_size(video_path)
    log.info(f"Input resolution: {in_w}x{in_h}")

    filter_str = build_filter(in_w, in_h, target["width"], target["height"])
    log.info(f"Filter: {filter_str}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"ffmpeg resize failed:\n{result.stderr}")
        sys.exit(1)
    log.info(f"Resized video saved: {output} ({target['desc']})")


def main():
    parser = argparse.ArgumentParser(description="Resize video for target platform aspect ratio")
    parser.add_argument("video", type=Path, help="Input video file")
    choices = ", ".join(f"{k} ({v['desc']})" for k, v in PRESETS.items())
    parser.add_argument("preset", choices=list(PRESETS.keys()),
                        help=f"Target platform preset: {choices}")
    parser.add_argument("-o", "--output", type=Path, help="Output video file (default: input_<preset>.mp4)")
    args = parser.parse_args()

    if not args.video.exists():
        log.error(f"Video not found: {args.video}")
        sys.exit(1)

    output = args.output or (args.video.parent / f"{args.video.stem}_{args.preset}.mp4")
    if output.exists():
        log.info(f"Output already exists: {output}, skipping")
        return

    resize(args.video, args.preset, output)


if __name__ == "__main__":
    main()
