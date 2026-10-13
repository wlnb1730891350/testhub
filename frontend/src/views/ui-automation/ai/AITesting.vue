<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">{{ $t('uiAutomation.ai.title') }}</h1>
    </div>

    <div class="card-container">
      <el-row :gutter="20">
        <el-col :span="12">
          <div class="section-title">{{ $t('uiAutomation.ai.taskInput') }}</div>
          <el-form :model="taskForm" label-position="top">
            <el-form-item label="所属项目" required>
              <el-select v-model="taskForm.projectId" placeholder="请选择所属项目" filterable style="width: 100%;" @change="handleTaskProjectChange">
                <el-option
                  v-for="project in projects"
                  :key="project.id"
                  :label="project.name"
                  :value="project.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="前置模板">
              <el-select v-model="taskForm.setupTemplateId" placeholder="可选：选择前置步骤模板" clearable filterable style="width: 100%;">
                <el-option
                  v-for="tpl in setupTemplates"
                  :key="tpl.id"
                  :label="tpl.name"
                  :value="tpl.id"
                >
                  <span>{{ tpl.name }}</span>
                  <span style="color: #909399; font-size: 12px; margin-left: 8px;">{{ tpl.steps_count }}步</span>
                </el-option>
              </el-select>
              <div class="form-tip" v-if="taskForm.setupTemplateId" style="color: #67c23a; font-size: 12px; margin-top: 4px;">
                已选模板的步骤会在任务描述前自动执行
              </div>
            </el-form-item>
            <el-form-item :label="$t('uiAutomation.ai.taskDescription')" required>
              <el-input
                v-model="taskForm.description"
                type="textarea"
                :rows="10"
                :placeholder="$t('uiAutomation.ai.taskPlaceholder')"
                maxlength="2000"
                show-word-limit
              />
            </el-form-item>

            <el-form-item :label="$t('uiAutomation.ai.gifRecording')">
              <el-switch
                v-model="taskForm.enableGif"
                :active-text="$t('uiAutomation.ai.on')"
                :inactive-text="$t('uiAutomation.ai.off')"
              />
              <span style="margin-left: 10px; color: #909399; font-size: 12px;">
                {{ $t('uiAutomation.ai.gifTip') }}
              </span>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                @click="handleRun"
                :loading="running"
                :disabled="!taskForm.description || !taskForm.projectId"
              >
                <el-icon><VideoPlay /></el-icon>
                {{ $t('uiAutomation.ai.startExecution') }}
              </el-button>
              <el-button
                type="danger"
                @click="handleStop"
                :disabled="!running || analyzing"
                v-if="running"
              >
                <el-icon><SwitchButton /></el-icon>
                {{ $t('uiAutomation.ai.stopExecution') }}
              </el-button>
              <el-button
                type="success"
                @click="handleSaveAsCase"
                :disabled="!taskForm.description || !taskForm.projectId"
              >
                <el-icon><DocumentAdd /></el-icon>
                {{ $t('uiAutomation.ai.saveAsCase') }}
              </el-button>
              <el-button
                type="warning"
                @click="handleAIRecording"
                :disabled="!currentExecutionId || running"
              >
                <el-icon><DocumentAdd /></el-icon>
                AI录制
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            :title="$t('uiAutomation.ai.tip')"
            type="info"
            :closable="false"
            style="margin-top: 20px;"
          >
            <template #default>
              <div>{{ $t('uiAutomation.ai.tipContent1') }}</div>
              <div>{{ $t('uiAutomation.ai.tipContent2') }}</div>
            </template>
          </el-alert>

          <div class="section-title" style="margin-top: 20px;">{{ $t('uiAutomation.ai.executionLogs') }}</div>
          <div class="log-container" ref="logContainer">
            <div v-if="!logs && !running" class="empty-logs">
              {{ $t('uiAutomation.ai.noLogs') }}
            </div>
            <pre v-else class="log-content">{{ logs }}</pre>
          </div>
        </el-col>

        <el-col :span="12">
          <div class="section-title">{{ $t('uiAutomation.ai.taskDetails') }}</div>
          <div class="task-list-container">
            <div v-if="analyzing" class="analyzing-state">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>{{ $t('uiAutomation.ai.analyzing') }}</span>
            </div>
            <div v-else-if="plannedTasks.length > 0">
              <div
                v-for="task in plannedTasks"
                :key="task.id"
                class="task-item"
                :class="task.status"
              >
                <div class="task-status-icon">
                  <el-icon v-if="task.status === 'completed'" color="#67C23A"><CircleCheckFilled /></el-icon>
                  <el-icon v-else-if="task.status === 'in_progress'" class="is-loading" color="#409EFF"><Loading /></el-icon>
                  <el-icon v-else color="#909399"><CircleCheck /></el-icon>
                </div>
                <div class="task-content">
                  <span class="task-id">{{ task.id }}.</span>
                  <span class="task-desc">{{ task.description }}</span>
                </div>
              </div>
            </div>
            <div v-else class="empty-tasks">
              {{ $t('uiAutomation.ai.noTasks') }}
            </div>
          </div>

        </el-col>
      </el-row>
    </div>

    <!-- 保存为用例对话框 -->
    <el-dialog v-model="showSaveDialog" :title="$t('uiAutomation.ai.saveAsCaseTitle')" width="500px" :close-on-click-modal="false">
      <el-form :model="saveForm" :rules="saveRules" ref="saveFormRef" label-width="90px">
        <el-form-item label="所属项目" prop="projectId">
          <el-select v-model="saveForm.projectId" placeholder="请选择所属项目" filterable style="width: 100%;" @change="handleSaveProjectChange">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="功能分类">
          <el-select v-model="saveForm.category" clearable filterable placeholder="可选：归入功能分类" style="width: 100%;">
            <el-option
              v-for="category in saveCaseCategories"
              :key="category.id"
              :label="category.name"
              :value="category.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.ai.caseName')" prop="name">
          <el-input v-model="saveForm.name" :placeholder="$t('uiAutomation.ai.caseNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.common.description')" prop="description">
          <el-input v-model="saveForm.description" type="textarea" :placeholder="$t('uiAutomation.ai.caseDescPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showSaveDialog = false">{{ $t('uiAutomation.common.cancel') }}</el-button>
          <el-button type="primary" @click="confirmSaveCase" :loading="saving">{{ $t('uiAutomation.common.save') }}</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- AI录制保存对话框 -->
    <el-dialog v-model="showAIRecordDialog" title="AI录制步骤" width="760px" :close-on-click-modal="false">
      <el-alert
        title="将本次AI执行沉淀为新的普通UI自动化用例步骤。请选择所属项目后保存。"
        type="info"
        :closable="false"
        style="margin-bottom: 12px;"
      />
      <el-form :model="aiRecordForm" label-width="100px">
        <el-form-item label="所属项目" required>
          <el-select v-model="aiRecordForm.projectId" placeholder="请选择所属项目" filterable style="width: 100%;">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称" required>
          <el-input v-model="aiRecordForm.testCaseName" placeholder="请输入新用例名称" />
        </el-form-item>
      </el-form>

      <div class="section-title" style="margin-top: 12px;">可保存步骤</div>
      <el-table :data="aiRecordingActions" v-loading="aiRecordLoading" height="280" border empty-text="暂无可保存步骤">
        <el-table-column type="index" label="#" width="55" />
        <el-table-column prop="action_type" label="动作" width="90" />
        <el-table-column prop="description" label="步骤描述" min-width="210" show-overflow-tooltip />
        <el-table-column prop="element_name" label="元素" min-width="160" show-overflow-tooltip />
        <el-table-column prop="locator_value" label="定位器" min-width="220" show-overflow-tooltip />
        <el-table-column prop="input_value" label="输入/断言值" min-width="160" show-overflow-tooltip />
      </el-table>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAIRecordDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmSaveAIRecording" :loading="aiRecordSaving" :disabled="aiRecordingActions.length === 0">
            保存步骤
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, DocumentAdd, CircleCheckFilled, CircleCheck, Loading, SwitchButton } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  runAdhocAITask,
  createAICase,
  getAIExecutionRecordDetail,
  stopAITask,
  getAIRecordingActions,
  saveAIRecording,
  getUiProjects,
  getSetupTemplates,
  getAICaseCategories
} from '@/api/ui_automation'

