<template>
  <div class="import-dialog">
    <el-dialog
      v-model="visible"
      title="📥 批量导入测试用例"
      width="900px"
      :close-on-click-modal="false"
      @close="handleClose"
    >
      <!-- 步骤条 -->
      <el-steps :active="currentStep" align-center class="import-steps">
        <el-step title="上传文件" description="支持 Excel / CSV" />
        <el-step title="字段映射" description="自动匹配列" />
        <el-step title="预览确认" description="检查数据" />
        <el-step title="导入完成" description="查看结果" />
      </el-steps>

      <!-- 步骤1: 上传文件 -->
      <div v-if="currentStep === 0" class="step-content">
        <el-upload
          ref="uploadRef"
          class="upload-area"
          drag
          :auto-upload="false"
          :limit="1"
          :on-change="handleFileChange"
          :on-exceed="handleExceed"
          accept=".xlsx,.xls,.csv"
        >
          <el-icon class="el-icon--upload" :size="48"><upload-filled /></el-icon>
          <div class="el-upload__text">
            拖拽文件到此处，或 <em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持 .xlsx / .xls / .csv 格式，单文件最大 10MB
            </div>
          </template>
        </el-upload>

        <div v-if="uploadFile" class="file-info">
          <el-tag type="success" size="large">
            📄 {{ uploadFile.name }} ({{ formatSize(uploadFile.size) }})
          </el-tag>
        </div>

        <div class="step-actions">
          <el-button type="primary" :disabled="!uploadFile" @click="handleUpload">
            下一步：字段映射 →
          </el-button>
        </div>
      </div>

      <!-- 步骤2: 字段映射 -->
      <div v-if="currentStep === 1" class="step-content">
        <div class="mapping-tip">
          <el-alert type="info" :closable="false" show-icon>
            系统已自动匹配列名。请检查映射是否正确，不需要的列选择"忽略"。
          </el-alert>
        </div>

        <div class="mapping-table">
          <table class="map-table">
            <thead>
              <tr>
                <th>原始列名</th>
                <th>→</th>
                <th>映射到字段</th>
                <th>预览数据（第1行）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(header, idx) in parseResult.headers" :key="idx">
                <td><el-tag size="small">{{ header }}</el-tag></td>
                <td class="arrow-cell">→</td>
                <td>
                  <el-select
                    v-model="columnMapping[header]"
                    placeholder="选择字段"
                    clearable
                    size="default"
                    style="width: 200px"
                  >
                    <el-option label="忽略此列" value="" />
                    <el-option label="标题 (必填)" value="title" />
                    <el-option label="描述" value="description" />
                    <el-option label="前置条件" value="preconditions" />
                    <el-option label="操作步骤" value="steps" />
                    <el-option label="预期结果 (必填)" value="expected_result" />
                    <el-option label="优先级" value="priority" />
                    <el-option label="测试类型" value="test_type" />
                    <el-option label="所属模块" value="module" />
                    <el-option label="状态" value="status" />
                    <el-option label="标签" value="tags" />
                  </el-select>
                </td>
                <td class="preview-cell">
                  {{ getPreviewData(header) || '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="step-actions">
          <el-button @click="currentStep = 0">← 上一步</el-button>
          <el-button type="primary" :disabled="!hasRequiredFields" @click="handleMapping">
            下一步：预览 →
          </el-button>
        </div>
      </div>

      <!-- 步骤3: 预览确认 -->
      <div v-if="currentStep === 2" class="step-content">
        <div class="preview-summary">
          <el-statistic title="待导入用例数" :value="previewRows.length" />
          <el-statistic title="已映射字段" :value="mappedFieldCount" />
        </div>

        <el-table :data="previewRows" max-height="400" border stripe class="preview-table">
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="module" label="模块" width="120" />
          <el-table-column prop="priority" label="优先级" width="90">
            <template #default="{ row }">
              <el-tag :type="priorityType(row.priority)" size="small">{{ row.priority }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="test_type" label="类型" width="100" />
          <el-table-column prop="expected_result" label="预期结果" min-width="200" show-overflow-tooltip />
          <el-table-column label="校验" width="80">
            <template #default="{ row }">
              <el-icon v-if="row.title && row.expected_result" color="#67C23A"><check /></el-icon>
              <el-icon v-else color="#F56C6C"><close /></el-icon>
            </template>
          </el-table-column>
        </el-table>

        <div class="step-actions">
          <el-button @click="currentStep = 1">← 上一步</el-button>
          <el-button type="primary" :loading="importing" @click="handleImport">
            🚀 确认导入 {{ previewRows.length }} 条用例
          </el-button>
        </div>
      </div>

      <!-- 步骤4: 结果 -->
      <div v-if="currentStep === 3" class="step-content">
        <div class="import-result">
          <el-result
            v-if="importResult.error_count === 0"
            icon="success"
            title="导入成功！"
            :sub-title="`成功导入 ${importResult.success_count} 条测试用例`"
          >
            <template #extra>
              <el-button type="primary" @click="handleClose">完成</el-button>
              <el-button @click="resetImport">继续导入</el-button>
            </template>
          </el-result>

          <el-result
            v-else-if="importResult.success_count === 0"
            icon="error"
            title="导入失败"
            sub-title="所有用例导入失败"
          >
            <template #extra>
              <div class="error-list">
                <p v-for="(err, i) in importResult.errors.slice(0, 10)" :key="i" class="error-item">{{ err }}</p>
              </div>
              <el-button @click="resetImport">重新导入</el-button>
            </template>
          </el-result>

          <el-result
            v-else
            icon="warning"
            title="部分导入成功"
            :sub-title="`成功 ${importResult.success_count} 条，失败 ${importResult.error_count} 条`"
          >
            <template #extra>
              <div class="error-list">
                <p v-for="(err, i) in importResult.errors.slice(0, 10)" :key="i" class="error-item">{{ err }}</p>
              </div>
              <el-button type="primary" @click="handleClose">完成</el-button>
              <el-button @click="resetImport">继续导入</el-button>
            </template>
          </el-result>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Check, Close } from '@element-plus/icons-vue'
import api from '@/utils/api'

const props = defineProps({
  modelValue: Boolean,
  projectId: { type: [Number, String], default: null }
})

const emit = defineEmits(['update:modelValue', 'imported'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})

const currentStep = ref(0)
const uploadFile = ref(null)
const uploadRef = ref(null)
const parseResult = ref(null)
const columnMapping = ref({})
const previewRows = ref([])
const importing = ref(false)
const importResult = ref({ success_count: 0, error_count: 0, errors: [] })

// 字段选项
const fieldOptions = [
  { label: '忽略此列', value: '' },
  { label: '标题 (必填)', value: 'title' },
  { label: '描述', value: 'description' },
  { label: '前置条件', value: 'preconditions' },
  { label: '操作步骤', value: 'steps' },
  { label: '预期结果 (必填)', value: 'expected_result' },
  { label: '优先级', value: 'priority' },
  { label: '测试类型', value: 'test_type' },
  { label: '所属模块', value: 'module' },
  { label: '状态', value: 'status' },
  { label: '标签', value: 'tags' },
]

const hasRequiredFields = computed(() => {
  const mapped = Object.values(columnMapping.value).filter(v => v)
  return mapped.includes('title') && mapped.includes('expected_result')
})

const mappedFieldCount = computed(() => {
  return Object.values(columnMapping.value).filter(v => v).length
})

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function priorityType(p) {
  const map = { critical: 'danger', high: 'warning', medium: '', low: 'info' }
  return map[p] || ''
}

function getPreviewData(header) {
  if (!parseResult.value || !parseResult.value.preview?.length) return ''
  return parseResult.value.preview[0]?.[header] || ''
}

function handleFileChange(file) {
  uploadFile.value = file.raw
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件，请先移除已选文件')
}

async function handleUpload() {
  if (!uploadFile.value) return

  const formData = new FormData()
  formData.append('file', uploadFile.value)
  if (props.projectId) {
    formData.append('project_id', props.projectId)
  }

  try {
    const resp = await api.post('/testcases/import/preview/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000
    })
    parseResult.value = resp.data

    // 初始化映射
    const mapping = {}
    if (resp.data.mapped_fields) {
      Object.assign(mapping, resp.data.mapped_fields)
    }
    columnMapping.value = mapping

    currentStep.value = 1
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '文件解析失败')
  }
}

