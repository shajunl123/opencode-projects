#!/usr/bin/env python3
"""
batch_process.py — One-command full pipeline:
  download -> transcribe -> translate -> clip -> subtitles -> resize -> summary

Usage:
  python batch_process.py <youtube_url> [--clips START END ...] [--platform douyin]
"""

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

from config import cfg

logging.basicConfig(level=logging.INFO, format="[batch] %(message)s")
log = logging.getLogger(__name__)

TRANSLATE_RETRIES = 3
TRANSLATE_RETRY_DELAY = 5


def git_commit_push(message: str) -> None:
    try:
        subprocess.run(["git", "add", "-A"], capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", message], capture_output=True)
        subprocess.run(["git", "push"], capture_output=True, check=True)
        log.info(f"Git commit + push: {message}")
    except subprocess.CalledProcessError as e:
        log.warning(f"Git operation failed (exit {e.returncode}), continuing anyway")


def run_script(name: str, *args: str, auto_push: bool = False, push_msg: str = "",
               retry: bool = False) -> None:
    log.info(f"=== Step: {name} ===")
    max_attempts = (TRANSLATE_RETRIES + 1) if retry else 1
    for attempt in range(1, max_attempts + 1):
        cmd = [sys.executable, name] + list(args)
        log.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode == 0:
            log.info(f"=== Step '{name}' completed ===\n")
            if auto_push and push_msg:
                git_commit_push(push_msg)
            return
        log.warning(f"Step '{name}' failed (attempt {attempt}/{max_attempts})")
        if attempt < max_attempts:
            time.sleep(TRANSLATE_RETRY_DELAY)
    log.error(f"Step '{name}' failed after {max_attempts} attempts")
    sys.exit(1)


def parse_clips(clips_args: list[str]) -> list[tuple[float, float]]:
    clips = []
    i = 0
    while i < len(clips_args):
        try:
            start = float(clips_args[i])
            end = float(clips_args[i + 1])
            clips.append((start, end))
            i += 2
        except (IndexError, ValueError):
            log.error(f"Invalid clip pair at index {i}: {clips_args[i:]}")
            sys.exit(1)
    return clips


def main():
    parser = argparse.ArgumentParser(description="Full video SOP pipeline: download -> transcribe -> translate -> clip -> subtitles -> resize -> summary")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--clips", nargs="+", default=None,
                        help="Clip segments as START END pairs in seconds, e.g. --clips 10 30 45 60")
    parser.add_argument("--platform", choices=["douyin", "xiaohongshu", "bilibili", "youtube"], default=None,
                        help="Target platform for resize (skip if not set)")
    parser.add_argument("--skip-download", action="store_true", help="Skip download step (use existing files)")
    parser.add_argument("--skip-transcribe", action="store_true", help="Skip transcription step")
    parser.add_argument("--skip-translate", action="store_true", help="Skip translation step")
    parser.add_argument("--skip-summary", action="store_true", help="Skip summary generation")
    parser.add_argument("--chunk-duration", type=float, default=3.0, help="Max seconds per subtitle chunk")
    parser.add_argument("--auto-push", action="store_true", help="Git commit + push after every step")
    parser.add_argument("--bilingual", action="store_true", help="Generate bilingual subtitles (CN large + EN small)")
    parser.add_argument("--whisper-mode", default=None, choices=["precise", "fast"],
                        help="Whisper mode: precise=large-v3-turbo, fast=medium (overrides config)")
    parser.add_argument("--cookies", default=None,
                        help="Browser to extract cookies from (brave/chrome/safari)")
    args = parser.parse_args()

    auto_push = args.auto_push
    url = args.url
    output_dir = cfg.OUTPUT_DIR.resolve()

    import re
    patterns = [r"v=([a-zA-Z0-9_-]{11})", r"youtu\.be/([a-zA-Z0-9_-]{11})"]
    video_id = None
    for p in patterns:
        m = re.search(p, url)
        if m:
            video_id = m.group(1)
            break
    if not video_id:
        log.error("Could not parse video ID from URL")
        sys.exit(1)

    # ---- Step 1: Download ----
    if not args.skip_download:
        dl_args = [url, "-o", str(output_dir)]
        if args.cookies:
            dl_args.extend(["--cookies", args.cookies])
        run_script("download_video.py", *dl_args,
                    auto_push=auto_push, push_msg=f"step download: {video_id}")
    else:
        log.info("Skipping download")

    video_dir = output_dir / video_id
    video_file = video_dir / f"{video_id}.mp4"
    en_srt = video_dir / f"{video_id}.srt"
    en_srt_alt = video_dir / f"{video_id}.en.srt"
    zh_srt = video_dir / f"{video_id}.zh.srt"

    if not video_file.exists():
        mp4s = list(video_dir.glob("*.mp4"))
        if mp4s:
            video_file = mp4s[0]
        else:
            log.error(f"No video found in {video_dir}")
            sys.exit(1)

    srt_candidates = list(video_dir.glob("*.en.srt")) + list(video_dir.glob("*.srt"))
    for c in srt_candidates:
        if c.stat().st_size > 0 and en_srt is None or c.name != f"{video_id}.zh.srt":
            en_srt = c
            break
    if not en_srt or not en_srt.exists():
        en_srt = en_srt_alt if en_srt_alt.exists() else video_dir / f"{video_id}.srt"

    # ---- Step 2: Transcribe ----
    if not args.skip_transcribe:
        tr_args = [str(video_file), "-o", str(en_srt),
                    "--chunk-duration", str(args.chunk_duration)]
        if args.whisper_mode:
            tr_args.extend(["--whisper-mode", args.whisper_mode])
        run_script("transcribe.py", *tr_args,
                    auto_push=auto_push, push_msg=f"step transcribe: {video_id}")
    else:
        log.info("Skipping transcription")

    # ---- Step 3: Translate ----
    if not args.skip_translate:
        run_script("translate_srt.py", str(en_srt), "-o", str(zh_srt),
                    auto_push=auto_push, push_msg=f"step translate: {video_id}",
                    retry=True)
    else:
        log.info("Skipping translation")

    # ---- Step 4: Clip & burn subtitles ----
    clips = parse_clips(args.clips) if args.clips else []

    # Smart clip: AI analyzes subtitles and auto-clips by content
    if args.smart_clip and not clips:
        log.info("[smart-clip] AI analyzing subtitles for chapter detection...")
        run_script("analyze_chapters.py", str(zh_srt), "--video", str(video_file),
                    auto_push=auto_push, push_msg=f"smart-clip: {video_id}")
        chapters_json = video_dir / "chapters.json"
        if chapters_json.exists():
            import json as _json
            with open(chapters_json) as cf:
                chapters = _json.load(cf)
            log.info(f"[smart-clip] AI generated {len(chapters)} chapters")
        else:
            log.warning("[smart-clip] chapters.json not found")
    if clips:
        for i, (start, end) in enumerate(clips, 1):
            clip_prefix = video_dir / f"clip_{i:02d}"
            log.info(f"--- Clip {i}: {start}s -> {end}s ---")
            run_script("clip_video.py", str(video_file), str(zh_srt), str(start), str(end),
                        "-o", str(clip_prefix),
                        auto_push=auto_push, push_msg=f"step clip {i}: {video_id}")
            clip_vid = video_dir / f"clip_{i:02d}.mp4"
            clip_srt = video_dir / f"clip_{i:02d}.srt"
            if clip_vid.exists() and clip_srt.exists():
                burn_args = [str(clip_vid), str(clip_srt),
                             "-o", str(video_dir / f"clip_{i:02d}_subtitled.mp4")]
                if args.bilingual:
                    burn_args.extend(["--bilingual", "--en-srt", str(en_srt)])
                run_script("burn_subtitles.py", *burn_args,
                            auto_push=auto_push, push_msg=f"step burn clip {i}: {video_id}")
    else:
        log.info("No clips specified, burning subtitles on full video")
        out_burned = video_dir / f"{video_id}_subtitled.mp4"
        burn_args = [str(video_file), str(zh_srt), "-o", str(out_burned)]
        if args.bilingual:
            burn_args.extend(["--bilingual", "--en-srt", str(en_srt)])
        run_script("burn_subtitles.py", *burn_args,
                    auto_push=auto_push, push_msg=f"step burn: {video_id}")

    # ---- Step 5: Resize (optional) ----
    if args.platform:
        input_for_resize = video_file
        if not clips:
            input_for_resize = video_dir / f"{video_id}_subtitled.mp4"
        elif clips:
            input_for_resize = video_dir / f"clip_01_subtitled.mp4"
        if input_for_resize.exists():
            run_script("resize_video.py", str(input_for_resize), args.platform,
                        auto_push=auto_push, push_msg=f"step resize: {video_id}")
        else:
            log.warning(f"Resize input not found: {input_for_resize}")
    else:
        log.info("No platform specified, skipping resize")

    # ---- Step 6: Summary ----
    if not args.skip_summary:
        transcript_srt = zh_srt if zh_srt.exists() else en_srt
        run_script("generate_summary.py", str(transcript_srt), "-o", str(video_dir),
                    auto_push=auto_push, push_msg=f"step summary: {video_id}")
    else:
        log.info("Skipping summary generation")

    if not auto_push:
        git_commit_push(f"batch process complete: {video_id}")

    log.info("=== All steps completed successfully ===")


if __name__ == "__main__":
    main()