const { t } = useI18n()
const route = useRoute()

const running = ref(false)
const analyzing = ref(false)
const saving = ref(false)
const logs = ref('')
const plannedTasks = ref([])
const currentExecutionId = ref(null)
const logContainer = ref(null)
const projects = ref([])
const setupTemplates = ref([])
const saveCaseCategories = ref([])

const showAIRecordDialog = ref(false)
const aiRecordLoading = ref(false)
const aiRecordSaving = ref(false)
const aiRecordingActions = ref([])
const aiRecordForm = reactive({
  projectId: null,
  testCaseName: ''
})

const taskForm = reactive({
  projectId: null,
  description: '',
  enableGif: false,
  setupTemplateId: null
})

const showSaveDialog = ref(false)
const saveForm = reactive({
  projectId: null,
  name: '',
  description: '',
  category: null
})
const saveFormRef = ref(null)

const saveRules = computed(() => ({
  projectId: [{ required: true, message: '请选择所属项目', trigger: 'change' }],
  name: [{ required: true, message: t('uiAutomation.ai.rules.nameRequired'), trigger: 'blur' }]
}))

const routeProjectId = () => {
  const raw = route.query.project || route.query.project_id || route.params.projectId || route.params.project_id
  const id = Number(raw)
  return Number.isFinite(id) && id > 0 ? id : null
}

