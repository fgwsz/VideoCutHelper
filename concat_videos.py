#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
                   FFmpeg 视频无损拼接工具  concat_videos.py  v6.7
================================================================================

【项目简介】
    一款基于 FFmpeg 的命令行视频批量拼接工具。按文件名自然升序，将多个视频
    合并为一个文件。默认采用 MPEG-TS 中转 + 流拷贝（stream copy），不重新编码，
    秒级完成；同时智能处理分辨率差异、编码不一致、尾部裁剪、音画同步等真实
    拼接难题，在"尽量无损"与"保证可播放"之间自动做出明确取舍。

【快速开始 TL;DR】
    1. 安装 ffmpeg / ffprobe 并确保可执行；
    2. 把视频放进一个目录，或显式列出文件名；
    3. 执行：  python3 concat_videos.py ./目录/ -o output.mp4
    4. 分辨率/编码/音频不一致时，工具会提示或按选项自动统一；
    5. 需要去掉每个片段末尾时长用 --trim-end，需严格对齐加 --exact-trim。

--------------------------------------------------------------------------------
【运行环境 / 依赖】
--------------------------------------------------------------------------------
    - Python 3.7+（仅使用标准库，无第三方依赖）。
    - 系统需安装并可在 PATH 中找到 ffmpeg 与 ffprobe；
      若不在 PATH，请用 --ffmpeg / --ffprobe 指定可执行文件的完整路径。
    - 跨平台：Linux / macOS / Windows。

--------------------------------------------------------------------------------
【核心特性】
--------------------------------------------------------------------------------
    - 无损优先：默认 stream copy，避免画质损失与漫长重编码。
    - 自然排序：1.mp4 < 2.mp4 < 10.mp4，符合直觉，避免字符串排序错乱。
    - 分辨率自适应：交互式或一键统一（scale+pad 等比留边，不变形）。
    - 编码自适应：H.264 / H.265 / AV1 / VP9 智能判定，必要时统一为 H.264。
    - 音频鲁棒：统一 AAC / 立体声 / 48kHz；缺失音轨自动补静音。
    - 尾部裁剪：快速（关键帧，无损秒完成）/ 精确（重编码同步对齐）两种模式。
    - 健壮性：子进程超时、探测缓存线程安全、文件数硬上限、异常堆栈可观测。

--------------------------------------------------------------------------------
【基本用法】
--------------------------------------------------------------------------------
    python3 concat_videos.py [输入文件或目录 ...] [选项]

    - 输入可省略（默认为当前目录 '.'）。
    - 输入可为单个文件、多个文件，或包含视频的目录（自动按扩展名筛选）。
    - 支持的扩展名：.mp4 .mkv .avi .mov .ts .flv .webm .MOV（用 -e 自定义）。

--------------------------------------------------------------------------------
【命令行参数】
--------------------------------------------------------------------------------
    位置参数
      输入                          视频文件或目录，可多个（默认：'.'）

    输出控制
      -o, --output PATH             输出文件（默认：concat_output.mp4）
      --overwrite                   允许覆盖已存在的输出文件

    输入筛选
      -e, --extensions E [E ...]    自定义支持的视频扩展名

    拼接策略（互斥的常见组合，详见【决策逻辑】）
      --no-check                    跳过分辨率/视频编码一致性检查与交互。
                                    ⚠ 音频仍会保证可拼接性：
                                      · 全 AAC  → 流拷贝 COPY
                                      · 混合编码 → 安全降级 REENCODE
      --resample                    强制重编码并统一分辨率（自动选择目标尺寸）。
      --uniform-resolution [WxH|auto]
                                    统一分辨率：
                                      · 传 WxH（如 1920x1080）→ 显式指定
                                      · 省略参数值（即只写 --uniform-resolution）
                                        → 等价 auto，自动选择
      --yes                         非交互模式，跳过所有交互确认。
                                    ⚠ 编码不一致时**保持流拷贝**（不重编码）。
                                      如需统一编码，请显式加 --resample 或
                                      --uniform-resolution auto。

    音频控制
      --audio-reencode              强制重新编码音频（统一为 AAC/立体声/48kHz）。

    裁剪
      --trim-end TIME               裁剪每个片段末尾的时长（秒数或 HH:MM:SS.msec）。
                                    默认是**快速裁剪**：基于关键帧，边界偏差 <1s。
      --exact-trim                  精确裁剪（重编码），音视频严格同步对齐。
                                    必须配合 --trim-end 使用；单独出现会被忽略并警告。

    调试 / 诊断
      --dry-run                     只打印将要执行的 ffmpeg 命令，不实际执行。
                                    此模式下 --quiet 不会抑制命令输出。
      --verbose                     输出调试信息（含每条 ffmpeg 命令、异常堆栈）。
      --quiet                       只输出警告和错误。

    外部依赖
      --ffmpeg PATH                 指定 ffmpeg 可执行文件路径（默认：ffmpeg）
      --ffprobe PATH                指定 ffprobe 可执行文件路径（默认：ffprobe）

    查看帮助
      -h, --help                    打印帮助并退出。

--------------------------------------------------------------------------------
【决策逻辑】——"工具会怎么处理我的文件？"
--------------------------------------------------------------------------------
    工具在做每件事前都会先探测再决策；下面是用户最关心的四个决策点。

    ┌───────────────────────────────────────────────────────────────────────┐
    │ 1. 视频是否重编码？                                                  │
    ├───────────────────────────────────────────────────────────────────────┤
    │ 触发重编码的情形（优先级从高到低）：                                  │
    │   a) 显式指定 --resample / --uniform-resolution（分辨率统一）        │
    │   b) 显式指定 --exact-trim（精确裁剪需要重编码）                     │
    │   c) 输入编码**全部**为 AV1 或 VP9（TS/MP4 拼接兼容性差 → H.264）    │
    │   d) 交互模式下用户在编码不一致提示中选择统一编码                    │
    │                                                                       │
    │ 保持流拷贝的情形：                                                    │
    │   · 所有视频编码一致且不属于 AV1/VP9                                 │
    │   · --no-check 且用户未显式要求统一                                   │
    │   · --yes / --quiet / 非 TTY 且未显式要求统一（保守：不重编码）       │
    └───────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────────────────────────────────────────────────────┐
    │ 2. 音频如何处理？                                                    │
    ├───────────────────────────────────────────────────────────────────────┤
    │ 决策顺序（第一条命中即返回）：                                        │
    │   1) 全部无音频            → 静音（-an，不生成音轨）                  │
    │   2) 部分无音频            → 补静音并统一重编码所有音频（SILENCE）   │
    │   3) --audio-reencode      → 全量重编码（REENCODE）                   │
    │   4) --exact-trim          → 全量重编码（音视频严格对齐）             │
    │   5) --no-check            → 全 AAC 则 COPY，否则安全降级 REENCODE    │
    │   6) 核心参数不一致        → REENCODE                                 │
    │   7) 源音频非 AAC          → REENCODE                                 │
    │   8) 以上都通过            → 流拷贝 COPY                              │
    └───────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────────────────────────────────────────────────────┐
    │ 3. 分辨率如何处理？                                                  │
    ├───────────────────────────────────────────────────────────────────────┤
    │   · --uniform-resolution WxH  → 统一到指定尺寸                        │
    │   · --uniform-resolution（无值）→ 自动选（见下）                      │
    │   · --resample                 → 自动选 + 强制重编码                  │
    │   · 默认 + 分辨率一致           → 不处理                              │
    │   · 默认 + 分辨率不一致         → 交互询问（--yes/--quiet/非 TTY 自动用快速拼接）│
    │                                                                       │
    │ 自动选目标尺寸规则（auto）：                                          │
    │   · 按横屏/竖屏分组，取同组最大宽和最大高                             │
    │   · 无横屏则取全部中最大宽、最大高                                    │
    │   · 缩放使用 scale+pad（等比缩放 + 黑边补齐），不会变形               │
    └───────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────────────────────────────────────────────────────┐
    │ 4. 尾部裁剪如何执行？                                                │
    ├───────────────────────────────────────────────────────────────────────┤
    │   · --trim-end 5            → 快速裁剪：每片段截掉末尾 5s             │
    │                               （基于关键帧，无损，边界偏差 <1s）      │
    │   · --trim-end 5 --exact-trim → 精确裁剪：重编码，音视频严格对齐      │
    │                               （耗时更长，画质有轻微损失）            │
    └───────────────────────────────────────────────────────────────────────┘

