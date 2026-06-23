#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：基于 SRT 字幕文件批量生成 TTS 音频
版本号：   1.0
作者：     通义实验室社区
更新日期： 2026-06-21
================================================================================

【功能描述】
-------------
读取 SRT 字幕文件，利用 Qwen3-TTS Voice Design 模型将文本合成为语音。
支持两种模式：
  - single  ：将所有字幕文本合并为一个音频文件（可插入静音间隔）。
  - separate：每条字幕单独生成一个 WAV 文件。

【依赖环境】
-------------
- Python 3.10+
- 包：qwen-tts, torch, soundfile, librosa（用于拼接音频）

【使用方法】
-------------
基本命令：
    python generate_audio_from_srt.py <srt_file> [选项]

【参数说明】
-------------
位置参数：
    srt_file                 输入 SRT 文件路径

可选参数：
    --mode MODE              模式：single 或 separate（默认 single）
    --language LANGUAGE      合成语言，默认 Chinese
    --instruct INSTRUCT      语音风格指令
    --model_path PATH        模型路径，默认脚本目录下的 Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
    --output_dir DIR         输出目录，默认当前目录
    --output_prefix PREFIX   输出文件名前缀（single模式）或文件前缀（separate模式），默认 'output'
    --silence SECONDS        single模式下句子间插入的静音秒数，默认 0.0
    --max_chars_per_segment  单次合成最大字符数（超长则拆分），默认 200
    --device DEVICE          设备（cuda/cpu），默认自动检测
    --dtype DTYPE            数据类型（float32/bfloat16），默认 float32

【使用示例】
-------------
# 合并所有字幕到一个音频
python generate_audio_from_srt.py subtitles.srt --mode single --instruct "温柔女声"

# 每条字幕单独生成音频
python generate_audio_from_srt.py subtitles.srt --mode separate --instruct "播音腔" --output_dir ./audio

# 合并时在句子间插入 0.5 秒静音
python generate_audio_from_srt.py subtitles.srt --mode single --silence 0.5
================================================================================
"""

import os
import sys
import re
import argparse
import time
from typing import List, Tuple, Optional

import torch
import soundfile as sf
import numpy as np
import librosa

# 导入 qwen_tts
try:
    from qwen_tts import Qwen3TTSModel
except ImportError as e:
    print(f"❌ qwen_tts 未正确安装: {e}")
    print("请运行: pip install qwen-tts")
    sys.exit(1)

# ============================================================================
# 获取脚本所在目录，构建默认模型路径
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TTS_MODEL = os.path.join(SCRIPT_DIR, "Qwen", "Qwen3-TTS-12Hz-1.7B-VoiceDesign")


# ============================================================================
# SRT 解析
# ============================================================================
def parse_srt(file_path: str) -> List[Tuple[float, float, str]]:
    """
    解析 SRT 文件，返回 (start_sec, end_sec, text) 列表。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

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
        subtitles.append((time_to_seconds(start_str), time_to_seconds(end_str), text))
    return subtitles


def time_to_seconds(time_str: str) -> float:
    """将 SRT 时间格式 (HH:MM:SS,mmm) 转换为秒（浮点数）。"""
    h, m, s = time_str.split(':')
    s, ms = s.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


# ============================================================================
# 音频拼接工具
# ============================================================================
def concatenate_wavs(wav_list: List[np.ndarray], sr: int, silence_sec: float = 0.0) -> np.ndarray:
    """
    将多个音频数组按顺序拼接，可插入静音。
    """
    if not wav_list:
        raise ValueError("wav_list 为空")
    # 静音样本数
    silence_samples = int(sr * silence_sec) if silence_sec > 0 else 0
    silence = np.zeros(silence_samples, dtype=np.float32) if silence_samples > 0 else None

    # 拼接
    segments = []
    for i, wav in enumerate(wav_list):
        if i > 0 and silence is not None:
            segments.append(silence)
        segments.append(wav)
    return np.concatenate(segments)


def split_text_for_tts(text: str, max_chars: int) -> List[str]:
    """
    将长文本按句子或字符切分成多个片段，每个片段不超过 max_chars。
    优先按句号、问号、感叹号切分，再按逗号等，最后强制截断。
    """
    if len(text) <= max_chars:
        return [text]

    # 按句子切分
    sentences = re.split(r'([。！？；])', text)
    merged = []
    for i in range(0, len(sentences)-1, 2):
        merged.append(sentences[i] + sentences[i+1])
    if len(sentences) % 2 == 1:
        merged.append(sentences[-1])

    parts = []
    current = ""
    for sent in merged:
        if len(current) + len(sent) <= max_chars:
            current += sent
        else:
            if current:
                parts.append(current.strip())
            # 如果句子本身超长，强制按字符截断
            if len(sent) > max_chars:
                for j in range(0, len(sent), max_chars):
                    parts.append(sent[j:j+max_chars].strip())
                current = ""
            else:
                current = sent
    if current:
        parts.append(current.strip())
    return parts


