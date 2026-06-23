#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：基于 Qwen3-ASR + Qwen3-ForcedAligner 的高精度视频字幕生成工具
更新日期：2026-06-23
================================================================================

【项目描述】
-------------------------------------------------------------------------------
本工具利用通义实验室开源的 Qwen3-ASR 语音识别模型和 Qwen3-ForcedAligner
强制对齐模型，从视频文件中提取语音，生成 **词级时间戳精确到毫秒** 的 SRT 字幕。

工作流程：
  1. 使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。
  2. 利用 WebRTC VAD 对音频进行语音活动检测，分割出独立的语音段。
  3. 对每个语音段依次执行：
       - ASR 识别（获取带标点的文本）
       - 强制对齐（获取每个词的时间戳）
  4. 将时间戳与文本按标点拆分、长度限制组合成字幕条目。
  5. 后处理：修正重叠、延长过短字幕至最小显示时长。
  6. 输出 UTF-8 编码的 SRT 字幕文件。

【核心优势】
-------------------------------------------------------------------------------
1. **时间戳精准**：强制对齐技术预测每个字/词的起止时间，精度达毫秒级，字幕与口型高度同步。
2. **内存优化**：采用“先 VAD 获时间戳，再逐段读取音频”的策略，内存峰值仅为单段音频大小（通常 < 1MB），支持任意时长视频。
3. **字幕可读性强**：按所有中英文标点拆分为最小子句，每行不超过设定字符数（默认 20），并智能延长过短字幕至 3 秒，避免闪屏。
4. **多语言支持**：支持中文、英文、粤语、日、韩、法、德等 10+ 种语言。
5. **进度反馈清晰**：进度条显示当前段序号/总段数、段长、实时生成字幕数。
6. **参数灵活**：可调节 VAD 灵敏度、最短语音/静音时长、最大字符数、最短显示时长等，适应不同场景。
7. **错误容忍**：单段 ASR 或对齐失败不会导致整体崩溃，程序继续处理后续段。

【依赖环境】
-------------------------------------------------------------------------------
- Python 3.10+
- 系统工具：ffmpeg（必须在 PATH 中）
- Python 包：
  - numpy, librosa, soundfile, torch
  - qwen-asr (通义官方 ASR 库)
  - webrtcvad (WebRTC 语音活动检测)
  - tqdm (进度条)
- 模型文件：需预先下载 Qwen3-ASR 和 Qwen3-ForcedAligner 模型至本地路径
  （默认脚本同级目录下的 Qwen/Qwen3-ASR-1.7B 和 Qwen/Qwen3-ForcedAligner-0.6B）

【使用方法】
-------------------------------------------------------------------------------
基本命令：
    python qwen_asr_aligner_srt.py <video_path> [选项]

【参数说明】
-------------------------------------------------------------------------------
位置参数：
    video_path               输入视频文件路径（必需）

可选参数：
    --asr_model PATH         Qwen3-ASR 模型路径（默认: ./Qwen/Qwen3-ASR-1.7B）
    --aligner_model PATH     Qwen3-ForcedAligner 模型路径（默认: ./Qwen/Qwen3-ForcedAligner-0.6B）
    --language STR           识别语言，支持 zh/en/yue/ja/ko/fr/de/es/pt/ru/it，默认 'zh'
    --output PATH            输出 SRT 文件路径（默认与视频同名）
    --max_chars INT          每行字幕最大 Unicode 字符数，默认 20，必须 >= 1
    --device STR             推理设备，'cuda' 或 'cpu'，默认自动检测
    --min_speech_duration_ms INT  最短语音段（毫秒），默认 300
    --min_silence_duration_ms INT 最短静音间隔（毫秒），默认 400
    --min_display_duration_ms INT 最短字幕显示时长（毫秒），默认 3000（3秒）
    --vad_aggressiveness INT VAD 激进程度（0~3），0最不激进（漏检少，误检多），
                             3最激进（漏检多，误检少），默认 0

【使用示例】
-------------------------------------------------------------------------------
# 基本用法（中文，每行最多 20 字符，VAD 最高灵敏度）
python qwen_asr_aligner_srt.py /path/to/video.mp4

# 指定英文，调整字幕长度和显示时长
python qwen_asr_aligner_srt.py video.mp4 --language en --max_chars 15 --min_display_duration_ms 2000

# 使用 CPU 推理（速度较慢）
python qwen_asr_aligner_srt.py video.mp4 --device cpu

