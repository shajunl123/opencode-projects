import argparse
import logging
import re
import sys
from pathlib import Path

from openai import OpenAI

from config import cfg

logging.basicConfig(level=logging.INFO, format="[translate] %(message)s")
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


def translate_batch(texts: list[str], client: OpenAI, model: str) -> list[str]:
    batch = "\n---\n".join(texts)
    prompt = (
        "你是专业字幕翻译。将以下英文字幕逐条翻译成简体中文。"
        "要求：口语化、适合观看、保留专有名词和技术术语、每行不超过12个字。"
        "按原顺序返回，用 --- 分隔。\n\n"
        f"{batch}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    result = resp.choices[0].message.content.strip()
    translated = re.split(r"\n---\n", result)
    if len(translated) != len(texts):
        log.warning(f"Expected {len(texts)} translations, got {len(translated)}. Falling back line by line.")
        return _translate_one_by_one(texts, client, model)
    return [t.strip() for t in translated]


def translate_texts(texts: list[str], client: OpenAI, model: str) -> list[str]:
    results = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i : i + BATCH_SIZE]
        log.info(f"Translating batch {i // BATCH_SIZE + 1}/{(len(texts) - 1) // BATCH_SIZE + 1} ({len(batch_texts)} entries)")
        translated = translate_batch(batch_texts, client, model)
        results.extend(translated)
    return results


def _translate_one_by_one(texts: list[str], client: OpenAI, model: str) -> list[str]:
    results = []
    for t in texts:
        if not t.strip():
            results.append("")
            continue
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": f"将以下英文字幕翻译成简体中文，只返回翻译结果：\n\n{t}",
                }
            ],
            temperature=0.1,
        )
        results.append(resp.choices[0].message.content.strip())
    return results


def polish_subtitles(entries: list[dict]) -> list[dict]:
    polished = []
    for e in entries:
        text = e["text"].strip()
        if not text:
            polished.append(e)
            continue
        polished.append({**e, "text": text})
    merged = []
    for e in polished:
        if merged and len(e["text"]) < 4:
            merged[-1]["text"] += " " + e["text"]
        else:
            merged.append(e)
    result = []
    for e in merged:
        text = e["text"]
        if len(text) > 18:
            parts = re.split(r"([，,])", text)
            chunks = []
            buf = ""
            for p in parts:
                buf += p
                if len(buf) >= 12 and p in ("，", ","):
                    chunks.append(buf.rstrip("，,"))
                    buf = ""
            if buf:
                chunks.append(buf)
            if len(chunks) > 1:
                for c in chunks:
                    result.append({**e, "text": c.strip()})
                continue
        result.append(e)
    for i, e in enumerate(result):
        e["index"] = i + 1
    return result


def main():
    parser = argparse.ArgumentParser(description="Translate English SRT to Chinese via AI API")
    parser.add_argument("input", type=Path, help="Input English SRT file")
    parser.add_argument("-o", "--output", type=Path, help="Output Chinese SRT file (default: input_stem.zh.srt)")
    parser.add_argument("--api-base", default=cfg.API_BASE_URL)
    parser.add_argument("--api-key", default=cfg.API_KEY)
    parser.add_argument("--model", default=cfg.MODEL)
    args = parser.parse_args()

    if not args.input.exists():
        log.error(f"Input not found: {args.input}")
        sys.exit(1)

    output = args.output or (args.input.parent / f"{args.input.stem}.zh.srt")
    if output.exists():
        log.info(f"Output already exists: {output}, skipping translation")
        return

    client = OpenAI(base_url=args.api_base, api_key=args.api_key)

    entries = parse_srt(args.input)
    if not entries:
        log.error("No valid SRT entries found")
        sys.exit(1)

    log.info(f"Translating {len(entries)} subtitle entries using {args.model}")
    texts = [e["text"] for e in entries]
    translated = translate_texts(texts, client, args.model)

    for e, zh in zip(entries, translated):
        e["text"] = zh

    log.info("Polishing subtitles (merging short lines, splitting long lines)...")
    entries = polish_subtitles(entries)

    srt_content = build_srt(entries)
    output.write_text(srt_content, encoding="utf-8")
    log.info(f"Translated SRT saved: {output}")


if __name__ == "__main__":
    main()