function handleMapping() {
  // 应用映射到预览数据
  const rows = parseResult.value.preview.map(rawRow => {
    const row = {}
    for (const [header, field] of Object.entries(columnMapping.value)) {
      if (field) {
        row[field] = rawRow[header] || ''
      }
    }
    // 确保必需字段
    row.title = row.title || ''
    row.description = row.description || ''
    row.preconditions = row.preconditions || ''
    row.steps = row.steps || ''
    row.expected_result = row.expected_result || ''
    row.priority = row.priority || 'medium'
    row.test_type = row.test_type || 'functional'
    row.module = row.module || ''
    row.status = row.status || 'draft'
    row.tags = row.tags || []
    return row
  })

  previewRows.value = rows
  currentStep.value = 2
}

async function handleImport() {
  importing.value = true
  try {
    // 重新解析全部数据（不只是预览的10行）
    const formData = new FormData()
    formData.append('file', uploadFile.value)
    if (props.projectId) {
      formData.append('project_id', props.projectId)
    }
    formData.append('column_mapping', JSON.stringify(columnMapping.value))

    // 先获取全量解析结果
    const parseResp = await api.post('/testcases/import/preview/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000
    })

    // 映射全量数据
    const allRows = parseResp.data.rows.map(rawRow => {
      const row = {}
      for (const [header, field] of Object.entries(columnMapping.value)) {
        if (field) {
          row[field] = rawRow[header] || ''
        }
      }
      row.title = row.title || ''
      row.description = row.description || ''
      row.preconditions = row.preconditions || ''
      row.steps = row.steps || ''
      row.expected_result = row.expected_result || ''
      row.priority = row.priority || 'medium'
      row.test_type = row.test_type || 'functional'
      row.module = row.module || ''
      row.status = row.status || 'draft'
      row.tags = row.tags || []
      return row
    })

    // 执行导入
    const resp = await api.post('/testcases/import/execute/', {
      rows: allRows,
      project_id: props.projectId,
    }, { timeout: 120000 })

    importResult.value = resp.data
    currentStep.value = 3
    emit('imported')
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '导入失败')
  } finally {
    importing.value = false
  }
}

