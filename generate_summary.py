import argparse
import json
import logging
import re
import sys
from pathlib import Path

from openai import OpenAI

from config import cfg

logging.basicConfig(level=logging.INFO, format="[summary] %(message)s")
log = logging.getLogger(__name__)

PLATFORMS = ["douyin", "xiaohongshu", "wechat", "twitter"]


def extract_srt_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    blocks = re.split(r"\n\s*\n", text)
    lines = []
    for block in blocks:
        parts = block.strip().splitlines()
        if len(parts) >= 3:
            lines.append("\n".join(parts[2:]))
    return "\n".join(lines)


def generate(srt_text: str, client: OpenAI, model: str) -> dict:
    prompt = (
        "你是一个社交媒体内容策略师。根据以下视频字幕，为每个平台生成可直接发布的推广文案。"
        "返回一个 JSON 对象，key 为 douyin、xiaohongshu、wechat、twitter，"
        "每个 value 是包含 'title'（标题）和 'body'（正文）的对象。\n"
        "- douyin：抖音风格，中文短标题 + 中文描述，简短有力、热门感，正文 200 字以内\n"
        "- xiaohongshu：小红书种草风格，中文，详细个人体验、适合加 emoji，正文 300-500 字\n"
        "- wechat：公众号专业风格，中文，结构清晰、正式专业，正文 500-800 字\n"
        "- twitter：英文，简洁有趣，正文 280 字符以内\n\n"
        "字幕内容：\n"
        f"{srt_text[:8000]}"  # limit to avoid token overflow
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        log.warning("Response was not valid JSON, returning raw text")
        return {"raw": content}

    # validate structure
    for p in PLATFORMS:
        if p not in result:
            result[p] = {"title": "", "body": f"(missing platform: {p})"}
        elif isinstance(result[p], str):
            result[p] = {"title": "", "body": result[p]}

    return result


def write_outputs(result: dict, output_dir: Path, base_name: str) -> None:
    for platform in PLATFORMS:
        data = result.get(platform, {})
        title = data.get("title", "")
        body = data.get("body", "")
        content = f"# {platform}\n\n"
        if title:
            content += f"## Title\n{title}\n\n"
        content += f"## Body\n{body}\n\n"
        out_path = output_dir / f"{base_name}_{platform}.md"
        out_path.write_text(content, encoding="utf-8")
        log.info(f"Saved {platform} copy -> {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate multi-platform promotional copy from transcript"
    )
    parser.add_argument("srt", type=Path, help="Input SRT file (English or Chinese)")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Output directory for markdown files (default: same as SRT)")
    parser.add_argument("--api-base", default=cfg.API_BASE_URL)
    parser.add_argument("--api-key", default=cfg.API_KEY)
    parser.add_argument("--model", default=cfg.MODEL)
    args = parser.parse_args()

    if not args.srt.exists():
        log.error(f"SRT not found: {args.srt}")
        sys.exit(1)

    output_dir = args.output_dir or args.srt.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = args.srt.stem

    client = OpenAI(base_url=args.api_base, api_key=args.api_key)

    srt_text = extract_srt_text(args.srt)
    if not srt_text.strip():
        log.error("No subtitle text extracted")
        sys.exit(1)

    log.info(f"Extracted {len(srt_text)} chars of transcript, generating copy...")
    result = generate(srt_text, client, args.model)
    write_outputs(result, output_dir, base_name)


if __name__ == "__main__":
    main()