--------------------------------------------------------------------------------
【使用示例】
--------------------------------------------------------------------------------
    基础用法
        # 拼接当前目录所有视频，输出到默认文件 concat_output.mp4
        python3 concat_videos.py

        # 指定输入文件 + 自定义输出名
        python3 concat_videos.py a.mp4 b.mp4 c.mp4 -o merged.mp4

        # 拼接一个目录（自然升序）
        python3 concat_videos.py ./parts/ -o final.mp4

        # 只接受 .mkv 与 .mp4（排除 .mov 等其他格式）
        python3 concat_videos.py ./parts/ -e .mkv .mp4

    分辨率与编码
        # 目录拼接；分辨率不一致时自动统一、跳过交互
        python3 concat_videos.py ./parts/ --resample --yes

        # 显式统一为 1920x1080
        python3 concat_videos.py ./parts/ --uniform-resolution 1920x1080

        # 自动选择目标尺寸并统一（= --resample）
        python3 concat_videos.py ./parts/ --uniform-resolution

        # 编码不一致但不想重编码（快速，接受可能无画面）
        python3 concat_videos.py ./parts/ --no-check --yes

    尾部裁剪
        # 每个视频去掉末尾 5 秒（快速，无损）
        python3 concat_videos.py *.mp4 --trim-end 5

        # 每个视频去掉末尾 0.5 秒
        python3 concat_videos.py *.mp4 --trim-end 0.5

        # 精确去掉末尾 5 秒（重编码，音视频严格对齐）
        python3 concat_videos.py *.mp4 --trim-end 0:0:5 --exact-trim

        # 兼容宽松时长写法：1 小时 5 分 3 秒
        python3 concat_videos.py *.mp4 --trim-end 1:5:3

    音频
        # 强制统一音频（例如源音频有 AAC 也有 Opus）
        python3 concat_videos.py *.mp4 --audio-reencode

    调试 / 诊断
        # 只查看将执行什么命令而不实际运行（verbose 打印完整命令）
        python3 concat_videos.py ./parts/ --dry-run --verbose

        # 只要警告和错误
        python3 concat_videos.py ./parts/ --quiet

    外部依赖路径
        # ffmpeg 不在 PATH 时手动指定
        python3 concat_videos.py ./parts/ \
            --ffmpeg /opt/ffmpeg/bin/ffmpeg \
            --ffprobe /opt/ffmpeg/bin/ffprobe

    管道 / 批处理 / CI 集成
        # 从 stdin 读入文件列表（每行一个路径）
        find ./parts -name '*.mp4' | xargs python3 concat_videos.py --yes

        # 在脚本中捕获结果（返回非 0 视为失败）
        python3 concat_videos.py ./parts/ -o final.mp4 --yes \
            && echo "拼接成功" || echo "拼接失败"

        # 定时任务（无 TTY，全部走非交互分支）
        0 3 * * * cd /data && python3 concat_videos.py ./today/ --yes

--------------------------------------------------------------------------------
【环境变量（运行时调优，可覆盖内置默认值）】
--------------------------------------------------------------------------------
    FFMPEG_CONCAT_TIMEOUT
        执行类子进程超时（秒），默认 7200（2 小时）；<=0 表示不限制。
        适用场景：单个视频重编码耗时较长的场景调大；有卡死风险的环境调小。

    FFMPEG_CONCAT_PROBE_TIMEOUT
        探测类子进程超时（秒），默认 60。
        探测超时会被降级（该文件时长未知，触发对应保守路径），不会中断整体流程。

    FFMPEG_CONCAT_MAX_FILES
        单次输入文件硬上限，默认 5000。
        防止超大目录触发海量并行 ffprobe；超过会立即报错退出。

--------------------------------------------------------------------------------
【退出码】
--------------------------------------------------------------------------------
    0     成功完成。
    1     业务失败（参数错误、找不到文件、ffmpeg 命令失败、磁盘不足等）。
    130   用户中断（Ctrl+C）。
    其他  底层异常（未捕获的 bug）由 Python 默认处理，会打印 traceback。

    说明：
      · 所有"可预期的错误"都会返回 1 并打印可读错误信息。
      · 探测层的降级（时长未知、编码未知）不视为失败，会继续尝试拼接。
      · --dry-run 只要参数与路径校验通过就返回 0（不实际执行 ffmpeg）。

--------------------------------------------------------------------------------
【故障排查 FAQ】
--------------------------------------------------------------------------------
    Q1. 报 "找不到 ffmpeg / ffprobe"？
        → 确认已安装，或显式传 --ffmpeg / --ffprobe 完整路径。

    Q2. 报 "输出文件已存在"？
        → 加 --overwrite，或换一个 -o 路径。

    Q3. 报 "临时目录/输出目录空间不足"？
        → 工具会分别预估临时目录（≈ 输入总大小 × 1.2）与输出目录需求。
        → 若对重编码场景偏保守（重编码输出可能远超 1.2×），可手动清理后重试。

    Q4. 报 "以下文件时长未知，无法执行 --trim-end 裁剪"？
        → 探测失败（超时/损坏/畸形容器）。检查文件完整性；或去掉 --trim-end。

    Q5. 拼接成功但某些片段"黑屏/无声"？
        → 大概率是编码不一致且用户加了 --no-check。
        → 去掉 --no-check，或用 --resample 显式统一编码。

    Q6. 快速裁剪后音视频不同步 / 总时长和预期不一致？
        → 快速裁剪基于关键帧，边界有 <1s 偏差。
        → 需要精确对齐请加 --exact-trim（会重编码，耗时更长）。

    Q7. 拼接成功但输出无法在播放器打开？
        → 检查输入是否全 AV1/VP9（工具会主动重编码，不应发生此情况）。
        → 若非 AV1/VP9 仍无法打开，请加 --verbose 重跑并检查 ffmpeg 输出。

    Q8. --dry-run 输出里路径是 /tmp/part_xxxx.ts，但我实际用的是别的临时目录？
        → dry-run 只做示意，不创建真实临时目录；实际运行使用 mkdtemp。

    Q9. --yes 之后分辨率没统一？
        → 这是 v6.7 的明确语义：--yes 只表示"全接受默认"，不隐含重编码。
        → 需要统一请显式加 --resample 或 --uniform-resolution。

    Q10. 想让它别问问题但也要统一编码？
        → python3 concat_videos.py ./parts/ --resample --yes

--------------------------------------------------------------------------------
【行为约定与注意事项】
--------------------------------------------------------------------------------
    - 输出文件不能与任一输入相同，工具会检测自覆盖并报错。
    - 拼接前会校验临时目录与输出目录的磁盘可用空间。
    - 快速裁剪（--trim-end 不带 --exact-trim）基于关键帧，边界可能有 <1s 偏差，
      对精度敏感请改用 --exact-trim（会触发重编码，耗时更长）。
    - 5.1 等多声道音频在统一重编码时会降混为立体声。
    - 音频流仅使用第一轨（含多音轨的文件会给出警告）。
    - 工具异常时返回非零退出码；正常完成返回 0。

--------------------------------------------------------------------------------
【分层架构（开发 / 二次开发参考）】
--------------------------------------------------------------------------------
    数据模型 → 探测层 → 决策层 → 命令层 → 编排层 → CLI

    · 数据模型：AudioInfo / VideoInfo / ConcatPlan 等纯数据结构。
    · 探测层：FFmpegRunner（进程 / 超时 / 进程组管理）、
              MediaProbe（ffprobe + 缓存 + 并行探测）。
    · 决策层：PlanBuilder（纯函数式，参数 + 探测结果 → 拼接方案）。
    · 命令层：TSCommandBuilder（拼装 ffmpeg / concat 命令）。
    · 编排层：ConcatPipeline（磁盘预检、临时目录、进度、清理、异常回退）。
    · CLI：参数解析、日志、退出码、Ctrl+C 中断与安全收尾。

    若需嵌入其他脚本，推荐调用入口：
        from concat_videos import main
        exit_code = main(['./parts/', '--resample', '--yes'])

