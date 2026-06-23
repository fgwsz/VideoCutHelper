#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：基于 Qwen3-ASR + Qwen3-ForcedAligner 的高精度视频字幕生成工具
更新日期：2026-06-24
================================================================================

【项目描述】
-------------------------------------------------------------------------------
本工具利用通义实验室开源的 Qwen3-ASR 语音识别模型和 Qwen3-ForcedAligner
强制对齐模型，从视频文件中提取语音，生成 **词级时间戳精确到毫秒** 的 SRT 字幕。

工作流程：
  1. 使用 ffmpeg 从视频中提取 16kHz 单声道 WAV 音频。
  2. 利用 WebRTC VAD 对整个音频进行语音活动检测，生成语音段和静音段的完整覆盖。
  3. 对每个音频段（包括静音段）依次执行：
       - ASR 识别（获取带标点的文本）
       - 强制对齐（获取每个词的时间戳）
  4. 将时间戳与文本按标点拆分、长度限制组合成字幕条目。
  5. 后处理：修正重叠、延长过短字幕至最小显示时长。
  6. 输出 UTF-8 编码的 SRT 字幕文件。

【核心优势】
-------------------------------------------------------------------------------
1. **全音频覆盖**：不仅处理 VAD 检测出的语音段，还强制处理所有静音段，彻底解决
   因 VAD 漏检导致的字幕缺失问题，确保末尾及中间任何潜在人声都被转录。
2. **时间戳精准**：强制对齐技术预测每个字/词的起止时间，精度达毫秒级，字幕与口型高度同步。
3. **内存优化**：采用“先 VAD 获时间戳，再逐段读取音频”的策略，内存峰值仅为单段音频大小，
   支持任意时长视频。
4. **字幕可读性强**：按所有中英文标点拆分为最小子句，每行不超过设定字符数（默认 20），
   并智能延长过短字幕至 3 秒，避免闪屏。
5. **多语言支持**：支持中文、英文、粤语、日、韩、法、德等 10+ 种语言。
6. **进度反馈清晰**：进度条显示百分比、已用/剩余时间、当前段号/总数、片段起止时间、
   已生成字幕数，处理状态一目了然。
7. **参数灵活**：可调节 VAD 灵敏度、最短语音/静音时长、最大字符数、最短显示时长等，
   适应不同场景。
8. **错误容忍**：单段 ASR 或对齐失败不会导致整体崩溃，程序继续处理后续段。

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
- 自动化安装脚本
    # 模型下载
    ./download_qwen_asr.sh
    # 依赖库安装
    ./install_qwen_asr.sh

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
    --min_speech_duration_ms INT  最短语音段（毫秒），默认 150
    --min_silence_duration_ms INT 最短静音间隔（毫秒），默认 200
    --min_display_duration_ms INT 最短字幕显示时长（毫秒），默认 3000（3秒）
    --vad_aggressiveness INT VAD 激进程度（0~3），0最不激进（漏检少，误检多），
                             3最激进（漏检多，误检少），默认 0
    --min_silence_segment_sec FLOAT 静音段最小处理时长（秒），短于此值的静音段将被跳过，
                                  默认 0.5

【使用示例】
-------------------------------------------------------------------------------
# 基本用法（中文，每行最多 20 字符，VAD 最高灵敏度）
python qwen_asr_aligner_srt.py /path/to/video.mp4

# 指定英文，调整字幕长度和显示时长
python qwen_asr_aligner_srt.py video.mp4 --language en --max_chars 15 --min_display_duration_ms 2000

# 使用 CPU 推理（速度较慢，但可避免 CUDA 驱动警告）
python qwen_asr_aligner_srt.py video.mp4 --device cpu

# 调整 VAD 参数以适应嘈杂环境（降低灵敏度，减少误检）
python qwen_asr_aligner_srt.py video.mp4 --vad_aggressiveness 2 --min_speech_duration_ms 400

【输出文件】
-------------------------------------------------------------------------------
生成的 SRT 字幕文件与输入视频同名（扩展名为 .srt），或通过 --output 指定路径。
文件编码为 UTF-8，每一条字幕包含序号、时间轴和文本。