# 调整 VAD 参数以适应嘈杂环境（降低灵敏度，减少误检）
python qwen_asr_aligner_srt.py video.mp4 --vad_aggressiveness 2 --min_speech_duration_ms 400

【输出文件】
-------------------------------------------------------------------------------
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
import logging
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import librosa
import soundfile as sf
import torch
from tqdm import tqdm
import webrtcvad
from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner


# ============================================================================
# 全局配置常量
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASR_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ASR-1.7B")
DEFAULT_ALIGNER_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ForcedAligner-0.6B")

SAMPLE_RATE = 16000                     # 所有模型均使用 16kHz
FRAME_DURATION_MS = 30                  # WebRTC VAD 固定帧长（30ms）
DEFAULT_VAD_AGGRESSIVENESS = 0          # 最高灵敏度，减少漏检
DEFAULT_MIN_DISPLAY_MS = 3000           # 默认字幕最短显示 3 秒

# 标点拆分正则（用于句子拆分）
SENTENCE_END_PUNCT = r'([。！？；.?!;])'

# 支持的语言映射（代码 → 模型全称）
SUPPORTED_LANGUAGES = {
    'zh': 'Chinese', 'en': 'English', 'yue': 'Cantonese',
    'fr': 'French', 'de': 'German', 'it': 'Italian',
    'ja': 'Japanese', 'ko': 'Korean', 'pt': 'Portuguese',
    'ru': 'Russian', 'es': 'Spanish'
}

# 日志配置（INFO 级别，仅输出关键信息）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 辅助函数
# ============================================================================

def normalize_language(user_lang: str) -> str:
    """
    标准化用户输入的语言代码或名称为模型支持的全称。

    Args:
        user_lang: 用户输入的语言标识（如 'zh', 'Chinese', 'en'）

    Returns:
        标准化后的语言全称（如 'Chinese'），若不支持则默认 'Chinese'。
    """
    user_lang = user_lang.strip().lower()
    # 检查是否已为全称（忽略大小写）
    for full_name in SUPPORTED_LANGUAGES.values():
        if full_name.lower() == user_lang:
            return full_name
    # 检查是否为代码
    if user_lang in SUPPORTED_LANGUAGES:
        return SUPPORTED_LANGUAGES[user_lang]
    logger.warning(f"语言 '{user_lang}' 不在支持列表，默认使用 'Chinese'")
    return 'Chinese'


def check_ffmpeg() -> None:
    """检查系统是否安装 ffmpeg 且可用，否则退出程序。"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.error("未找到 ffmpeg，请先安装 ffmpeg 并确保其在 PATH 中。")
        sys.exit(1)


def extract_audio(video_path: str, output_wav: str) -> None:
    """
    使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。

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
    获取 WAV 音频时长（秒）。

    Args:
        wav_path: WAV 文件路径。

    Returns:
        音频时长（秒）。
    """
    return librosa.get_duration(path=wav_path)


def format_time(seconds: float) -> str:
    """
    将秒数格式化为 HH:MM:SS（仅用于日志）。

    Args:
        seconds: 秒数。

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
        ms: 毫秒数。

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
# VAD 检测与音频读取
# ============================================================================

