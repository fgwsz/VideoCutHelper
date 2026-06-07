#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================================
                    时间差值计算器（视频剪辑专用）
================================================================================

功能描述
--------
本脚本用于计算两个时间点之间的差值（第一个时间减去第二个时间），
特别适合视频剪辑中的时间码计算（如剪辑入点、出点、片段长度等）。

支持自动识别时间格式，根据冒号（:）的数量自动解析为：
    - 无冒号       → 秒（可带小数或毫秒，如 45.678）
    - 1个冒号      → 分:秒（可带毫秒，如 1:23.456）
    - 2个冒号      → 时:分:秒（可带毫秒，如 1:23:45.678）

输出格式统一为 [+/-]HH:MM:SS.mmm （小时、分钟、秒各2位，毫秒3位）。

交互特性
--------
- 输入解析失败时会提示重新输入，不会崩溃退出。
- 每次计算完成后会询问是否继续计算（y/n），若输入 y 则重新开始，否则退出。

依赖
----
仅需 Python 3.6+ 标准库，无第三方依赖。

================================================================================
"""

import sys

def time_to_milliseconds(time_str: str) -> int:
    """
    将时间字符串转换为毫秒数（整数）。若格式无效，返回 None。
    """
    time_str = time_str.strip()
    if not time_str:
        return None
    ms_part = 0
    try:
        if '.' in time_str:
            main_part, ms_str = time_str.split('.')
            ms_str = (ms_str + '000')[:3]
            ms_part = int(ms_str)
        else:
            main_part = time_str

        parts = main_part.split(':')
        total_seconds = 0.0
        if len(parts) == 1:
            total_seconds = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            total_seconds = minutes * 60 + seconds
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            total_seconds = hours * 3600 + minutes * 60 + seconds
        else:
            return None
        return int(round(total_seconds * 1000)) + ms_part
    except (ValueError, IndexError):
        return None

def milliseconds_to_time(ms: int) -> str:
    """将毫秒数转换为标准时间码格式 HH:MM:SS.mmm。"""
    sign = '-' if ms < 0 else ''
    abs_ms = abs(ms)
    hours = abs_ms // 3_600_000
    abs_ms %= 3_600_000
    minutes = abs_ms // 60_000
    abs_ms %= 60_000
    seconds = abs_ms // 1000
    milliseconds = abs_ms % 1000
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

def get_valid_time(prompt: str) -> int:
    """循环提示用户输入，直到获得合法毫秒值，返回毫秒整数。"""
    while True:
        raw = input(prompt).strip()
        ms = time_to_milliseconds(raw)
        if ms is not None:
            return ms
        print("格式错误！支持格式示例: 45.678, 1:23.456, 1:23:45.678 (无毫秒也可)")

def main():
    print("=== 时间差值计算器（视频剪辑专用）===")
    print("输入格式示例：\n"
          "  45.678          (秒.毫秒)\n"
          "  1:23.456        (分:秒.毫秒)\n"
          "  1:23:45.678     (时:分:秒.毫秒)\n"
          "不输入毫秒也可，如 45, 1:23, 1:23:45\n")
    while True:
        ms1 = get_valid_time("第一个时间 > ")
        ms2 = get_valid_time("第二个时间 > ")
        diff_ms = ms1 - ms2
        print(f"\n差值 = {milliseconds_to_time(diff_ms)}\n")

        again = input("是否继续计算？(y/n): ").strip().lower()
        if again not in ('y', 'yes'):
            print("退出。")
            break
        print()  # 空一行分隔

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断，退出。")
        sys.exit(0)
