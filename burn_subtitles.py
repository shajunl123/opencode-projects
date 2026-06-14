import argparse
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from config import cfg

logging.basicConfig(level=logging.INFO, format="[burn] %(message)s")
log = logging.getLogger(__name__)

FONT_RATIO = 1.7


def build_style(font_size: int, font_color: str) -> str:
    return (
        f"FontName=系统默认字体,FontSize={font_size},"
        f"PrimaryColour=&H{font_color}&,"
        f"OutlineColour=&H80000000,"
        f"BorderStyle=1,Outline=2,Shadow=1,"
        f"Alignment=2,MarginV=20"
    )


def parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    blocks = re.split(r"\n\s*\n", text)
    entries = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        idx_line = lines[0].strip()
        if not idx_line.isdigit():
            continue
        time_line = lines[1].strip()
        content = "\n".join(lines[2:]).strip()
        m = re.match(
            r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)",
            time_line,
        )
        if not m:
            continue
        entries.append({
            "index": int(idx_line),
            "start": m.group(1).replace(",", "."),
            "end": m.group(2).replace(",", "."),
            "text": content,
        })
    return entries


def srt_entries_to_ass(entries: list[dict], style_name: str) -> list[str]:
    lines = []
    for e in entries:
        start = e["start"].replace(".", ",")
        end = e["end"].replace(".", ",")
        escaped = e["text"].replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{escaped}")
    return lines


def build_bilingual_ass(zh_entries: list[dict], en_entries: list[dict],
                        zh_font_size: int, font_color: str) -> str:
    en_font_size = max(1, int(zh_font_size / FONT_RATIO))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        "PlayResX: 384\n"
        "PlayResY: 288\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: CN,系统默认字体,{zh_font_size},&H{font_color},&H{font_color},"
        f"&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,20,1\n"
        f"Style: EN,系统默认字体,{en_font_size},&H{font_color},&H{font_color},"
        f"&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,20,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    cn_lines = srt_entries_to_ass(zh_entries, "CN")
    en_lines = srt_entries_to_ass(en_entries, "EN")
    return header + "\n".join(cn_lines + en_lines)


def srt_to_ass(srt_path: Path, font_size: int, font_color: str) -> str:
    entries = parse_srt(srt_path)
    return build_bilingual_ass(entries, [], font_size, font_color)


def burn(video_path: Path, srt_path: Path, output: Path,
         font_size: int, font_color: str) -> None:
    log.info(f"Burning subtitles: {video_path} + {srt_path} -> {output}")
    style = build_style(font_size, font_color)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles={srt_path}:force_style='{style}'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output),
    ]
    log.info(f"Running: ffmpeg ... -vf subtitles=...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"ffmpeg burn failed:\n{result.stderr}")
        sys.exit(1)
    log.info(f"Subtitled video saved: {output}")


def burn_bilingual(video_path: Path, zh_srt: Path, en_srt: Path,
                   output: Path, font_size: int, font_color: str) -> None:
    log.info(f"Burning bilingual subtitles: {video_path} -> {output}")
    zh_entries = parse_srt(zh_srt)
    en_entries = parse_srt(en_srt)
    ass_content = build_bilingual_ass(zh_entries, en_entries, font_size, font_color)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ass",
                                     delete=False, encoding="utf-8") as f:
        f.write(ass_content)
        ass_path = f.name
    log.info(f"Generated bilingual ASS ({len(zh_entries)} CN + {len(en_entries)} EN entries)")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        Path(ass_path).unlink(missing_ok=True)
    except Exception:
        pass
    if result.returncode != 0:
        log.error(f"ffmpeg burn failed:\n{result.stderr}")
        sys.exit(1)
    log.info(f"Bilingual subtitled video saved: {output}")


def main():
    parser = argparse.ArgumentParser(description="Burn hard subtitles into video")
    parser.add_argument("video", type=Path, help="Input video file")
    parser.add_argument("srt", type=Path, help="Input SRT subtitle file (Chinese for bilingual)")
    parser.add_argument("-o", "--output", type=Path, help="Output video file (default: input_burned.mp4)")
    parser.add_argument("--font-size", type=int, default=24, help="Chinese font size (default: 24)")
    parser.add_argument("--font-color", default="00FFFFFF", help="Font color in AABBGGRR hex (default: 00FFFFFF = white)")
    parser.add_argument("--bilingual", action="store_true", help="Enable bilingual subtitles (CN large + EN small)")
    parser.add_argument("--en-srt", type=Path, help="English SRT file for bilingual mode (auto-detect if omitted)")
    args = parser.parse_args()

    for p in [args.video, args.srt]:
        if not p.exists():
            log.error(f"File not found: {p}")
            sys.exit(1)

    output = args.output or (args.video.parent / f"{args.video.stem}_burned.mp4")
    if output.exists():
        log.info(f"Output already exists: {output}, skipping")
        return

    if args.bilingual:
        en_srt = args.en_srt
        if not en_srt:
            candidates = list(args.srt.parent.glob("*.en.srt"))
            if not candidates:
                log.error("No English SRT found. Provide --en-srt or place .en.srt in same directory.")
                sys.exit(1)
            en_srt = candidates[0]
            log.info(f"Auto-detected English SRT: {en_srt}")
        if not en_srt.exists():
            log.error(f"English SRT not found: {en_srt}")
            sys.exit(1)
        burn_bilingual(args.video, args.srt, en_srt, output,
                       args.font_size, args.font_color)
    else:
        burn(args.video, args.srt, output, args.font_size, args.font_color)


if __name__ == "__main__":
    main()