def merge_speech_flags(
    speech_flags: List[bool],
    frame_duration_ms: int,
    min_speech_duration_ms: int,
    min_silence_duration_ms: int
) -> List[Tuple[int, int]]:
    """
    将每帧的语音标志合并为连续的语音段（帧索引闭区间）。

    该函数根据最小语音时长和最小静音时长，将布尔标志序列转换为语音段列表。
    短于 min_speech_duration_ms 的语音段将被丢弃；静音长度达到 min_silence_duration_ms
    时视为段结束。

    Args:
        speech_flags: 每帧是否为语音的布尔列表。
        frame_duration_ms: 每帧时长（毫秒）。
        min_speech_duration_ms: 最短语音段时长（毫秒）。
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


def get_vad_segments(
    audio_path: str,
    sample_rate: int = SAMPLE_RATE,
    aggressiveness: int = DEFAULT_VAD_AGGRESSIVENESS,
    min_speech_duration_ms: int = 300,
    min_silence_duration_ms: int = 400,
    block_duration_sec: float = 0.5
) -> List[Tuple[float, float]]:
    """
    对音频执行 VAD 检测，返回所有语音段的时间戳列表（秒），不加载音频数据。

    该函数是内存优化的核心：它只读取一次音频，生成语音标志，然后合并为段，
    但只返回时间戳，音频数据由后续的 read_audio_segment 按需读取。

    Args:
        audio_path: WAV 音频文件路径（必须为 16kHz 单声道）。
        sample_rate: 采样率。
        aggressiveness: VAD 激进程度（0~3）。
        min_speech_duration_ms: 最短语音段（毫秒）。
        min_silence_duration_ms: 最短静音间隔（毫秒）。
        block_duration_sec: 每次读取的音频块长度（秒）。

    Returns:
        List[Tuple[float, float]]，每个元组为 (start_sec, end_sec)。
    """
    with sf.SoundFile(audio_path, mode='r') as f:
        if f.samplerate != sample_rate:
            raise ValueError(f"采样率必须为 {sample_rate} Hz")
        if f.channels != 1:
            raise ValueError("音频必须是单声道")

        vad = webrtcvad.Vad(aggressiveness)
        frame_duration_ms = FRAME_DURATION_MS
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

    # 合并帧标志为语音段（帧索引）
    seg_frames = merge_speech_flags(
        speech_flags, frame_duration_ms,
        min_speech_duration_ms, min_silence_duration_ms
    )
    # 转换为秒
    segments = []
    for start_frame, end_frame in seg_frames:
        start_sec = start_frame * frame_duration_ms / 1000.0
        end_sec = end_frame * frame_duration_ms / 1000.0
        segments.append((start_sec, end_sec))
    return segments


def read_audio_segment(audio_path: str, start_sec: float, end_sec: float) -> np.ndarray:
    """
    从音频文件中读取指定时间段的音频数据。

    Args:
        audio_path: WAV 文件路径。
        start_sec: 起始时间（秒）。
        end_sec: 结束时间（秒）。

    Returns:
        numpy 数组，float32，[-1,1] 范围。
    """
    with sf.SoundFile(audio_path, mode='r') as f:
        f.seek(int(start_sec * f.samplerate))
        num_samples = int((end_sec - start_sec) * f.samplerate)
        audio_data = f.read(num_samples, dtype='float32', always_2d=False)
        # 若读取数据不足，补零（理论上不应发生）
        if len(audio_data) < num_samples:
            audio_data = np.pad(audio_data, (0, num_samples - len(audio_data)))
        return audio_data


# ============================================================================
# 文本处理与字幕生成（核心拆分逻辑）
# ============================================================================

def split_sentences(text: str) -> List[str]:
    """
    按句子结束标点（。！？；.?!;）将文本拆分为带标点的完整句子。

    Args:
        text: 原始文本。

    Returns:
        句子列表，每个句子末尾保留原标点。
    """
    parts = re.split(SENTENCE_END_PUNCT, text)
    sentences = []
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

    该函数是时间戳分配的核心：给定一个目标纯文本（如一个句子或片段），
    在已清理的词列表中查找它对应的起始和结束词的索引。

    Args:
        token_clean_list: 已清理的词列表（每个词已去除标点）。
        target_clean: 目标纯文本（已清理，可能包含空格）。
        start_pos: 搜索起始字符位置（本版未使用，保留）。

    Returns:
        (token_start, token_end) 索引，若找不到则返回 None。
    """
    joined = ''.join(token_clean_list)  # 拼接成连续字符串（不含空格）
    target_no_space = target_clean.replace(' ', '')
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


def split_text_by_punctuation(text: str, max_chars: int) -> List[str]:
    """
    递归拆分文本为最小子句，确保每个子句长度 ≤ max_chars。

    拆分策略：
      1. 先按所有中英文标点拆分成最小子句（每个子句内部不含标点）。
      2. 对仍超过 max_chars 的子句，按字符强行截断（递归拆分）。
    返回拆分后的片段列表，每段末尾保留原标点（如果有）。

    Args:
        text: 待拆分的文本。
        max_chars: 每片段最大字符数（Unicode）。

    Returns:
        拆分后的片段列表。
    """
    # 定义所有中英文标点（可根据需要扩展）
    punct_pattern = r'([。！？；，、：.?!;,:])'
    parts = re.split(punct_pattern, text)
    # 将文本和标点合并为“文本+标点”的子句
    clauses = []
    for i in range(0, len(parts)-1, 2):
        clause = parts[i] + parts[i+1]
        if clause.strip():
            clauses.append(clause)
    if len(parts) % 2 == 1:
        last = parts[-1]
        if last.strip():
            clauses.append(last)

    # 对每个子句，若长度超标，则按字符截断
    result = []
    for clause in clauses:
        if len(clause) <= max_chars:
            result.append(clause)
        else:
            # 强制按字符切分
            for j in range(0, len(clause), max_chars):
                result.append(clause[j:j+max_chars])
    return [c.strip() for c in result if c.strip()]


