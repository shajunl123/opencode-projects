import argparse
import logging
import re
import sys
from pathlib import Path

from openai import OpenAI

from config import cfg

logging.basicConfig(level=logging.INFO, format="[polish] %(message)s")
log = logging.getLogger(__name__)


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
        entries.append({"index": int(idx_line), "time": time_line, "text": content})
    return entries


def build_srt(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        lines.append(str(e["index"]))
        lines.append(e["time"])
        lines.append(e["text"])
        lines.append("")
    return "\n".join(lines)


BATCH_SIZE = 20


def polish_batch(texts: list[str], client: OpenAI, model: str) -> list[str]:
    batch = "\n---\n".join(texts)
    prompt = (
        "你是一个专业字幕润色助手。对以下中文字幕逐条进行润色，规则如下：\n"
        "1. 纠错：修正错别字、语法错误\n"
        "2. 断句：按语义断句，每行不超过12个字\n"
        "3. 合并过短行（少于4个字）\n"
        "4. 拆分过长行（超过18个字）\n"
        "保持原意和口语化风格，保留专有名词。"
        "按原顺序返回，用 --- 分隔。\n\n"
        f"{batch}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    result = resp.choices[0].message.content.strip()
    polished = re.split(r"\n---\n", result)
    if len(polished) != len(texts):
        log.warning(f"Expected {len(texts)} polished lines, got {len(polished)}. Falling back line by line.")
        return _polish_one_by_one(texts, client, model)
    return [t.strip() for t in polished]


def _polish_one_by_one(texts: list[str], client: OpenAI, model: str) -> list[str]:
    results = []
    for t in texts:
        if not t.strip():
            results.append("")
            continue
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": f"润色以下中文字幕，修正错别字和语法，按语义断句（每行≤12字）：\n\n{t}",
            }],
            temperature=0.1,
        )
        results.append(resp.choices[0].message.content.strip())
    return results


def polish_texts(texts: list[str], client: OpenAI, model: str) -> list[str]:
    results = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i: i + BATCH_SIZE]
        log.info(f"Polishing batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1} ({len(batch_texts)} entries)")
        results.extend(polish_batch(batch_texts, client, model))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Polish Chinese SRT subtitles using AI API (error correction, sentence splitting, merge/split lines)"
    )
    parser.add_argument("input", type=Path, help="Input Chinese SRT file")
    parser.add_argument("-o", "--output", type=Path, help="Output polished SRT file (default: input_stem.polished.srt)")
    parser.add_argument("--api-base", default=cfg.API_BASE_URL)
    parser.add_argument("--api-key", default=cfg.API_KEY)
    parser.add_argument("--model", default=cfg.MODEL)
    args = parser.parse_args()

    if not args.input.exists():
        log.error(f"Input not found: {args.input}")
        sys.exit(1)

    output = args.output or (args.input.parent / f"{args.input.stem}.polished.srt")

    client = OpenAI(base_url=args.api_base, api_key=args.api_key)

    entries = parse_srt(args.input)
    if not entries:
        log.error("No valid SRT entries found")
        sys.exit(1)

    log.info(f"Polishing {len(entries)} subtitle entries using {args.model}")
    texts = [e["text"] for e in entries]
    polished = polish_texts(texts, client, args.model)

    for e, zh in zip(entries, polished):
        e["text"] = zh

    srt_content = build_srt(entries)
    output.write_text(srt_content, encoding="utf-8")
    log.info(f"Polished SRT saved: {output}")


if __name__ == "__main__":
    main()
