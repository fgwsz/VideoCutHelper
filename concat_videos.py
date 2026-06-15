#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
                   FFmpeg 视频无损拼接工具 v5.7
================================================================================

📖 项目概述
------------
这是一个基于 FFmpeg 的 Python 脚本，用于按文件名升序自动拼接多个视频文件。
核心设计理念：快速、无损、灵活。默认采用 MPEG-TS 中转 + 流拷贝技术，避免
重新编码，从而实现“秒级”拼接；同时智能处理分辨率差异、编码格式不一致和
尾部裁剪需求。

✨ 核心功能
------------
1. 灵活输入
   - 支持直接指定单个或多个视频文件。
   - 支持指定目录（自动扫描该目录下所有视频文件，不递归子目录）。
   - 支持混合输入（文件 + 目录）。
   - 支持的视频扩展名：.mp4, .mkv, .avi, .mov, .ts, .flv, .webm, .MOV
     （可通过 -e 参数自定义）

2. 自动排序
   - 所有输入视频按文件名字典序升序拼接（例如 1.mp4, 10.mp4, 2.mp4）
   - 排序基于文件名（不含路径），确保跨目录输入时仍按名称组织

3. 拼接策略

   【模式A】默认快速无损拼接
   - 流程：每个视频 → 转封装为 MPEG-TS（流拷贝）→ 合并所有 TS 片段 → 转封装为最终格式
   - 优点：不重新编码，速度极快（等同于文件复制），避免直接 concat 的时长异常问题
   - 缺点：若输入视频分辨率不一致，输出文件的容器元数据（width/height）仅保留第一个视频的信息，
           但现代播放器会忽略元数据，直接解析每一帧，因此实际播放正常

   【模式B】尾部裁剪（去除片尾/广告）
   - 命令：--trim-end 5 （裁剪每个视频末尾5秒）
   - 子模式：
        • 快速裁剪（默认）: 使用 `-c copy` 进行关键帧裁剪，速度极快，但裁剪长度可能不精确（误差±0.5秒）
        • 精确裁剪（--exact-trim）: 重新编码，精确到帧，速度较慢
   - 说明：快速裁剪适合去除片尾等不要求精确边界的场景；精确裁剪适合需要严格对齐的场合

   【模式C】统一分辨率（修正元数据）
   - 命令：--resample 或 --uniform-resolution 1920x1080
   - 当需要将拼接结果导入专业剪辑软件（Premiere Pro、Final Cut）或上传到严格要求元数据的平台时使用
   - 自动选择目标分辨率：优先采用所有横屏视频中的最大宽×高；若全为竖屏，则采用竖屏最大尺寸
   - 竖屏视频在横屏输出中会自动左右加黑边（scale+pad 滤镜），保持原始比例

   【模式D】编码格式统一（解决 H.264/H.265 混用问题）
   - 当检测到视频编码不一致时，自动统计每种编码的文件个数和总大小
   - 交互式让用户选择目标编码（H.264 或 H.265）
   - 只重新编码那些不是目标编码的视频，已是目标编码的视频保持流拷贝
   - 也可通过 --resample 等参数强制全部重编码

4. 智能交互
   - 分辨率不一致时，询问是否重新编码统一分辨率（默认否）
   - 编码不一致时，询问并让用户选择目标编码（默认根据统计选择）
   - 添加 --yes 参数可跳过所有交互，用于自动化脚本

5. 其他特性
   - 自动清理临时文件
   - 详细的进度提示（带 emoji）和错误信息
   - 最终时长验证（期望 vs 实际）
   - 支持跳过分辨率/编码检查（--no-check）

🚀 快速开始
------------
环境要求：
   • Python 3.6+
   • FFmpeg（含 ffmpeg 和 ffprobe），已加入系统 PATH

安装：
   将本脚本保存为 concat_videos.py，并赋予执行权限（Linux/macOS）：
       chmod +x concat_videos.py

基本用法：
   python concat_videos.py [输入...] [-o 输出] [选项]

