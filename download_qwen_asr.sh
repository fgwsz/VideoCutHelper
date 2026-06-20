#!/bin/bash
script_dir=$(dirname "$(readlink -f "$0")")
# Download through ModelScope (recommended for users in Mainland China)
pip install -U modelscope
modelscope download --model Qwen/Qwen3-ASR-1.7B  --local_dir "$script_dir/Qwen/Qwen3-ASR-1.7B"
modelscope download --model Qwen/Qwen3-ASR-0.6B --local_dir ."$script_dir/Qwen/Qwen3-ASR-0.6B"
modelscope download --model Qwen/Qwen3-ForcedAligner-0.6B --local_dir "$script_dir/Qwen/Qwen3-ForcedAligner-0.6B"
