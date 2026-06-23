#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：基于 Qwen3-ASR + Qwen3-ForcedAligner 的高精度视频字幕生成工具
更新日期：2026-06-23
================================================================================

【项目描述】
-------------
本工具利用通义实验室开源的 Qwen3-ASR 语音识别模型和 Qwen3-ForcedAligner
强制对齐模型，从视频文件中提取语音，生成**词级时间戳精确到毫秒**的 SRT 字幕。
它通过 VAD（语音活动检测）自动切分音频，再对每个语音段分别进行 ASR 识别和
强制对齐，从而：
- 避免长音频对齐模型的长度限制（模型通常只支持 ≤30 秒的音频）；
- 提高短语音段的对齐精度（VAD 分割使得每段语音更纯净）；
- 支持任意时长的视频处理（理论上无长度上限）。

【核心优势】
-------------
1. **时间戳精准**：强制对齐技术预测每个字/词的起止时间，精度达毫秒级，字幕与口型高度同步。
2. **保留标点**：字幕文本完整保留原始标点符号（中英文逗号、句号等），更符合阅读习惯。
3. **智能拆分**：按标点（句号、逗号等）拆分长句，每行字幕不超过设定长度，确保阅读舒适。
4. **多语言支持**：支持中文、英文、粤语、日、韩、法、德等 10+ 种语言。
5. **内存优化**：流式 VAD 检测仅缓存有效语音段，静音部分不占用内存，支持超长视频。
6. **操作简单**：无需手动配置 VAD 参数，开箱即用，并带有进度条显示。

【依赖环境】
-------------
- Python 3.10+
- 系统工具：ffmpeg（必须在 PATH 中）
- Python 包（均需预装）：
  - numpy, librosa, soundfile, torch
  - qwen-asr (通义官方 ASR 库)
  - webrtcvad (WebRTC 语音活动检测)
  - tqdm (进度条)

在执行此脚本之前，请确保所有依赖已安装，并已下载 Qwen3-ASR 和 Qwen3-ForcedAligner 模型
至本地路径（或使用 Hugging Face 在线加载）。

【使用方法】
-------------
基本命令：
    python qwen_asr_aligner_srt.py <video_path> [选项]

【参数说明】
-------------
位置参数：
    video                   输入视频文件路径（必需）

可选参数：
    --asr_model             Qwen3-ASR 模型名称或路径，默认为此脚本目录下的 'Qwen/Qwen3-ASR-1.7B'
    --aligner_model         Qwen3-ForcedAligner 模型名称或路径，默认为此脚本目录下的 'Qwen/Qwen3-ForcedAligner-0.6B'
    --language              识别语言，支持 zh/en/yue/ja/ko/fr/de/es/pt/ru/it，默认 'zh'
    --output                输出 SRT 文件路径，默认与视频同名
    --max_chars             每行字幕最大字符数（按 Unicode 字符计数，中文英文均算1个），默认 10，必须 >= 1
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

# 更改 VAD 参数（例如更短的语音段）
python qwen_asr_aligner_srt.py video.mp4 --min_speech_duration_ms 200

【输出文件】
-------------
生成的 SRT 字幕文件与输入视频同名（扩展名为 .srt），或通过 --output 指定路径。
文件编码为 UTF-8，每一条字幕包含序号、时间轴和文本。

