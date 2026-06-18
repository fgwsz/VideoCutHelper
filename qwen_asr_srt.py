#!/usr/bin/env python3
# qwen_asr_vad_srt.py
"""
================================================================================
基于 VAD 分段 + Qwen3-ASR 的高精度视频字幕生成工具（含长句自动拆分）
================================================================================

【功能描述】
------------
本脚本利用 Qwen3-ASR-1.7B 模型和语音活动检测（VAD）技术，从视频文件中自动
提取语音并生成精确到句的 SRT 字幕文件。同时，自动对过长的字幕条目进行拆分，
使每行字幕长度适中，提升阅读体验。

核心流程：
1. 使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。
2. 采用 VAD 技术分析音频波形，检测所有“有效语音段”。
   - 默认使用 webrtcvad（专业 VAD 库），若未安装则自动回退到能量阈值法。
   - 静音定义：低于人耳听觉阈值（约 -50dB）或 webrtcvad 判断为非语音。
3. 将每个语音段切割为独立的小音频文件。
4. 加载 Qwen3-ASR 模型，对每个片段进行独立识别（模型仅加载一次）。
5. 将每个片段的识别文本与时间戳合并，输出标准 SRT 字幕文件。
6. 【新增】自动拆分行长超过预设阈值的字幕，按标点或比例分配时间。

【技术优势】
------------
- 时间戳精确：来自波形分析，无需依赖模型输出时间戳。
- 分段识别：模型处理短片段精度更高，尤其适合长音频。
- 高度可控：VAD 参数可调，适应不同录音环境（安静、嘈杂、远距离等）。
- 自动静音阈值：模拟人耳听觉极限，不放过微弱语音。
- 自动长句拆分：字幕更清晰易读，默认每行 ≤ 40 字符（中文）。

【依赖要求】
------------
系统工具：
  - ffmpeg           (用于音频提取)

Python 包（核心）：
  - qwen-asr         (Qwen3-ASR 模型接口)
  - torch            (深度学习框架)
  - librosa          (音频加载与处理)
  - numpy            (数值计算)
  - soundfile        (写入 WAV 片段)
  - webrtcvad        (推荐，提供最佳 VAD 效果；若缺失则自动切换至能量法)

安装命令（Ubuntu/Debian）：
  sudo apt install ffmpeg
  pip install qwen-asr torch librosa numpy soundfile
  pip install webrtcvad   # 强烈推荐

【语言支持】
------------
脚本支持 Qwen3-ASR 模型的所有语言，包括中文、英文、粤语、阿拉伯语等，
详见模型官方文档。语言参数可使用 ISO 639-1 代码（如 zh, en）或完整名称
（如 Chinese, English）。默认：zh（中文）。

【参数说明】
------------
  positional:
    video                   输入视频文件路径（必需）

  optional:
    --model_path            Qwen3-ASR 模型目录，默认 ~/Downloads/Qwen3-ASR-1.7B
    --language              识别语言，默认 zh
    --output                输出 SRT 文件路径，默认与视频同名 .srt

    --vad_method            选择 VAD 方法：'webrtc'（默认）或 'energy'
    --vad_threshold         能量阈值（仅 energy 模式），值越小越灵敏，默认 0.01
    --vad_aggressiveness    webrtcvad 激进级别（0~3），值越低越灵敏，默认 1
    --min_speech_duration_ms 最短语音段长度（毫秒），默认 300
    --min_silence_duration_ms 最短静音间隔（毫秒），默认 400

    --max_chars             每行字幕最大字符数（0 表示不拆分），默认 40
    --min_chars             拆分后最短字符数（过短合并到前一段），默认 5
    --no_split              禁用自动拆分（等同于 --max_chars 0）

【使用示例】
------------
  # 基本用法（中文，自动拆分长句）
  python qwen_asr_vad_srt.py /path/to/video.mp4

  # 指定英文识别，自定义最大字符数
  python qwen_asr_vad_srt.py video.mp4 --language en --max_chars 60

  # 使用能量法并调整灵敏度，禁用拆分
  python qwen_asr_vad_srt.py video.mp4 --vad_method energy --vad_threshold 0.005 --no_split

【调优建议】
------------
- 如果发现语音段被遗漏（识别不足）：降低 vad_threshold 或 vad_aggressiveness。
- 如果噪音被误判为语音（出现多余片段）：提高 vad_threshold 或 vad_aggressiveness。
- 如果句子被错误断开：增加 min_silence_duration_ms（如 500）。
- 如果短句（如“嗯”）被忽略：降低 min_speech_duration_ms（如 200）。
- 对于中文，max_chars 建议 30~40；英文建议 50~70。

【注意事项】
------------
- 首次运行需下载模型（若本地无），请确保网络稳定。
- 建议使用 GPU 加速（CUDA），否则 CPU 处理速度可能较慢。
- 临时音频文件会在脚本结束后自动清理。
- 如果音频无声或没有语音，脚本将输出提示并退出。

【版本信息】
------------
作者：基于 Qwen3-ASR 社区脚本定制
版本：2.1 (整合长句拆分)
更新日期：2026-06-19
================================================================================
"""