const initProjectSelection = () => {
  const routeId = routeProjectId()
  const fallbackId = projects.value.length === 1 ? projects.value[0].id : null
  const selectedId = routeId || fallbackId
  if (selectedId) {
    taskForm.projectId = selectedId
    saveForm.projectId = selectedId
    aiRecordForm.projectId = selectedId
  }
}

const loadProjects = async () => {
  try {
    const response = await getUiProjects({ page_size: 100 })
    projects.value = response.data.results || response.data || []
    initProjectSelection()
  } catch (error) {
    console.error('获取项目列表失败:', error)
    ElMessage.error('获取项目列表失败')
  }
}

const loadSaveCaseCategories = async (projectId) => {
  try {
    const response = await getAICaseCategories({ page_size: 1000 })
    saveCaseCategories.value = response.data?.results || response.data || []
  } catch (error) {
    saveCaseCategories.value = []
    console.error('加载功能分类失败:', error)
  }
}

const handleSaveProjectChange = () => {
  loadSaveCaseCategories(saveForm.projectId)
}

const loadExecutionFromQuery = async () => {
  const queryExecutionId = route.query.execution_id || route.query.record_id
  if (!queryExecutionId) return

  currentExecutionId.value = Number(queryExecutionId)
  try {
    const response = await getAIExecutionRecordDetail(currentExecutionId.value)
    const record = response.data
    if (record.project?.id || record.project_id) {
      taskForm.projectId = record.project?.id || record.project_id
      saveForm.projectId = taskForm.projectId
      aiRecordForm.projectId = taskForm.projectId
    }
    taskForm.description = record.task_description || ''
    logs.value = record.logs || ''
    plannedTasks.value = record.planned_tasks || []
    running.value = ['pending', 'running', 'in_progress'].includes(record.status)
    analyzing.value = false
    if (running.value) {
      pollLogs()
    }
  } catch (error) {
    console.error('加载AI执行记录失败:', error)
    ElMessage.error('加载AI执行记录失败: ' + (error.response?.data?.error || error.message))
    currentExecutionId.value = null
  }
}