================================================================================
"""

import os
import sys
import re
import argparse
import subprocess
import tempfile
import time
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import librosa
import soundfile as sf
import torch
from tqdm import tqdm
import webrtcvad
from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner


# ============================================================================
# 全局常量定义
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASR_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ASR-1.7B")
DEFAULT_ALIGNER_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ForcedAligner-0.6B")

# 标点拆分正则：优先按句子结束标点拆分，再按次要标点拆分
SENTENCE_END_PUNCT = r'([。！？；.?!;])'
SECONDARY_PUNCT = r'([，、：,;:])'

# 音频处理固定采样率（所有模型均使用 16kHz）
SAMPLE_RATE = 16000


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
    # 若输入的是全称（如 'chinese'），则匹配并返回标准大小写
    for full_name in SUPPORTED_MAP.values():
        if full_name.lower() == user_lang:
            return full_name
    # 若输入的是代码，则映射
    if user_lang in SUPPORTED_MAP:
        return SUPPORTED_MAP[user_lang]
    # 默认回退
    print(f"⚠️ 语言 '{user_lang}' 不在支持列表，默认使用 'Chinese'")
    print(f"   支持的语言: {', '.join(SUPPORTED_MAP.values())}")
    return 'Chinese'


def check_ffmpeg() -> None:
    """
    检查 ffmpeg 是否可用，若不可用则打印错误并退出。
    """
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("❌ 未找到 ffmpeg，请先安装 ffmpeg 并确保其在 PATH 中。")
        sys.exit(1)


def extract_audio(video_path: str, output_wav: str) -> None:
    """
    使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。
    关键：'-ac 1' 强制将多声道下混为单声道，满足 VAD 和 ASR 模型的要求。

    Args:
        video_path: 输入视频文件路径。
        output_wav: 输出 WAV 文件路径。
    """
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ac', '1',                      # 强制单声道
        '-ar', str(SAMPLE_RATE),         # 强制 16kHz
        '-vn',                           # 不处理视频流
        output_wav, '-y'
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_audio_duration(wav_path: str) -> float:
    """
    获取音频时长（秒）。

    Args:
        wav_path: WAV 文件路径。

    Returns:
        音频时长（秒）。
    """
    return librosa.get_duration(path=wav_path)


def format_time(seconds: float) -> str:
    """
    将秒数格式化为 HH:MM:SS（仅用于日志输出）。

    Args:
        seconds: 秒数（浮点数）。

    Returns:
        格式化的时间字符串，如 "01:23:45"。
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def time_ms_to_srt(ms: float) -> str:
    """
    将毫秒时间转换为 SRT 时间格式 (HH:MM:SS,mmm)。

    Args:
        ms: 毫秒数（浮点数）。

    Returns:
        格式化的 SRT 时间戳字符串。
    """
    seconds = ms / 1000.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================================
# VAD 流式检测模块
# ============================================================================

def merge_speech_flags(
    speech_flags: List[bool],
    frame_duration_ms: int,
    min_speech_duration_ms: int,
    min_silence_duration_ms: int
) -> List[Tuple[int, int]]:
    """
    将语音标志序列合并为连续的语音段（帧索引形式）。

    该函数是 VAD 后处理的核心，它将每一帧的语音/非语音判断结果，
    根据最小语音时长和最小静音时长合并成若干个连续的语音段。

    Args:
        speech_flags: 每帧是否为语音的布尔列表。
        frame_duration_ms: 每帧的时长（毫秒）。
        min_speech_duration_ms: 最短语音段时长（毫秒），短于此值的语音段将被丢弃。
        min_silence_duration_ms: 最短静音段时长（毫秒），用于分割语音段。

    Returns:
        List[Tuple[int, int]]，每个元组为 (start_frame, end_frame) 帧索引（闭区间）。
    """
    min_silence_frames = int(min_silence_duration_ms / frame_duration_ms)
    min_speech_frames = int(min_speech_duration_ms / frame_duration_ms)
    segments = []
    i, n = 0, len(speech_flags)
    while i < n:
        # 跳过非语音帧
        while i < n and not speech_flags[i]:
            i += 1
        if i >= n:
            break
        start = i
        silence_count = 0
        # 寻找语音段的结束（连续静音帧达到阈值）
        while i < n:
            if speech_flags[i]:
                silence_count = 0
                i += 1
            else:
                silence_count += 1
                i += 1
                if silence_count >= min_silence_frames:
                    break
        end = i - silence_count  # 结束位置不包含静音帧
        if end - start >= min_speech_frames:
            segments.append((start, end))
    return segments


