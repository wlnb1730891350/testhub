import io
path = r'c:\Users\a\testhub_workspace\testhub_platform\frontend\src\api\ui_automation.js'
append = '''

// ==================== AI 用例批量/录制/导入 ====================

// 批量执行 AI 用例
export function batchRunAICases(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-run/',
    method: 'post',
    data
  })
}

// 批量录制 AI 用例
export function batchRecordAICases(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-record/',
    method: 'post',
    data
  })
}

// 获取 AI 录制动作
export function getAIRecordingActions(recordId) {
  return request({
    url: `/ui-automation/ai-execution-records/${recordId}/ai-recording-actions/`,
    method: 'get'
  })
}

// 保存 AI 录制
export function saveAIRecording(recordId, data) {
  return request({
    url: `/ui-automation/ai-execution-records/${recordId}/save-ai-recording/`,
    method: 'post',
    data
  })
}

// 导入 AI 用例
export function importAICases(formData) {
  return request({
    url: '/ui-automation/ai-cases/import-cases/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
'''
with io.open(path, 'a', encoding='utf-8') as f:
    f.write(append)
print('ok')
