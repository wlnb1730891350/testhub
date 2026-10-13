<template>
  <div class="speech-input-container">
    <div class="speech-header">
      <h3>🎤 语音输入</h3>
      <div class="speech-status">
        <span v-if="isRecording" class="recording-indicator">
          <span class="pulse"></span>
          正在录音...
        </span>
        <span v-else-if="isProcessing" class="processing-indicator">
          处理中...
        </span>
        <span v-else class="ready-indicator">
          点击麦克风开始输入
        </span>
      </div>
    </div>

    <div class="speech-controls">
      <button
        class="record-button"
        :class="{ recording: isRecording }"
        @click="toggleRecording"
        :disabled="isProcessing"
      >
        <svg v-if="!isRecording" viewBox="0 0 24 24" width="24" height="24">
          <path fill="currentColor" d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
          <path fill="currentColor" d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
        </svg>
        <svg v-else viewBox="0 0 24 24" width="24" height="24">
          <rect fill="currentColor" x="6" y="6" width="12" height="12"/>
        </svg>
      </button>

      <div class="language-select">
        <select v-model="selectedLanguage" :disabled="isRecording">
          <option value="zh">中文</option>
          <option value="en">English</option>
          <option value="auto">自动检测</option>
        </select>
      </div>
    </div>

    <div class="transcription-result" v-if="transcription">
      <div class="result-header">
        <span class="label">识别结果：</span>
        <span class="confidence" v-if="confidence">
          置信度: {{ (confidence * 100).toFixed(0) }}%
        </span>
      </div>
      <div class="result-text">{{ transcription }}</div>
      <div class="result-actions">
        <button class="action-btn" @click="retry">
          <svg viewBox="0 0 24 24" width="16" height="16">
            <path fill="currentColor" d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
          </svg>
          重新识别
        </button>
        <button class="action-btn primary" @click="confirmResult">
          确认使用
        </button>
      </div>
    </div>

    <div class="error-message" v-if="error">
      <span class="error-icon">⚠️</span>
      <span>{{ error }}</span>
    </div>

    <div class="tips">
      <h4>💡 语音输入技巧：</h4>
      <ul>
        <li>清晰说出操作步骤，例如："点击搜索按钮"</li>
        <li>支持多步骤："打开登录页面，输入用户名，点击登录按钮"</li>
        <li>输入值请用引号标注："输入 'test@example.com' 到邮箱输入框"</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { speechTranscribe } from '@/api/ui_automation'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'transcribed', 'error'])

const isRecording = ref(false)
const isProcessing = ref(false)
const transcription = ref('')
const normalizedText = ref('')
const confidence = ref(null)
const error = ref('')
const selectedLanguage = ref('zh')

let mediaRecorder = null
let audioChunks = []
let recognition = null

// 初始化 Web Speech API（浏览器原生支持）
const initSpeechRecognition = () => {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    console.warn('当前浏览器不支持语音识别')
    return false
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
  recognition = new SpeechRecognition()
  recognition.continuous = false
  recognition.interimResults = false
  recognition.lang = selectedLanguage.value === 'auto' ? 'zh-CN' : selectedLanguage.value

  recognition.onresult = (event) => {
    const result = event.results[0]
    const text = result[0].transcript
    transcription.value = text
    confidence.value = result[0].confidence || 0.95
    isRecording.value = false
    
    // 发送到后端进行文本规范化
    processTranscription(text)
  }

  recognition.onerror = (event) => {
    console.error('语音识别错误:', event.error)
    error.value = `语音识别错误: ${event.error}`
    isRecording.value = false
    emit('error', error.value)
  }

  recognition.onend = () => {
    isRecording.value = false
  }

  return true
}

// 切换录音状态
const toggleRecording = async () => {
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

// 开始录音
const startRecording = async () => {
  try {
    error.value = ''
    transcription.value = ''
    confidence.value = null

    // 优先使用 Web Speech API
    if (recognition) {
      recognition.lang = selectedLanguage.value === 'auto' ? 'zh-CN' : selectedLanguage.value
      recognition.start()
      isRecording.value = true
      return
    }

    // 降级：使用 MediaRecorder + 后端 Whisper API
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(stream)
    audioChunks = []

    mediaRecorder.ondataavailable = (event) => {
      audioChunks.push(event.data)
    }

    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
      await uploadAudio(audioBlob)
      stream.getTracks().forEach(track => track.stop())
    }

    mediaRecorder.start()
    isRecording.value = true

  } catch (err) {
    console.error('启动录音失败:', err)
    error.value = '无法访问麦克风，请检查权限设置'
    emit('error', error.value)
  }
}

// 停止录音
const stopRecording = () => {
  if (recognition && isRecording.value) {
    recognition.stop()
  }
  if (mediaRecorder && isRecording.value) {
    mediaRecorder.stop()
  }
  isRecording.value = false
}

