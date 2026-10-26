#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
clean_duplicate_videos.py — 清理目录中的重复视频，保留画质最好的版本
================================================================================

一、功能概述
--------------------------------------------------------------------------------
扫描指定目录（默认递归），自动找出"时长相同、内容相同但画质不同"的重复视频，
在每一组重复中保留画质最好的版本，其余标记为待清理。

核心流程：
    1. ffprobe 读取每个视频的时长、分辨率、编码、码率。
    2. 按时长分桶（时长差 <= --duration-tol 秒）。
    3. 桶内视频在多个时间点抽帧，计算 dHash（差值哈希），
       用汉明距离判断是否为"同一内容的不同版本"。
    4. 对内容相同的子组，按 (像素数, 每像素码率 x 编码效率系数) 打分，
       保留最高分，其余标记为待清理。
    5. 默认 dry-run 只打印计划；加 --execute 才真正删除或移动到隔离目录。

特点：
    * 不会仅凭"文件大小"判断画质 —— 避免 4K 低码率 vs 1080p 高码率、
      HEVC vs H264 等场景的误判。
    * 抽帧比对，避免把时长接近但内容不同的视频误删。
    * 支持把待删文件移动到隔离目录，事后可恢复。
    * 支持导出清理计划为 JSON，便于外部审阅。
    * 抽帧失败的视频会被自动排除在比较之外，绝不会被误删。


二、依赖与安装
--------------------------------------------------------------------------------
    1) Python 3.8+
    2) Pillow:
           pip install pillow
    3) ffmpeg / ffprobe 必须在 PATH 中：
           - macOS:    brew install ffmpeg
           - Ubuntu:   sudo apt install ffmpeg
           - Windows:  从 https://ffmpeg.org/download.html 下载后加入 PATH


三、快速开始（推荐顺序）
--------------------------------------------------------------------------------
    第一步 · 预览（不会删除任何文件）:
        python clean_duplicate_videos.py "/path/to/videos"

    第二步 · 安全清理（把待删文件移到隔离目录，事后确认没问题再手动删）:
        python clean_duplicate_videos.py "/path/to/videos" --execute \
               --quarantine /tmp/video_trash

    第三步 · 直接删除（确认预览无误后再用）:
        python clean_duplicate_videos.py "/path/to/videos" --execute -y

    提示：建议永远先跑一次预览，人工核对"保留/清理"的选择是否合理。


四、命令行参数
--------------------------------------------------------------------------------
    位置参数:
        directory
            要扫描的目录。必填。

    执行控制:
        --execute
            真正执行删除或移动。不加则只打印计划（dry-run）。
        --yes, -y
            执行时跳过交互确认。适合脚本化调用，请确认预览无误后再用。
        --quarantine DIR
            把待清理文件移动到 DIR（保留相对原根目录的子路径），
            而不是直接删除。推荐使用，可随时恢复。

    判定参数:
        --duration-tol SEC     (默认 1.0)
            时长分桶容差。两个视频时长差 <= 该值才会进入同一比较桶。
            存在 0.5s 以内偏差的转码版本保持默认即可。

        --hash-tol N           (默认 8)
            dHash 汉明距离阈值（64 位哈希）。越小越严格。
            同源视频一般 0-4；6 更严格；12 更宽松。

        --frames N             (默认 4)
            每个视频抽样帧数。内容变化剧烈的视频可加到 6-8。
            抽样点均分布在中间 80% 区域，避开片头片尾。

    性能与过滤:
        --jobs N               (默认 min(8, CPU 核数))
            ffprobe / ffmpeg 抽帧的并发数。
        --min-size BYTES       (默认 0)
            忽略小于该字节数的文件。例如 --min-size 10485760 跳过 10MB 以下。
        --no-recursive
            不递归子目录，只处理 directory 顶层。

    输出:
        --json FILE
            把清理计划导出为 JSON（含每个文件的路径、分辨率、编码、
            码率、大小、时长），便于外部审阅或二次处理。
        --help, -h
            查看帮助。


