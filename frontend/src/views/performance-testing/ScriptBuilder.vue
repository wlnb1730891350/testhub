<template>
  <div class="builder-page">
    <div class="page-header">
      <div>
        <h2>脚本编排</h2>
        <p>支持在线编排生成 JMX，也支持上传原生 JMX 后仅调整线程组和 CSV 文件</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Upload" @click="openJmxUploadDialog('ONLINE')">导入 JMX</el-button>
        <el-button :icon="DocumentAdd" @click="newScript">新建脚本</el-button>
        <el-button type="primary" :icon="Check" :loading="saving" @click="saveScript">保存</el-button>
        <el-button type="success" :icon="VideoPlay" :disabled="!form.project || !form.name" @click="runScript">执行</el-button>
      </div>
    </div>

    <div class="builder-layout">
      <el-card class="side-card" shadow="never">
        <template #header>
          <div class="card-title">
            <span>脚本列表</span>
            <el-button link @click="loadScripts">刷新</el-button>
          </div>
        </template>
        <el-select v-model="projectId" placeholder="选择项目" filterable clearable style="width: 100%" @change="loadScripts">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <div class="script-list">
          <button
            v-for="script in scripts"
            :key="script.id"
            class="script-item"
            :class="{ active: script.id === currentScriptId }"
            @click="selectScript(script)"
          >
            <span>{{ script.name }}</span>
            <small>{{ scriptTypeText(script.script_type) }} · v{{ script.version }}</small>
          </button>
        </div>
      </el-card>

      <el-card class="editor-card" shadow="never">
        <el-form :model="form" label-width="90px">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="脚本名称" required>
                <el-input v-model.trim="form.name" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="所属项目" required>
                <el-select v-model="form.project" filterable style="width: 100%" @change="handleProjectChange">
                  <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="状态">
                <el-select v-model="form.status" style="width: 100%">
                  <el-option label="草稿" value="draft" />
                  <el-option label="就绪" value="ready" />
                  <el-option label="归档" value="archived" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="脚本模式">
            <el-radio-group v-model="form.script_type" @change="handleScriptTypeChange">
              <el-radio-button value="ONLINE">在线编排</el-radio-button>
              <el-radio-button value="JMX_UPLOAD" :disabled="!form.original_jmx">纯 JMX</el-radio-button>
            </el-radio-group>
            <el-button v-if="!form.original_jmx" link :icon="Upload" @click="openJmxUploadDialog('JMX_UPLOAD')">上传 JMX 创建</el-button>
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" />
          </el-form-item>
        </el-form>

        <div class="toolbar">
          <div class="toolbar-left">
            <el-button v-if="!isPureJmx" size="small" @click="loadDefaultConfig">载入模板</el-button>
            <el-button size="small" @click="downloadJmx">导出 JMX</el-button>
            <span v-if="!isPureJmx">支持变量写法：<code>&#123;&#123;base_url&#125;&#125;</code> 或 JMeter 原生 <code>${var}</code></span>
            <span v-else>原始 JMX 会在执行前应用线程组和 CSV 文件覆盖</span>
          </div>
          <el-radio-group v-if="!isPureJmx" v-model="editorMode" size="small" @change="handleEditorModeChange">
            <el-radio-button value="visual">可视化</el-radio-button>
            <el-radio-button value="json">JSON</el-radio-button>
          </el-radio-group>
          <el-tag v-else type="info" effect="plain">纯 JMX</el-tag>
        </div>

        <div v-if="isPureJmx" class="pure-jmx-panel">
          <section class="builder-section">
            <div class="section-header">
              <div>
                <h3>JMX 文件</h3>
                <p>{{ form.original_jmx ? '已上传原始 JMX，可重新上传替换' : '请上传 JMX 文件后继续' }}</p>
              </div>
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept=".jmx,application/xml,text/xml"
                :on-change="handleReplaceJmxFile"
              >
                <el-button size="small" :loading="jmxUploading" :icon="Upload">
                  {{ currentScriptId ? '重新上传 JMX' : '上传 JMX' }}
                </el-button>
              </el-upload>
            </div>
            <el-alert
              v-if="form.import_warnings?.length"
              type="warning"
              :title="form.import_warnings.join('；')"
              show-icon
              :closable="false"
            />
          </section>

          <section class="builder-section">
            <div class="section-header">
              <div>
                <h3>线程组参数</h3>
                <p>线程组来自上传的 JMX，仅覆盖运行参数</p>
              </div>
            </div>
            <div v-if="!visualConfig.thread_groups.length" class="empty-state large">未识别到线程组</div>
            <div v-for="(group, groupIndex) in visualConfig.thread_groups" :key="group._id" class="pure-thread-group">
              <div class="pure-group-title">
                <strong>{{ group.name }}</strong>
                <el-tag size="small" effect="plain">#{{ group.jmx_index ?? groupIndex }}</el-tag>
              </div>
              <el-row :gutter="12" class="group-fields">
                <el-col :span="6">
                  <label>并发线程</label>
                  <el-input-number v-model="group.threads" :min="1" :max="100000" controls-position="right" />
                </el-col>
                <el-col :span="6">
                  <label>启动时间(秒)</label>
                  <el-input-number v-model="group.ramp_up" :min="0" :max="86400" controls-position="right" />
                </el-col>
                <el-col :span="6">
                  <label>循环次数</label>
                  <el-input-number v-model="group.loops" :min="-1" :max="100000" controls-position="right" />
                  <span class="field-hint">-1 表示循环到停止</span>
                </el-col>
                <el-col :span="6">
                  <label>持续时间(秒)</label>
                  <el-input-number v-model="group.duration" :min="0" :max="86400" controls-position="right" />
                </el-col>
              </el-row>
            </div>
          </section>

          <section class="builder-section">
            <div class="section-header">
              <div>
                <h3>CSV 文件</h3>
                <p>CSV 控件来自上传的 JMX，上传文件后执行时会替换对应路径</p>
              </div>
            </div>
            <div v-if="!visualConfig.datasets.length" class="empty-state">未识别到 CSV 数据集</div>
            <div v-for="dataset in visualConfig.datasets" :key="dataset._id" class="pure-dataset-row">
              <el-input :model-value="dataset.name" disabled />
              <el-input :model-value="dataset.filename" disabled placeholder="CSV 文件路径" />
              <span class="dataset-meta">{{ dataset._variables_text || '未声明变量' }}</span>
              <span class="dataset-meta">{{ dataset.row_count ? `${dataset.row_count} 行` : '' }}</span>
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept=".csv,text/csv"
                :on-change="(file) => uploadDatasetFile(file, dataset, { preserveVariables: true })"
              >
                <el-button size="small" :loading="dataset._uploading" :icon="Upload">上传 CSV</el-button>
              </el-upload>
            </div>
          </section>
        </div>

        <div v-else-if="editorMode === 'visual'" class="visual-builder">
          <section class="builder-section">
            <div class="section-header">
              <div>
                <h3>用户定义的变量</h3>
                <p>TestPlan 层变量控件，可在 URL、参数和请求体中使用，例如 &#123;&#123;base_url&#125;&#125;</p>
              </div>
              <el-button size="small" :icon="Plus" @click="addVariable">添加变量</el-button>
            </div>
            <div class="kv-list">
              <div v-for="(item, index) in variableRows" :key="item._id" class="kv-row">
                <el-input v-model.trim="item.key" placeholder="变量名，如 base_url" />
                <el-input v-model="item.value" placeholder="变量值" />
                <el-button :icon="Delete" circle text @click="removeVariable(index)" />
              </div>
              <div v-if="!variableRows.length" class="empty-state">暂无变量</div>
            </div>
          </section>

          <section class="builder-section">
            <div class="section-header">
              <div>
                <h3>线程组</h3>
                <p>拖拽线程组或请求左侧手柄可以调整执行顺序</p>
              </div>
              <el-button size="small" type="primary" :icon="Plus" @click="addThreadGroup">添加线程组</el-button>
            </div>

            <div v-if="!visualConfig.thread_groups.length" class="empty-state large">暂无线程组</div>

            <div
              v-for="(group, groupIndex) in visualConfig.thread_groups"
              :key="group._id"
              class="thread-group"
              @dragover.prevent
              @drop="dropGroup(groupIndex)"
            >
              <div class="group-header">
                <el-icon class="drag-handle" draggable="true" @dragstart="dragGroupStart(groupIndex)" @dragend="clearDragState">
                  <Rank />
                </el-icon>
                <el-input v-model.trim="group.name" class="group-name" placeholder="线程组名称" />
                <el-button size="small" :icon="Plus" @click="addStep(group)">添加请求</el-button>
                <el-button size="small" :icon="Delete" @click="removeThreadGroup(groupIndex)">删除线程组</el-button>
              </div>

              <el-row :gutter="12" class="group-fields">
                <el-col :span="6">
                  <label>并发线程</label>
                  <el-input-number v-model="group.threads" :min="1" :max="100000" controls-position="right" />
                </el-col>
                <el-col :span="6">
                  <label>启动时间(秒)</label>
                  <el-input-number v-model="group.ramp_up" :min="0" :max="86400" controls-position="right" />
                </el-col>
                <el-col :span="6">
                  <label>循环次数</label>
                  <el-input-number v-model="group.loops" :min="-1" :max="100000" controls-position="right" />
                  <span class="field-hint">-1 表示循环到停止</span>
                </el-col>
                <el-col :span="6">
                  <label>持续时间(秒)</label>
                  <el-input-number v-model="group.duration" :min="0" :max="86400" controls-position="right" />
                </el-col>
              </el-row>

              <div class="subsection">
                <div class="subsection-header">
                  <h4>用户定义的变量</h4>
                  <el-button size="small" link :icon="Plus" @click="addPair(group._variableRows)">添加变量</el-button>
                </div>
                <div v-if="!group._variableRows.length" class="empty-state">未配置线程组变量</div>
                <div class="kv-list compact">
                  <div v-for="(item, variableIndex) in group._variableRows" :key="item._id" class="kv-row">
                    <el-input v-model.trim="item.key" placeholder="变量名" />
                    <el-input v-model="item.value" placeholder="变量值" />
                    <el-button :icon="Delete" circle text @click="removePair(group._variableRows, variableIndex)" />
                  </div>
                </div>
              </div>

              <div class="subsection">
                <div class="subsection-header">
                  <h4>参数化数据集</h4>
                  <el-button size="small" link :icon="Plus" @click="addDataset(group)">添加数据集</el-button>
                </div>
                <div v-if="!group.datasets.length" class="empty-state">未配置 CSV 数据集</div>
                <div v-for="(dataset, datasetIndex) in group.datasets" :key="dataset._id" class="dataset-row">
                  <el-input v-model.trim="dataset.name" placeholder="数据集名称" />
                  <el-input v-model.trim="dataset.filename" placeholder="CSV 文件路径" />
                  <el-upload
                    :auto-upload="false"
                    :show-file-list="false"
                    accept=".csv,text/csv"
                    :on-change="(file) => uploadDatasetFile(file, dataset)"
                  >
                    <el-button size="small" :loading="dataset._uploading" :icon="Upload">上传</el-button>
                  </el-upload>
                  <el-input v-model.trim="dataset._variables_text" placeholder="变量名，用英文逗号分隔" />
                  <el-input v-model.trim="dataset.delimiter" class="tiny-input" placeholder="," />
                  <el-checkbox v-model="dataset.ignore_first_line">忽略首行</el-checkbox>
                  <el-button :icon="Delete" circle text @click="removeDataset(group, datasetIndex)" />
                </div>
              </div>

              <div class="subsection">
                <div class="subsection-header">
                  <h4>HTTP 请求</h4>
                  <el-button size="small" link :icon="Plus" @click="addStep(group)">添加请求</el-button>
                </div>
                <div v-if="!group.steps.length" class="empty-state">暂无请求步骤</div>

                <div
                  v-for="(step, stepIndex) in group.steps"
                  :key="step._id"
                  class="request-step"
                  @dragover.prevent
                  @drop.stop="dropStep(groupIndex, stepIndex)"
                >
                  <div class="step-header">
                    <el-icon
                      class="drag-handle"
                      draggable="true"
                      @dragstart.stop="dragStepStart(groupIndex, stepIndex)"
                      @dragend="clearDragState"
                    >
                      <Rank />
                    </el-icon>
                    <el-select v-model="step.method" class="method-select">
                      <el-option label="GET" value="GET" />
                      <el-option label="POST" value="POST" />
                      <el-option label="PUT" value="PUT" />
                      <el-option label="PATCH" value="PATCH" />
                      <el-option label="DELETE" value="DELETE" />
                    </el-select>
                    <el-input v-model.trim="step.name" placeholder="请求名称" />
                    <el-button :icon="Delete" circle text @click="removeStep(group, stepIndex)" />
                  </div>

                  <el-input v-model.trim="step.url" class="url-input" placeholder="&#123;&#123;base_url&#125;&#125;/api/path" />

                  <el-tabs class="step-tabs">
                    <el-tab-pane label="Headers">
                      <div class="kv-list compact">
                        <div v-for="(header, headerIndex) in step._headers" :key="header._id" class="kv-row">
                          <el-input v-model.trim="header.key" placeholder="Header 名称" />
                          <el-input v-model="header.value" placeholder="Header 值" />
                          <el-button :icon="Delete" circle text @click="removePair(step._headers, headerIndex)" />
                        </div>
                        <el-button size="small" link :icon="Plus" @click="addPair(step._headers)">添加 Header</el-button>
                      </div>
                    </el-tab-pane>
                    <el-tab-pane label="Params">
                      <div class="kv-list compact">
                        <div v-for="(param, paramIndex) in step._params" :key="param._id" class="kv-row">
                          <el-input v-model.trim="param.key" placeholder="参数名" />
                          <el-input v-model="param.value" placeholder="参数值" />
                          <el-button :icon="Delete" circle text @click="removePair(step._params, paramIndex)" />
                        </div>
                        <el-button size="small" link :icon="Plus" @click="addPair(step._params)">添加参数</el-button>
                      </div>
                    </el-tab-pane>
                    <el-tab-pane label="Body">
                      <el-input v-model="step.body" type="textarea" :rows="5" placeholder="请求体，支持 JSON、表单文本或变量" />
                    </el-tab-pane>
                    <el-tab-pane label="断言">
                      <div class="assertion-list">
                        <div v-for="(assertion, assertionIndex) in step.assertions" :key="assertion._id" class="assertion-row">
                          <el-select v-model="assertion.type">
                            <el-option label="状态码" value="response_code" />
                            <el-option label="包含文本" value="contains" />
                          </el-select>
                          <el-input v-model.trim="assertion.value" placeholder="期望值，如 200" />
                          <el-input v-model.trim="assertion.name" placeholder="断言名称" />
                          <el-button :icon="Delete" circle text @click="removeAssertion(step, assertionIndex)" />
                        </div>
                        <el-button size="small" link :icon="Plus" @click="addAssertion(step)">添加断言</el-button>
                      </div>
                    </el-tab-pane>
                  </el-tabs>
                </div>
                <div class="request-drop-zone" @dragover.prevent @drop.stop="dropStep(groupIndex, group.steps.length)">
                  拖到这里放到末尾
                </div>
              </div>
            </div>
          </section>
        </div>

        <el-input
          v-else
          v-model="configText"
          type="textarea"
          :rows="28"
          spellcheck="false"
          class="json-editor"
        />
      </el-card>
    </div>

    <el-dialog v-model="importDialogVisible" title="导入 JMX 脚本" width="680px">
      <el-form label-width="90px">
        <el-form-item label="目标项目" required>
          <el-select v-model="importForm.project_id" filterable style="width: 100%">
            <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="脚本名称" required>
          <el-input v-model.trim="importForm.name" />
        </el-form-item>
        <el-form-item label="导入方式">
          <el-radio-group v-model="importForm.script_type">
            <el-radio-button value="ONLINE">在线编排</el-radio-button>
            <el-radio-button value="JMX_UPLOAD">纯 JMX</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="JMX 文件" required>
          <el-upload :auto-upload="false" :limit="1" :on-change="handleImportFile" :on-remove="clearImportFile">
            <el-button :icon="Upload">选择文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="preview"
        :type="preview.executable ? 'success' : 'warning'"
        :title="`识别到 ${preview.thread_group_count} 个线程组、${preview.dataset_count || 0} 个 CSV、${preview.total_requests} 个请求`"
        :description="(preview.warnings || []).join('；')"
        show-icon
        :closable="false"
      />

      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button :loading="importing" @click="previewImport">预览</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">
          {{ importForm.script_type === 'ONLINE' ? '导入为在线编排' : '保存为纯 JMX' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Delete, DocumentAdd, Plus, Rank, Upload, VideoPlay } from '@element-plus/icons-vue'
import {
  createPerformanceDataset,
  createPerformanceScript,
  executePerformanceScript,
  exportScriptJmx,
  exportCurrentScriptJmx,
  getDefaultPerformanceConfig,
  getPerformanceProjects,
  getPerformanceScripts,
  importJmxConfirm,
  importJmxPreview,
  updatePerformanceScript,
  uploadScriptJmx,
} from '@/api/performance-testing'

const projects = ref([])
const scripts = ref([])
const projectId = ref(null)
const currentScriptId = ref(null)
const saving = ref(false)
const importing = ref(false)
const jmxUploading = ref(false)
const importDialogVisible = ref(false)
const editorMode = ref('visual')
const preview = ref(null)
const importFile = ref(null)
const importForm = ref({ project_id: null, name: '导入JMX脚本', script_type: 'ONLINE' })
const visualConfig = ref({ variables: {}, thread_groups: [], datasets: [] })
const variableRows = ref([])
const configText = ref('')
const draggingGroupIndex = ref(null)
const draggingStep = ref(null)

const form = ref({
  name: '',
  description: '',
  project: null,
  status: 'draft',
  script_type: 'ONLINE',
  original_jmx: null,
  import_warnings: [],
})

const isPureJmx = computed(() => form.value.script_type === 'JMX_UPLOAD')

const createId = () => `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

const clone = (value) => JSON.parse(JSON.stringify(value ?? {}))

const toNumber = (value, fallback) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

const normalizeLoopCount = (value) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return 1
  const integer = Math.trunc(number)
  return integer === -1 || integer > 0 ? integer : 1
}

const splitList = (value) => {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

const emptyPair = () => ({ _id: createId(), key: '', value: '' })

const objectToRows = (value) => {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  return Object.entries(source).map(([key, rowValue]) => ({
    _id: createId(),
    key,
    value: rowValue ?? '',
  }))
}

const rowsToObject = (rows) => {
  return (rows || []).reduce((result, row) => {
    const key = String(row.key || '').trim()
    if (key) {
      result[key] = row.value ?? ''
    }
    return result
  }, {})
}

const normalizeEditableDataset = (dataset = {}) => ({
  _id: createId(),
  jmx_index: dataset.jmx_index ?? null,
  name: dataset.name || 'CSV 数据集',
  filename: dataset.filename || '',
  dataset_id: dataset.dataset_id || dataset.id || null,
  file_url: dataset.file_url || '',
  row_count: dataset.row_count || 0,
  _uploading: false,
  _variables_text: Array.isArray(dataset.variables) ? dataset.variables.join(',') : dataset.variables || '',
  delimiter: dataset.delimiter || ',',
  ignore_first_line: Boolean(dataset.ignore_first_line),
})

const normalizeEditableStep = (step = {}, index = 0) => ({
  _id: createId(),
  type: 'http_request',
  name: step.name || `HTTP 请求 ${index + 1}`,
  method: (step.method || 'GET').toUpperCase(),
  url: step.url || '{{base_url}}/',
  body: step.body || '',
  _headers: objectToRows(step.headers),
  _params: objectToRows(step.params),
  assertions: (Array.isArray(step.assertions) ? step.assertions : []).map((assertion) => ({
    _id: createId(),
    type: assertion.type || 'response_code',
    value: assertion.value || '',
    name: assertion.name || '',
  })),
})

const normalizeEditableGroup = (group = {}, index = 0) => ({
  _id: createId(),
  jmx_index: group.jmx_index ?? null,
  name: group.name || `线程组 ${index + 1}`,
  threads: toNumber(group.threads, 1),
  ramp_up: toNumber(group.ramp_up, 1),
  loops: normalizeLoopCount(group.loops),
  duration: toNumber(group.duration, 0),
  _variableRows: objectToRows(group.variables || group.user_defined_variables),
  datasets: (Array.isArray(group.datasets) ? group.datasets : []).map(normalizeEditableDataset),
  steps: (Array.isArray(group.steps) ? group.steps : []).map(normalizeEditableStep),
})

const toEditableConfig = (config = {}) => {
  const source = clone(config)
  const groups = Array.isArray(source.thread_groups) ? source.thread_groups : []
  const topLevelDatasets = Array.isArray(source.datasets) && source.datasets.length
    ? source.datasets
    : collectGroupDatasets(groups)
  return {
    variables: source.variables && typeof source.variables === 'object' ? source.variables : {},
    thread_groups: groups.map(normalizeEditableGroup),
    datasets: topLevelDatasets.map(normalizeEditableDataset),
  }
}

const collectGroupDatasets = (groups = []) => {
  const seen = new Set()
  const datasets = []
  groups.forEach((group) => {
    if (!Array.isArray(group.datasets)) return
    group.datasets.forEach((dataset) => {
      const key = dataset?.jmx_index ?? `${dataset?.name || ''}:${dataset?.filename || ''}`
      if (seen.has(key)) return
      seen.add(key)
      datasets.push(dataset)
    })
  })
  return datasets
}

const buildDatasetConfig = (dataset) => {
  const result = {
    name: dataset.name || 'CSV 数据集',
    filename: dataset.filename || '',
    dataset_id: dataset.dataset_id || null,
    variables: splitList(dataset._variables_text),
    delimiter: dataset.delimiter || ',',
    ignore_first_line: Boolean(dataset.ignore_first_line),
  }
  if (dataset.jmx_index !== null && dataset.jmx_index !== undefined) result.jmx_index = dataset.jmx_index
  return result
}

const buildConfigFromVisual = () => {
  const datasets = (visualConfig.value.datasets || [])
    .map(buildDatasetConfig)
    .filter((dataset) => dataset.filename || dataset.variables.length)
  const config = {
    variables: rowsToObject(variableRows.value),
    thread_groups: (visualConfig.value.thread_groups || []).map((group, groupIndex) => {
      const groupDatasets = (group.datasets || [])
        .map(buildDatasetConfig)
        .filter((dataset) => dataset.filename || dataset.variables.length)
      const result = {
        name: group.name || `线程组 ${groupIndex + 1}`,
        threads: toNumber(group.threads, 1),
        ramp_up: toNumber(group.ramp_up, 1),
        loops: normalizeLoopCount(group.loops),
        duration: toNumber(group.duration, 0),
        variables: rowsToObject(group._variableRows),
        steps: (group.steps || []).map((step, stepIndex) => ({
          type: 'http_request',
          name: step.name || `HTTP 请求 ${stepIndex + 1}`,
          method: (step.method || 'GET').toUpperCase(),
          url: step.url || '/',
          headers: rowsToObject(step._headers),
          params: rowsToObject(step._params),
          body: step.body || '',
          assertions: (step.assertions || []).map((assertion) => ({
            type: assertion.type || 'response_code',
            value: assertion.value || '',
            name: assertion.name || '',
          })).filter((assertion) => assertion.value),
        })),
      }
      if (group.jmx_index !== null && group.jmx_index !== undefined) result.jmx_index = group.jmx_index
      if (groupDatasets.length) result.datasets = groupDatasets
      return result
    }),
  }
  if (datasets.length) config.datasets = datasets
  return config
}

const syncJsonFromVisual = () => {
  configText.value = JSON.stringify(buildConfigFromVisual(), null, 2)
}

const setConfig = (config) => {
  visualConfig.value = toEditableConfig(config)
  variableRows.value = objectToRows(visualConfig.value.variables)
  syncJsonFromVisual()
}

const syncVisualFromJson = () => {
  try {
    const parsed = JSON.parse(configText.value || '{}')
    setConfig(parsed)
    return true
  } catch (error) {
    ElMessage.error('编排 JSON 格式不正确，无法切换到可视化视图')
    return false
  }
}

const handleEditorModeChange = (mode) => {
  if (mode === 'json') {
    syncJsonFromVisual()
    return
  }
  if (!syncVisualFromJson()) {
    editorMode.value = 'json'
  }
}

const getConfigForSave = () => {
  if (isPureJmx.value) {
    const config = buildConfigFromVisual()
    configText.value = JSON.stringify(config, null, 2)
    return config
  }

  if (editorMode.value === 'visual') {
    const config = buildConfigFromVisual()
    configText.value = JSON.stringify(config, null, 2)
    return config
  }

  try {
    const config = JSON.parse(configText.value || '{}')
    setConfig(config)
    editorMode.value = 'json'
    return config
  } catch (error) {
    ElMessage.error('编排 JSON 格式不正确')
    return null
  }
}

const addVariable = () => {
  variableRows.value.push(emptyPair())
}

const removeVariable = (index) => {
  variableRows.value.splice(index, 1)
}

const addPair = (rows) => {
  rows.push(emptyPair())
}

const removePair = (rows, index) => {
  rows.splice(index, 1)
}

const addThreadGroup = () => {
  visualConfig.value.thread_groups.push(normalizeEditableGroup({
    steps: [normalizeEditableStep({ name: '首页请求', url: '{{base_url}}/' })],
  }, visualConfig.value.thread_groups.length))
}

const removeThreadGroup = (index) => {
  visualConfig.value.thread_groups.splice(index, 1)
}

const addDataset = (group) => {
  group.datasets.push(normalizeEditableDataset())
}

const removeDataset = (group, index) => {
  group.datasets.splice(index, 1)
}

const uploadDatasetFile = async (file, dataset, options = {}) => {
  if (!form.value.project) {
    ElMessage.warning('请先选择项目')
    return
  }
  dataset._uploading = true
  try {
    const body = new FormData()
    body.append('project', form.value.project)
    body.append('name', dataset.name || file.name || 'CSV 数据集')
    body.append('description', '脚本编排上传')
    body.append('file', file.raw)
    const { data } = await createPerformanceDataset(body)
    dataset.dataset_id = data.id
    dataset.name = dataset.name || data.name
    dataset.filename = data.file_path || data.file || dataset.filename
    dataset.file_url = data.file_url || data.file || ''
    dataset.row_count = data.row_count || 0
    if (Array.isArray(data.variables) && data.variables.length && (!options.preserveVariables || !dataset._variables_text)) {
      dataset._variables_text = data.variables.join(',')
      dataset.ignore_first_line = true
    }
    ElMessage.success(`数据集上传成功，识别 ${dataset.row_count || 0} 行数据`)
    if (editorMode.value === 'visual') {
      syncJsonFromVisual()
    }
  } finally {
    dataset._uploading = false
  }
}

const addStep = (group) => {
  group.steps.push(normalizeEditableStep({}, group.steps.length))
}

const removeStep = (group, index) => {
  group.steps.splice(index, 1)
}

const addAssertion = (step) => {
  step.assertions.push({
    _id: createId(),
    type: 'response_code',
    value: '200',
    name: '状态码断言',
  })
}

const removeAssertion = (step, index) => {
  step.assertions.splice(index, 1)
}

const moveItem = (items, fromIndex, toIndex) => {
  if (fromIndex === null || fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
  const [item] = items.splice(fromIndex, 1)
  items.splice(toIndex, 0, item)
}

const dragGroupStart = (index) => {
  draggingGroupIndex.value = index
}

const dropGroup = (index) => {
  if (draggingGroupIndex.value === null) return
  moveItem(visualConfig.value.thread_groups, draggingGroupIndex.value, index)
  clearDragState()
}

const dragStepStart = (groupIndex, stepIndex) => {
  draggingStep.value = { groupIndex, stepIndex }
}

const dropStep = (targetGroupIndex, targetStepIndex) => {
  if (!draggingStep.value) return
  const { groupIndex, stepIndex } = draggingStep.value
  const sourceGroup = visualConfig.value.thread_groups[groupIndex]
  const targetGroup = visualConfig.value.thread_groups[targetGroupIndex]
  if (!sourceGroup || !targetGroup) {
    clearDragState()
    return
  }

  if (groupIndex === targetGroupIndex) {
    moveItem(targetGroup.steps, stepIndex, targetStepIndex)
  } else {
    const [step] = sourceGroup.steps.splice(stepIndex, 1)
    targetGroup.steps.splice(targetStepIndex, 0, step)
  }
  clearDragState()
}

const clearDragState = () => {
  draggingGroupIndex.value = null
  draggingStep.value = null
}

const loadProjects = async () => {
  const { data } = await getPerformanceProjects({ page_size: 1000 })
  projects.value = data.results || data
  if (!projectId.value && projects.value.length) {
    projectId.value = projects.value[0].id
  }
}

const loadScripts = async () => {
  const params = { page_size: 1000 }
  if (projectId.value) params.project = projectId.value
  const { data } = await getPerformanceScripts(params)
  scripts.value = data.results || data
}

const scriptTypeText = (type) => {
  if (type === 'JMX_UPLOAD') return '纯 JMX'
  return '在线编排'
}

const selectScript = (script) => {
  currentScriptId.value = script.id
  form.value = {
    id: script.id,
    name: script.name,
    description: script.description,
    project: script.project,
    status: script.status,
    script_type: script.script_type,
    original_jmx: script.original_jmx || null,
    import_warnings: script.import_warnings || [],
  }
  editorMode.value = 'visual'
  setConfig(script.config || {})
}

const newScript = async () => {
  currentScriptId.value = null
  const project = projects.value.find((item) => item.id === projectId.value) || projects.value[0]
  form.value = {
    name: '新建性能脚本',
    description: '',
    project: project?.id || null,
    status: 'draft',
    script_type: 'ONLINE',
    original_jmx: null,
    import_warnings: [],
  }
  editorMode.value = 'visual'
  await loadDefaultConfig()
}

const handleProjectChange = () => {
  projectId.value = form.value.project
}

const handleScriptTypeChange = (type) => {
  if (type === 'JMX_UPLOAD' && !form.value.original_jmx) {
    form.value.script_type = 'ONLINE'
    openJmxUploadDialog('JMX_UPLOAD')
  }
  if (type === 'ONLINE') {
    editorMode.value = 'visual'
  }
}

const openJmxUploadDialog = (scriptType = 'ONLINE') => {
  importForm.value = {
    project_id: form.value.project || projectId.value || projects.value[0]?.id || null,
    name: form.value.name && form.value.name !== '新建性能脚本' ? form.value.name : '导入JMX脚本',
    script_type: scriptType,
  }
  importFile.value = null
  preview.value = null
  importDialogVisible.value = true
}

const loadDefaultConfig = async () => {
  const project = projects.value.find((item) => item.id === form.value.project)
  const { data } = await getDefaultPerformanceConfig({ base_url: project?.base_url || '' })
  setConfig(data)
}

const saveScript = async (options = {}) => {
  const silent = options?.silent === true
  if (!form.value.project || !form.value.name) {
    ElMessage.warning('请选择项目并填写脚本名称')
    return null
  }
  if (isPureJmx.value && !form.value.original_jmx) {
    ElMessage.warning('请先上传 JMX 文件')
    openJmxUploadDialog()
    return null
  }

  const config = getConfigForSave()
  if (!config) return null

  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      description: form.value.description,
      project: form.value.project,
      status: form.value.status,
      script_type: form.value.script_type,
      config,
    }
    let savedScript
    if (currentScriptId.value) {
      const { data } = await updatePerformanceScript(currentScriptId.value, payload)
      savedScript = data
    } else {
      const { data } = await createPerformanceScript(payload)
      savedScript = data
      currentScriptId.value = data.id
    }
    if (!silent) ElMessage.success('保存成功')
    await loadScripts()
    if (savedScript) selectScript(savedScript)
    return savedScript
  } finally {
    saving.value = false
  }
}

const runScript = async () => {
  const savedScript = await saveScript({ silent: true })
  const scriptId = savedScript?.id || currentScriptId.value
  if (!scriptId) return

  const { data } = await executePerformanceScript(scriptId)
  ElMessage.success(`已保存并提交执行 #${data.id}`)
}

