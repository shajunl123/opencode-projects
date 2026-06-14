import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[clip] %(message)s")
log = logging.getLogger(__name__)


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def srt_ts_to_seconds(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    blocks = re.split(r"\n\s*\n", text)
    entries = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        time_line = lines[1].strip()
        m = re.match(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", time_line)
        if not m:
            continue
        start = srt_ts_to_seconds(m.group(1))
        end = srt_ts_to_seconds(m.group(2))
        content = "\n".join(lines[2:]).strip()
        entries.append({"start": start, "end": end, "text": content})
    return entries


def clip_video(video_path: Path, start: float, end: float, output: Path) -> None:
    duration = end - start
    log.info(f"Clipping video: {start:.2f}s -> {end:.2f}s (duration={duration:.2f}s)")
    cmd = [
        "ffmpeg", "-y",
        "-ss", fmt_ts(start),
        "-i", str(video_path),
        "-t", fmt_ts(duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"ffmpeg clip failed:\n{result.stderr}")
        sys.exit(1)
    log.info(f"Clip saved: {output}")


def clip_subtitles(srt_entries: list[dict], start: float, end: float, output: Path) -> None:
    filtered = []
    for e in srt_entries:
        if e["start"] >= start - 0.1 and e["end"] <= end + 0.1:
            entry = {
                "start": e["start"] - start,
                "end": e["end"] - start,
                "text": e["text"],
            }
            filtered.append(entry)

    if not filtered:
        # If SRT is word-level, try matching by overlap
        for e in srt_entries:
            if e["start"] < end and e["end"] > start:
                entry = {
                    "start": max(0, e["start"] - start),
                    "end": min(end, e["end"] - start),
                    "text": e["text"],
                }
                filtered.append(entry)

    lines = []
    for i, e in enumerate(filtered, 1):
        start_ts = fmt_ts(e["start"]).replace(".", ",")
        end_ts = fmt_ts(e["end"]).replace(".", ",")
        # SRT timestamp format: hh:mm:ss,mmm
        lines.append(str(i))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(e["text"])
        lines.append("")

    content = "\n".join(lines)
    output.write_text(content, encoding="utf-8")
    log.info(f"Subtitle clip saved ({len(filtered)} entries): {output}")


def main():
    parser = argparse.ArgumentParser(description="Clip video + extract subtitle segment")
    parser.add_argument("video", type=Path, help="Input video file")
    parser.add_argument("srt", type=Path, help="Input SRT subtitle file")
    parser.add_argument("start", type=float, help="Start time in seconds")
    parser.add_argument("end", type=float, help="End time in seconds")
    parser.add_argument("-o", "--output", type=Path, help="Output clip prefix (default: clip)")
    args = parser.parse_args()

    for p in [args.video, args.srt]:
        if not p.exists():
            log.error(f"File not found: {p}")
            sys.exit(1)

    if args.end <= args.start:
        log.error("End time must be greater than start time")
        sys.exit(1)

    stem = args.output or Path("clip")
    clip_video_path = stem.parent / f"{stem.name}.mp4"
    clip_srt_path = stem.parent / f"{stem.name}.srt"

    srt_entries = parse_srt(args.srt)
    clip_video(args.video, args.start, args.end, clip_video_path)
    clip_subtitles(srt_entries, args.start, args.end, clip_srt_path)


if __name__ == "__main__":
    main()