典型示例：
   # 1. 快速拼接当前目录下所有视频（分辨率不一致时会询问）
   python concat_videos.py

   # 2. 拼接指定目录，输出到 merged.mp4
   python concat_videos.py /path/to/videos -o merged.mp4

   # 3. 拼接多个指定文件（支持跨目录）
   python concat_videos.py video1.mp4 video2.mkv /other/video3.mp4

   # 4. 快速裁剪每个视频末尾5秒后拼接（去除片尾）
   python concat_videos.py *.mp4 --trim-end 5 -o trimmed.mp4

   # 5. 精确裁剪末尾5秒（重新编码，慢但精确）
   python concat_videos.py *.mp4 --trim-end 5 --exact-trim

   # 6. 强制统一分辨率（自动选择横屏最大尺寸）
   python concat_videos.py *.mp4 --resample -o uniform.mp4

   # 7. 手动指定统一分辨率 1920x1080
   python concat_videos.py *.mp4 --uniform-resolution 1920x1080

   # 8. 同时裁剪+统一分辨率
   python concat_videos.py *.mp4 --trim-end 3 --uniform-resolution 1920x1080

   # 9. 自动化脚本（跳过所有交互）
   python concat_videos.py *.mp4 --yes -o auto.mp4

📋 完整命令行参数
-----------------
参数                    说明
-------------------------------------------------------------------------------
inputs                  视频文件或目录（可多个），默认为当前目录
-o, --output           输出文件路径（默认 concat_output.mp4）
-e, --extensions       支持的视频扩展名列表（默认 .mp4 .mkv .avi .mov .ts .flv .webm .MOV）
--no-check             跳过分辨率/编码一致性检查（不检测也不警告）
--resample             强制重新编码并统一分辨率（自动选择目标分辨率，优先横屏）
--uniform-resolution   手动指定统一分辨率，格式 WxH（例如 1920x1080）或 auto
--trim-end             从每个视频末尾裁剪掉指定时长，支持秒数（5）或 HH:MM:SS（00:00:05）
--exact-trim           与 --trim-end 同时使用时，启用精确裁剪（重新编码）
--yes                  跳过所有交互确认（用于自动化脚本）

时长格式说明：
   --trim-end 接受两种格式：
       • 纯数字（整数或浮点数）：秒数，例如 5 或 3.5
       • HH:MM:SS.msec：例如 00:00:05（5秒），00:01:30.5（1分30.5秒）

⚙️ 工作原理详解
-----------------
【无损快速拼接流程】
   输入视频 → 转封装为 TS（流拷贝）→ 合并所有 TS 片段（concat demuxer）→ 转封装为输出格式
   全程不重新编码，速度等同于文件复制。TS 格式天然支持拼接，且能避免直接 concat
   不同编码参数视频时出现的“时长异常”问题。

【快速裁剪原理（默认）】
   ffmpeg -i input.mp4 -ss 0 -t <新时长> -c copy -copyts -start_at_zero output.ts
   -c copy 复制流，-copyts 保留输入时间戳，-start_at_zero 强制从 0 开始。
   由于只能切在关键帧，实际裁剪长度可能略有偏差，但可满足大部分去片尾需求。

【精确裁剪原理（--exact-trim）】
   ffmpeg -i input.mp4 -ss 0 -t <新时长> -c:v libx264 ... output.ts
   重新编码，每一帧都可精准控制，但速度慢。

【统一分辨率原理】
   使用 scale+pad 滤镜：
       scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2
   先将视频等比缩放到能完整放入目标画布，再居中填充黑边，保证所有内容可见。

【编码格式统一原理】
   只对非目标编码的视频调用 ffmpeg 重新编码（libx264 或 libx265），保持原分辨率；
   已是目标编码的视频直接流拷贝。这样避免重复编码已符合要求的视频。

❓ 常见问题 (FAQ)
-----------------
Q1：拼接后视频总时长比预期多出几秒？
A1：可能是快速裁剪模式时间戳不连续导致。解决方案：
    - 使用 --exact-trim 进行精确裁剪（重新编码）。
    - 或者忽略（现代播放器通常仍能正确播放）。

