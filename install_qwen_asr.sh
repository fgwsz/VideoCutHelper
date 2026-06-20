#!/bin/bash
script_dir=$(dirname "$(readlink -f "$0")")
#安装python-venv
sudo apt update
sudo apt install python3.10-venv
cd "$script_dir"
python3 -m venv asr_env
#进入asr_env环境
source asr_env/bin/activate
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install --upgrade pip
pip install qwen-asr
python -c "from qwen_asr import Qwen3ASRModel; print('导入成功')"
#webrtcvad
pip install webrtcvad
#退出asr_env环境
deactivate
