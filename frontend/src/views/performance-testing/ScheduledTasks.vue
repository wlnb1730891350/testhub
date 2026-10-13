<template>
  <div class="perf-page">
    <div class="page-header">
      <h2>性能定时任务</h2>
      <div>
        <el-button :icon="Refresh" @click="loadSchedules">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openDialog">新建任务</el-button>
      </div>
    </div>

    <el-table :data="schedules" v-loading="loading">
      <el-table-column prop="name" label="任务名称" min-width="180" />
      <el-table-column prop="target_name" label="脚本" min-width="180" />
      <el-table-column prop="schedule_type_display" label="类型" width="100" />
      <el-table-column prop="next_run_display" label="下次运行" min-width="180" />
      <el-table-column prop="last_run_display" label="上次运行" min-width="180" />
      <el-table-column prop="status_display" label="状态" width="100" />
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="executeSchedule(row)">立即执行</el-button>
          <el-button link type="danger" @click="removeSchedule(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建性能定时任务" width="560px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="任务名称" required>
          <el-input v-model.trim="form.name" />
        </el-form-item>
        <el-form-item label="性能脚本" required>
          <el-select v-model="form.target_id" filterable style="width: 100%" @change="syncProject">
            <el-option v-for="script in scripts" :key="script.id" :label="script.name" :value="script.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度类型">
          <el-select v-model="form.schedule_type" style="width: 100%">
            <el-option label="单次" value="O" />
            <el-option label="分钟间隔" value="I" />
            <el-option label="Cron" value="C" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.schedule_type === 'I'" label="间隔分钟">
          <el-input-number v-model="form.minutes" :min="1" />
        </el-form-item>
        <el-form-item v-if="form.schedule_type === 'C'" label="Cron">
          <el-input v-model.trim="form.cron" placeholder="*/30 * * * *" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSchedule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  createSchedulerSchedule,
  deleteSchedulerSchedule,
  executeSchedulerSchedule,
  getPerformanceScripts,
  getSchedulerSchedules,
} from '@/api/performance-testing'

const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const schedules = ref([])
const scripts = ref([])
const form = ref({})

const blankForm = () => ({
  name: '',
  module: 'PERFORMANCE',
  task_type: 'PERFORMANCE_SCRIPT',
  target_id: null,
  project_id: null,
  schedule_type: 'O',
  repeats: -1,
  minutes: 5,
  cron: '',
  description: '',
  notify_on_failure: true,
})

const loadSchedules = async () => {
  loading.value = true
  try {
    const { data } = await getSchedulerSchedules({ page_size: 1000 })
    const rows = data.results || data
    schedules.value = rows.filter((item) => item.config?.module === 'PERFORMANCE')
  } finally {
    loading.value = false
  }
}

const loadScripts = async () => {
  const { data } = await getPerformanceScripts({ page_size: 1000 })
  scripts.value = data.results || data
}

const openDialog = () => {
  form.value = blankForm()
  dialogVisible.value = true
}

const syncProject = () => {
  const script = scripts.value.find((item) => item.id === form.value.target_id)
  form.value.project_id = script?.project || null
}

const saveSchedule = async () => {
  if (!form.value.name || !form.value.target_id) {
    ElMessage.warning('请填写任务名称并选择脚本')
    return
  }
  saving.value = true
  try {
    await createSchedulerSchedule(form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    await loadSchedules()
  } finally {
    saving.value = false
  }
}

const executeSchedule = async (row) => {
  await executeSchedulerSchedule(row.id)
  ElMessage.success('已提交执行')
}

const removeSchedule = async (row) => {
  await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, '提示', { type: 'warning' })
  await deleteSchedulerSchedule(row.id)
  ElMessage.success('删除成功')
  await loadSchedules()
}

onMounted(async () => {
  await loadScripts()
  await loadSchedules()
})
</script>

<style scoped lang="scss">
.perf-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

  h2 {
    margin: 0;
  }
}
</style>