def detect_speech_streaming(
    audio_path: str,
    sample_rate: int = SAMPLE_RATE,
    aggressiveness: int = 1,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400,
    block_duration_sec: float = 0.5
) -> Tuple[List[Tuple[float, float]], List[np.ndarray]]:
    """
    流式读取音频，同时进行 VAD 检测，并缓存每个语音段的音频数据。

    这是内存优化的核心：音频文件只被读取一次，检测过程中只存储有效语音段，
    静音部分不占用内存。检测完成后，语音段数据已准备好供后续 ASR 处理。

    Args:
        audio_path: WAV 音频文件路径（必须为 16kHz 单声道）。
        sample_rate: 采样率（默认 16000）。
        aggressiveness: VAD 激进程度（0-3），默认 1。
        min_speech_duration_ms: 最短语音段（毫秒）。
        min_silence_duration_ms: 最短静音间隔（毫秒）。
        block_duration_sec: 每次读取的音频块长度（秒），影响流式处理粒度。

    Returns:
        Tuple[List[Tuple[float, float]], List[np.ndarray]]
        - segments: 每个语音段的 (start_sec, end_sec) 时间戳列表。
        - cached_audio: 与 segments 对应的音频数据（float32, [-1,1]）。
    """
    # 使用 soundfile 打开音频文件（支持大文件流式读取）
    with sf.SoundFile(audio_path, mode='r') as f:
        # 校验音频格式，确保与 VAD 兼容
        if f.samplerate != sample_rate:
            raise ValueError(f"采样率必须是 {sample_rate} Hz")
        if f.channels != 1:
            raise ValueError("音频必须是单声道")

        vad = webrtcvad.Vad(aggressiveness)
        frame_duration_ms = 30  # WebRTC VAD 固定帧长 30ms
        frame_bytes = int(sample_rate * frame_duration_ms / 1000) * 2  # 16-bit PCM
        block_frames = int(block_duration_sec * sample_rate)

        speech_flags = []

        # 分块读取音频，逐块转换为 int16 PCM 并逐帧判断
        for block in f.blocks(blocksize=block_frames, dtype='float32', fill_value=0):
            int16_block = (block * 32767).astype(np.int16)
            pcm_bytes = int16_block.tobytes()
            for i in range(0, len(pcm_bytes), frame_bytes):
                frame = pcm_bytes[i:i+frame_bytes]
                if len(frame) < frame_bytes:
                    break
                try:
                    is_speech = vad.is_speech(frame, sample_rate)
                except Exception:
                    is_speech = False
                speech_flags.append(is_speech)

        # 将帧标志合并为语音段（帧索引）
        seg_frames = merge_speech_flags(speech_flags, frame_duration_ms,
                                        min_speech_duration_ms, min_silence_duration_ms)

        if not seg_frames:
            return [], []

        # 再次打开文件，读取每个语音段的实际音频数据（缓存）
        with sf.SoundFile(audio_path, mode='r') as f2:
            segments = []
            cached_audio = []
            for start_frame, end_frame in seg_frames:
                start_sec = start_frame * frame_duration_ms / 1000.0
                end_sec = end_frame * frame_duration_ms / 1000.0
                f2.seek(int(start_sec * sample_rate))
                num_samples = int((end_sec - start_sec) * sample_rate)
                audio_data = f2.read(num_samples, dtype='float32', always_2d=False)
                # 防止文件尾部数据不足（理论上不会）
                if len(audio_data) < num_samples:
                    audio_data = np.pad(audio_data, (0, num_samples - len(audio_data)))
                segments.append((start_sec, end_sec))
                cached_audio.append(audio_data)
            return segments, cached_audio


def detect_speech(
    audio_path: str,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400
) -> Tuple[List[Tuple[float, float]], List[np.ndarray]]:
    """
    语音检测入口函数，直接调用流式 WebRTC VAD。

    Args:
        audio_path: WAV 音频文件路径。
        min_speech_duration_ms: 最短语音段（毫秒）。
        min_silence_duration_ms: 最短静音间隔（毫秒）。

    Returns:
        同 detect_speech_streaming 的返回值。
    """
    return detect_speech_streaming(
        audio_path,
        sample_rate=SAMPLE_RATE,
        aggressiveness=1,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=min_silence_duration_ms
    )


