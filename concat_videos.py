#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FFmpeg 无损视频拼接工具（增强版）

功能描述：
    本脚本使用 FFmpeg 将多个视频文件无损拼接为一个视频文件。
    支持按文件名升序自动排序，支持直接指定视频文件或包含视频文件的目录。
    
    核心改进：默认采用「TS 中转拼接」策略，解决原始 concat demuxer 因时间戳不连续、
    编码参数微小差异导致的时长异常、音视频不同步等问题。该策略将每个输入视频重新
    封装为 MPEG-TS 格式并重置时间戳，然后再拼接，整个过程不重新编码，速度快且稳定。

依赖：
    - Python 3.6+
    - FFmpeg（需包含 ffmpeg 和 ffprobe 命令，并已加入系统 PATH）

使用方法：
    python concat_videos.py [inputs...] [-o OUTPUT] [-e EXTENSIONS] [--no-check] [--direct-concat]

参数说明：
    inputs              要拼接的视频文件或包含视频文件的目录（可多个，默认为当前目录）
    -o, --output        输出文件路径（默认 concat_output.mp4）
    -e, --extensions    支持的视频扩展名列表（默认 .mp4 .mkv .avi .mov .ts .flv .webm .MOV）
    --no-check          跳过视频参数一致性检查（默认会进行简单检查）
    --direct-concat     使用原始的直接拼接方式（不推荐，可能引发时长异常）

示例：
    # 拼接当前目录下所有支持的视频（默认安全模式）
    python concat_videos.py

    # 拼接指定目录下的所有视频
    python concat_videos.py /path/to/videos -o merged.mp4

    # 直接指定多个视频文件
    python concat_videos.py video1.mp4 video2.mkv /other/video3.mp4