五、画质判定逻辑
--------------------------------------------------------------------------------
保留谁？排序键为三元组：
    (像素数, 每像素码率 x 编码效率系数, 文件大小)

    1. 先比分辨率 —— 高分辨率通常意味着更多细节。
    2. 同分辨率再比 bpp = bitrate / (width x height) —— 每像素信息量越大，
       压缩伪影越少。
    3. 乘以编码效率系数 —— 同码率下 HEVC ~= 1.25 x H264，AV1 ~= 1.5 x H264，
       避免把"高效编码压得更狠的文件"误判为低画质。
    4. 最后用文件大小兜底，仅作同分平局裁决。

内置的编码效率系数（CODEC_QUALITY_FACTOR）:
    h264/avc 1.00 | hevc/h265 1.25 | av1 1.50 | vp9 1.20 | vp8 0.90
    mpeg4 0.75 | mpeg2video 0.60 | prores/dnxhd 2.00 | ffv1/huffyuv 2.50
    未知编码按 1.00 处理。

如何判断"内容相同"？
    在时长的中间 80% 均匀抽取 N 帧，计算每帧的 dHash（8x8 = 64 位）。
    两视频比较时，只要 >= 75% 的抽样帧汉明距离 <= --hash-tol，
    就判为"同一内容的不同版本"。少于 2 帧可用的比较会被拒绝，
    因此抽帧失败的视频不会被误判为重复。


六、参数调节建议（排错表）
--------------------------------------------------------------------------------
现象                                              → 建议
-------------------------------------------------→--------------------------------
同一片段的不同清晰度版本没被识别为重复         → 调大 --hash-tol（如 10-12），
                                                    或增大 --duration-tol
                                                    
时长相差 2 秒以上的版本（多了片头广告等）       → 适度增大 --duration-tol，
                                                    但要注意这会增加误判风险

内容变化剧烈的视频被误判为不同                 → 增大 --frames（如 6-8）

不同内容的视频被误判为重复                     → 减小 --hash-tol（如 4-6）

扫描太慢                                        → 增大 --jobs；
                                                    对小于某个体积的文件
                                                    用 --min-size 跳过

担心误删重要文件                                → 始终使用 --quarantine


七、示例场景
--------------------------------------------------------------------------------
# 1) 常见：递归扫描并预览
python clean_duplicate_videos.py ~/Videos

# 2) 安全清理：移动到隔离目录
python clean_duplicate_videos.py ~/Videos --execute \
       --quarantine /tmp/video_trash

# 3) 直接删除（确认预览无误后）
python clean_duplicate_videos.py ~/Videos --execute -y

# 4) 只处理顶层，不递归
python clean_duplicate_videos.py ~/Videos --no-recursive

# 5) 严格模式：只认几乎完全一致的内容
python clean_duplicate_videos.py ~/Videos --hash-tol 4 --frames 6

# 6) 跳过 10MB 以下的小文件，加速扫描
python clean_duplicate_videos.py ~/Videos --min-size 10485760

# 7) 导出清理计划供人工审核
python clean_duplicate_videos.py ~/Videos --json plan.json

# 8) 脚本化：无人值守执行（请先预览）
python clean_duplicate_videos.py ~/Videos --execute -y \
       --quarantine /tmp/video_trash --json plan.json


八、工作原理（简述）
--------------------------------------------------------------------------------
    probe_video()            → ffprobe 读取元数据（含旋转补偿）
    group_by_duration()      → 按 duration 排序后聚合到容差桶内
    find_duplicate_groups()  → 桶内两两抽帧 dHash 比对，并查集合并
    max(quality_key())       → 每组选出保留对象
    remove_to_quarantine()   → 移动（保留相对路径，重名自动加后缀）


九、已知边界与注意事项
--------------------------------------------------------------------------------
    * 片头/片尾不同（如一个版本多了 2 秒广告）会导致按百分比采样点
      错位而漏检。这种情况可适度放宽 --hash-tol 或人工处理。
    * 画面被裁切或拉伸（16:9 ↔ 4:3 加黑边）会改变哈希，通常不会被
      判为重复 —— 属于保守行为，不会误删。
    * 竖屏视频会依据 rotation 元数据交换宽高，不会被误判为横屏。
    * 无 video 流、时长为 0、尺寸为 0、无法读取的文件会被跳过，
      不会参与比较，也绝不会被删除。
    * 直接删除（不带 --quarantine）后无法通过脚本恢复，请务必先预览。
    * 跨文件系统移动由 shutil.move 处理（会退化为复制+删除）。