import os
import sys
import argparse
import subprocess
import tempfile
import wave
import contextlib
import re
import numpy as np
import librosa
import soundfile as sf
import torch

# ---------- 导入 Qwen3-ASR ----------
try:
    from qwen_asr import Qwen3ASRModel
except ImportError:
    print("❌ qwen-asr 未安装，请运行: pip install qwen-asr")
    sys.exit(1)


# ---------- 语言映射 ----------
QWEN_LANG_MAP = {
    'zh': 'Chinese', 'en': 'English', 'yue': 'Cantonese',
    'ar': 'Arabic', 'de': 'German', 'fr': 'French',
    'es': 'Spanish', 'pt': 'Portuguese', 'id': 'Indonesian',
    'it': 'Italian', 'ko': 'Korean', 'ru': 'Russian',
    'th': 'Thai', 'vi': 'Vietnamese', 'ja': 'Japanese',
    'tr': 'Turkish', 'hi': 'Hindi', 'ms': 'Malay',
    'nl': 'Dutch', 'sv': 'Swedish', 'da': 'Danish',
    'fi': 'Finnish', 'pl': 'Polish', 'cs': 'Czech',
    'fil': 'Filipino', 'fa': 'Persian', 'el': 'Greek',
    'ro': 'Romanian', 'hu': 'Hungarian', 'mk': 'Macedonian',
}
QWEN_LANG_REVERSE = {v: k for k, v in QWEN_LANG_MAP.items()}


def normalize_language(user_lang):
    """将用户输入转换为 Qwen 可识别的完整语言名称"""
    user_lang = user_lang.strip().lower()
    # 尝试匹配完整名称
    for full_name in QWEN_LANG_REVERSE.keys():
        if full_name.lower() == user_lang:
            return full_name
    # 尝试匹配短代码
    if user_lang in QWEN_LANG_MAP:
        return QWEN_LANG_MAP[user_lang]
    # 默认中文
    print(f"⚠️ 未知语言 '{user_lang}'，默认使用中文")
    return 'Chinese'


# ---------- VAD 实现 ----------
def detect_speech_webrtc(audio_path, aggressiveness=1,
                         min_speech_duration_ms=300,
                         min_silence_duration_ms=400):
    """
    使用 webrtcvad 进行语音活动检测
    返回: list of (start_sec, end_sec)
    """
    try:
        import webrtcvad
    except ImportError:
        raise ImportError("webrtcvad 未安装，请运行: pip install webrtcvad")

    with contextlib.closing(wave.open(audio_path, 'rb')) as wf:
        sample_rate = wf.getframerate()
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(f"不支持的采样率 {sample_rate}，仅支持 8k/16k/32k/48k")
        if wf.getnchannels() != 1:
            raise ValueError("音频必须是单声道")
        pcm_data = wf.readframes(wf.getnframes())

    vad = webrtcvad.Vad(aggressiveness)
    frame_duration_ms = 30   # 固定 30ms
    frame_bytes = int(sample_rate * frame_duration_ms / 1000) * 2  # 16bit PCM

    # 帧级语音标志
    speech_flags = []
    for i in range(0, len(pcm_data), frame_bytes):
        frame = pcm_data[i:i+frame_bytes]
        if len(frame) < frame_bytes:
            break
        try:
            is_speech = vad.is_speech(frame, sample_rate)
        except:
            is_speech = False
        speech_flags.append(is_speech)

    # 合并语音段
    min_silence_frames = int(min_silence_duration_ms / frame_duration_ms)
    min_speech_frames = int(min_speech_duration_ms / frame_duration_ms)

    segments = []
    i = 0
    while i < len(speech_flags):
        # 跳过静音
        while i < len(speech_flags) and not speech_flags[i]:
            i += 1
        if i >= len(speech_flags):
            break
        start = i
        # 寻找语音结束（连续静音帧达到阈值）
        silence_count = 0
        while i < len(speech_flags):
            if speech_flags[i]:
                silence_count = 0
                i += 1
            else:
                silence_count += 1
                i += 1
                if silence_count >= min_silence_frames:
                    break
        end = i - silence_count
        if end - start >= min_speech_frames:
            start_sec = start * frame_duration_ms / 1000.0
            end_sec = end * frame_duration_ms / 1000.0
            segments.append((start_sec, end_sec))
    return segments