// 上传音频到后端
const uploadAudio = async (audioBlob) => {
  isProcessing.value = true
  error.value = ''

  try {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')
    formData.append('language', selectedLanguage.value)

    const response = await speechTranscribe(formData)
    
    if (response.data && response.data.success) {
      const data = response.data.data
      transcription.value = data.text
      normalizedText.value = data.normalized_text
      confidence.value = data.confidence || 0.95
      
      emit('transcribed', {
        text: data.normalized_text || data.text,
        original: data.text,
        confidence: data.confidence
      })
      
      ElMessage.success('语音识别成功')
    } else {
      throw new Error(response.data?.msg || '识别失败')
    }
  } catch (err) {
    console.error('语音识别失败:', err)
    error.value = err.response?.data?.msg || err.message || '语音识别失败'
    emit('error', error.value)
  } finally {
    isProcessing.value = false
  }
}

// 处理识别文本（规范化）
const processTranscription = async (text) => {
  isProcessing.value = true
  try {
    // 可以调用后端自然语言解析 API
    // const response = await speechParse({ text })
    // normalizedText.value = response.data.data.steps
    normalizedText.value = text
    emit('transcribed', {
      text,
      original: text,
      confidence: confidence.value
    })
  } catch (err) {
    console.error('文本处理失败:', err)
  } finally {
    isProcessing.value = false
  }
}

// 重新识别
const retry = () => {
  transcription.value = ''
  normalizedText.value = ''
  confidence.value = null
  error.value = ''
  startRecording()
}

// 确认使用结果
const confirmResult = () => {
  const finalText = normalizedText.value || transcription.value
  if (!finalText) {
    ElMessage.warning('请先进行语音识别')
    return
  }
  emit('update:modelValue', finalText)
  ElMessage.success('已确认语音输入')
}

// 监听语言变化
const updateLanguage = () => {
  if (recognition) {
    recognition.lang = selectedLanguage.value === 'auto' ? 'zh-CN' : selectedLanguage.value
  }
}

onMounted(() => {
  initSpeechRecognition()
})

onUnmounted(() => {
  if (recognition) {
    recognition.stop()
  }
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
})

// 暴露方法给父组件
defineExpose({
  startRecording,
  stopRecording,
  retry
})
</script>

<style scoped lang="scss">
.speech-input-container {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 20px;
  background: #fafafa;
}

.speech-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  
  h3 {
    margin: 0;
    font-size: 16px;
    color: #303133;
  }
}

.speech-status {
  font-size: 14px;
  
  .recording-indicator {
    color: #f56c6c;
    display: flex;
    align-items: center;
    gap: 8px;
    
    .pulse {
      width: 8px;
      height: 8px;
      background: #f56c6c;
      border-radius: 50%;
      animation: pulse 1.5s ease-in-out infinite;
    }
  }
  
  .processing-indicator {
    color: #e6a23c;
  }
  
  .ready-indicator {
    color: #909399;
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

.speech-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.record-button {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 2px solid #dcdfe6;
  background: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
  color: #606266;
  
  &:hover:not(:disabled) {
    border-color: #409eff;
    color: #409eff;
    transform: scale(1.05);
  }
  
  &:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }
  
  &.recording {
    border-color: #f56c6c;
    color: #f56c6c;
    background: #fef0f0;
    animation: record-pulse 1s ease-in-out infinite;
  }
}

@keyframes record-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4); }
  50% { box-shadow: 0 0 0 12px rgba(245, 108, 108, 0); }
}

.language-select {
  select {
    padding: 8px 12px;
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    font-size: 14px;
    outline: none;
    cursor: pointer;
    
    &:focus {
      border-color: #409eff;
    }
  }
}

.transcription-result {
  background: white;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  
  .label {
    font-weight: 500;
    color: #606266;
  }
  
  .confidence {
    font-size: 12px;
    color: #67c23a;
    background: #f0f9eb;
    padding: 2px 8px;
    border-radius: 4px;
  }
}

.result-text {
  font-size: 16px;
  color: #303133;
  line-height: 1.6;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 12px;
}

.result-actions {
  display: flex;
  gap: 8px;
  
  .action-btn {
    padding: 8px 16px;
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    background: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    color: #606266;
    
    &:hover {
      border-color: #409eff;
      color: #409eff;
    }
    
    &.primary {
      background: #409eff;
      border-color: #409eff;
      color: white;
      
      &:hover {
        background: #66b1ff;
      }
    }
  }
}

.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 4px;
  color: #f56c6c;
  font-size: 14px;
  margin-bottom: 16px;
}

.tips {
  margin-top: 20px;
  padding: 12px;
  background: #ecf5ff;
  border-left: 4px solid #409eff;
  border-radius: 4px;
  
  h4 {
    margin: 0 0 8px 0;
    font-size: 14px;
    color: #409eff;
  }
  
  ul {
    margin: 0;
    padding-left: 20px;
    
    li {
      font-size: 13px;
      color: #606266;
      line-height: 1.8;
    }
  }
}
</style>
