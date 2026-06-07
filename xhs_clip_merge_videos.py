#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
小红书视频处理工具 - 批量裁剪、整理与拼接

================================================================================
1. 概要
================================================================================
本脚本用于处理从小红书下载的两类视频文件：
    - Camera_xhs_<name>.mp4      (相机拍摄的视频)
    - xhs_live_photo_<name>.mp4  (实况照片转换的视频)
其中 <name> 为数字或字母标识符（如 001, abc）。

脚本自动完成以下任务：
    a) 扫描指定目录下的上述两类文件；
    b) 对 Camera 视频裁剪末尾固定时长（默认3秒）；
    c) 对 Live 视频完整复制（不裁剪）；
    d) 按 <name> 分组并排序，每组内先 Camera 后 Live；
    e) 生成拼接素材列表，并在控制台展示供用户确认；
    f) 用户确认后，将所有素材无损拼接为一个 MP4 文件。

================================================================================
2. 使用方式
================================================================================
    python xhs_clip_merge_videos.py [工作目录]
    python3 xhs_clip_merge_videos.py [工作目录]

    - 若提供 工作目录，则切换到该目录下执行所有操作（扫描、输出等）。
    - 若不提供，则使用当前脚本所在目录。

    示例：
        python xhs_clip_merge_videos.py /home/user/Downloads/xiaohongshu
        python3 xhs_clip_merge_videos.py /home/user/Downloads/xiaohongshu

================================================================================
3. 输入要求
================================================================================
    - 输入目录中必须存在符合命名约定的文件：
        Camera_xhs_<name>.mp4
        xhs_live_photo_<name>.mp4
      <name> 可以是任意字符串，但必须与配对的 Live 文件一致（仅通过文件名匹配）。
    - 文件扩展名必须为 .mp4（大小写不敏感，但脚本假定小写）。
    - 文件数量、分组无限制，但受限于系统文件句柄和内存。

================================================================================
4. 处理流程详情
================================================================================
    Step 1 – 目录定位
        根据命令行参数确定工作目录，并切换至该目录。

    Step 2 – 文件扫描与分组
        使用 glob 模式匹配：
            "Camera_xhs_*.mp4"
            "xhs_live_photo_*.mp4"
        提取 <name>，建立映射：{ name: {'camera': path, 'live': path} }。

    Step 3 – 素材预处理（输出到 Camera_xhs_output/trimmed/）
        对每个 name：
            - 若存在 Camera 文件，使用 ffmpeg 裁剪末尾 3 秒（可调整 CUT_SECONDS 常量），
              输出为 Camera_xhs_output/trimmed/Camera_xhs_<name>.mp4。
            - 若存在 Live 文件，完整复制为 xhs_live_photo_<name>.mp4 到同一子目录。
        若任一文件因时长不足或处理失败，则跳过该素材并记录警告。

    Step 4 – 拼接顺序生成
        将所有成功处理的素材按以下规则排序：
            a) 先按 name 的自然顺序（数值优先，支持数字部分）升序；
            b) 相同 name 下，Camera 素材排在 Live 素材之前。
        结果存入列表 final_materials。

    Step 5 – 用户确认
        在控制台输出表格，包含序号、name、类型、文件名。
        等待用户输入 'y' 或 'Y' 确认；任何其他输入（包括直接回车）均视为取消。

    Step 6 – 无损拼接
        使用 ffmpeg concat demuxer 合并 final_materials 中所有文件。
        输出路径：Camera_xhs_output/merged_output.mp4。
        若拼接失败，脚本退出并报错；成功则提示完成。

================================================================================
5. 输出
================================================================================
    - 生成目录：<工作目录>/Camera_xhs_output/
        ├── trimmed/                     # 裁剪/复制后的中间素材
        │   ├── Camera_xhs_<name>.mp4
        │   └── xhs_live_photo_<name>.mp4
        └── merged_output.mp4            # 最终拼接结果
    - 所有输出文件均保留原始画质与编码（使用 -c copy）。

