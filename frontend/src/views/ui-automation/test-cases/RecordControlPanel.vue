<template>
  <el-dialog
    v-model="visible"
    title="录制回放"
    width="900px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <div v-if="!isRecording && recordedActions.length === 0" class="record-setup">
      <el-form :model="recordForm" label-width="100px">
        <el-form-item label="目标 URL">
          <el-input v-model="recordForm.startUrl" placeholder="https://example.com" />
        </el-form-item>
        <el-form-item label="浏览器">
          <el-select v-model="recordForm.browser" style="width: 100%">
            <el-option label="Chromium" value="chromium" />
            <el-option label="Firefox" value="firefox" />
            <el-option label="WebKit" value="webkit" />
          </el-select>
        </el-form-item>
        <el-form-item label="无头模式">
          <el-switch v-model="recordForm.headless" />
        </el-form-item>
      </el-form>

      <div class="setup-actions">
        <el-button type="danger" size="large" :loading="starting" @click="startRecording">
          <el-icon><VideoCamera /></el-icon>
          开始录制
        </el-button>
      </div>
    </div>

    <div v-else class="record-active">
      <div class="record-status-bar">
        <div class="status-left">
          <span class="rec-dot" :class="{ active: isRecording }"></span>
          <span class="status-text">{{ isRecording ? '录制中...' : '录制已停止' }}</span>
          <el-tag v-if="isRecording" type="danger" size="small" effect="dark">REC</el-tag>
          <el-tag v-else type="info" size="small">STOPPED</el-tag>
        </div>

        <div class="status-right">
          <span class="actions-count">已录制 {{ recordedActions.length }} 个操作</span>
          <el-button v-if="isRecording" type="danger" size="small" @click="stopRecording">
            <el-icon><VideoPause /></el-icon>
            停止录制
          </el-button>
          <el-button v-else size="small" @click="resetRecording">
            <el-icon><RefreshLeft /></el-icon>
            重新录制
          </el-button>
        </div>
      </div>

      <div v-if="!isRecording && recordedActions.length > 0" class="action-filter-bar">
        <div class="filter-left">
          <el-checkbox
            :model-value="allActionsSelected"
            :indeterminate="isActionSelectionIndeterminate"
            @change="toggleSelectAllActions"
          >
            全选
          </el-checkbox>
          <span class="filter-summary">已选 {{ selectedActionIndexes.length }} / {{ recordedActions.length }} 个步骤</span>
          <span v-if="suggestedFilteredCount > 0" class="filter-hint">
            已识别 {{ suggestedFilteredCount }} 个疑似噪音步骤
          </span>
        </div>

        <div class="filter-right">
          <el-button size="small" type="success" plain @click="applySuggestedSelection">
            智能保留
          </el-button>
          <span class="filter-label">快捷保留</span>
          <el-button size="small" @click="keepLastActions(3)">最后 3 步</el-button>
          <el-button size="small" @click="keepLastActions(5)">最后 5 步</el-button>
          <el-button size="small" @click="keepLastActions(10)">最后 10 步</el-button>
        </div>
      </div>

      <div v-if="!isRecording && suggestedSegments.length > 0" class="segment-bar">
        <span class="segment-label">业务段</span>
        <el-button
          v-for="segment in suggestedSegments"
          :key="segment.key"
          size="small"
          plain
          @click="selectSegment(segment)"
        >
          {{ segment.label }} · {{ segment.start + 1 }}-{{ segment.end + 1 }}
        </el-button>
      </div>

      <div ref="actionsListRef" class="actions-list">
        <div
          v-for="(action, index) in recordedActions"
          :key="index"
          class="action-item"
          :class="{
            'action-item-selected': isActionSelected(index),
            'action-item-suggested-skip': hasSuggestedSkip(index) && !isActionSelected(index)
          }"
          @click="toggleActionSelection(index)"
        >
          <div class="action-check">
            <el-checkbox
              :model-value="isActionSelected(index)"
              @change="toggleActionSelection(index)"
              @click.stop
            />
          </div>

          <div class="action-index">{{ index + 1 }}</div>

          <div class="action-icon">
            <el-icon v-if="action.action_type === 'click'" color="#409eff"><Mouse /></el-icon>
            <el-icon v-else-if="action.action_type === 'fill'" color="#67c23a"><Edit /></el-icon>
            <el-icon v-else color="#e6a23c"><Operation /></el-icon>
          </div>

          <div class="action-info">
            <div class="action-desc">{{ getActionDescription(action) }}</div>
            <div class="action-detail">
              <el-tag size="small" :type="getActionTagType(action.action_type)">
                {{ action.action_type }}
              </el-tag>
              <el-tag v-if="hasSuggestedSkip(index)" size="small" type="info" effect="plain">
                {{ getSuggestedSkipReason(index) }}
              </el-tag>
              <span class="locator-text">
                {{ action.locator_strategy || 'locator' }}: {{ truncate(action.locator_value || action.element_selector || '', 40) }}
              </span>
            </div>
          </div>

          <div class="action-url">{{ truncate(getPageName(action.page_url), 30) }}</div>
        </div>

        <div v-if="recordedActions.length === 0" class="empty-actions">
          <el-icon size="40" color="#c0c4cc"><VideoCamera /></el-icon>
          <p>录制完成后，操作步骤会显示在这里</p>
        </div>
      </div>

      <div v-if="!isRecording && recordedActions.length > 0" class="save-section">
        <el-divider />
        <el-form :model="saveForm" label-width="100px">
          <el-form-item label="保存方式">
            <el-radio-group v-model="saveForm.mode">
              <el-radio value="append" :disabled="!canAppendToCurrentCase">追加到当前用例</el-radio>
              <el-radio value="create">另存为新用例</el-radio>
            </el-radio-group>
          </el-form-item>

          <el-form-item v-if="saveForm.mode === 'append'" label="当前用例">
            <el-input
              :model-value="currentTestCaseName || '未选择当前用例'"
              disabled
              style="width: 320px"
            />
          </el-form-item>

          <el-form-item label="用例名称">
            <el-input
              v-model="saveForm.name"
              :disabled="saveForm.mode === 'append'"
              :placeholder="saveForm.mode === 'append' ? '将直接追加到当前用例' : '请输入测试用例名称'"
              style="width: 320px"
            />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveAsTestCase">
              <el-icon><Check /></el-icon>
              保存
            </el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Check,
  Edit,
  Mouse,
  Operation,
  RefreshLeft,
  VideoCamera,
  VideoPause
} from '@element-plus/icons-vue'
import {
  checkRecordingStatus,
  getRecordingActions,
  saveRecordingAsTestCase,
  startRecording as startRecordingApi,
  stopRecording as stopRecordingApi
} from '@/api/ui_automation'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: '' },
  defaultUrl: { type: String, default: 'https://test6-web.nn.com/' },
  currentTestCaseId: { type: [Number, String], default: '' },
  currentTestCaseName: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const visible = ref(false)
