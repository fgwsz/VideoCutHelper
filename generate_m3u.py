#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
项目名称：M3U 播放列表生成器 (generate_m3u.py)
================================================================================

1. 项目简介
-----------
本脚本用于自动扫描指定目录下的视频文件，生成符合 M3U 标准的播放列表文件。
它能够快速将大量分散在文件夹中的视频组织成一个可供 VLC、MPV 等播放器
直接加载的播放列表，极大简化了多媒体文件的批量管理流程。

2. 主要功能
-----------
- 支持用户指定工作目录（绝对或相对路径），默认使用当前目录。
- 默认仅扫描当前目录（不递归子目录），可通过 `-r` 选项启用递归。
- 按文件名的字典序升序排序，确保文件名最大的条目在播放列表中排在最后。
- 输出 M3U 文件中的路径采用相对于工作目录的格式，且统一使用正斜杠（/）
  以兼容跨平台播放器。
- 允许用户通过 `--extensions` 自定义视频文件扩展名（覆盖默认列表）。
- 默认生成的文件（未指定 `-o`）自动放在用户输入的目录下，而不是当前目录。
- 输出文件强制使用 UTF‑8 编码，完美支持中文等多字节字符，避免编码错误。
- 提供完善的命令行参数解析与错误提示，操作友好。

3. 命令行用法
---------------
python generate_m3u.py [目录路径] [选项]

参数说明：
  directory               工作目录路径（可选，默认为当前目录 `.`）
  -r, --recursive         递归搜索所有子目录中的视频文件
  -o, --output FILE       输出 M3U 文件名（默认在输入目录下生成 playlist.m3u）
                          若指定，则按该路径生成（相对路径相对于当前工作目录）
  --extensions EXT        自定义视频扩展名，逗号分隔，如 `.mp4,.mkv,.ts`
                          若指定则完全覆盖默认扩展名集合。
  -h, --help              显示帮助信息并退出

4. 使用示例
---------------
  # 扫描当前目录（非递归），在 ./ 下生成 playlist.m3u
  python generate_m3u.py

  # 扫描指定目录 D:\Videos（非递归），在 D:\Videos\ 下生成 playlist.m3u
  python generate_m3u.py "D:\Videos"

  # 递归扫描当前目录及其所有子目录
  python generate_m3u.py -r

  # 递归扫描，输出到自定义位置（相对路径，相对于当前目录）
  python generate_m3u.py -r -o mylist.m3u

  # 仅匹配 .mp4 和 .mkv 文件，递归扫描，输出到 /tmp/videos.m3u（绝对路径）
  python generate_m3u.py -r --extensions .mp4,.mkv -o /tmp/videos.m3u

5. 支持的视频扩展名（默认）
-------------------------------
.mp4, .mkv, .avi, .mov, .flv, .wmv, .webm, .m4v, .mpg, .mpeg,
.ts, .m2ts, .3gp, .ogv, .rmvb, .vob

6. 依赖与环境
---------------
- Python 3.6 或更高版本（仅使用标准库：os, argparse, pathlib）
- 无任何第三方库依赖，可直接运行于 Windows / macOS / Linux。

7. 输出说明
---------------
- 生成的文件编码为 UTF-8，兼容中文文件名。
- M3U 文件中的路径为相对于工作目录的相对路径，便于播放列表与视频文件
  整体移动时保持引用有效。
- 路径分隔符统一使用 `/`（正斜杠），确保跨平台兼容性。
- 如果未通过 `-o` 指定输出文件，则默认在用户输入的目录下生成 `playlist.m3u`。

8. 错误处理
---------------
- 若指定的目录不存在，脚本会报错并退出。
- 若未找到任何匹配的视频文件，脚本给出警告但正常退出（不生成文件）。
- 若输出路径的目录不存在，脚本会自动创建。