def detect_speech_energy(audio_path, threshold=0.01,
                         min_speech_duration_ms=300,
                         min_silence_duration_ms=400,
                         frame_duration_ms=30):
    """
    基于能量的简单 VAD（使用 librosa）
    阈值默认 0.01，更灵敏
    """
    y, sr = librosa.load(audio_path, sr=16000)
    frame_length = int(sr * frame_duration_ms / 1000)
    hop_length = frame_length
    energy = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    max_energy = np.max(energy)
    if max_energy < 1e-10:
        return []  # 无声
    normalized = energy / max_energy
    speech_flags = normalized > threshold

    # 合并逻辑与 webrtc 类似
    min_silence_frames = int(min_silence_duration_ms / frame_duration_ms)
    min_speech_frames = int(min_speech_duration_ms / frame_duration_ms)

    segments = []
    i = 0
    while i < len(speech_flags):
        while i < len(speech_flags) and not speech_flags[i]:
            i += 1
        if i >= len(speech_flags):
            break
        start = i
        silence_count = 0
        while i < len(speech_flags):
            if speech_flags[i]:
                silence_count = 0
                i += 1
            else:
                silence_count += 1
                i += 1
                if silence_count >= min_silence_frames:
                    break
        end = i - silence_count
        if end - start >= min_speech_frames:
            start_sec = start * frame_duration_ms / 1000.0
            end_sec = end * frame_duration_ms / 1000.0
            segments.append((start_sec, end_sec))
    return segments


# ---------- 核心功能 ----------
def extract_audio(video_path, output_wav):
    """使用 ffmpeg 提取 16kHz 单声道 WAV 音频"""
    cmd = ['ffmpeg', '-i', video_path, '-ac', '1', '-ar', '16000', '-vn', output_wav, '-y']
    subprocess.run(cmd, check=True, capture_output=True)


def transcribe_segment(model, audio_path, language):
    """识别单个音频片段，返回文本"""
    results = model.transcribe(audio=audio_path, language=language)
    if results and len(results) > 0:
        first = results[0]
        text = first.text if hasattr(first, 'text') else first.get('text', '')
        return text.strip()
    return None


