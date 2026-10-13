import io
path = r'c:\Users\a\testhub_workspace\testhub_platform\frontend\src\api\ui_automation.js'
append = '''
// ==================== Setup Templates ====================

// 获取前置模板列表
export function getSetupTemplates(params = {}) {
  return request({
    url: '/ui-automation/setup-templates/',
    method: 'get',
    params
  })
}

// 获取单个前置模板
export function getSetupTemplate(id) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'get'
  })
}

// 创建前置模板
export function createSetupTemplate(data) {
  return request({
    url: '/ui-automation/setup-templates/',
    method: 'post',
    data
  })
}

// 更新前置模板
export function updateSetupTemplate(id, data) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'put',
    data
  })
}

// 删除前置模板
export function deleteSetupTemplate(id) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'delete'
  })
}

// ==================== 语音输入 / 自然语言 AI ====================

// 语音转文字
export function speechTranscribe(formData) {
  return request({
    url: '/ui-automation/speech/transcribe/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 自然语言解析为步骤
export function speechParse(data) {
  return request({
    url: '/ui-automation/speech/parse/',
    method: 'post',
    data
  })
}

// 基于自然语音描述的元素定位
export function speechElementLocate(data) {
  return request({
    url: '/ui-automation/speech/locate/',
    method: 'post',
    data,
    timeout: 120000
  })
}
'''
with io.open(path, 'a', encoding='utf-8') as f:
    f.write(append)
print('ok')