"""

import os
import subprocess
import sys
import tempfile
import argparse
import shutil
from pathlib import Path
from typing import List, Set, Dict, Optional

# ==================== 常量配置 ====================
DEFAULT_EXTENSIONS: Set[str] = {
    '.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv', '.webm', '.MOV'
}
DEFAULT_OUTPUT: str = "concat_output.mp4"
TEMP_PREFIX = "ffmpeg_concat_ts_"


# ==================== 辅助函数 ====================
def collect_video_files(paths: List[str], extensions: Set[str]) -> List[Path]:
    """从给定的路径列表（文件或目录）中收集所有符合条件的视频文件，并按文件名升序排序。"""
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
            print(f"⚠️ 警告：未知文件类型，已忽略 - {p}")

    video_files.sort(key=lambda x: x.name)
    return video_files


def get_video_stream_info(file_path: Path) -> Optional[Dict[str, str]]:
    """使用 ffprobe 获取视频流的编码信息（编码名、宽度、高度、像素格式）。"""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
        'stream=codec_name,width,height,pix_fmt', '-of', 'default=noprint_wrappers=1',
        str(file_path)
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


def check_video_compatibility(video_files: List[Path]) -> bool:
    """检查所有视频的视频流参数是否与第一个视频一致。"""
    if len(video_files) < 2:
        return True

    first_info = get_video_stream_info(video_files[0])
    if not first_info:
        print("⚠️ 警告：无法获取第一个视频的编码信息，跳过兼容性检查")
        return True

    all_same = True
    for vf in video_files[1:]:
        info = get_video_stream_info(vf)
        if not info:
            print(f"⚠️ 警告：无法获取 {vf.name} 的编码信息，跳过比较")
            continue
        for key in ['codec_name', 'width', 'height', 'pix_fmt']:
            if info.get(key) != first_info.get(key):
                print(f"⚠️ 警告：{vf.name} 的 {key} ({info.get(key)}) 与第一个视频 ({first_info.get(key)}) 不一致，可能导致拼接问题！")
                all_same = False
    return all_same


def convert_to_ts(input_file: Path, output_ts: Path) -> bool:
    """
    将单个视频文件重新封装为 MPEG-TS 格式，重置时间戳，不重新编码。
    返回 True 表示成功，False 表示失败。
    """
    # 探测视频编码类型
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

    # 根据编码选择比特流过滤器
    bsf_map = {
        'h264': 'h264_mp4toannexb',
        'hevc': 'hevc_mp4toannexb',
        'mpeg4': 'mpeg4_unpack_bframes',
    }
    bsf = bsf_map.get(video_codec, None)

    # 构建 ffmpeg 命令
    cmd = [
        'ffmpeg', '-i', str(input_file),
        '-c', 'copy',
        '-f', 'mpegts',
        '-muxdelay', '0',
        '-muxpreload', '0',
    ]
    if bsf:
        cmd += ['-bsf:v', bsf]          # 修正：去掉多余空格

    cmd += ['-fflags', '+genpts', str(output_ts)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ 转换 TS 失败：{input_file}\n错误信息：{result.stderr}")
        return False
    return True


def concat_videos_safe(video_files: List[Path], output_path: Path) -> None:
    """
    安全拼接模式：将每个视频转为 TS 并重置时间戳，然后合并 TS，最后转封装为目标格式。
    """
    temp_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    ts_files = []

    try:
        print("🔄 正在将输入视频转换为 TS 格式（重置时间戳）...")
        for idx, vf in enumerate(video_files):
            ts_file = Path(temp_dir) / f"part_{idx:04d}.ts"
            print(f"   处理 {vf.name} -> {ts_file.name}")
            if not convert_to_ts(vf, ts_file):
                raise RuntimeError(f"转换 {vf.name} 为 TS 失败")
            ts_files.append(ts_file)

        list_file = Path(temp_dir) / "concat_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for ts_file in ts_files:
                f.write(f"file '{ts_file.absolute()}'\n")

        merged_ts = Path(temp_dir) / "merged.ts"
        cmd_concat = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',
            str(merged_ts)
        ]
        print("🔗 正在合并 TS 片段...")
        result = subprocess.run(cmd_concat, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ 合并 TS 失败：{result.stderr}")
            raise RuntimeError("合并 TS 片段失败")

        print(f"📦 正在转封装为最终格式：{output_path}")
        cmd_final = [
            'ffmpeg', '-y',
            '-i', str(merged_ts),
            '-c', 'copy',
            str(output_path)
        ]
        result_final = subprocess.run(cmd_final, capture_output=True, text=True)
        if result_final.returncode != 0:
            print(f"❌ 最终转封装失败：{result_final.stderr}")
            raise RuntimeError("最终转封装失败")

        print(f"✅ 拼接成功！输出文件：{output_path}")

    except Exception as e:
        print(f"❌ 拼接过程中出错：{e}")
        sys.exit(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def concat_videos_direct(video_files: List[Path], output_path: Path) -> None:
    """
    原始直接拼接模式（不推荐，可能引发时长异常）
    """
    if not video_files:
        print("❌ 错误：没有提供任何有效的视频文件。")
        sys.exit(1)

    list_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            list_file = f.name
            for vf in video_files:
                escaped_path = str(vf).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file,
            '-c', 'copy',
            str(output_path)
        ]

        print("⚠️ 使用直接拼接模式（可能有时长异常风险）")
        print(f"🔧 执行命令：{' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ 拼接成功！输出文件：{output_path}")
        else:
            print(f"❌ FFmpeg 错误：\n{result.stderr}")
            sys.exit(1)
    finally:
        if list_file and os.path.exists(list_file):
            os.unlink(list_file)


# ==================== 主函数 ====================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="FFmpeg 无损视频拼接工具（增强版，默认使用 TS 中转解决时长异常）",
        epilog="示例：\n  %(prog)s /path/to/dir\n  %(prog)s video1.mp4 video2.mkv -o merged.mp4"
    )
    parser.add_argument('inputs', nargs='*', default=['.'],
                        help='要拼接的视频文件或目录（可多个，默认为当前目录）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT,
                        help=f'输出文件路径（默认 {DEFAULT_OUTPUT}）')
    parser.add_argument('-e', '--extensions', nargs='+', default=list(DEFAULT_EXTENSIONS),
                        help=f'支持的视频扩展名（默认 {", ".join(DEFAULT_EXTENSIONS)}）')
    parser.add_argument('--no-check', action='store_true',
                        help='跳过视频参数一致性检查')
    parser.add_argument('--direct-concat', action='store_true',
                        help='使用原始的直接拼接方式（不推荐，可能引发时长异常）')

    args = parser.parse_args()

    extensions: Set[str] = {ext.lower() for ext in args.extensions}

    print("🔍 正在收集视频文件...")
    video_files = collect_video_files(args.inputs, extensions)

    if not video_files:
        print("❌ 错误：未找到任何支持的视频文件。请检查路径和扩展名。")
        sys.exit(1)

    print(f"📁 找到 {len(video_files)} 个视频文件，按名称升序排列：")
    for i, vf in enumerate(video_files, 1):
        print(f"   {i}. {vf}")

    if not args.no_check:
        print("🔍 检查视频参数一致性...")
        check_video_compatibility(video_files)

    output_path = Path(args.output)
    if args.direct_concat:
        concat_videos_direct(video_files, output_path)
    else:
        print("🚀 使用安全拼接模式（TS 中转，可避免时长异常）...")
        concat_videos_safe(video_files, output_path)


if __name__ == '__main__':
    main()