# ============================================================================
# 文本处理公共函数（用于字幕拆分和时间戳分配）
# ============================================================================

def split_sentences(text: str) -> List[str]:
    """
    将文本按句子结束标点拆分为带标点的完整句子。

    支持中文（。！？；）和英文（. ? ! ;）标点。

    Args:
        text: 原始文本（可能包含多种标点）。

    Returns:
        句子列表，每个句子末尾保留原标点。
    """
    parts = re.split(SENTENCE_END_PUNCT, text)
    sentences = []
    # 将标点与前面的内容合并
    for i in range(0, len(parts)-1, 2):
        sentences.append(parts[i] + parts[i+1])
    if len(parts) % 2 == 1:
        sentences.append(parts[-1])
    return [s.strip() for s in sentences if s.strip()]


def clean_text(text: str) -> str:
    """
    清理文本：移除所有标点符号，只保留字母、数字、中文和空格，并压缩多余空格。

    该函数用于生成纯文本版本，以便在词时间戳列表中进行定位匹配。

    Args:
        text: 原始文本（可能含标点）。

    Returns:
        清理后的纯文本（无标点，单词间保留单个空格）。
    """
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def find_token_range_by_clean(
    token_clean_list: List[str],
    target_clean: str,
    start_pos: int = 0
) -> Optional[Tuple[int, int]]:
    """
    在清理后的 token 拼接字符串中搜索 target_clean，返回其覆盖的 token 索引范围。

    该函数是字幕时间戳分配的核心：给定一个目标纯文本（如一个句子或片段），
    在已清理的词列表中查找它对应的起始和结束词的索引。

    Args:
        token_clean_list: 已清理的词列表（每个词已去除标点）。
        target_clean: 目标纯文本（已清理，可能包含空格）。
        start_pos: 搜索起始位置（字符偏移，用于后续句子的定位，本版未使用）。

    Returns:
        (token_start, token_end) 索引，若找不到则返回 None。
    """
    joined = ''.join(token_clean_list)  # 拼接成连续字符串（不含空格）
    target_no_space = target_clean.replace(' ', '')  # 去除空格以匹配
    pos = joined.find(target_no_space, start_pos)
    if pos == -1:
        # 忽略大小写再试一次
        pos = joined.lower().find(target_no_space.lower(), start_pos)
        if pos == -1:
            return None
    end_pos = pos + len(target_no_space)

    token_start = token_end = None
    char_pos = 0
    for i, token in enumerate(token_clean_list):
        token_len = len(token)
        if char_pos <= pos < char_pos + token_len:
            token_start = i
        if char_pos <= end_pos <= char_pos + token_len:
            token_end = i
            break
        char_pos += token_len
    if token_start is None or token_end is None:
        return None
    return token_start, token_end


# ============================================================================
# 核心处理模块：ASR 识别 + 强制对齐
# ============================================================================