onMounted(async () => {
  await loadProjects()
  loadExecutionFromQuery()
})

const handleRun = async () => {
  if (!taskForm.projectId) {
    ElMessage.warning('请选择所属项目')
    return
  }
  running.value = true
  analyzing.value = true
  logs.value = t('uiAutomation.ai.messages.initAgent')
  plannedTasks.value = []

  try {
    const response = await runAdhocAITask({
      task_description: taskForm.description,
      project_id: taskForm.projectId,
      execution_mode: 'text',
      enable_gif: taskForm.enableGif,
      setup_template_id: taskForm.setupTemplateId
    })

    currentExecutionId.value = response.data.execution_id
    ElMessage.success(t('uiAutomation.ai.messages.startSuccess'))

    pollLogs()

  } catch (error) {
    console.error('执行失败:', error)
    ElMessage.error(t('uiAutomation.ai.messages.startFailed') + ': ' + (error.response?.data?.error || error.message))
    running.value = false
    analyzing.value = false
  }
}

const handleStop = async () => {
  if (!currentExecutionId.value) return

  try {
    await stopAITask(currentExecutionId.value)
    ElMessage.warning(t('uiAutomation.ai.messages.stopping'))
  } catch (error) {
    console.error('停止失败:', error)
    ElMessage.error(t('uiAutomation.ai.messages.stopFailed'))
  }
}

const pollLogs = () => {
  const pollInterval = setInterval(async () => {
    if (!currentExecutionId.value) {
      clearInterval(pollInterval)
      return
    }

    try {
      const response = await getAIExecutionRecordDetail(currentExecutionId.value)
      const record = response.data

      logs.value = record.logs || ''
      plannedTasks.value = record.planned_tasks || []

      if (plannedTasks.value.length > 0) {
        analyzing.value = false
      }

      nextTick(() => {
        if (logContainer.value) {
          logContainer.value.scrollTop = logContainer.value.scrollHeight
        }
      })

      if (record.status === 'passed' || record.status === 'failed' || record.status === 'stopped') {
        clearInterval(pollInterval)
        running.value = false
        analyzing.value = false
        if (record.status === 'passed') {
          ElMessage.success(t('uiAutomation.ai.messages.executionSuccess'))
        } else if (record.status === 'stopped') {
          ElMessage.warning(t('uiAutomation.ai.messages.taskStopped'))
        } else {
          ElMessage.error(t('uiAutomation.ai.messages.executionFailed'))
        }
      }
    } catch (error) {
      console.error('获取日志失败:', error)
    }
  }, 2000)
}

const handleSaveAsCase = () => {
  showSaveDialog.value = true
  saveForm.projectId = taskForm.projectId || routeProjectId() || saveForm.projectId || null
  saveForm.name = ''
  saveForm.description = ''
  saveForm.category = null
  loadSaveCaseCategories(saveForm.projectId)
}

const confirmSaveCase = async () => {
  if (!saveFormRef.value) return

  await saveFormRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        await createAICase({
          project_id: saveForm.projectId,
          name: saveForm.name,
          description: saveForm.description,
          task_description: taskForm.description,
          setup_template: taskForm.setupTemplateId || null,
          category: saveForm.category || null
        })

        ElMessage.success(t('uiAutomation.ai.messages.saveSuccess'))
        showSaveDialog.value = false
      } catch (error) {
        console.error('保存失败:', error)
        ElMessage.error(t('uiAutomation.ai.messages.saveFailed'))
      } finally {
        saving.value = false
      }
    }
  })
}

