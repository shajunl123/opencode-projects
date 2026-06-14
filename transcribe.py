import argparse
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from config import cfg

logging.basicConfig(level=logging.INFO, format="[transcribe] %(message)s")
log = logging.getLogger(__name__)


def fmt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def extract_audio(video_path: Path, wav_path: Path) -> None:
    log.info(f"Extracting audio: {video_path} -> {wav_path}")
    cmd = [
        cfg.FFMPEG_PATH, "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"ffmpeg failed:\n{result.stderr}")
        sys.exit(1)


def transcribe(audio_path: Path, model_name: str, device: str,
               compute_type: str, language: str | None = None) -> list:
    log.info(f"Loading whisper model '{model_name}' (device={device}, compute={compute_type})")
    # 优先用本地模型
    import os
    local_model = os.environ.get("WHISPER_LOCAL_MODEL", "")
    model_path = local_model if local_model and os.path.exists(local_model) else model_name
    model = WhisperModel(model_path, device=device, compute_type=compute_type)

    log.info("Transcribing (word-level timestamps)...")
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        language=language,
    )
    lang = info.language if language is None else language
    log.info(f"Language: {lang} (p={info.language_probability:.2f})")

    words = []
    for seg in segments:
        for w in seg.words:
            words.append({
                "text": w.word.strip(),
                "start": w.start,
                "end": w.end,
            })
    return words


def words_to_srt(words: list, chunk_duration: float = 3.0) -> str:
    if not words:
        return ""

    lines = []
    idx = 1
    i = 0
    while i < len(words):
        chunk_words = []
        chunk_start = words[i]["start"]
        chunk_end = chunk_start
        while i < len(words) and (words[i]["end"] - chunk_start) < chunk_duration:
            chunk_words.append(words[i])
            chunk_end = words[i]["end"]
            i += 1

        if not chunk_words:
            # ensure progress
            chunk_words.append(words[i])
            chunk_end = words[i]["end"]
            i += 1

        text = " ".join(w["text"] for w in chunk_words)
        lines.append(f"{idx}")
        lines.append(f"{fmt_timestamp(chunk_start)} --> {fmt_timestamp(chunk_end)}")
        lines.append(text)
        lines.append("")
        idx += 1

    return "\n".join(lines)


WHISPER_MODE_MODELS = {
    "precise": "large-v3-turbo",
    "fast": "medium",
}


def resolve_model(model: str | None, whisper_mode: str | None) -> str:
    if model:
        return model
    mode = (whisper_mode or cfg.WHISPER_MODE).lower()
    return WHISPER_MODE_MODELS.get(mode, cfg.WHISPER_MODEL)


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe video/audio to SRT using faster-whisper"
    )
    parser.add_argument("input", type=Path, help="Input video or audio file")
    parser.add_argument("-o", "--output", type=Path, help="Output SRT file (default: input_dir/<basename>.srt)")
    parser.add_argument("--model", default=None, help="Whisper model size (overrides WHISPER_MODE)")
    parser.add_argument("--whisper-mode", default=None, choices=["precise", "fast"],
                        help="Whisper mode: precise=large-v3-turbo, fast=medium")
    parser.add_argument("--language", default=None, help="Source language code (e.g. en, zh; default: auto-detect)")
    parser.add_argument("--device", default=cfg.WHISPER_DEVICE, help=f"Inference device (default: {cfg.WHISPER_DEVICE})")
    parser.add_argument(
        "--compute-type", default=cfg.WHISPER_COMPUTE_TYPE,
        help=f"Compute type (default: {cfg.WHISPER_COMPUTE_TYPE})",
    )
    parser.add_argument("--chunk-duration", type=float, default=3.0, help="Max seconds per subtitle chunk (default: 3.0)")
    args = parser.parse_args()

    if not args.input.exists():
        log.error(f"Input not found: {args.input}")
        sys.exit(1)

    model_name = resolve_model(args.model, args.whisper_mode)
    log.info(f"Using model: {model_name} (mode={args.whisper_mode or cfg.WHISPER_MODE})")

    input_stem = args.input.stem
    srt_path = args.output or (args.input.parent / f"{input_stem}.srt")
    if srt_path.exists():
        log.info(f"SRT already exists: {srt_path}, skipping transcription")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        extract_audio(args.input, wav_path)
        words = transcribe(wav_path, model_name, args.device,
                           args.compute_type, language=args.language)

    srt_content = words_to_srt(words, args.chunk_duration)
    srt_path.write_text(srt_content, encoding="utf-8")
    log.info(f"SRT saved ({len(words)} words, {srt_path.stat().st_size} bytes): {srt_path}")


if __name__ == "__main__":
    main()