--------------------------------------------------------------------------------
【版本历史】
--------------------------------------------------------------------------------
    v6.7（当前）— P0/P1 修复：
        P0-a. 探测 format 为 null 时 .get('duration') 崩溃 → 改用 `or {}`
        P0-b. 探测 streams 为 null 时 for 循环崩溃 → 改用 `or []`
        P1-4. MediaProbe.probe 注释修正：本实现只保证结果一致，不保证不重复探测
        P1-5. --yes / --quiet / 非 TTY 下，编码不一致不再隐式强制 H.264，
              改为保守流拷贝 + 强警告；统一编码请显式 --resample / --uniform-resolution
        P1-6. 全 VP9 与全 AV1 一样重编码 H.264（VP9 经 mpegts 拼接兼容性差）
        P1-7. --no-check 帮助文本明确音频仍保证可拼接性
        P1-8. format.duration 缺失时用 max(stream.duration) 回填，
              避免 MKV 等容器 --trim-end 误报"时长未知"

    v6.6 — P0 修复：
        P0-1. 非 TTY / 管道场景 input() 抛 EOFError → PlanBuilder 增加 TTY 检测；
              main 捕获 KeyboardInterrupt/EOFError/OSError
        P0-2. ffprobe 返回 width="N/A" → int() 崩 → 改用容错 _int_or_zero
        P0-3. 无权限目录 iterdir() 抛 PermissionError → 降级为警告跳过

    v6.5 — 健壮性加固：
        子进程超时、MediaProbe 缓存加锁、MAX_INPUT_FILES 上限、
        编码参数集中配置、--verbose 附带 traceback、日志与 root 隔离

    v6.4 — 业务修复：
        --trim-end 前置校验、--no-check 跳过音频检查、
        --exact-trim 强制音频重编码、--ffmpeg 路径校验、
        --output 目录预检、--dry-run 不被 --quiet 抑制、自然排序

    v6.3 及更早 — 见历史归档

--------------------------------------------------------------------------------
【许可与反馈】
--------------------------------------------------------------------------------
    本工具无第三方依赖，源码可直接阅读与修改。
    使用中遇到问题请带上 --verbose 的输出（含错误上下文与命令），
    便于定位到具体的决策分支。