【版本历史】
-------------------------------------------------------------------------------
- v6.6 (2026-06-24)：最终稳定版，添加完整项目文档和函数注释，使用 warnings 过滤 CUDA 警告。
- v6.5 (2026-06-24)：强制替换 torch.cuda.is_available 以彻底消除 CUDA 驱动警告。
- v6.4 (2026-06-23)：使用 CUDA_VISIBLE_DEVICES="-1" 屏蔽 GPU。
- v6.3 (2026-06-23)：修复进度条信息显示，屏蔽 pad_token_id 警告。
- v6.0 (2026-06-23)：重构为全音频覆盖模式（语音+静音段全部处理）。
- v5.0 (2026-06-23)：增加高灵敏度 VAD 默认参数和尾部强制补录。
- v4.0 (2026-06-23)：重写拆分逻辑，实现递归拆分为最小子句。

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

# ===== 第一步：屏蔽 CUDA 驱动警告（在导入 torch 之前） =====
# 使用 warnings 过滤器精确捕获 UserWarning 并忽略，避免干扰命令行
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="torch.cuda")

# ===== 第二步：解析 --device cpu 参数，设置环境变量禁用 GPU =====
_use_cpu = False
if "--device" in sys.argv:
    idx = sys.argv.index("--device")
    if idx + 1 < len(sys.argv) and sys.argv[idx+1].lower() == "cpu":
        _use_cpu = True
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # 彻底禁用所有 GPU 设备

# ===== 第三步：导入 torch 并强制覆盖 CUDA 检测函数 =====
import torch

if _use_cpu:
    # 强制返回 False，使后续代码认为 CUDA 不可用
    torch.cuda.is_available = lambda: False
    torch.cuda.device_count = lambda: 0

# ===== 第四步：导入其他依赖库 =====
import numpy as np
import librosa
import soundfile as sf
from tqdm import tqdm
import webrtcvad

# ===== 屏蔽 transformers 库的 pad_token_id 警告 =====
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
import transformers
transformers.logging.set_verbosity_error()

from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner


# ============================================================================
# 全局配置常量
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASR_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ASR-1.7B")
DEFAULT_ALIGNER_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-ForcedAligner-0.6B")

SAMPLE_RATE = 16000                     # 所有模型均使用 16kHz
FRAME_DURATION_MS = 30                  # WebRTC VAD 固定帧长，不可更改
MIN_ALLOWED_MS = 30                     # 用户设定的 VAD 参数下限（至少一帧）
DEFAULT_VAD_AGGRESSIVENESS = 0          # 最灵敏，漏检最少
DEFAULT_MIN_SPEECH_MS = 150             # 默认最短语音段 150ms（原 300）
DEFAULT_MIN_SILENCE_MS = 200            # 默认最短静音间隔 200ms（原 400）
DEFAULT_MIN_DISPLAY_MS = 3000           # 字幕最短显示 3 秒
DEFAULT_MIN_SILENCE_SEGMENT_SEC = 0.5   # 静音段最小处理时长（秒），避免碎片过多

# 句子结束标点（用于分句）
SENTENCE_END_PUNCT = r'([。！？；.?!;])'

# 语言代码到模型全称的映射
SUPPORTED_LANGUAGES = {
    'zh': 'Chinese', 'en': 'English', 'yue': 'Cantonese',
    'fr': 'French', 'de': 'German', 'it': 'Italian',
    'ja': 'Japanese', 'ko': 'Korean', 'pt': 'Portuguese',
    'ru': 'Russian', 'es': 'Spanish'
}

