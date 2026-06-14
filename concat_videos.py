#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
FFmpeg 视频无损拼接工具
================================================================================

📖 项目简介
------------
这是一个基于 FFmpeg 的 Python 脚本，用于按文件名升序自动拼接多个视频文件。
核心特点：
  - 默认无损快速拼接：采用 MPEG-TS 中转 + 流拷贝技术，不重新编码，秒级完成。
  - 智能处理分辨率差异：当视频分辨率不一致时，仅警告并询问是否重编码（默认不重编码），避免不必要的性能开销。
  - 可选分辨率统一：支持自动或手动指定目标分辨率，重新编码后获得元数据准确的输出文件。
  - 跨平台支持：Windows / macOS / Linux 均可运行，依赖仅 Python 3.6+ 和 FFmpeg。

✨ 核心功能
------------
1. 灵活输入
   - 支持直接指定单个或多个视频文件。
   - 支持指定目录（自动扫描目录下所有视频文件，不递归子目录）。
   - 支持混合输入（例如：视频1.mp4 视频2.mkv ./目录A ./目录B）。
   - 支持的视频格式：.mp4, .mkv, .avi, .mov, .ts, .flv, .webm, .MOV（可自定义扩展名）。

2. 自动排序
   - 所有输入视频按文件名字典序升序拼接。
   - 排序基于文件名，不含路径，确保跨目录输入时仍按名称组织。

3. 拼接策略
   a) 默认模式（快速无损）
      - 每个视频先转换为 MPEG-TS 格式（重置时间戳，不重新编码）。
      - 使用 FFmpeg concat demuxer 合并所有 TS 片段。
      - 最后转封装为用户指定的格式（如 MP4）。
      - 优点：速度极快（等同于文件复制），避免直接 concat 可能出现的时长异常。
      - 缺点：若输入视频分辨率不一致，输出文件的容器元数据（如 width/height）只保留第一个视频的信息，
               但实际播放无影响（现代播放器会忽略元数据）。

   b) 统一分辨率模式（重新编码）
      - 当用户明确要求时（通过 --resample 或 --uniform-resolution），将所有视频重新编码到统一分辨率。
      - 自动选择目标分辨率：优先采用横屏视频的最大宽×高；若全为竖屏，则采用竖屏最大宽×高。
      - 手动指定分辨率：例如 --uniform-resolution 1920x1080。
      - 重编码使用 libx264 + veryfast 预设，画质与速度均衡；竖屏视频自动左右加黑边保持比例。
      - 适用场景：需要将拼接结果导入专业剪辑软件（Premiere Pro、Final Cut等）或上传到某些严格要求元数据的平台。

4. 分辨率不一致时的交互
   - 脚本启动时会自动检查所有视频的分辨率是否一致。
   - 若不一致且用户未提供 --resample / --uniform-resolution：
        * 输出警告信息。
        * 询问用户是否重新编码，默认选项为 N（不重编码）。
        * 若用户输入 y，则自动切换至重编码模式（使用自动选择的分辨率）。
   - 若添加 --yes 参数，则跳过交互，直接采用快速拼接（适合自动化脚本）。

5. 其他特性
   - 自动清理临时文件：所有中间 TS 文件和列表文件在处理完成后自动删除。
   - 错误处理：任何 FFmpeg 命令失败都会中止并显示错误信息。
   - 详细日志：每个步骤输出清晰的进度提示（带 emoji），便于监控。
   - 参数兼容性：可跳过分辨率检查（--no-check），自定义扩展名（-e）。

🚀 快速开始
------------
环境要求：
  - Python 3.6+
  - FFmpeg（包含 ffmpeg 和 ffprobe 命令，并已加入系统 PATH）

安装：
  将本脚本保存为 concat_videos.py，赋予执行权限（Linux/macOS）：
    chmod +x concat_videos.py

使用示例：
  # 1. 拼接当前目录下所有支持的视频（默认快速模式，分辨率不一致时会询问）
  python concat_videos.py

  # 2. 拼接指定目录下的所有视频，输出到 merged.mp4
  python concat_videos.py /path/to/videos -o merged.mp4

  # 3. 直接指定多个文件（支持不同目录）
  python concat_videos.py video1.mp4 video2.mkv /other/video3.mp4 -o result.mp4

  # 4. 强制重新编码，自动选择目标分辨率（横屏优先）
  python concat_videos.py *.mp4 --resample -o uniform.mp4

  # 5. 手动指定统一分辨率 1920x1080
  python concat_videos.py *.mp4 --uniform-resolution 1920x1080

  # 6. 跳过分辨率不一致的交互（用于自动化脚本）
  python concat_videos.py *.mp4 --yes -o quick.mp4

  # 7. 只处理 .mp4 和 .mov 文件
  python concat_videos.py . -e .mp4 .mov -o mixed.mp4