const starting = ref(false)
const saving = ref(false)
const isRecording = ref(false)
const sessionId = ref('')
const recordedActions = ref([])
const selectedActionIndexes = ref([])
const suggestedSkipReasons = ref({})
const suggestedSegments = ref([])
const pollTimer = ref(null)
const actionsListRef = ref(null)

const recordForm = reactive({
  startUrl: 'https://test6-web.nn.com/',
  browser: 'chromium',
  headless: false
})

const saveForm = reactive({
  name: '',
  mode: 'create'
})

const canAppendToCurrentCase = computed(() => Boolean(props.currentTestCaseId))
const allActionsSelected = computed(() => {
  return recordedActions.value.length > 0 && selectedActionIndexes.value.length === recordedActions.value.length
})
const isActionSelectionIndeterminate = computed(() => {
  return selectedActionIndexes.value.length > 0 && selectedActionIndexes.value.length < recordedActions.value.length
})
const suggestedFilteredCount = computed(() => Object.keys(suggestedSkipReasons.value).length)

function syncSaveMode() {
  saveForm.mode = canAppendToCurrentCase.value ? 'append' : 'create'
  if (saveForm.mode === 'append') {
    saveForm.name = props.currentTestCaseName || ''
  } else if (!saveForm.name && sessionId.value) {
    saveForm.name = `录制用例_${sessionId.value}`
  }
}