def generate_srt(segments_text, output_path):
    """生成 SRT 字幕文件（原始版，未拆分）"""
    def fmt_time(sec):
        hours = int(sec // 3600)
        minutes = int((sec % 3600) // 60)
        secs = int(sec % 60)
        millis = int((sec % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    with open(output_path, 'w', encoding='utf-8') as f:
        for i, (start, end, text) in enumerate(segments_text, start=1):
            if not text:
                continue
            f.write(f"{i}\n")
            f.write(f"{fmt_time(start)} --> {fmt_time(end)}\n")
            f.write(f"{text}\n\n")


# ---------- 长句拆分功能 ----------
def parse_srt(content):
    """解析 SRT 内容，返回条目列表"""
    blocks = re.split(r'\n\s*\n', content.strip())
    subtitles = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        time_line = lines[1].strip()
        match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', time_line)
        if not match:
            continue
        start_str, end_str = match.groups()
        text = ' '.join(lines[2:]).strip()
        subtitles.append({
            'index': idx,
            'start': start_str,
            'end': end_str,
            'text': text
        })
    return subtitles


def time_to_seconds(time_str):
    """将 HH:MM:SS,mmm 转换为秒（浮点数）"""
    h, m, s = time_str.split(':')
    s, ms = s.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def seconds_to_time(sec):
    """将秒数转换为 HH:MM:SS,mmm 格式"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_text_by_punctuation(text, max_chars, min_chars=5):
    """按标点拆分文本，尽量使每段不超过 max_chars"""
    if len(text) <= max_chars:
        return [text]

    # 按句子结束标点（。！？；）拆分
    sentences = re.split(r'([。！？；])', text)
    merged = []
    for i in range(0, len(sentences)-1, 2):
        merged.append(sentences[i] + sentences[i+1])
    if len(sentences) % 2 == 1:
        merged.append(sentences[-1])

    final_segments = []
    for seg in merged:
        if len(seg) <= max_chars:
            final_segments.append(seg)
        else:
            # 按次要标点（，、：）拆分
            sub_parts = re.split(r'([，、：])', seg)
            sub_merged = []
            for i in range(0, len(sub_parts)-1, 2):
                sub_merged.append(sub_parts[i] + sub_parts[i+1])
            if len(sub_parts) % 2 == 1:
                sub_merged.append(sub_parts[-1])
            for part in sub_merged:
                if len(part) <= max_chars:
                    final_segments.append(part)
                else:
                    # 强制按最大字符数切分
                    for j in range(0, len(part), max_chars):
                        final_segments.append(part[j:j+max_chars])

    # 清理空字符串
    final_segments = [s.strip() for s in final_segments if s.strip()]
    # 合并过短片段
    merged_final = []
    for seg in final_segments:
        if merged_final and len(seg) < min_chars:
            merged_final[-1] += seg
        else:
            merged_final.append(seg)
    return merged_final


def split_subtitle(sub, max_chars, min_chars):
    """处理单条字幕，返回拆分后的条目列表 (start_sec, end_sec, text)"""
    start_sec = time_to_seconds(sub['start'])
    end_sec = time_to_seconds(sub['end'])
    duration = end_sec - start_sec
    text = sub['text']

    if len(text) <= max_chars:
        return [(start_sec, end_sec, text)]

    parts = split_text_by_punctuation(text, max_chars, min_chars)
    if len(parts) == 1:
        return [(start_sec, end_sec, parts[0])]

    total_chars = sum(len(p) for p in parts)
    if total_chars == 0:
        return [(start_sec, end_sec, text)]

    results = []
    current_start = start_sec
    for i, part in enumerate(parts):
        char_ratio = len(part) / total_chars
        part_duration = duration * char_ratio
        part_end = current_start + part_duration
        if i == len(parts) - 1:
            part_end = end_sec
        results.append((current_start, part_end, part))
        current_start = part_end
    return results


def split_srt_file(input_path, output_path, max_chars, min_chars):
    """对 SRT 文件进行拆分，生成新的 SRT"""
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    subs = parse_srt(content)
    if not subs:
        print("⚠️ 无法解析 SRT 文件，跳过拆分")
        return False

    new_entries = []
    for sub in subs:
        entries = split_subtitle(sub, max_chars, min_chars)
        new_entries.extend(entries)

    # 写入新文件
    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, (start_sec, end_sec, text) in enumerate(new_entries, start=1):
            start_str = seconds_to_time(start_sec)
            end_str = seconds_to_time(end_sec)
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{text}\n\n")
    return True


# ---------- 主程序 ----------
def main():
    parser = argparse.ArgumentParser(
        description='基于 VAD 分段 + Qwen3-ASR 的视频字幕生成（含长句拆分）',
        epilog='更多细节请参阅脚本首部文档。'
    )
    parser.add_argument('video', help='输入视频文件路径')
    parser.add_argument('--model_path', default='~/Downloads/Qwen3-ASR-1.7B',
                        help='Qwen3-ASR 模型目录')
    parser.add_argument('--language', default='zh', help='识别语言（zh/en/Chinese...）')
    parser.add_argument('--output', help='输出 SRT 文件路径（默认与视频同名）')

    parser.add_argument('--vad_method', choices=['webrtc', 'energy'], default='webrtc',
                        help='VAD 方法（推荐 webrtc）')
    parser.add_argument('--vad_threshold', type=float, default=0.01,
                        help='能量阈值（仅 energy 模式），值越小越灵敏')
    parser.add_argument('--vad_aggressiveness', type=int, choices=[0,1,2,3], default=1,
                        help='webrtcvad 激进级别（0~3），越低越灵敏')
    parser.add_argument('--min_speech_duration_ms', type=int, default=300,
                        help='最短语音段（毫秒）')
    parser.add_argument('--min_silence_duration_ms', type=int, default=400,
                        help='最短静音间隔（毫秒）')

    # 长句拆分参数
    parser.add_argument('--max_chars', type=int, default=40,
                        help='每行字幕最大字符数（0 表示不拆分）')
    parser.add_argument('--min_chars', type=int, default=5,
                        help='拆分后最短字符数（过短合并到前一段）')
    parser.add_argument('--no_split', action='store_true',
                        help='禁用自动拆分（等同于 --max_chars 0）')

    args = parser.parse_args()

    # 如果禁用拆分，将 max_chars 设为 0
    if args.no_split:
        args.max_chars = 0

    # ---------- 检查输入 ----------
    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path):
        print(f"❌ 视频文件不存在: {video_path}")
        sys.exit(1)

    model_path = os.path.expanduser(args.model_path)
    if not os.path.exists(model_path):
        print(f"❌ 模型目录不存在: {model_path}")
        sys.exit(1)

    qwen_lang = normalize_language(args.language)
    print(f"🌐 识别语言: {qwen_lang}")

    if args.output:
        srt_path = args.output
    else:
        base = os.path.splitext(video_path)[0]
        srt_path = base + '.srt'

    # 临时音频文件
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_wav = tmp.name

    try:
        print("🎬 提取音频...")
        extract_audio(video_path, audio_wav)
        print("✅ 音频提取完成")

        # ---------- VAD 检测 ----------
        print("🔍 检测语音段...")
        if args.vad_method == 'webrtc':
            try:
                segments = detect_speech_webrtc(
                    audio_wav,
                    aggressiveness=args.vad_aggressiveness,
                    min_speech_duration_ms=args.min_speech_duration_ms,
                    min_silence_duration_ms=args.min_silence_duration_ms
                )
            except ImportError:
                print("⚠️ webrtcvad 未安装，自动切换至 energy 模式")
                segments = detect_speech_energy(
                    audio_wav,
                    threshold=args.vad_threshold,
                    min_speech_duration_ms=args.min_speech_duration_ms,
                    min_silence_duration_ms=args.min_silence_duration_ms
                )
        else:
            segments = detect_speech_energy(
                audio_wav,
                threshold=args.vad_threshold,
                min_speech_duration_ms=args.min_speech_duration_ms,
                min_silence_duration_ms=args.min_silence_duration_ms
            )

        if not segments:
            print("⚠️ 未检测到任何语音段，请检查音频或调整 VAD 参数")
            return

        print(f"✅ 检测到 {len(segments)} 个语音段")

        # ---------- 加载模型 ----------
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        print(f"💻 使用设备: {device}")
        print("🧠 加载 Qwen3-ASR...")
        model = Qwen3ASRModel.from_pretrained(
            model_path,
            dtype=dtype,
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            max_inference_batch_size=32,
            max_new_tokens=256
        )
        print("✅ 模型加载完成")

        # ---------- 逐段识别 ----------
        segments_text = []
        total = len(segments)
        for idx, (start, end) in enumerate(segments, start=1):
            # 切割音频片段
            y, sr = librosa.load(audio_wav, sr=16000)
            start_sample = int(start * sr)
            end_sample = int(end * sr)
            if end_sample <= start_sample:
                continue
            segment_audio = y[start_sample:end_sample]
            if len(segment_audio) < 0.1 * sr:  # 小于0.1秒跳过
                continue

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_seg:
                seg_path = tmp_seg.name
            sf.write(seg_path, segment_audio, sr)

            print(f"  识别第 {idx}/{total} 段 ({start:.2f}s - {end:.2f}s)...")
            text = transcribe_segment(model, seg_path, qwen_lang)
            os.remove(seg_path)

            if text:
                segments_text.append((start, end, text))
                preview = text[:30] + ('...' if len(text) > 30 else '')
                print(f"    -> \"{preview}\"")
            else:
                print(f"    -> (无识别结果)")

        if not segments_text:
            print("❌ 所有段落均未识别到文本")
            return

        # ---------- 生成原始 SRT ----------
        generate_srt(segments_text, srt_path)
        print(f"✅ 初始字幕已生成: {srt_path}")

        # ---------- 长句拆分（如果启用） ----------
        if args.max_chars > 0:
            print(f"✂️ 正在拆分长句（最大 {args.max_chars} 字符）...")
            # 生成拆分后的文件，覆盖原文件或另存（此处覆盖原文件）
            success = split_srt_file(srt_path, srt_path, args.max_chars, args.min_chars)
            if success:
                print("✅ 长句拆分完成，字幕已更新")
            else:
                print("⚠️ 长句拆分失败，保留原始字幕")

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(audio_wav):
            os.remove(audio_wav)


if __name__ == '__main__':
    main()
