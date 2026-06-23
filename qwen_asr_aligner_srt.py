#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：基于 Qwen3-ASR + Qwen3-ForcedAligner 的高精度视频字幕生成工具
更新日期： 2026-06-20
================================================================================

【项目描述】
-------------
本工具利用通义实验室开源的 Qwen3-ASR 语音识别模型和 Qwen3-ForcedAligner
强制对齐模型，从视频文件中提取语音，生成**词级时间戳精确到毫秒**的 SRT 字幕。
它通过 VAD（语音活动检测）自动切分音频，再对每个语音段分别进行 ASR 识别和
强制对齐，从而：
- 避免长音频对齐模型的长度限制；
- 提高短语音段的对齐精度；
- 支持任意时长的视频处理。

【核心优势】
-------------
1. **时间戳精准**：强制对齐技术预测每个字/词的起止时间，精度达毫秒级。
2. **保留标点**：字幕文本完整保留原始标点符号，更符合阅读习惯。
3. **自动拆分**：按标点（句号、逗号等）拆分长句，确保每行字幕不超过设定长度。
4. **多语言支持**：支持中文、英文、粤语、日、韩、法、德等 10+ 种语言。
5. **操作简单**：无需手动配置 VAD 参数，开箱即用。

【依赖环境】
-------------
- Python 3.10+
- 系统工具：ffmpeg
- Python 包：qwen-asr, webrtcvad
在执行此脚本之前,请运行以下脚本安装依赖:
```bash
#下载模型
./download_qwen_asr.sh
#安装依赖库
./install_qwen_asr.sh
```
之后可以使用过如下的方式运行此脚本:
```bash
source asr_env/bin/activate
#... 这里是运行此脚本的位置
deactivate
```

【使用方法】
-------------
基本命令：
    python qwen_asr_aligner_srt.py <video_path> [选项]

【参数说明】
-------------
位置参数：
    video                   输入视频文件路径（必需）

可选参数：
    --asr_model             Qwen3-ASR 模型名称或路径，默认为此脚本目录下的'Qwen/Qwen3-ASR-1.7B'
    --aligner_model         Qwen3-ForcedAligner 模型名称或路径，默认为此脚本目录下的'Qwen/Qwen3-ForcedAligner-0.6B'
    --language              识别语言，支持 zh/en/yue/ja/ko/fr/de/es/pt/ru/it，默认 'zh'
    --output                输出 SRT 文件路径，默认与视频同名
    --max_chars             每行字幕最大字符数（按 Unicode 字符计数，中文英文均算1个），默认 10
    --min_chars             拆分后最短字符数（过短合并到前一段），默认 2
    --device                推理设备，可选 'cuda' 或 'cpu'，默认自动检测
    --min_speech_duration_ms 最短语音段（毫秒），默认 300
    --min_silence_duration_ms 最短静音间隔（毫秒），默认 400

【使用示例】
-------------
# 基本用法（中文，每行最多 10 个字符）
python qwen_asr_aligner_srt.py /path/to/video.mp4

# 指定英文，调整字幕长度（例如 20 个字符）
python qwen_asr_aligner_srt.py video.mp4 --language en --max_chars 20

# 使用 CPU 推理（速度较慢）
python qwen_asr_aligner_srt.py video.mp4 --device cpu

