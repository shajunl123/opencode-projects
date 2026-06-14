#!/usr/bin/env python3
"""
智能章节分析 — 基于字幕内容语义切分

用 AI 分析字幕，识别话题转换点，生成 2-5 分钟章节。
替代硬性按时间切片，实现内容感知切分。

Usage:
    python analyze_chapters.py subtitles.srt -o chapters.json
    python analyze_chapters.py subtitles.srt --min-minutes 2 --max-minutes 5
"""

import argparse
import json
import re
import sys
import os
from pathlib import Path

from openai import OpenAI
from config import cfg


def parse_srt(path: Path) -> list:
    """解析 SRT 文件"""
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
        # 解析时间
        match = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", time_line)
        if match:
            start = match.group(1).replace(",", ".")
            end = match.group(2).replace(",", ".")
            entries.append({
                "index": int(idx_line),
                "start": start,
                "end": end,
                "text": content,
            })
    return entries


def time_to_seconds(time_str: str) -> float:
    """将 HH:MM:SS.mmm 转为秒"""
    parts = time_str.replace(",", ".").split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def seconds_to_time(seconds: float) -> str:
    """将秒转为 HH:MM:SS,mmm 格式"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def build_transcript(entries: list) -> str:
    """构建带时间戳的转写文本"""
    lines = []
    for e in entries:
        start_sec = time_to_seconds(e["start"])
        lines.append(f"[{start_sec:.1f}s] {e['text']}")
    return "\n".join(lines)


def analyze_chapters(entries: list, client: OpenAI, model: str,
                     min_minutes: float = 2, max_minutes: float = 5) -> list:
    """用 AI 分析字幕，生成章节"""

    transcript = build_transcript(entries)

    # 获取视频总时长
    if entries:
        total_seconds = time_to_seconds(entries[-1]["end"])
    else:
        return []

    prompt = f"""你是一个视频内容分析师。请分析以下视频字幕（带时间戳），识别话题转换点，将视频切分为章节。

要求：
1. 每个章节 2-5 分钟（最短 {min_minutes} 分钟，最长 {max_minutes} 分钟）
2. 在话题自然转换处切分（不要机械按时间切）
3. 每个章节是独立的、有意义的内容单元
4. 确保覆盖全部内容，不遗漏
5. 视频总时长: {total_seconds:.0f} 秒

请返回 JSON 数组，每个章节包含：
- "title": 章节标题（10-20字，精炼概括）
- "start": 起始时间（秒，数字）
- "end": 结束时间（秒，数字）
- "summary": 核心摘要（1-2句话，50-100字）
- "keywords": 关键词数组（3-5个）

只返回 JSON 数组，不要其他文字。

字幕内容：
{transcript[:12000]}"""

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content.strip()

    try:
        result = json.loads(content)
        # 兼容 {"chapters": [...]} 或直接 [...]
        if isinstance(result, dict):
            chapters = result.get("chapters", result.get("data", []))
        elif isinstance(result, list):
            chapters = result
        else:
            chapters = []

        # 验证和修正
        validated = []
        for i, ch in enumerate(chapters):
            if not isinstance(ch, dict):
                continue
            start = float(ch.get("start", 0))
            end = float(ch.get("end", 0))
            if end <= start:
                continue
            validated.append({
                "index": i + 1,
                "title": ch.get("title", f"Chapter {i+1}"),
                "start": start,
                "end": end,
                "start_time": seconds_to_time(start),
                "end_time": seconds_to_time(end),
                "duration_seconds": end - start,
                "summary": ch.get("summary", ""),
                "keywords": ch.get("keywords", []),
            })

        return validated

    except json.JSONDecodeError:
        print(f"[chapters] AI 返回非 JSON，尝试提取...")
        # 尝试从文本中提取 JSON
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        print(f"[chapters] 无法解析 AI 返回")
        return []


def clip_video_by_chapters(video_path: Path, chapters: list, output_dir: Path,
                           ffmpeg_path: str = "ffmpeg") -> list:
    """根据章节自动切片"""
    output_dir.mkdir(parents=True, exist_ok=True)
    clips = []

    for ch in chapters:
        start = ch["start"]
        end = ch["end"]
        title = re.sub(r'[^\w\s-]', '', ch["title"]).strip().replace(' ', '_')[:50]
        filename = f"clip_{ch['index']:02d}_{title}.mp4"
        output_path = output_dir / filename

        cmd = [
            ffmpeg_path, "-y",
            "-i", str(video_path),
            "-ss", str(start),
            "-to", str(end),
            "-c", "copy",
            str(output_path),
        ]

        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            clips.append({
                "chapter": ch,
                "file": str(output_path),
                "size_mb": output_path.stat().st_size / 1024 / 1024 if output_path.exists() else 0,
            })
            print(f"  ✅ {filename} ({ch['duration_seconds']:.0f}s)")
        else:
            print(f"  ❌ {filename} 失败: {result.stderr[:100]}")

    return clips


def main():
    parser = argparse.ArgumentParser(description="智能章节分析（AI 内容感知切分）")
    parser.add_argument("srt", type=Path, help="输入 SRT 字幕文件")
    parser.add_argument("-o", "--output", type=Path, help="输出 JSON 文件")
    parser.add_argument("--video", type=Path, help="视频文件（指定后自动切片）")
    parser.add_argument("--min-minutes", type=float, default=2, help="最短章节（分钟）")
    parser.add_argument("--max-minutes", type=float, default=5, help="最长章节（分钟）")
    parser.add_argument("--api-base", default=cfg.API_BASE_URL)
    parser.add_argument("--api-key", default=cfg.API_KEY)
    parser.add_argument("--model", default=cfg.MODEL)
    args = parser.parse_args()

    if not args.srt.exists():
        print(f"[chapters] SRT 文件不存在: {args.srt}")
        sys.exit(1)

    entries = parse_srt(args.srt)
    if not entries:
        print("[chapters] SRT 为空")
        sys.exit(1)

    print(f"[chapters] 解析 {len(entries)} 条字幕")

    client = OpenAI(base_url=args.api_base, api_key=args.api_key)
    chapters = analyze_chapters(entries, client, args.model, args.min_minutes, args.max_minutes)

    if not chapters:
        print("[chapters] AI 未返回有效章节")
        sys.exit(1)

    print(f"\n📊 分析完成，生成 {len(chapters)} 个章节：\n")
    for ch in chapters:
        duration = ch["duration_seconds"]
        print(f"  [{ch['index']}] {ch['start_time']} → {ch['end_time']} ({duration:.0f}s)")
        print(f"      {ch['title']}")
        print(f"      {ch['summary'][:80]}...")
        print()

    # 保存 JSON
    output = args.output or (args.srt.parent / "chapters.json")
    output.write_text(json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[chapters] 保存到: {output}")

    # 自动切片
    if args.video:
        if not args.video.exists():
            print(f"[chapters] 视频文件不存在: {args.video}")
            return
        output_dir = args.srt.parent / "clips"
        print(f"\n[clips] 开始切片 → {output_dir}")
        clips = clip_video_by_chapters(args.video, chapters, output_dir, cfg.FFMPEG_PATH)
        print(f"\n[clips] 完成: {len(clips)} 个片段")


if __name__ == "__main__":
    main()