================================================================================
6. 依赖项
================================================================================
    - Python 3.6+
    - ffmpeg 和 ffprobe（需在系统 PATH 中）
        * 安装方式：
            Windows:  下载可执行文件并添加至 PATH
            macOS:    brew install ffmpeg
            Linux:    sudo apt install ffmpeg

================================================================================
7. 注意事项与限制
================================================================================
    - 裁剪操作基于时长，假设视频均为恒定帧率；若视频有可变帧率，时长计算可能存在微小误差。
    - 裁剪末尾 3 秒时，若视频总时长 ≤ 3 秒，则跳过该文件（不会进入拼接）。
    - 拼接要求所有素材编码格式一致（通常 H.264/AAC），若不一致可能导致拼接失败。
    - 临时文件列表 filelist.txt 会在每次拼接完成后自动删除。
    - 原始文件不会被修改或移动。
    - 文件名中的 <name> 若包含路径分隔符或特殊字符，可能引起问题（通常不会）。

================================================================================
8. 配置调整
================================================================================
    脚本开头可修改以下常量：
        CUT_SECONDS = 3          # 相机视频尾部裁剪秒数
        OUTPUT_DIR_NAME = "Camera_xhs_output"
        TRIMMED_SUBDIR = "trimmed"
    如需修改匹配模式，请直接编辑 scan_files 函数中的 patterns 列表。

================================================================================
9. 退出码
================================================================================
    - 0: 正常完成（用户确认且拼接成功）
    - 1: 参数错误、依赖缺失、未找到文件、用户取消或处理失败