def process_audio_segment(
    asr_model: Qwen3ASRModel,
    aligner_model: Qwen3ForcedAligner,
    audio_data: np.ndarray,
    sample_rate: int,
    language: str,
    temp_wav_path: str,
    offset_ms: float = 0.0
) -> Tuple[List[Tuple[str, float, float]], str]:
    """
    处理单个音频片段：ASR 识别 + 强制对齐，返回词时间戳和原始识别文本（含标点）。

    流程：
      1. 将内存中的 audio_data 写入临时 WAV 文件（模型接口要求文件路径）。
      2. 调用 ASR 模型获取带标点的识别文本。
      3. 调用强制对齐模型获取每个词的时间戳。
      4. 将时间戳加上全局偏移量（offset_ms）转换为绝对时间。

    Args:
        asr_model: 已加载的 Qwen3ASRModel 实例。
        aligner_model: 已加载的 Qwen3ForcedAligner 实例。
        audio_data: 音频数据 (numpy array, float32, [-1,1])。
        sample_rate: 采样率（必须与模型一致，即 16000）。
        language: 语言全称（如 'Chinese'）。
        temp_wav_path: 复用的临时 WAV 文件路径（覆盖写入）。
        offset_ms: 该片段在原始音频中的起始时间（毫秒），用于全局时间戳偏移。

    Returns:
        (word_timestamps, original_text)
        - word_timestamps: List[(word, start_ms, end_ms)]，时间戳为全局绝对毫秒时间。
        - original_text: ASR 返回的完整文本（包含标点）。
    """
    # 将音频数据写入临时文件（覆盖）
    sf.write(temp_wav_path, audio_data, sample_rate)

    # 1. ASR 识别
    asr_result = asr_model.transcribe(audio=temp_wav_path, language=language)
    if not asr_result or not asr_result[0].text:
        return [], ""
    recognized_text = asr_result[0].text.strip()
    if not recognized_text:
        return [], ""

    # 2. 强制对齐
    align_results = aligner_model.align(
        audio=temp_wav_path,
        text=recognized_text,
        language=language
    )
    if not align_results or not align_results[0]:
        # 若对齐失败，只返回文本，时间戳为空（调用方会跳过该段）
        return [], recognized_text

    # 3. 添加全局偏移
    word_timestamps = []
    for r in align_results[0]:
        start_ms = r.start_time * 1000.0 + offset_ms
        end_ms = r.end_time * 1000.0 + offset_ms
        word_timestamps.append((r.text, start_ms, end_ms))
    return word_timestamps, recognized_text


# ============================================================================
# 字幕生成模块：按标点和长度拆分，并分配时间戳
# ============================================================================

def split_text_by_punctuation(text: str, max_chars: int) -> List[str]:
    """
    将文本按标点拆分为多个片段，保证每个片段不超过 max_chars（Unicode 字符数）。

    拆分顺序（优先级从高到低）：
      1. 按句子结束标点（。！？；.?!;）拆分为句子。
      2. 若句子仍超长，按次要标点（，、：,;:）拆分。
      3. 若仍超长，则强制按字符截断。

    所有片段均保留原始标点，以保证字幕自然。

    Args:
        text: 待拆分的原始文本（可能包含多种标点）。
        max_chars: 每片段最大字符数。

    Returns:
        拆分后的片段列表（保留原始标点）。
    """
    if len(text) <= max_chars:
        return [text]

    # 1. 按句子结束标点拆分
    sentences = split_sentences(text)
    final_parts = []
    for sent in sentences:
        if len(sent) <= max_chars:
            final_parts.append(sent)
            continue
        # 2. 按次要标点拆分
        sub_parts = re.split(SECONDARY_PUNCT, sent)
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

    return [p.strip() for p in final_parts if p.strip()]