📋 命令行参数
-------------
  inputs                 视频文件或目录（可多个），默认为当前目录
  -o, --output          输出文件路径，默认 concat_output.mp4
  -e, --extensions      支持的视频扩展名列表，默认常见格式
  --no-check            跳过分辨率一致性检查（不检测也不警告）
  --resample            强制重新编码并统一分辨率（自动选择目标分辨率）
  --uniform-resolution [WxH或auto]  手动指定统一分辨率，如 1920x1080；auto 表示自动选择
  --yes                 跳过交互确认（用于脚本），分辨率不一致时自动采用快速拼接

⚙️ 工作原理简述
-----------------
无损快速拼接流程：
  输入视频 → 转封装为 TS（流拷贝） → 合并所有 TS 片段 → 转封装为输出格式
整个过程不重新编码，速度等同于文件复制。

统一分辨率重编码流程：
  输入视频 → 重新编码 + scale/pad 滤镜 → 合并 TS → 转封装输出
使用 libx264 编码，通过 scale+pad 保持比例并添加黑边。

❓ 常见问题
------------
Q1：拼接后视频总时长远超源文件总和？
A1：本脚本默认采用 TS 中转方式，已彻底规避此问题。若仍遇到，请检查输入视频是否含有可变帧率（VFR）。

Q2：输出文件的元数据显示分辨率不对（例如显示1080x1920，实际内容是横屏）？
A2：这是快速拼接模式的正常现象。容器元数据只继承了第一个视频的分辨率，但视频流内部各片段实际分辨率不同。
    现代播放器会忽略容器元数据，直接解析每一帧，因此播放正常。如需修正元数据，请使用 --resample 重新编码。

Q3：重新编码太慢怎么办？
A3：可使用更快的预设（如 ultrafast），或启用硬件加速（修改脚本中的编码器为 h264_nvenc 等），
    或者接受快速拼接模式（播放无影响）。

Q4：如何让脚本按数字顺序排序（1,2,10 而不是 1,10,2）？
A4：安装 natsort 库，将排序代码替换为：from natsort import natsorted; video_files = natsorted(video_files, key=lambda x: x.name)

Q5：脚本报错“ffprobe 不是内部或外部命令”？
A5：请确保 FFmpeg 已正确安装并添加到系统 PATH 中，重启终端后重试。

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
DEFAULT_EXTENSIONS: Set[str] = {
    '.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv', '.webm', '.MOV'
}
DEFAULT_OUTPUT: str = "concat_output.mp4"
TEMP_PREFIX: str = "ffmpeg_concat_"


# ==================== 辅助函数 ====================
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
            print(f"⚠️ 警告：未知文件类型，已忽略 - {p}")

    video_files.sort(key=lambda x: x.name)
    return video_files


def get_video_stream_info(file_path: Path) -> Optional[Dict[str, str]]:
    """
    使用 ffprobe 获取视频流的编码信息。

    参数:
        file_path: 视频文件路径

    返回:
        包含编码名称、宽度、高度、像素格式等信息的字典；若获取失败则返回 None
    """
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,r_frame_rate',
        '-of', 'default=noprint_wrappers=1',
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
    portrait_res  = [(w, h) for w, h in valid_res if w < h]

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


def convert_to_ts(input_file: Path, output_ts: Path, target_res: Optional[Tuple[int, int]] = None) -> bool:
    """
    将单个视频文件转换为 MPEG-TS 格式。
    若提供 target_res，则重新编码并缩放到目标分辨率（保持比例并填充黑边）；
    否则进行流拷贝（无损，速度极快）。

    参数:
        input_file: 输入视频文件路径
        output_ts: 输出的 TS 文件路径
        target_res: 目标分辨率 (width, height)；None 表示无损拷贝

    返回:
        True 表示成功，False 表示失败
    """
    if target_res is None:
        # 无损流拷贝
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
    else:
        # 重新编码统一分辨率
        w, h = target_res
        vf = f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2'
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'mpegts', '-fflags', '+genpts',
            str(output_ts)
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ 转换失败：{input_file}\n错误信息：{result.stderr}")
        return False
    return True