const downloadJmx = async () => {
  if (!form.value.project) {
    ElMessage.warning('请选择项目后再导出 JMX')
    return
  }
  if (isPureJmx.value) {
    const savedScript = await saveScript({ silent: true })
    const scriptId = savedScript?.id || currentScriptId.value
    if (!scriptId) return
    const { data } = await exportScriptJmx(scriptId)
    downloadBlob(data, `${form.value.name || 'test_plan'}.jmx`)
    return
  }

  const config = getConfigForSave()
  if (!config) return

  const payload = {
    name: form.value.name || 'test_plan',
    project: form.value.project,
    config,
  }
  const { data } = await exportCurrentScriptJmx(payload)
  downloadBlob(data, `${form.value.name || 'test_plan'}.jmx`)
}

const handleReplaceJmxFile = async (file) => {
  if (!file?.raw) return
  if (!form.value.project) {
    ElMessage.warning('请先选择项目')
    return
  }
  if (!currentScriptId.value) {
    importFile.value = file.raw
    importForm.value = {
      project_id: form.value.project,
      name: form.value.name || '导入JMX脚本',
      script_type: 'JMX_UPLOAD',
    }
    importDialogVisible.value = true
    return
  }

  jmxUploading.value = true
  try {
    const body = new FormData()
    body.append('file', file.raw)
    const { data } = await uploadScriptJmx(currentScriptId.value, body)
    ElMessage.success('JMX 已更新')
    await loadScripts()
    selectScript(data)
  } finally {
    jmxUploading.value = false
  }
}