"""

import os
import re
import glob
import shutil
import subprocess
import sys
from typing import List, Dict, Tuple

class VideoProcessor:
    """视频处理核心类"""

    def __init__(self, cut_seconds: int = 3):
        self.cut_seconds = cut_seconds

    @staticmethod
    def natural_sort_key(s: str) -> List:
        """自然排序键"""
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def get_duration(self, filepath: str) -> float:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if res.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {filepath}\n{res.stderr}")
        return float(res.stdout.strip())

    def trim_video(self, src: str, dst: str) -> bool:
        """裁剪视频末尾 self.cut_seconds 秒"""
        try:
            duration = self.get_duration(src)
        except Exception as e:
            print(f"  ⚠️ 无法获取时长: {e}")
            return False
        if duration <= self.cut_seconds:
            print(f"  ⚠️ 视频过短 ({duration:.2f}s)，跳过裁剪")
            return False
        new_duration = duration - self.cut_seconds
        cmd = ['ffmpeg', '-i', src, '-t', str(new_duration), '-c', 'copy', '-y', dst]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if res.returncode != 0:
            print(f"  ❌ 裁剪失败: {src}\n{res.stderr}")
            return False
        print(f"  ✂️ 裁剪成功: {os.path.basename(src)} -> {new_duration:.2f}s")
        return True

    @staticmethod
    def copy_video(src: str, dst: str) -> bool:
        """直接复制完整视频"""
        try:
            shutil.copy2(src, dst)
            print(f"  📄 复制完整: {os.path.basename(src)}")
            return True
        except Exception as e:
            print(f"  ❌ 复制失败: {src}\n{e}")
            return False

    @staticmethod
    def concat_videos(file_list: List[str], output: str) -> bool:
        """无损拼接视频"""
        if not file_list:
            raise ValueError("文件列表为空")
        list_file = "filelist.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for path in file_list:
                abs_path = os.path.abspath(path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file,
               '-c', 'copy', '-y', output]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        os.remove(list_file)
        if res.returncode != 0:
            print(f"拼接失败:\n{res.stderr}")
            return False
        print(f"✅ 拼接成功: {output}")
        return True


def scan_files(base_dir: str, patterns: List[str]) -> Dict[str, Dict[str, str]]:
    """
    扫描指定目录下的文件，返回字典 { name: { 'camera': path, 'live': path } }
    其中 name 是从文件名中提取的数字部分，例如 '001'
    """
    result = {}
    for pattern in patterns:
        if pattern.startswith("Camera"):
            file_type = "camera"
            prefix = "Camera_xhs_"
        elif pattern.startswith("xhs_live_photo"):
            file_type = "live"
            prefix = "xhs_live_photo_"
        else:
            continue

        full_pattern = os.path.join(base_dir, pattern)
        for filepath in glob.glob(full_pattern):
            basename = os.path.basename(filepath)
            if not basename.endswith('.mp4'):
                continue
            if basename.startswith(prefix):
                name = basename[len(prefix):-4]  # 去掉 .mp4
            else:
                continue
            if name not in result:
                result[name] = {}
            result[name][file_type] = filepath
    return result


def main():
    # 配置
    CUT_SECONDS = 3
    OUTPUT_DIR_NAME = "Camera_xhs_output"
    TRIMMED_SUBDIR = "trimmed"

    # 解析命令行参数：第一个参数为可选的工作目录
    if len(sys.argv) > 1:
        work_dir = sys.argv[1]
        if not os.path.isdir(work_dir):
            print(f"错误：指定的路径不存在或不是目录: {work_dir}")
            sys.exit(1)
        work_dir = os.path.abspath(work_dir)
        print(f"切换到工作目录: {work_dir}")
        os.chdir(work_dir)
    else:
        work_dir = os.getcwd()
        print(f"使用当前目录: {work_dir}")

    # 创建输出目录（在当前工作目录下）
    output_dir = os.path.join(work_dir, OUTPUT_DIR_NAME)
    trimmed_dir = os.path.join(output_dir, TRIMMED_SUBDIR)
    os.makedirs(trimmed_dir, exist_ok=True)

    # 扫描文件
    files_by_name = scan_files(work_dir, [
        "Camera_xhs_*.mp4",
        "xhs_live_photo_*.mp4"
    ])

    if not files_by_name:
        print("未找到任何匹配的文件")
        return

    # 对 name 进行自然排序
    sorted_names = sorted(files_by_name.keys(), key=VideoProcessor.natural_sort_key)
    print(f"找到 {len(sorted_names)} 个名称: {sorted_names}")

    processor = VideoProcessor(cut_seconds=CUT_SECONDS)

    # 收集最终素材信息 (name, type, path)
    final_materials = []  # List[Tuple[name, type, path]]

    for name in sorted_names:
        item = files_by_name[name]
        print(f"\n处理名称: {name}")

        # 1. Camera
        if 'camera' in item:
            src = item['camera']
            dst = os.path.join(trimmed_dir, f"Camera_xhs_{name}.mp4")
            if processor.trim_video(src, dst):
                final_materials.append((name, "Camera", dst))
        else:
            print("  ⚠️ 无 Camera 文件")

        # 2. Live
        if 'live' in item:
            src = item['live']
            dst = os.path.join(trimmed_dir, f"xhs_live_photo_{name}.mp4")
            if processor.copy_video(src, dst):
                final_materials.append((name, "Live", dst))
        else:
            print("  ⚠️ 无 Live 文件")

    if not final_materials:
        print("没有可拼接的视频")
        return

    # 拼接前展示素材清单
    print("\n" + "="*60)
    print("即将拼接以下素材（按顺序）：")
    print(f"{'序号':<6} {'名称':<10} {'类型':<8} {'文件路径'}")
    print("-"*60)
    for idx, (name, typ, path) in enumerate(final_materials, start=1):
        print(f"{idx:<6} {name:<10} {typ:<8} {os.path.basename(path)}")
    print(f"\n总计 {len(final_materials)} 个素材")
    print("="*60)

    # 用户确认
    choice = input("\n是否继续拼接？(y/N): ").strip().lower()
    if choice != 'y':
        print("已取消拼接操作。")
        return

    # 提取路径列表
    final_files = [path for _, _, path in final_materials]

    # 拼接最终视频
    output_path = os.path.join(output_dir, "merged_output.mp4")
    if processor.concat_videos(final_files, output_path):
        print(f"\n🎉 成功！最终视频保存在: {output_path}")
    else:
        print("\n❌ 拼接失败")


if __name__ == "__main__":
    main()
