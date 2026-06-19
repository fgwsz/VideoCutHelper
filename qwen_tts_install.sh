# Qwen3-TTS-12Hz
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-Tokenizer-12Hz  --local_dir ~/Downloads/Qwen3-TTS-12Hz/Qwen3-TTS-Tokenizer-12Hz 
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --local_dir ~/Downloads/Qwen3-TTS-12Hz-1.7B-CustomVoice
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local_dir ~/Downloads/Qwen3-TTS-12Hz/Qwen3-TTS-12Hz-1.7B-VoiceDesign
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base --local_dir ~/Downloads/Qwen3-TTS-12Hz/Qwen3-TTS-12Hz-1.7B-Base
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --local_dir ~/Downloads/Qwen3-TTS-12Hz/Qwen3-TTS-12Hz-0.6B-CustomVoice
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base --local_dir ~/Downloads/Qwen3-TTS-12Hz/Qwen3-TTS-12Hz-0.6B-Base
#安装python-venv
sudo apt update
sudo apt install python3.10-venv
python3 -m venv tts_env
#不需要时,执行 deactivate 退出(tts_env)环境
source tts_env/bin/activate
pip install --upgrade pip
pip install qwen-tts
sudo apt install -y sox   # 系统依赖
#pip install -U flash-attn --no-build-isolation
python -c "from qwen_tts import Qwen3TTSModel; print('导入成功')"
#安装cpu版本torch
pip uninstall torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