const handleImportFile = (file) => {
  importFile.value = file.raw
  preview.value = null
}

const clearImportFile = () => {
  importFile.value = null
  preview.value = null
}

const buildImportFormData = () => {
  const body = new FormData()
  body.append('project_id', importForm.value.project_id)
  body.append('name', importForm.value.name)
  body.append('script_type', importForm.value.script_type)
  if (preview.value?.config) body.append('config', JSON.stringify(preview.value.config))
  if (preview.value?.warnings) body.append('warnings', JSON.stringify(preview.value.warnings))
  if (importFile.value) body.append('file', importFile.value)
  return body
}

const previewImport = async () => {
  if (!importFile.value) {
    ElMessage.warning('请选择 JMX 文件')
    return
  }
  importing.value = true
  try {
    const { data } = await importJmxPreview(buildImportFormData())
    preview.value = data
  } finally {
    importing.value = false
  }
}

const confirmImport = async () => {
  if (!importForm.value.project_id || !importFile.value) {
    ElMessage.warning('请选择项目和 JMX 文件')
    return
  }
  importing.value = true
  try {
    const { data } = await importJmxConfirm(buildImportFormData())
    ElMessage.success(importForm.value.script_type === 'ONLINE' ? '已导入为在线编排' : '已保存为纯 JMX 脚本')
    importDialogVisible.value = false
    projectId.value = importForm.value.project_id
    await loadScripts()
    selectScript(data)
  } finally {
    importing.value = false
  }
}

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await loadProjects()
  await loadScripts()
  await newScript()
  importForm.value.project_id = projectId.value
})
</script>