const handleAIRecording = async () => {
  if (!currentExecutionId.value) {
    ElMessage.warning('请先执行一次AI任务')
    return
  }
  showAIRecordDialog.value = true
  aiRecordLoading.value = true
  aiRecordForm.projectId = taskForm.projectId || routeProjectId() || aiRecordForm.projectId || null
  aiRecordForm.testCaseName = `AI录制用例_${new Date().toLocaleString()}`
  try {
    const response = await getAIRecordingActions(currentExecutionId.value)
    aiRecordingActions.value = response.data.actions || []
    if (aiRecordingActions.value.length === 0) {
      ElMessage.warning(response.data.message || '暂无可保存步骤')
    }
  } catch (error) {
    console.error('获取AI录制步骤失败:', error)
    ElMessage.error('获取AI录制步骤失败: ' + (error.response?.data?.error || error.message))
  } finally {
    aiRecordLoading.value = false
  }
}

const handleTaskProjectChange = async () => {
  if (taskForm.projectId) {
    try {
      const res = await getSetupTemplates({ project_id: taskForm.projectId })
      setupTemplates.value = res.data?.results || res.data || []
    } catch (e) {
      setupTemplates.value = []
    }
  } else {
    setupTemplates.value = []
  }
  taskForm.setupTemplateId = null
  saveForm.projectId = taskForm.projectId
  loadSaveCaseCategories(saveForm.projectId)
  aiRecordForm.projectId = taskForm.projectId
}

const confirmSaveAIRecording = async () => {
  if (!currentExecutionId.value) return
  if (!aiRecordForm.projectId) {
    ElMessage.warning('请选择所属项目')
    return
  }
  if (!aiRecordForm.testCaseName) {
    ElMessage.warning('请输入用例名称')
    return
  }

  aiRecordSaving.value = true
  try {
    const payload = {
      project_id: aiRecordForm.projectId,
      test_case_name: aiRecordForm.testCaseName
    }
    const response = await saveAIRecording(currentExecutionId.value, payload)
    ElMessage.success(`保存成功：${response.data.test_case_name}，新增 ${response.data.steps_created} 个步骤`)
    showAIRecordDialog.value = false
  } catch (error) {
    console.error('保存AI录制失败:', error)
    ElMessage.error('保存AI录制失败: ' + (error.response?.data?.error || error.message))
  } finally {
    aiRecordSaving.value = false
  }
}

</script>

<style lang="scss" scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  min-height: calc(100vh - 140px);
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 15px;
  padding-left: 10px;
  border-left: 4px solid #409eff;
}

.task-list-container {
  background-color: #f5f7fa;
  border-radius: 4px;
  padding: 15px;
  margin-bottom: 20px;
  height: calc(100vh - 200px);
  overflow-y: auto;

  .task-item {
    display: flex;
    align-items: flex-start;
    padding: 10px;
    border-bottom: 1px solid #e4e7ed;
    transition: all 0.3s;

    &:last-child {
      border-bottom: none;
    }

    &.completed {
      background-color: #f0f9eb;
      .task-desc {
        color: #67c23a;
        text-decoration: line-through;
      }
    }

    &.in_progress {
      background-color: #ecf5ff;
      .task-desc {
        color: #409eff;
        font-weight: bold;
      }
    }

    .task-status-icon {
      margin-right: 10px;
      margin-top: 2px;
      font-size: 16px;
    }

    .task-content {
      flex: 1;
      line-height: 1.5;

      .task-id {
        font-weight: bold;
        margin-right: 5px;
      }
    }
  }
}

.empty-tasks {
  color: #909399;
  text-align: center;
  padding: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.analyzing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #409eff;

  .el-icon {
    font-size: 24px;
    margin-bottom: 10px;
  }
}

.log-container {
  background-color: #1e1e1e;
  border-radius: 4px;
  height: 300px;
  overflow-y: auto;
  padding: 15px;
  color: #fff;
  font-family: 'Consolas', 'Monaco', monospace;

  .empty-logs {
    color: #909399;
    text-align: center;
    margin-top: 100px;
  }

  .log-content {
    margin: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 14px;
    line-height: 1.5;
  }
}

</style>