================================================================================
"""

import os
import sys
import re
import argparse
import subprocess
import tempfile
import contextlib
import wave
import time
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import librosa
import soundfile as sf
import torch

# 导入 qwen-asr 库
try:
    from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner
except ImportError as e:
    print(f"❌ qwen-asr 未正确安装: {e}")
    print("请运行: pip install qwen-asr")
    sys.exit(1)

# ============================================================================
# 获取脚本所在目录，用于构建本地模型默认路径
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASR_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ASR-1.7B")
DEFAULT_ALIGNER_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ForcedAligner-0.6B")


# ============================================================================
# 辅助函数
# ============================================================================

def normalize_language(user_lang: str) -> str:
    """
    将用户输入的语言代码或名称标准化为 Qwen3-ForcedAligner 支持的语言全称。

    Args:
        user_lang: 用户输入的语言标识（如 'zh', 'Chinese', 'en'）

    Returns:
        标准化后的语言全称（如 'Chinese'），若不支持则默认返回 'Chinese'
    """
    SUPPORTED_MAP = {
        'zh': 'Chinese', 'en': 'English', 'yue': 'Cantonese',
        'fr': 'French', 'de': 'German', 'it': 'Italian',
        'ja': 'Japanese', 'ko': 'Korean', 'pt': 'Portuguese',
        'ru': 'Russian', 'es': 'Spanish'
    }
    user_lang = user_lang.strip().lower()
    for full_name in SUPPORTED_MAP.values():
        if full_name.lower() == user_lang:
            return full_name
    if user_lang in SUPPORTED_MAP:
        return SUPPORTED_MAP[user_lang]
    print(f"⚠️ 语言 '{user_lang}' 不在支持列表，默认使用 'Chinese'")
    print(f"   支持的语言: {', '.join(SUPPORTED_MAP.values())}")
    return 'Chinese'


def extract_audio(video_path: str, output_wav: str) -> None:
    """使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。"""
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ac', '1', '-ar', '16000', '-vn',
        output_wav, '-y'
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_audio_duration(wav_path: str) -> float:
    """获取音频时长（秒）。"""
    # 使用 path 参数以避免未来警告
    return librosa.get_duration(path=wav_path)


def format_time(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def time_ms_to_srt(ms: float) -> str:
    """将毫秒时间转换为 SRT 时间格式 (HH:MM:SS,mmm)。"""
    seconds = ms / 1000.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================================
# VAD 检测模块（自动启用）
# ============================================================================

def detect_speech_webrtc(
    audio_path: str,
    aggressiveness: int = 1,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400
) -> List[Tuple[float, float]]:
    """使用 webrtcvad 检测语音段。"""
    try:
        import webrtcvad
    except ImportError:
        raise ImportError("webrtcvad 未安装")

    with contextlib.closing(wave.open(audio_path, 'rb')) as wf:
        sample_rate = wf.getframerate()
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(f"不支持的采样率 {sample_rate}")
        if wf.getnchannels() != 1:
            raise ValueError("音频必须是单声道")
        pcm_data = wf.readframes(wf.getnframes())

    vad = webrtcvad.Vad(aggressiveness)
    frame_duration_ms = 30
    frame_bytes = int(sample_rate * frame_duration_ms / 1000) * 2

    speech_flags = []
    for i in range(0, len(pcm_data), frame_bytes):
        frame = pcm_data[i:i+frame_bytes]
        if len(frame) < frame_bytes:
            break
        try:
            is_speech = vad.is_speech(frame, sample_rate)
        except Exception:
            is_speech = False
        speech_flags.append(is_speech)

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


def detect_speech_energy(
    audio_path: str,
    threshold: float = 0.01,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400,
    frame_duration_ms: int = 30
) -> List[Tuple[float, float]]:
    """基于能量的 VAD（librosa）。"""
    y, sr = librosa.load(audio_path, sr=16000)
    frame_length = int(sr * frame_duration_ms / 1000)
    hop_length = frame_length
    energy = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    max_energy = np.max(energy)
    if max_energy < 1e-10:
        return []
    normalized = energy / max_energy
    speech_flags = normalized > threshold

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


def detect_speech(
    audio_path: str,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400
) -> List[Tuple[float, float]]:
    """
    自动 VAD 检测：优先使用 webrtc，若未安装则回退 energy。
    """
    try:
        return detect_speech_webrtc(
            audio_path,
            aggressiveness=1,
            min_speech_duration_ms=min_speech_duration_ms,
            min_silence_duration_ms=min_silence_duration_ms
        )
    except ImportError:
        print("⚠️ webrtcvad 未安装，使用能量法 VAD（效果稍差）")
        return detect_speech_energy(
            audio_path,
            threshold=0.01,
            min_speech_duration_ms=min_speech_duration_ms,
            min_silence_duration_ms=min_silence_duration_ms
        )


# ============================================================================
# 核心处理模块（ASR + 强制对齐）
# ============================================================================

def process_audio_segment(
    asr_model: Qwen3ASRModel,
    aligner_model: Qwen3ForcedAligner,
    audio_data: np.ndarray,
    sample_rate: int,
    language: str,
    offset_ms: float = 0.0
) -> Tuple[List[Tuple[str, float, float]], str]:
    """
    处理单个音频片段：ASR 识别 + 强制对齐，返回词时间戳和原始识别文本（含标点）。

    Args:
        asr_model: 已加载的 Qwen3ASRModel 实例
        aligner_model: 已加载的 Qwen3ForcedAligner 实例
        audio_data: 音频数据 (numpy array)
        sample_rate: 采样率 (必须为 16000)
        language: 语言全称 (如 'Chinese')
        offset_ms: 该片段在原始音频中的起始时间（毫秒）

    Returns:
        (word_timestamps, original_text)
        - word_timestamps: List[(word, start_ms, end_ms)]，时间戳为全局绝对毫秒时间。
        - original_text: ASR 返回的完整文本（包含标点）。
    """
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        seg_path = tmp.name
    try:
        sf.write(seg_path, audio_data, sample_rate)

        # ASR 识别
        asr_result = asr_model.transcribe(audio=seg_path, language=language)
        if not asr_result or not asr_result[0].text:
            return [], ""
        recognized_text = asr_result[0].text.strip()
        if not recognized_text:
            return [], ""

        # 强制对齐
        align_results = aligner_model.align(
            audio=seg_path,
            text=recognized_text,
            language=language
        )
        if not align_results or not align_results[0]:
            return [], recognized_text

        # 添加偏移
        word_timestamps = []
        for r in align_results[0]:
            start_ms = r.start_time * 1000.0 + offset_ms
            end_ms = r.end_time * 1000.0 + offset_ms
            word_timestamps.append((r.text, start_ms, end_ms))
        return word_timestamps, recognized_text

    finally:
        if os.path.exists(seg_path):
            os.remove(seg_path)


# ============================================================================
# 字幕生成模块（细粒度拆分，保留标点）
# ============================================================================

def split_text_by_punctuation(text: str, max_chars: int) -> List[str]:
    """
    将文本按标点拆分为多个片段，保证每个片段不超过 max_chars（Unicode 字符数）。
    拆分顺序：先按句号、问号、感叹号、分号；再按逗号、顿号、冒号；
    若仍超长，则强制按字符截断。
    注意：拆分时保留标点符号，使字幕更自然。
    """
    if len(text) <= max_chars:
        return [text]

    # 1. 按句子结束标点拆分
    sentence_parts = re.split(r'([。！？；.?!;])', text)
    merged = []
    for i in range(0, len(sentence_parts)-1, 2):
        merged.append(sentence_parts[i] + sentence_parts[i+1])
    if len(sentence_parts) % 2 == 1:
        merged.append(sentence_parts[-1])

    final_parts = []
    for seg in merged:
        if len(seg) <= max_chars:
            final_parts.append(seg)
        else:
            # 2. 按次要标点拆分（逗号、顿号、冒号）
            sub_parts = re.split(r'([，、：,;:])', seg)
            sub_merged = []
            for i in range(0, len(sub_parts)-1, 2):
                sub_merged.append(sub_parts[i] + sub_parts[i+1])
            if len(sub_parts) % 2 == 1:
                sub_merged.append(sub_parts[-1])

            for part in sub_merged:
                if len(part) <= max_chars:
                    final_parts.append(part)
                else:
                    # 3. 强制按字符截断
                    for j in range(0, len(part), max_chars):
                        final_parts.append(part[j:j+max_chars])

    # 清理空字符串
    final_parts = [p.strip() for p in final_parts if p.strip()]
    return final_parts


def group_tokens_by_punctuation(
    word_timestamps: List[Tuple[str, float, float]],
    raw_text: str,
    max_chars: int = 10
) -> List[Dict[str, Any]]:
    """
    根据标点和最大字符数将词分组为字幕条目。

    Args:
        word_timestamps: 词级时间戳列表 [(word, start_ms, end_ms), ...]
        raw_text: ASR 返回的原始文本（含标点）
        max_chars: 每段最大字符数（Unicode）

    Returns:
        List[Dict]，每个字典含 'text', 'start_ms', 'end_ms'
    """
    if not word_timestamps:
        return []

    token_texts = [t[0] for t in word_timestamps]
    token_joined = ''.join(token_texts)

    # 按句子结束标点拆分原始文本（保留标点）
    sentences = re.split(r'([。！？；.?!;])', raw_text)
    merged_sentences = []
    for i in range(0, len(sentences)-1, 2):
        merged_sentences.append(sentences[i] + sentences[i+1])
    if len(sentences) % 2 == 1:
        merged_sentences.append(sentences[-1])

    result = []
    current_pos = 0

    for sent in merged_sentences:
        # 去除标点和空白，得到纯文本用于匹配
        sent_clean = re.sub(r'[^\w\s\u4e00-\u9fff]', '', sent)
        sent_clean = re.sub(r'\s+', '', sent_clean)
        if not sent_clean:
            continue

        # 在 token_joined 中定位
        start_idx = token_joined.find(sent_clean, current_pos)
        if start_idx == -1:
            start_idx = token_joined.lower().find(sent_clean.lower(), current_pos)
            if start_idx == -1:
                print(f"⚠️ 无法定位句子: {sent_clean}")
                continue
        end_idx = start_idx + len(sent_clean)

        # 获取该句子的词索引范围
        token_start = token_end = None
        char_pos = 0
        for idx, token in enumerate(token_texts):
            token_len = len(token)
            if char_pos <= start_idx < char_pos + token_len:
                token_start = idx
            if char_pos <= end_idx <= char_pos + token_len:
                token_end = idx
                break
            char_pos += token_len

        if token_start is None or token_end is None:
            print(f"⚠️ 无法确定词范围: {sent_clean}")
            continue

        # 提取该句子的词时间戳子集
        sub_tokens = word_timestamps[token_start:token_end+1]
        # 该句子的纯文本（不含标点，用于后续拆分）
        sub_text = ''.join([t[0] for t in sub_tokens])

        # 进一步按标点和最大字符数拆分（保留原始标点）
        fragments = split_text_by_punctuation(sent, max_chars)

        # 为每个片段分配时间
        for frag in fragments:
            # 去除 frag 中的标点，得到纯文本
            frag_clean = re.sub(r'[^\w\s\u4e00-\u9fff]', '', frag)
            frag_clean = re.sub(r'\s+', '', frag_clean)
            if not frag_clean:
                continue

            # 在 sub_text 中定位
            frag_start = sub_text.find(frag_clean)
            if frag_start == -1:
                frag_start = sub_text.lower().find(frag_clean.lower())
                if frag_start == -1:
                    continue
            frag_end = frag_start + len(frag_clean)

            # 在 sub_tokens 中定位起始和结束词
            start_word_idx = None
            end_word_idx = None
            char_pos = 0
            for i, (word, _, _) in enumerate(sub_tokens):
                wlen = len(word)
                if char_pos <= frag_start < char_pos + wlen:
                    start_word_idx = i
                if char_pos <= frag_end <= char_pos + wlen:
                    end_word_idx = i
                    break
                char_pos += wlen
            if start_word_idx is None or end_word_idx is None:
                continue

            start_ms = sub_tokens[start_word_idx][1]
            end_ms = sub_tokens[end_word_idx][2]
            result.append({
                'text': frag,  # 保留原始标点
                'start_ms': start_ms,
                'end_ms': end_ms
            })

        current_pos = end_idx

    return result


def write_srt(subtitles: List[Dict[str, Any]], output_path: str) -> None:
    """将字幕列表写入 UTF‑8 编码的 SRT 文件。"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, sub in enumerate(subtitles, start=1):
            start_str = time_ms_to_srt(sub['start_ms'])
            end_str = time_ms_to_srt(sub['end_ms'])
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{sub['text']}\n\n")


