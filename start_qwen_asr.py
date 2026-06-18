# start_qwen_asr.py
import torch
import gradio as gr
import librosa
import numpy as np
import os
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    from qwen_asr import Qwen3ASRModel, parse_asr_output
    print("✅ 成功导入 qwen_asr.Qwen3ASRModel")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("\n请确保 qwen-asr 包已正确安装:")
    print("  pip install -U qwen-asr")
    sys.exit(1)

# 模型路径
MODEL_PATH = os.path.expanduser('~/Downloads/Qwen3-ASR-1.7B')

print("=" * 70)
print("Qwen3-ASR 语音识别系统 (最终版)")
print("=" * 70)
print(f"模型路径: {MODEL_PATH}")

# 检查路径
if not os.path.exists(MODEL_PATH):
    print(f"❌ 错误: 模型路径不存在！")
    print(f"请确认路径: {MODEL_PATH}")
    sys.exit(1)

# 检测设备
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"\n📊 硬件信息:")
print(f"   - 设备: {device}")
if torch.cuda.is_available():
    print(f"   - GPU: {torch.cuda.get_device_name(0)}")
    print(f"   - 显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

print("\n⏳ 正在加载模型...")

try:
    # 加载模型
    print("📥 使用 Qwen3ASRModel.from_pretrained() 加载模型...")
    
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    
    model = Qwen3ASRModel.from_pretrained(
        MODEL_PATH,
        dtype=dtype,
        device_map="cuda:0" if torch.cuda.is_available() else "cpu",
        max_inference_batch_size=32,
        max_new_tokens=256
    )
    
    print("✅ 模型加载成功！")
    print(f"   模型类型: {type(model)}")
    
except Exception as e:
    print(f"❌ 加载失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

def transcribe_audio(audio_input):
    """转录音频文件"""
    if audio_input is None:
        return "请上传音频文件"
    
    try:
        print(f"\n🔄 处理音频: {os.path.basename(audio_input)}")
        
        # 加载音频
        audio, sr = librosa.load(audio_input, sr=16000)
        duration = len(audio) / 16000
        print(f"   时长: {duration:.2f}秒")
        
        # 识别
        print("   🔍 识别中...")
        results = model.transcribe(
            audio=audio_input,
            language=None,
        )
        
        # 处理结果
        if results and len(results) > 0:
            first_result = results[0]
            lang = getattr(first_result, 'language', 'unknown')
            text = getattr(first_result, 'text', str(first_result))
            
            print(f"   ✅ 完成 (语言: {lang})")
            return f"【识别结果】\n{text}\n\n【检测语言】{lang}"
        else:
            return "未识别到有效语音"
        
    except Exception as e:
        error_msg = f"❌ 识别失败: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return error_msg

# 创建Web界面 - 移除不兼容的参数
with gr.Blocks(title="Qwen3-ASR 语音识别", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🎤 Qwen3-ASR 语音识别系统
    ### 支持中文及22种方言
    
    **📝 使用说明**：
    1. 上传音频文件或直接录制
    2. 点击"开始识别"按钮
    3. 等待识别结果显示
    """)
    
    with gr.Row():
        with gr.Column(scale=1):
            audio_input = gr.Audio(
                type="filepath",
                label="上传或录制音频",
                sources=["upload", "microphone"]
            )
            submit_btn = gr.Button("🎯 开始识别", variant="primary", size="lg")
        
        with gr.Column(scale=1):
            text_output = gr.Textbox(
                label="识别结果",
                lines=12,
                placeholder="识别结果将显示在这里..."
                # 移除了 show_copy_button 参数
            )
    
    submit_btn.click(
        fn=transcribe_audio,
        inputs=audio_input,
        outputs=text_output
    )
    
    gr.Markdown("""

    ### ⚠️ 注意事项
    - 建议音频时长控制在30秒以内
    - 支持格式：WAV、MP3、FLAC、M4A等
    - 模型会自动将音频重采样为16kHz
    """)

print("\n" + "=" * 70)
print("🚀 服务启动成功！")
print("🌐 请访问: http://127.0.0.1:7860")
print("=" * 70)
print("\n⏹️ 按 Ctrl+C 停止服务\n")

# 启动服务
demo.launch(
    server_name="127.0.0.1",
    server_port=7860,
    share=False
)