9. 版本与更新
---------------
版本：1.1.0
创建日期：2026-06-18
作者：DeepSeek AI 助手
更新日志：
  - v1.1.0 (2026-06-18)：默认输出文件路径改为用户输入目录，强制 UTF-8 编码。
  - v1.0.0 (2026-06-18)：初始版本，实现基本扫描、排序、生成功能。

10. 注意事项
----------------
- 若视频文件分布在多个子目录，建议使用 `-r` 递归选项，否则只会扫描顶层。
- 若文件数量极大（数万个），递归遍历可能较慢，请耐心等待。
- 扩展名匹配不区分大小写（自动转为小写比较）。
- 若同时存在同名但不同扩展名的文件，它们都会被视为独立条目。

================================================================================
"""

import os
import argparse
from pathlib import Path

# -----------------------------------------------------------------------------
# 常量定义
# -----------------------------------------------------------------------------

DEFAULT_VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv',
    '.webm', '.m4v', '.mpg', '.mpeg', '.ts', '.m2ts',
    '.3gp', '.ogv', '.rmvb', '.vob'
}

# -----------------------------------------------------------------------------
# 核心功能函数
# -----------------------------------------------------------------------------

def is_video_file(filename: str, extensions: set) -> bool:
    """
    判断文件名是否为视频文件（基于扩展名匹配）。

    Args:
        filename (str): 文件名（可包含路径）
        extensions (set): 允许的视频扩展名集合（小写，含点号）

    Returns:
        bool: 如果扩展名在集合中返回 True，否则 False。

    Examples:
        >>> is_video_file('movie.mp4', {'.mp4', '.mkv'})
        True
        >>> is_video_file('doc.txt', {'.mp4'})
        False
    """
    ext = os.path.splitext(filename)[1].lower()
    return ext in extensions


def collect_video_files(root_dir: str, recursive: bool, extensions: set) -> list:
    """
    收集指定目录下的视频文件路径（相对于 root_dir 的相对路径）。

    Args:
        root_dir (str): 根目录路径（绝对路径或相对路径，将被解析为绝对路径）
        recursive (bool): 是否递归扫描子目录
        extensions (set): 用于过滤视频文件的扩展名集合

    Returns:
        list: 视频文件相对于 root_dir 的相对路径列表（字符串），
              按文件名升序排序（字典序，忽略路径）。

    Raises:
        ValueError: 当 root_dir 不存在或不是目录时抛出。

    Examples:
        >>> collect_video_files('.', False, {'.mp4'})  # 假设当前目录有 a.mp4, b.mp4
        ['a.mp4', 'b.mp4']  # 排序后
    """
    root = Path(root_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"目录不存在或不是目录: {root_dir}")

    video_files = []

    if recursive:
        # 递归遍历所有子目录
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if is_video_file(fname, extensions):
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, start=root)
                    video_files.append(rel_path)
    else:
        # 仅扫描当前目录
        for item in root.iterdir():
            if item.is_file() and is_video_file(item.name, extensions):
                video_files.append(item.name)  # 相对路径 = 文件名

    # 按文件名升序排序（保持稳定）
    video_files.sort(key=lambda p: os.path.basename(p))
    return video_files


def write_m3u(video_files: list, output_path: str, root_dir: str) -> None:
    """
    将视频文件列表写入 M3U 格式的文件。

    Args:
        video_files (list): 相对路径字符串列表（相对于 root_dir）
        output_path (str): 输出 M3U 文件的路径（可以是相对或绝对路径）
        root_dir (str): 工作目录（仅用于提示信息）

    Returns:
        None

    Raises:
        OSError: 当文件写入失败时抛出（如权限不足、磁盘满等）。

    Note:
        - 文件编码为 UTF-8，确保中文字符无乱码。
        - 路径中的反斜杠会被统一替换为正斜杠，以确保跨平台兼容性（VLC 支持正斜杠）。
        - 如果输出目录不存在，会自动创建。
    """
    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(output_path, 'w', encoding='utf-8') as f:
        for rel_path in video_files:
            # 统一路径分隔符为 POSIX 风格（正斜杠）
            posix_path = rel_path.replace('\\', '/')
            f.write(posix_path + '\n')

    print(f"✅ 播放列表已生成: {os.path.abspath(output_path)}")
    print(f"   包含 {len(video_files)} 个视频文件，工作目录: {root_dir}")


def parse_extensions(ext_str: str) -> set:
    """
    解析用户输入的扩展名字符串为集合。

    Args:
        ext_str (str): 逗号分隔的扩展名，如 ".mp4,.mkv,.avi"

    Returns:
        set: 小写的扩展名集合（包含点号），例如 {'.mp4', '.mkv', '.avi'}

    Raises:
        ValueError: 当扩展名格式不正确时抛出（如未以点开头）。

    Examples:
        >>> parse_extensions('.mp4,.mkv')
        {'.mp4', '.mkv'}
        >>> parse_extensions('mp4')   # 缺少点号
        ValueError: 扩展名必须以点开头: 'mp4'
    """
    if not ext_str:
        return set()
    ext_list = [ext.strip().lower() for ext in ext_str.split(',') if ext.strip()]
    for ext in ext_list:
        if not ext.startswith('.'):
            raise ValueError(f"扩展名必须以点开头: '{ext}'")
    return set(ext_list)


# -----------------------------------------------------------------------------
# 命令行入口
# -----------------------------------------------------------------------------

def main() -> int:
    """
    主函数，解析命令行参数并执行生成任务。

    Returns:
        int: 程序退出码，0 表示成功，非 0 表示失败。

    Process:
        1. 解析命令行参数。
        2. 处理扩展名（若用户自定义则覆盖默认）。
        3. 检查工作目录是否存在。
        4. 确定输出路径：若未指定 -o，则在输入目录下生成 playlist.m3u。
        5. 收集视频文件列表。
        6. 生成并写入 M3U 文件。
        7. 输出结果或错误信息。
    """
    parser = argparse.ArgumentParser(
        description="生成 M3U 播放列表，扫描指定目录下的视频文件。"
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='视频文件所在目录（默认为当前目录）'
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='递归搜索子目录中的视频文件'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='输出的 M3U 文件名（默认在输入目录下生成 playlist.m3u）'
    )
    parser.add_argument(
        '--extensions',
        help='自定义视频扩展名，逗号分隔（如 .mp4,.mkv），覆盖默认列表'
    )
    args = parser.parse_args()

    # 处理扩展名
    if args.extensions:
        try:
            extensions = parse_extensions(args.extensions)
        except ValueError as e:
            print(f"❌ 扩展名格式错误: {e}")
            return 1
        if not extensions:
            print("❌ 错误：扩展名列表为空")
            return 1
    else:
        extensions = DEFAULT_VIDEO_EXTENSIONS

    # 解析工作目录
    try:
        root_dir = os.path.abspath(args.directory)
        if not os.path.isdir(root_dir):
            print(f"❌ 错误：目录 '{root_dir}' 不存在")
            return 1
    except Exception as e:
        print(f"❌ 无法解析目录: {e}")
        return 1

    # 确定输出路径
    if args.output is None:
        # 未指定 -o，默认在输入目录下生成 playlist.m3u
        output_path = os.path.join(root_dir, 'playlist.m3u')
    else:
        # 用户指定了输出路径，直接使用（相对路径相对于当前工作目录）
        output_path = args.output

    # 收集视频文件
    try:
        video_files = collect_video_files(root_dir, args.recursive, extensions)
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return 1

    if not video_files:
        print(f"⚠️  在 '{root_dir}' 中未找到任何视频文件（扩展名: {extensions}）")
        return 0

    # 写入 M3U 文件
    try:
        write_m3u(video_files, output_path, root_dir)
        return 0
    except Exception as e:
        print(f"❌ 写入播放列表失败: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