# ============================================================================
# 主程序
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description='基于 Qwen3-ASR + 强制对齐的高精度视频字幕生成工具',
        epilog='示例: python qwen_asr_aligner_srt video.mp4'
    )
    parser.add_argument('video', help='输入视频文件路径')
    parser.add_argument('--asr_model', default=DEFAULT_ASR_MODEL,
                        help=f'Qwen3-ASR 模型路径（默认: {DEFAULT_ASR_MODEL}）')
    parser.add_argument('--aligner_model', default=DEFAULT_ALIGNER_MODEL,
                        help=f'强制对齐模型路径（默认: {DEFAULT_ALIGNER_MODEL}）')
    parser.add_argument('--language', default='zh', help='识别语言')
    parser.add_argument('--output', help='输出 SRT 文件路径')
    parser.add_argument('--max_chars', type=int, default=10,
                        help='每行字幕最大字符数（按 Unicode 字符计数），默认 10')
    parser.add_argument('--min_chars', type=int, default=2,
                        help='拆分后最短字符数（过短合并到前一段），默认 2')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='推理设备 (cuda/cpu)')
    parser.add_argument('--min_speech_duration_ms', type=int, default=300,
                        help='最短语音段（毫秒）')
    parser.add_argument('--min_silence_duration_ms', type=int, default=400,
                        help='最短静音间隔（毫秒）')

    args = parser.parse_args()

    # 检查输入
    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path):
        print(f"❌ 视频文件不存在: {video_path}")
        sys.exit(1)

    if args.output:
        srt_path = args.output
    else:
        srt_path = os.path.splitext(video_path)[0] + '.srt'

    language = normalize_language(args.language)
    print(f"🌐 识别语言: {language}")

    device = args.device
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_available() else torch.float32
    print(f"💻 使用设备: {device}")

    # 记录开始时间
    start_time = time.time()

    # 提取音频
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_wav = tmp.name

    try:
        print("🎬 提取音频...")
        extract_audio(video_path, audio_wav)
        print("✅ 音频提取完成")

        total_duration = get_audio_duration(audio_wav)
        print(f"⏱️ 音频总时长: {format_time(total_duration)}")

        # ---------- 加载模型 ----------
        print("🧠 加载 Qwen3-ASR 模型...")
        asr_model = Qwen3ASRModel.from_pretrained(
            args.asr_model,
            dtype=dtype,
            device_map=device
        )
        print("✅ ASR 模型加载完成")

        print("⏱️ 加载 Qwen3-ForcedAligner 模型...")
        aligner_model = Qwen3ForcedAligner.from_pretrained(
            args.aligner_model,
            dtype=dtype,
            device_map=device
        )
        print("✅ 强制对齐模型加载完成")

        # ---------- VAD 检测（自动） ----------
        print("🔍 检测语音段...")
        segments = detect_speech(
            audio_wav,
            min_speech_duration_ms=args.min_speech_duration_ms,
            min_silence_duration_ms=args.min_silence_duration_ms
        )

        if not segments:
            print("⚠️ 未检测到任何语音段，请检查音频或调整参数")
            return

        print(f"✅ 检测到 {len(segments)} 个语音段")

        # ---------- 逐段处理 ----------
        all_subtitles = []
        total_segments = len(segments)

        full_audio, sr = librosa.load(audio_wav, sr=16000)

        for idx, (start_sec, end_sec) in enumerate(segments, 1):
            print(f"\n🔹 处理第 {idx}/{total_segments} 段 ({start_sec:.2f}s - {end_sec:.2f}s)")

            start_sample = int(start_sec * sr)
            end_sample = int(end_sec * sr)
            if end_sample <= start_sample:
                continue
            segment_audio = full_audio[start_sample:end_sample]
            if len(segment_audio) < 0.1 * sr:
                continue

            offset_ms = start_sec * 1000.0
            word_ts, original_text = process_audio_segment(
                asr_model=asr_model,
                aligner_model=aligner_model,
                audio_data=segment_audio,
                sample_rate=sr,
                language=language,
                offset_ms=offset_ms
            )

            if not word_ts:
                print("   ⚠️ 该段无有效识别结果，跳过")
                continue

            # 分组生成字幕（使用原始含标点的文本）
            subs = group_tokens_by_punctuation(word_ts, original_text, max_chars=args.max_chars)
            all_subtitles.extend(subs)
            print(f"   ✅ 生成 {len(subs)} 条字幕")

        if not all_subtitles:
            print("❌ 所有段落均未生成有效字幕")
            return

        # ---------- 排序 ----------
        all_subtitles.sort(key=lambda x: x['start_ms'])

        # ---------- 写入 SRT ----------
        write_srt(all_subtitles, srt_path)
        print(f"\n✅ 字幕已保存至: {srt_path}")

        # ---------- 显示总时长和耗时 ----------
        elapsed = time.time() - start_time
        print(f"⏱️ 视频总时长: {format_time(total_duration)}")
        print(f"⏱️ 程序处理总耗时: {format_time(elapsed)}")

    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(audio_wav):
            os.remove(audio_wav)


if __name__ == '__main__':
    main()