Q2：输出文件的元数据显示分辨率不对，比如竖屏却显示横屏？
A2：这是快速拼接模式的正常现象。容器元数据只保留第一个视频的信息，
    但实际视频流中各帧分辨率是正确的，播放无影响。如需修正，请使用 --resample。

Q3：重新编码太慢怎么办？
A3：可修改脚本中的编码预设（-preset）为 ultrafast，或启用硬件加速
    （将 libx264 替换为 h264_nvenc 等），但这会降低压缩率或画质。

Q4：如何让脚本按数字顺序排序（1,2,10）而不是字典序（1,10,2）？
A4：安装 natsort 库，将排序代码替换为：
    from natsort import natsorted
    video_files = natsorted(video_files, key=lambda x: x.name)

Q5：脚本报错“ffprobe 不是内部或外部命令”？
A5：请确认 FFmpeg 已正确安装并添加到了系统 PATH 中，重启终端后重试。

Q6：混合 H.264 和 H.265 视频拼接后后面的视频无画面怎么办？
A6：本脚本已自动处理：检测到编码不一致时会交互让用户选择目标编码，
    并只重新编码不符合目标编码的视频，从而避免此问题且避免重复编码。

================================================================================
"""

import os
import subprocess
import sys
import tempfile
import argparse
import shutil
import re
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple

# ==================== 常量配置 ====================
# 默认支持的视频文件扩展名（不区分大小写）
DEFAULT_EXTENSIONS: Set[str] = {
    '.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv', '.webm', '.MOV'
}
# 默认输出文件名
DEFAULT_OUTPUT: str = "concat_output.mp4"
# 临时目录前缀（用于存放中间 TS 文件）
TEMP_PREFIX: str = "ffmpeg_concat_"


# ==================== 辅助函数 ====================
def parse_duration(duration_str: str) -> float:
    """
    解析时长字符串，返回秒数（浮点数）。

    支持格式：
        - 纯数字（整数或浮点数），如 "5", "3.5"
        - HH:MM:SS.msec，如 "00:00:05", "01:30:05.500"

    异常：输入格式无效时抛出 ValueError
    """
    duration_str = duration_str.strip()
    # 尝试直接解析为浮点数（秒）
    try:
        return float(duration_str)
    except ValueError:
        pass

    # 尝试解析 HH:MM:SS.msec 格式
    match = re.match(r'^(\d{1,2}):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$', duration_str)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        s = float(match.group(3))
        return h * 3600 + m * 60 + s

    raise ValueError(f"无法解析时长格式: {duration_str}，请使用秒数或 HH:MM:SS.msec 格式")


def get_video_duration(file_path: Path) -> Optional[float]:
    """
    使用 ffprobe 获取视频时长（秒）。

    返回 None 表示获取失败。
    """
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except:
        pass
    return None


def get_file_size_mb(file_path: Path) -> float:
    """获取文件大小（MB）。"""
    return file_path.stat().st_size / (1024 * 1024)


def collect_video_files(paths: List[str], extensions: Set[str]) -> List[Path]:
    """
    从给定的路径列表（文件或目录）中收集所有符合条件的视频文件，并按文件名升序排序。

    参数:
        paths: 输入路径列表（字符串形式），可以是文件或目录
        extensions: 支持的视频扩展名集合（小写带点）

    返回:
        排序后的 Path 对象列表
    """
    video_files: List[Path] = []
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            print(f"⚠️ 警告：路径不存在，已忽略 - {p}")
            continue
        if p.is_file():
            if p.suffix.lower() in extensions:
                video_files.append(p)
            else:
                print(f"⚠️ 警告：文件扩展名不支持，已忽略 - {p}")
        elif p.is_dir():
            for f in p.iterdir():
                if f.is_file() and f.suffix.lower() in extensions:
                    video_files.append(f)
        else:
            print(f"⚠️ 警告：未知类型，已忽略 - {p}")
    # 按文件名字典序升序排序
    video_files.sort(key=lambda x: x.name)
    return video_files


def get_video_stream_info(file_path: Path) -> Optional[Dict[str, str]]:
    """
    使用 ffprobe 获取视频流的编码信息（编码名称、宽度、高度、像素格式、帧率）。

    参数:
        file_path: 视频文件路径

    返回:
        包含编码信息的字典，失败返回 None
    """
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,r_frame_rate',
        '-of', 'default=noprint_wrappers=1', str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        info: Dict[str, str] = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                info[k] = v
        return info if info else None
    except Exception:
        return None


def get_video_codec(file_path: Path) -> Optional[str]:
    """
    获取视频编码名称（如 'h264', 'hevc'）。

    参数:
        file_path: 视频文件路径

    返回:
        编码名称字符串，失败返回 None
    """
    info = get_video_stream_info(file_path)
    if info and 'codec_name' in info:
        return info['codec_name'].lower()
    return None


def get_all_resolutions(video_files: List[Path]) -> List[Optional[Tuple[int, int]]]:
    """
    获取所有视频文件的分辨率列表。

    参数:
        video_files: 视频文件路径列表

    返回:
        每个视频的 (width, height) 元组列表，无法获取的为 None
    """
    resolutions = []
    for vf in video_files:
        info = get_video_stream_info(vf)
        if info and 'width' in info and 'height' in info:
            resolutions.append((int(info['width']), int(info['height'])))
        else:
            resolutions.append(None)
    return resolutions


def check_resolution_consistency(video_files: List[Path]) -> bool:
    """
    检查所有视频的分辨率是否完全一致。

    参数:
        video_files: 视频文件路径列表

    返回:
        True 表示所有分辨率一致；False 表示存在至少一个不同分辨率
    """
    res_list = get_all_resolutions(video_files)
    unique_res = set(r for r in res_list if r is not None)
    return len(unique_res) <= 1


def get_codec_stats(video_files: List[Path]) -> Dict[str, Dict[str, any]]:
    """
    统计每种编码格式的文件个数和总大小。

    参数:
        video_files: 视频文件路径列表

    返回:
        字典，格式: {codec_name: {'count': int, 'total_size_mb': float}}
    """
    stats = {}
    for vf in video_files:
        info = get_video_stream_info(vf)
        codec = info['codec_name'].lower() if info and 'codec_name' in info else 'unknown'
        size_mb = get_file_size_mb(vf)
        if codec not in stats:
            stats[codec] = {'count': 0, 'total_size_mb': 0.0}
        stats[codec]['count'] += 1
        stats[codec]['total_size_mb'] += size_mb
    return stats


def prompt_codec_choice(stats: Dict[str, Dict[str, any]]) -> str:
    """
    展示编码统计信息，让用户选择目标编码格式。

    参数:
        stats: get_codec_stats 返回的统计字典

    返回:
        用户选择的编码名称（如 'h264' 或 'hevc'）
    """
    print("\n📊 检测到多种视频编码格式：")
    codec_list = list(stats.keys())
    for i, codec in enumerate(codec_list, 1):
        count = stats[codec]['count']
        size_mb = stats[codec]['total_size_mb']
        print(f"   {i}. {codec.upper()} : {count} 个文件, 总大小 {size_mb:.2f} MB")
    print("   （选择后将把其他编码的视频重新编码为该格式）")
    while True:
        try:
            choice = input("   请选择目标编码编号 (1-{}): ".format(len(codec_list))).strip()
            idx = int(choice) - 1
            if 0 <= idx < len(codec_list):
                return codec_list[idx]
            else:
                print("   无效编号，请重新输入。")
        except ValueError:
            print("   请输入数字编号。")


def get_target_resolution(video_files: List[Path]) -> Tuple[int, int]:
    """
    根据视频方向自动确定目标分辨率（优先采用横屏最大分辨率）。

    参数:
        video_files: 视频文件路径列表

    返回:
        目标分辨率元组 (width, height)

    异常:
        当无法获取任何视频的分辨率时抛出 ValueError
    """
    resolutions = get_all_resolutions(video_files)
    valid_res = [r for r in resolutions if r is not None]
    if not valid_res:
        raise ValueError("无法获取任何视频的分辨率")

    landscape_res = [(w, h) for w, h in valid_res if w >= h]
    portrait_res = [(w, h) for w, h in valid_res if w < h]

    if landscape_res:
        max_w = max(r[0] for r in landscape_res)
        max_h = max(r[1] for r in landscape_res)
        print(f"📐 检测到横屏视频，目标分辨率采用横屏尺寸：{max_w}x{max_h}")
        return (max_w, max_h)
    else:
        max_w = max(r[0] for r in portrait_res)
        max_h = max(r[1] for r in portrait_res)
        print(f"📐 全部为竖屏视频，目标分辨率采用竖屏尺寸：{max_w}x{max_h}")
        return (max_w, max_h)


def convert_to_ts(input_file: Path, output_ts: Path,
                  target_res: Optional[Tuple[int, int]] = None,
                  trim_end: Optional[float] = None,
                  exact_trim: bool = False,
                  target_codec: Optional[str] = None) -> Tuple[bool, float]:
    """
    将单个视频文件转换为 MPEG-TS 格式。
    根据参数决定使用流拷贝（快速）还是重新编码。

    参数:
        input_file: 输入视频文件路径
        output_ts: 输出的 TS 文件路径
        target_res: 目标分辨率，None 表示不改变分辨率
        trim_end: 从尾部裁剪的秒数，None 表示不裁剪
        exact_trim: 是否精确裁剪（重新编码）
        target_codec: 目标编码器（'libx264' 或 'libx265'），如果提供且当前视频编码与之不符，则重新编码

    返回:
        (success, duration) 元组，success 为布尔值，duration 为输出文件时长（秒）
    """
    output_duration = 0.0

    # 获取当前视频编码（如果需要统一编码）
    current_codec = None
    if target_codec is not None:
        current_codec = get_video_codec(input_file)
        if current_codec is None:
            print(f"⚠️ 无法获取 {input_file.name} 的编码信息，将重新编码")
            current_codec = 'unknown'

    # 决定是否需要重新编码
    need_reencode = (target_res is not None) or (trim_end is not None and exact_trim)
    if not need_reencode and target_codec is not None:
        # 如果需要统一编码，检查当前编码是否已是目标编码
        # 映射编码器名称到简短编码名
        target_short = None
        if target_codec == 'libx264':
            target_short = 'h264'
        elif target_codec == 'libx265':
            target_short = 'hevc'
        if target_short and current_codec and current_codec != target_short:
            need_reencode = True

    # 快速裁剪模式（流拷贝）
    if not need_reencode and trim_end is not None and not exact_trim and target_res is None:
        duration = get_video_duration(input_file)
        if duration is None:
            print(f"❌ 无法获取 {input_file.name} 的时长")
            return False, 0.0
        trim_duration = duration - trim_end
        if trim_duration <= 0:
            print(f"⚠️ 警告：{input_file.name} 裁剪时长超过视频本身，跳过")
            return False, 0.0
        print(f"   📊 原始时长: {duration:.2f}s, 裁剪后时长: {trim_duration:.2f}s")
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-c', 'copy',
            '-copyts',          # 保留输入时间戳
            '-start_at_zero',   # 强制从 0 开始
            '-f', 'mpegts',
            str(output_ts)
        ]
        print(f"   🔧 执行快速裁剪命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ 快速裁剪失败：{input_file}\n{result.stderr}")
            return False, 0.0
        out_duration = get_video_duration(output_ts)
        if out_duration is None:
            print(f"⚠️ 无法获取裁剪后文件的时长")
        else:
            output_duration = out_duration
            if abs(out_duration - trim_duration) > 0.5:
                print(f"⚠️ 时长验证异常: 期望 {trim_duration:.2f}s, 实际 {out_duration:.2f}s")
        return True, output_duration

    # 无损流拷贝模式（无裁剪、无重编码、无强制重编码）
    if not need_reencode:
        # 获取编码类型以选择 bitstream filter
        codec_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1',
            str(input_file)
        ]
        try:
            codec_result = subprocess.run(codec_cmd, capture_output=True, text=True, check=True)
            video_codec = codec_result.stdout.strip().lower()
        except:
            video_codec = 'unknown'
        bsf_map = {
            'h264': 'h264_mp4toannexb',
            'hevc': 'hevc_mp4toannexb',
            'mpeg4': 'mpeg4_unpack_bframes',
        }
        bsf = bsf_map.get(video_codec, None)
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-c', 'copy',
            '-f', 'mpegts',
            '-muxdelay', '0', '-muxpreload', '0'
        ]
        if bsf:
            cmd += ['-bsf:v', bsf]
        cmd += ['-fflags', '+genpts', str(output_ts)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ 流拷贝失败：{input_file}\n{result.stderr}")
            return False, 0.0
        out_duration = get_video_duration(output_ts)
        output_duration = out_duration if out_duration else 0.0
        return True, output_duration

    # 重新编码模式（裁剪或/和缩放，或统一编码）
    duration = get_video_duration(input_file)
    if duration is None:
        print(f"❌ 无法获取 {input_file.name} 的时长")
        return False, 0.0
    trim_duration = duration - trim_end if trim_end else duration
    if trim_duration <= 0:
        print(f"⚠️ 警告：{input_file.name} 裁剪时长超过视频本身，跳过")
        return False, 0.0
    print(f"   📊 原始时长: {duration:.2f}s, 重新编码后时长: {trim_duration:.2f}s")

    # 确定使用的编码器
    if target_codec is None:
        vcodec = 'libx264'
        vcodec_opts = ['-preset', 'veryfast', '-crf', '23']
    else:
        vcodec = target_codec
        if vcodec == 'libx264':
            vcodec_opts = ['-preset', 'veryfast', '-crf', '23']
        elif vcodec == 'libx265':
            vcodec_opts = ['-preset', 'veryfast', '-crf', '28']  # CRF 28 对应 H.265 较高质量
        else:
            vcodec_opts = ['-preset', 'veryfast', '-crf', '23']

    if target_res is None:
        # 仅重新编码（保持原分辨率）
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-c:v', vcodec, *vcodec_opts,
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'mpegts', '-fflags', '+genpts',
            str(output_ts)
        ]
    else:
        # 裁剪 + 缩放
        w, h = target_res
        vf = f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2'
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-vf', vf,
            '-c:v', vcodec, *vcodec_opts,
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'mpegts', '-fflags', '+genpts',
            str(output_ts)
        ]

    print(f"   🔧 执行重新编码命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ 重新编码失败：{input_file}\n{result.stderr}")
        return False, 0.0
    out_duration = get_video_duration(output_ts)
    output_duration = out_duration if out_duration else trim_duration
    return True, output_duration


def concat_videos_safe(video_files: List[Path], output_path: Path,
                       uniform_res: Optional[Tuple[int, int]] = None,
                       trim_end: Optional[float] = None,
                       exact_trim: bool = False,
                       target_codec: Optional[str] = None) -> None:
    """
    安全拼接模式：先将每个视频转为 TS（可选重编码），然后合并所有 TS，最后转封装为目标格式。
    并验证最终时长与期望值的偏差。

    参数:
        video_files: 按顺序排列的视频文件列表
        output_path: 最终输出文件路径
        uniform_res: 统一分辨率（None 表示不改变）
        trim_end: 从每个视频末尾裁剪的秒数（None 表示不裁剪）
        exact_trim: 是否精确裁剪
        target_codec: 目标编码器（用于统一编码，None 表示不强制）
    """
    temp_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    ts_files = []
    expected_total_duration = 0.0

    try:
        print("🔄 正在转换视频为 TS 格式...")
        for idx, vf in enumerate(video_files):
            ts_file = Path(temp_dir) / f"part_{idx:04d}.ts"
            print(f"   处理 {vf.name} -> {ts_file.name}")
            success, duration = convert_to_ts(vf, ts_file, uniform_res, trim_end, exact_trim, target_codec)
            if not success:
                raise RuntimeError(f"转换 {vf.name} 失败")
            ts_files.append(ts_file)
            expected_total_duration += duration

        # 创建 concat 列表文件
        list_file = Path(temp_dir) / "concat_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for ts_file in ts_files:
                escaped = str(ts_file.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        # 合并所有 TS 片段
        merged_ts = Path(temp_dir) / "merged.ts"
        cmd_concat = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(list_file), '-c', 'copy', str(merged_ts)
        ]
        print("🔗 正在合并 TS 片段...")
        subprocess.run(cmd_concat, capture_output=True, text=True, check=True)

        # 转封装为最终格式
        print(f"📦 正在转封装为最终格式：{output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd_final = ['ffmpeg', '-y', '-i', str(merged_ts), '-c', 'copy', str(output_path)]
        subprocess.run(cmd_final, capture_output=True, text=True, check=True)

        # 验证最终时长
        final_duration = get_video_duration(output_path)
        if final_duration is None:
            print("⚠️ 无法获取最终视频时长")
        else:
            print(f"📊 期望总时长: {expected_total_duration:.2f}s, 实际总时长: {final_duration:.2f}s")
            if abs(final_duration - expected_total_duration) > 0.5:
                print("⚠️ 警告：实际总时长与期望值偏差较大，可能是由于快速裁剪模式时间戳不连续导致。")
                print("   建议使用 --exact-trim 重新拼接以获得精确结果。")

        print(f"✅ 拼接成功！输出文件：{output_path}")

    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg 命令执行失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 拼接过程中出错：{e}")
        sys.exit(1)
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    """命令行入口：解析参数、收集文件、处理编码/分辨率一致性、执行拼接。"""
    parser = argparse.ArgumentParser(
        description="视频拼接工具（默认快速拼接，支持快速尾部裁剪）",
        epilog="示例：\n  %(prog)s *.mp4 -o merged.mp4\n  %(prog)s --trim-end 5 *.mp4"
    )
    parser.add_argument('inputs', nargs='*', default=['.'],
                        help='视频文件或目录（可多个）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT,
                        help=f'输出文件路径（默认 {DEFAULT_OUTPUT}）')
    parser.add_argument('-e', '--extensions', nargs='+', default=list(DEFAULT_EXTENSIONS),
                        help=f'支持的视频扩展名（默认 {", ".join(DEFAULT_EXTENSIONS)}）')
    parser.add_argument('--no-check', action='store_true',
                        help='跳过分辨率/编码一致性检查')
    parser.add_argument('--resample', action='store_true',
                        help='强制重新编码并统一分辨率（自动选择）')
    parser.add_argument('--uniform-resolution', nargs='?', const='auto', default=None,
                        help='手动指定统一分辨率，如 1920x1080')
    parser.add_argument('--trim-end', type=str, default=None,
                        help='从每个视频末尾裁剪掉指定时长（例如 5 或 00:00:05）')
    parser.add_argument('--exact-trim', action='store_true',
                        help='启用精确裁剪（重新编码），否则使用快速裁剪（流拷贝）')
    parser.add_argument('--yes', action='store_true',
                        help='跳过交互确认')

    args = parser.parse_args()

    # 处理尾部裁剪参数
    trim_seconds: Optional[float] = None
    if args.trim_end:
        try:
            trim_seconds = parse_duration(args.trim_end)
            if trim_seconds <= 0:
                print("❌ --trim-end 时长必须大于 0")
                sys.exit(1)
            mode = "精确" if args.exact_trim else "快速"
            print(f"✂️ 将裁剪每个视频末尾 {trim_seconds} 秒（{mode}模式）")
            if not args.exact_trim:
                print("   (快速模式基于关键帧，可能不精确；如需精确请加 --exact-trim)")
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    # 收集视频文件
    extensions = {ext.lower() for ext in args.extensions}
    print("🔍 正在收集视频文件...")
    video_files = collect_video_files(args.inputs, extensions)
    if not video_files:
        print("❌ 未找到任何视频文件")
        sys.exit(1)

    print(f"📁 找到 {len(video_files)} 个文件，按名称排序：")
    for i, vf in enumerate(video_files, 1):
        print(f"   {i}. {vf.name}")

    # 编码一致性处理
    codec_stats = get_codec_stats(video_files)
    codec_consistent = len(codec_stats) <= 1
    target_codec = None   # None 表示不强制统一编码

    if not codec_consistent:
        print("⚠️ 警告：输入视频的编码格式不一致。")
        user_requested_reencode = (args.resample or args.uniform_resolution or (trim_seconds is not None and args.exact_trim))
        if not user_requested_reencode and not args.yes:
            target_codec_name = prompt_codec_choice(codec_stats)
            if target_codec_name in ['h264', 'avc']:
                target_codec = 'libx264'
            elif target_codec_name in ['hevc', 'h265']:
                target_codec = 'libx265'
            else:
                target_codec = 'libx264'
            print(f"✅ 将把非 {target_codec_name.upper()} 编码的视频重新编码，{target_codec_name.upper()} 视频保持原样。")
        else:
            if user_requested_reencode:
                print("   由于您指定了重编码参数，将使用 H.264 编码统一视频（所有视频将重新编码）。")
                target_codec = 'libx264'   # 强制所有视频重编码（包括同编码的）
            else:
                print("   (--yes 跳过交互，将尝试快速拼接，但可能导致后续视频无画面)")

    # 分辨率一致性处理
    need_reencode = (args.resample or args.uniform_resolution or (trim_seconds is not None and args.exact_trim) or target_codec is not None)
    if not args.no_check:
        if not check_resolution_consistency(video_files):
            print("⚠️ 输入视频的分辨率不一致。")
            if not need_reencode:
                print("   默认采用无损快速拼接（元数据可能不准）。")
                if not args.yes:
                    ans = input("   是否重新编码以统一分辨率？(y/N) [默认 N]: ").strip().lower()
                    if ans == 'y':
                        args.resample = True
                        need_reencode = True
                        print("✅ 已启用重编码模式。")
                    else:
                        print("⏩ 继续使用快速拼接。")
                else:
                    print("   (--yes 跳过询问，使用快速拼接)")

    # 确定目标分辨率
    target_res = None
    if args.resample:
        target_res = get_target_resolution(video_files)
        print(f"📐 启用重编码，目标分辨率：{target_res[0]}x{target_res[1]}")
    elif args.uniform_resolution is not None:
        if args.uniform_resolution == 'auto':
            target_res = get_target_resolution(video_files)
            print(f"📐 自动分辨率：{target_res[0]}x{target_res[1]}")
        else:
            match = re.match(r'(\d+)[xX](\d+)', args.uniform_resolution)
            if match:
                target_res = (int(match.group(1)), int(match.group(2)))
                print(f"📐 手动分辨率：{target_res[0]}x{target_res[1]}")
            else:
                print("❌ 分辨率格式错误，应为 WxH")
                sys.exit(1)

    # 如果用户通过 `--resample` 或 `--uniform-resolution` 要求重编码，但未设置 target_codec，
    # 则默认使用 libx264（这样也会统一编码，但无需额外提示）
    if (args.resample or args.uniform_resolution) and target_codec is None:
        target_codec = 'libx264'
        print("🔄 由于启用了分辨率重编码，将同时统一视频编码为 H.264。")

    # 执行拼接
    concat_videos_safe(video_files, Path(args.output),
                       uniform_res=target_res,
                       trim_end=trim_seconds,
                       exact_trim=args.exact_trim,
                       target_codec=target_codec)


if __name__ == '__main__':
    main()