function clearRecordingDraft() {
  recordedActions.value = []
  selectedActionIndexes.value = []
  suggestedSkipReasons.value = {}
  suggestedSegments.value = []
  sessionId.value = ''
  isRecording.value = false
  saveForm.name = ''
  syncSaveMode()
}

function syncSelectedActions(selectSuggestedOnly = false) {
  const allIndexes = recordedActions.value.map((_, index) => index)
  if (!selectSuggestedOnly) {
    selectedActionIndexes.value = allIndexes
    return
  }

  const skipped = suggestedSkipReasons.value
  selectedActionIndexes.value = allIndexes.filter(index => !skipped[index])
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function scrollActionsToBottom() {
  if (actionsListRef.value) {
    actionsListRef.value.scrollTop = actionsListRef.value.scrollHeight
  }
}

function isActionSelected(index) {
  return selectedActionIndexes.value.includes(index)
}

function hasSuggestedSkip(index) {
  return Boolean(suggestedSkipReasons.value[index])
}

function getSuggestedSkipReason(index) {
  return suggestedSkipReasons.value[index] || ''
}

function getActionLocatorKey(action) {
  return [
    action.page_url || '',
    action.locator_strategy || '',
    action.locator_value || action.element_selector || '',
    action.element_tag || ''
  ].join('::')
}

function getActionSearchText(action) {
  return [
    action.action_type || '',
    action.element_text || '',
    action.element_tag || '',
    action.locator_description || '',
    action.locator_value || '',
    action.page_url || '',
    action.input_value || ''
  ].join(' ').toLowerCase()
}

function isEditableActionTarget(action) {
  const tag = String(action.element_tag || '').toLowerCase()
  return ['input', 'textarea', 'select'].includes(tag)
}

function getActionTimestamp(action) {
  const raw = Number(action.timestamp)
  return Number.isFinite(raw) ? raw : null
}

function buildSuggestedSkipReasons(actions) {
  const reasons = {}

  for (let index = 0; index < actions.length; index += 1) {
    const current = actions[index]
    const next = actions[index + 1]
    const previous = actions[index - 1]
    const currentType = current?.action_type
    const currentLocatorKey = getActionLocatorKey(current || {})

    if (!currentType) continue

    if (
      currentType === 'click' &&
      isEditableActionTarget(current) &&
      next &&
      ['fill', 'press'].includes(next.action_type) &&
      getActionLocatorKey(next) === currentLocatorKey
    ) {
      reasons[index] = '输入前点击'
      continue
    }

    if (
      currentType === 'fill' &&
      next &&
      next.action_type === 'fill' &&
      getActionLocatorKey(next) === currentLocatorKey
    ) {
      reasons[index] = '连续输入旧值'
      continue
    }

    if (
      currentType === 'fill' &&
      !String(current.input_value || '').trim() &&
      next &&
      next.action_type === 'fill' &&
      getActionLocatorKey(next) === currentLocatorKey
    ) {
      reasons[index] = '空输入过渡'
      continue
    }

    if (
      currentType === 'click' &&
      previous &&
      previous.action_type === 'click' &&
      getActionLocatorKey(previous) === currentLocatorKey
    ) {
      const currentTimestamp = getActionTimestamp(current)
      const previousTimestamp = getActionTimestamp(previous)
      if (
        currentTimestamp !== null &&
        previousTimestamp !== null &&
        currentTimestamp - previousTimestamp <= 1200
      ) {
        reasons[index - 1] = '重复点击'
      }
    }

    if (
      ['click', 'fill'].includes(currentType) &&
      !String(current.locator_value || current.element_selector || '').trim()
    ) {
      reasons[index] = '缺少定位信息'
    }
  }

  return reasons
}

function inferSegmentLabel(segmentActions) {
  const joinedText = segmentActions.map(getActionSearchText).join(' ')

  if (/(登录|登陆|账号|账户|用户名|密码|signin|login|otp|验证码|verify|sms)/.test(joinedText)) {
    return '登录段'
  }

  if (/(查询|搜索|search|筛选|filter)/.test(joinedText)) {
    return '查询段'
  }

  if (/(新增|创建|提交|保存|确定|confirm|submit|create)/.test(joinedText)) {
    return '提交流程'
  }

  if (/(菜单|导航|nav|tab|侧边|切换)/.test(joinedText)) {
    return '导航段'
  }

  if (segmentActions.some(action => action.action_type === 'press')) {
    return '按键段'
  }

  if (segmentActions.some(action => action.action_type === 'fill')) {
    return '输入段'
  }

  return '操作段'
}

function buildSuggestedSegments(actions) {
  if (!actions.length) {
    return []
  }

  const segments = []
  let start = 0

  const shouldSplitBefore = (currentIndex) => {
    if (currentIndex === 0) return false

    const current = actions[currentIndex]
    const previous = actions[currentIndex - 1]
    const currentTime = getActionTimestamp(current)
    const previousTime = getActionTimestamp(previous)
    const pageChanged = (current.page_url || '') !== (previous.page_url || '')
    const largeGap = currentTime !== null && previousTime !== null && currentTime - previousTime > 10000
    const previousPress = previous.action_type === 'press' && /enter/i.test(String(previous.input_value || ''))
    const currentStartsInputFlow = ['click', 'fill'].includes(current.action_type) && isEditableActionTarget(current)

    return pageChanged || largeGap || (previousPress && currentStartsInputFlow)
  }

  const pushSegment = (segmentStart, segmentEnd) => {
    if (segmentEnd < segmentStart) return
    const segmentActions = actions.slice(segmentStart, segmentEnd + 1)
    segments.push({
      key: `${segmentStart}-${segmentEnd}`,
      start: segmentStart,
      end: segmentEnd,
      label: inferSegmentLabel(segmentActions),
      actions: segmentActions
    })
  }

  for (let index = 1; index < actions.length; index += 1) {
    if (shouldSplitBefore(index)) {
      pushSegment(start, index - 1)
      start = index
    }
  }

  pushSegment(start, actions.length - 1)

  return segments
    .map((segment, index) => ({
      ...segment,
      label: segments.filter(item => item.label === segment.label).length > 1
        ? `${segment.label}${index + 1}`
        : segment.label
    }))
}

function updateSuggestedSelection({ autoApply = false } = {}) {
  suggestedSkipReasons.value = buildSuggestedSkipReasons(recordedActions.value)
  suggestedSegments.value = buildSuggestedSegments(recordedActions.value)
  if (autoApply) {
    syncSelectedActions(true)
  }
}

function applySuggestedSelection() {
  updateSuggestedSelection({ autoApply: true })
  if (!selectedActionIndexes.value.length && recordedActions.value.length) {
    syncSelectedActions(false)
    ElMessage.warning('智能保留后没有剩余步骤，已恢复为全选')
    return
  }

  if (suggestedFilteredCount.value > 0) {
    ElMessage.success(`已为你过滤 ${suggestedFilteredCount.value} 个疑似噪音步骤`)
  } else {
    ElMessage.info('这段录制里没有明显的噪音步骤')
  }
}

function selectSegment(segment) {
  const indexes = []
  for (let index = segment.start; index <= segment.end; index += 1) {
    if (!suggestedSkipReasons.value[index]) {
      indexes.push(index)
    }
  }

  selectedActionIndexes.value = indexes.length
    ? indexes
    : Array.from({ length: segment.end - segment.start + 1 }, (_, offset) => segment.start + offset)

  ElMessage.success(`已选中 ${segment.label}`)
}

async function refreshRecordedActions({ autoSelect = false } = {}) {
  if (!sessionId.value) return

  const actionsRes = await getRecordingActions(sessionId.value)
  const data = actionsRes.data || actionsRes
  recordedActions.value = Array.isArray(data.actions) ? data.actions : []
  updateSuggestedSelection()

  if (autoSelect) {
    syncSelectedActions(true)
    if (!selectedActionIndexes.value.length && recordedActions.value.length) {
      syncSelectedActions(false)
    }
  } else {
    selectedActionIndexes.value = selectedActionIndexes.value
      .filter(index => index >= 0 && index < recordedActions.value.length)
      .sort((a, b) => a - b)
  }

  await nextTick()
  scrollActionsToBottom()
}

function startPolling() {
  stopPolling()
  pollTimer.value = setInterval(async () => {
    if (!sessionId.value) return

    try {
      const statusRes = await checkRecordingStatus(sessionId.value)
      const statusData = statusRes.data || statusRes

      if (statusData.status === 'error') {
        isRecording.value = false
        stopPolling()
        ElMessage.error(statusData.error || '录制失败')
        return
      }

      if (statusData.status === 'stopped') {
        isRecording.value = false
        stopPolling()
        await refreshRecordedActions({ autoSelect: true })
        return
      }

      await refreshRecordedActions()
    } catch (error) {
      console.error('检查录制状态失败', error)
    }
  }, 1500)
}

watch(() => props.modelValue, (value) => {
  visible.value = value
  if (value) {
    recordForm.startUrl = props.defaultUrl || 'https://test6-web.nn.com/'
    syncSaveMode()
  }
})

watch(visible, (value) => {
  emit('update:modelValue', value)
})

watch(() => props.currentTestCaseId, () => {
  if (visible.value && !sessionId.value) {
    syncSaveMode()
  }
})

async function startRecording() {
  if (!props.projectId) {
    ElMessage.warning('请先选择项目')
    return
  }

  if (!recordForm.startUrl) {
    ElMessage.warning('请输入目标 URL')
    return
  }

  starting.value = true
  try {
    const res = await startRecordingApi({
      project_id: props.projectId,
      start_url: recordForm.startUrl,
      browser: recordForm.browser,
      headless: recordForm.headless
    })

    sessionId.value = res.data?.session_id || res.session_id
    isRecording.value = true
    recordedActions.value = []
    selectedActionIndexes.value = []
    saveForm.name = ''

    ElMessage.success('录制会话已启动，请在浏览器中执行操作')
    startPolling()
  } catch (error) {
    ElMessage.error(`启动录制失败: ${error.response?.data?.error || error.message}`)
  } finally {
    starting.value = false
  }
}

async function stopRecording() {
  if (!sessionId.value) {
    ElMessage.warning('当前没有正在录制的会话')
    return
  }

  try {
    const res = await stopRecordingApi(sessionId.value)
    isRecording.value = false
    stopPolling()

    const data = res.data || res
    recordedActions.value = Array.isArray(data.actions) ? data.actions : []
    updateSuggestedSelection()
    syncSelectedActions(true)

    if (!selectedActionIndexes.value.length && recordedActions.value.length) {
      syncSelectedActions(false)
    }

    if (!recordedActions.value.length) {
      ElMessage.warning('录制已停止，但没有捕获到操作')
      return
    }

    if (saveForm.mode === 'create' && !saveForm.name) {
      saveForm.name = `录制用例_${sessionId.value}`
    }

    if (suggestedFilteredCount.value > 0) {
      ElMessage.success(`已捕获 ${recordedActions.value.length} 个操作，并自动过滤 ${suggestedFilteredCount.value} 个疑似噪音步骤`)
    } else {
      ElMessage.success(`已捕获 ${recordedActions.value.length} 个操作`)
    }
  } catch (error) {
    ElMessage.error(`停止录制失败: ${error.response?.data?.error || error.message}`)
  }
}

function resetRecording() {
  stopPolling()
  clearRecordingDraft()
}

function toggleSelectAllActions(checked) {
  selectedActionIndexes.value = checked ? recordedActions.value.map((_, index) => index) : []
}

function toggleActionSelection(index) {
  if (selectedActionIndexes.value.includes(index)) {
    selectedActionIndexes.value = selectedActionIndexes.value.filter(item => item !== index)
    return
  }

  selectedActionIndexes.value = [...selectedActionIndexes.value, index].sort((a, b) => a - b)
}

function keepLastActions(count) {
  const indexes = recordedActions.value.map((_, index) => index)
  selectedActionIndexes.value = indexes.slice(Math.max(indexes.length - count, 0))
}

async function saveAsTestCase() {
  if (!sessionId.value) {
    ElMessage.warning('录制会话已失效，请重新开始录制')
    return
  }

  if (!recordedActions.value.length) {
    ElMessage.warning('请先录制操作步骤')
    return
  }

  if (!selectedActionIndexes.value.length) {
    ElMessage.warning('请至少保留一个录制步骤')
    return
  }

  const isAppendMode = saveForm.mode === 'append'
  const targetTestCaseId = isAppendMode ? props.currentTestCaseId : null
  const caseName = isAppendMode ? (props.currentTestCaseName || '').trim() : saveForm.name.trim()

  if (isAppendMode && !targetTestCaseId) {
    ElMessage.warning('当前没有可追加的测试用例')
    return
  }

  if (!isAppendMode && !caseName) {
    ElMessage.warning('请输入测试用例名称')
    return
  }

  saving.value = true
  try {
    const res = await saveRecordingAsTestCase(
      sessionId.value,
      caseName,
      targetTestCaseId,
      {
        projectId: props.projectId,
        selectedActionIndexes: selectedActionIndexes.value
      }
    )
    const data = res.data || res

    if (data.save_mode === 'append') {
      ElMessage.success(`已向 ${data.test_case_name} 追加 ${data.steps_created} 个录制步骤`)
    } else {
      ElMessage.success(`已保存为测试用例: ${data.test_case_name}`)
    }

    emit('saved', res)
    visible.value = false
  } catch (error) {
    ElMessage.error(`保存失败: ${error.response?.data?.error || error.message}`)
  } finally {
    saving.value = false
  }
}

function getActionDescription(action) {
  const actionType = action.action_type || 'action'
  const targetText = (action.element_name || action.element_text || action.locator_description || '').trim()
  const inputValue = action.input_value || action.key || action.value || ''

  if (actionType === 'click') {
    return targetText ? `点击 ${targetText}` : '点击元素'
  }

  if (actionType === 'fill') {
    return targetText ? `在 ${targetText} 中输入 "${inputValue}"` : `输入 "${inputValue}"`
  }

  if (actionType === 'press') {
    return targetText ? `在 ${targetText} 上按下 "${inputValue}"` : `按下按键 "${inputValue}"`
  }

  if (actionType === 'select') {
    return targetText ? `选择 ${targetText}` : '选择选项'
  }

  return actionType
}

function getActionTagType(type) {
  const tagTypeMap = {
    click: '',
    fill: 'success',
    press: 'warning',
    select: 'warning'
  }
  return tagTypeMap[type] || 'info'
}

function getPageName(url) {
  if (!url) return ''

  try {
    const parsedUrl = new URL(url)
    return `${parsedUrl.pathname}${parsedUrl.search}` || parsedUrl.hostname
  } catch {
    return url
  }
}

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? `${str.slice(0, len)}...` : str
}