# ============================================================================
# 主程序
# ============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description='从 SRT 字幕文件生成 TTS 音频（支持合并或单句输出）',
        epilog='示例: python generate_audio_from_srt.py subs.srt --mode single --instruct "温柔女声"'
    )
    parser.add_argument('srt_file', help='输入 SRT 文件路径')
    parser.add_argument('--mode', choices=['single', 'separate'], default='single',
                        help='模式：single（合并为一个音频）或 separate（每句单独输出）')
    parser.add_argument('--language', default='Chinese', help='合成语言')
    parser.add_argument('--instruct', default='', help='语音风格指令')
    parser.add_argument('--model_path', default=DEFAULT_TTS_MODEL,
                        help=f'模型路径（默认: {DEFAULT_TTS_MODEL}）')
    parser.add_argument('--output_dir', default='.', help='输出目录')
    parser.add_argument('--output_prefix', default='output', help='输出文件名前缀')
    parser.add_argument('--silence', type=float, default=0.0,
                        help='single 模式下句子间插入的静音秒数')
    parser.add_argument('--max_chars_per_segment', type=int, default=200,
                        help='单次合成最大字符数（超长则拆分）')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='推理设备')
    parser.add_argument('--dtype', default='float32', choices=['float32', 'bfloat16'],
                        help='数据类型')

    args = parser.parse_args()

    # 检查 SRT 文件
    if not os.path.exists(args.srt_file):
        print(f"❌ SRT 文件不存在: {args.srt_file}")
        sys.exit(1)

    # 解析 SRT
    print(f"📖 读取 SRT 文件: {args.srt_file}")
    subtitles = parse_srt(args.srt_file)
    if not subtitles:
        print("❌ 未能解析出任何字幕条目")
        sys.exit(1)
    print(f"✅ 共解析出 {len(subtitles)} 条字幕")

    # 提取文本列表（忽略时间戳，仅文本）
    texts = [text for _, _, text in subtitles]
    # 过滤空文本
    texts = [t for t in texts if t.strip()]
    if not texts:
        print("❌ 所有字幕文本均为空")
        sys.exit(1)

    # 加载模型
    device = args.device
    dtype = torch.bfloat16 if args.dtype == 'bfloat16' else torch.float32
    print(f"💻 使用设备: {device}, 数据类型: {dtype}")
    print("🧠 加载 Qwen3-TTS 模型...")
    try:
        model = Qwen3TTSModel.from_pretrained(
            args.model_path,
            device_map=device,
            dtype=dtype,
        )
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        sys.exit(1)
    print("✅ 模型加载完成")

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    start_time = time.time()
    language = args.language
    instruct = args.instruct

    if args.mode == 'separate':
        # ---------- 每条字幕单独合成 ----------
        print("🔹 模式: separate (每条单独输出)")
        for idx, text in enumerate(texts, start=1):
            print(f"  处理第 {idx}/{len(texts)} 条: {text[:30]}...")
            # 若文本超长，分段合成并拼接（但 separate 模式建议限制单句长度，这里做简单处理）
            segments = split_text_for_tts(text, args.max_chars_per_segment)
            wavs = []
            for seg in segments:
                try:
                    wav, sr = model.generate_voice_design(
                        text=seg,
                        language=language,
                        instruct=instruct if instruct else None,
                    )
                    wavs.append(wav[0])  # generate_voice_design 返回列表
                except Exception as e:
                    print(f"    ⚠️ 合成失败: {e}")
                    continue
            if not wavs:
                continue
            # 拼接该条字幕的多个片段（无静音）
            combined = np.concatenate(wavs) if len(wavs) > 1 else wavs[0]
            filename = f"{args.output_prefix}_{idx:03d}.wav"
            filepath = os.path.join(args.output_dir, filename)
            sf.write(filepath, combined, sr)
            print(f"   ✅ 已保存: {filepath}")

        print(f"✅ 全部合成完成，共 {len(texts)} 个文件")

    else:  # single 模式
        # ---------- 合并所有字幕到一个音频 ----------
        print("🔹 模式: single (合并为一个音频)")
        # 将所有文本合并成一个大字符串，用句号分隔
        full_text = '。'.join(texts)  # 中文句号分隔
        # 拆分长文本
        text_segments = split_text_for_tts(full_text, args.max_chars_per_segment)
        print(f"  文本总长 {len(full_text)} 字符，分为 {len(text_segments)} 个片段合成")
        all_wavs = []
        sr = None
        for i, seg in enumerate(text_segments, start=1):
            print(f"  合成片段 {i}/{len(text_segments)}: {seg[:30]}...")
            try:
                wav, sr = model.generate_voice_design(
                    text=seg,
                    language=language,
                    instruct=instruct if instruct else None,
                )
                all_wavs.append(wav[0])
            except Exception as e:
                print(f"    ⚠️ 片段合成失败: {e}")
                continue
        if not all_wavs:
            print("❌ 所有片段合成失败")
            sys.exit(1)

        # 拼接（插入静音）
        if len(all_wavs) > 1:
            print(f"  拼接 {len(all_wavs)} 个音频片段，静音间隔 {args.silence} 秒")
            combined = concatenate_wavs(all_wavs, sr, args.silence)
        else:
            combined = all_wavs[0]
        filename = f"{args.output_prefix}.wav"
        filepath = os.path.join(args.output_dir, filename)
        sf.write(filepath, combined, sr)
        print(f"✅ 已保存合并音频: {filepath}")

    elapsed = time.time() - start_time
    print(f"⏱️ 总耗时: {elapsed:.2f} 秒")


if __name__ == '__main__':
    main()
