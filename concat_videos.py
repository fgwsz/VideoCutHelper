#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
FFmpeg 视频无损拼接工具 v5.1 (优化尾部裁剪速度)
================================================================================

📖 项目简介
------------
这是一个基于 FFmpeg 的 Python 脚本，用于按文件名升序自动拼接多个视频文件。
核心特点：
  - 默认无损快速拼接：采用 MPEG-TS 中转 + 流拷贝技术，不重新编码，秒级完成。
  - 智能处理分辨率差异：当视频分辨率不一致时，仅警告并询问是否重编码（默认不重编码）。
  - 可选分辨率统一：支持自动或手动指定目标分辨率，重新编码后获得元数据准确的输出文件。
  - 尾部裁剪：支持从每个视频的末尾裁剪掉指定时长（例如去除片尾）。
      * 默认使用快速模式（流拷贝，基于关键帧），速度极快，但裁剪点可能不精确（±几帧）。
      * 可使用 --exact-trim 启用精确裁剪（重新编码），速度较慢但帧精确。
  - 跨平台支持：Windows / macOS / Linux。

✨ 新增功能说明
----------------
--trim-end DURATION  从每个视频末尾裁剪掉指定时长。
                     默认采用快速模式（流拷贝），只移动关键帧，不重新编码。
--exact-trim         与 --trim-end 同时使用时，启用精确裁剪（重新编码），确保精确到帧。

📋 命令行参数更新
-----------------
  --trim-end DURATION   从每个视频末尾裁剪掉指定时长（例如 5 或 00:00:05）
  --exact-trim          使用精确裁剪（重新编码），默认为快速裁剪（流拷贝）

使用示例：
  # 快速裁剪每个视频末尾5秒后拼接（速度快，可能不精确）
  python concat_videos.py *.mp4 --trim-end 5 -o trimmed.mp4

  # 精确裁剪末尾5秒（慢，但精确到帧）
  python concat_videos.py *.mp4 --trim-end 5 --exact-trim

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
def parse_duration(duration_str: str) -> float:
    """解析时长字符串，返回秒数。支持秒数或 HH:MM:SS.msec 格式。"""
    duration_str = duration_str.strip()
    try:
        return float(duration_str)
    except ValueError:
        pass
    match = re.match(r'^(\d{1,2}):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$', duration_str)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        s = float(match.group(3))
        return h * 3600 + m * 60 + s
    raise ValueError(f"无法解析时长格式: {duration_str}，请使用秒数或 HH:MM:SS.msec 格式")


def get_video_duration(file_path: Path) -> Optional[float]:
    """使用 ffprobe 获取视频时长（秒）。"""
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
            print(f"⚠️ 警告：未知类型，已忽略 - {p}")
    video_files.sort(key=lambda x: x.name)
    return video_files


def get_video_stream_info(file_path: Path) -> Optional[Dict[str, str]]:
    """使用 ffprobe 获取视频流的编码信息。"""
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


def get_all_resolutions(video_files: List[Path]) -> List[Optional[Tuple[int, int]]]:
    """获取所有视频文件的分辨率列表。"""
    resolutions = []
    for vf in video_files:
        info = get_video_stream_info(vf)
        if info and 'width' in info and 'height' in info:
            resolutions.append((int(info['width']), int(info['height'])))
        else:
            resolutions.append(None)
    return resolutions


def check_resolution_consistency(video_files: List[Path]) -> bool:
    """检查所有视频的分辨率是否完全一致。"""
    res_list = get_all_resolutions(video_files)
    unique_res = set(r for r in res_list if r is not None)
    return len(unique_res) <= 1


def get_target_resolution(video_files: List[Path]) -> Tuple[int, int]:
    """根据视频方向自动确定目标分辨率（优先采用横屏最大分辨率）。"""
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


def convert_to_ts(input_file: Path, output_ts: Path,
                  target_res: Optional[Tuple[int, int]] = None,
                  trim_end: Optional[float] = None,
                  exact_trim: bool = False) -> Tuple[bool, float]:
    """
    将单个视频文件转换为 MPEG-TS 格式。
    返回 (成功标志, 输出文件时长)。
    """
    output_duration = 0.0

    need_reencode = (target_res is not None) or (trim_end is not None and exact_trim)

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
        # 修复时间戳问题：添加 -copyts -start_at_zero
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-c', 'copy',
            '-copyts',          # 保留输入时间戳
            '-start_at_zero',   # 从 0 开始重新计算时间戳
            '-f', 'mpegts',
            str(output_ts)
        ]
        print(f"   🔧 执行快速裁剪命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ 快速裁剪失败：{input_file}\n{result.stderr}")
            return False, 0.0
        # 验证输出时长
        out_duration = get_video_duration(output_ts)
        if out_duration is None:
            print(f"⚠️ 无法获取裁剪后文件的时长")
        else:
            output_duration = out_duration
            if abs(out_duration - trim_duration) > 0.5:
                print(f"⚠️ 时长验证异常: 期望 {trim_duration:.2f}s, 实际 {out_duration:.2f}s")
        return True, output_duration

    # 无损流拷贝模式（无裁剪、无重编码）
    if not need_reencode:
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

    # 重新编码模式（裁剪或/和缩放）
    duration = get_video_duration(input_file)
    if duration is None:
        print(f"❌ 无法获取 {input_file.name} 的时长")
        return False, 0.0
    trim_duration = duration - trim_end if trim_end else duration
    if trim_duration <= 0:
        print(f"⚠️ 警告：{input_file.name} 裁剪时长超过视频本身，跳过")
        return False, 0.0
    print(f"   📊 原始时长: {duration:.2f}s, 重新编码后时长: {trim_duration:.2f}s")

    if target_res is None:
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'mpegts', '-fflags', '+genpts',
            str(output_ts)
        ]
    else:
        w, h = target_res
        vf = f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2'
        cmd = [
            'ffmpeg', '-i', str(input_file),
            '-ss', '0',
            '-t', str(trim_duration),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
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
                       exact_trim: bool = False) -> None:
    """安全拼接模式，支持快速/精确裁剪，并验证总时长。"""
    temp_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    ts_files = []
    expected_total_duration = 0.0

    try:
        print("🔄 正在转换视频为 TS 格式...")
        for idx, vf in enumerate(video_files):
            ts_file = Path(temp_dir) / f"part_{idx:04d}.ts"
            print(f"   处理 {vf.name} -> {ts_file.name}")
            success, duration = convert_to_ts(vf, ts_file, uniform_res, trim_end, exact_trim)
            if not success:
                raise RuntimeError(f"转换 {vf.name} 失败")
            ts_files.append(ts_file)
            expected_total_duration += duration

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
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
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
                        help='跳过分辨率一致性检查')
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

    extensions = {ext.lower() for ext in args.extensions}
    print("🔍 正在收集视频文件...")
    video_files = collect_video_files(args.inputs, extensions)
    if not video_files:
        print("❌ 未找到任何视频文件")
        sys.exit(1)

    print(f"📁 找到 {len(video_files)} 个文件，按名称排序：")
    for i, vf in enumerate(video_files, 1):
        print(f"   {i}. {vf.name}")

    consistent = True
    need_reencode = (args.resample or args.uniform_resolution or (trim_seconds is not None and args.exact_trim))
    if not args.no_check:
        consistent = check_resolution_consistency(video_files)
        if not consistent:
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

    concat_videos_safe(video_files, Path(args.output),
                       uniform_res=target_res,
                       trim_end=trim_seconds,
                       exact_trim=args.exact_trim)


if __name__ == '__main__':
    main()