function resetImport() {
  currentStep.value = 0
  uploadFile.value = null
  parseResult.value = null
  columnMapping.value = {}
  previewRows.value = []
  importResult.value = { success_count: 0, error_count: 0, errors: [] }
  if (uploadRef.value) {
    uploadRef.value.clearFiles()
  }
}

function handleClose() {
  resetImport()
  visible.value = false
}

watch(visible, (v) => {
  if (!v) resetImport()
})
</script>

<style scoped>
.import-steps {
  margin-bottom: 24px;
}

.step-content {
  min-height: 300px;
  padding: 16px 0;
}

.upload-area {
  width: 100%;
}

.file-info {
  margin-top: 16px;
  text-align: center;
}

.step-actions {
  margin-top: 24px;
  text-align: right;
}

.mapping-tip {
  margin-bottom: 16px;
}

.mapping-table {
  max-height: 400px;
  overflow-y: auto;
}

.map-table {
  width: 100%;
  border-collapse: collapse;
}

.map-table th,
.map-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  text-align: left;
}

.map-table th {
  background: #f5f7fa;
  font-weight: 600;
  position: sticky;
  top: 0;
}

.arrow-cell {
  text-align: center;
  color: #909399;
  font-size: 18px;
}

.preview-cell {
  color: #606266;
  font-size: 13px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-summary {
  display: flex;
  gap: 32px;
  margin-bottom: 16px;
}

.preview-table {
  width: 100%;
}

.import-result {
  padding: 20px 0;
}

.error-list {
  max-height: 200px;
  overflow-y: auto;
  text-align: left;
  background: #fef0f0;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}

.error-item {
  margin: 4px 0;
  font-size: 13px;
  color: #f56c6c;
}
</style>