def group_tokens_by_punctuation(
    word_timestamps: List[Tuple[str, float, float]],
    raw_text: str,
    max_chars: int = 10
) -> List[Dict[str, Any]]:
    """
    根据标点和最大字符数将词分组为字幕条目，并为每个条目分配时间戳。

    这是整个脚本中最关键的字幕生成函数。它执行以下步骤：
      1. 将 raw_text 按句子结束标点分成句子。
      2. 对每个句子，在词时间戳列表中定位该句子的起始/结束词。
      3. 调用 split_text_by_punctuation 对该句子进行细粒度拆分。
      4. 为每个拆分出的片段，通过纯文本匹配在子词列表中定位其起止词，
         从而获得该片段的起始和结束时间戳。

    注意：所有匹配均基于清理后的纯文本（去除标点和空格），以避免标点干扰。

    Args:
        word_timestamps: 词级时间戳列表 [(word, start_ms, end_ms), ...]。
        raw_text: ASR 返回的原始文本（含标点）。
        max_chars: 每段最大字符数。

    Returns:
        List[Dict]，每个字典含 'text', 'start_ms', 'end_ms'。
    """
    if not word_timestamps:
        return []

    # 提取每个词的原始文本，并生成对应的清理版本（去除标点和多余空格）
    token_texts = [t[0] for t in word_timestamps]
    token_clean = [clean_text(t) for t in token_texts]

    # 将 raw_text 拆分为句子（保留标点）
    sentences = split_sentences(raw_text)
    result = []

    for sent in sentences:
        sent_clean = clean_text(sent)
        if not sent_clean:
            continue

        # 在清理后的 token 拼接中定位该句子的词索引范围
        range_idx = find_token_range_by_clean(token_clean, sent_clean, 0)
        if range_idx is None:
            print(f"⚠️ 无法定位句子: {sent_clean}")
            continue
        token_start, token_end = range_idx

        # 提取该句子对应的原始子词列表（带标点）和清理后的子词列表
        sub_tokens = word_timestamps[token_start:token_end+1]
        sub_token_clean = token_clean[token_start:token_end+1]
        sub_text_clean = ''.join(sub_token_clean)  # 清理后的拼接（无空格）

        # 对该句子进行细粒度拆分（按标点和长度）
        fragments = split_text_by_punctuation(sent, max_chars)

        for frag in fragments:
            frag_clean = clean_text(frag)
            if not frag_clean:
                continue
            # 在清理后的子句拼接中定位该片段
            frag_no_space = frag_clean.replace(' ', '')
            pos = sub_text_clean.find(frag_no_space)
            if pos == -1:
                pos = sub_text_clean.lower().find(frag_no_space.lower())
                if pos == -1:
                    continue
            end_pos = pos + len(frag_no_space)

            # 确定该片段在 sub_tokens 中的起始和结束词索引
            start_w = end_w = None
            char_pos = 0
            for i, token in enumerate(sub_token_clean):
                token_len = len(token)
                if char_pos <= pos < char_pos + token_len:
                    start_w = i
                if char_pos <= end_pos <= char_pos + token_len:
                    end_w = i
                    break
                char_pos += token_len
            if start_w is None or end_w is None:
                continue

            start_ms = sub_tokens[start_w][1]
            end_ms = sub_tokens[end_w][2]
            result.append({
                'text': frag,
                'start_ms': start_ms,
                'end_ms': end_ms
            })

    return result