# 日志配置（INFO 级别，关键信息可见）
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
    将用户输入的语言代码或名称标准化为模型可识别的全称。

    Args:
        user_lang: 用户输入，如 'zh', 'en', 'Chinese', 'English' 等。

    Returns:
        标准化后的语言全称，如 'Chinese'，若不支持则返回 'Chinese'。
    """
    user_lang = user_lang.strip().lower()
    # 尝试匹配全称（忽略大小写）
    for full_name in SUPPORTED_LANGUAGES.values():
        if full_name.lower() == user_lang:
            return full_name
    # 尝试匹配代码
    if user_lang in SUPPORTED_LANGUAGES:
        return SUPPORTED_LANGUAGES[user_lang]
    # 未知语言回退
    logger.warning(f"语言 '{user_lang}' 不在支持列表，默认使用 'Chinese'")
    return 'Chinese'


def check_ffmpeg() -> None:
    """检查 ffmpeg 是否安装且可用，若不存在则退出程序。"""
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
        output_wav: 输出音频文件路径。
    """
    # -ac 1 强制单声道，-ar 16000 重采样，-vn 跳过视频流
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ac', '1',
        '-ar', str(SAMPLE_RATE),
        '-vn',
        output_wav, '-y'
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_audio_duration(wav_path: str) -> float:
    """获取 WAV 音频的时长（秒）。"""
    return librosa.get_duration(path=wav_path)


