#!/bin/bash
# =============================================================================
# 一键运行 qwen_asr_aligner_srt.py（自动激活并退出 asr_env 虚拟环境）
# 使用方法: ./generate_srt.sh <video_path> [选项]
# 若不提供任何参数，则自动显示帮助信息（等同于 ./generate_srt.sh -h）
# =============================================================================

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/asr_env"
PYTHON_SCRIPT="$SCRIPT_DIR/qwen_asr_aligner_srt.py"

# ---------- 参数检查：若未提供任何参数，自动添加 -h ----------
if [ $# -eq 0 ]; then
    echo "ℹ️ 未提供参数，自动显示帮助信息..."
    set -- -h   # 将参数替换为 -h，后续转发给 Python 脚本
fi

# ---------- 检查虚拟环境 ----------
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ 错误: 虚拟环境目录 '$VENV_DIR' 不存在。"
    echo "   请先运行 ./install_qwen_asr.sh 创建虚拟环境并安装依赖。"
    exit 1
fi

# ---------- 检查 Python 脚本 ----------
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "❌ 错误: Python 脚本 '$PYTHON_SCRIPT' 不存在。"
    echo "   请确保 qwen_asr_aligner_srt.py 与本脚本位于同一目录。"
    exit 1
fi

# ---------- 在子 Shell 中运行 ----------
(
    echo "🔧 激活虚拟环境 asr_env ..."
    source "$VENV_DIR/bin/activate"

    echo "🚀 运行 qwen_asr_aligner_srt.py ..."
    python "$PYTHON_SCRIPT" "$@"
    exit_code=$?

    echo "🔧 退出虚拟环境 asr_env ..."
    deactivate

    exit $exit_code
)

# 捕获子 Shell 的退出码
final_exit=$?
if [ $final_exit -ne 0 ]; then
    echo "⚠️ 程序运行失败，返回码: $final_exit"
else
    echo "✅ 程序运行完成，虚拟环境已退出。"
fi
exit $final_exit