def write_srt(subtitles: List[Dict[str, Any]], output_path: str) -> None:
    """
    将字幕列表写入 UTF‑8 编码的 SRT 文件。

    Args:
        subtitles: 字幕列表，每个元素包含 'text', 'start_ms', 'end_ms'。
        output_path: 输出 SRT 文件路径。
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, sub in enumerate(subtitles, start=1):
            start_str = time_ms_to_srt(sub['start_ms'])
            end_str = time_ms_to_srt(sub['end_ms'])
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{sub['text']}\n\n")


def fix_overlaps(subtitles: List[Dict[str, Any]]) -> None:
    """
    修正时间戳重叠：确保后一条字幕的开始时间不早于前一条的结束时间。

    由于 VAD 切段和对齐误差，可能出现相邻字幕时间重叠的情况。
    本函数通过微调前一条的结束时间来保证时间线严格递增。

    Args:
        subtitles: 字幕列表（已按 start_ms 排序）。
    """
    for i in range(1, len(subtitles)):
        prev = subtitles[i-1]
        curr = subtitles[i]
        if curr['start_ms'] < prev['end_ms']:
            # 将前一条的结束时间提前到当前开始时间之前 10ms
            prev['end_ms'] = curr['start_ms'] - 10
            # 防止结束时间早于开始时间
            if prev['end_ms'] < prev['start_ms']:
                prev['end_ms'] = prev['start_ms'] + 10


def check_model_path(path: str, name: str) -> None:
    """
    检查模型路径是否存在，若不存在则退出程序。

    Args:
        path: 模型路径。
        name: 模型名称（用于提示信息）。
    """
    if not os.path.exists(path):
        print(f"❌ {name} 路径不存在: {path}")
        sys.exit(1)


# ============================================================================
# 主程序入口
# ============================================================================

def main() -> None:
    """
    主程序入口：解析命令行参数，执行视频字幕生成全流程。
    """
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
                        help='每行字幕最大字符数，必须 >= 1，默认 10')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='推理设备 (cuda/cpu)')
    parser.add_argument('--min_speech_duration_ms', type=int, default=300,
                        help='最短语音段（毫秒）')
    parser.add_argument('--min_silence_duration_ms', type=int, default=400,
                        help='最短静音间隔（毫秒）')

    args = parser.parse_args()

    # ----- 参数校验 -----
    if args.max_chars < 1:
        print("❌ --max_chars 必须 >= 1")
        sys.exit(1)

    check_ffmpeg()

    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path):
        print(f"❌ 视频文件不存在: {video_path}")
        sys.exit(1)

    check_model_path(args.asr_model, "ASR 模型")
    check_model_path(args.aligner_model, "对齐模型")

    if args.output:
        srt_path = args.output
    else:
        srt_path = os.path.splitext(video_path)[0] + '.srt'

    language = normalize_language(args.language)
    print(f"🌐 识别语言: {language}")

    device = args.device
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_available() else torch.float32
    print(f"💻 使用设备: {device}")

    start_time = time.time()

    # ----- 创建临时文件 -----
    # audio_wav: ffmpeg 提取的原始音频（之后会被删除）
    # temp_seg_path: 用于 ASR/对齐的复用临时文件（每次覆盖写入）
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_wav = tmp.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp2:
        temp_seg_path = tmp2.name

    try:
        # 1. 提取音频
        print("🎬 提取音频...")
        extract_audio(video_path, audio_wav)
        print("✅ 音频提取完成")

        total_duration = get_audio_duration(audio_wav)
        print(f"⏱️ 音频总时长: {format_time(total_duration)}")

        # 2. 加载模型
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

        # 3. VAD 检测（流式，返回语音段和缓存音频）
        print("🔍 流式检测语音段...")
        segments, cached_audio = detect_speech(
            audio_wav,
            min_speech_duration_ms=args.min_speech_duration_ms,
            min_silence_duration_ms=args.min_silence_duration_ms
        )
        if not segments:
            print("⚠️ 未检测到任何语音段，请检查音频或调整参数")
            return
        print(f"✅ 检测到 {len(segments)} 个语音段，缓存语音数据总时长: {sum(end-start for start,end in segments):.2f}s")

        # 原始音频文件不再需要，删除以释放磁盘空间
        os.unlink(audio_wav)

        # 4. 逐段处理（ASR + 对齐 + 字幕生成）
        all_subtitles = []
        iterator = tqdm(zip(segments, cached_audio), total=len(segments),
                        desc="处理语音段", unit="段")

        for (start_sec, end_sec), segment_audio in iterator:
            # 跳过过短的音频段（可能为噪音）
            if len(segment_audio) < 0.1 * SAMPLE_RATE:
                continue

            offset_ms = start_sec * 1000.0
            word_ts, original_text = process_audio_segment(
                asr_model=asr_model,
                aligner_model=aligner_model,
                audio_data=segment_audio,
                sample_rate=SAMPLE_RATE,
                language=language,
                temp_wav_path=temp_seg_path,
                offset_ms=offset_ms
            )

            if not word_ts:
                iterator.set_postfix_str("跳过（无结果）")
                continue

            subs = group_tokens_by_punctuation(
                word_ts, original_text,
                max_chars=args.max_chars
            )
            all_subtitles.extend(subs)
            iterator.set_postfix_str(f"生成 {len(subs)} 条")

        if not all_subtitles:
            print("❌ 所有段落均未生成有效字幕")
            return

        # 5. 排序与时间轴修正
        all_subtitles.sort(key=lambda x: x['start_ms'])
        fix_overlaps(all_subtitles)

        # 6. 写入 SRT
        write_srt(all_subtitles, srt_path)
        print(f"\n✅ 字幕已保存至: {srt_path}")

        elapsed = time.time() - start_time
        print(f"⏱️ 视频总时长: {format_time(total_duration)}")
        print(f"⏱️ 程序处理总耗时: {format_time(elapsed)}")

    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理临时文件
        for f in [audio_wav, temp_seg_path]:
            if os.path.exists(f):
                os.unlink(f)


if __name__ == '__main__':
    main()