def format_time(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS 用于日志输出。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def time_ms_to_srt(ms: float) -> str:
    """
    将毫秒时间转换为 SRT 标准时间戳格式。

    Args:
        ms: 毫秒（浮点数）。

    Returns:
        形如 "00:01:23,456" 的字符串。
    """
    seconds = ms / 1000.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================================
# VAD 检测与段生成
# ============================================================================

def detect_speech_flags(
    audio_path: str,
    sample_rate: int = SAMPLE_RATE,
    aggressiveness: int = DEFAULT_VAD_AGGRESSIVENESS,
    block_duration_sec: float = 0.5
) -> List[bool]:
    """
    对音频进行 VAD 检测，返回每帧（30ms）的语音标志。

    Args:
        audio_path: 16kHz 单声道 WAV 文件路径。
        sample_rate: 采样率。
        aggressiveness: VAD 激进程度（0~3）。
        block_duration_sec: 内部读取块大小（秒）。

    Returns:
        bool 列表，True 表示该帧为语音。
    """
    with sf.SoundFile(audio_path, mode='r') as f:
        # 校验音频格式
        if f.samplerate != sample_rate:
            raise ValueError(f"采样率必须为 {sample_rate} Hz")
        if f.channels != 1:
            raise ValueError("音频必须是单声道")

        vad = webrtcvad.Vad(aggressiveness)
        frame_duration_ms = FRAME_DURATION_MS
        frame_bytes = int(sample_rate * frame_duration_ms / 1000) * 2  # 16-bit PCM 字节数
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
    return speech_flags


def merge_flags_to_segments(
    speech_flags: List[bool],
    frame_duration_ms: int,
    min_speech_duration_ms: int,
    min_silence_duration_ms: int,
    is_speech: bool
) -> List[Tuple[int, int]]:
    """
    将标志列表合并为指定类型（语音或静音）的段（帧索引闭区间）。

    Args:
        speech_flags: 每帧的语音标志（True 为语音）。
        frame_duration_ms: 每帧时长（毫秒）。
        min_speech_duration_ms: 最短语音段阈值（用于语音段）。
        min_silence_duration_ms: 最短静音段阈值（用于静音段）。
        is_speech: True 表示提取语音段，False 表示提取静音段。

    Returns:
        段列表，每个段为 (start_frame, end_frame) 闭区间。
    """
    # 根据类型选择对应的最小帧数阈值
    min_duration_ms = min_speech_duration_ms if is_speech else min_silence_duration_ms
    min_frames = int(min_duration_ms / frame_duration_ms)
    segments = []
    i, n = 0, len(speech_flags)
    while i < n:
        # 寻找目标标志的起始
        while i < n and speech_flags[i] != is_speech:
            i += 1
        if i >= n:
            break
        start = i
        # 寻找结束（标志翻转）
        while i < n and speech_flags[i] == is_speech:
            i += 1
        end = i - 1  # 闭区间
        # 只保留长度大于阈值的段
        if end - start + 1 >= min_frames:
            segments.append((start, end))
    return segments


def read_audio_segment(audio_path: str, start_sec: float, end_sec: float) -> np.ndarray:
    """
    从 WAV 文件中读取指定时间段的音频数据。

    Args:
        audio_path: 音频文件路径。
        start_sec: 起始时间（秒）。
        end_sec: 结束时间（秒）。

    Returns:
        float32 数组，范围 [-1, 1]。
    """
    with sf.SoundFile(audio_path, mode='r') as f:
        f.seek(int(start_sec * f.samplerate))
        num_samples = int((end_sec - start_sec) * f.samplerate)
        audio_data = f.read(num_samples, dtype='float32', always_2d=False)
        # 若读取数据不足，补零（通常不会发生）
        if len(audio_data) < num_samples:
            audio_data = np.pad(audio_data, (0, num_samples - len(audio_data)))
        return audio_data


def get_all_segments(
    audio_path: str,
    sample_rate: int = SAMPLE_RATE,
    aggressiveness: int = DEFAULT_VAD_AGGRESSIVENESS,
    min_speech_duration_ms: int = DEFAULT_MIN_SPEECH_MS,
    min_silence_duration_ms: int = DEFAULT_MIN_SILENCE_MS,
    min_silence_segment_sec: float = DEFAULT_MIN_SILENCE_SEGMENT_SEC,
    block_duration_sec: float = 0.5
) -> List[Dict[str, Any]]:
    """
    获取所有需要处理的音频段（包括语音段和静音段），覆盖整个音频。

    本函数是“全音频覆盖”策略的核心：
      1. 先对音频进行 VAD 检测，得到每帧的语音/静音标志。
      2. 分别提取语音段和静音段（帧索引）。
      3. 转换为时间（秒）并合并为一个列表，按起始时间排序。
      4. 合并相邻或重叠的段，并补全开头和结尾的静音段。
      5. 返回包含所有段的字典列表，每个字典有 start_sec, end_sec, is_speech。

    Args:
        audio_path: 音频文件路径。
        sample_rate: 采样率。
        aggressiveness: VAD 激进程度。
        min_speech_duration_ms: 最短语音段（毫秒）。
        min_silence_duration_ms: 最短静音间隔（用于 VAD 分割，也作为静音段的最小长度）。
        min_silence_segment_sec: 静音段最小处理时长（秒），短于此值的静音段将被丢弃。
        block_duration_sec: 内部读取块大小。

    Returns:
        段列表，每个元素为 {'start_sec': float, 'end_sec': float, 'is_speech': bool}。
    """
    # 1. 获取语音标志
    speech_flags = detect_speech_flags(audio_path, sample_rate, aggressiveness, block_duration_sec)
    frame_duration_ms = FRAME_DURATION_MS

    # 2. 提取语音段和静音段（帧索引）
    speech_seg_frames = merge_flags_to_segments(
        speech_flags, frame_duration_ms,
        min_speech_duration_ms, min_silence_duration_ms,
        is_speech=True
    )
    silence_seg_frames = merge_flags_to_segments(
        speech_flags, frame_duration_ms,
        min_speech_duration_ms, min_silence_duration_ms,
        is_speech=False
    )

    # 3. 转换为秒并加入类型标记
    all_segments = []

    for start_frame, end_frame in speech_seg_frames:
        start_sec = start_frame * frame_duration_ms / 1000.0
        end_sec = (end_frame + 1) * frame_duration_ms / 1000.0  # 闭区间转开区间
        all_segments.append({'start_sec': start_sec, 'end_sec': end_sec, 'is_speech': True})

    min_silence_sec = min_silence_segment_sec
    for start_frame, end_frame in silence_seg_frames:
        start_sec = start_frame * frame_duration_ms / 1000.0
        end_sec = (end_frame + 1) * frame_duration_ms / 1000.0
        if end_sec - start_sec >= min_silence_sec:
            all_segments.append({'start_sec': start_sec, 'end_sec': end_sec, 'is_speech': False})

    # 4. 按起始时间排序
    all_segments.sort(key=lambda x: x['start_sec'])

    # 5. 合并重叠或相邻段，并补全开头和结尾
    merged = []
    for seg in all_segments:
        if not merged:
            merged.append(seg)
        else:
            last = merged[-1]
            # 若当前段起始 <= 上一段结束（允许微小重叠），则合并
            if seg['start_sec'] <= last['end_sec'] + 0.01:
                last['end_sec'] = max(last['end_sec'], seg['end_sec'])
                last['is_speech'] = last['is_speech'] or seg['is_speech']  # 有语音则标记为语音
            else:
                # 若中间有间隙，补一个静音段
                if seg['start_sec'] > last['end_sec'] + 0.01:
                    gap = {
                        'start_sec': last['end_sec'],
                        'end_sec': seg['start_sec'],
                        'is_speech': False
                    }
                    if gap['end_sec'] - gap['start_sec'] >= min_silence_sec:
                        merged.append(gap)
                merged.append(seg)

    # 6. 补全开头静音
    if merged:
        if merged[0]['start_sec'] > 0.0:
            first = merged[0]
            gap = {
                'start_sec': 0.0,
                'end_sec': first['start_sec'],
                'is_speech': False
            }
            if gap['end_sec'] - gap['start_sec'] >= min_silence_sec:
                merged.insert(0, gap)

        # 7. 补全结尾静音
        total_duration = get_audio_duration(audio_path)
        if merged[-1]['end_sec'] < total_duration:
            last = merged[-1]
            gap = {
                'start_sec': last['end_sec'],
                'end_sec': total_duration,
                'is_speech': False
            }
            if gap['end_sec'] - gap['start_sec'] >= min_silence_sec:
                merged.append(gap)

    return merged


# ============================================================================
# 文本处理与字幕生成
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
    移除文本中的标点符号，只保留字母、数字、中文和空格，并压缩多余空格。

    该函数用于生成纯文本版本，便于在时间戳列表中进行字符串匹配。

    Args:
        text: 可能含标点的原始文本。

    Returns:
        清理后的纯文本。
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
    在清理后的词列表中搜索目标纯文本，返回词索引范围。

    实现细节：将所有词清理后拼接成连续字符串，用 find 定位目标，
    然后反推每个词在拼接串中的边界，得到词索引。

    Args:
        token_clean_list: 清理后的词列表（每个词已无标点）。
        target_clean: 目标纯文本（可能含空格，但匹配时会忽略）。
        start_pos: 搜索起始字符位置（本版未使用）。

    Returns:
        (start_token_idx, end_token_idx)，若找不到则返回 None。
    """
    joined = ''.join(token_clean_list)         # 词间无空格拼接
    target_no_space = target_clean.replace(' ', '')
    pos = joined.find(target_no_space, start_pos)
    if pos == -1:
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
    将文本拆分为最小子句，确保每段长度 ≤ max_chars。

    策略：
        1. 按所有中英文标点（。！？；，、：.?!;,:）拆分成最小子句（内部无标点）。
        2. 若子句仍超长，按字符等分截断。

    Args:
        text: 待拆分的文本。
        max_chars: 每段最大 Unicode 字符数。

    Returns:
        拆分后的片段列表，每段末尾保留原标点。
    """
    # 匹配所有常见中英文标点
    punct_pattern = r'([。！？；，、：.?!;,:])'
    parts = re.split(punct_pattern, text)
    clauses = []
    # 合并文本和标点形成子句
    for i in range(0, len(parts)-1, 2):
        clause = parts[i] + parts[i+1]
        if clause.strip():
            clauses.append(clause)
    if len(parts) % 2 == 1:
        last = parts[-1]
        if last.strip():
            clauses.append(last)

    result = []
    for clause in clauses:
        if len(clause) <= max_chars:
            result.append(clause)
        else:
            # 按字符强制截断
            for j in range(0, len(clause), max_chars):
                result.append(clause[j:j+max_chars])
    return [c.strip() for c in result if c.strip()]


def group_tokens_by_punctuation(
    word_timestamps: List[Tuple[str, float, float]],
    raw_text: str,
    max_chars: int = 20
) -> List[Dict[str, Any]]:
    """
    将词级时间戳分组为字幕条目。

    流程：
        1. 按句子结束标点拆分 raw_text。
        2. 对每个句子，在词时间戳中定位其起止词索引。
        3. 对句子进行细粒度拆分（split_text_by_punctuation）。
        4. 对每个片段，通过清理后的文本匹配确定其起止词，获得时间戳。

    Args:
        word_timestamps: 词时间戳列表 [(word, start_ms, end_ms), ...]。
        raw_text: ASR 返回的原始文本（含标点）。
        max_chars: 每段最大字符数。

    Returns:
        字幕列表，每项为 {'text': str, 'start_ms': float, 'end_ms': float}。
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

        # 在整体词列表中定位该句子
        range_idx = find_token_range_by_clean(token_clean, sent_clean, 0)
        if range_idx is None:
            logger.warning(f"字符串匹配失败，跳过句子: {sent_clean[:30]}...")
            continue

        token_start, token_end = range_idx
        sub_tokens = word_timestamps[token_start:token_end+1]
        sub_token_clean = token_clean[token_start:token_end+1]
        sub_text_clean = ''.join(sub_token_clean)

        # 拆分句子为片段
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
                    continue
            end_pos = pos + len(frag_no_space)

            # 确定片段对应的词索引
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
    将字幕列表写入 UTF-8 编码的 SRT 文件。

    Args:
        subtitles: 字幕列表，每项含 'text', 'start_ms', 'end_ms'。
        output_path: 输出文件路径。
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
    后处理：修正时间重叠，并延长过短字幕至最小显示时长。

    修正重叠：若后一条开始时间早于前一条结束，则前一条结束时间提前到后一条开始-10ms。
    延长过短：若字幕持续时间 < min_display_duration_ms，尝试延长到目标时长，
            但不得超过下一条开始-10ms，最后一条不得超过音频总时长。

    Args:
        subtitles: 字幕列表（会就地修改）。
        min_display_duration_ms: 最短显示时长（毫秒）。
        audio_duration_sec: 音频总时长（秒），用于限制最后一条。
    """
    if not subtitles:
        return

    # 修正重叠
    for i in range(1, len(subtitles)):
        prev = subtitles[i-1]
        curr = subtitles[i]
        if curr['start_ms'] < prev['end_ms']:
            prev['end_ms'] = curr['start_ms'] - 10
            if prev['end_ms'] < prev['start_ms']:
                prev['end_ms'] = prev['start_ms'] + 10

    # 延长过短字幕
    min_display_ms = min_display_duration_ms
    for i, sub in enumerate(subtitles):
        duration = sub['end_ms'] - sub['start_ms']
        if duration < min_display_ms:
            new_end = sub['start_ms'] + min_display_ms
            if i + 1 < len(subtitles):
                next_start = subtitles[i+1]['start_ms']
                if new_end > next_start - 10:
                    new_end = next_start - 10
            else:
                if audio_duration_sec is not None:
                    max_end = audio_duration_sec * 1000
                    if new_end > max_end:
                        new_end = max_end
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
    处理单个音频片段：ASR 识别 + 强制对齐，返回词时间戳和识别文本。

    由于模型接口需要文件路径，先将 audio_data 写入临时 WAV 文件。
    然后调用 ASR 和强制对齐，最后将时间戳加上全局偏移。

    Args:
        asr_model: Qwen3ASRModel 实例。
        aligner_model: Qwen3ForcedAligner 实例。
        audio_data: 音频数据（float32）。
        sample_rate: 采样率（必须 16000）。
        language: 语言全称。
        temp_wav_path: 临时 WAV 文件路径（复用）。
        offset_ms: 该段在原始音频中的起始偏移（毫秒）。

    Returns:
        (word_timestamps, recognized_text)
        word_timestamps: [(word, start_ms, end_ms), ...] 全局时间。
        recognized_text: ASR 返回的原始文本（含标点）。
    """
    # 写入临时文件（覆盖）
    sf.write(temp_wav_path, audio_data, sample_rate)

    try:
        # ASR 识别
        asr_result = asr_model.transcribe(audio=temp_wav_path, language=language)
        if not asr_result or not asr_result[0].text:
            return [], ""
        recognized_text = asr_result[0].text.strip()
        if not recognized_text:
            return [], ""

        # 强制对齐
        align_results = aligner_model.align(
            audio=temp_wav_path,
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

    except Exception as e:
        logger.error(f"处理音频段时出错: {e}")
        return [], ""


# ============================================================================
# 主程序
# ============================================================================

def main() -> None:
    """主程序入口：解析参数，执行完整字幕生成流程。"""
    parser = argparse.ArgumentParser(
        description='基于 Qwen3-ASR + 强制对齐的高精度视频字幕生成工具 (v6.6)'
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
    parser.add_argument('--min_speech_duration_ms', type=int, default=DEFAULT_MIN_SPEECH_MS,
                        help=f'最短语音段（毫秒），默认 {DEFAULT_MIN_SPEECH_MS}（最小 30）')
    parser.add_argument('--min_silence_duration_ms', type=int, default=DEFAULT_MIN_SILENCE_MS,
                        help=f'最短静音间隔（毫秒），默认 {DEFAULT_MIN_SILENCE_MS}（最小 30）')
    parser.add_argument('--min_display_duration_ms', type=int, default=DEFAULT_MIN_DISPLAY_MS,
                        help=f'最短字幕显示时长（毫秒），默认 {DEFAULT_MIN_DISPLAY_MS}ms（3秒）')
    parser.add_argument('--vad_aggressiveness', type=int, choices=[0, 1, 2, 3],
                        default=DEFAULT_VAD_AGGRESSIVENESS,
                        help=f'VAD 激进程度 (0~3)，0最不激进（漏检少，误检多），'
                             f'3最激进（漏检多，误检少），默认 {DEFAULT_VAD_AGGRESSIVENESS}')
    parser.add_argument('--min_silence_segment_sec', type=float, default=DEFAULT_MIN_SILENCE_SEGMENT_SEC,
                        help=f'静音段最小处理时长（秒），短于此值的静音段将被跳过，默认 {DEFAULT_MIN_SILENCE_SEGMENT_SEC}s')

    args = parser.parse_args()

    # 如果用户指定了 CPU，确保覆盖（已在外层设置，但再次确保）
    if args.device == 'cpu':
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        torch.cuda.is_available = lambda: False
        torch.cuda.device_count = lambda: 0

    # 参数合法性校验
    if args.max_chars < 1:
        logger.error("--max_chars 必须 >= 1")
        sys.exit(1)

    if args.min_speech_duration_ms < MIN_ALLOWED_MS:
        logger.warning(f"min_speech_duration_ms 不能小于 {MIN_ALLOWED_MS}ms，已自动调整为 {MIN_ALLOWED_MS}ms")
        args.min_speech_duration_ms = MIN_ALLOWED_MS
    if args.min_silence_duration_ms < MIN_ALLOWED_MS:
        logger.warning(f"min_silence_duration_ms 不能小于 {MIN_ALLOWED_MS}ms，已自动调整为 {MIN_ALLOWED_MS}ms")
        args.min_silence_duration_ms = MIN_ALLOWED_MS

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
    if device == 'cuda' and not torch.cuda.is_available():
        logger.warning("CUDA 不可用，自动切换至 CPU")
        device = 'cpu'
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_available() else torch.float32
    logger.info(f"使用设备: {device}")

    start_time = time.time()

    # 创建临时文件
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_wav = tmp.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp2:
        temp_seg_path = tmp2.name

    try:
        # ---- 1. 提取音频 ----
        logger.info("提取音频...")
        extract_audio(video_path, audio_wav)
        total_duration = get_audio_duration(audio_wav)
        logger.info(f"音频总时长: {format_time(total_duration)}")

        # ---- 2. 加载模型 ----
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

        # ---- 消除 pad_token_id 警告 ----
        for model in [asr_model, aligner_model]:
            try:
                eos_token_id = None
                if hasattr(model, 'tokenizer') and hasattr(model.tokenizer, 'eos_token_id'):
                    eos_token_id = model.tokenizer.eos_token_id
                elif hasattr(model, 'processor') and hasattr(model.processor, 'tokenizer') and hasattr(model.processor.tokenizer, 'eos_token_id'):
                    eos_token_id = model.processor.tokenizer.eos_token_id
                elif hasattr(model, 'model') and hasattr(model.model, 'config') and hasattr(model.model.config, 'eos_token_id'):
                    eos_token_id = model.model.config.eos_token_id
                elif hasattr(model, 'config') and hasattr(model.config, 'eos_token_id'):
                    eos_token_id = model.config.eos_token_id

                if eos_token_id is not None:
                    if hasattr(model, 'generation_config'):
                        model.generation_config.pad_token_id = eos_token_id
                    if hasattr(model, 'model') and hasattr(model.model, 'generation_config'):
                        model.model.generation_config.pad_token_id = eos_token_id
                    if hasattr(model, 'config'):
                        model.config.pad_token_id = eos_token_id
            except Exception:
                pass  # 忽略设置失败，不影响主流程

        # ---- 3. 生成所有音频段（语音+静音） ----
        logger.info("检测音频段（包含语音和静音）...")
        all_segments = get_all_segments(
            audio_wav,
            aggressiveness=args.vad_aggressiveness,
            min_speech_duration_ms=args.min_speech_duration_ms,
            min_silence_duration_ms=args.min_silence_duration_ms,
            min_silence_segment_sec=args.min_silence_segment_sec
        )
        total_segments = len(all_segments)
        if total_segments == 0:
            logger.warning("未生成任何音频段")
            return

        speech_count = sum(1 for s in all_segments if s['is_speech'])
        silence_count = total_segments - speech_count
        logger.info(f"共生成 {total_segments} 个音频段（语音段: {speech_count}，静音段: {silence_count}）")

        # ---- 4. 逐段处理（ASR + 对齐 + 分组） ----
        all_subtitles = []
        last_n = 0.0

        # 进度条：基于总时长（秒），显示百分比、已用/剩余时间
        with tqdm(total=total_duration, unit='s', desc="处理进度") as pbar:
            for idx, seg in enumerate(all_segments, 1):
                start_sec = seg['start_sec']
                end_sec = seg['end_sec']

                # 读取该段音频数据
                segment_audio = read_audio_segment(audio_wav, start_sec, end_sec)
                if len(segment_audio) < 0.1 * SAMPLE_RATE:
                    pbar.update(end_sec - last_n)
                    last_n = end_sec
                    pbar.set_postfix(
                        段=f"{idx}/{total_segments}",
                        时间=f"{start_sec:.1f}-{end_sec:.1f}s",
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
                    subs = group_tokens_by_punctuation(
                        word_ts, original_text,
                        max_chars=args.max_chars
                    )
                    all_subtitles.extend(subs)
                    pbar.update(end_sec - last_n)
                    last_n = end_sec
                    pbar.set_postfix(
                        段=f"{idx}/{total_segments}",
                        时间=f"{start_sec:.1f}-{end_sec:.1f}s",
                        字幕=len(all_subtitles)
                    )
                else:
                    pbar.update(end_sec - last_n)
                    last_n = end_sec
                    pbar.set_postfix(
                        段=f"{idx}/{total_segments}",
                        时间=f"{start_sec:.1f}-{end_sec:.1f}s",
                        字幕=len(all_subtitles),
                        状态="无结果"
                    )

        if not all_subtitles:
            logger.error("未生成任何有效字幕")
            return

        # ---- 5. 排序与后处理 ----
        all_subtitles.sort(key=lambda x: x['start_ms'])
        postprocess_subtitles(
            all_subtitles,
            min_display_duration_ms=args.min_display_duration_ms,
            audio_duration_sec=total_duration
        )

        # ---- 6. 写入 SRT ----
        write_srt(all_subtitles, srt_path)

        elapsed = time.time() - start_time
        logger.info(f"✅ 字幕已保存至: {srt_path}")
        logger.info(f"视频总时长: {format_time(total_duration)}")
        logger.info(f"程序处理总耗时: {format_time(elapsed)}")
        logger.info(f"共处理 {total_segments} 个音频段，生成 {len(all_subtitles)} 条字幕")

    except Exception as e:
        logger.error(f"发生错误: {e}", exc_info=True)
    finally:
        # 清理临时文件
        for f in [audio_wav, temp_seg_path]:
            if os.path.exists(f):
                os.unlink(f)


if __name__ == '__main__':
    main()