function handleClose() {
  stopPolling()
  clearRecordingDraft()
}

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.record-setup {
  padding: 20px;
}

.setup-actions {
  margin-top: 20px;
  text-align: center;
}

.record-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border-radius: 8px;
  background: #f5f7fa;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-text,
.actions-count {
  color: #303133;
}

.rec-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c0c4cc;
}

.rec-dot.active {
  background: #f56c6c;
  box-shadow: 0 0 0 4px rgba(245, 108, 108, 0.18);
}

.action-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.segment-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.segment-label {
  font-size: 13px;
  color: #606266;
}

.filter-left,
.filter-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-summary,
.filter-label {
  font-size: 13px;
  color: #606266;
}

.filter-hint {
  font-size: 13px;
  color: #67c23a;
}

.actions-list {
  max-height: 420px;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
}

.action-item {
  display: grid;
  grid-template-columns: 28px 40px 40px minmax(0, 1fr) 180px;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.action-item:last-child {
  margin-bottom: 0;
}

.action-item:hover {
  border-color: #c6e2ff;
}

.action-item-selected {
  border-color: #67c23a;
  background: #f3fbf2;
}

.action-item-suggested-skip {
  border-style: dashed;
  opacity: 0.78;
}

.action-check {
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-index {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}

.action-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-info {
  min-width: 0;
}

.action-desc {
  margin-bottom: 6px;
  font-weight: 600;
  color: #303133;
}

.action-detail {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 13px;
  color: #606266;
}

.locator-text,
.action-url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-url {
  font-size: 12px;
  text-align: right;
  color: #909399;
}

.empty-actions {
  padding: 40px 0;
  text-align: center;
  color: #909399;
}

.save-section {
  margin-top: 16px;
}

@media (max-width: 900px) {
  .record-status-bar,
  .action-filter-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .status-right,
  .filter-right {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .segment-bar {
    align-items: stretch;
  }

  .action-item {
    grid-template-columns: 28px 40px 40px minmax(0, 1fr);
  }

  .action-url {
    display: none;
  }
}
</style>
