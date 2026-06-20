#!/bin/bash
script_dir=$(dirname "$(readlink -f "$0")")
# Qwen3-TTS-12Hz
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-Tokenizer-12Hz  --local_dir "$script_dir/Qwen/Qwen3-TTS-Tokenizer-12Hz"
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --local_dir "$script_dir/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local_dir "$script_dir/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base --local_dir "$script_dir/Qwen/Qwen3-TTS-12Hz-1.7B-Base"
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --local_dir "$script_dir/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --local_dir "$script_dir/Qwen/Qwen3-TTS-12Hz-0.6B-Base"