<style scoped lang="scss">
.builder-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header,
.card-title,
.toolbar,
.toolbar-left,
.section-header,
.subsection-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-header {
  h2 {
    margin: 0 0 6px;
  }

  p {
    margin: 0;
    color: var(--el-text-color-secondary);
  }
}

.header-actions,
.toolbar-left {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.builder-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
}

.script-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.script-item {
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  border-radius: 6px;
  padding: 10px;
  text-align: left;
  cursor: pointer;

  span,
  small {
    display: block;
  }

  small {
    margin-top: 4px;
    color: var(--el-text-color-secondary);
  }

  &.active {
    border-color: var(--el-color-primary);
    color: var(--el-color-primary);
  }
}

.toolbar {
  margin-bottom: 14px;
  color: var(--el-text-color-secondary);
}

.visual-builder {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.pure-jmx-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.builder-section {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 16px;

  &:first-child {
    border-top: 0;
    padding-top: 0;
  }
}

.section-header {
  margin-bottom: 12px;

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: 16px;
  }

  p {
    margin-top: 4px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
}

.kv-list,
.assertion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kv-row,
.assertion-row,
.dataset-row {
  display: grid;
  grid-template-columns: minmax(150px, 0.8fr) minmax(200px, 1fr) 36px;
  gap: 8px;
  align-items: center;
}

.assertion-row {
  grid-template-columns: 130px minmax(140px, 1fr) minmax(160px, 1fr) 36px;
}

.dataset-row {
  grid-template-columns: minmax(120px, 0.8fr) minmax(180px, 1fr) 86px minmax(160px, 1fr) 70px 100px 36px;
}

.tiny-input {
  max-width: 70px;
}

.empty-state {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13px;

  &.large {
    padding: 24px;
    text-align: center;
  }
}

.thread-group {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 14px;
  background: var(--el-bg-color);
}

.pure-thread-group {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;
  background: var(--el-bg-color);
}

.pure-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.pure-dataset-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.8fr) minmax(220px, 1.2fr) minmax(150px, 1fr) 80px 112px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.dataset-meta {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-header,
.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-header {
  margin-bottom: 12px;
}

.group-name {
  flex: 1;
}

.drag-handle {
  color: var(--el-text-color-secondary);
  cursor: grab;
  font-size: 18px;

  &:active {
    cursor: grabbing;
  }
}

.group-fields {
  margin-bottom: 12px;

  label {
    display: block;
    margin-bottom: 6px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  :deep(.el-input-number) {
    width: 100%;
  }
}

.field-hint {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.subsection {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 12px;
  margin-top: 12px;
}

.subsection-header {
  margin-bottom: 10px;

  h4 {
    margin: 0;
    font-size: 14px;
  }
}

.request-step {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 10px;
  background: var(--el-fill-color-extra-light);
}

.request-drop-zone {
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 8px 10px;
  text-align: center;
}

.method-select {
  width: 112px;
}

.url-input {
  margin-top: 10px;
}

.step-tabs {
  margin-top: 4px;

  :deep(.el-tabs__header) {
    margin-bottom: 10px;
  }
}

.compact {
  gap: 6px;
}

.json-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.45;
}

@media (max-width: 1100px) {
  .builder-layout {
    grid-template-columns: 1fr;
  }

  .kv-row,
  .assertion-row,
  .dataset-row,
  .pure-dataset-row {
    grid-template-columns: 1fr;
  }

  .group-fields :deep(.el-col) {
    max-width: 50%;
    flex: 0 0 50%;
  }
}
</style>
