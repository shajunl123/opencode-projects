# Video SOP Tools

一站式视频处理流水线：下载 YouTube 视频 → 语音识别 → 字幕翻译 → 智能剪辑 → 字幕压制 → 尺寸适配 → 多平台推广文案生成。

## 安装

```bash
pip install -r requirements.txt
```

依赖：Python 3.10+, [ffmpeg](https://ffmpeg.org/), [yt-dlp](https://github.com/yt-dlp/yt-dlp)

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `API_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `API_KEY` | API 密钥 | `sk-xxx` |
| `MODEL` | 翻译/摘要用的 LLM 模型 | `gpt-4o-mini` |
| `WHISPER_MODEL` | Whisper 模型大小 | `base` |
| `WHISPER_DEVICE` | 推理设备 | `auto` / `cpu` / `cuda` |
| `WHISPER_COMPUTE_TYPE` | 计算精度 | `auto` / `float16` |
| `OUTPUT_DIR` | 输出根目录 | `output` |

## 脚本说明

### 1. 下载 YouTube 视频 + 英文字幕

```bash
python download_video.py "https://youtube.com/watch?v=VIDEO_ID"
```

### 2. 语音识别生成 SRT

```bash
python transcribe.py video.mp4 -o output.srt --model base
```

### 3. 字幕翻译（英 -> 中）

```bash
python translate_srt.py input.srt -o output.zh.srt
```

字幕按 20 条一批自动分批翻译，避免长视频超 token 限制。

### 4. 智能剪辑（视频 + 字幕同步裁剪）

```bash
python clip_video.py video.mp4 subtitles.srt 10 30 -o clip_01
```

### 5. 字幕压制（硬字幕）

```bash
python burn_subtitles.py video.mp4 subtitles.srt -o output.mp4
```

### 6. 尺寸适配

```bash
python resize_video.py video.mp4 douyin
```

支持平台：`douyin` (9:16), `xiaohongshu` (3:4), `bilibili` (16:9), `youtube` (16:9)

### 7. 多平台推广文案生成

```bash
python generate_summary.py transcript.srt -o output_dir
```

抖音输出中文短标题+描述，小红书输出中文种草风格，公众号输出中文专业风格，Twitter 输出英文。

## 一键批量处理

```bash
python batch_process.py "https://youtube.com/watch?v=VIDEO_ID"
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--clips START END ...` | 裁剪时段，如 `--clips 10 30 45 60` |
| `--platform douyin` | 目标平台尺寸适配 |
| `--skip-download` | 跳过下载（使用已有文件） |
| `--skip-transcribe` | 跳过语音识别 |
| `--skip-translate` | 跳过翻译 |
| `--skip-summary` | 跳过文案生成 |
| `--chunk-duration 3.0` | 每段字幕最大秒数 |
| `--auto-push` | 每步完成后自动 git commit + push |

完整示例：

```bash
python batch_process.py "https://youtube.com/watch?v=VIDEO_ID" \
  --clips 15 30 60 90 \
  --platform douyin \
  --auto-push
```
