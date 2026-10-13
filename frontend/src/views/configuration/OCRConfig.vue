<template>
  <div class="ocr-config-page">
    <header class="page-header">
      <div>
        <h1>OCR 配置</h1>
        <p>管理 APP 自动化和图像识别使用的离线或在线 OCR 引擎。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" circle title="刷新" @click="loadData" />
        <el-button type="primary" :icon="Plus" @click="openCreate">新增配置</el-button>
      </div>
    </header>

    <el-alert
      :type="installation?.tesseract?.tesseract_available ? 'success' : 'warning'"
      :closable="false"
      show-icon
      class="installation-alert"
    >
      <template #title>
        {{ installationText }}
      </template>
    </el-alert>

    <el-table v-loading="loading" :data="configs" border empty-text="暂无 OCR 配置">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="provider_display" label="服务商" min-width="140" />
      <el-table-column prop="model_name" label="模型" min-width="160" show-overflow-tooltip />
      <el-table-column prop="language" label="语言" width="130" />
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
          <el-tag v-if="row.is_default" type="primary" size="small" class="default-tag">默认</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="270" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button text :loading="testingId === row.id" @click="testConfig(row)">测试</el-button>
          <el-button v-if="!row.is_default" text @click="setDefault(row)">设为默认</el-button>
          <el-button text type="danger" @click="removeConfig(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑 OCR 配置' : '新增 OCR 配置'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：生产环境 OCR" />
        </el-form-item>
        <el-form-item label="服务商" prop="provider">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <template v-if="form.provider !== 'tesseract'">
          <el-form-item label="API Key" :prop="editingId ? '' : 'api_key'">
            <el-input v-model="form.api_key" type="password" show-password placeholder="编辑时留空表示不修改" />
          </el-form-item>
          <el-form-item label="接口地址">
            <el-input v-model="form.base_url" placeholder="OpenAI 兼容接口地址" />
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input v-model="form.model_name" placeholder="例如：gpt-4o" />
          </el-form-item>
        </template>
        <el-form-item label="识别语言">
          <el-input v-model="form.language" />
        </el-form-item>
        <el-form-item label="最低置信度">
          <el-slider v-model="form.min_confidence" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item label="默认配置">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  createOcrConfig,
  deleteOcrConfig,
  getOcrConfigs,
  getOcrInstallation,
  setDefaultOcrConfig,
  testOcrConfig,
  updateOcrConfig
} from '@/api/ocr'

const providers = [
  { label: 'Tesseract OCR', value: 'tesseract' },
  { label: 'OpenAI', value: 'openai' },
  { label: '智谱 GLM-4V', value: 'zhipu' },
  { label: '硅基流动', value: 'siliconflow' },
  { label: '百度 AI OCR', value: 'baidu' },
  { label: '腾讯 OCR', value: 'tencent' },
  { label: '阿里云 OCR', value: 'aliyun' },
  { label: '自定义 OCR', value: 'custom' }
]

const blankForm = () => ({
  name: '',
  provider: 'tesseract',
  api_key: '',
  base_url: '',
  model_name: '',
  language: 'chi_sim+eng',
  min_confidence: 0.3,
  extra_config: {},
  is_active: true,
  is_default: false
})

const configs = ref([])
const installation = ref(null)
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const formRef = ref()
const form = reactive(blankForm())
const rules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择服务商', trigger: 'change' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }]
}

const installationText = computed(() => {
  const status = installation.value?.tesseract
  if (!status) return '正在检查本机 Tesseract 状态'
  if (status.tesseract_available) return `Tesseract 可用${status.version ? `，版本 ${status.version}` : ''}`
  return '本机未安装 Tesseract；仍可配置在线 OCR 服务。'
})

const normalizeList = (data) => data?.results || data || []

const loadData = async () => {
  loading.value = true
  try {
    const [configResponse, installResponse] = await Promise.all([
      getOcrConfigs(),
      getOcrInstallation()
    ])
    configs.value = normalizeList(configResponse.data)
    installation.value = installResponse.data
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || 'OCR 配置加载失败')
  } finally {
    loading.value = false
  }
}

const resetForm = (value = {}) => Object.assign(form, blankForm(), value, { api_key: '' })

const openCreate = () => {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const openEdit = (row) => {
  editingId.value = row.id
  resetForm(row)
  dialogVisible.value = true
}

const saveConfig = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload = { ...form }
    if (editingId.value && !payload.api_key) delete payload.api_key
    if (editingId.value) await updateOcrConfig(editingId.value, payload)
    else await createOcrConfig(payload)
    ElMessage.success('OCR 配置已保存')
    dialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const testConfig = async (row) => {
  testingId.value = row.id
  try {
    const { data } = await testOcrConfig(row.id)
    ElMessage.success(data.message || 'OCR 配置可用')
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.response?.data?.error || 'OCR 配置不可用')
  } finally {
    testingId.value = null
  }
}

const setDefault = async (row) => {
  await setDefaultOcrConfig(row.id)
  ElMessage.success('已设置默认 OCR 配置')
  await loadData()
}

const removeConfig = async (row) => {
  await ElMessageBox.confirm(`确定删除“${row.name}”吗？`, '删除 OCR 配置', { type: 'warning' })
  await deleteOcrConfig(row.id)
  ElMessage.success('已删除')
  await loadData()
}

onMounted(loadData)
</script>

<style scoped>
.ocr-config-page {
  width: 100%;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: 0;
}

.page-header p {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.installation-alert {
  margin-bottom: 16px;
}

.default-tag {
  margin-left: 6px;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
  }
}
</style>