def concat_videos_safe(video_files: List[Path], output_path: Path,
                       uniform_res: Optional[Tuple[int, int]] = None) -> None:
    """
    安全拼接模式：先将每个视频转为 TS（可选重编码），然后合并所有 TS，最后转封装为目标格式。

    参数:
        video_files: 按顺序排列的视频文件列表
        output_path: 最终输出文件路径
        uniform_res: 统一分辨率（None 表示不重编码）
    """
    temp_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    ts_files = []

    try:
        print("🔄 正在转换视频为 TS 格式...")
        for idx, vf in enumerate(video_files):
            ts_file = Path(temp_dir) / f"part_{idx:04d}.ts"
            print(f"   处理 {vf.name} -> {ts_file.name}")
            if not convert_to_ts(vf, ts_file, uniform_res):
                raise RuntimeError(f"转换 {vf.name} 失败")
            ts_files.append(ts_file)

        list_file = Path(temp_dir) / "concat_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for ts_file in ts_files:
                escaped = str(ts_file.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        merged_ts = Path(temp_dir) / "merged.ts"
        cmd_concat = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(list_file), '-c', 'copy', str(merged_ts)
        ]
        print("🔗 正在合并 TS 片段...")
        subprocess.run(cmd_concat, capture_output=True, text=True, check=True)

        print(f"📦 正在转封装为最终格式：{output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd_final = ['ffmpeg', '-y', '-i', str(merged_ts), '-c', 'copy', str(output_path)]
        subprocess.run(cmd_final, capture_output=True, text=True, check=True)

        print(f"✅ 拼接成功！输出文件：{output_path}")

    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg 命令执行失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 拼接过程中出错：{e}")
        sys.exit(1)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    """命令行入口：解析参数、收集文件、处理交互、执行拼接。"""
    parser = argparse.ArgumentParser(
        description="视频拼接工具（默认快速拼接，需确认才重编码）",
        epilog="示例：\n  %(prog)s *.mp4 -o merged.mp4\n  %(prog)s --resample *.mp4"
    )
    parser.add_argument('inputs', nargs='*', default=['.'],
                        help='要拼接的视频文件或目录（可多个，默认为当前目录）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT,
                        help=f'输出文件路径（默认 {DEFAULT_OUTPUT}）')
    parser.add_argument('-e', '--extensions', nargs='+', default=list(DEFAULT_EXTENSIONS),
                        help=f'支持的视频扩展名（默认 {", ".join(DEFAULT_EXTENSIONS)}）')
    parser.add_argument('--no-check', action='store_true',
                        help='跳过分辨率一致性检查（不检测也不警告）')
    parser.add_argument('--resample', action='store_true',
                        help='强制重新编码以统一分辨率（自动选择目标分辨率，优先横屏）')
    parser.add_argument('--uniform-resolution', nargs='?', const='auto', default=None,
                        help='手动指定统一分辨率（例如 1920x1080），会触发重新编码；使用 auto 表示自动选择')
    parser.add_argument('--yes', action='store_true',
                        help='跳过交互确认（用于脚本），分辨率不一致时自动采用快速拼接')

    args = parser.parse_args()

    extensions = {ext.lower() for ext in args.extensions}

    print("🔍 正在收集视频文件...")
    video_files = collect_video_files(args.inputs, extensions)
    if not video_files:
        print("❌ 错误：未找到任何支持的视频文件。请检查路径和扩展名。")
        sys.exit(1)

    print(f"📁 找到 {len(video_files)} 个视频文件，按名称升序排列：")
    for i, vf in enumerate(video_files, 1):
        print(f"   {i}. {vf.name}")

    consistent = True
    if not args.no_check:
        consistent = check_resolution_consistency(video_files)
        if not consistent:
            print("⚠️ 警告：输入视频的分辨率不一致。")
            if not (args.resample or args.uniform_resolution):
                print("   默认采用无损快速拼接（输出元数据可能不准确，但播放正常）。")
                if not args.yes:
                    answer = input("   是否重新编码以统一分辨率？(y/N) [默认 N]: ").strip().lower()
                    if answer == 'y':
                        args.resample = True
                        print("✅ 已启用重编码模式，将统一分辨率。")
                    else:
                        print("⏩ 继续使用快速拼接模式。")
                else:
                    print("   (由于 --yes 参数，跳过询问，使用快速拼接模式)")

    target_res = None
    if args.resample:
        target_res = get_target_resolution(video_files)
        print(f"📐 启用重编码，目标分辨率：{target_res[0]}x{target_res[1]}")
    elif args.uniform_resolution is not None:
        if args.uniform_resolution == 'auto':
            target_res = get_target_resolution(video_files)
            print(f"📐 根据 --uniform-resolution=auto 计算得到统一分辨率：{target_res[0]}x{target_res[1]}")
        else:
            match = re.match(r'(\d+)[xX](\d+)', args.uniform_resolution)
            if match:
                target_res = (int(match.group(1)), int(match.group(2)))
                print(f"📐 使用手动指定分辨率：{target_res[0]}x{target_res[1]}")
            else:
                print("❌ 分辨率格式错误，应为 WxH，例如 1920x1080")
                sys.exit(1)

    concat_videos_safe(video_files, Path(args.output), uniform_res=target_res)


if __name__ == '__main__':
    main()