================================================================================
"""

import sys
import os
import signal
import json
import shutil
import logging
import argparse
import re
import threading
import subprocess
import tempfile
import traceback
import atexit
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from typing import List, Set, Dict, Optional, Tuple


__version__ = '6.7'


# ============================================================================
# 常量
# ============================================================================
DEFAULT_EXTENSIONS: Set[str] = {
    '.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv', '.webm', '.MOV'
}
DEFAULT_OUTPUT = "concat_output.mp4"
TEMP_PREFIX = "ffmpeg_concat_"

AUDIO_TARGET_CODEC = 'aac'
AUDIO_TARGET_BITRATE = '192k'
AUDIO_TARGET_SAMPLE_RATE = '48000'
AUDIO_TARGET_CHANNELS = '2'

VIDEO_PRESET = 'veryfast'
VIDEO_CRF_BY_CODEC: Dict[str, str] = {'h264': '23', 'hevc': '28'}
DEFAULT_CRF = '23'


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


PROBE_TIMEOUT = _env_float('FFMPEG_CONCAT_PROBE_TIMEOUT', 60.0)
FFMPEG_TIMEOUT = _env_float('FFMPEG_CONCAT_TIMEOUT', 7200.0)
MAX_INPUT_FILES = _env_int('FFMPEG_CONCAT_MAX_FILES', 5000)

BSF_MAP: Dict[str, str] = {
    'h264': 'h264_mp4toannexb',
    'hevc': 'hevc_mp4toannexb',
    'mpeg4': 'mpeg4_unpack_bframes',
    'av1': 'av1_metadata',
    'vp9': 'vp9_superframe',
}

ENCODER_TO_CODEC = {'libx264': 'h264', 'libx265': 'hevc'}
CODEC_TO_ENCODER = {'h264': 'libx264', 'avc': 'libx264',
                    'hevc': 'libx265', 'h265': 'libx265'}

TS_FAMILY_SUFFIXES = {'.ts', '.m2ts', '.mts'}

PROBE_WORKERS = 8
MAX_AUTO_RESOLUTION_FILES = 10000

IS_WINDOWS = sys.platform == 'win32'


# ============================================================================
# 异常与日志
# ============================================================================
class FFmpegError(RuntimeError):
    """FFmpeg 命令或业务逻辑失败。"""


logger = logging.getLogger('concat')


def setup_logging(quiet: bool = False, verbose: bool = False) -> None:
    """配置 'concat' 子 logger（不污染 root，库友好）。"""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


# ============================================================================
# 数据模型
# ============================================================================
@dataclass(frozen=True)
class AudioInfo:
    codec: str
    sample_rate: str
    channels: str
    channel_layout: str
    bit_rate: int = 0

    def core_equal(self, other: 'AudioInfo') -> bool:
        """核心参数是否一致（不含 bit_rate，码率差异只告警不重编码）。"""
        return (self.codec, self.sample_rate, self.channels, self.channel_layout) == \
               (other.codec, other.sample_rate, other.channels, other.channel_layout)


@dataclass
class VideoInfo:
    path: Path
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    v_codec: Optional[str] = None
    audio: Optional[AudioInfo] = None
    audio_stream_count: int = 0
    audio_duration: Optional[float] = None
    video_duration: Optional[float] = None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def resolution(self) -> Optional[Tuple[int, int]]:
        if self.width and self.height:
            return (self.width, self.height)
        return None

    def trimmed_duration(self, trim_end: Optional[float],
                         strict: bool = False) -> Optional[float]:
        if self.duration is None:
            if strict:
                raise FFmpegError(f"{self.path.name} 时长未知，无法执行裁剪")
            return None
        if trim_end is None:
            return self.duration
        remaining = self.duration - trim_end
        if remaining <= 0:
            if strict:
                raise FFmpegError(
                    f"{self.path.name} 裁剪 {trim_end}s 超过其时长 {self.duration:.2f}s")
            return 0.0
        return remaining


class AudioOp(Enum):
    COPY = 'copy'
    REENCODE = 'reencode'
    SILENCE = 'silence'


class VideoOp(Enum):
    COPY = 'copy'
    REENCODE = 'reencode'


@dataclass
class ConcatPlan:
    output: Path
    video_op: VideoOp
    audio_op: AudioOp
    target_vcodec: Optional[str] = None
    target_resolution: Optional[Tuple[int, int]] = None
    trim_end: Optional[float] = None
    exact_trim: bool = False
    source_audio_codec: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def is_quick_trim(self) -> bool:
        return self.trim_end is not None and not self.exact_trim

    @property
    def is_exact_trim(self) -> bool:
        return self.trim_end is not None and self.exact_trim

    @property
    def audio_is_reencoded(self) -> bool:
        return self.audio_op in (AudioOp.REENCODE, AudioOp.SILENCE)

    @property
    def target_codec_short(self) -> Optional[str]:
        return ENCODER_TO_CODEC.get(self.target_vcodec) if self.target_vcodec else None

    @property
    def has_audio_expected(self) -> bool:
        return self.audio_is_reencoded or self.source_audio_codec is not None


# ============================================================================
# 工具函数
# ============================================================================
def get_file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def get_file_size_mb(path: Path) -> float:
    return get_file_size_bytes(path) / (1024 * 1024)


def build_audio_encode_opts() -> List[str]:
    return [
        '-c:a', AUDIO_TARGET_CODEC,
        '-b:a', AUDIO_TARGET_BITRATE,
        '-ar', AUDIO_TARGET_SAMPLE_RATE,
        '-ac', AUDIO_TARGET_CHANNELS,
    ]


def build_video_encode_opts(vcodec: str,
                            target_resolution: Optional[Tuple[int, int]] = None
                            ) -> List[str]:
    short = ENCODER_TO_CODEC.get(vcodec, vcodec)
    crf = VIDEO_CRF_BY_CODEC.get(short, DEFAULT_CRF)
    opts = ['-c:v', vcodec, '-preset', VIDEO_PRESET, '-crf', crf]
    if target_resolution:
        w, h = target_resolution
        opts += ['-vf', _scale_pad_filter(w, h)]
    return opts


def _scale_pad_filter(w: int, h: int) -> str:
    return (f'scale={w}:{h}:force_original_aspect_ratio=decrease,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2')


def ffmpeg_base(ffmpeg_path: str) -> List[str]:
    return [ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-y']


_DURATION_HMS_RE = re.compile(r'^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$')


def parse_duration(duration_str: str) -> float:
    s = duration_str.strip()
    try:
        return float(s)
    except ValueError:
        pass
    m = _DURATION_HMS_RE.match(s)
    if m:
        h, mm, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mm * 60 + sec
    raise ValueError(f"无法解析时长: {s}，请使用秒数或 HH:MM:SS.msec")


def _natural_sort_key(p: Path) -> List:
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', p.name)]


def _check_executable(path_str: str) -> bool:
    if shutil.which(path_str):
        return True
    try:
        return Path(path_str).is_file()
    except OSError:
        return False


def collect_video_files(paths: List[str], extensions: Set[str],
                       max_files: int = MAX_INPUT_FILES) -> List[Path]:
    """收集视频文件，自然排序去重。[v6.6 · P0-3] 目录权限错误降级为警告。"""
    seen: Set[Path] = set()
    result: List[Path] = []
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            logger.warning(f"⚠️ 路径不存在，已忽略 - {p}")
            continue

        candidates: List[Path] = []
        if p.is_file():
            if p.suffix.lower() in extensions:
                candidates = [p]
            else:
                logger.warning(f"⚠️ 扩展名不支持，已忽略 - {p}")
        elif p.is_dir():
            try:
                candidates = [f for f in p.iterdir()
                              if f.is_file() and f.suffix.lower() in extensions]
            except OSError as e:
                logger.warning(f"⚠️ 无法读取目录 {p}: {e}，已跳过")
                continue
        else:
            logger.warning(f"⚠️ 未知类型，已忽略 - {p}")
            continue

        for c in candidates:
            key = c.resolve()
            if key in seen:
                continue
            seen.add(key)
            result.append(c)
            if max_files > 0 and len(result) > max_files:
                raise FFmpegError(
                    f"输入视频文件数超过上限 {max_files}，"
                    "请缩小输入目录范围或拆分处理")

    result.sort(key=_natural_sort_key)
    return result


def nearest_existing(p: Path) -> Path:
    p = p.resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


# ============================================================================
# 探测层
# ============================================================================
class FFmpegRunner:
    """执行子进程，支持 SIGINT 转发与超时保护。"""

    def __init__(self, ffmpeg: str = 'ffmpeg', ffprobe: str = 'ffprobe',
                 ffmpeg_timeout: float = FFMPEG_TIMEOUT,
                 probe_timeout: float = PROBE_TIMEOUT):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.ffmpeg_timeout = ffmpeg_timeout
        self.probe_timeout = probe_timeout
        self._active_proc: Optional[subprocess.Popen] = None

    def _timeout_arg(self, timeout: float) -> Optional[float]:
        return timeout if timeout and timeout > 0 else None

    def run_checked(self, cmd: List[str]) -> Tuple[int, str, str]:
        logger.debug(f"[CMD] {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            start_new_session=True,
        )
        self._active_proc = proc
        timeout = self._timeout_arg(self.ffmpeg_timeout)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            raise FFmpegError(
                f"命令执行超时（{self.ffmpeg_timeout:.0f}s）已终止，"
                f"文件可能损坏或 ffmpeg 卡死：{' '.join(cmd[:6])} ...")
        except KeyboardInterrupt:
            self._terminate(proc)
            raise
        finally:
            self._active_proc = None

        if proc.returncode != 0:
            raise FFmpegError(self._format_error(cmd, stderr or '', proc.returncode))
        return proc.returncode, stdout or '', stderr or ''

    def run_raw(self, cmd: List[str]) -> subprocess.CompletedProcess:
        timeout = self._timeout_arg(self.probe_timeout)
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise FFmpegError(f"探测超时（{self.probe_timeout:.0f}s）")

    def shutdown(self) -> None:
        if self._active_proc is not None:
            self._terminate(self._active_proc)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        def _signal(sig, default_fn):
            try:
                if IS_WINDOWS:
                    default_fn()
                else:
                    os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, OSError):
                try:
                    default_fn()
                except Exception:
                    pass
            except Exception:
                pass

        _signal(signal.SIGTERM, proc.terminate)
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        _signal(signal.SIGKILL, proc.kill)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _format_error(cmd: List[str], stderr: str, code: int) -> str:
        key_lines = [ln.strip() for ln in stderr.splitlines()
                     if any(k in ln.lower() for k in
                            ('error', 'invalid', 'failed', 'cannot', 'no such', 'not found'))]
        if not key_lines:
            key_lines = stderr.strip().splitlines()[-10:]
        detail = ' | '.join(key_lines) if key_lines else '(无 stderr)'
        if len(cmd) > 6:
            preview = ' '.join(cmd[:6]) + ' ... ' + cmd[-1]
        else:
            preview = ' '.join(cmd)
        return f"命令失败 (code={code}): {preview}\n  {detail}"


class MediaProbe:
    """每个文件一次 ffprobe（JSON），缓存并支持并行探测。"""

    def __init__(self, runner: FFmpegRunner):
        self.runner = runner
        self._cache: Dict[Path, VideoInfo] = {}
        self._cache_lock = threading.Lock()

    def probe(self, path: Path) -> VideoInfo:
        """
        [v6.7 · P1-4] 缓存语义说明（重要）：
            本实现是"结果一致性缓存"，不是"执行去重"：
              · 同一 key 的并发首次访问，**多个线程可能都会执行 _do_probe**
              · 后写入者被丢弃，最终以先写入者为缓存
              · 因此不保证每个文件只调一次 ffprobe
            若未来需要真正去重（一次探测、其余等待），应改用
            threading.Condition 或 Future 占位——成本较高，当前不实现。
        """
        key = path.resolve()
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        info = self._do_probe(path)
        with self._cache_lock:
            existing = self._cache.get(key)
            if existing is not None:
                return existing
            self._cache[key] = info
        return info

    def probe_all(self, paths: List[Path]) -> List[VideoInfo]:
        if not paths:
            return []
        workers = min(PROBE_WORKERS, len(paths))
        if workers <= 1:
            return [self.probe(p) for p in paths]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self.probe, paths))

    @staticmethod
    def _norm(value) -> str:
        return value.lower() if isinstance(value, str) and value else ''

    @staticmethod
    def _float_or_none(value) -> Optional[float]:
        try:
            f = float(value)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_zero(value) -> int:
        try:
            return int(value) if value else 0
        except (TypeError, ValueError):
            return 0

    def _do_probe(self, path: Path) -> VideoInfo:
        cmd = [
            self.runner.ffprobe, '-v', 'error',
            '-show_entries',
            'format=duration:'
            'stream=codec_type,codec_name,width,height,sample_rate,'
            'channels,channel_layout,bit_rate,duration',
            '-of', 'json', str(path)
        ]
        try:
            result = self.runner.run_raw(cmd)
            if result.returncode != 0 or not result.stdout.strip():
                logger.warning(f"⚠️ 探测失败: {path.name}")
                return VideoInfo(path=path)
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, OSError, FFmpegError) as e:
            logger.warning(f"⚠️ 探测异常: {path.name} - {e}")
            return VideoInfo(path=path)

        info = VideoInfo(path=path)
        # [v6.7 · P0-a] 关键陷阱：dict.get(key, default) 只在 key 不存在时返回
        # default；如果 key 存在但 value 是 None，返回 None。所以 '{format: None}'
        # 用 .get('format', {}) 会得到 None，接着 .get('duration') → AttributeError。
        # 用 `or {}` 才能兜住 "format: null" 的畸形 ffprobe 输出。
        fmt = data.get('format') or {}
        info.duration = self._float_or_none(fmt.get('duration'))

        # [v6.7 · P0-b] 同样的陷阱：streams 可能是 null → for ... in None 抛 TypeError
        for stream in (data.get('streams') or []):
            if not isinstance(stream, dict):
                continue
            ctype = stream.get('codec_type')
            if ctype == 'video' and info.v_codec is None:
                info.v_codec = self._norm(stream.get('codec_name')) or None
                # [v6.6 · P0-2] width 可能是 "N/A"，用容错解析
                w = self._int_or_zero(stream.get('width'))
                h = self._int_or_zero(stream.get('height'))
                if w and h:
                    info.width, info.height = w, h
                info.video_duration = self._float_or_none(stream.get('duration'))
            elif ctype == 'audio':
                if info.audio is None:
                    info.audio = AudioInfo(
                        codec=self._norm(stream.get('codec_name')),
                        sample_rate=str(stream.get('sample_rate') or ''),
                        channels=str(stream.get('channels') or ''),
                        channel_layout=self._norm(stream.get('channel_layout')),
                        bit_rate=self._int_or_zero(stream.get('bit_rate')),
                    )
                    info.audio_duration = self._float_or_none(stream.get('duration'))
                info.audio_stream_count += 1

        # [v6.7 · P1-8] format.duration 缺失时用 stream.duration 回填。
        # MKV / 部分 TS 容器的 format.duration 常为 None，但 stream.duration 有值；
        # 不回填会导致 PlanBuilder 的 --trim-end 前置校验误报"时长未知"。
        if info.duration is None:
            candidates = [info.video_duration, info.audio_duration]
            filled = [c for c in candidates if c]
            if filled:
                info.duration = max(filled)
                logger.debug(f"[v6.7] {path.name} format.duration 缺失，"
                             f"用 stream.duration 回填: {info.duration:.3f}s")

        return info


# ============================================================================
# 决策层
# ============================================================================
class PlanBuilder:
    """参数 + 探测结果 → ConcatPlan。纯函数式，不修改外部状态。"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        # [v6.6 · P0-1] 非 TTY（管道/cron/subprocess）也视为非交互，
        # 避免后续 input() 抛 EOFError。
        try:
            stdin_is_tty = sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, ValueError):
            stdin_is_tty = False
        self.non_interactive = bool(
            args.yes or args.dry_run or args.quiet or not stdin_is_tty
        )

    def build(self, videos: List[VideoInfo]) -> ConcatPlan:
        if not videos:
            raise FFmpegError("没有可处理的视频文件")

        trim_end, exact_trim = self._parse_trim()

        if trim_end is not None:
            unknown = [v.path.name for v in videos if v.duration is None]
            if unknown:
                shown = ', '.join(unknown[:3]) + ('...' if len(unknown) > 3 else '')
                raise FFmpegError(
                    f"以下文件时长未知，无法执行 --trim-end 裁剪：{shown}\n"
                    "   请确认文件完整，或去掉 --trim-end 参数")

        target_res, resolution_note, resolution_forced = self._decide_resolution(videos)

        forced_video_reencode = resolution_forced or (trim_end is not None and exact_trim)
        video_op, target_vcodec, video_note = self._decide_video_op(
            videos, forced_video_reencode, exact_trim
        )

        audio_op, source_audio_codec, audio_note = self._decide_audio_op(videos)

        plan = ConcatPlan(
            output=Path(self.args.output),
            video_op=video_op,
            audio_op=audio_op,
            target_vcodec=target_vcodec,
            target_resolution=target_res,
            trim_end=trim_end,
            exact_trim=exact_trim,
            source_audio_codec=source_audio_codec,
        )

        for note in (video_note, audio_note, resolution_note):
            if note:
                plan.notes.append(note)

        if plan.is_quick_trim and any(v.duration for v in videos):
            plan.notes.append(
                "⚠️ 快速裁剪基于关键帧，音视频边界可能有 <1s 偏差；如需精确请加 --exact-trim")

        if plan.audio_is_reencoded:
            plan.notes.append(
                f"⚠️ 音频统一为 {AUDIO_TARGET_CODEC.upper()} "
                f"{AUDIO_TARGET_BITRATE}/{AUDIO_TARGET_SAMPLE_RATE}Hz/"
                f"{AUDIO_TARGET_CHANNELS}ch（5.1 等源会被降混为立体声）")

        self._append_source_av_sync_warnings(videos, plan)
        self._append_multi_track_warning(videos, plan)
        self._append_bit_rate_warnings(videos, plan)

        return plan

    def _parse_trim(self) -> Tuple[Optional[float], bool]:
        if self.args.exact_trim and not self.args.trim_end:
            logger.warning("⚠️ --exact-trim 需配合 --trim-end 使用，已忽略")
        if not self.args.trim_end:
            return None, False
        try:
            sec = parse_duration(self.args.trim_end)
        except ValueError as e:
            raise FFmpegError(str(e))
        if sec <= 0:
            raise FFmpegError("--trim-end 时长必须大于 0")
        return sec, self.args.exact_trim

    def _decide_resolution(self, videos: List[VideoInfo]) -> Tuple[
        Optional[Tuple[int, int]], Optional[str], bool
    ]:
        if self.args.uniform_resolution is not None:
            if self.args.uniform_resolution == 'auto':
                target = self._auto_target_resolution(videos)
            else:
                m = re.match(r'^(\d+)[xX](\d+)$', self.args.uniform_resolution)
                if not m:
                    raise FFmpegError(
                        f"分辨率格式错误: {self.args.uniform_resolution}，应为 WxH")
                target = (int(m.group(1)), int(m.group(2)))
            return self._maybe_skip_reencode(videos, target)

        if self.args.resample:
            target = self._auto_target_resolution(videos)
            return self._maybe_skip_reencode(videos, target)

        if self.args.no_check:
            return None, "⚠️ --no-check 跳过分辨率检查", False

        valid_res = [v.resolution for v in videos if v.resolution]
        if not valid_res:
            return None, "⚠️ 无法获取任何视频的分辨率", False
        if len(set(valid_res)) <= 1:
            return None, None, False

        logger.info("⚠️ 输入视频的分辨率不一致（默认采用无损快速拼接）。")
        if self.non_interactive:
            return None, "非交互模式，使用快速拼接", False
        ans = input("   是否重新编码以统一分辨率？(y/N) [默认 N]: ").strip().lower()
        if ans == 'y':
            return self._maybe_skip_reencode(videos, self._auto_target_resolution(videos))
        return None, None, False

    @staticmethod
    def _maybe_skip_reencode(videos: List[VideoInfo],
                             target: Tuple[int, int]) -> Tuple[
        Optional[Tuple[int, int]], Optional[str], bool
    ]:
        valid = [v.resolution for v in videos if v.resolution]
        codecs = [v.v_codec for v in videos if v.v_codec]
        if (len(valid) == len(videos)
                and all(r == target for r in valid)
                and len(codecs) == len(videos)
                and len(set(codecs)) <= 1):
            return None, f"✅ 所有视频已是 {target[0]}x{target[1]}，跳过重编码", False
        return target, None, True

    def _decide_video_op(self, videos: List[VideoInfo],
                         forced_reencode: bool,
                         exact_trim: bool) -> Tuple[
        VideoOp, Optional[str], Optional[str]
    ]:
        if forced_reencode:
            codecs = {v.v_codec for v in videos if v.v_codec}
            reason = "精确裁剪" if exact_trim else "分辨率重编码"
            if len(codecs) == 1:
                only = next(iter(codecs))
                if only in CODEC_TO_ENCODER:
                    vcodec = CODEC_TO_ENCODER[only]
                    return VideoOp.REENCODE, vcodec, \
                        f"{reason}需要重编码（保持 {only.upper()}）"
                return VideoOp.REENCODE, 'libx264', \
                    f"{reason}需要重编码（源编码 {only.upper()}，降级为 H.264）"
            return VideoOp.REENCODE, 'libx264', \
                f"{reason}需要重编码（输入编码不一致，统一为 H.264）"

        codecs = {v.v_codec or 'unknown' for v in videos}
        if len(codecs) <= 1 and 'unknown' not in codecs:
            only = next(iter(codecs), None)
            # [v6.7 · P1-6] VP9 与 AV1 一样不能经 mpegts 可靠拼接：
            #   · TS 对 VP9 的支持是 ffmpeg 实验性特性（BSF_MAP['vp9'] 在
            #     mpegts 上的行为不稳），多数播放器/下游工具不识别
            #   · 全 VP9 输入（如 .webm）若走 COPY 会得到"能拼接但不可用"
            #     的结果，用户难以自查
            # 因此一并重编码为 H.264，把"拼完不能用"提前变成"拼完能用"。
            if only in ('av1', 'vp9'):
                return VideoOp.REENCODE, 'libx264', \
                    f"全 {only.upper()}（MP4/TS 无损拼接兼容性差），重编码为 H.264"
            return VideoOp.COPY, None, None

        if self.args.no_check:
            return VideoOp.COPY, None, \
                "⚠️ --no-check 跳过编码检查，编码不一致可能导致后续视频无画面"

        # [v6.7 · P1-5] 非交互模式不再隐式强制 H.264。
        # 修复依据：
        #   · --yes 的语义是"接受默认"，交互默认是 N（不重编码）
        #   · --quiet / --dry-run / 非 TTY 是环境推断，用户没有明确要求重编码
        #   · 隐式重编码会让用户在 CI/批处理中"意外损失画质且耗时"
        # 用户如需统一编码，显式选择 --resample / --uniform-resolution 即可。
        if self.non_interactive:
            return VideoOp.COPY, None, (
                "⚠️ 非交互模式 + 编码不一致 → 保守使用流拷贝（不重编码）。\n"
                "     若需统一编码为 H.264，请显式加 --resample 或 --uniform-resolution auto"
            )

        target = self._prompt_codec_choice(videos)
        short = ENCODER_TO_CODEC.get(target, target).upper()
        return VideoOp.REENCODE, target, \
            f"将把非 {short} 的视频重编码为 {short}"

    def _decide_audio_op(self, videos: List[VideoInfo]) -> Tuple[
        AudioOp, Optional[str], Optional[str]
    ]:
        """
        决策顺序（1~8）：
          1. 完全无音频          → COPY（-an）
          2. 部分无音频          → SILENCE
          3. --audio-reencode    → REENCODE
          4. --exact-trim        → REENCODE（音画同步对齐）
          5. --no-check          → 全 AAC 走 COPY，否则安全降级 REENCODE
          6. 参数一致性检查      → 不一致则 REENCODE
          7. 非 AAC              → REENCODE
          8. 全部通过            → COPY
        """
        any_audio = any(v.has_audio for v in videos)
        all_audio = all(v.has_audio for v in videos)

        if not any_audio:
            return AudioOp.COPY, None, "所有视频均无音频流"

        if not all_audio:
            missing = [v.path.name for v in videos if not v.has_audio]
            shown = ', '.join(missing[:3]) + ('...' if len(missing) > 3 else '')
            note = f"部分文件无音频流（{shown}），将补静音并统一重编码所有音频"
            if self.args.audio_reencode:
                note += "（--audio-reencode 已涵盖）"
            return AudioOp.SILENCE, None, note

        if self.args.audio_reencode:
            return AudioOp.REENCODE, None, "用户强制 --audio-reencode"

        if self.args.exact_trim and self.args.trim_end:
            return AudioOp.REENCODE, None, \
                "精确裁剪强制音频重编码，保证与视频精确对齐"

        if self.args.no_check:
            all_aac = all(v.audio and v.audio.codec == 'aac' for v in videos)
            if all_aac:
                return AudioOp.COPY, 'aac', \
                    "⚠️ --no-check 跳过音频检查，全 AAC 走流拷贝"
            return AudioOp.REENCODE, None, \
                "⚠️ --no-check 跳过音频检查，但音频非全 AAC，安全降级重编码"

        first = videos[0].audio
        if first is None:
            return AudioOp.COPY, None, "所有视频均无音频流"
        for v in videos[1:]:
            if v.audio is None:
                continue
            if not v.audio.core_equal(first):
                return AudioOp.REENCODE, None, f"音频核心参数不一致（{v.path.name}）"

        if first.codec != 'aac':
            return AudioOp.REENCODE, None, \
                f"源音频 {first.codec.upper()} 非 AAC，统一重编码以兼容"

        return AudioOp.COPY, first.codec, None

    def _auto_target_resolution(self, videos: List[VideoInfo]) -> Tuple[int, int]:
        if len(videos) > MAX_AUTO_RESOLUTION_FILES:
            raise FFmpegError(f"文件数超过 {MAX_AUTO_RESOLUTION_FILES}，请显式指定分辨率")
        valid = [v.resolution for v in videos if v.resolution]
        if not valid:
            raise FFmpegError("无法获取任何视频的分辨率以自动选择目标尺寸")
        landscape = [(w, h) for w, h in valid if w >= h]
        if landscape:
            return (max(r[0] for r in landscape), max(r[1] for r in landscape))
        return (max(r[0] for r in valid), max(r[1] for r in valid))

    def _prompt_codec_choice(self, videos: List[VideoInfo]) -> str:
        stats: Dict[str, Dict[str, float]] = {}
        for v in videos:
            codec = v.v_codec or 'unknown'
            st = stats.setdefault(codec, {'count': 0, 'size': 0.0})
            st['count'] += 1
            st['size'] += get_file_size_mb(v.path)

        logger.info("\n📊 检测到多种视频编码格式：")
        codec_list = list(stats.keys())
        for i, codec in enumerate(codec_list, 1):
            logger.info(f"   {i}. {codec.upper()} : "
                        f"{int(stats[codec]['count'])} 个文件, "
                        f"总大小 {stats[codec]['size']:.2f} MB")

        while True:
            try:
                choice = input(f"   请选择目标编码编号 (1-{len(codec_list)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(codec_list):
                    return CODEC_TO_ENCODER.get(codec_list[idx], 'libx264')
                logger.warning("   无效编号，请重新输入。")
            except ValueError:
                logger.warning("   请输入数字编号。")

    @staticmethod
    def _append_source_av_sync_warnings(videos: List[VideoInfo],
                                        plan: ConcatPlan) -> None:
        bad = []
        for v in videos:
            if v.video_duration and v.audio_duration:
                diff = abs(v.video_duration - v.audio_duration)
                if diff > 0.5:
                    bad.append(f"{v.path.name}(差{diff:.2f}s)")
        if bad:
            plan.notes.append(
                f"⚠️ 以下源文件音视频时长差异 >0.5s，接缝可能不同步："
                f"{', '.join(bad[:5])}" + ('...' if len(bad) > 5 else ''))

    @staticmethod
    def _append_multi_track_warning(videos: List[VideoInfo], plan: ConcatPlan) -> None:
        multi = [v.path.name for v in videos if v.audio_stream_count > 1]
        if multi:
            plan.notes.append(
                f"⚠️ {len(multi)} 个文件含多音轨，仅使用第一音轨："
                f"{', '.join(multi[:3])}" + ('...' if len(multi) > 3 else ''))

    @staticmethod
    def _append_bit_rate_warnings(videos: List[VideoInfo], plan: ConcatPlan) -> None:
        if plan.audio_op != AudioOp.COPY:
            return
        rates = {v.audio.bit_rate for v in videos if v.audio and v.audio.bit_rate > 0}
        if len(rates) > 1:
            rates_str = ', '.join(f"{r // 1000}kbps" for r in sorted(rates))
            plan.notes.append(
                f"⚠️ 音频码率存在差异（{rates_str}），但核心参数一致，将流拷贝不重编码；"
                "如需统一请加 --audio-reencode")


# ============================================================================
# 命令构造层
# ============================================================================
class TSCommandBuilder:
    """构造单文件 → MPEG-TS 的 ffmpeg 命令。"""

    TS_MUX_OPTS = ['-muxdelay', '0', '-muxpreload', '0']

    def __init__(self, plan: ConcatPlan, ffmpeg_path: str = 'ffmpeg'):
        self.plan = plan
        self.ffmpeg = ffmpeg_path

    def build(self, info: VideoInfo, output_ts: Path) -> List[str]:
        plan = self.plan
        cmd: List[str] = ffmpeg_base(self.ffmpeg)
        cmd += ['-i', str(info.path)]

        video_op = self._effective_video_op(info)
        need_silence_input = plan.audio_op == AudioOp.SILENCE and not info.has_audio

        if need_silence_input:
            cmd += ['-f', 'lavfi', '-i',
                    f'anullsrc=channel_layout=stereo:sample_rate={AUDIO_TARGET_SAMPLE_RATE}']

        if plan.trim_end is not None:
            trim_duration = info.trimmed_duration(plan.trim_end, strict=True)
            cmd += ['-t', str(trim_duration)]

        cmd += self._video_opts(info, video_op)
        cmd += self._audio_opts(info, need_silence_input)
        cmd += self._timestamp_opts()
        cmd += ['-f', 'mpegts', str(output_ts)]
        return cmd

    def _effective_video_op(self, info: VideoInfo) -> VideoOp:
        plan = self.plan
        if plan.target_resolution is not None:
            return VideoOp.REENCODE
        if plan.is_exact_trim:
            return VideoOp.REENCODE
        if plan.video_op == VideoOp.COPY:
            return VideoOp.COPY
        if plan.target_codec_short and info.v_codec == plan.target_codec_short:
            return VideoOp.COPY
        return VideoOp.REENCODE

    def _video_opts(self, info: VideoInfo, video_op: VideoOp) -> List[str]:
        if video_op == VideoOp.COPY:
            opts = ['-c:v', 'copy']
            bsf = BSF_MAP.get(info.v_codec or '')
            if bsf:
                opts += ['-bsf:v', bsf]
            return opts

        vcodec = self.plan.target_vcodec or 'libx264'
        return build_video_encode_opts(vcodec, self.plan.target_resolution)

    def _audio_opts(self, info: VideoInfo, need_silence_input: bool) -> List[str]:
        plan = self.plan
        if not info.has_audio and plan.audio_op == AudioOp.COPY:
            return ['-an']

        if need_silence_input:
            opts = ['-map', '0:v:0', '-map', '1:a']
        else:
            opts = ['-map', '0:v:0', '-map', '0:a:0']

        if plan.audio_op == AudioOp.COPY:
            return opts + ['-c:a', 'copy']

        opts += build_audio_encode_opts()
        if need_silence_input:
            opts += ['-shortest']
        else:
            opts += self._aresample_opts()
        return opts

    def _aresample_opts(self) -> List[str]:
        if self.plan.is_quick_trim:
            return ['-af', 'aresample=async=1']
        return ['-af', 'aresample=async=1:first_pts=0']

    def _timestamp_opts(self) -> List[str]:
        opts: List[str] = []
        if self.plan.is_quick_trim:
            opts += ['-copyts', '-start_at_zero']
        elif self.plan.trim_end is not None:
            opts += ['-fflags', '+genpts']
        opts += self.TS_MUX_OPTS
        return opts


def build_final_mux_audio_opts(plan: ConcatPlan) -> List[str]:
    if not plan.has_audio_expected:
        return []
    is_ts = plan.output.suffix.lower() in TS_FAMILY_SUFFIXES
    audio_is_aac = plan.audio_is_reencoded or plan.source_audio_codec == 'aac'
    if audio_is_aac:
        opts = ['-c:a', 'copy']
        if not is_ts:
            opts += ['-bsf:a', 'aac_adtstoasc']
        return opts
    return build_audio_encode_opts()


# ============================================================================
# 流程编排层
# ============================================================================
class ConcatPipeline:
    """转换 → 合并+封装 两阶段。"""

    def __init__(self, runner: FFmpegRunner, probe: MediaProbe,
                 plan: ConcatPlan, dry_run: bool = False):
        self.runner = runner
        self.probe = probe
        self.plan = plan
        self.dry_run = dry_run
        self.expected_duration = 0.0
        self._temp_dir: Optional[Path] = None
        self._file_count = 0

    def run(self, videos: List[VideoInfo]) -> None:
        self._file_count = len(videos)
        self._validate(videos)
        if self.dry_run:
            self._print_dry_run(videos)
            return

        self._temp_dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        atexit.register(self._cleanup)
        try:
            ts_files = self._convert_all(videos, self._temp_dir)
            self._merge_and_finalize(ts_files, self._temp_dir)
        finally:
            self._cleanup()

    def _validate(self, videos: List[VideoInfo]) -> None:
        out = self.plan.output
        out_resolved = out.resolve()
        for v in videos:
            try:
                if v.path.resolve() == out_resolved:
                    raise FFmpegError(f"输出文件与输入相同: {out}")
            except OSError:
                pass
        if not self.dry_run:
            self._check_disk_space(videos)

    def _check_disk_space(self, videos: List[VideoInfo]) -> None:
        input_bytes = sum(get_file_size_bytes(v.path) for v in videos)
        need_temp = int(input_bytes * 1.2)
        need_output = int(input_bytes * 1.2)

        checks = [
            ('临时目录', Path(tempfile.gettempdir()), need_temp),
            ('输出目录', nearest_existing(self.plan.output.parent), need_output),
        ]
        for label, path, need in checks:
            try:
                free = shutil.disk_usage(path).free
            except OSError:
                logger.warning(f"⚠️ 无法检查{label} ({path}) 剩余空间，跳过预检")
                continue
            if free < need:
                raise FFmpegError(
                    f"{label} ({path}) 空间不足：预计需要 {need / 1024**3:.2f} GB，"
                    f"当前可用 {free / 1024**3:.2f} GB")

    def _convert_all(self, videos: List[VideoInfo], temp_dir: Path) -> List[Path]:
        logger.info("\n🔄 [阶段1/2] 转换视频为 TS 格式...")
        builder = TSCommandBuilder(self.plan, ffmpeg_path=self.runner.ffmpeg)
        ts_files: List[Path] = []

        for idx, info in enumerate(videos, 1):
            ts_path = temp_dir / f"part_{idx - 1:04d}.ts"
            logger.info(f"   ({idx}/{len(videos)}) {info.path.name} → {ts_path.name}")
            cmd = builder.build(info, ts_path)
            try:
                self.runner.run_checked(cmd)
            except FFmpegError as e:
                raise FFmpegError(f"转换 {info.path.name} 失败：\n  {e}")

            ts_duration = self.probe.probe(ts_path).duration
            if ts_duration is None or ts_duration <= 0:
                fallback = info.trimmed_duration(self.plan.trim_end, strict=False)
                if fallback is None:
                    logger.warning(f"⚠️ {info.path.name} 时长未知，将不计入期望总时长")
                    fallback = 0.0
                ts_duration = fallback
            self.expected_duration += ts_duration
            ts_files.append(ts_path)
        return ts_files

    def _merge_and_finalize(self, ts_files: List[Path], temp_dir: Path) -> None:
        logger.info(f"\n🔗 [阶段2/2] 合并并转封装为 {self.plan.output}")
        list_file = temp_dir / "concat_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for ts in ts_files:
                path_str = str(ts.absolute())
                if '\n' in path_str or '\r' in path_str:
                    raise FFmpegError(f"临时路径含换行符（不支持）：{path_str}")
                escaped = path_str.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        self.plan.output.parent.mkdir(parents=True, exist_ok=True)

        cmd = ffmpeg_base(self.runner.ffmpeg)
        cmd += ['-f', 'concat', '-safe', '0',
                '-i', str(list_file), '-c:v', 'copy']
        cmd += build_final_mux_audio_opts(self.plan)
        cmd.append(str(self.plan.output))

        self.runner.run_checked(cmd)
        self._verify_duration()

    def _verify_duration(self) -> None:
        actual = self.probe.probe(self.plan.output).duration
        if actual is None:
            logger.warning("⚠️ 无法获取最终视频时长")
            return
        diff = abs(actual - self.expected_duration)
        tolerance = max(0.5, 0.02 * max(1, self._file_count))
        logger.info(
            f"📊 期望时长: {self.expected_duration:.2f}s  "
            f"实际时长: {actual:.2f}s  偏差: {diff:.2f}s")
        if diff > tolerance:
            logger.warning(
                f"⚠️ 偏差 ({diff:.2f}s) 超过容差 ({tolerance:.2f}s)，"
                "可能是快速裁剪的时间戳不连续导致；建议使用 --exact-trim")

    def _cleanup(self) -> None:
        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def _print_dry_run(self, videos: List[VideoInfo]) -> None:
        logger.info("\n[DRY-RUN] 以下命令将执行：")
        builder = TSCommandBuilder(self.plan, ffmpeg_path=self.runner.ffmpeg)
        temp_root = Path(tempfile.gettempdir())
        for idx, info in enumerate(videos, 1):
            ts_path = temp_root / f"part_{idx - 1:04d}.ts"
            cmd = builder.build(info, ts_path)
            logger.info(f"   [{idx}/{len(videos)}] {' '.join(cmd)}")

        cmd = ffmpeg_base(self.runner.ffmpeg)
        cmd += ['-f', 'concat', '-safe', '0',
                '-i', str(temp_root / 'concat_list.txt'), '-c:v', 'copy']
        cmd += build_final_mux_audio_opts(self.plan)
        cmd.append(str(self.plan.output))
        logger.info(f"   [MERGE] {' '.join(cmd)}")


# ============================================================================
# 计划汇总
# ============================================================================
def print_plan_summary(plan: ConcatPlan) -> None:
    logger.info("\n📋 拼接计划汇总")
    logger.info("─" * 60)

    v = "流拷贝（无损）" if plan.video_op == VideoOp.COPY else f"重编码 → {plan.target_vcodec}"
    if plan.target_resolution:
        v += f" @ {plan.target_resolution[0]}x{plan.target_resolution[1]}"
    logger.info(f"   视频：{v}")

    a = {AudioOp.COPY: "流拷贝（无损）",
         AudioOp.REENCODE: "统一重编码",
         AudioOp.SILENCE: "统一重编码 + 补静音"}[plan.audio_op]
    logger.info(f"   音频：{a}")

    if plan.trim_end is not None:
        mode = "精确" if plan.exact_trim else "快速"
        logger.info(f"   裁剪：每个片段末尾 {plan.trim_end}s（{mode}模式）")

    logger.info(f"   输出：{plan.output}")

    if plan.notes:
        logger.info("─" * 60)
        for note in plan.notes:
            logger.info(f"   {note}")
    logger.info("─" * 60)


# ============================================================================
# CLI
# ============================================================================
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"视频拼接工具 v{__version__}",
        epilog="示例：\n  %(prog)s *.mp4 -o merged.mp4\n  %(prog)s --trim-end 5 *.mp4"
    )
    parser.add_argument('inputs', nargs='*', default=['.'],
                        help='视频文件或目录（可多个）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT,
                        help=f'输出文件路径（默认 {DEFAULT_OUTPUT}）')
    parser.add_argument('-e', '--extensions', nargs='+', default=list(DEFAULT_EXTENSIONS),
                        help='支持的视频扩展名')
    # [v6.7 · P1-7] 明确 --no-check 只跳过"分辨率/视频编码"，
    # 音频仍会保证可拼接性（全 AAC → COPY，否则 REENCODE）
    parser.add_argument('--no-check', action='store_true',
                        help='跳过分辨率/视频编码一致性检查与交互'
                             '（音频仍会保证可拼接性：全 AAC 走 COPY，否则安全降级 REENCODE）')
    parser.add_argument('--resample', action='store_true',
                        help='强制重新编码并统一分辨率（自动选择）')
    parser.add_argument('--uniform-resolution', nargs='?', const='auto', default=None,
                        help='手动指定分辨率 WxH，或 auto')
    parser.add_argument('--trim-end', type=str, default=None,
                        help='裁剪末尾指定时长（秒或 HH:MM:SS）')
    parser.add_argument('--exact-trim', action='store_true',
                        help='精确裁剪（重新编码，音视频同步对齐）')
    parser.add_argument('--audio-reencode', action='store_true',
                        help='强制重新编码音频')
    parser.add_argument('--overwrite', action='store_true',
                        help='覆盖已存在的输出文件')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印命令，不执行')
    parser.add_argument('--ffmpeg', default='ffmpeg',
                        help='ffmpeg 可执行文件路径')
    parser.add_argument('--ffprobe', default='ffprobe',
                        help='ffprobe 可执行文件路径')
    parser.add_argument('--quiet', action='store_true',
                        help='只输出警告和错误')
    parser.add_argument('--verbose', action='store_true',
                        help='输出调试信息（包括每条 ffmpeg 命令与异常堆栈）')
    # [v6.7 · P1-5] 明确 --yes 在编码不一致时保持流拷贝
    parser.add_argument('--yes', action='store_true',
                        help='非交互模式，跳过所有交互确认；'
                             '编码不一致时保持流拷贝（如需统一编码，请加 --resample）')
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    setup_logging(quiet=args.quiet and not args.dry_run, verbose=args.verbose)

    if not _check_executable(args.ffmpeg):
        logger.error(f"❌ 找不到 ffmpeg: {args.ffmpeg}")
        logger.error("   请用 --ffmpeg 指定路径，或确保其在 PATH 中")
        return 1
    if not _check_executable(args.ffprobe):
        logger.error(f"❌ 找不到 ffprobe: {args.ffprobe}")
        logger.error("   请用 --ffprobe 指定路径，或确保其在 PATH 中")
        return 1

    output_path = Path(args.output)
    if output_path.exists():
        if output_path.is_dir():
            logger.error(f"❌ 输出路径是目录: {output_path}")
            logger.error("   请指定一个文件路径，例如 output.mp4")
            return 1
        if not args.overwrite and not args.dry_run:
            logger.error(f"❌ 输出文件已存在: {output_path}")
            logger.error("   使用 --overwrite 覆盖")
            return 1

    runner = FFmpegRunner(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    probe = MediaProbe(runner)
    atexit.register(runner.shutdown)

    extensions = {ext.lower() for ext in args.extensions}
    logger.info("🔍 正在收集视频文件...")
    try:
        paths = collect_video_files(args.inputs, extensions)
    except FFmpegError as e:
        logger.error(f"❌ {e}")
        return 1
    if not paths:
        logger.error("❌ 未找到任何视频文件")
        return 1

    logger.info(f"📁 找到 {len(paths)} 个文件，按名称排序：")
    for i, p in enumerate(paths, 1):
        logger.info(f"   {i}. {p.name}")

    logger.info("\n🔬 正在探测媒体信息...")
    videos = probe.probe_all(paths)

    # [v6.6 · P0-1] 分层捕获：先 KeyboardInterrupt（BaseException），
    # 再 FFmpegError（业务），最后 EOFError/OSError（input() 交互失败兜底）。
    try:
        plan = PlanBuilder(args).build(videos)
    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断")
        return 130
    except FFmpegError as e:
        logger.error(f"❌ {e}")
        if args.verbose:
            logger.debug("\n" + traceback.format_exc())
        return 1
    except (EOFError, OSError) as e:
        logger.error(f"❌ 交互输入失败: {e}")
        logger.error("   建议加 --yes 使用非交互模式，或用管道之外的终端运行")
        return 1

    print_plan_summary(plan)

    try:
        ConcatPipeline(runner, probe, plan, dry_run=args.dry_run).run(videos)
    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断")
        return 130
    except FFmpegError as e:
        logger.error(f"\n❌ {e}")
        if args.verbose:
            logger.debug("\n" + traceback.format_exc())
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
