#安装python-venv
sudo apt update
sudo apt install python3.10-venv
python3 -m venv tts_env
#进入tts_env环境
source tts_env/bin/activate
pip install --upgrade pip
pip install qwen-tts
sudo apt install -y sox   # 系统依赖
python -c "from qwen_tts import Qwen3TTSModel; print('导入成功')"
#安装cpu版本torch
pip uninstall torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
#退出tts_env环境
deactivate