def group_tokens_by_punctuation(
    word_timestamps: List[Tuple[str, float, float]],
    raw_text: str,
    max_chars: int = 20
) -> List[Dict[str, Any]]:
    """
    将词级时间戳分组为字幕条目，每个条目包含文本、起止时间。

    处理流程：
      1. 将 raw_text 按句子结束标点拆分为句子。
      2. 对每个句子，在词时间戳列表中定位该句子的起始/结束词。
      3. 调用 split_text_by_punctuation 对该句子进行细粒度拆分（确保每段 ≤ max_chars）。
      4. 为每个拆分出的片段，通过纯文本匹配在子词列表中定位其起止词，
         从而获得该片段的起始和结束时间戳。

    若字符串匹配失败，则跳过该句子（记录警告）。

    Args:
        word_timestamps: 词级时间戳列表 [(word, start_ms, end_ms), ...]。
        raw_text: ASR 返回的原始文本（含标点）。
        max_chars: 每段最大字符数。

    Returns:
        List[Dict]，每个字典含 'text', 'start_ms', 'end_ms'。
    """
    if not word_timestamps:
        return []

    token_texts = [t[0] for t in word_timestamps]
    token_clean = [clean_text(t) for t in token_texts]
    sentences = split_sentences(raw_text)
    result = []

    for sent in sentences:
        sent_clean = clean_text(sent)
        if not sent_clean:
            continue

        # 在全局 token 中定位该句子
        range_idx = find_token_range_by_clean(token_clean, sent_clean, 0)
        if range_idx is None:
            logger.warning(f"字符串匹配失败，跳过句子: {sent_clean[:30]}...")
            continue

        token_start, token_end = range_idx
        sub_tokens = word_timestamps[token_start:token_end+1]
        sub_token_clean = token_clean[token_start:token_end+1]
        sub_text_clean = ''.join(sub_token_clean)

        # 拆分为最小子句
        fragments = split_text_by_punctuation(sent, max_chars)

        for frag in fragments:
            frag_clean = clean_text(frag)
            if not frag_clean:
                continue

            # 在子句拼接中定位片段
            frag_no_space = frag_clean.replace(' ', '')
            pos = sub_text_clean.find(frag_no_space)
            if pos == -1:
                pos = sub_text_clean.lower().find(frag_no_space.lower())
                if pos == -1:
                    # 匹配失败则跳过该片段（可考虑更宽松的回退策略）
                    continue
            end_pos = pos + len(frag_no_space)

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


def postprocess_subtitles(
    subtitles: List[Dict[str, Any]],
    min_display_duration_ms: int = DEFAULT_MIN_DISPLAY_MS,
    audio_duration_sec: float = None
) -> None:
    """
    后处理字幕列表：修正重叠 + 延长过短字幕至最小显示时长。

    处理逻辑：
      1. 修正重叠：若后一条开始时间早于前一条结束时间，则将前一条结束时间
         提前到后一条开始前 10ms。
      2. 延长过短字幕：若某条字幕持续时间 < min_display_duration_ms，则尝试
         将结束时间延长到 start + min_display_duration_ms，但若与下一条字幕
         重叠，则压缩到下一条开始前 10ms（尽可能延后）。

    Args:
        subtitles: 字幕列表（已按 start_ms 排序）。
        min_display_duration_ms: 最短显示时长（毫秒）。
        audio_duration_sec: 音频总时长（秒），用于限制最后一条字幕的延长。
    """
    if not subtitles:
        return

    # 1. 修正重叠
    for i in range(1, len(subtitles)):
        prev = subtitles[i-1]
        curr = subtitles[i]
        if curr['start_ms'] < prev['end_ms']:
            prev['end_ms'] = curr['start_ms'] - 10
            # 防止结束时间早于开始时间
            if prev['end_ms'] < prev['start_ms']:
                prev['end_ms'] = prev['start_ms'] + 10

    # 2. 延长过短字幕
    min_display_ms = min_display_duration_ms
    for i, sub in enumerate(subtitles):
        duration = sub['end_ms'] - sub['start_ms']
        if duration < min_display_ms:
            new_end = sub['start_ms'] + min_display_ms
            # 检查下一条字幕
            if i + 1 < len(subtitles):
                next_start = subtitles[i+1]['start_ms']
                if new_end > next_start - 10:
                    new_end = next_start - 10
            else:
                # 最后一条字幕，不能超过音频总时长
                if audio_duration_sec is not None:
                    max_end = audio_duration_sec * 1000
                    if new_end > max_end:
                        new_end = max_end
            # 只有延长后的结束时间更大才更新
            if new_end > sub['end_ms']:
                sub['end_ms'] = new_end