十、输出说明
--------------------------------------------------------------------------------
    stdout：
        - 扫描统计（文件数、有效视频数、时长分组数）
        - 每一组重复的"★ 保留 / ✗ 清理"清单及画质参数
        - 汇总：可清理文件数、释放空间
    stderr：
        - 处理失败的文件及原因
    --json：
        [
          {
            "keep":   {path,width,height,codec,bitrate,size,duration},
            "remove": [ { ... }, ... ]
          },
          ...
        ]
================================================================================
"""

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    sys.exit("缺少依赖 Pillow，请先运行: pip install pillow")


VIDEO_EXTS = {
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".3gp", ".3g2", ".rmvb",
    ".rm", ".asf", ".ogv", ".divx", ".vob", ".f4v",
}

# 编码效率系数：相同码率下，编码越先进视觉质量越高
CODEC_QUALITY_FACTOR = {
    "h264": 1.00, "avc": 1.00, "avc1": 1.00,
    "hevc": 1.25, "h265": 1.25, "hev1": 1.25, "hvc1": 1.25,
    "av1": 1.50, "av01": 1.50,
    "vp9": 1.20, "vp09": 1.20, "vp8": 0.90,
    "mpeg4": 0.75, "msmpeg4v3": 0.65, "msmpeg4v2": 0.60,
    "mpeg2video": 0.60, "mpeg1video": 0.50,
    "wmv2": 0.70, "wmv3": 0.75, "vc1": 0.85, "theora": 0.70,
    "prores": 2.00, "dnxhd": 2.00, "ffv1": 2.50, "huffyuv": 2.50,
    "rawvideo": 3.00,
}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class VideoMeta:
    path: Path
    size: int
    duration: float
    width: int
    height: int
    codec: str
    bitrate: float
    frames: List[Optional[int]] = field(default_factory=list)

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def bpp(self) -> float:
        """每像素每秒比特数，衡量压缩程度，越高越接近无损"""
        if self.pixels <= 0 or self.duration <= 0:
            return 0.0
        return self.bitrate / self.pixels

    @property
    def codec_factor(self) -> float:
        return CODEC_QUALITY_FACTOR.get(self.codec.lower(), 1.0)

    def quality_key(self) -> Tuple[int, float, int]:
        # 先比分辨率，再比"等效每像素码率"，最后比文件大小做兜底
        return (self.pixels, self.bpp * self.codec_factor, self.size)

    def describe(self) -> str:
        return (f"{self.width}x{self.height} {self.codec or '?'} "
                f"{self.bitrate / 1e6:.2f}Mbps bpp={self.bpp:.4f} "
                f"{fmt_size(self.size)}")


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------- #
# 元数据探测
# --------------------------------------------------------------------------- #
def ffprobe_json(path: Path) -> Optional[dict]:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None


def probe_video(path: Path) -> Optional[VideoMeta]:
    info = ffprobe_json(path)
    if not info:
        return None
    vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not vstreams:
        return None
    v = vstreams[0]
    fmt = info.get("format", {}) or {}
    try:
        duration = float(fmt.get("duration") or v.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return None
    try:
        width = int(v.get("width") or 0)
        height = int(v.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None

    # 处理手机竖屏视频的旋转元数据
    rotation = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rotation = abs(int(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
            break
    if not rotation:
        tags = v.get("tags") or {}
        if "rotate" in tags:
            try:
                rotation = abs(int(float(tags["rotate"])))
            except (TypeError, ValueError):
                pass
    if rotation % 180 == 90:
        width, height = height, width

    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None

    return VideoMeta(
        path=path, size=size, duration=duration,
        width=width, height=height,
        codec=str(v.get("codec_name") or ""),
        bitrate=size * 8.0 / duration,
    )


# --------------------------------------------------------------------------- #
# 帧哈希
# --------------------------------------------------------------------------- #
def dhash(img: Image.Image, hash_size: int = 8) -> int:
    small = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = list(small.getdata())
    w = hash_size + 1
    bits = 0
    for r in range(hash_size):
        base = r * w
        for c in range(hash_size):
            bits = (bits << 1) | (1 if px[base + c] > px[base + c + 1] else 0)
    return bits


def extract_frame_hash(path: Path, timestamp: float, hash_size: int = 8) -> Optional[int]:
    box = hash_size * 4  # 先缩到 32x32，再交给 PIL 缩到 9x8，减少 ffmpeg 版本差异
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(timestamp, 0):.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={box}:{box}:flags=area,setsar=1",
        "-f", "image2pipe", "-vcodec", "ppm", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        with Image.open(io.BytesIO(r.stdout)) as im:
            im.load()
            return dhash(im, hash_size)
    except Exception:
        return None


def sample_timestamps(duration: float, n: int) -> List[float]:
    """在视频中间 80% 区域均匀取 n 个时间点，避开片头片尾"""
    if duration <= 0 or n <= 0:
        return []
    if duration < 2.0:
        return [duration * 0.5] * n
    return [min(duration * ((i + 0.5) / n * 0.8 + 0.1), duration - 0.1)
            for i in range(n)]


def hash_frames(meta: VideoMeta, n_frames: int, hash_size: int = 8) -> List[Optional[int]]:
    return [extract_frame_hash(meta.path, t, hash_size)
            for t in sample_timestamps(meta.duration, n_frames)]


def frames_match(a: List[Optional[int]], b: List[Optional[int]], tol: int) -> bool:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return False
    matched = sum(1 for x, y in pairs if hamming(x, y) <= tol)
    need = max(2, math.ceil(len(pairs) * 0.75))
    return matched >= need


# --------------------------------------------------------------------------- #
# 分组
# --------------------------------------------------------------------------- #
def group_by_duration(metas: List[VideoMeta], tol: float) -> List[List[VideoMeta]]:
    if not metas:
        return []
    metas = sorted(metas, key=lambda m: m.duration)
    groups, cur = [], [metas[0]]
    for m in metas[1:]:
        if m.duration - cur[0].duration <= tol:
            cur.append(m)
        else:
            if len(cur) >= 2:
                groups.append(cur)
            cur = [m]
    if len(cur) >= 2:
        groups.append(cur)
    return groups


class DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def find_duplicate_groups(bucket: List[VideoMeta], hash_tol: int,
                          n_frames: int, jobs: int) -> List[List[VideoMeta]]:
    # 并发抽帧
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(hash_frames, m, n_frames): m for m in bucket}
        for fut in as_completed(futures):
            m = futures[fut]
            try:
                m.frames = fut.result()
            except Exception:
                m.frames = []

    dsu = DSU(len(bucket))
    for i in range(len(bucket)):
        for j in range(i + 1, len(bucket)):
            if frames_match(bucket[i].frames, bucket[j].frames, hash_tol):
                dsu.union(i, j)

    groups: Dict[int, List[VideoMeta]] = {}
    for i, m in enumerate(bucket):
        groups.setdefault(dsu.find(i), []).append(m)
    return [g for g in groups.values() if len(g) >= 2]


# --------------------------------------------------------------------------- #
# 文件操作
# --------------------------------------------------------------------------- #
def remove_to_quarantine(path: Path, root: Path, quarantine: Path) -> Path:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    dest = quarantine / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        i = 1
        while True:
            cand = dest.with_name(f"{dest.stem}__{i}{dest.suffix}")
            if not cand.exists():
                dest = cand
                break
            i += 1
    shutil.move(str(path), str(dest))
    return dest


def collect_video_paths(root: Path, recursive: bool) -> List[Path]:
    it = root.rglob("*") if recursive else root.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(
        description="清理目录中的重复视频，保留画质最好的版本"
                    "（详细说明请查看本脚本首部文档或 --help）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("directory", help="要扫描的目录")
    ap.add_argument("--execute", action="store_true", help="真正执行删除/移动（默认只预览）")
    ap.add_argument("--yes", "-y", action="store_true", help="执行时跳过交互确认")
    ap.add_argument("--quarantine", metavar="DIR",
                    help="把待清理文件移动到该目录（保留相对路径），而不是直接删除")
    ap.add_argument("--duration-tol", type=float, default=1.0,
                    help="时长分桶容差（秒），默认 1.0")
    ap.add_argument("--hash-tol", type=int, default=8,
                    help="dHash 汉明距离阈值，默认 8（越小越严格）")
    ap.add_argument("--frames", type=int, default=4, help="每个视频抽样帧数，默认 4")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4),
                    help="并发数")
    ap.add_argument("--min-size", type=int, default=0, help="忽略小于该字节数的文件")
    ap.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    ap.add_argument("--json", metavar="FILE", help="把清理计划导出为 JSON")
    args = ap.parse_args()

    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"错误：目录不存在 -> {root}")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"错误：找不到 {tool}，请先安装 ffmpeg 并加入 PATH")

    print(f"扫描目录 : {root}")
    paths = collect_video_paths(root, not args.no_recursive)
    if args.min_size > 0:
        paths = [p for p in paths if p.stat().st_size >= args.min_size]
    print(f"视频文件 : {len(paths)} 个")
    if len(paths) < 2:
        print("文件太少，无需处理。")
        return

    print("读取视频元数据 ...")
    metas: List[VideoMeta] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = {pool.submit(probe_video, p): p for p in paths}
        for fut in as_completed(futs):
            try:
                m = fut.result()
            except Exception:
                m = None
            if m:
                metas.append(m)
    print(f"有效视频 : {len(metas)} 个")
    if len(metas) < 2:
        print("可用视频太少，无需处理。")
        return

    buckets = group_by_duration(metas, args.duration_tol)
    print(f"时长分组 : {len(buckets)} 组（每组 >= 2 个文件）")

    plans: List[Tuple[VideoMeta, List[VideoMeta]]] = []
    for idx, bucket in enumerate(buckets, 1):
        print(f"  → 时长桶 {idx}: {len(bucket)} 个文件，时长约 "
              f"{fmt_duration(bucket[0].duration)}，抽帧比对中 ...")
        for g in find_duplicate_groups(bucket, args.hash_tol, args.frames, args.jobs):
            keep = max(g, key=lambda m: m.quality_key())
            plans.append((keep, [m for m in g if m is not keep]))

    if not plans:
        print("\n没有发现内容重复但画质不同的视频。")
        return

    # ---------- 打印计划 ----------
    total_bytes, n_files = 0, 0
    print("\n" + "=" * 78)
    print("清理计划")
    print("=" * 78)
    for i, (keep, removes) in enumerate(plans, 1):
        print(f"\n[组 {i}] 时长 {fmt_duration(keep.duration)}")
        print(f"  ★ 保留  {keep.path}")
        print(f"           {keep.describe()}")
        for r in removes:
            print(f"  ✗ 清理  {r.path}")
            print(f"           {r.describe()}")
            total_bytes += r.size
            n_files += 1
    print("\n" + "-" * 78)
    print(f"共 {len(plans)} 组重复；可清理 {n_files} 个文件，释放约 {fmt_size(total_bytes)}")

    # ---------- 导出 JSON ----------
    if args.json:
        def pack(m: VideoMeta) -> dict:
            return {"path": str(m.path), "width": m.width, "height": m.height,
                    "codec": m.codec, "bitrate": round(m.bitrate, 2),
                    "size": m.size, "duration": round(m.duration, 3)}
        data = [{"keep": pack(k), "remove": [pack(r) for r in rs]} for k, rs in plans]
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"计划已写入 {args.json}")

    # ---------- 执行 ----------
    if not args.execute:
        print("\n[预览模式] 未删除任何文件。确认无误后加 --execute 执行。")
        if args.quarantine:
            print(f"（执行时会移动到 {args.quarantine}）")
        return

    if not args.yes:
        ans = input(f"\n确认清理以上 {n_files} 个文件？输入 yes 继续: ").strip().lower()
        if ans not in ("yes", "y"):
            print("已取消。")
            return

    quarantine = Path(args.quarantine).expanduser().resolve() if args.quarantine else None
    if quarantine:
        quarantine.mkdir(parents=True, exist_ok=True)

    removed, freed, failed = 0, 0, []
    for _, removes in plans:
        for r in removes:
            try:
                if quarantine:
                    remove_to_quarantine(r.path, root, quarantine)
                else:
                    r.path.unlink()
                removed += 1
                freed += r.size
                print(f"  已处理: {r.path}")
            except Exception as e:
                failed.append((r.path, str(e)))
                print(f"  失败: {r.path} -> {e}", file=sys.stderr)

    print(f"\n完成：清理 {removed} 个文件，释放 {fmt_size(freed)}")
    if failed:
        print(f"有 {len(failed)} 个文件处理失败。", file=sys.stderr)


if __name__ == "__main__":
    main()
