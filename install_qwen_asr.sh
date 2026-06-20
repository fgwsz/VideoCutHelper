#安装python-venv
sudo apt update
sudo apt install python3.10-venv
python3 -m venv asr_env
#进入asr_env环境
source asr_env/bin/activate
pip install --upgrade pip
pip install qwen-asr
python -c "from qwen_asr import Qwen3ASRModel; print('导入成功')"
#aeneas
#sudo apt install libespeak-dev
#pip install aeneas
#webrtcvad
#pip install webrtcvad
#退出asr_env环境
deactivate