# ============================================================================
# 核心处理模块：ASR + 强制对齐
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
    处理单个音频片段：ASR 识别 + 强制对齐，返回词时间戳和原始识别文本。

    流程：
      1. 将内存中的 audio_data 写入临时 WAV 文件（模型接口要求文件路径）。
      2. 调用 ASR 模型获取带标点的识别文本。
      3. 调用强制对齐模型获取每个词的时间戳。
      4. 将时间戳加上全局偏移量（offset_ms）转换为绝对时间。

    Args:
        asr_model: 已加载的 Qwen3ASRModel 实例。
        aligner_model: 已加载的 Qwen3ForcedAligner 实例。
        audio_data: 音频数据 (numpy array, float32, [-1,1])。
        sample_rate: 采样率。
        language: 语言全称（如 'Chinese'）。
        temp_wav_path: 复用的临时 WAV 文件路径（覆盖写入）。
        offset_ms: 该片段在原始音频中的起始时间（毫秒），用于全局偏移。

    Returns:
        (word_timestamps, original_text)
        - word_timestamps: List[(word, start_ms, end_ms)]，全局绝对毫秒时间。
        - original_text: ASR 返回的完整文本（包含标点）。
    """
    # 将音频数据写入临时文件（覆盖）
    sf.write(temp_wav_path, audio_data, sample_rate)

    try:
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
            # 若对齐失败，返回空时间戳，但保留文本（调用方会跳过）
            return [], recognized_text

        # 3. 添加全局偏移
        word_timestamps = []
        for r in align_results[0]:
            start_ms = r.start_time * 1000.0 + offset_ms
            end_ms = r.end_time * 1000.0 + offset_ms
            word_timestamps.append((r.text, start_ms, end_ms))
        return word_timestamps, recognized_text

    except Exception as e:
        logger.error(f"处理音频段时出错: {e}")
        return [], ""


# ============================================================================
# 主程序
# ============================================================================

def main() -> None:
    """主程序入口：解析命令行参数，执行视频字幕生成全流程。"""
    parser = argparse.ArgumentParser(
        description='基于 Qwen3-ASR + 强制对齐的高精度视频字幕生成工具 (v4.5)'
    )
    parser.add_argument('video', help='输入视频文件路径')
    parser.add_argument('--asr_model', default=DEFAULT_ASR_MODEL,
                        help=f'Qwen3-ASR 模型路径（默认: {DEFAULT_ASR_MODEL}）')
    parser.add_argument('--aligner_model', default=DEFAULT_ALIGNER_MODEL,
                        help=f'强制对齐模型路径（默认: {DEFAULT_ALIGNER_MODEL}）')
    parser.add_argument('--language', default='zh', help='识别语言')
    parser.add_argument('--output', help='输出 SRT 文件路径')
    parser.add_argument('--max_chars', type=int, default=20,
                        help='每行字幕最大字符数（Unicode），默认 20')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='推理设备 (cuda/cpu)')
    parser.add_argument('--min_speech_duration_ms', type=int, default=300,
                        help='最短语音段（毫秒）')
    parser.add_argument('--min_silence_duration_ms', type=int, default=400,
                        help='最短静音间隔（毫秒）')
    parser.add_argument('--min_display_duration_ms', type=int, default=DEFAULT_MIN_DISPLAY_MS,
                        help=f'最短字幕显示时长（毫秒），默认 {DEFAULT_MIN_DISPLAY_MS}ms（3秒）')
    parser.add_argument('--vad_aggressiveness', type=int, choices=[0, 1, 2, 3],
                        default=DEFAULT_VAD_AGGRESSIVENESS,
                        help=f'VAD 激进程度 (0~3)，0最不激进（漏检少，误检多），'
                             f'3最激进（漏检多，误检少），默认 {DEFAULT_VAD_AGGRESSIVENESS}')

    args = parser.parse_args()

    # 参数校验
    if args.max_chars < 1:
        logger.error("--max_chars 必须 >= 1")
        sys.exit(1)

    check_ffmpeg()

    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path):
        logger.error(f"视频文件不存在: {video_path}")
        sys.exit(1)

    if not os.path.exists(args.asr_model):
        logger.error(f"ASR 模型路径不存在: {args.asr_model}")
        sys.exit(1)
    if not os.path.exists(args.aligner_model):
        logger.error(f"对齐模型路径不存在: {args.aligner_model}")
        sys.exit(1)

    srt_path = args.output or os.path.splitext(video_path)[0] + '.srt'
    language = normalize_language(args.language)
    logger.info(f"识别语言: {language}")

    device = args.device
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_available() else torch.float32
    logger.info(f"使用设备: {device}")

    start_time = time.time()

    # 创建临时文件
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_wav = tmp.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp2:
        temp_seg_path = tmp2.name

    try:
        # 1. 提取音频
        logger.info("提取音频...")
        extract_audio(video_path, audio_wav)
        total_duration = get_audio_duration(audio_wav)
        logger.info(f"音频总时长: {format_time(total_duration)}")

        # 2. 加载模型
        logger.info("加载 Qwen3-ASR 模型...")
        asr_model = Qwen3ASRModel.from_pretrained(
            args.asr_model,
            dtype=dtype,
            device_map=device
        )
        logger.info("加载 Qwen3-ForcedAligner 模型...")
        aligner_model = Qwen3ForcedAligner.from_pretrained(
            args.aligner_model,
            dtype=dtype,
            device_map=device
        )
        logger.info("模型加载完成")

        # 3. VAD 检测（仅获取时间戳列表）
        logger.info("检测语音段...")
        segments = get_vad_segments(
            audio_wav,
            aggressiveness=args.vad_aggressiveness,
            min_speech_duration_ms=args.min_speech_duration_ms,
            min_silence_duration_ms=args.min_silence_duration_ms
        )
        total_segments = len(segments)
        if total_segments == 0:
            logger.warning("未检测到任何语音段")
            return
        logger.info(f"检测到 {total_segments} 个语音段")

        # 4. 逐段处理（ASR + 对齐 + 字幕分组）
        all_subtitles = []
        with tqdm(total=total_segments, unit='段', desc="处理进度", ncols=90) as pbar:
            for idx, (start_sec, end_sec) in enumerate(segments, 1):
                seg_duration = end_sec - start_sec
                # 读取当前段音频数据（内存中只保留这一段）
                segment_audio = read_audio_segment(audio_wav, start_sec, end_sec)
                # 跳过过短段（可能为噪音）
                if len(segment_audio) < 0.1 * SAMPLE_RATE:
                    pbar.update(1)
                    pbar.set_postfix(
                        段号=f"{idx}/{total_segments}",
                        段长=f"{seg_duration:.2f}s",
                        字幕=len(all_subtitles),
                        状态="跳过"
                    )
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

                if word_ts:
                    # 将词时间戳分组为字幕条目
                    subs = group_tokens_by_punctuation(
                        word_ts, original_text,
                        max_chars=args.max_chars
                    )
                    all_subtitles.extend(subs)
                    pbar.set_postfix(
                        段号=f"{idx}/{total_segments}",
                        段长=f"{seg_duration:.2f}s",
                        字幕=len(all_subtitles)
                    )
                else:
                    pbar.set_postfix(
                        段号=f"{idx}/{total_segments}",
                        段长=f"{seg_duration:.2f}s",
                        字幕=len(all_subtitles),
                        状态="无结果"
                    )

                pbar.update(1)

        if not all_subtitles:
            logger.error("未生成任何有效字幕")
            return

        # 5. 排序与后处理
        all_subtitles.sort(key=lambda x: x['start_ms'])
        postprocess_subtitles(
            all_subtitles,
            min_display_duration_ms=args.min_display_duration_ms,
            audio_duration_sec=total_duration
        )

        # 6. 写入 SRT
        write_srt(all_subtitles, srt_path)

        elapsed = time.time() - start_time
        logger.info(f"✅ 字幕已保存至: {srt_path}")
        logger.info(f"视频总时长: {format_time(total_duration)}")
        logger.info(f"程序处理总耗时: {format_time(elapsed)}")
        logger.info(f"共处理 {total_segments} 个语音段，生成 {len(all_subtitles)} 条字幕")

    except Exception as e:
        logger.error(f"发生错误: {e}", exc_info=True)
    finally:
        # 清理临时文件
        for f in [audio_wav, temp_seg_path]:
            if os.path.exists(f):
                os.unlink(f)


if __name__ == '__main__':
    main()
